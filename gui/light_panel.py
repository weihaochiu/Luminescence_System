"""Compact manual light panel and advanced settings; share one LightService."""
from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QSignalBlocker, Qt, QTimer
from PySide6.QtWidgets import (
    QCheckBox, QComboBox, QDialog, QDialogButtonBox, QFileDialog, QFormLayout,
    QGroupBox, QHBoxLayout, QLabel, QLineEdit, QPlainTextEdit, QPushButton, QSlider, QSpinBox,
    QVBoxLayout, QWidget,
)

from core.i18n import i18n, tr
from tools.gsp4h_controller.worker import available_ports
from .light_service import LightService


def connection_text(service: LightService) -> str:
    if service.busy in ("scan", "connect", "refresh"):
        return tr("light.checking")
    if service.state.shutdown_required and not service.state.ready:
        return tr("light.unknown")
    if service.state.ready:
        return tr("light.connected", port=service.state.port)
    if service.error:
        return tr("light.error")
    return tr("light.disconnected")


class LightPanel(QWidget):
    def __init__(self, service: LightService, parent=None) -> None:
        super().__init__(parent)
        self.service = service
        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 10)
        row = QHBoxLayout()
        self.status = QLabel()
        self.status.setWordWrap(True)
        self.auto_button = QPushButton()
        self.auto_button.clicked.connect(service.auto_connect)
        row.addWidget(self.status, 1)
        row.addWidget(self.auto_button)
        layout.addLayout(row)
        self.power_button = QPushButton()
        self.power_button.clicked.connect(self._toggle)
        layout.addWidget(self.power_button)
        form = QFormLayout()
        self.channel_label = QLabel()
        self.channel = QComboBox()
        self.channel.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon)
        self.channel.setMinimumContentsLength(10)
        for index in range(1, 5):
            self.channel.addItem(tr("light.channel_name", channel=index), index)
        self.channel.currentIndexChanged.connect(self.refresh)
        form.addRow(self.channel_label, self.channel)
        self.level_label = QLabel()
        controls = QHBoxLayout()
        self.slider = QSlider(Qt.Orientation.Horizontal)
        self.slider.setRange(0, 255)
        self.level = QSpinBox()
        self.level.setRange(0, 255)
        self.slider.valueChanged.connect(self.level.setValue)
        self.level.valueChanged.connect(self.slider.setValue)
        self.level.valueChanged.connect(self._set_level)
        controls.addWidget(self.slider, 1)
        controls.addWidget(self.level)
        form.addRow(self.level_label, controls)
        layout.addLayout(form)
        self.hint = QLabel()
        self.hint.setWordWrap(True)
        layout.addWidget(self.hint)
        service.changed.connect(self.refresh)
        i18n.language_changed.connect(self.refresh)
        self.refresh()

    def _set_level(self, value: int) -> None:
        self.service.set_level(self.channel.currentData(), value)

    def _toggle(self) -> None:
        if self.power_button.property("powerAction") == "off":
            self.service.off()
        else:
            self.service.enable()

    def refresh(self, *_args) -> None:
        service = self.service
        self.status.setText(connection_text(service))
        self.auto_button.setText(tr("light.auto_connect"))
        self.auto_button.setEnabled(service.can_connect)
        self.channel_label.setText(tr("light.channel"))
        with QSignalBlocker(self.channel):
            for index in range(self.channel.count()):
                channel = self.channel.itemData(index)
                name = service.channel_name(channel)
                label = (tr("light.channel_named", channel=channel, name=name) if name
                         else tr("light.channel_name", channel=channel))
                self.channel.setItemText(index, label)
                self.channel.setItemData(index, label, Qt.ItemDataRole.ToolTipRole)
        self.channel.setToolTip(self.channel.currentText())
        self.level_label.setText(tr("light.level"))
        off = service.state.shutdown_required and (
            service.state.mode != "L" or service.busy == "enable")
        self.power_button.setProperty("powerAction", "off" if off else "on")
        key = "retry_off" if off and not service.state.ready else "power_off" if off else "power_on"
        self.power_button.setText(tr("light." + key))
        self.power_button.setEnabled(
            not service._stopping and not service._stopped and (
                (off and not service._off_pending) or service.can_enable))
        value = service.levels[self.channel.currentData() - 1]
        with QSignalBlocker(self.slider), QSignalBlocker(self.level):
            self.slider.setValue(value)
            self.level.setValue(value)
        self.slider.setEnabled(service.editable)
        self.level.setEnabled(service.editable)
        self.channel.setEnabled(not service.locks)
        if service.error:
            hint = tr("light.settings_hint")
        elif service.notice:
            hint = tr("light." + service.notice)
        elif service.locks:
            hint = tr("light.locked")
        elif service.state.ready:
            hint = tr("light.mode", mode=service.state.mode)
        else:
            hint = ""
        self.hint.setText(hint)


class LightSettingsDialog(QDialog):
    def __init__(self, service: LightService, parent=None) -> None:
        super().__init__(parent)
        self.service = service
        self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
        self.resize(690, 580)
        layout = QVBoxLayout(self)
        form = QFormLayout()
        self.port_label = QLabel()
        self.port = QComboBox()
        self.port.setEditable(True)
        form.addRow(self.port_label, self.port)
        self.parity_label = QLabel()
        self.parity = QComboBox()
        for value in ("none", "even", "odd"):
            self.parity.addItem(value, value)
        self.parity.setCurrentIndex(self.parity.findData(service.parity))
        self.parity.currentIndexChanged.connect(self._save_parity)
        form.addRow(self.parity_label, self.parity)
        layout.addLayout(form)
        self.serial_info = QLabel()
        layout.addWidget(self.serial_info)
        self.startup = QCheckBox()
        self.startup.setChecked(service.settings.value("light/auto_connect", True, type=bool))
        self.startup.toggled.connect(lambda value: service.settings.setValue("light/auto_connect", value))
        layout.addWidget(self.startup)
        self.preferred = QLabel()
        self.preferred.setWordWrap(True)
        layout.addWidget(self.preferred)
        self.channel_names_group = QGroupBox()
        names_form = QFormLayout(self.channel_names_group)
        self.channel_name_labels: dict[int, QLabel] = {}
        self.channel_name_edits: dict[int, QLineEdit] = {}
        for channel in range(1, 5):
            label = QLabel()
            edit = QLineEdit(service.channel_name(channel))
            edit.textEdited.connect(lambda name, ch=channel: service.set_channel_name(ch, name))
            edit.editingFinished.connect(lambda ch=channel: self._save_channel_name(ch))
            self.channel_name_labels[channel] = label
            self.channel_name_edits[channel] = edit
            names_form.addRow(label, edit)
        layout.addWidget(self.channel_names_group)
        row = QHBoxLayout()
        self.scan = QPushButton()
        self.connect = QPushButton()
        self.disconnect = QPushButton()
        self.read = QPushButton()
        self.scan.clicked.connect(service.auto_connect)
        self.connect.clicked.connect(self._connect)
        self.disconnect.clicked.connect(lambda: service.off(disconnect=True))
        self.read.clicked.connect(service.refresh)
        for button in (self.scan, self.connect, self.disconnect, self.read):
            row.addWidget(button)
        layout.addLayout(row)
        self.status = QLabel()
        self.status.setWordWrap(True)
        layout.addWidget(self.status)
        self.readback = QLabel()
        self.readback.setWordWrap(True)
        layout.addWidget(self.readback)
        self.details = QLabel()
        self.details.setWordWrap(True)
        layout.addWidget(self.details)
        self.log = QPlainTextEdit()
        self.log.setReadOnly(True)
        self.log.setMaximumBlockCount(1500)
        layout.addWidget(self.log, 1)
        self.export = QPushButton()
        self.export.clicked.connect(self._export)
        layout.addWidget(self.export)
        self.buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        self.buttons.rejected.connect(self.reject)
        layout.addWidget(self.buttons)
        self._last_scan = None
        self._populate_ports()
        service.changed.connect(self.refresh)
        i18n.language_changed.connect(self.refresh)
        self._log_timer = QTimer(self)
        self._log_timer.setInterval(300)
        self._log_timer.timeout.connect(self._refresh_log)
        self._log_timer.start()
        self.refresh()

    def _populate_ports(self) -> None:
        selected = (self.service.state.port if self.service.state.shutdown_required
                    else self.port.currentData() or self.service.preferred_port())
        with QSignalBlocker(self.port):
            self.port.clear()
            ports = self.service.scan_result.ports if self.service.scan_result else available_ports()
            for port in ports:
                self.port.addItem(port.display, port.name)
            if self.port.findData(selected) < 0:
                self.port.addItem(str(selected), str(selected))
            self.port.setCurrentIndex(self.port.findData(selected))

    def _connect(self) -> None:
        if self.port.currentText() == self.port.itemText(self.port.currentIndex()):
            port = str(self.port.currentData())
        else:
            port = self.port.currentText()
        self.service.connect_port(port)

    def _save_parity(self) -> None:
        self.service.settings.setValue("light/parity", self.parity.currentData())

    def _save_channel_name(self, channel: int) -> None:
        edit = self.channel_name_edits[channel]
        self.service.set_channel_name(channel, edit.text())
        with QSignalBlocker(edit):
            edit.setText(self.service.channel_name(channel))

    def _refresh_log(self) -> None:
        value = "\n".join(self.service.logs)
        if value != self.log.toPlainText():
            self.log.setPlainText(value)
            self.log.verticalScrollBar().setValue(self.log.verticalScrollBar().maximum())

    def _export(self) -> None:
        path, _filter = QFileDialog.getSaveFileName(
            self, tr("light.export"), "gsp4h_communication.txt", tr("light.log_filter"))
        if path:
            try:
                Path(path).write_text("\n".join(self.service.logs) + "\n", encoding="utf-8")
            except OSError as exc:
                self.service.failed.emit("FILE-201", str(exc))

    def refresh(self, *_args) -> None:
        service = self.service
        self.setWindowTitle(tr("light.settings"))
        self.buttons.button(QDialogButtonBox.StandardButton.Close).setText(tr("common.close"))
        self.port_label.setText(tr("light.port"))
        self.parity_label.setText(tr("light.parity"))
        with QSignalBlocker(self.parity):
            for index in range(self.parity.count()):
                self.parity.setItemText(index, tr("light.parity_" + self.parity.itemData(index)))
        self.serial_info.setText(tr("light.serial_info"))
        self.startup.setText(tr("light.startup"))
        self.preferred.setText(tr("light.preferred", port=service.preferred_port()))
        self.channel_names_group.setTitle(tr("light.channel_names"))
        for channel, edit in self.channel_name_edits.items():
            self.channel_name_labels[channel].setText(tr("light.channel_name", channel=channel))
            edit.setPlaceholderText(tr("light.channel_name_placeholder"))
            if not edit.hasFocus():
                with QSignalBlocker(edit):
                    edit.setText(service.channel_name(channel))
        for button, key in ((self.scan, "scan"), (self.connect, "connect"),
                            (self.disconnect, "disconnect"), (self.read, "read"), (self.export, "export")):
            button.setText(tr("light." + key))
        if service.scan_result is not self._last_scan:
            self._last_scan = service.scan_result
            self._populate_ports()
        for widget in (self.port, self.parity, self.scan, self.connect):
            widget.setEnabled(service.can_connect)
        self.startup.setEnabled(not service.locks)
        self.disconnect.setEnabled(service.state.shutdown_required and not service.busy
                                   and not service.locks and not service._off_pending)
        self.read.setEnabled(service.state.connected and not service.busy and not service.locks)
        self.status.setText(connection_text(service))
        unknown = tr("common.unknown")
        levels = " / ".join(f"CH{i}={v if v is not None else unknown}"
                            for i, v in enumerate(service.state.brightness, 1))
        self.readback.setText(tr("light.readback", mode=service.state.mode or unknown, levels=levels))
        self.details.setText(service.error or (tr("light." + service.notice) if service.notice
                                              else tr("light.settings_description")))
        self._refresh_log()
