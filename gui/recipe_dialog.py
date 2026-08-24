from __future__ import annotations

"""Four-page Recipe manager with a persistent execution-plan preview."""

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QPushButton,
    QTabWidget,
    QTreeWidget,
    QVBoxLayout,
    QWidget,
)

from core.i18n import tr

from .recipe_dialog_logic import RecipeDialogLogicMixin
from .recipe_dialog_pages import RecipeDialogPagesMixin
from .recipe_store import Recipe, RecipeStore


class RecipeManagerDialog(
    QDialog,
    RecipeDialogPagesMixin,
    RecipeDialogLogicMixin,
):
    """Dialog shell and stable public entry point for Recipe management."""

    recipes_changed = Signal()

    def __init__(
        self,
        store: RecipeStore,
        parent: QWidget | None = None,
        *,
        camera_resolutions: list[tuple[int, int]] | None = None,
    ) -> None:
        super().__init__(parent)
        self.store = store
        self.current_recipe: Recipe | None = None
        self.setWindowTitle(tr("recipe.dialog_title"))
        self.resize(1500, 850)
        self.setMinimumSize(1180, 700)
        self._build_ui()
        if camera_resolutions:
            self.resolution_combo.clear()
            for index, (width, height) in enumerate(camera_resolutions):
                self.resolution_combo.addItem(
                    f"{width} × {height}", f"sdk:{index}"
                )
        self._connect_summary_updates()
        self._reload_list()

    def _build_ui(self) -> None:
        self.search_edit = QLineEdit()
        self.search_edit.setPlaceholderText(tr("recipe.search"))
        self.recipe_list = QListWidget()
        self.recipe_list.setMinimumWidth(230)
        self.new_button = QPushButton(tr("common.new"))
        self.copy_button = QPushButton(tr("common.copy"))
        self.delete_button = QPushButton(tr("common.delete"))
        self.import_button = QPushButton(tr("common.import"))
        self.export_button = QPushButton(tr("common.export"))

        list_buttons = QHBoxLayout()
        list_buttons.addWidget(self.new_button)
        list_buttons.addWidget(self.copy_button)
        list_buttons.addWidget(self.delete_button)
        transfer_buttons = QHBoxLayout()
        transfer_buttons.addWidget(self.import_button)
        transfer_buttons.addWidget(self.export_button)
        left = QWidget()
        left_layout = QVBoxLayout(left)
        left_layout.setContentsMargins(0, 0, 0, 0)
        left_layout.addWidget(QLabel(tr("recipe.all")))
        left_layout.addWidget(self.search_edit)
        left_layout.addWidget(self.recipe_list, 1)
        left_layout.addLayout(list_buttons)
        left_layout.addLayout(transfer_buttons)

        self.tabs = QTabWidget()
        self.tabs.addTab(self._build_basic_tab(), tr("recipe.tab_basic"))
        self.tabs.addTab(self._build_polarity_dark_iv_tab(), tr("recipe.tab_polarity_dark"))
        self.tabs.addTab(self._build_el_matrix_tab(), tr("recipe.tab_matrix"))
        self.tabs.addTab(self._build_output_tab(), tr("recipe.tab_output"))

        self.execution_tree = QTreeWidget()
        self.execution_tree.setHeaderHidden(True)
        self.execution_tree.setStyleSheet(
            "background:#f6f7f8; border:1px solid #c9cdd0; padding:6px;"
        )
        self.validation_label = QLabel(tr("recipe.not_validated"))
        self.validation_label.setWordWrap(True)
        self.validation_label.setStyleSheet("color:#687078; padding:6px;")
        right = QWidget()
        right.setMinimumWidth(310)
        right.setMaximumWidth(390)
        right_layout = QVBoxLayout(right)
        right_layout.setContentsMargins(0, 0, 0, 0)
        right_layout.addWidget(QLabel(tr("recipe.execution_plan")))
        right_layout.addWidget(self.execution_tree, 1)
        right_layout.addWidget(QLabel(tr("recipe.validation_result")))
        right_layout.addWidget(self.validation_label)

        divider1 = QFrame()
        divider1.setFrameShape(QFrame.Shape.VLine)
        divider2 = QFrame()
        divider2.setFrameShape(QFrame.Shape.VLine)
        columns = QHBoxLayout()
        columns.addWidget(left)
        columns.addWidget(divider1)
        columns.addWidget(self.tabs, 1)
        columns.addWidget(divider2)
        columns.addWidget(right)

        self.validate_button = QPushButton(tr("common.validate"))
        self.save_button = QPushButton(tr("common.save"))
        self.save_button.setDefault(True)
        self.close_button = QPushButton(tr("common.close"))
        footer = QHBoxLayout()
        footer.addWidget(QLabel(tr("recipe.footer_settings_note")))
        footer.addStretch()
        footer.addWidget(self.validate_button)
        footer.addWidget(self.save_button)
        footer.addWidget(self.close_button)

        layout = QVBoxLayout(self)
        layout.addLayout(columns, 1)
        layout.addLayout(footer)

        self.search_edit.textChanged.connect(self._reload_list)
        self.recipe_list.currentItemChanged.connect(self._load_selected)
        self.new_button.clicked.connect(self._new_recipe)
        self.copy_button.clicked.connect(self._copy_recipe)
        self.delete_button.clicked.connect(self._delete_recipe)
        self.import_button.clicked.connect(self._import_recipe)
        self.export_button.clicked.connect(self._export_recipe)
        self.validate_button.clicked.connect(self._validate_current)
        self.save_button.clicked.connect(self._save_current)
        self.close_button.clicked.connect(self.accept)
