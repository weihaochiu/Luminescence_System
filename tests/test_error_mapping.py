from __future__ import annotations

from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from core.error_registry import default_error_registry
from gui.camera_auto_exposure_settings_dialog import CameraAutoExposureSettingsDialog
from gui.main_window_devices import MainWindowDeviceMixin
from gui.smu_base import SMUDevice, SMUDriver
from gui.smu_control import SMUControlManager, SMUErrorKind


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

    def test_structured_smu_condition_uses_fault_target_not_selected_device(self) -> None:
        faulted = SMUDevice(
            "USB0::A::INSTR",
            manufacturer="Keysight Technologies",
            model="B2901B",
            serial_number="SERIAL-A",
            idn="Keysight Technologies,B2901B,SERIAL-A,1.0",
            supported=True,
        )
        selected = SMUDevice(
            "USB0::B::INSTR",
            manufacturer="Keysight Technologies",
            model="B2901B",
            serial_number="SERIAL-B",
            idn="Keysight Technologies,B2901B,SERIAL-B,1.0",
            supported=True,
        )
        control = SMUControlManager()
        self.addCleanup(
            lambda: control.shutdown(safety_confirmed=True, force=True)
        )
        control.bind_driver(SMUDriver(object(), faulted), output_confirmed_off=True)
        control._latch_output_unknown("OUTPUT query failed")
        control.bind_driver(None, force=True)
        report_error = Mock()
        dummy = SimpleNamespace(
            status_message=SimpleNamespace(setText=Mock()),
            smu_manager=SimpleNamespace(
                is_connected=False,
                connected_device=None,
                control=control,
            ),
            device_panel=SimpleNamespace(
                selected_smu=lambda: selected,
                set_smu_disconnected=Mock(),
            ),
            report_error=report_error,
        )

        MainWindowDeviceMixin.show_smu_error(
            dummy,
            "localized wording may change",
            SMUErrorKind.OUTPUT_OFF_UNCONFIRMED,
        )

        self.assertEqual("SMU-203", report_error.call_args.args[0])
        context = report_error.call_args.kwargs["context"]
        self.assertEqual("USB0::A::INSTR", context["resource"])
        self.assertEqual("SERIAL-A", context["smu_serial_number"])
        self.assertEqual(
            SMUErrorKind.OUTPUT_OFF_UNCONFIRMED.value,
            context["smu_error_kind"],
        )


if __name__ == "__main__":
    unittest.main()
