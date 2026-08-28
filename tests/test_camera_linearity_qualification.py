from __future__ import annotations

import json
from pathlib import Path
import tempfile
from threading import Event
import unittest

import numpy as np
import tifffile
from PIL import Image

from tools.camera_linearity_qualification.analysis import (
    CameraLinearityAnalyzer, dark_correct, _compression_index,
)
from tools.camera_linearity_qualification.capture_manifest import (
    CaptureManifest, atomic_write_json, sha256_file,
)
from tools.camera_linearity_qualification.capture_plan import (
    FULL_EXPOSURES_MS, FULL_GAINS, build_capture_plan, capture_timeout_s,
)
from tools.camera_linearity_qualification.capture_runner import (
    AcquiredFrame, CaptureCancelled, CaptureRunner,
)
from tools.camera_linearity_qualification.image_loader import effective_array, load_folder
from tools.camera_linearity_qualification.models import (
    CaptureCondition, CapturePlan, FrameType, QualificationResult, ROI, RunMode,
)
from tools.camera_linearity_qualification.profile import build_profile
from tools.camera_linearity_qualification.regression import is_monotonic, linear_regression
from tools.camera_linearity_qualification.settings import QualificationCriteria


class FakeCamera:
    def __init__(self, *, mismatch: bool = False, stale: bool = False, cancel_after: int | None = None) -> None:
        self.state = {"ExposureReadbackUs": 1234, "GainReadback": 150, "AutoExposureMode": "continuous"}
        self.restored: list[dict[str, object]] = []
        self.closed = False; self.sequence = 10; self.calls: list[tuple[float, int, int, float]] = []
        self.mismatch = mismatch; self.stale = stale; self.cancel_after = cancel_after

    def snapshot_state(self) -> dict[str, object]: return dict(self.state)

    def capture(self, exposure_ms: float, gain_percent: int, settling_frames: int, timeout_s: float, check_cancel):
        self.calls.append((exposure_ms, gain_percent, settling_frames, timeout_s))
        if self.cancel_after is not None and len(self.calls) > self.cancel_after:
            raise CaptureCancelled("cancelled")
        check_cancel()
        if not self.stale or len(self.calls) == 1: self.sequence += 1
        value = min(3500, round(10 + exposure_ms * gain_percent / 1000.0))
        array = np.full((12, 16), value, dtype=np.uint16)
        metadata = {
            "ScientificMeasurementReady": True, "EffectiveDNMax": 4095,
            "SensorBitDepth": 12, "RawValueAlignment": "right", "PixelFormat": "MONO16",
            "ExposureReadbackUs": exposure_ms * 1000 + (1000 if self.mismatch else 0),
            "GainReadback": gain_percent, "CameraModel": "Fake", "CameraSerial": "F001",
        }
        return AcquiredFrame(array, metadata, self.sequence, "2026-08-28T12:00:00+08:00", 30.0)

    def restore_state(self, state: dict[str, object]) -> None: self.restored.append(dict(state))
    def close(self) -> None: self.closed = True


def write_synthetic_dataset(
    root: Path,
    *,
    gains: tuple[int, ...] = (100,),
    exposures: tuple[float, ...] = (50, 100, 200, 500, 1000, 2000, 5000),
    repeats: int = 5,
    dark_repeats: int = 5,
    compressed: bool = False,
    stale_first: bool = False,
    noisy: bool = False,
    alignment: str = "right",
) -> None:
    rng = np.random.default_rng(17); sequence = 0
    roi = {"x": 0, "y": 0, "width": 20, "height": 16}
    for gain in gains:
        for exposure in exposures:
            signal = exposure * 0.30 * (gain / 100)
            if compressed and exposure >= 200: signal = 60 + (exposure - 200) * 0.003
            for frame_type, count in (("LIGHT", repeats), ("DARK", dark_repeats)):
                for repeat in range(1, count + 1):
                    sequence += 1
                    base = 10.0 if frame_type == "DARK" else 10.0 + signal
                    sigma = 1.0 if not noisy else max(20.0, signal * .25)
                    if stale_first and frame_type == "LIGHT" and repeat == 1 and exposure > exposures[0]:
                        base = 10.0 + exposures[exposures.index(exposure) - 1] * .30 * (gain / 100)
                    array = np.clip(np.rint(rng.normal(base, sigma, (16, 20))), 0, 4095).astype(np.uint16)
                    stored = np.left_shift(array, 4) if alignment == "left" else array
                    folder = root / frame_type / f"G{gain}" / f"E{exposure:05.0f}ms"; folder.mkdir(parents=True, exist_ok=True)
                    stem = f"{frame_type}_G{gain}_E{exposure:05.0f}ms_R{repeat:02d}_SEQ{sequence:06d}"
                    tiff = folder / f"{stem}.tiff"; tifffile.imwrite(tiff, stored)
                    payload = {
                        "schema_version": "1.0.0", "frame_type": frame_type,
                        "CameraModel": "SyntheticLinear", "CameraSerial": "SYNTHETIC",
                        "PixelFormat": "MONO16", "SensorBitDepth": 12,
                        "EffectiveDNMax": 4095, "RawValueAlignment": alignment, "ROI": roi,
                        "requested_exposure_ms": exposure, "actual_exposure_ms": exposure,
                        "requested_gain_percent": gain, "actual_gain_percent": gain,
                        "repeat_index": repeat, "frame_sequence": sequence,
                        "CameraTemperatureC": 30.0 + sequence * .001,
                    }
                    payload["tiff_sha256"] = sha256_file(tiff)
                    atomic_write_json(tiff.with_suffix(".json"), payload)


class CapturePlanTests(unittest.TestCase):
    def test_full_matrix_generation_and_count(self) -> None:
        plan = build_capture_plan(RunMode.FULL)
        self.assertEqual(45, len(plan.conditions)); self.assertEqual(450, plan.planned_frame_count)
        self.assertEqual(tuple(FULL_GAINS), tuple(dict.fromkeys(item.gain_percent for item in plan.conditions)))
        self.assertEqual(tuple(float(item) for item in FULL_EXPOSURES_MS), tuple(item.exposure_ms for item in plan.conditions[:9]))

    def test_pilot_matrix(self) -> None:
        plan = build_capture_plan(RunMode.PILOT)
        self.assertEqual(9, len(plan.conditions)); self.assertEqual(27, plan.planned_frame_count); self.assertEqual(0, plan.dark_repeats)

    def test_quick_verification_uses_profile_limits(self) -> None:
        plan = build_capture_plan(RunMode.QUICK, profile={"recommended_exposure_limits": {"minimum_ms": 100, "maximum_ms": 10000}})
        self.assertEqual(6, len(plan.conditions)); self.assertEqual(36, plan.planned_frame_count)
        self.assertEqual(100.0, plan.conditions[0].exposure_ms); self.assertEqual(10000.0, plan.conditions[-1].exposure_ms)

    def test_timeout_for_15_second_exposure(self) -> None:
        self.assertGreaterEqual(capture_timeout_s(15000, 2), 67.5)


class CaptureRunnerTests(unittest.TestCase):
    def test_setting_readback_mismatch_restores_state(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            camera = FakeCamera(mismatch=True); plan = CapturePlan(RunMode.PILOT, (CaptureCondition(100, 50),), 1, 0, 2)
            with self.assertRaisesRegex(RuntimeError, "readback mismatch"):
                CaptureRunner(camera, plan, temporary, ROI(0, 0, 16, 12)).run()
            self.assertEqual([camera.state], camera.restored)

    def test_settling_frames_are_delegated_and_tiff_sidecar_pair(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            camera = FakeCamera(); plan = CapturePlan(RunMode.PILOT, (CaptureCondition(100, 50),), 1, 0, 3)
            result = CaptureRunner(camera, plan, temporary, ROI(0, 0, 16, 12)).run()
            self.assertEqual(3, camera.calls[0][2]); tiffs = list(result.session_dir.rglob("*.tiff")); self.assertEqual(1, len(tiffs)); self.assertTrue(tiffs[0].with_suffix(".json").exists())
            sidecar = json.loads(tiffs[0].with_suffix(".json").read_text(encoding="utf-8")); self.assertEqual(sha256_file(tiffs[0]), sidecar["tiff_sha256"])

    def test_stale_frame_sequence_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            camera = FakeCamera(stale=True); plan = CapturePlan(RunMode.PILOT, (CaptureCondition(100, 50), CaptureCondition(100, 100)), 1, 0, 0)
            with self.assertRaisesRegex(RuntimeError, "Stale"):
                CaptureRunner(camera, plan, temporary, ROI(0, 0, 16, 12)).run()

    def test_safe_cancellation_and_state_restoration(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            cancel = Event(); cancel.set(); camera = FakeCamera(); plan = CapturePlan(RunMode.PILOT, (CaptureCondition(100, 50),), 1, 0, 0)
            result = CaptureRunner(camera, plan, temporary, ROI(0, 0, 16, 12), cancel_event=cancel).run()
            self.assertTrue(result.cancelled); self.assertEqual([camera.state], camera.restored)

    def test_light_dark_two_phase_and_matching_metadata(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            camera = FakeCamera(); phases=[]; plan = CapturePlan(RunMode.QUICK, (CaptureCondition(100, 50),), 1, 1, 0)
            result = CaptureRunner(camera, plan, temporary, ROI(0, 0, 16, 12), confirm_phase=lambda phase,payload: phases.append(phase) or True).run()
            self.assertIn("LIGHT", phases); self.assertIn("DARK", phases)
            dark = next(result.session_dir.rglob("DARK_*.json")); payload=json.loads(dark.read_text(encoding="utf-8")); self.assertEqual("DARK",payload["frame_type"]); self.assertEqual(100,payload["MatchingGain"]); self.assertEqual(50,payload["MatchingExposure"])

    def test_adaptive_early_stop_records_skipped_conditions(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            camera=FakeCamera(); plan=CapturePlan(RunMode.PILOT,(CaptureCondition(100,50),CaptureCondition(100,100),CaptureCondition(100,200)),1,0,0,True)
            criteria=QualificationCriteria(early_stop_median_dn=1,early_stop_consecutive=2)
            result=CaptureRunner(camera,plan,temporary,ROI(0,0,16,12),criteria=criteria).run()
            self.assertEqual((CaptureCondition(100,200),),result.skipped_conditions)
            manifest=json.loads((result.session_dir/"capture_manifest.json").read_text(encoding="utf-8")); self.assertEqual("ADAPTIVE_EARLY_STOP",manifest["skipped_conditions"][0]["trigger"])

    def test_synthetic_capture_then_analyze_workflow(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            camera=FakeCamera(); plan=CapturePlan(RunMode.QUICK,(CaptureCondition(100,50),CaptureCondition(100,100)),3,3,0,False)
            result=CaptureRunner(camera,plan,temporary,ROI(0,0,16,12),confirm_phase=lambda phase,payload: True).run()
            outcome=CameraLinearityAnalyzer().analyze_folder(result.session_dir,mode=RunMode.QUICK,full_frame_confirmed=True)
            self.assertTrue((result.session_dir/"ANALYSIS"/"CAMERA_LINEARITY_REPORT.md").exists()); self.assertFalse(outcome.profile["profile_usable_for_production"])


class IOAndRawTests(unittest.TestCase):
    def test_manifest_atomic_write(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            path=Path(temporary)/"manifest.json"; manifest=CaptureManifest(path,"abc","pilot"); manifest.add_event("TEST","ok")
            self.assertEqual("ok",json.loads(path.read_text(encoding="utf-8"))["events"][0]["detail"]); self.assertFalse(list(path.parent.glob("*.tmp")))

    def test_roi_validation(self) -> None:
        ROI(0,0,10,10).validate(10,10)
        with self.assertRaises(ValueError): ROI(9,9,2,2).validate(10,10)

    def test_uint16_raw12_right_and_left_alignment(self) -> None:
        for alignment in ("right","left"):
            with self.subTest(alignment=alignment), tempfile.TemporaryDirectory() as temporary:
                root=Path(temporary); write_synthetic_dataset(root,exposures=(50,),repeats=1,dark_repeats=0,alignment=alignment)
                frames,errors=load_folder(root); self.assertFalse(errors); converted=effective_array(frames[0]); self.assertEqual(np.uint16,converted.dtype); self.assertLessEqual(int(converted.max()),4095)

    def test_unknown_alignment_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root=Path(temporary); write_synthetic_dataset(root,exposures=(50,),repeats=1,dark_repeats=0); sidecar=next(root.rglob("*.json")); payload=json.loads(sidecar.read_text()); payload["RawValueAlignment"]="unknown"; atomic_write_json(sidecar,payload)
            frames,_=load_folder(root)
            with self.assertRaises(ValueError): effective_array(frames[0])

    def test_dark_correction_preserves_negatives(self) -> None:
        corrected=dark_correct(np.array([[2]],dtype=np.uint16),np.array([[5]],dtype=np.uint16)); self.assertEqual(-3.0,float(corrected[0,0])); self.assertEqual(np.float32,corrected.dtype)


class NumericalAnalysisTests(unittest.TestCase):
    def test_regression_metrics(self) -> None:
        result=linear_regression(np.arange(1,7),np.arange(1,7)*3+2); self.assertAlmostEqual(3,result.slope); self.assertGreaterEqual(result.r2,.999999); self.assertLess(result.max_absolute_residual_percent,1e-9)

    def test_residual_threshold_classification_and_monotonicity(self) -> None:
        self.assertTrue(is_monotonic(np.array([1,2,2,3]))); self.assertFalse(is_monotonic(np.array([1,3,2])))

    def test_compression_detection(self) -> None:
        exposures=np.array([1,2,3,4,5,6],float); values=np.array([10,20,30,39,43,45],float); self.assertIsNotNone(_compression_index(exposures,values,.8))

    def test_dark_preview_validation(self) -> None:
        analyzer=CameraLinearityAnalyzer(); self.assertEqual((True,"Dark preview accepted"),analyzer.validate_dark_preview(10,1000)); self.assertFalse(analyzer.validate_dark_preview(500,1000)[0])

    def test_pilot_readiness(self) -> None:
        analyzer=CameraLinearityAnalyzer(); self.assertEqual("SUITABLE FOR FULL QUALIFICATION",analyzer.pilot_readiness([50,300,500,1000,1500,2500])); self.assertEqual("LIGHT TOO DIM",analyzer.pilot_readiness([5,10,20]))


class SyntheticEndToEndTests(unittest.TestCase):
    def test_synthetic_linear_camera_pass_but_not_production_usable(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root=Path(temporary)/"dataset"; write_synthetic_dataset(root)
            outcome=CameraLinearityAnalyzer().analyze_folder(root,synthetic=True,full_frame_confirmed=True)
            self.assertEqual(QualificationResult.PASS,outcome.overall); self.assertFalse(outcome.profile["profile_usable_for_production"])
            required=("CAMERA_LINEARITY_REPORT.md","analysis_summary.json","camera_linearity_profile.json","dataset_inventory.csv","image_statistics.csv","dark_statistics.csv","exposure_linearity_summary.csv","exposure_linearity_points.csv","gain_response.csv","repeatability.csv","acquisition_transition_anomalies.csv","usable_dynamic_range.csv","exposure_gap_analysis.csv","recommended_camera_settings.csv","qualification_results.csv","ROI_overlay.png")
            for name in required: self.assertTrue((root/"ANALYSIS"/name).exists(),name)
            json.loads((root/"ANALYSIS"/"analysis_summary.json").read_text(encoding="utf-8"))
            Image.open(root/"ANALYSIS"/"ROI_overlay.png").verify()
            plots=("dark_corrected_dn_vs_exposure.png","regression_residual.png","dn_per_exposure_stability.png","gain_response.png","temporal_repeatability.png","dark_dn_vs_exposure.png","dark_dn_vs_temperature.png","saturation_compression.png","exposure_gap_consistency.png","condition_heatmaps.png","representative_roi_preview.png")
            for name in plots:
                path=root/"ANALYSIS"/"plots"/name; self.assertTrue(path.exists(),name); Image.open(path).verify()

    def test_synthetic_compressed_camera_fails(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root=Path(temporary); write_synthetic_dataset(root,compressed=True)
            outcome=CameraLinearityAnalyzer().analyze_folder(root,synthetic=True,full_frame_confirmed=True); self.assertEqual(QualificationResult.FAIL,outcome.overall)

    def test_synthetic_stale_first_frame_fails(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root=Path(temporary); write_synthetic_dataset(root,stale_first=True)
            outcome=CameraLinearityAnalyzer().analyze_folder(root,synthetic=True,full_frame_confirmed=True); self.assertNotEqual(QualificationResult.PASS,outcome.overall); self.assertTrue(outcome.tables["acquisition_transition_anomalies"])

    def test_synthetic_missing_dark_is_conditional(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root=Path(temporary); write_synthetic_dataset(root,dark_repeats=0)
            outcome=CameraLinearityAnalyzer().analyze_folder(root,synthetic=True,full_frame_confirmed=True); self.assertEqual(QualificationResult.CONDITIONAL_PASS,outcome.overall); self.assertFalse(outcome.profile["profile_usable_for_production"])

    def test_synthetic_noisy_camera_fails(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root=Path(temporary); write_synthetic_dataset(root,noisy=True)
            outcome=CameraLinearityAnalyzer().analyze_folder(root,synthetic=True,full_frame_confirmed=True); self.assertEqual(QualificationResult.FAIL,outcome.overall)

    def test_hdr_exposure_gap_and_gain_response_outputs(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root=Path(temporary); write_synthetic_dataset(root,gains=(100,200))
            outcome=CameraLinearityAnalyzer().analyze_folder(root,synthetic=True,full_frame_confirmed=True)
            self.assertTrue(outcome.tables["exposure_gap_analysis"]); self.assertTrue(outcome.tables["gain_response"]); self.assertTrue(all(not row["physical_gain_linearity_claimed"] for row in outcome.tables["gain_response"]))

    def test_insufficient_repeats_downgrade_and_production_gate(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root=Path(temporary); write_synthetic_dataset(root,repeats=3,dark_repeats=3)
            outcome=CameraLinearityAnalyzer().analyze_folder(root,synthetic=False,full_frame_confirmed=True)
            self.assertEqual(QualificationResult.CONDITIONAL_PASS,outcome.overall); self.assertFalse(outcome.profile["profile_usable_for_production"])

    def test_synthetic_identity_cannot_bypass_production_gate(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root=Path(temporary); write_synthetic_dataset(root)
            outcome=CameraLinearityAnalyzer().analyze_folder(root,synthetic=False,full_frame_confirmed=True)
            self.assertEqual(QualificationResult.PASS,outcome.overall); self.assertFalse(outcome.profile["profile_usable_for_production"])

    def test_quick_verification_emits_required_status(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root=Path(temporary); write_synthetic_dataset(root,repeats=3,dark_repeats=3)
            outcome=CameraLinearityAnalyzer().analyze_folder(root,mode=RunMode.QUICK,full_frame_confirmed=True)
            self.assertEqual("PROFILE STILL VALID",outcome.summary["quick_verification_result"]); self.assertFalse(outcome.profile["profile_usable_for_production"])

    def test_reliable_window_and_saturation_columns_are_derived(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root=Path(temporary); write_synthetic_dataset(root)
            outcome=CameraLinearityAnalyzer().analyze_folder(root,full_frame_confirmed=True)
            gain=outcome.tables["exposure_linearity_summary"][0]
            self.assertGreaterEqual(gain["linear_point_count"],5); self.assertIsNotNone(gain["reliable_dn_low"]); self.assertIn("saturation_fraction",outcome.tables["exposure_linearity_points"][0])


if __name__ == "__main__":
    unittest.main()
