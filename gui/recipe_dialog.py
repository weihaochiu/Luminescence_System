from __future__ import annotations

"""Recipe manager dialog shell.

The shell owns navigation and layout.  Page construction, EL point behavior,
and Recipe persistence are separated into three cohesive modules.
"""

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
    QVBoxLayout,
    QWidget,
)

from .recipe_dialog_logic import RecipeDialogLogicMixin
from .recipe_dialog_pages import RecipeDialogPagesMixin
from .recipe_dialog_points import RecipeDialogPointsMixin
from .recipe_store import Recipe, RecipeStore


class RecipeManagerDialog(
    QDialog,
    RecipeDialogPagesMixin,
    RecipeDialogPointsMixin,
    RecipeDialogLogicMixin,
):
    """Dialog shell and stable public entry point for Recipe management."""

    recipes_changed = Signal()

    POINT_COLUMNS = ["啟用", "設定值", "Dwell (s)", "Exposure (ms) *", "Gain (%) *", "Frames *", "間隔 (s) *"]
    CAMERA_COLUMNS = range(3, 7)
    CAMERA_VALUE_ROLE = int(Qt.ItemDataRole.UserRole) + 1
    HDR_CELL_TEXT = "啟用 HDR"

    def __init__(self, store: RecipeStore, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.store = store
        self.current_recipe: Recipe | None = None
        self.setWindowTitle("EL Recipe 管理－四階段流程")
        self.resize(1500, 850)
        self.setMinimumSize(1180, 700)
        self._build_ui()
        self._connect_summary_updates()
        self._reload_list()

    def _build_ui(self) -> None:
        self.search_edit = QLineEdit()
        self.search_edit.setPlaceholderText("搜尋 Recipe…")
        self.recipe_list = QListWidget()
        self.recipe_list.setMinimumWidth(230)
        self.new_button = QPushButton("新增")
        self.copy_button = QPushButton("複製")
        self.delete_button = QPushButton("刪除")
        self.import_button = QPushButton("匯入")
        self.export_button = QPushButton("匯出")

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
        left_layout.addWidget(QLabel("所有 Recipe"))
        left_layout.addWidget(self.search_edit)
        left_layout.addWidget(self.recipe_list, 1)
        left_layout.addLayout(list_buttons)
        left_layout.addLayout(transfer_buttons)

        self.tabs = QTabWidget()
        self.tabs.addTab(self._build_basic_tab(), "1 基本／樣品")
        self.tabs.addTab(self._build_el_matrix_tab(), "2 EL Matrix")
        self.tabs.addTab(self._build_polarity_tab(), "3 極性確認")
        self.tabs.addTab(self._build_dark_iv_tab(), "4 Legacy Dark I–V")
        self.tabs.addTab(self._build_camera_tab(), "4 相機／非 HDR 預設")
        self.tabs.addTab(self._build_el_tab(), "5 EL 點位")
        self.tabs.addTab(self._build_dark_frame_tab(), "7 Legacy Dark Frames")
        self.tabs.addTab(self._build_safety_tab(), "8 安全／SMU")
        self.tabs.addTab(self._build_output_tab(), "9 輸出")

        self.summary_label = QLabel("請選擇或新增 Recipe")
        self.summary_label.setAlignment(Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignLeft)
        self.summary_label.setWordWrap(True)
        self.summary_label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self.summary_label.setStyleSheet("background:#f6f7f8; border:1px solid #c9cdd0; padding:12px;")
        self.validation_label = QLabel("尚未驗證")
        self.validation_label.setWordWrap(True)
        self.validation_label.setStyleSheet("color:#687078; padding:6px;")
        right = QWidget()
        right.setMinimumWidth(310)
        right.setMaximumWidth(390)
        right_layout = QVBoxLayout(right)
        right_layout.setContentsMargins(0, 0, 0, 0)
        right_layout.addWidget(QLabel("完整執行流程摘要"))
        right_layout.addWidget(self.summary_label, 1)
        right_layout.addWidget(QLabel("驗證結果"))
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

        self.validate_button = QPushButton("驗證")
        self.save_button = QPushButton("儲存")
        self.save_button.setDefault(True)
        self.close_button = QPushButton("關閉")
        footer = QHBoxLayout()
        footer.addWidget(QLabel("EL Matrix 只使用啟用的 Logical Channel；只有啟用且通過驗證的 Recipe 會顯示在主畫面。"))
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
