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
    QScrollArea,
    QSizePolicy,
    QSpinBox,
    QTableWidget,
    QTableWidgetItem,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from core.i18n import tr


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
        self.state_combo.addItem(tr("recipe.state_draft"), "draft")
        self.state_combo.addItem(tr("recipe.state_active"), "active")
        self.state_combo.addItem(tr("recipe.state_disabled"), "disabled")
        self.description_edit = QTextEdit()
        self.description_edit.setMaximumHeight(90)
        self.area_spin = _double_spin(0.000001, 10000.0, 0.1, " cm²", 6)
        self.apply_area_button = QPushButton(tr("recipe.apply_area_all_channels"))
        self.forward_polarity_combo = QComboBox()
        self.forward_polarity_combo.addItem(tr("recipe.forward_positive"), "positive")
        self.forward_polarity_combo.addItem(tr("recipe.forward_negative"), "negative")
        self.id_value = QLabel("—")
        self.version_value = QLabel("—")
        area_row = QHBoxLayout()
        area_row.addWidget(self.area_spin)
        area_row.addWidget(self.apply_area_button)
        area_widget = QWidget()
        area_widget.setLayout(area_row)
        form.addRow(tr("recipe.name_required"), self.name_edit)
        form.addRow(tr("recipe.state"), self.state_combo)
        form.addRow(tr("recipe.default_active_area"), area_widget)
        form.addRow(tr("recipe.unverified_polarity_direction"), self.forward_polarity_combo)
        form.addRow(tr("common.description"), self.description_edit)
        form.addRow(tr("recipe.id"), self.id_value)
        form.addRow(tr("common.version"), self.version_value)
        layout.addLayout(form)

        self.channels_table = QTableWidget(4, 3)
        self.channels_table.setHorizontalHeaderLabels(
            [tr("common.enabled"), tr("common.channel"), tr("recipe.device_area")]
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
        layout.addWidget(QLabel(tr("recipe.measurement_channels_note")))
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

        polarity = QGroupBox(tr("recipe.polarity_verification"))
        polarity_layout = QVBoxLayout(polarity)
        self.polarity_enabled_check = QCheckBox(tr("recipe.enable_polarity_verification"))
        self.polarity_enabled_check.setChecked(True)
        polarity_layout.addWidget(self.polarity_enabled_check)
        polarity_note = QLabel(
            tr("recipe.polarity_note")
        )
        polarity_note.setWordWrap(True)
        polarity_layout.addWidget(polarity_note)
        layout.addWidget(polarity)

        dark = QGroupBox(tr("recipe.dark_iv"))
        dark_layout = QFormLayout(dark)
        self.dark_iv_enabled_check = QCheckBox(tr("recipe.enable_dark_iv"))
        self.dark_iv_enabled_check.setChecked(True)
        self.dark_stable_spin = _double_spin(0, 3600, 10, " s")
        self.dark_start_spin = _double_spin(-210, 210, -0.2, " V", 4)
        self.dark_stop_spin = _double_spin(-210, 210, 1.2, " V", 4)
        self.dark_step_spin = _double_spin(0.000001, 210, 0.02, " V", 6)
        self.dark_direction_combo = QComboBox()
        self.dark_direction_combo.addItem(tr("recipe.forward"), "forward")
        self.dark_direction_combo.addItem(tr("recipe.reverse"), "reverse")
        self.dark_direction_combo.addItem(tr("recipe.bidirectional"), "bidirectional")
        self.dark_dwell_spin = _double_spin(0, 600, 0.1, " s")
        self.dark_compliance_spin = _double_spin(0.000001, 10000, 20, " mA", 6)
        self.dark_nplc_spin = _double_spin(0.001, 100, 1, " NPLC")
        self.dark_repeat_spin = QSpinBox()
        self.dark_repeat_spin.setRange(1, 999)
        self.dark_inter_delay_spin = _double_spin(0, 3600, 1, " s")
        self.dark_return_zero_check = QCheckBox(tr("recipe.return_zero_after"))
        self.dark_output_off_check = QCheckBox(tr("recipe.output_off_after"))
        self.dark_compliance_action_combo = QComboBox()
        self.dark_compliance_action_combo.addItem(tr("recipe.confirm_then_continue"), "confirm")
        self.dark_compliance_action_combo.addItem(tr("recipe.abort_immediately"), "abort")
        dark_layout.addRow(self.dark_iv_enabled_check)
        dark_layout.addRow(tr("recipe.dark_stabilization"), self.dark_stable_spin)
        dark_layout.addRow(tr("common.start"), self.dark_start_spin)
        dark_layout.addRow(tr("common.stop"), self.dark_stop_spin)
        dark_layout.addRow(tr("recipe.step"), self.dark_step_spin)
        dark_layout.addRow(tr("recipe.direction"), self.dark_direction_combo)
        dark_layout.addRow(tr("recipe.dwell_per_point"), self.dark_dwell_spin)
        dark_layout.addRow(tr("smu.current_compliance"), self.dark_compliance_spin)
        dark_layout.addRow(tr("smu.nplc"), self.dark_nplc_spin)
        dark_layout.addRow(tr("recipe.repeat"), self.dark_repeat_spin)
        dark_layout.addRow(tr("recipe.scan_interval"), self.dark_inter_delay_spin)
        dark_layout.addRow(self.dark_return_zero_check)
        dark_layout.addRow(self.dark_output_off_check)
        dark_layout.addRow(tr("recipe.compliance_action"), self.dark_compliance_action_combo)
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
        self.dark_frame_enabled_check = QCheckBox(tr("recipe.capture_dark_frame"))
        self.dark_frame_enabled_check.setChecked(True)
        self.matrix_output_mode_combo = QComboBox()
        self.matrix_output_mode_combo.addItem(tr("smu.constant_current_density"), "current_density")
        self.matrix_output_mode_combo.addItem(tr("smu.constant_voltage"), "voltage")
        self.matrix_current_density_edit = QLineEdit("2, 4, 6, 8, 10, 12")
        self.matrix_voltage_edit = QLineEdit("0.8, 1.0, 1.1, 1.2")
        self.matrix_gain_edit = QLineEdit("100, 200, 300, 400, 500")
        self.exposure_mode_combo = QComboBox()
        self.exposure_mode_combo.addItem(tr("recipe.manual_exposure"), "manual")
        self.exposure_mode_combo.addItem(tr("recipe.auto_exposure"), "auto")
        self.auto_exposure_group = QGroupBox(tr("recipe.auto_exposure"))
        auto_form = QFormLayout(self.auto_exposure_group)
        self.auto_gain_mode_combo = QComboBox()
        self.auto_gain_mode_combo.addItem(tr("recipe.auto_gain"), "auto")
        self.auto_gain_mode_combo.addItem(tr("recipe.fixed_gain"), "fixed")
        self.auto_gain_spin = QSpinBox()
        self.auto_gain_spin.setRange(100, 65535)
        self.auto_gain_spin.setValue(100)
        self.auto_gain_spin.setSuffix(" %")
        self.auto_target_combo = QComboBox()
        for value in (20, 30, 40, 50, 60, 70, 80):
            self.auto_target_combo.addItem(f"{value} %", value)
        self.auto_target_combo.setCurrentIndex(3)
        self.auto_max_exposure_spin = _double_spin(0.03, 15000, 15000, " ms")
        self.auto_stops_edit = QLineEdit("0")
        self.auto_stops_edit.setPlaceholderText(tr("recipe.ae_stops_example"))
        self.auto_stops_edit.setToolTip(tr("recipe.ae_stops_hint"))
        self.auto_timeout_spin = _double_spin(0.1, 3600, 60, " s")
        auto_form.addRow(tr("camera.gain"), self.auto_gain_mode_combo)
        auto_form.addRow(tr("recipe.fixed_gain"), self.auto_gain_spin)
        auto_form.addRow(tr("camera.auto_exposure_target"), self.auto_target_combo)
        auto_form.addRow(tr("recipe.ae_max_exposure"), self.auto_max_exposure_spin)
        auto_form.addRow(tr("recipe.ae_timeout"), self.auto_timeout_spin)
        auto_form.addRow(tr("recipe.ae_stops"), self.auto_stops_edit)
        auto_note = QLabel(tr("recipe.ae_note"))
        auto_note.setWordWrap(True)
        auto_form.addRow(auto_note)
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
        form.addRow(tr("smu.output_mode"), self.matrix_output_mode_combo)
        self.matrix_current_density_label = QLabel(tr("recipe.current_density_list"))
        self.matrix_voltage_label = QLabel(tr("recipe.voltage_list"))
        form.addRow(self.matrix_current_density_label, self.matrix_current_density_edit)
        form.addRow(self.matrix_voltage_label, self.matrix_voltage_edit)
        roi_group = QGroupBox(tr("recipe.roi_el_settings"))
        roi_form = QFormLayout(roi_group)
        self.roi_current_density_spin = _double_spin(0.000001, 100000, 2, " mA/cm²", 6)
        self.roi_voltage_spin = _double_spin(0.000001, 210, 0.8, " V", 6)
        self.roi_current_density_label = QLabel(tr("recipe.roi_current_density"))
        self.roi_voltage_label = QLabel(tr("recipe.roi_voltage"))
        roi_form.addRow(self.roi_current_density_label, self.roi_current_density_spin)
        roi_form.addRow(self.roi_voltage_label, self.roi_voltage_spin)
        roi_note = QLabel(tr("recipe.roi_el_note"))
        roi_note.setWordWrap(True)
        roi_form.addRow(roi_note)
        form.addRow(roi_group)
        form.addRow(tr("recipe.exposure_mode"), self.exposure_mode_combo)
        self.manual_exposure_group = QGroupBox(tr("recipe.manual_exposure"))
        manual_form = QFormLayout(self.manual_exposure_group)
        manual_form.addRow(tr("recipe.gain_list"), self.matrix_gain_edit)
        manual_form.addRow(tr("recipe.exposure_list"), self.matrix_exposure_edit)
        self.exposure_settings_widget = QWidget()
        self.exposure_settings_widget.setSizePolicy(
            QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Maximum,
        )
        exposure_settings_layout = QVBoxLayout(self.exposure_settings_widget)
        exposure_settings_layout.setContentsMargins(0, 0, 0, 0)
        exposure_settings_layout.addWidget(self.manual_exposure_group)
        exposure_settings_layout.addWidget(self.auto_exposure_group)
        form.addRow(self.exposure_settings_widget)
        form.addRow(tr("recipe.captures_per_condition"), self.matrix_repeat_spin)
        self.matrix_voltage_compliance_label = QLabel(tr("smu.voltage_compliance"))
        self.matrix_current_compliance_label = QLabel(tr("smu.current_compliance"))
        form.addRow(
            self.matrix_voltage_compliance_label,
            self.matrix_voltage_compliance_spin,
        )
        form.addRow(
            self.matrix_current_compliance_label,
            self.matrix_current_compliance_spin,
        )
        form.addRow(tr("measurement.output_stabilization"), self.matrix_stabilization_spin)
        form.addRow(tr("measurement.capture_timeout"), self.matrix_capture_timeout_spin)
        note = QLabel(tr("recipe.capture_sequence_note"))
        self.capture_sequence_note = note
        note.setWordWrap(True)
        note.setStyleSheet("background:#edf5fa; border:1px solid #b6cedd; padding:8px;")
        form.addRow(note)
        self.matrix_output_mode_combo.currentIndexChanged.connect(
            self._set_el_matrix_output_mode_ui
        )
        self._set_el_matrix_output_mode_ui()
        self.exposure_mode_combo.currentIndexChanged.connect(self._set_exposure_mode_ui)
        self.auto_gain_mode_combo.currentIndexChanged.connect(self._set_exposure_mode_ui)
        self._set_exposure_mode_ui()
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setWidget(page)
        return scroll

    def _set_exposure_mode_ui(self, *_args: object) -> None:
        automatic = self.exposure_mode_combo.currentData() == "auto"
        self.manual_exposure_group.setVisible(not automatic)
        self.auto_exposure_group.setVisible(automatic)
        self.manual_exposure_group.setEnabled(not automatic)
        self.auto_exposure_group.setEnabled(automatic)
        self.auto_gain_spin.setEnabled(
            automatic and self.auto_gain_mode_combo.currentData() == "fixed"
        )
        self.capture_sequence_note.setText(
            tr("recipe.ae_sequence_note") if automatic else tr("recipe.capture_sequence_note")
        )

    def _set_el_matrix_output_mode_ui(self, *_args: object) -> None:
        voltage_mode = self.matrix_output_mode_combo.currentData() == "voltage"
        for widget in (
            self.matrix_voltage_label,
            self.roi_voltage_label, self.roi_voltage_spin,
            self.matrix_voltage_edit,
            self.matrix_current_compliance_label,
            self.matrix_current_compliance_spin,
        ):
            widget.setVisible(voltage_mode)
        for widget in (
            self.matrix_current_density_label,
            self.roi_current_density_label, self.roi_current_density_spin,
            self.matrix_current_density_edit,
            self.matrix_voltage_compliance_label,
            self.matrix_voltage_compliance_spin,
        ):
            widget.setVisible(not voltage_mode)

    def _build_output_tab(self) -> QWidget:
        page = QWidget()
        form = QFormLayout(page)
        self.resolution_combo = QComboBox()
        self.resolution_combo.addItem(tr("camera.full_resolution"), "full")
        self.output_tiff_check = QCheckBox(tr("file.tiff_scientific_master"))
        self.output_png_check = QCheckBox(tr("file.png"))
        self.output_jpg_check = QCheckBox(tr("file.jpg"))
        self.output_jpg_footer_check = QCheckBox(tr("file.jpg_footer"))
        self.output_tiff_check.setChecked(True)
        self.output_jpg_footer_check.setChecked(True)
        self.save_raw_check = QCheckBox(tr("file.capture_records_required"))
        self.save_summary_csv_check = QCheckBox(tr("file.summary_csv_required"))
        self.save_json_check = QCheckBox(tr("file.json_metadata_required"))
        self.save_snapshot_check = QCheckBox(tr("file.recipe_snapshot_required"))
        for required in (
            self.save_raw_check,
            self.save_summary_csv_check,
            self.save_json_check,
            self.save_snapshot_check,
        ):
            required.setChecked(True)
            required.setEnabled(False)
            required.setToolTip(tr("file.traceability_required"))
        self.export_pixel_csv_check = QCheckBox(tr("file.export_full_resolution_pixel_csv"))
        self.pixel_csv_raw_check = QCheckBox(tr("file.raw_dn"))
        self.pixel_csv_corrected_check = QCheckBox(tr("file.dark_corrected"))
        self.pixel_csv_normalized_check = QCheckBox(tr("file.exposure_normalized"))
        form.addRow(tr("camera.resolution"), self.resolution_combo)
        form.addRow(QLabel(tr("recipe.image_output_formats")))
        form.addRow(self.output_tiff_check)
        form.addRow(self.output_png_check)
        form.addRow(self.output_jpg_check)
        form.addRow(self.output_jpg_footer_check)
        form.addRow(self.save_raw_check)
        form.addRow(self.save_summary_csv_check)
        form.addRow(self.save_json_check)
        form.addRow(self.save_snapshot_check)
        form.addRow(QLabel(tr("file.pixel_csv")))
        form.addRow(self.export_pixel_csv_check)
        form.addRow(self.pixel_csv_raw_check)
        form.addRow(self.pixel_csv_corrected_check)
        form.addRow(self.pixel_csv_normalized_check)
        return page
