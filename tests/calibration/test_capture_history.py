from __future__ import annotations

import csv
import json
from pathlib import Path
import tempfile
import unittest

import numpy as np
import tifffile

from core.calibration.models import CalibrationResult, RulerDetection
from tools.ruler_scale_calibration_tester.capture_history import (
    CaptureHistoryStore,
    analyze_camera_capture,
)
from tools.ruler_scale_calibration_tester.source import AnalysisSource


class _ResultService:
    def __init__(self, *, success: bool) -> None:
        self.success = success

    def analyze(self, frame: np.ndarray, **kwargs: object) -> CalibrationResult:
        result = CalibrationResult(
            success=self.success,
            timestamp="2026-08-26T13:00:01+08:00",
            algorithm_version="capture-history-test",
            source_type="camera",
            source_identity=str(kwargs["source_identity"]),
            source_display_name=str(kwargs["source_display_name"]),
            captured_frame_sequence=int(kwargs["captured_frame_sequence"]),
            input_dtype=str(frame.dtype),
            input_resolution=(frame.shape[1], frame.shape[0]),
            input_min=int(frame.min()),
            input_max=int(frame.max()),
            ruler_detection=RulerDetection(
                success=True,
                polygon=[(0.0, 0.0), (7.0, 0.0), (7.0, 5.0), (0.0, 5.0)],
                angle_deg=0.0,
                confidence=0.9,
            ),
            ruler_angle_deg=0.0,
            verification_mode=("tick_hierarchy_verified" if self.success else "unverified"),
            pixels_per_mm=20.0 if self.success else None,
            um_per_pixel=50.0 if self.success else None,
            quality_score=91.0 if self.success else 12.0,
            quality_label="PASS" if self.success else "FAIL",
            failure_reasons=[] if self.success else ["ticks_not_detected"],
        )
        result.debug_images = {
            "final_overlay": np.zeros((6, 8, 3), dtype=np.uint8),
            "ticks_overlay": np.zeros((6, 8, 3), dtype=np.uint8),
            "ruler_candidates": np.zeros((6, 8, 3), dtype=np.uint8),
            "rectified": np.zeros((6, 8), dtype=np.uint8),
            "threshold": np.zeros((6, 8), dtype=np.uint8),
            "edges": np.zeros((6, 8), dtype=np.uint8),
            "ocr_overlay": np.zeros((6, 8, 3), dtype=np.uint8),
        }
        return result


class _RaisingService:
    def analyze(self, frame: np.ndarray, **kwargs: object) -> CalibrationResult:
        raise RuntimeError("intentional analysis failure")


class CaptureHistoryTests(unittest.TestCase):
    @staticmethod
    def source() -> AnalysisSource:
        return AnalysisSource(
            source_type="camera",
            source_identity="camera|RisingCam|frame=4821|captured=test",
            frame_sequence=4821,
            display_name="RisingCam frame 4821",
            capture_timestamp="2026-08-26T13:00:00.123+08:00",
            acquisition_metadata={
                "ExposureReadbackUs": 2500,
                "GainReadback": 100,
                "SDKAutoExposureEnabled": False,
                "AutoExposureMode": "manual",
                "SDKAutoExposureTargetReadback": None,
                "SensorBitDepth": 12,
                "RawValueAlignment": "right",
                "EffectiveDNMax": 4095,
                "CameraTemperatureC": None,
            },
        )

    def test_pass_fail_exception_exact_uint16_manifest_and_collision(self) -> None:
        raw = np.arange(48, dtype=np.uint16).reshape(6, 8) * 911
        raw[2, 3] = 65535
        with tempfile.TemporaryDirectory() as directory:
            store = CaptureHistoryStore(Path(directory) / "history")
            passed = analyze_camera_capture(_ResultService(success=True), store, raw, self.source())
            failed = analyze_camera_capture(_ResultService(success=False), store, raw, self.source())
            raised = analyze_camera_capture(_RaisingService(), store, raw, self.source())

            self.assertNotEqual(passed.capture_id, failed.capture_id)
            self.assertNotEqual(failed.capture_id, raised.capture_id)
            self.assertTrue(passed.capture_id.endswith("frame_004821"))
            self.assertTrue(failed.capture_id.endswith("frame_004821_01"))
            self.assertTrue(raised.capture_id.endswith("frame_004821_02"))

            for outcome in (passed, failed, raised):
                self.assertIsNotNone(outcome.capture_directory)
                capture_root = outcome.capture_directory
                assert capture_root is not None
                exact = tifffile.imread(capture_root / "raw_input.tiff")
                self.assertEqual(np.uint16, exact.dtype)
                self.assertTrue(np.array_equal(raw, exact))
                self.assertTrue((capture_root / "preview.png").is_file())
                self.assertTrue((capture_root / "result.json").is_file())

            passed_json = json.loads(
                (passed.capture_directory / "result.json").read_text(encoding="utf-8")
            )
            self.assertTrue(passed_json["success"])
            self.assertEqual(65535, passed_json["input_max"])
            self.assertEqual("capture-history-test", passed_json["algorithm_version"])
            self.assertTrue((passed.capture_directory / "final_overlay.png").is_file())
            acquisition = passed_json["camera_acquisition"]
            self.assertEqual(2500, acquisition["camera_exposure_us"])
            self.assertEqual(100, acquisition["camera_gain"])
            self.assertFalse(acquisition["auto_exposure_enabled"])
            self.assertEqual("manual", acquisition["auto_exposure_mode"])
            self.assertIsNone(acquisition["auto_exposure_target"])
            self.assertEqual(12, acquisition["sensor_bit_depth"])
            self.assertEqual("right", acquisition["raw_value_alignment"])
            self.assertEqual(4095, acquisition["effective_dn_max"])
            self.assertIsNone(acquisition["camera_temperature_c"])
            self.assertFalse(acquisition["availability"]["camera_temperature_c"])

            failed_json = json.loads(
                (failed.capture_directory / "result.json").read_text(encoding="utf-8")
            )
            self.assertFalse(failed_json["success"])
            self.assertEqual(["ticks_not_detected"], failed_json["failure_reasons"])

            raised_json = json.loads(
                (raised.capture_directory / "result.json").read_text(encoding="utf-8")
            )
            self.assertFalse(raised_json["success"])
            self.assertEqual(["analysis_exception"], raised_json["failure_reasons"])
            self.assertIn("intentional analysis failure", raised_json["analysis_exception"])

            with (store.root / "manifest.csv").open(
                "r", encoding="utf-8-sig", newline=""
            ) as stream:
                rows = list(csv.DictReader(stream))
            self.assertEqual(3, len(rows))
            self.assertEqual(["PASS", "FAIL", "FAIL"], [row["result"] for row in rows])
            self.assertEqual(
                str(passed.capture_directory.resolve()), rows[0]["directory"]
            )
            self.assertEqual(3, store.statistics().count)

    def test_default_history_root_is_project_anchored(self) -> None:
        root = CaptureHistoryStore().root
        self.assertTrue(root.is_absolute())
        self.assertEqual("ruler_capture_history", root.name)
        self.assertEqual("local", root.parent.name)

    def test_unavailable_camera_metadata_is_explicit_null(self) -> None:
        source = AnalysisSource(
            source_type="camera",
            source_identity="camera|unknown",
            frame_sequence=1,
            display_name="Unknown camera",
            capture_timestamp="2026-08-26T13:00:00.123+08:00",
        )
        with tempfile.TemporaryDirectory() as directory:
            store = CaptureHistoryStore(Path(directory) / "history")
            pending = store.begin_capture(np.zeros((2, 3), dtype=np.uint16), source)
            payload = json.loads(
                (pending.directory / "result.json").read_text(encoding="utf-8")
            )["camera_acquisition"]
        for key in (
            "camera_exposure_us",
            "camera_gain",
            "auto_exposure_enabled",
            "auto_exposure_mode",
            "auto_exposure_target",
            "sensor_bit_depth",
            "raw_value_alignment",
            "effective_dn_max",
            "camera_temperature_c",
        ):
            self.assertIn(key, payload)
            self.assertIsNone(payload[key])
            self.assertFalse(payload["availability"][key])


if __name__ == "__main__":
    unittest.main()
