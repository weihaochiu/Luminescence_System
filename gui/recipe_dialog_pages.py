from __future__ import annotations

"""The four formal Recipe editor pages."""

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDoubleSpinBox,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QPushButton,
    QSpinBox,
    QTableWidget,
    QTableWidgetItem,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)


def _double_spin(
    minimum: float,
    maximum: float,
    value: float = 0.0,
    suffix: str = "",
    decimals: int = 3,
) -> QDoubleSpinBox:
    spin = QDoubleSpinBox()
    spin.setRange(minimum, maximum)
    spin.setDecimals(decimals)
    spin.setValue(value)
    spin.setSuffix(suffix)
    spin.setKeyboardTracking(False)
    return spin


class RecipeDialogPagesMixin:
    def _build_basic_tab(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        form = QFormLayout()
        self.name_edit = QLineEdit()
        self.state_combo = QComboBox()
        self.state_combo.addItem("草稿", "draft")
        self.state_combo.addItem("啟用", "active")
        self.state_combo.addItem("停用", "disabled")
        self.description_edit = QTextEdit()
        self.description_edit.setMaximumHeight(90)
        self.area_spin = _double_spin(0.000001, 10000.0, 0.1, " cm²", 6)
        self.apply_area_button = QPushButton("套用到所有 Channel")
        self.forward_polarity_combo = QComboBox()
        self.forward_polarity_combo.addItem("正向為正", "positive")
        self.forward_polarity_combo.addItem("正向為負", "negative")
        self.id_value = QLabel("—")
        self.version_value = QLabel("—")
        area_row = QHBoxLayout()
        area_row.addWidget(self.area_spin)
        area_row.addWidget(self.apply_area_button)
        area_widget = QWidget()
        area_widget.setLayout(area_row)
        form.addRow("Recipe 名稱 *", self.name_edit)
        form.addRow("狀態", self.state_combo)
        form.addRow("預設 Active Area", area_widget)
        form.addRow("未執行極性確認時的方向", self.forward_polarity_combo)
        form.addRow("說明", self.description_edit)
        form.addRow("Recipe ID", self.id_value)
        form.addRow("版本", self.version_value)
        layout.addLayout(form)

        self.channels_table = QTableWidget(4, 3)
        self.channels_table.setHorizontalHeaderLabels(
            ["啟用", "Channel", "Device Area (cm²)"]
        )
        self.channels_table.verticalHeader().setVisible(False)
        self.channels_table.horizontalHeader().setSectionResizeMode(
            QHeaderView.ResizeMode.Stretch
        )
        for row in range(4):
            enabled = QTableWidgetItem()
            enabled.setFlags(enabled.flags() | Qt.ItemFlag.ItemIsUserCheckable)
            enabled.setCheckState(
                Qt.CheckState.Checked if row == 0 else Qt.CheckState.Unchecked
            )
            channel = QTableWidgetItem(f"CH{row + 1}")
            channel.setFlags(channel.flags() & ~Qt.ItemFlag.ItemIsEditable)
            self.channels_table.setItem(row, 0, enabled)
            self.channels_table.setItem(row, 1, channel)
            self.channels_table.setItem(row, 2, QTableWidgetItem("0.100"))
        layout.addWidget(QLabel("量測 Channel（Sample ID 於主畫面輸入）"))
        layout.addWidget(self.channels_table, 1)
        self.apply_area_button.clicked.connect(self._apply_default_area_to_channels)
        return page

    def _apply_default_area_to_channels(self) -> None:
        value = f"{self.area_spin.value():.6f}".rstrip("0").rstrip(".")
        for row in range(self.channels_table.rowCount()):
            self.channels_table.item(row, 2).setText(value)

    def _build_polarity_dark_iv_tab(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)

        polarity = QGroupBox("極性確認")
        polarity_layout = QVBoxLayout(polarity)
        self.polarity_enabled_check = QCheckBox("啟用極性確認")
        self.polarity_enabled_check.setChecked(True)
        polarity_layout.addWidget(self.polarity_enabled_check)
        polarity_note = QLabel(
            "啟用時沿用既有 White Light、Jsc/Voc 與 polarity factor 正式流程。"
        )
        polarity_note.setWordWrap(True)
        polarity_layout.addWidget(polarity_note)
        layout.addWidget(polarity)

        dark = QGroupBox("Dark IV")
        dark_layout = QFormLayout(dark)
        self.dark_iv_enabled_check = QCheckBox("啟用 Dark IV")
        self.dark_iv_enabled_check.setChecked(True)
        self.dark_stable_spin = _double_spin(0, 3600, 10, " s")
        self.dark_start_spin = _double_spin(-210, 210, -0.2, " V", 4)
        self.dark_stop_spin = _double_spin(-210, 210, 1.2, " V", 4)
        self.dark_step_spin = _double_spin(0.000001, 210, 0.02, " V", 6)
        self.dark_direction_combo = QComboBox()
        self.dark_direction_combo.addItem("Forward", "forward")
        self.dark_direction_combo.addItem("Reverse", "reverse")
        self.dark_direction_combo.addItem("Bidirectional", "bidirectional")
        self.dark_dwell_spin = _double_spin(0, 600, 0.1, " s")
        self.dark_compliance_spin = _double_spin(0.000001, 10000, 20, " mA", 6)
        self.dark_nplc_spin = _double_spin(0.001, 100, 1, " NPLC")
        self.dark_repeat_spin = QSpinBox()
        self.dark_repeat_spin.setRange(1, 999)
        self.dark_inter_delay_spin = _double_spin(0, 3600, 1, " s")
        self.dark_return_zero_check = QCheckBox("完成後回到 0 V")
        self.dark_output_off_check = QCheckBox("完成後關閉 OUTPUT")
        self.dark_compliance_action_combo = QComboBox()
        self.dark_compliance_action_combo.addItem("確認後繼續", "confirm")
        self.dark_compliance_action_combo.addItem("立即中止", "abort")
        dark_layout.addRow(self.dark_iv_enabled_check)
        dark_layout.addRow("Dark stabilization", self.dark_stable_spin)
        dark_layout.addRow("Start", self.dark_start_spin)
        dark_layout.addRow("Stop", self.dark_stop_spin)
        dark_layout.addRow("Step", self.dark_step_spin)
        dark_layout.addRow("方向", self.dark_direction_combo)
        dark_layout.addRow("每點 Dwell", self.dark_dwell_spin)
        dark_layout.addRow("Current compliance", self.dark_compliance_spin)
        dark_layout.addRow("NPLC", self.dark_nplc_spin)
        dark_layout.addRow("Repeat", self.dark_repeat_spin)
        dark_layout.addRow("掃描間隔", self.dark_inter_delay_spin)
        dark_layout.addRow(self.dark_return_zero_check)
        dark_layout.addRow(self.dark_output_off_check)
        dark_layout.addRow("Compliance 行為", self.dark_compliance_action_combo)
        layout.addWidget(dark, 1)
        self.dark_parameter_widgets = (
            self.dark_stable_spin, self.dark_start_spin, self.dark_stop_spin,
            self.dark_step_spin, self.dark_direction_combo, self.dark_dwell_spin,
            self.dark_compliance_spin, self.dark_nplc_spin, self.dark_repeat_spin,
            self.dark_inter_delay_spin, self.dark_return_zero_check,
            self.dark_output_off_check, self.dark_compliance_action_combo,
        )
        self.dark_iv_enabled_check.toggled.connect(self._set_dark_iv_widgets_enabled)
        return page

    def _set_dark_iv_widgets_enabled(self, enabled: bool) -> None:
        for widget in self.dark_parameter_widgets:
            widget.setEnabled(enabled)

    def _build_el_matrix_tab(self) -> QWidget:
        page = QWidget()
        form = QFormLayout(page)
        self.dark_frame_enabled_check = QCheckBox("拍攝 Dark Frame")
        self.dark_frame_enabled_check.setChecked(True)
        self.matrix_output_mode_combo = QComboBox()
        self.matrix_output_mode_combo.addItem("定電流密度", "current_density")
        self.matrix_output_mode_combo.addItem("定電壓", "voltage")
        self.matrix_current_density_edit = QLineEdit("2, 4, 6, 8, 10, 12")
        self.matrix_voltage_edit = QLineEdit("0.8, 1.0, 1.1, 1.2")
        self.matrix_gain_edit = QLineEdit("100, 200, 300, 400, 500")
        self.matrix_exposure_edit = QLineEdit(
            "0.5, 1, 2, 5, 10, 20, 50, 100, 200, 500, 1000, 2000, 5000, 10000, 15000"
        )
        self.matrix_repeat_spin = QSpinBox()
        self.matrix_repeat_spin.setRange(1, 999)
        self.matrix_voltage_compliance_spin = _double_spin(0.000001, 210, 3, " V", 6)
        self.matrix_current_compliance_spin = _double_spin(
            0.000001, 10000, 20, " mA", 6
        )
        self.matrix_stabilization_spin = QSpinBox()
        self.matrix_stabilization_spin.setRange(0, 3_600_000)
        self.matrix_stabilization_spin.setSuffix(" ms")
        self.matrix_capture_timeout_spin = _double_spin(0.1, 3600, 20, " s")
        form.addRow(self.dark_frame_enabled_check)
        form.addRow("輸出模式", self.matrix_output_mode_combo)
        self.matrix_current_density_label = QLabel("Current Density List (mA/cm²)")
        self.matrix_voltage_label = QLabel("Voltage List (V)")
        form.addRow(self.matrix_current_density_label, self.matrix_current_density_edit)
        form.addRow(self.matrix_voltage_label, self.matrix_voltage_edit)
        form.addRow("Gain List (%)", self.matrix_gain_edit)
        form.addRow("Exposure List (ms)", self.matrix_exposure_edit)
        form.addRow("每條件拍攝張數", self.matrix_repeat_spin)
        self.matrix_voltage_compliance_label = QLabel("Voltage Compliance")
        self.matrix_current_compliance_label = QLabel("Current Compliance")
        form.addRow(
            self.matrix_voltage_compliance_label,
            self.matrix_voltage_compliance_spin,
        )
        form.addRow(
            self.matrix_current_compliance_label,
            self.matrix_current_compliance_spin,
        )
        form.addRow("Output Stabilization Time", self.matrix_stabilization_spin)
        form.addRow("Capture timeout", self.matrix_capture_timeout_spin)
        note = QLabel(
            "Gain、Exposure 與每條件拍攝張數是正式量測唯一的拍攝序列來源。"
        )
        note.setWordWrap(True)
        note.setStyleSheet("background:#edf5fa; border:1px solid #b6cedd; padding:8px;")
        form.addRow(note)
        self.matrix_output_mode_combo.currentIndexChanged.connect(
            self._set_el_matrix_output_mode_ui
        )
        self._set_el_matrix_output_mode_ui()
        return page

    def _set_el_matrix_output_mode_ui(self, *_args: object) -> None:
        voltage_mode = self.matrix_output_mode_combo.currentData() == "voltage"
        for widget in (
            self.matrix_voltage_label,
            self.matrix_voltage_edit,
            self.matrix_current_compliance_label,
            self.matrix_current_compliance_spin,
        ):
            widget.setVisible(voltage_mode)
        for widget in (
            self.matrix_current_density_label,
            self.matrix_current_density_edit,
            self.matrix_voltage_compliance_label,
            self.matrix_voltage_compliance_spin,
        ):
            widget.setVisible(not voltage_mode)

    def _build_output_tab(self) -> QWidget:
        page = QWidget()
        form = QFormLayout(page)
        self.resolution_combo = QComboBox()
        self.resolution_combo.addItem("原始解析度 / Full Resolution", "full")
        self.output_tiff_check = QCheckBox("TIFF（高位深 Scientific Master）")
        self.output_png_check = QCheckBox("PNG")
        self.output_jpg_check = QCheckBox("JPG")
        self.output_jpg_footer_check = QCheckBox("JPG with Footer")
        self.output_tiff_check.setChecked(True)
        self.output_jpg_footer_check.setChecked(True)
        self.save_raw_check = QCheckBox("保存 capture records（必要）")
        self.save_summary_csv_check = QCheckBox("Dark IV / EL Summary CSV（必要）")
        self.save_json_check = QCheckBox("JSON Metadata（必要）")
        self.save_snapshot_check = QCheckBox("Recipe Snapshot（必要）")
        for required in (
            self.save_raw_check,
            self.save_summary_csv_check,
            self.save_json_check,
            self.save_snapshot_check,
        ):
            required.setChecked(True)
            required.setEnabled(False)
            required.setToolTip("量測追溯所需，正式流程固定輸出")
        self.export_pixel_csv_check = QCheckBox("輸出全解析度 Pixel CSV")
        self.pixel_csv_raw_check = QCheckBox("Raw DN")
        self.pixel_csv_corrected_check = QCheckBox("Dark-corrected")
        self.pixel_csv_normalized_check = QCheckBox("Exposure-normalized")
        form.addRow("影像解析度", self.resolution_combo)
        form.addRow(QLabel("影像輸出格式（可複選）"))
        form.addRow(self.output_tiff_check)
        form.addRow(self.output_png_check)
        form.addRow(self.output_jpg_check)
        form.addRow(self.output_jpg_footer_check)
        form.addRow(self.save_raw_check)
        form.addRow(self.save_summary_csv_check)
        form.addRow(self.save_json_check)
        form.addRow(self.save_snapshot_check)
        form.addRow(QLabel("Pixel CSV"))
        form.addRow(self.export_pixel_csv_check)
        form.addRow(self.pixel_csv_raw_check)
        form.addRow(self.pixel_csv_corrected_check)
        form.addRow(self.pixel_csv_normalized_check)
        return page
