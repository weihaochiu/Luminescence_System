from __future__ import annotations

"""Settings dialog for ordering and showing registered sidebar items."""

import logging

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QAbstractItemView,
    QDialog,
    QDialogButtonBox,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from core.i18n import tr

from .registry import SidebarItemState, SidebarRegistry


LOGGER = logging.getLogger(__name__)


class SidebarSettingsDialog(QDialog):
    """Edit registry state; Apply updates the existing main-window widgets."""

    def __init__(self, registry: SidebarRegistry, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.registry = registry
        self.setWindowTitle(tr("settings.sidebar_title"))
        self.setMinimumSize(430, 430)

        intro = QLabel(tr("settings.sidebar_description"))
        intro.setWordWrap(True)

        self.item_list = QListWidget()
        self.item_list.setObjectName("sidebarSettingsList")
        self.item_list.setDragDropMode(QAbstractItemView.DragDropMode.InternalMove)
        self.item_list.setDefaultDropAction(Qt.DropAction.MoveAction)
        self.item_list.setDragDropOverwriteMode(False)
        self.item_list.setDropIndicatorShown(True)
        self.item_list.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)

        self.show_all_button = QPushButton(tr("settings.show_all"))
        self.reset_button = QPushButton(tr("settings.restore_defaults"))
        utility_buttons = QHBoxLayout()
        utility_buttons.addWidget(self.show_all_button)
        utility_buttons.addWidget(self.reset_button)
        utility_buttons.addStretch(1)

        self.buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok
            | QDialogButtonBox.StandardButton.Cancel
            | QDialogButtonBox.StandardButton.Apply
        )
        self.buttons.button(QDialogButtonBox.StandardButton.Ok).setText(tr("common.ok"))
        self.buttons.button(QDialogButtonBox.StandardButton.Cancel).setText(tr("common.cancel"))
        self.buttons.button(QDialogButtonBox.StandardButton.Apply).setText(tr("common.apply"))

        layout = QVBoxLayout(self)
        layout.addWidget(intro)
        layout.addWidget(self.item_list, 1)
        layout.addLayout(utility_buttons)
        layout.addWidget(self.buttons)

        self.show_all_button.clicked.connect(self.show_all)
        self.reset_button.clicked.connect(self.reset_defaults)
        self.buttons.button(QDialogButtonBox.StandardButton.Apply).clicked.connect(self.apply)
        self.buttons.accepted.connect(self._accept)
        self.buttons.rejected.connect(self.reject)

        self._populate(self.registry.active_states)

    def states(self) -> list[SidebarItemState]:
        states: list[SidebarItemState] = []
        for row in range(self.item_list.count()):
            item = self.item_list.item(row)
            states.append(
                SidebarItemState(
                    str(item.data(Qt.ItemDataRole.UserRole)),
                    item.checkState() == Qt.CheckState.Checked,
                )
            )
        return states

    def show_all(self) -> None:
        for row in range(self.item_list.count()):
            self.item_list.item(row).setCheckState(Qt.CheckState.Checked)

    def reset_defaults(self) -> None:
        self._populate(self.registry.default_states())
        LOGGER.info("SIDEBAR settings reset to defaults")

    def apply(self) -> None:
        self.registry.save_and_apply(self.states())

    def _accept(self) -> None:
        self.apply()
        self.accept()

    def _populate(self, states: list[SidebarItemState]) -> None:
        metadata = {item.id: item for item in self.registry.items}
        self.item_list.clear()
        for state in states:
            item = QListWidgetItem(metadata[state.id].display_name)
            item.setData(Qt.ItemDataRole.UserRole, state.id)
            item.setCheckState(
                Qt.CheckState.Checked if state.visible else Qt.CheckState.Unchecked
            )
            item.setFlags(
                item.flags()
                | Qt.ItemFlag.ItemIsUserCheckable
                | Qt.ItemFlag.ItemIsDragEnabled
                | Qt.ItemFlag.ItemIsDropEnabled
            )
            self.item_list.addItem(item)
