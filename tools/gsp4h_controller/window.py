"""Independent light-control window; never imports or starts the main app."""
from __future__ import annotations

from datetime import datetime
from pathlib import Path
from threading import Event

from PySide6.QtCore import QSignalBlocker, QStandardPaths, QThread, QTimer, Qt, Signal, Slot
from PySide6.QtGui import QCloseEvent
from PySide6.QtWidgets import (
    QComboBox, QFileDialog, QGridLayout, QGroupBox, QHBoxLayout, QLabel,
    QMainWindow, QPlainTextEdit, QPushButton, QSlider, QSpinBox, QVBoxLayout, QWidget,
)

from .controller import LightState
from .messages import text
from .settings import BrightnessStore
from .worker import ControllerWorker, OperationResult, available_ports


class LightControlWindow(QMainWindow):
    request = Signal(object)
    dispose_worker = Signal()
    BRIGHTNESS_INTERVAL_MS = 80

    def __init__(
        self, *, auto_start: bool = True, worker: ControllerWorker | None = None,
        settings_store: BrightnessStore | None = None,
    ) -> None:
        super().__init__()
        self.setWindowTitle(text("title"))
        self.resize(1000, 740)
        self.state = LightState()
        self._busy = False
        self._operation = ""
        self._connection_error = False
        self._pending_brightness: dict[int, int] = {}
        self._closing = False
        self._off_pending = False
        self._thread_stopping = False
        self._thread_stopped = False
        self.settings_store = settings_store or BrightnessStore(
            Path(QStandardPaths.writableLocation(QStandardPaths.StandardLocation.GenericConfigLocation))
            / "Luminescence_GSP4H" / "brightness.json"
        )
        load_error = ""
        try:
            saved = self.settings_store.load()
        except (OSError, ValueError) as exc:
            saved, load_error = None, str(exc)
        self._has_settings = saved is not None
        self.desired_brightness = saved or (0, 0, 0, 0)
        self._settings_dirty = False
        self._settings_error = ""
        self._close_save_failed = False
        self.cancel_scan = worker.cancel if worker is not None else Event()
        self._brightness_timer = QTimer(self)
        self._brightness_timer.setSingleShot(True)
        self._brightness_timer.setInterval(self.BRIGHTNESS_INTERVAL_MS)
        self._brightness_timer.timeout.connect(self._flush_brightness)
        self._settings_timer = QTimer(self)
        self._settings_timer.setSingleShot(True)
        self._settings_timer.setInterval(200)
        self._settings_timer.timeout.connect(self._save_settings)
        self._build_ui()
        self._sync_values()
        if load_error:
            self.settings_label.setText(text("settings_load_error", detail=load_error))
            self._trace("WARN", f"Brightness settings not loaded: {load_error}")
        self.worker_thread = QThread(self)
        self.worker = worker or ControllerWorker(self.cancel_scan)
        self.worker.moveToThread(self.worker_thread)
        self.request.connect(self.worker.execute)
        self.dispose_worker.connect(self.worker.dispose)
        self.worker.completed.connect(self._completed)
        self.worker.trace.connect(self._trace)
        self.worker.connection_fault.connect(self._connection_fault)
        self.worker_thread.finished.connect(self.worker.deleteLater)
        self.worker_thread.finished.connect(self._thread_finished)
        self.worker_thread.start()
        self._populate_ports(available_ports(), ())
        self._update_controls()
        if auto_start:
            QTimer.singleShot(0, self.scan)

    def _build_ui(self) -> None:
        central = QWidget()
        layout = QVBoxLayout(central)
        self.setCentralWidget(central)

        connection = QGroupBox(text("connection"))
        grid = QGridLayout(connection)
        self.port_combo = QComboBox()
        self.port_combo.setEditable(True)
        self.port_combo.setMinimumContentsLength(30)
        self.parity_combo = QComboBox()
        for value in ("none", "even", "odd"):
            self.parity_combo.addItem(text(value), value)
        self.scan_button = QPushButton(text("scan"))
        self.connect_button = QPushButton(text("connect"))
        self.disconnect_button = QPushButton(text("disconnect"))
        self.refresh_button = QPushButton(text("refresh"))
        grid.addWidget(self.port_combo, 0, 0, 1, 4)
        grid.addWidget(QLabel(text("parity")), 0, 4)
        grid.addWidget(self.parity_combo, 0, 5)
        for index, button in enumerate((self.scan_button, self.connect_button, self.disconnect_button, self.refresh_button)):
            grid.addWidget(button, 1, index)
        grid.addWidget(QLabel(text("serial_settings")), 1, 4, 1, 2)
        connection_row = QHBoxLayout()
        self.connection_lamp = QLabel()
        self.connection_lamp.setFixedSize(18, 18)
        self.connection_status = QLabel(text("connection_disconnected"))
        connection_row.addWidget(self.connection_lamp)
        connection_row.addWidget(self.connection_status)
        connection_row.addStretch()
        grid.addLayout(connection_row, 2, 0, 1, 6)
        self.scan_button.clicked.connect(self.scan)
        self.connect_button.clicked.connect(self.connect_selected)
        self.disconnect_button.clicked.connect(lambda: self._submit("disconnect"))
        self.refresh_button.clicked.connect(lambda: self._submit("refresh"))
        layout.addWidget(connection)

        self.status = QLabel(text("initial"))
        self.status.setWordWrap(True)
        self.status.setMinimumHeight(54)
        self.status.setStyleSheet("padding: 8px; background: #e8eef5; color: #172b4d;")
        layout.addWidget(self.status)
        channels = QGroupBox(text("channels"))
        rows = QGridLayout(channels)
        for index, key in enumerate(("channel", "requested", "readback", "actions")):
            rows.addWidget(QLabel(text(key)), 0, (0, 1, 3, 4)[index])
        rows.setColumnStretch(1, 1)
        self.sliders: list[QSlider] = []
        self.values: list[QSpinBox] = []
        self.readbacks: list[QLabel] = []
        self.zero_buttons: list[QPushButton] = []
        for channel in range(1, 5):
            slider = QSlider(Qt.Orientation.Horizontal)
            slider.setRange(0, 255)
            value = QSpinBox()
            value.setRange(0, 255)
            slider.valueChanged.connect(value.setValue)
            value.valueChanged.connect(slider.setValue)
            value.valueChanged.connect(lambda level, ch=channel: self._brightness_changed(ch, level))
            readback = QLabel(text("unavailable"))
            readback.setMinimumWidth(75)
            zero = QPushButton(text("zero"))
            zero.clicked.connect(lambda _checked=False, ch=channel: self._zero_channel(ch))
            rows.addWidget(QLabel(text("channel_name", channel=channel)), channel, 0)
            for column, widget in enumerate((slider, value, readback, zero), 1):
                rows.addWidget(widget, channel, column)
            self.sliders.append(slider)
            self.values.append(value)
            self.readbacks.append(readback)
            self.zero_buttons.append(zero)
        layout.addWidget(channels)
        self.settings_label = QLabel(text("settings_loaded") if self._has_settings else text("settings_initial"))
        self.settings_label.setWordWrap(True)
        layout.addWidget(self.settings_label)

        global_group = QGroupBox(text("global"))
        mode_layout = QVBoxLayout(global_group)
        self.mode_label = QLabel(text("mode", value=text("mode_unknown")))
        self.mode_label.setWordWrap(True)
        self.mode_label.setMinimumHeight(44)
        self.mode_reason = QLabel(text("mode_unknown_reason"))
        self.mode_reason.setWordWrap(True)
        mode_layout.addWidget(self.mode_label)
        mode_layout.addWidget(self.mode_reason)
        mode_buttons = QHBoxLayout()
        self.power_button = QPushButton(text("power_on"))
        self.power_button.setMinimumHeight(36)
        self.power_button.clicked.connect(self.toggle_power)
        mode_buttons.addWidget(self.power_button)
        mode_layout.addLayout(mode_buttons)
        layout.addWidget(global_group)
        hint = QLabel(text("hint"))
        hint.setWordWrap(True)
        layout.addWidget(hint)
        log_row = QHBoxLayout()
        log_row.addWidget(QLabel(text("log")))
        log_row.addStretch()
        export = QPushButton(text("export"))
        export.clicked.connect(self.export_log)
        log_row.addWidget(export)
        layout.addLayout(log_row)
        self.log_view = QPlainTextEdit()
        self.log_view.setReadOnly(True)
        self.log_view.setMaximumBlockCount(1500)
        layout.addWidget(self.log_view, 1)

    def _populate_ports(self, ports, compatible) -> None:
        selected = self._selected_port()
        self.port_combo.clear()
        for port in ports:
            label = text("candidate", port=port.display) if port.name in compatible else port.display
            self.port_combo.addItem(label, port.name)
        if self.port_combo.findData("COM6") < 0:
            default_port = "COM6"
            self.port_combo.addItem(default_port, default_port)
        index = self.port_combo.findData(selected)
        self.port_combo.setCurrentIndex(index if index >= 0 else self.port_combo.findData("COM6"))

    def _selected_port(self) -> str:
        if self.port_combo.currentIndex() >= 0 and self.port_combo.currentText() == self.port_combo.itemText(self.port_combo.currentIndex()):
            return str(self.port_combo.currentData())
        return self.port_combo.currentText().strip() or "COM6"

    def _update_controls(self) -> None:
        stopping = self._closing or self._off_pending or self._thread_stopping
        idle = not (self._busy or stopping or self._pending_brightness)
        no_session = not self.state.shutdown_required
        self.scan_button.setEnabled(idle and no_session)
        self.connect_button.setEnabled(idle and no_session)
        self.port_combo.setEnabled(idle and no_session)
        self.parity_combo.setEnabled(idle and no_session)
        self.disconnect_button.setEnabled(idle and self.state.shutdown_required)
        self.refresh_button.setEnabled(idle and self.state.connected)
        adjustable = self.state.ready and not stopping and (
            not self._busy or self._operation == "brightness"
        )
        for widget in (*self.sliders, *self.values, *self.zero_buttons):
            widget.setEnabled(adjustable)
        if self._busy and self._operation == "enable":
            power_action, power_text = "off", "power_cancel"
        elif not self.state.shutdown_required:
            power_action, power_text = "on", "power_on"
        elif not self.state.ready:
            power_action, power_text = "off", "power_retry_off"
        elif self.state.mode == "H":
            power_action, power_text = "off", "power_off"
        else:
            power_action, power_text = "on", "power_on"
        self.power_button.setText(text(power_text))
        self.power_button.setProperty("powerAction", power_action)
        self.power_button.setStyleSheet(
            "font-weight: bold; padding: 8px; color: " + ("#a4262c;" if power_action == "off" else "#146c43;")
        )
        self.power_button.setEnabled(self.state.shutdown_required and not stopping and (
            power_action == "off" or (self.state.ready and not self._busy)
        ))
        for index, label in enumerate(self.readbacks):
            value = self.state.brightness[index] if self.state.connected else None
            label.setText(str(value) if value is not None else text("unknown"))
        mode = self.state.mode if self.state.connected and self.state.mode in ("H", "L") else None
        self.mode_label.setText(text("mode", value=text("mode_" + mode.lower()) if mode else text("mode_unknown")))
        if mode == "H":
            color, background = "#146c43", "#e7f4ec"
            reason = "mode_h_zero_reason" if self.state.brightness == (0, 0, 0, 0) else "mode_h_reason"
        elif mode == "L":
            color, background, reason = "#805b00", "#fff3cd", "mode_l_reason"
        else:
            color, background, reason = "#4f5965", "#edf0f3", "mode_unknown_reason"
        self.mode_label.setStyleSheet(
            f"font-size: 16px; font-weight: bold; padding: 8px; border-radius: 4px; color: {color}; background: {background};"
        )
        self.mode_reason.setText(text(reason))
        if self._busy and self._operation in ("scan", "connect", "refresh"):
            lamp, color, key = "checking", "#d99200", "connection_checking"
        elif self._connection_error or (self.state.shutdown_required and not self.state.ready):
            lamp, color, key = "error", "#c62828", "connection_error"
        elif self.state.ready:
            lamp, color, key = "connected", "#198754", "connection_verified"
        else:
            lamp, color, key = "disconnected", "#858b94", "connection_disconnected"
        description = text(key, port=self.state.port)
        self.connection_lamp.setProperty("connectionState", lamp)
        self.connection_lamp.setStyleSheet(f"background: {color}; border: 1px solid #555; border-radius: 9px;")
        self.connection_lamp.setAccessibleName(description)
        self.connection_lamp.setToolTip(description)
        self.connection_status.setText(description)

    def _sync_values(self) -> None:
        # Desired settings survive OFF, shutdown zeroing, and device refresh.
        for slider, spinbox, value in zip(self.sliders, self.values, self.desired_brightness):
            with QSignalBlocker(slider), QSignalBlocker(spinbox):
                slider.setValue(value)
                spinbox.setValue(value)

    def _save_settings(self) -> bool:
        self._settings_timer.stop()
        if not self._has_settings or not self._settings_dirty:
            return not bool(self._settings_error)
        try:
            self.settings_store.save(self.desired_brightness)
        except (OSError, ValueError) as exc:
            self._settings_error = str(exc)
            self.settings_label.setText(text("settings_save_error", detail=str(exc)))
            self._trace("ERROR", f"Brightness settings not saved: {exc}")
            return False
        self._settings_dirty = False
        self._settings_error = ""
        self.settings_label.setText(text("settings_saved"))
        return True

    def _discard_brightness(self) -> None:
        self._brightness_timer.stop()
        self._pending_brightness.clear()

    def _brightness_changed(self, channel: int, value: int) -> None:
        if not self.state.ready or self._closing or self._off_pending or self._thread_stopping:
            return
        if self._busy and self._operation != "brightness":
            return
        self.desired_brightness = tuple(spin.value() for spin in self.values)
        self._has_settings = True
        self._settings_dirty = True
        self.settings_label.setText(text("settings_pending"))
        self._settings_timer.start()
        self._pending_brightness[channel] = value
        # Do not restart on every drag event: send updates during dragging, not
        # just after the operator releases the slider. Keep only the latest value
        # for each channel while the worker completes the preceding transaction.
        if not self._brightness_timer.isActive():
            self._brightness_timer.start()
        self._update_controls()

    def _zero_channel(self, channel: int) -> None:
        self.values[channel - 1].setValue(0)
        self._brightness_changed(channel, 0)

    @Slot()
    def _flush_brightness(self) -> None:
        if self._busy:
            return
        if not self.state.ready or self._closing or self._off_pending or self._thread_stopping:
            self._discard_brightness()
            return
        if self._pending_brightness:
            channel = next(iter(self._pending_brightness))
            value = self._pending_brightness.pop(channel)
            self._submit("brightness", channel=channel, value=value)
        else:
            self._update_controls()

    def _submit(self, operation: str, **parameters) -> None:
        if self._busy or self._thread_stopping:
            return
        if operation != "brightness":
            self._discard_brightness()
        self._busy = True
        self._operation = operation
        if operation == "enable":
            self.cancel_scan.clear()
        self.status.setText(text("busy", operation=text("operation_" + operation)))
        self._update_controls()
        self.request.emit({"operation": operation, **parameters})

    @Slot()
    def scan(self) -> None:
        if self._closing or self._thread_stopping or self.state.shutdown_required or self._busy:
            return
        self.cancel_scan.clear()
        self._submit("scan", parity=self.parity_combo.currentData())

    @Slot()
    def connect_selected(self) -> None:
        self._submit("connect", port=self._selected_port(), parity=self.parity_combo.currentData())

    @Slot()
    def all_off(self) -> None:
        if not self.state.shutdown_required or self._closing:
            return
        self.cancel_scan.set()
        self._save_settings()
        self._discard_brightness()
        if self._busy:
            self._off_pending = True
            self.status.setText(text("off_wait"))
            self._update_controls()
        else:
            self._submit("off")

    @Slot()
    def toggle_power(self) -> None:
        if self._closing or self._thread_stopping:
            return
        if self.power_button.property("powerAction") == "off":
            self.all_off()
        elif self.state.ready and not self._busy:
            self._save_settings()
            self._submit("enable", values=self.desired_brightness)

    @Slot(str, str)
    def _trace(self, kind: str, data: str) -> None:
        timestamp = datetime.now().astimezone().isoformat(timespec="milliseconds")
        self.log_view.appendPlainText(f"{timestamp} {kind} {data}")

    @Slot(object)
    def _connection_fault(self, state: LightState) -> None:
        self.state = state
        self._connection_error = True
        self._discard_brightness()
        self.status.setText(text("lost"))
        self._update_controls()

    @Slot(object)
    def _completed(self, result: OperationResult) -> None:
        self._busy = False
        self._operation = ""
        self.state = result.state
        self._connection_error = bool(result.error)
        if result.error:
            self._discard_brightness()
        if result.scan is not None:
            self._populate_ports(result.scan.ports, result.scan.compatible)
        if self.state.shutdown_required:
            index = self.port_combo.findData(self.state.port)
            if index >= 0:
                self.port_combo.setCurrentIndex(index)
            else:
                self.port_combo.setEditText(self.state.port)
        if result.error:
            key = "shutdown_failed" if self._closing or result.operation == "disconnect" else "failed"
            self.status.setText(text(key, detail=result.error))
        elif result.cancelled:
            self.status.setText(text("enable_cancelled" if result.operation == "enable" else "cancelled"))
        elif result.operation == "disconnect":
            self.status.setText(text("disconnected"))
        elif result.operation == "off":
            self.status.setText(text("off_verified"))
        elif result.operation == "enable":
            self.status.setText(text("on_verified"))
        elif self.state.ready:
            self.status.setText(text("connected", port=self.state.port))
        elif result.scan is not None:
            if len(result.scan.compatible) > 1:
                self.status.setText(text("multiple", ports=", ".join(result.scan.compatible)))
            else:
                self.status.setText(text("no_match"))

        if not self._has_settings and self.state.ready and result.operation in ("scan", "connect", "refresh"):
            self.desired_brightness = tuple(self.state.brightness)
            self._has_settings = True
            self._settings_dirty = True
            self._sync_values()
            self._save_settings()
        if self._closing:
            if result.operation == "disconnect" and result.error:
                self._closing = False
                self._off_pending = False
            elif self.state.shutdown_required:
                self._submit("disconnect")
                return
            elif self._close_save_failed:
                self._closing = False
                self.status.setText(text("settings_close_error", detail=self._settings_error))
            else:
                self._stop_thread()
                return
        elif self._off_pending:
            self._off_pending = False
            if self.state.shutdown_required:
                self._submit("off")
                return
        elif self._pending_brightness and not self._brightness_timer.isActive():
            self._flush_brightness()
            return
        self._update_controls()

    def export_log(self) -> None:
        filename, _ = QFileDialog.getSaveFileName(
            self, text("export_title"), "gsp4h_communication.txt", text("log_filter"),
        )
        if filename:
            try:
                Path(filename).write_text(self.log_view.toPlainText() + "\n", encoding="utf-8")
            except OSError as exc:
                self.status.setText(text("export_error", detail=str(exc)))

    def _stop_thread(self) -> None:
        self._discard_brightness()
        self._settings_timer.stop()
        self._thread_stopping = True
        self._update_controls()
        self.dispose_worker.emit()

    @Slot()
    def _thread_finished(self) -> None:
        self._thread_stopped = True
        self.close()

    def closeEvent(self, event: QCloseEvent) -> None:
        if self._thread_stopped:
            event.accept()
            return
        event.ignore()
        if self._closing:
            return
        self._closing = True
        self._close_save_failed = not self._save_settings()
        self._discard_brightness()
        self._off_pending = False
        self.cancel_scan.set()
        self.status.setText(text("shutdown_wait"))
        self._update_controls()
        if not self._busy:
            if self.state.shutdown_required:
                self._submit("disconnect")
            elif self._close_save_failed:
                self._closing = False
                self.status.setText(text("settings_close_error", detail=self._settings_error))
                self._update_controls()
            else:
                self._stop_thread()
