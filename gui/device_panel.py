from __future__ import annotations

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QAbstractItemView,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from .smu_base import SMUDevice
from .instrument_state_manager import SMUInstrumentState, SMUUIState
from .recipe_store import Recipe


class DevicePanel(QWidget):
    """Camera and SMU selection widgets for the left equipment area."""

    smu_scan_requested = Signal()
    smu_connect_requested = Signal()
    smu_disconnect_requested = Signal()
    smu_selection_changed = Signal(str)
    recipe_selection_changed = Signal(str)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.smu_devices: list[SMUDevice] = []
        self.recipes: list[Recipe] = []

        self.camera_list = QListWidget()
        self.camera_list.setMaximumHeight(118)
        self.camera_list.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)

        self.smu_list = QListWidget()
        self.smu_list.setMaximumHeight(132)
        self.smu_list.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.smu_list.setToolTip("選取 VISA 儀器後按「連線」；選取本身不會自動連線。")

        self.recipe_list = QListWidget()
        self.recipe_list.setMaximumHeight(165)
        self.recipe_list.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.recipe_list.setToolTip("此處只顯示已啟用且通過驗證的 Recipe。")
        self.recipe_empty_label = QLabel("尚無可用 Recipe\n請從「設定 → Recipe 管理」建立")
        self.recipe_empty_label.setWordWrap(True)
        self.recipe_empty_label.setStyleSheet("color:#687078; padding:6px;")

        self.smu_state = QLabel("● 未連線")
        self.smu_state.setObjectName("smuState")
        self.smu_state.setWordWrap(True)
        self.smu_state.setStyleSheet("color: #687078; font-weight: 600;")

        self.smu_scan_button = QPushButton("重新掃描")
        self.smu_connect_button = QPushButton("連線")
        self.smu_disconnect_button = QPushButton("中斷")
        self.smu_disconnect_button.setEnabled(False)

        buttons = QHBoxLayout()
        buttons.addWidget(self.smu_scan_button)
        buttons.addWidget(self.smu_connect_button)
        buttons.addWidget(self.smu_disconnect_button)

        self.camera_content = QWidget()
        camera_layout = QVBoxLayout(self.camera_content)
        camera_layout.setContentsMargins(8, 6, 8, 8)
        camera_layout.addWidget(self.camera_list)

        self.smu_content = QWidget()
        smu_layout = QVBoxLayout(self.smu_content)
        smu_layout.setContentsMargins(8, 6, 8, 8)
        smu_layout.addWidget(self.smu_state)
        smu_layout.addWidget(self.smu_list)
        smu_layout.addLayout(buttons)

        self.recipe_content = QWidget()
        recipe_layout = QVBoxLayout(self.recipe_content)
        recipe_layout.setContentsMargins(8, 6, 8, 8)
        recipe_layout.addWidget(self.recipe_empty_label)
        recipe_layout.addWidget(self.recipe_list)

        self.smu_scan_button.clicked.connect(lambda _checked=False: self.smu_scan_requested.emit())
        self.smu_connect_button.clicked.connect(
            lambda _checked=False: self.smu_connect_requested.emit()
        )
        self.smu_disconnect_button.clicked.connect(
            lambda _checked=False: self.smu_disconnect_requested.emit()
        )
        self.smu_list.currentRowChanged.connect(self._emit_selected_address)
        self.recipe_list.currentRowChanged.connect(self._emit_selected_recipe)
        self._update_buttons()

    def set_smu_devices(self, devices: list[SMUDevice], preferred_address: str = "") -> None:
        self.smu_devices = list(devices)
        self.smu_list.clear()
        preferred_row = -1
        for row, device in enumerate(devices):
            suffix = "（B2900 驅動）" if device.supported else "（一般 SCPI）"
            serial = f"S/N：{device.serial_number}\n" if device.serial_number else ""
            self.smu_list.addItem(
                f"{device.display_name} {suffix}\n{serial}{device.visa_address}"
            )
            self.smu_list.item(row).setToolTip(device.idn or device.visa_address)
            if device.visa_address == preferred_address:
                preferred_row = row
        if devices:
            self.smu_list.setCurrentRow(preferred_row if preferred_row >= 0 else 0)
        self._update_buttons()

    def selected_smu(self) -> SMUDevice | None:
        row = self.smu_list.currentRow()
        return self.smu_devices[row] if 0 <= row < len(self.smu_devices) else None

    def select_smu(self, visa_address: str) -> None:
        for row, device in enumerate(self.smu_devices):
            if device.visa_address == visa_address:
                self.smu_list.setCurrentRow(row)
                return

    def set_recipes(self, recipes: list[Recipe], preferred_id: str = "") -> None:
        self.recipes = list(recipes)
        self.recipe_list.clear()
        preferred_row = -1
        for row, recipe in enumerate(self.recipes):
            mode = "I" if recipe.el_sweep.drive_mode == "current" else "V"
            profiles = len(recipe.dark_profiles())
            self.recipe_list.addItem(
                f"{recipe.name}\nv{recipe.version}｜{mode} mode｜"
                f"{len(recipe.enabled_points())} 點｜{profiles} Dark"
            )
            self.recipe_list.item(row).setToolTip(
                (recipe.description + "\n" if recipe.description else "")
                + "流程：極性確認 → Dark I–V → Dark Frames → EL"
            )
            if recipe.recipe_id == preferred_id:
                preferred_row = row
        has_recipes = bool(self.recipes)
        self.recipe_empty_label.setVisible(not has_recipes)
        self.recipe_list.setVisible(has_recipes)
        if has_recipes:
            self.recipe_list.setCurrentRow(preferred_row if preferred_row >= 0 else 0)

    def selected_recipe(self) -> Recipe | None:
        row = self.recipe_list.currentRow()
        return self.recipes[row] if 0 <= row < len(self.recipes) else None

    def set_smu_scanning(self) -> None:
        self.smu_state.setText("● 掃描中")
        self.smu_state.setStyleSheet("color: #c48a00; font-weight: 600;")
        self._set_busy(True)

    def set_smu_connecting(self) -> None:
        self.smu_state.setText("● 連線中")
        self.smu_state.setStyleSheet("color: #c48a00; font-weight: 600;")
        self._set_busy(True)

    def set_smu_connected(self, device: SMUDevice) -> None:
        self.smu_state.setText(f"● 已連線：{device.model or device.display_name}")
        self.smu_state.setStyleSheet("color: #16823b; font-weight: 600;")
        self.smu_list.setEnabled(False)
        self.smu_scan_button.setEnabled(False)
        self.smu_connect_button.setEnabled(False)
        self.smu_disconnect_button.setEnabled(True)

    def set_smu_disconnected(self, error: bool = False) -> None:
        self.smu_state.setText("● 錯誤" if error else "● 未連線")
        color = "#c62828" if error else "#687078"
        self.smu_state.setStyleSheet(f"color: {color}; font-weight: 600;")
        self.smu_list.setEnabled(True)
        self._update_buttons()

    def apply_smu_ui_state(self, state: SMUUIState) -> None:
        self.smu_state.setText(state.status_text)
        colors = {
            SMUInstrumentState.DISCONNECTED: "#687078",
            SMUInstrumentState.CONNECTING: "#c48a00",
            SMUInstrumentState.READY_MANUAL: "#16823b",
            SMUInstrumentState.MANUAL_OUTPUT_ON: "#9a5c00",
            SMUInstrumentState.TRANSITIONING: "#8a5a00",
            SMUInstrumentState.AUTO_RUNNING: "#8a5a00",
            SMUInstrumentState.UNEXPECTED_OUTPUT_ON: "#c62828",
            SMUInstrumentState.OUTPUT_UNKNOWN: "#c62828",
            SMUInstrumentState.ERROR: "#c62828",
            SMUInstrumentState.EMERGENCY_STOP: "#9b111e",
        }
        self.smu_state.setStyleSheet(
            f"color: {colors[state.state]}; font-weight: 600;"
        )
        self.smu_state.setToolTip(state.manual_lock_reason or state.status_text)

    def _set_busy(self, busy: bool) -> None:
        self.smu_list.setEnabled(not busy)
        self.smu_scan_button.setEnabled(not busy)
        self.smu_connect_button.setEnabled(not busy and self.selected_smu() is not None)
        self.smu_disconnect_button.setEnabled(False)

    def _update_buttons(self) -> None:
        self.smu_scan_button.setEnabled(True)
        self.smu_connect_button.setEnabled(self.selected_smu() is not None)
        self.smu_disconnect_button.setEnabled(False)

    def _emit_selected_address(self, _row: int = -1) -> None:
        self._update_buttons()
        selected = self.selected_smu()
        self.smu_selection_changed.emit(selected.visa_address if selected else "")

    def _emit_selected_recipe(self, _row: int = -1) -> None:
        selected = self.selected_recipe()
        self.recipe_selection_changed.emit(selected.recipe_id if selected else "")
