from __future__ import annotations

from dataclasses import replace
from datetime import datetime
from pathlib import Path
from threading import Event
import tempfile
import unittest

import numpy as np
from PySide6.QtGui import QImage

from core.calibration.acquisition_quality import (
    RulerAcquisitionMetrics,
    RulerAcquisitionQualityEvaluator,
    RulerCandidateQuality,
)
from core.calibration.models import CalibrationResult
from tools.ruler_scale_calibration_tester.capture_history import CaptureHistoryStore
from tools.ruler_scale_calibration_tester.ruler_auto_exposure import (
    AcquiredRulerFrame,
    CameraCaptureBridgeRulerAdapter,
    RulerAutoExposureDecisionEngine,
    RulerAutoExposureConfig,
    RulerAutoExposureRunner,
    RulerCameraLimits,
)
from gui.el_matrix_runner import CapturedFrame
from tools.ruler_scale_calibration_tester.exposure_sweep import (
    ControlledExposureSweepRunner,
)


def candidate(reliable: bool = True) -> RulerCandidateQuality:
    return RulerCandidateQuality(
        reliable=reliable,
        reasons=() if reliable else ("spacing_inconsistent_with_ruler",),
        confidence=0.9,
        periodicity_support=0.9,
        accepted_tick_count=30,
        spacing_fraction=0.02,
        parallel_edge_support=0.5,
        tick_comb_support=0.8,
        polygon_inside_fraction=1.0,
        angle_deg=10.0,
        polygon=((10.0, 10.0), (110.0, 10.0), (110.0, 30.0), (10.0, 30.0)),
        roi_area_fraction=0.1,
    )


def metrics(
    *,
    reliable: bool = True,
    ruler_sat: float = 0.02,
    tick_sat: float = 0.02,
    michelson: float = 0.65,
    normalized: float = 0.25,
    hierarchy: bool = True,
) -> RulerAcquisitionMetrics:
    return RulerAcquisitionMetrics(
        global_saturation_fraction=0.03,
        ruler_roi_saturation_fraction=ruler_sat,
        tick_band_saturation_fraction=tick_sat,
        normalized_tick_contrast=normalized,
        michelson_tick_contrast=michelson,
        accepted_tick_count=30,
        periodicity_support=0.9,
        hierarchy_verified=hierarchy,
        candidate=candidate(reliable),
    )


class DecisionEngineTests(unittest.TestCase):
    def setUp(self) -> None:
        self.engine = RulerAutoExposureDecisionEngine()
        self.limits = RulerCameraLimits(100, 10000, 100, 400)

    def decision(self, value: RulerAcquisitionMetrics, exposure: int = 1000, gain: int = 100):
        return self.engine.decide(
            value, exposure, gain, self.limits,
            candidate_retry_count=0, exposure_adjustment_count=0,
        )

    def test_high_clipping_decreases_exposure_and_never_gain(self) -> None:
        decision = self.decision(metrics(ruler_sat=0.60, tick_sat=0.70))
        self.assertEqual("reduce_exposure", decision.action)
        self.assertLess(decision.requested_exposure_us, 1000)
        self.assertEqual(100, decision.requested_gain)

    def test_low_clipping_weak_signal_increases_exposure(self) -> None:
        decision = self.decision(metrics(michelson=0.20, normalized=0.05))
        self.assertEqual("increase_exposure", decision.action)
        self.assertGreater(decision.requested_exposure_us, 1000)

    def test_exposure_max_low_signal_uses_bounded_gain_fallback(self) -> None:
        decision = self.decision(
            metrics(ruler_sat=0.01, tick_sat=0.01, michelson=0.20, normalized=0.05),
            exposure=10000,
        )
        self.assertEqual("increase_gain", decision.action)
        self.assertGreater(decision.requested_gain, 100)
        self.assertLessEqual(decision.requested_gain, 400)

    def test_two_stable_good_frames_can_converge(self) -> None:
        first = metrics()
        second = replace(first, global_saturation_fraction=0.031)
        self.assertEqual("hold_for_stability", self.decision(first).action)
        self.assertTrue(self.engine.stable(first, second))

    def test_max_adjustments_and_unreliable_candidate_fail_closed(self) -> None:
        limited = self.engine.decide(
            metrics(ruler_sat=0.7, tick_sat=0.7), 1000, 100, self.limits,
            candidate_retry_count=0,
            exposure_adjustment_count=self.engine.config.maximum_exposure_adjustments,
        )
        self.assertEqual("fail", limited.action)
        rejected = self.engine.decide(
            metrics(reliable=False), 1000, 100, self.limits,
            candidate_retry_count=self.engine.config.maximum_candidate_retries,
            exposure_adjustment_count=0,
        )
        self.assertEqual("fail", rejected.action)
        self.assertIn("ruler_candidate_unreliable", rejected.reason)


class CandidateQualityTests(unittest.TestCase):
    def test_left_aligned_raw_is_converted_only_for_quality_metrics(self) -> None:
        evaluator = RulerAcquisitionQualityEvaluator()
        result = CalibrationResult(success=False)
        right = np.asarray([[0, 4095], [1024, 2048]], dtype=np.uint16)
        left = np.left_shift(right, 4).astype(np.uint16)
        right_metrics = evaluator.evaluate(right, result, 4095, "right")
        left_metrics = evaluator.evaluate(left, result, 4095, "left")
        self.assertEqual(
            right_metrics.global_saturation_fraction,
            left_metrics.global_saturation_fraction,
        )
        self.assertEqual(65520, int(left.max()))

    def test_high_contrast_straight_fixture_edge_is_not_reliable_without_ticks(self) -> None:
        result = CalibrationResult(
            success=False,
            ruler_angle_deg=0.0,
            diagnostics={
                "rectified_resolution": [1000, 100],
                "ruler_candidates": [{
                    "selected": True,
                    "score": 0.99,
                    "periodicity": 1.0,
                    "contrast": 1.0,
                    "edge_support": 1.0,
                    "tick_comb_support": 0.0,
                    "area_fraction": 0.1,
                    "polygon": [[0, 40], [999, 40], [999, 60], [0, 60]],
                }],
            },
        )
        quality = RulerAcquisitionQualityEvaluator().evaluate_candidate(result, (500, 1000))
        self.assertFalse(quality.reliable)
        self.assertIn("accepted_ticks_insufficient", quality.reasons)
        self.assertIn("spacing_inconsistent_with_ruler", quality.reasons)

    def test_border_crossing_candidate_uses_clipped_area_not_vertex_count(self) -> None:
        quality = RulerAcquisitionQualityEvaluator._polygon_inside_fraction(
            ((-20.0, 10.0), (120.0, 10.0), (120.0, 90.0), (-20.0, 90.0)),
            100,
            100,
        )
        self.assertGreater(quality, 0.5)


class _Service:
    def analyze(self, frame: np.ndarray, **kwargs: object) -> CalibrationResult:
        return CalibrationResult(
            success=True,
            verification_mode="tick_hierarchy_verified",
            timestamp="2026-08-26T15:00:00+08:00",
            source_identity=str(kwargs.get("source_identity", "")),
            source_display_name=str(kwargs.get("source_display_name", "")),
            captured_frame_sequence=int(kwargs.get("captured_frame_sequence") or 1),
        )


class _RaisingService:
    def analyze(self, frame: np.ndarray, **kwargs: object) -> CalibrationResult:
        raise RuntimeError("analysis failed")


class _Evaluator:
    def __init__(self, values: list[RulerAcquisitionMetrics]) -> None:
        self.values = values
        self.index = 0

    def evaluate(
        self,
        raw: np.ndarray,
        result: CalibrationResult,
        maximum: int,
        alignment: str = "right",
    ):
        value = self.values[min(self.index, len(self.values) - 1)]
        self.index += 1
        return value


class _Camera:
    def __init__(self, *, raises: bool = False) -> None:
        self.raises = raises
        self.restored: list[dict[str, object]] = []
        self.captures = 0
        self.state = {
            "ExposureReadbackUs": 1000,
            "GainReadback": 150,
            "AutoExposureMode": "continuous",
        }

    def snapshot_state(self):
        return dict(self.state)

    def limits(self):
        return RulerCameraLimits(100, 10000, 100, 400)

    def capture(self, exposure_us: int, gain: int, settling_frames: int, check_cancel):
        check_cancel()
        if self.raises:
            raise RuntimeError("capture failed")
        self.captures += 1
        return AcquiredRulerFrame(
            np.zeros((20, 30), dtype=np.uint16),
            {
                "ExposureReadbackUs": exposure_us,
                "GainReadback": gain,
                "EffectiveDNMax": 4095,
                "RawValueAlignment": "right",
                "AutoExposureMode": "manual",
            },
            self.captures,
            f"2026-08-26T15:00:0{self.captures}+08:00",
        )

    def restore_state(self, state):
        self.restored.append(dict(state))


class RestorationTests(unittest.TestCase):
    def run_case(self, values, *, camera=None, cancel=None):
        with tempfile.TemporaryDirectory() as directory:
            runner = RulerAutoExposureRunner(
                _Service(),
                CaptureHistoryStore(Path(directory) / "history"),
                evaluator=_Evaluator(values),
            )
            camera = camera or _Camera()
            outcome = runner.run(camera, "fake", cancel)
            self.assertEqual(1, len(camera.restored))
            self.assertEqual(1000, camera.restored[0]["ExposureReadbackUs"])
            self.assertEqual(150, camera.restored[0]["GainReadback"])
            self.assertEqual("continuous", camera.restored[0]["AutoExposureMode"])
            return outcome

    def test_pass_fail_exception_and_cancel_restore_state(self) -> None:
        passed = self.run_case([metrics(), metrics()])
        self.assertTrue(passed.success)
        failed = self.run_case([metrics(reliable=False)] * 3)
        self.assertFalse(failed.success)
        raised = self.run_case([metrics()], camera=_Camera(raises=True))
        self.assertFalse(raised.success)
        cancel = Event(); cancel.set()
        cancelled = self.run_case([metrics()], cancel=cancel)
        self.assertFalse(cancelled.success)
        self.assertIn("ruler_auto_exposure_cancelled", cancelled.reason)

    def test_controlled_sweep_writes_local_style_csv_and_restores(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            camera = _Camera()
            runner = ControlledExposureSweepRunner(
                _Service(),
                evaluator=_Evaluator([metrics()]),
                output_root=directory,
            )
            output = runner.run(camera, "fake")
            rows = (output / "sweep_results.csv").read_text(encoding="utf-8-sig").splitlines()
            self.assertEqual(28, len(rows))  # header + 9 unique exposures * 3 repeats
            self.assertTrue((output / "summary.txt").is_file())
            self.assertEqual(1, len(camera.restored))

    def test_attempt_provenance_separates_current_and_next_request(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            camera = _Camera()
            runner = RulerAutoExposureRunner(
                _Service(),
                CaptureHistoryStore(Path(directory) / "history"),
                evaluator=_Evaluator([
                    metrics(ruler_sat=0.7, tick_sat=0.7),
                    metrics(),
                    metrics(),
                ]),
            )
            progress = []
            outcome = runner.run(camera, "fake", attempt_callback=progress.append)
            self.assertTrue(outcome.success)
            first = outcome.attempts[0]
            self.assertEqual(1000, first.requested_exposure_us)
            self.assertEqual(100, first.requested_gain)
            self.assertLess(first.next_requested_exposure_us, first.requested_exposure_us)
            self.assertEqual(outcome.attempts, progress)

    def test_total_attempt_limit_fails_and_restores(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            values = []
            for offset in (0.0, 30.0, 60.0):
                shifted = replace(candidate(), polygon=tuple(
                    (x + offset, y) for x, y in candidate().polygon
                ))
                values.append(replace(metrics(), candidate=shifted))
            camera = _Camera()
            engine = RulerAutoExposureDecisionEngine(
                RulerAutoExposureConfig(maximum_total_attempts=3)
            )
            runner = RulerAutoExposureRunner(
                _Service(),
                CaptureHistoryStore(Path(directory) / "history"),
                evaluator=_Evaluator(values),
                engine=engine,
            )
            outcome = runner.run(camera, "fake")
            self.assertFalse(outcome.success)
            self.assertEqual("maximum_total_attempts_reached", outcome.reason)
            self.assertEqual("fail", outcome.attempts[-1].decision)
            self.assertEqual(1, len(camera.restored))

    def test_analysis_exception_is_finalized_in_capture_history(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            history = CaptureHistoryStore(Path(directory) / "history")
            camera = _Camera()
            runner = RulerAutoExposureRunner(
                _RaisingService(),
                history,
                evaluator=_Evaluator([metrics()]),
            )
            outcome = runner.run(camera, "fake")
            self.assertFalse(outcome.success)
            self.assertEqual("analysis_exception", outcome.reason)
            result_files = list(history.root.rglob("result.json"))
            self.assertEqual(1, len(result_files))
            payload = result_files[0].read_text(encoding="utf-8")
            self.assertIn('"analysis_exception"', payload)
            self.assertNotIn('"analysis_pending"', payload)
            self.assertEqual(1, len(camera.restored))

    def test_formal_bridge_adapter_uses_camera_metadata_and_scientific_frame(self) -> None:
        class _Controller:
            is_open = True

        class _Bridge:
            controller = _Controller()

            def capture(self, exposure_ms, gain, timeout, check_cancel, **kwargs):
                return CapturedFrame(
                    QImage(3, 2, QImage.Format.Format_Grayscale8),
                    datetime.now().astimezone(),
                    38.5,
                    {
                        "ExposureReadbackUs": 2500,
                        "GainReadback": 100,
                        "FrameSequence": 7,
                        "EffectiveDNMax": 4095,
                        "RawValueAlignment": "right",
                    },
                    np.full((2, 3), 123, dtype=np.uint16),
                )

            def restore_state(self, state):
                pass

        adapter = CameraCaptureBridgeRulerAdapter(
            _Bridge(),
            {"ExposureReadbackUs": 2500, "GainReadback": 100},
        )
        acquired = adapter.capture(2500, 100, 0, lambda: None)
        self.assertEqual(np.uint16, acquired.raw.dtype)
        self.assertEqual(7, acquired.frame_sequence)
        self.assertEqual(38.5, acquired.metadata["CameraTemperatureC"])


if __name__ == "__main__":
    unittest.main()
