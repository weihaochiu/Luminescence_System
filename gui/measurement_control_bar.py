from __future__ import annotations

"""Reusable measurement context/actions bar with responsive rearrangement."""

from PySide6.QtWidgets import (
    QFrame,
    QGridLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QSizePolicy,
)

from .responsive_layout import LayoutMode


class MeasurementControlBar(QFrame):
    """Own one widget set and move it between WIDE/STANDARD/COMPACT grids."""

    def __init__(self, parent: QFrame | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("measurementBar")
        self.layout_mode = LayoutMode.WIDE

        self.sample_label = QLabel("樣品 ID")
        self.sample_id_edit = QLineEdit()
        self.sample_id_edit.setPlaceholderText("輸入樣品 ID")

        self.path_label = QLabel("儲存位置")
        self.measurement_path_edit = QLineEdit()
        self.measurement_path_edit.setReadOnly(True)
        self.measurement_path_edit.setPlaceholderText("選擇量測資料儲存位置")
        self.measurement_path_edit.textChanged.connect(self.measurement_path_edit.setToolTip)
        self.measurement_path_button = QPushButton("瀏覽…")

        self.recipe_label = QLabel("Recipe")
        self.selected_recipe_label = QLabel("尚未選擇")
        self.selected_recipe_label.setWordWrap(True)
        self.hdr_session_button = QPushButton("HDR：未設定")

        self.white_light_status = QLabel("白光 ● 未連線")
        self.white_light_button = QPushButton("開啟白光")
        self.start_measurement_button = QPushButton("開始量測")
        self.start_measurement_button.setObjectName("startMeasurement")
        self.stop_measurement_button = QPushButton("停止")
        self.stop_measurement_button.setObjectName("stopMeasurement")
        self.stop_measurement_button.setEnabled(False)
        self.emergency_stop_button = QPushButton("Emergency Stop")
        self.emergency_stop_button.setObjectName("emergencyStop")
        self.emergency_stop_button.setToolTip(
            "Immediately blocks new output; OUTPUT OFF runs after active VISA I/O, then source is zeroed."
        )

        self._widgets = (
            self.sample_label,
            self.sample_id_edit,
            self.path_label,
            self.measurement_path_edit,
            self.measurement_path_button,
            self.recipe_label,
            self.selected_recipe_label,
            self.hdr_session_button,
            self.white_light_status,
            self.white_light_button,
            self.start_measurement_button,
            self.stop_measurement_button,
            self.emergency_stop_button,
        )
        self._configure_size_policies()

        self.grid = QGridLayout(self)
        self.grid.setContentsMargins(10, 7, 10, 7)
        self.grid.setHorizontalSpacing(7)
        self.grid.setVerticalSpacing(6)
        self.set_layout_mode(LayoutMode.WIDE)

    def _configure_size_policies(self) -> None:
        expanding = QSizePolicy.Policy.MinimumExpanding
        preferred = QSizePolicy.Policy.Preferred
        minimum = QSizePolicy.Policy.Minimum
        fixed = QSizePolicy.Policy.Fixed

        self.sample_id_edit.setSizePolicy(preferred, fixed)
        self.measurement_path_edit.setSizePolicy(expanding, fixed)
        self.selected_recipe_label.setSizePolicy(expanding, preferred)
        self.hdr_session_button.setSizePolicy(minimum, fixed)
        for button in (
            self.measurement_path_button,
            self.white_light_button,
            self.start_measurement_button,
            self.stop_measurement_button,
            self.emergency_stop_button,
        ):
            button.setSizePolicy(minimum, fixed)

        self.refresh_metrics()

    def refresh_metrics(self) -> None:
        """Recalculate runtime font/style-dependent minimum widths."""

        metrics = self.fontMetrics()
        self.sample_id_edit.setMinimumWidth(metrics.horizontalAdvance("M" * 12))
        self.measurement_path_edit.setMinimumWidth(metrics.horizontalAdvance("M" * 16))
        self.selected_recipe_label.setMinimumWidth(metrics.horizontalAdvance("MMMMMM"))
        for button in (
            self.measurement_path_button,
            self.hdr_session_button,
            self.white_light_button,
            self.start_measurement_button,
            self.stop_measurement_button,
            self.emergency_stop_button,
        ):
            button.setMinimumWidth(metrics.horizontalAdvance(button.text()) + 28)

    def recommended_breakpoints(self) -> tuple[int, int]:
        """Return content-aware logical-pixel breakpoints for this font."""

        metrics = self.fontMetrics()
        action_width = sum(
            metrics.horizontalAdvance(button.text()) + 36
            for button in (
                self.white_light_button,
                self.start_measurement_button,
                self.stop_measurement_button,
                self.emergency_stop_button,
            )
        )
        standard = max(1080, action_width + metrics.horizontalAdvance("M" * 35))
        wide = max(1500, action_width + metrics.horizontalAdvance("M" * 92))
        return standard, wide

    def set_layout_mode(self, mode: LayoutMode) -> None:
        self.layout_mode = LayoutMode(mode)
        while self.grid.count():
            self.grid.takeAt(0)
        for index in range(14):
            self.grid.setColumnStretch(index, 0)
        for index in range(6):
            self.grid.setRowStretch(index, 0)

        if self.layout_mode is LayoutMode.WIDE:
            self._layout_wide()
        elif self.layout_mode is LayoutMode.STANDARD:
            self._layout_standard()
        else:
            self._layout_compact()

    def _layout_wide(self) -> None:
        widgets = (
            self.sample_label,
            self.sample_id_edit,
            self.path_label,
            self.measurement_path_edit,
            self.measurement_path_button,
            self.recipe_label,
            self.selected_recipe_label,
            self.hdr_session_button,
            self.white_light_status,
            self.white_light_button,
            self.start_measurement_button,
            self.stop_measurement_button,
            self.emergency_stop_button,
        )
        for column, widget in enumerate(widgets):
            self.grid.addWidget(widget, 0, column)
        self.recipe_label.setVisible(True)
        self.grid.setColumnStretch(3, 2)
        self.grid.setColumnStretch(6, 1)

    def _layout_standard(self) -> None:
        self.recipe_label.setVisible(True)
        self.grid.addWidget(self.sample_label, 0, 0)
        self.grid.addWidget(self.sample_id_edit, 0, 1)
        self.grid.addWidget(self.recipe_label, 0, 2)
        self.grid.addWidget(self.selected_recipe_label, 0, 3, 1, 2)
        self.grid.addWidget(self.hdr_session_button, 0, 5)

        self.grid.addWidget(self.path_label, 1, 0)
        self.grid.addWidget(self.measurement_path_edit, 1, 1, 1, 4)
        self.grid.addWidget(self.measurement_path_button, 1, 5)

        self.grid.addWidget(self.white_light_status, 2, 0)
        self.grid.addWidget(self.white_light_button, 2, 1)
        self.grid.addWidget(self.start_measurement_button, 2, 3)
        self.grid.addWidget(self.stop_measurement_button, 2, 4)
        self.grid.addWidget(self.emergency_stop_button, 2, 5)
        self.grid.setColumnStretch(3, 1)

    def _layout_compact(self) -> None:
        self.recipe_label.setVisible(True)
        self.grid.addWidget(self.sample_label, 0, 0)
        self.grid.addWidget(self.sample_id_edit, 0, 1, 1, 4)

        self.grid.addWidget(self.recipe_label, 1, 0)
        self.grid.addWidget(self.selected_recipe_label, 1, 1, 1, 4)

        self.grid.addWidget(self.path_label, 2, 0)
        self.grid.addWidget(self.measurement_path_edit, 2, 1, 1, 3)
        self.grid.addWidget(self.measurement_path_button, 2, 4)

        self.grid.addWidget(self.hdr_session_button, 3, 0, 1, 2)
        self.grid.addWidget(self.white_light_status, 3, 2, 1, 3)

        self.grid.addWidget(self.white_light_button, 4, 0)
        self.grid.addWidget(self.start_measurement_button, 4, 1)
        self.grid.addWidget(self.stop_measurement_button, 4, 2)
        self.grid.addWidget(self.emergency_stop_button, 4, 3, 1, 2)
        self.grid.setColumnStretch(1, 1)
        self.grid.setColumnStretch(3, 1)
