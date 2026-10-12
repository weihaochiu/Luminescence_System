from __future__ import annotations

from datetime import datetime
import math
from time import monotonic

from PySide6.QtCore import Qt, Signal, QTimer
from PySide6.QtWidgets import (QAbstractItemView, QDialog, QDialogButtonBox, QFormLayout, QLabel,
                              QLineEdit, QMessageBox, QPushButton, QTableWidget,
                              QTableWidgetItem, QVBoxLayout)
from .calibration import LightCalibration
from .lux_reference import load_capture, required_levels
from .messages import msg


class LuxDialog(QDialog):
    apply_requested = Signal(int, int)
    reference_ready = Signal(object)
    off_requested = Signal()

    def __init__(self, session, parent=None):
        super().__init__(parent)
        self.session = str(session)
        _base, _manifest, snapshot, rows = load_capture(session)
        self.channel = snapshot["plan"]["channel"]
        self.levels = (0, *required_levels(rows))
        self.settle_s = float(snapshot['plan'].get('settle_s', 1.))
        self.index = 0
        self.readings = {}
        self.started = False
        self.ready = False
        self.busy = False
        self.saving = False
        self.phase = 'INITIAL'
        self.setWindowTitle(msg("補填本次測試的 LUX", "Measure LUX for this capture"))
        self.setWindowModality(Qt.WindowModality.ApplicationModal)
        self.resize(740, 580)
        layout = QVBoxLayout(self)
        info = QLabel(msg("程式自動切換 PWM。讀值穩定後輸入 LUX，按確定即可進入下一個。PWM 0 是背景讀值。\n每次確定表示讀值已穩定且光源、位置、方向與暖機條件和拍攝時相同；原始拍攝紀錄不會改寫。",
                          "PWM switches automatically. Enter stable LUX and confirm to advance. PWM 0 measures background.\nEach confirmation acknowledges stable readings and the capture's source, geometry and warmup conditions. Capture evidence stays unchanged."))
        info.setWordWrap(True)
        layout.addWidget(info)
        self.table = QTableWidget(len(self.levels), 2)
        self.table.setHorizontalHeaderLabels([msg("PWM 等級", "PWM level"), msg("量測 LUX", "Measured LUX")])
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.NoSelection)
        for row, level in enumerate(self.levels):
            item = QTableWidgetItem(str(level))
            item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsEditable)
            self.table.setItem(row, 0, item)
            self.table.setItem(row, 1, QTableWidgetItem(""))
        self.table.horizontalHeader().setStretchLastSection(True)
        self.table.selectRow(0)
        layout.addWidget(self.table)
        self.current = QLabel()
        layout.addWidget(self.current)
        value_form = QFormLayout()
        self.value = QLineEdit()
        self.value.setPlaceholderText(msg("輸入目前照度計的穩定讀值", "Enter the current stable meter reading"))
        value_form.addRow(msg("目前 LUX", "Current LUX"), self.value)
        layout.addLayout(value_form)
        self.state = QLabel(msg("準備自動設定 PWM 0", "Preparing to apply PWM 0 automatically"))
        self.state.setWordWrap(True)
        layout.addWidget(self.state)
        original = snapshot["light_calibration"]["calibration"]
        form = QFormLayout()
        self.meter = QLineEdit(original.get("meter", ""))
        self.geometry = QLineEdit(original.get("geometry", ""))
        self.notes = QLineEdit()
        form.addRow(msg("光強計識別", "Meter identity"), self.meter)
        form.addRow(msg("量測位置／光學條件", "Geometry / optics"), self.geometry)
        form.addRow(msg("備註", "Notes"), self.notes)
        layout.addLayout(form)
        buttons = QDialogButtonBox()
        self.back = buttons.addButton(msg("上一步", "Previous"), QDialogButtonBox.ButtonRole.ActionRole)
        self.next = buttons.addButton(msg("確定／下一個", "Confirm / Next"), QDialogButtonBox.ButtonRole.ActionRole)
        self.retry = buttons.addButton(msg("重試設定", "Retry setting"), QDialogButtonBox.ButtonRole.ActionRole)
        self.later = buttons.addButton(msg("稍後補填（安全關燈）", "Fill later (turn off safely)"), QDialogButtonBox.ButtonRole.RejectRole)
        self.next.setDefault(True)
        self.next.clicked.connect(self._next)
        self.back.clicked.connect(self._previous)
        self.retry.clicked.connect(self._request_current)
        self.later.clicked.connect(self.reject)
        layout.addWidget(buttons)
        self.source_name = original.get("source_name", "")
        self.timer = QTimer(self)
        self.timer.setInterval(500)
        self.timer.timeout.connect(self._tick)
        self._update_controls()

    def start(self):
        if self.started or self.phase == 'CLOSED':
            return
        self.started = True
        self._request_current()

    def _update_controls(self):
        enabled = self.ready and not self.busy and not self.saving
        self.value.setEnabled(enabled)
        self.next.setEnabled(enabled)
        self.back.setEnabled(enabled and self.index > 0)
        self.retry.setVisible(self.phase == 'ERROR')
        self.retry.setEnabled(not self.busy and not self.saving)
        self.next.setText(msg("確定並完成分析", "Confirm and analyze") if self.index == len(self.levels) - 1 else msg("確定／下一個", "Confirm / Next"))
        self.current.setText(msg(f"目前：CH{self.channel} / PWM {self.levels[self.index]}（第 {self.index + 1}／{len(self.levels)} 項）",
                                 f"Current: CH{self.channel} / PWM {self.levels[self.index]} ({self.index + 1}/{len(self.levels)})"))
        self.table.setCurrentCell(self.index, 1)
        self.table.scrollToItem(self.table.item(self.index, 1))

    def set_busy(self, busy):
        self.busy = busy
        self._update_controls()

    def show_readback(self, state, error="", operation='apply'):
        if operation == 'attach_lux':
            if error:
                self.saving = False
                self._fail(error)
            return
        if operation != 'apply' or self.phase != 'APPLYING':
            return
        level = self.levels[self.index]
        expected = [0] * 4
        expected[self.channel - 1] = level
        matched = state and state.ready and state.mode == ('H' if level else 'L') and state.brightness == tuple(expected)
        if error or not matched:
            self._fail(error or msg("PWM 讀回與目前步驟不一致，尚未開放輸入", "PWM readback does not match the current step; input remains locked"))
            return
        self.timer.stop()
        self.phase = 'READY'
        self.ready = True
        self.state.setText(msg("PWM 已確認且等待完成；請等照度計讀值穩定後輸入", "PWM verified and settling wait completed; enter the stable meter reading"))
        self._update_controls()
        self.value.setFocus()
        self.value.selectAll()

    def _request_current(self):
        if self.busy or self.saving or self.phase == 'CLOSED':
            return
        self.ready = False
        self.phase = 'APPLYING'
        self.requested_at = monotonic()
        self.value.setText(str(self.readings.get(self.levels[self.index], '')))
        self._update_controls()
        self._tick()
        self.timer.start()
        self.apply_requested.emit(self.channel, self.levels[self.index])

    def _tick(self):
        self.state.setText(msg(f"正在設定 PWM 並等待穩定／讀回確認，已等待 {monotonic() - self.requested_at:.1f} 秒",
                               f"Applying PWM and waiting for settling/readback, {monotonic() - self.requested_at:.1f} s elapsed"))

    def _fail(self, error):
        self.timer.stop()
        self.phase = 'ERROR'
        self.ready = False
        self.state.setText(error)
        self._update_controls()

    def _previous(self):
        if self.ready and not self.busy and not self.saving and self.index > 0:
            self.index -= 1
            self._request_current()

    def _next(self):
        if not self.ready or self.busy or self.saving:
            return
        try:
            try:
                reading = float(self.value.text())
            except ValueError:
                raise ValueError(msg("請輸入有效的 LUX 數值", "Enter a valid numeric LUX reading")) from None
            if not math.isfinite(reading) or reading < 0:
                raise ValueError(msg("LUX 必須是有限的非負數值", "LUX must be finite and non-negative"))
            if self.index > 0 and reading <= self.readings[0]:
                raise ValueError(msg("照光讀值必須大於背景；請確認讀值或用上一步修正背景", "Light reading must exceed background; check the reading or return to correct background"))
            self.readings[self.levels[self.index]] = reading
            self.table.item(self.index, 1).setText(f"{reading:g}")
            if self.index < len(self.levels) - 1:
                self.index += 1
                self._request_current()
                return
            profile = LightCalibration(channel=self.channel, source_name=self.source_name, unit="lux",
                                       meter=self.meter.text(), geometry=self.geometry.text(), notes=self.notes.text(),
                                       measured_at=datetime.now().astimezone().isoformat(timespec="seconds"),
                                       reference_level=max(self.levels), background=self.readings[0], readings=dict(self.readings))
            profile.require_levels(tuple(self.levels[1:]))
            self.saving = True
            self.ready = False
            self.phase = 'SAVING'
            self._update_controls()
            self.reference_ready.emit(profile)
        except Exception as exc:
            QMessageBox.warning(self, msg("LUX 資料尚未完整", "LUX values incomplete"), str(exc))

    def reject(self):
        if self.saving:
            return  # Saving includes verified OFF; wait for completion.
        self.timer.stop()
        self.ready = False
        self.phase = 'CLOSED'
        self.off_requested.emit()
        super().reject()
