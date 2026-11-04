from __future__ import annotations

import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

import numpy as np

from gui.camera_ae_calibration import AECalibrationProfile, AECalibrationProfileStore
from gui.camera_controller import CameraStartupError
from gui.sdk import nncam
from tests.qt_test_utils import ensure_qapplication
from tests.test_camera_scientific import _FakeMonoCamera, _open


class RowOrderCamera(_FakeMonoCamera):
    """Model Windows bottom-up buffers independently of sensor coordinates."""

    sensor = np.array([[1601, 1617, 1633], [17, 33, 49]], dtype=np.uint16)

    def PullImageV4(self, *args):
        super().PullImageV4(*args)
        rows = self.sensor[::-1] if self.get_Option(nncam.NNCAM_OPTION_UPSIDE_DOWN) else self.sensor
        padded = np.zeros((2, self.owner._pitch // 2), dtype="<u2")
        padded[:, :3] = rows
        self.owner._buffer = padded.tobytes()

    def native_metering_dn(self):
        x, y, width, height = self.ae_aux_rect
        return float(self.sensor[y:y + height, x:x + width].mean())


class CameraRowOrderTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = ensure_qapplication()

    def test_windows_default_is_changed_before_stream_and_recorded_in_metadata(self):
        camera = _FakeMonoCamera()
        self.assertEqual(1, camera.get_Option(nncam.NNCAM_OPTION_UPSIDE_DOWN))
        original_start = camera.StartPullModeWithCallback

        def start(*args):
            self.assertEqual(0, camera.get_Option(nncam.NNCAM_OPTION_UPSIDE_DOWN))
            original_start(*args)

        with patch.object(camera, "StartPullModeWithCallback", new=start):
            controller, errors = _open(camera)
        try:
            self.assertTrue(controller.is_open, errors)
            metadata = controller.capture_metadata()
            self.assertEqual(0, metadata["SDKUpsideDownReadback"])
            self.assertEqual(1, metadata["SDKUpsideDownBeforeNormalization"])
            self.assertEqual("TopDown", metadata["ScientificRowOrder"])
        finally:
            controller.close_camera()

    def test_asymmetric_bright_top_roi_matches_sdk_and_scientific_measurement(self):
        camera = RowOrderCamera()
        controller, errors = _open(camera)
        camera.owner = controller
        frames = []
        controller.scientific_frame_ready.connect(lambda data, _image, _sequence: frames.append(data.copy()))
        try:
            self.assertTrue(controller.is_open, errors)
            self.assertTrue(controller.set_auto_exposure_roi(0, 0, 3, 1))
            controller._raw_value_alignment = "right"
            controller._pull_live_frame()
            np.testing.assert_array_equal(camera.sensor, frames[-1])
            self.assertEqual(1617.0, camera.native_metering_dn())
            self.assertEqual(camera.native_metering_dn(), controller._latest_metering_mean_effective_dn)
            self.assertNotEqual(float(camera.sensor[-1].mean()), controller._latest_metering_mean_effective_dn)
        finally:
            controller.close_camera()

    def test_unsupported_row_order_does_not_start_unverified_scientific_stream(self):
        camera = _FakeMonoCamera(unsupported_options={nncam.NNCAM_OPTION_UPSIDE_DOWN})
        controller, errors = _open(camera)
        try:
            self.assertFalse(controller.is_open)
            self.assertIn("NNCAM_OPTION_UPSIDE_DOWN=0", errors[0])
            self.assertEqual([], camera.stream_events)
        finally:
            controller.close_camera()

    def test_readback_mismatch_does_not_start_stream(self):
        camera = _FakeMonoCamera(readback_overrides={nncam.NNCAM_OPTION_UPSIDE_DOWN: 1})
        controller, errors = _open(camera)
        try:
            self.assertFalse(controller.is_open)
            self.assertIn("Top-down rows requested 0, read back 1", errors[0])
            self.assertEqual([], camera.stream_events)
        finally:
            controller.close_camera()

    def test_restart_rechecks_row_order_and_invalidates_previous_frame_readiness(self):
        camera = _FakeMonoCamera()
        controller, errors = _open(camera)
        try:
            self.assertTrue(controller.is_open, errors)
            controller._scientific_frame_validated = True
            camera.option_values[nncam.NNCAM_OPTION_UPSIDE_DOWN] = 1
            previous_starts = len(camera.stream_events)
            with self.assertRaisesRegex(CameraStartupError, "Top-down rows"):
                controller._start_stream()
            self.assertFalse(controller._scientific_frame_validated)
            self.assertEqual(previous_starts, len(camera.stream_events))
        finally:
            controller.close_camera()

    def test_previous_orientation_calibrations_are_ignored_without_rewriting_file(self):
        with TemporaryDirectory() as directory:
            path = Path(directory) / "calibration.json"
            original = json.dumps({"schema_version": 2, "profiles": [{"profile_id": "old"}]})
            path.write_text(original, encoding="utf-8")
            with patch.object(AECalibrationProfile, "from_dict") as parse:
                AECalibrationProfileStore(path)
            parse.assert_not_called()
            self.assertEqual(original, path.read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
