from __future__ import annotations

"""Settings and service screen for the USBRelay8 controller."""

from copy import deepcopy

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QCheckBox, QDialog, QDialogButtonBox, QHBoxLayout, QLabel, QLineEdit,
    QMessageBox, QPushButton, QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget,
)

from .relay_controller import RelayError, RelayService, RelayState
from .relay_settings import RelayGroup, RelaySettings, RelaySettingsStore


class RelaySettingsDialog(QDialog):
    def __init__(self, store: RelaySettingsStore, service: RelayService, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.store, self.service = store, service
        self.working = deepcopy(store.settings)
        self.setWindowTitle("Relay 設定")
        self.resize(980, 640)
        self._build_ui()
        self._write_settings()
        if self.service.controller.connected:
            try:
                self.service.refresh_hardware_state()
            except RelayError:
                pass
            self._refresh_statuses()
        self._refresh_connection_status()

    def _build_ui(self) -> None:
        note = QLabel(
            "Relay 設定會依 VID、PID 與產品名稱重新偵測設備；不會保存 USB 插槽或 HID path。"
            "Channel 個別控制僅供接線確認與維修使用。USBRelay8 繼電器板需確認外部 5 V Relay 電源已接妥。"
        )
        note.setWordWrap(True)
        note.setStyleSheet("background:#edf5fa; border:1px solid #b6cedd; padding:8px;")
        self.connection_label = QLabel()
        self.detect_button = QPushButton("重新偵測設備")
        self.detect_button.clicked.connect(self._detect)
        connection = QHBoxLayout()
        connection.addWidget(self.connection_label, 1)
        connection.addWidget(self.detect_button)

        self.channel_table = QTableWidget(8, 7)
        self.channel_table.setHorizontalHeaderLabels(["Channel", "啟用", "名稱", "用途／連接設備", "Group", "目前狀態", "手動控制"])
        self.channel_table.verticalHeader().setVisible(False)
        self.channel_table.setColumnWidth(0, 70)
        self.channel_table.setColumnWidth(1, 60)
        self.channel_table.setColumnWidth(2, 160)
        self.channel_table.setColumnWidth(3, 240)
        self.channel_table.setColumnWidth(4, 130)
        self.channel_table.setColumnWidth(5, 95)
        for row in range(8):
            item = QTableWidgetItem(f"CH{row + 1}")
            item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsEditable)
            self.channel_table.setItem(row, 0, item)
            enabled = QCheckBox()
            enabled.setStyleSheet("margin-left:18px;")
            self.channel_table.setCellWidget(row, 1, enabled)
            self.channel_table.setCellWidget(row, 2, QLineEdit())
            self.channel_table.setCellWidget(row, 3, QLineEdit())
            self.channel_table.setItem(row, 4, QTableWidgetItem(""))
            state = QTableWidgetItem("未知")
            state.setFlags(state.flags() & ~Qt.ItemFlag.ItemIsEditable)
            self.channel_table.setItem(row, 5, state)
            controls = QWidget()
            layout = QHBoxLayout(controls)
            layout.setContentsMargins(2, 1, 2, 1)
            on, off = QPushButton("開啟"), QPushButton("關閉")
            on.clicked.connect(lambda _checked=False, ch=row + 1: self._channel(ch, True))
            off.clicked.connect(lambda _checked=False, ch=row + 1: self._channel(ch, False))
            layout.addWidget(on); layout.addWidget(off)
            self.channel_table.setCellWidget(row, 6, controls)

        self.group_table = QTableWidget(0, 5)
        self.group_table.setHorizontalHeaderLabels(["Group ID", "顯示名稱", "Member channels（例如 1,2）", "啟用", "目前狀態"])
        self.group_table.setColumnWidth(0, 170)
        self.group_table.setColumnWidth(1, 170)
        self.group_table.setColumnWidth(2, 260)
        self.group_table.setColumnWidth(3, 70)
        self.group_table.setColumnWidth(4, 90)
        self.add_group_button = QPushButton("新增 Group")
        self.remove_group_button = QPushButton("刪除選取 Group")
        self.group_on_button = QPushButton("開啟群組")
        self.group_off_button = QPushButton("關閉群組")
        self.add_group_button.clicked.connect(self._add_group)
        self.remove_group_button.clicked.connect(self._remove_group)
        self.group_on_button.clicked.connect(lambda: self._group(True))
        self.group_off_button.clicked.connect(lambda: self._group(False))
        group_buttons = QHBoxLayout()
        for button in (self.add_group_button, self.remove_group_button, self.group_on_button, self.group_off_button):
            group_buttons.addWidget(button)
        group_buttons.addStretch(1)

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(self._save)
        buttons.rejected.connect(self.reject)
        layout = QVBoxLayout(self)
        layout.addWidget(note)
        layout.addLayout(connection)
        layout.addWidget(QLabel("Channel 設定"))
        layout.addWidget(self.channel_table, 1)
        layout.addWidget(QLabel("Relay Group（同步代表同一次軟體操作，非機械接點的零時間差）"))
        layout.addWidget(self.group_table, 1)
        layout.addLayout(group_buttons)
        layout.addWidget(buttons)

    def _write_settings(self) -> None:
        for row, channel in enumerate(self.working.channels):
            self.channel_table.cellWidget(row, 1).setChecked(channel.enabled)
            self.channel_table.cellWidget(row, 2).setText(channel.display_name)
            self.channel_table.cellWidget(row, 3).setText(channel.description)
        self.group_table.setRowCount(0)
        for group in self.working.groups:
            self._append_group(group)
        self._refresh_statuses()

    def _append_group(self, group: RelayGroup) -> None:
        row = self.group_table.rowCount()
        self.group_table.insertRow(row)
        self.group_table.setCellWidget(row, 0, self._line(group.group_id))
        self.group_table.setCellWidget(row, 1, self._line(group.display_name))
        self.group_table.setCellWidget(row, 2, self._line(",".join(str(item) for item in group.members)))
        enabled = QCheckBox()
        enabled.setChecked(group.enabled)
        enabled.setStyleSheet("margin-left:20px;")
        self.group_table.setCellWidget(row, 3, enabled)
        status = QTableWidgetItem("未知")
        status.setFlags(status.flags() & ~Qt.ItemFlag.ItemIsEditable)
        self.group_table.setItem(row, 4, status)

    @staticmethod
    def _line(value: str) -> QLineEdit:
        widget = QLineEdit(value)
        return widget

    def _read_settings(self) -> RelaySettings:
        settings = deepcopy(self.working)
        for row, channel in enumerate(settings.channels):
            channel.enabled = self.channel_table.cellWidget(row, 1).isChecked()
            channel.display_name = self.channel_table.cellWidget(row, 2).text().strip() or "未使用"
            channel.description = self.channel_table.cellWidget(row, 3).text().strip()
        groups: list[RelayGroup] = []
        for row in range(self.group_table.rowCount()):
            raw_members = self.group_table.cellWidget(row, 2).text().strip()
            try:
                members = [int(value.strip().removeprefix("CH").removeprefix("ch")) for value in raw_members.split(",") if value.strip()]
            except ValueError:
                raise ValueError(f"第 {row + 1} 個 Group 的 member 格式無效")
            groups.append(RelayGroup(
                self.group_table.cellWidget(row, 0).text().strip(), self.group_table.cellWidget(row, 1).text().strip(), members,
                self.group_table.cellWidget(row, 3).isChecked(),
            ))
        settings.groups = groups
        return settings

    def _detect(self) -> None:
        try:
            candidate = self._read_settings()
            errors = candidate.validate()
            if errors:
                raise ValueError("\n".join(errors))
        except Exception as exc:
            QMessageBox.warning(self, "Relay 設定無效", str(exc))
            return
        self._refresh_connection_status(self.service.refresh_connection(candidate))
        self._refresh_statuses()

    def _refresh_connection_status(self, message: str | None = None) -> None:
        text = message or ("Relay 已連線" if self.service.controller.connected else "Relay 未連線")
        self.connection_label.setText(text)
        self.connection_label.setStyleSheet("color:#16823b; font-weight:600;" if self.service.controller.connected else "color:#b3261e; font-weight:600;")

    def _refresh_statuses(self) -> None:
        labels = {
            RelayState.ON: "開啟",
            RelayState.OFF: "關閉",
            RelayState.UNKNOWN: "未知",
            RelayState.ERROR: "錯誤／狀態未知",
            RelayState.PARTIAL: "部分啟用／狀態異常",
        }
        for channel in range(1, 9):
            value = self.service.controller.channel_states[channel]
            self.channel_table.item(channel - 1, 5).setText(labels[value])
        groups_by_channel = {channel: group.display_name for group in self.working.groups for channel in group.members}
        for channel in range(1, 9):
            self.channel_table.item(channel - 1, 4).setText(groups_by_channel.get(channel, ""))
        try:
            runtime_groups = self._read_settings().groups
        except (TypeError, ValueError):
            runtime_groups = self.working.groups
        for row, group in enumerate(runtime_groups):
            self.group_table.item(row, 4).setText(labels[self.service.group_state(group.group_id, group)])

    def _channel(self, channel: int, state: bool) -> None:
        try:
            (self.service.channel_on if state else self.service.channel_off)(channel, "manual_channel")
        except RelayError as exc:
            QMessageBox.warning(self, "Relay 操作失敗", str(exc))
        self._refresh_statuses()

    def _selected_group_id(self) -> str | None:
        row = self.group_table.currentRow()
        return self.group_table.cellWidget(row, 0).text().strip() if row >= 0 else None

    def _group(self, state: bool) -> None:
        group_id = self._selected_group_id()
        if not group_id:
            QMessageBox.information(self, "選擇 Group", "請先選擇要操作的 Relay Group。")
            return
        try:
            candidate = self._read_settings()
            errors = candidate.validate()
            if errors:
                raise ValueError("\n".join(errors))
            group = candidate.group(group_id)
            if group is None:
                raise ValueError(f"找不到 Relay Group：{group_id}")
            (self.service.group_on if state else self.service.group_off)(group_id, "manual_group", group)
        except (RelayError, ValueError) as exc:
            QMessageBox.warning(self, "Relay Group 操作失敗", str(exc))
        self._refresh_statuses()

    def _add_group(self) -> None:
        self._append_group(RelayGroup("new_group", "新群組", [1]))

    def _remove_group(self) -> None:
        row = self.group_table.currentRow()
        if row >= 0:
            self.group_table.removeRow(row)

    def _save(self) -> None:
        try:
            settings = self._read_settings()
            errors = settings.validate()
            if errors:
                raise ValueError("\n".join(errors))
            self.store.settings = settings
            self.store.save()
        except Exception as exc:
            QMessageBox.warning(self, "Relay 設定無效", str(exc))
            return
        self.accept()
