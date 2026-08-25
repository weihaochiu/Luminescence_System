from __future__ import annotations

import unittest
from datetime import datetime
from types import SimpleNamespace
from unittest.mock import Mock, patch

from PySide6.QtTest import QSignalSpy, QTest

from core.i18n import configure_i18n
from gui.el_matrix_runner import MatrixRuntimeProgress
from gui.main_window_measurement import (
    _on_measurement_cancelled,
    _on_measurement_failed,
    _on_measurement_finished,
)
from gui.measurement_progress_dialog import (
    MeasurementProgressDialog,
    MeasurementProgressState,
)
from gui.pixel_csv_postprocessor import PixelCSVProgress
from gui.smu_control import SMUOwnership
from tests.qt_test_utils import ensure_qapplication


SAFE_SHUTDOWN = {
    "smu_output_off": True,
    "routing_off": True,
    "white_light_off": True,
    "ownership_released": True,
    "ok": True,
}


class MeasurementProgressDialogLifecycleTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.app = ensure_qapplication()

    def setUp(self) -> None:
        configure_i18n(None)
        self.dialogs: list[MeasurementProgressDialog] = []

    def tearDown(self) -> None:
        for dialog in self.dialogs:
            if dialog.ui_state in (
                MeasurementProgressState.RUNNING,
                MeasurementProgressState.STOPPING,
            ):
                dialog.set_stopped()
            dialog.close()
        self.app.processEvents()
        configure_i18n(None)

    def dialog(self) -> MeasurementProgressDialog:
        dialog = MeasurementProgressDialog("EL Matrix")
        self.dialogs.append(dialog)
        return dialog

    @staticmethod
    def window(dialog: MeasurementProgressDialog, *, emergency: bool = False):
        control = SimpleNamespace(
            ownership=SMUOwnership.IDLE,
            safe_shutdown=Mock(side_effect=AssertionError("duplicate safe shutdown")),
        )
        return SimpleNamespace(
            smu_manager=SimpleNamespace(control=control),
            emergency_manager=SimpleNamespace(is_active=emergency),
            relay_service=SimpleNamespace(
                safe_smu_output_channels_off=Mock(return_value=True),
                safe_white_light_off=Mock(return_value=True),
            ),
            status_message=SimpleNamespace(setText=Mock()),
            selected_recipe=SimpleNamespace(name="EL Matrix"),
            _measurement_progress_dialog=dialog,
            _measurement_hardware_active=True,
        )

    def test_official_success_enters_completed_and_auto_closes_without_shutdown(self) -> None:
        dialog = self.dialog()
        dialog.show()
        stops = QSignalSpy(dialog.stop_requested)
        window = self.window(dialog)

        _on_measurement_finished(window, {
            "hardware_measurement_completed": True,
            "safe_shutdown": SAFE_SHUTDOWN,
            "captures": 7,
            "postprocess": {"status": "completed", "total_files": 14},
        })

        self.assertEqual(MeasurementProgressState.COMPLETED, dialog.ui_state)
        self.assertEqual(7, dialog.progress_bar.maximum())
        self.assertEqual(7, dialog.progress_bar.value())
        self.assertEqual("100.0%", dialog.percent_value.text())
        self.assertEqual("00:00", dialog.remaining_time_value.text())
        self.assertIn("✓ 量測完成", dialog.phase_value.text())
        self.assertEqual("關閉", dialog.stop_button.text())
        self.assertTrue(dialog.auto_close_active)
        self.assertEqual(3000, dialog._auto_close_timer.interval())

        QTest.qWait(3200)
        self.assertFalse(dialog.isVisible())
        self.assertEqual(0, stops.count())
        window.smu_manager.control.safe_shutdown.assert_not_called()

    def test_manual_close_before_timer_is_idempotent(self) -> None:
        dialog = self.dialog()
        dialog.set_complete(2)
        stops = QSignalSpy(dialog.stop_requested)
        finished = QSignalSpy(dialog.finished)

        dialog.stop_button.click()
        self.app.processEvents()
        close_count = finished.count()
        self.assertFalse(dialog.isVisible())
        self.assertFalse(dialog.auto_close_active)

        dialog._auto_close_timer.timeout.emit()
        self.app.processEvents()
        self.assertEqual(close_count, finished.count())
        self.assertEqual(0, stops.count())

    def test_error_remains_visible_with_close_action_and_reason(self) -> None:
        dialog = self.dialog()
        dialog.show()
        window = self.window(dialog)
        with patch("gui.main_window_measurement.report_error"):
            _on_measurement_failed(window, "Camera capture failed")

        self.assertTrue(dialog.isVisible())
        self.assertEqual(MeasurementProgressState.ERROR, dialog.ui_state)
        self.assertFalse(dialog.auto_close_active)
        self.assertEqual("關閉", dialog.stop_button.text())
        self.assertIn("Camera capture failed", dialog.condition_value.text())
        window.smu_manager.control.safe_shutdown.assert_not_called()

    def test_manual_stop_transitions_through_stopping_and_does_not_auto_close(self) -> None:
        dialog = self.dialog()
        dialog.show()
        window = self.window(dialog)
        safe_stop = Mock()

        def request_safe_stop() -> None:
            safe_stop()
            window.smu_manager.control.ownership = SMUOwnership.IDLE

        dialog.stop_requested.connect(request_safe_stop)
        dialog.stop_button.click()
        self.assertEqual(MeasurementProgressState.STOPPING, dialog.ui_state)
        self.assertFalse(dialog.stop_button.isEnabled())

        _on_measurement_cancelled(window)
        self.assertEqual(1, safe_stop.call_count)
        self.assertTrue(dialog.isVisible())
        self.assertEqual(MeasurementProgressState.ABORTED, dialog.ui_state)
        self.assertFalse(dialog.auto_close_active)
        self.assertEqual("關閉", dialog.stop_button.text())
        self.assertIn("量測已停止", dialog.phase_value.text())

    def test_emergency_termination_remains_visible_and_never_completes(self) -> None:
        dialog = self.dialog()
        dialog.show()
        window = self.window(dialog, emergency=True)

        _on_measurement_finished(window, {
            "hardware_measurement_completed": True,
            "safe_shutdown": SAFE_SHUTDOWN,
            "captures": 3,
            "postprocess": {"status": "not_requested", "total_files": 0},
        })

        self.assertTrue(dialog.isVisible())
        self.assertEqual(MeasurementProgressState.ABORTED, dialog.ui_state)
        self.assertFalse(dialog.auto_close_active)
        self.assertIn("EMERGENCY STOP", dialog.phase_value.text())
        window.smu_manager.control.safe_shutdown.assert_not_called()

    def test_progress_100_does_not_start_auto_close_or_change_state(self) -> None:
        dialog = self.dialog()
        dialog.show()
        progress = MatrixRuntimeProgress(
            phase="Saving footer",
            current=4,
            total=4,
            channel="Ch1",
            sample_id="Sample-A",
            channel_index=1,
            channel_total=1,
            output_mode="voltage",
            commanded_voltage_v=1.2,
            gain_percent=10,
            exposure_ms=20.0,
            repeat_index=1,
            repeat_total=1,
            channel_completed=4,
            channel_capture_total=4,
            remaining_captures=0,
            remaining_time_s=0.0,
            estimated_finish=datetime.now().astimezone(),
        )
        dialog.update_progress(progress)

        self.assertEqual(dialog.progress_bar.maximum(), dialog.progress_bar.value())
        self.assertEqual("100.0%", dialog.percent_value.text())
        self.assertEqual(MeasurementProgressState.RUNNING, dialog.ui_state)
        self.assertFalse(dialog.auto_close_active)
        self.assertTrue(dialog.isVisible())

    def test_final_measurement_context_survives_postprocessing(self) -> None:
        dialog = self.dialog()
        dialog.update_progress(MatrixRuntimeProgress(
            phase="Capture",
            current=4,
            total=4,
            channel="Ch2",
            sample_id="Sample-B",
            channel_index=2,
            channel_total=2,
            output_mode="voltage",
            commanded_voltage_v=1.5,
            gain_percent=20,
            exposure_ms=30.0,
            repeat_index=1,
            repeat_total=1,
            channel_completed=2,
            channel_capture_total=2,
        ))
        expected = (
            dialog.channel_value.text(),
            dialog.sample_value.text(),
            dialog.condition_value.text(),
            dialog.channel_progress_value.text(),
        )
        dialog.update_postprocess_progress(PixelCSVProgress(
            current=5,
            total=10,
            percent=50.0,
            remaining_time_s=1.0,
            estimated_finish=None,
            message="Writing CSV",
        ))
        dialog.set_complete(4)

        self.assertEqual(expected, (
            dialog.channel_value.text(),
            dialog.sample_value.text(),
            dialog.condition_value.text(),
            dialog.channel_progress_value.text(),
        ))

    def test_close_event_preserves_running_behavior_and_terminal_close_is_ui_only(self) -> None:
        running = self.dialog()
        running_stops = QSignalSpy(running.stop_requested)
        running.show()
        running.close()
        self.app.processEvents()
        self.assertFalse(running.isVisible())
        self.assertEqual(MeasurementProgressState.RUNNING, running.ui_state)
        self.assertEqual(0, running_stops.count())

        transitions = (
            lambda item: item.set_complete(1),
            lambda item: item.set_failed("failure"),
            lambda item: item.set_stopped(),
        )
        for transition in transitions:
            dialog = self.dialog()
            stops = QSignalSpy(dialog.stop_requested)
            transition(dialog)
            dialog.close()
            self.app.processEvents()
            self.assertFalse(dialog.isVisible())
            self.assertEqual(0, stops.count())


if __name__ == "__main__":
    unittest.main()
