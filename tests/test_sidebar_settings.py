from __future__ import annotations

import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import Mock, patch

from tests.qt_test_utils import ensure_qapplication

from PySide6.QtCore import QMetaMethod, QSettings, Qt, SIGNAL
from PySide6.QtWidgets import QVBoxLayout, QWidget

from gui.sidebar import SidebarItem, SidebarItemState, SidebarRegistry, SidebarSettingsDialog


def signal_receiver_count(obj: object, signal_name: str) -> int:
    """Return receivers for a named Qt signal without hard-coding its types."""

    meta = obj.metaObject()
    counts = []
    for index in range(meta.methodCount()):
        method = meta.method(index)
        if method.methodType() != QMetaMethod.MethodType.Signal:
            continue
        if bytes(method.name()).decode() != signal_name:
            continue
        signature = bytes(method.methodSignature()).decode()
        counts.append(obj.receivers(SIGNAL(signature)))
    if not counts:
        raise AssertionError(f"Qt signal not found: {type(obj).__name__}.{signal_name}")
    return sum(counts)


class SidebarSettingsTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.app = ensure_qapplication()

    def setUp(self) -> None:
        self.tmp = TemporaryDirectory()
        self.settings = QSettings(
            str(Path(self.tmp.name) / "settings.ini"),
            QSettings.Format.IniFormat,
        )
        self.host = QWidget()
        self.layout = QVBoxLayout(self.host)
        self.layout.addStretch()
        self.widgets = {name: QWidget() for name in ("camera", "smu", "recipe")}
        self.registry = SidebarRegistry(self.layout, self.settings)
        self.registry.register(SidebarItem("camera", "相機連線", self.widgets["camera"], 10))
        self.registry.register(SidebarItem("smu", "SMU 連線", self.widgets["smu"], 20))
        self.registry.register(
            SidebarItem("recipe", "Recipe 選擇", self.widgets["recipe"], 30, False)
        )
        self.registry.restore()

    def tearDown(self) -> None:
        if hasattr(self, "host"):
            self.host.close()
        if hasattr(self, "tmp"):
            self.tmp.cleanup()

    def layout_ids(self) -> list[str]:
        by_widget = {widget: item_id for item_id, widget in self.widgets.items()}
        result = []
        for index in range(self.layout.count()):
            widget = self.layout.itemAt(index).widget()
            if widget in by_widget:
                result.append(by_widget[widget])
        return result

    def create_main_window(self):
        from gui.main_window import MainWindow

        isolated = QSettings(
            str(Path(self.tmp.name) / "main-window.ini"),
            QSettings.Format.IniFormat,
        )
        with patch("gui.main_window.QSettings", return_value=isolated), patch(
            "gui.main_window.QStandardPaths.writableLocation", return_value=self.tmp.name
        ), patch("gui.main_window.QTimer.singleShot"):
            return MainWindow()

    def dispose_main_window(self, window: QWidget) -> None:
        manager = window.responsive_layout_manager
        window.removeEventFilter(manager)
        window.measurement_control_bar.removeEventFilter(manager)
        self.app.removeEventFilter(manager)
        manager.deleteLater()
        window.deleteLater()
        self.app.processEvents()

    def test_apply_reorders_and_changes_visibility_immediately(self) -> None:
        self.registry.save_and_apply([
            SidebarItemState("recipe", True),
            SidebarItemState("camera", False),
            SidebarItemState("smu", True),
        ])
        self.assertEqual(["recipe", "camera", "smu"], self.layout_ids())
        self.assertTrue(self.widgets["camera"].isHidden())
        self.assertFalse(self.widgets["recipe"].isHidden())

        self.registry.save_and_apply([
            SidebarItemState("recipe", True),
            SidebarItemState("camera", True),
            SidebarItemState("smu", True),
        ])
        self.assertFalse(self.widgets["camera"].isHidden())

    def test_show_all_preserves_order_and_reset_restores_all_defaults(self) -> None:
        self.registry.apply([
            SidebarItemState("recipe", False),
            SidebarItemState("smu", False),
            SidebarItemState("camera", True),
        ])
        dialog = SidebarSettingsDialog(self.registry)
        try:
            original_order = [state.id for state in dialog.states()]
            dialog.show_all()
            self.assertEqual(original_order, [state.id for state in dialog.states()])
            self.assertTrue(all(state.visible for state in dialog.states()))

            dialog.reset_defaults()
            self.assertEqual(
                [("camera", True), ("smu", True), ("recipe", False)],
                [(state.id, state.visible) for state in dialog.states()],
            )
        finally:
            dialog.close()

    def test_dialog_apply_uses_current_drag_list_order_and_persists(self) -> None:
        dialog = SidebarSettingsDialog(self.registry)
        try:
            moved = dialog.item_list.takeItem(2)
            dialog.item_list.insertItem(0, moved)
            dialog.item_list.item(1).setCheckState(Qt.CheckState.Unchecked)
            dialog.apply()
        finally:
            dialog.close()

        self.assertEqual(["recipe", "camera", "smu"], self.layout_ids())
        restored_host = QWidget()
        restored_layout = QVBoxLayout(restored_host)
        restored_layout.addStretch()
        restored = SidebarRegistry(restored_layout, self.settings)
        restored_widgets = {name: QWidget() for name in ("camera", "smu", "recipe")}
        for order, name in enumerate(("camera", "smu", "recipe"), 1):
            restored.register(SidebarItem(name, name, restored_widgets[name], order * 10))
        states = restored.restore()
        self.assertEqual(["recipe", "camera", "smu"], [state.id for state in states])
        self.assertFalse(next(state.visible for state in states if state.id == "camera"))
        restored_host.close()

    def test_missing_new_item_uses_default_and_unknown_id_is_ignored(self) -> None:
        self.settings.setValue(
            "interface/sidebar/items",
            json.dumps({
                "items": [
                    {"id": "smu", "visible": False},
                    {"id": "retired_panel", "visible": True},
                    {"id": "recipe", "visible": True},
                ]
            }),
        )
        with self.assertLogs("gui.sidebar.registry", level="WARNING") as captured:
            states = self.registry.load_states()
        self.assertEqual(["camera", "smu", "recipe"], [state.id for state in states])
        self.assertTrue(next(state.visible for state in states if state.id == "camera"))
        self.assertTrue(any("unknown id" in message for message in captured.output))

    def test_late_registered_item_appears_at_default_position(self) -> None:
        temperature = QWidget()
        self.widgets["temperature"] = temperature
        self.registry.register(
            SidebarItem("temperature", "相機溫度", temperature, 15, False)
        )
        self.assertEqual(
            ["camera", "temperature", "smu", "recipe"],
            self.layout_ids(),
        )
        self.assertTrue(temperature.isHidden())

    def test_repeated_apply_keeps_widget_and_layout_item_identity(self) -> None:
        identities = {name: id(widget) for name, widget in self.widgets.items()}
        states = [
            SidebarItemState("smu", False),
            SidebarItemState("recipe", True),
            SidebarItemState("camera", False),
        ]
        for _ in range(3):
            self.registry.apply(states)
        self.assertEqual(identities, {name: id(widget) for name, widget in self.widgets.items()})
        self.assertEqual(["smu", "recipe", "camera"], self.layout_ids())

    def test_main_window_sidebar_changes_are_view_only(self) -> None:
        window = self.create_main_window()
        smu_controller = window.smu_manager.control
        camera_controller = window.controller
        relay_controller = window.relay_controller
        smu_disconnect = Mock(wraps=window.smu_manager.disconnect)
        camera_close = Mock(wraps=window.controller.close_camera)
        capture_receivers = window.capture_button.receivers(SIGNAL("clicked()"))
        resolution_receivers = window.resolution_combo.receivers(
            SIGNAL("currentIndexChanged(int)")
        )
        with patch.object(window.smu_manager, "disconnect", smu_disconnect), patch.object(
            window.controller, "close_camera", camera_close
        ):
            states = [
                SidebarItemState(item.id, item.id not in {"smu_connection", "camera_connection"})
                for item in reversed(window.sidebar_registry.items)
            ]
            window.sidebar_registry.apply(states)
            window.sidebar_registry.apply(states)
            smu_disconnect.assert_not_called()
            camera_close.assert_not_called()
        self.assertEqual(
            capture_receivers,
            window.capture_button.receivers(SIGNAL("clicked()")),
        )
        self.assertEqual(
            resolution_receivers,
            window.resolution_combo.receivers(SIGNAL("currentIndexChanged(int)")),
        )
        self.assertIs(smu_controller, window.smu_manager.control)
        self.assertIs(camera_controller, window.controller)
        self.assertIs(relay_controller, window.relay_controller)
        self.dispose_main_window(window)

    def test_hardware_signals_are_connected_during_main_window_startup(self) -> None:
        window = self.create_main_window()
        try:
            expected = {
                "emergency_stop": signal_receiver_count(
                    window.emergency_stop_button, "clicked"
                ),
                "manual_output": signal_receiver_count(
                    window.manual_smu_panel, "output_requested"
                ),
                "manual_output_off": signal_receiver_count(
                    window.manual_smu_panel, "output_off_requested"
                ),
                "manual_handover": signal_receiver_count(
                    window.manual_smu_panel, "handover_requested"
                ),
                "manual_polarity": signal_receiver_count(
                    window.smu_manager.control, "manual_polarity_changed"
                ),
                "manual_sequence_status": signal_receiver_count(
                    window.smu_manager.control, "manual_sequence_status"
                ),
                "manual_sequence_finished": signal_receiver_count(
                    window.smu_manager.control, "manual_sequence_finished"
                ),
                "manual_channel": signal_receiver_count(
                    window.smu_manager.control, "manual_channel_changed"
                ),
                "manual_command": signal_receiver_count(
                    window.smu_manager.control, "command_applied"
                ),
                "manual_readback": signal_receiver_count(
                    window.smu_manager.control, "readback_ready"
                ),
                "camera_frame": signal_receiver_count(window.controller, "frame_ready"),
                "camera_opened": signal_receiver_count(window.controller, "camera_opened"),
                "camera_closed": signal_receiver_count(window.controller, "camera_closed"),
                "camera_exposure": signal_receiver_count(
                    window.controller, "exposure_changed"
                ),
                "camera_exposure_status": signal_receiver_count(
                    window.controller, "exposure_status_changed"
                ),
                "camera_auto_exposure": signal_receiver_count(
                    window.controller, "auto_exposure_result"
                ),
                "camera_fps": signal_receiver_count(window.controller, "fps_changed"),
                "camera_status": signal_receiver_count(window.controller, "status_changed"),
                "camera_error": signal_receiver_count(window.controller, "error_occurred"),
            }
            self.assertTrue(all(count > 0 for count in expected.values()), expected)
        finally:
            self.dispose_main_window(window)

    def test_opening_sidebar_settings_does_not_add_hardware_signal_receivers(self) -> None:
        window = self.create_main_window()
        watched = (
            (window.emergency_stop_button, "clicked"),
            (window.manual_smu_panel, "output_requested"),
            (window.manual_smu_panel, "output_off_requested"),
            (window.controller, "frame_ready"),
            (window.controller, "camera_opened"),
            (window.controller, "camera_closed"),
            (window.controller, "status_changed"),
            (window.controller, "error_occurred"),
        )
        try:
            before = [signal_receiver_count(obj, name) for obj, name in watched]
            with patch("gui.main_window_ui.SidebarSettingsDialog") as dialog_class:
                for _ in range(3):
                    window.open_sidebar_settings()
            after = [signal_receiver_count(obj, name) for obj, name in watched]
            self.assertEqual(3, dialog_class.call_count)
            self.assertEqual(before, after)
        finally:
            self.dispose_main_window(window)

    def test_hardware_signal_behavior_remains_single_after_three_dialog_opens(self) -> None:
        window = self.create_main_window()
        emergency_slot = Mock()
        manual_off_slot = Mock()
        try:
            window.emergency_stop_button.clicked.disconnect()
            window.manual_smu_panel.output_off_requested.disconnect()
            window.emergency_stop_measurement = emergency_slot
            window.request_manual_smu_off = manual_off_slot
            window.emergency_stop_button.clicked.connect(emergency_slot)
            window.manual_smu_panel.output_off_requested.connect(manual_off_slot)

            window.emergency_stop_button.click()
            window.manual_smu_panel.output_off_requested.emit()
            emergency_slot.assert_called_once()
            manual_off_slot.assert_called_once()

            with patch("gui.main_window_ui.SidebarSettingsDialog"):
                for _ in range(3):
                    window.open_sidebar_settings()

            window.emergency_stop_button.click()
            window.manual_smu_panel.output_off_requested.emit()
            self.assertEqual(2, emergency_slot.call_count)
            self.assertEqual(2, manual_off_slot.call_count)
        finally:
            self.dispose_main_window(window)


if __name__ == "__main__":
    unittest.main()
