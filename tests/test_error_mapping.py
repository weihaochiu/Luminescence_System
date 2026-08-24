from __future__ import annotations

from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from core.error_registry import default_error_registry
from gui.camera_auto_exposure_settings_dialog import CameraAutoExposureSettingsDialog
from gui.main_window_devices import MainWindowDeviceMixin


class ErrorConditionMappingTests(unittest.TestCase):
    def test_connected_camera_without_frame_is_not_reported_as_no_selection(self) -> None:
        dummy = SimpleNamespace(
            controller=SimpleNamespace(is_open=True),
            last_image=None,
            report_error=Mock(),
        )
        MainWindowDeviceMixin.capture_current_frame(dummy)
        dummy.report_error.assert_called_once_with(
            "CAM-102",
            context={"operation": "capture_current_frame"},
        )
        self.assertEqual(
            "errors.CAM-102.title",
            default_error_registry.require("CAM-102").title_key,
        )

    def test_disconnected_camera_still_uses_no_camera_selected_condition(self) -> None:
        dummy = SimpleNamespace(
            controller=SimpleNamespace(is_open=False),
            last_image=None,
            report_error=Mock(),
        )
        MainWindowDeviceMixin.capture_current_frame(dummy)
        dummy.report_error.assert_called_once_with(
            "CAM-101",
            context={"operation": "capture_current_frame"},
        )

    def test_measurement_guard_is_not_camera_acquisition_failure(self) -> None:
        dummy = SimpleNamespace(_measurement_running=lambda: True)
        with patch(
            "gui.camera_auto_exposure_settings_dialog.report_error"
        ) as reported:
            CameraAutoExposureSettingsDialog._run_calibration(dummy)
        self.assertEqual("UI-101", reported.call_args.args[1])
        self.assertNotEqual("CAM-202", reported.call_args.args[1])


if __name__ == "__main__":
    unittest.main()
