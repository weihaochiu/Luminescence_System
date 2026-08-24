from __future__ import annotations

from PySide6.QtCore import QSignalBlocker, Signal
from PySide6.QtWidgets import (
    QAbstractItemView,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from core.i18n import i18n, tr

from .smu_base import SMUDevice
from .instrument_state_manager import SMUInstrumentState, SMUUIState
from .recipe_store import Recipe
from .el_matrix_plan import ELMatrixPlan


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
        self._recipe_capture_counts: dict[str, int] = {}
        self._last_smu_ui_state: SMUUIState | None = None
        self._status_mode = "disconnected"
        self._status_device = ""

        self.camera_list = QListWidget()
        self.camera_list.setMaximumHeight(118)
        self.camera_list.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)

        self.smu_list = QListWidget()
        self.smu_list.setMaximumHeight(132)
        self.smu_list.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.smu_list.setToolTip(tr("smu.select_tooltip"))

        self.recipe_list = QListWidget()
        self.recipe_list.setMaximumHeight(165)
        self.recipe_list.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.recipe_list.setToolTip(tr("recipe.available_only_tooltip"))
        self.recipe_empty_label = QLabel(tr("recipe.none_available"))
        self.recipe_empty_label.setWordWrap(True)
        self.recipe_empty_label.setStyleSheet("color:#687078; padding:6px;")

        self.smu_state = QLabel(tr("common.state_disconnected"))
        self.smu_state.setObjectName("smuState")
        self.smu_state.setWordWrap(True)
        self.smu_state.setStyleSheet("color: #687078; font-weight: 600;")

        self.smu_scan_button = QPushButton(tr("common.rescan"))
        self.smu_connect_button = QPushButton(tr("common.connect"))
        self.smu_disconnect_button = QPushButton(tr("common.disconnect"))
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
        i18n.language_changed.connect(self.retranslate)
        self._update_buttons()

    def retranslate(self, _language: str = "") -> None:
        self.smu_list.setToolTip(tr("smu.select_tooltip"))
        self.recipe_list.setToolTip(tr("recipe.available_only_tooltip"))
        self.recipe_empty_label.setText(tr("recipe.none_available"))
        self.smu_scan_button.setText(tr("common.rescan"))
        self.smu_connect_button.setText(tr("common.connect"))
        self.smu_disconnect_button.setText(tr("common.disconnect"))
        self._retranslate_smu_items()
        self._retranslate_recipe_items()
        if self._last_smu_ui_state is not None:
            self.apply_smu_ui_state(self._last_smu_ui_state)
        else:
            status = {
                "scanning": tr("common.state_scanning"),
                "connecting": tr("common.state_connecting"),
                "connected": tr("common.state_connected_to", device=self._status_device),
                "error": tr("common.state_error"),
                "disconnected": tr("common.state_disconnected"),
            }[self._status_mode]
            self.smu_state.setText(status)

    def _retranslate_smu_items(self) -> None:
        blocker = QSignalBlocker(self.smu_list)
        for row, device in enumerate(self.smu_devices):
            item = self.smu_list.item(row)
            if item is None:
                continue
            suffix = tr("smu.b2900_driver_suffix") if device.supported else tr("smu.generic_scpi_suffix")
            serial = tr("smu.serial_line", serial=device.serial_number) if device.serial_number else ""
            item.setText(tr("smu.device_list_entry", name=device.display_name, suffix=suffix, serial=serial, resource=device.visa_address))
        del blocker

    def _retranslate_recipe_items(self) -> None:
        blocker = QSignalBlocker(self.recipe_list)
        for row, recipe in enumerate(self.recipes):
            item = self.recipe_list.item(row)
            if item is None:
                continue
            captures = self._recipe_capture_counts.get(
                recipe.recipe_id, recipe.matrix_capture_counts()["overall"]
            )
            item.setText(tr("recipe.list_summary", name=recipe.name, version=recipe.version, channels=len(recipe.enabled_channels()), captures=captures))
            item.setToolTip((recipe.description + "\n" if recipe.description else "") + tr("recipe.preview_tooltip"))
        del blocker

    def set_smu_devices(self, devices: list[SMUDevice], preferred_address: str = "") -> None:
        self.smu_devices = list(devices)
        self.smu_list.clear()
        preferred_row = -1
        for row, device in enumerate(devices):
            suffix = tr("smu.b2900_driver_suffix") if device.supported else tr("smu.generic_scpi_suffix")
            serial = tr("smu.serial_line", serial=device.serial_number) if device.serial_number else ""
            self.smu_list.addItem(
                tr("smu.device_list_entry", name=device.display_name, suffix=suffix,
                   serial=serial, resource=device.visa_address)
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

    def set_recipes(
        self,
        recipes: list[Recipe],
        preferred_id: str = "",
        *,
        global_safety: object | None = None,
    ) -> None:
        self.recipes = list(recipes)
        self._recipe_capture_counts = {}
        self.recipe_list.clear()
        preferred_row = -1
        for row, recipe in enumerate(self.recipes):
            try:
                counts = ELMatrixPlan(
                    recipe,
                    global_safety=global_safety,
                ).capture_counts()
            except ValueError:
                counts = recipe.matrix_capture_counts()
            self._recipe_capture_counts[recipe.recipe_id] = counts["overall"]
            self.recipe_list.addItem(
                tr("recipe.list_summary", name=recipe.name, version=recipe.version,
                   channels=len(recipe.enabled_channels()), captures=counts["overall"])
            )
            self.recipe_list.item(row).setToolTip(
                (recipe.description + "\n" if recipe.description else "")
                + tr("recipe.preview_tooltip")
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
        self._last_smu_ui_state = None
        self._status_mode = "scanning"
        self.smu_state.setText(tr("common.state_scanning"))
        self.smu_state.setStyleSheet("color: #c48a00; font-weight: 600;")
        self._set_busy(True)

    def set_smu_connecting(self) -> None:
        self._last_smu_ui_state = None
        self._status_mode = "connecting"
        self.smu_state.setText(tr("common.state_connecting"))
        self.smu_state.setStyleSheet("color: #c48a00; font-weight: 600;")
        self._set_busy(True)

    def set_smu_connected(self, device: SMUDevice) -> None:
        self._last_smu_ui_state = None
        self._status_mode = "connected"
        self._status_device = device.model or device.display_name
        self.smu_state.setText(tr("common.state_connected_to", device=device.model or device.display_name))
        self.smu_state.setStyleSheet("color: #16823b; font-weight: 600;")
        self.smu_list.setEnabled(False)
        self.smu_scan_button.setEnabled(False)
        self.smu_connect_button.setEnabled(False)
        self.smu_disconnect_button.setEnabled(True)

    def set_smu_disconnected(self, error: bool = False) -> None:
        self._last_smu_ui_state = None
        self._status_mode = "error" if error else "disconnected"
        self.smu_state.setText(tr("common.state_error") if error else tr("common.state_disconnected"))
        color = "#c62828" if error else "#687078"
        self.smu_state.setStyleSheet(f"color: {color}; font-weight: 600;")
        self.smu_list.setEnabled(True)
        self._update_buttons()

    def apply_smu_ui_state(self, state: SMUUIState) -> None:
        self._last_smu_ui_state = state
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
