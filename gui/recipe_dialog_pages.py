from __future__ import annotations

"""The eight cohesive Recipe editor pages and their widget construction."""

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QAbstractItemView,
    QCheckBox,
    QComboBox,
    QDoubleSpinBox,
    QFormLayout,
    QFrame,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QPushButton,
    QSpinBox,
    QTableWidget,
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
    """Build Recipe pages; persistence and table behavior live elsewhere."""

    def _build_basic_tab(self) -> QWidget:
        page = QWidget()
        form = QFormLayout(page)
        self.name_edit = QLineEdit()
        self.type_value = QLabel("EL 四階段量測（固定）")
        self.state_combo = QComboBox()
        self.state_combo.addItem("草稿（不顯示於主畫面）", "draft")
        self.state_combo.addItem("啟用", "active")
        self.state_combo.addItem("停用", "disabled")
        self.description_edit = QTextEdit()
        self.description_edit.setMaximumHeight(100)
        self.area_spin = _double_spin(0.000001, 10000.0, 0.1, " cm²", 6)
        self.forward_polarity_combo = QComboBox()
        self.forward_polarity_combo.addItem("正電流／正電壓", "positive")
        self.forward_polarity_combo.addItem("負電流／負電壓", "negative")
        self.device_id_required_check = QCheckBox("開始量測前必須輸入 Device／Pixel ID")
        self.id_value = QLabel("—")
        self.version_value = QLabel("—")
        form.addRow("Recipe 名稱 *", self.name_edit)
        form.addRow("量測類型", self.type_value)
        form.addRow("狀態", self.state_combo)
        form.addRow("Active area *", self.area_spin)
        form.addRow("預期 EL 正向極性", self.forward_polarity_combo)
        form.addRow("樣品識別", self.device_id_required_check)
        form.addRow("用途／備註", self.description_edit)
        form.addRow("Recipe ID", self.id_value)
        form.addRow("版本", self.version_value)
        return page

    def _build_polarity_tab(self) -> QWidget:
        page = QWidget()
        form = QFormLayout(page)
        self.polarity_required_check = QCheckBox("執行白光下 Jsc／Voc 極性確認（必做）")
        self.polarity_required_check.setChecked(True)
        self.polarity_required_check.setEnabled(False)
        form.addRow(self.polarity_required_check)
        note = QLabel(
            "Jsc / Voc 條件由「設定 → 極性確認…」統一管理。Recipe 執行時讀取同一份"
            "全域設定，並把當次設定與量測結果寫入 snapshot。"
        )
        note.setWordWrap(True)
        note.setStyleSheet("background:#edf5fa; border:1px solid #b6cedd; padding:8px;")
        form.addRow(note)
        return page

    def _build_dark_iv_tab(self) -> QWidget:
        page = QWidget()
        form = QFormLayout(page)
        self.dark_iv_required_check = QCheckBox("每次 EL 前執行 Dark I–V（必做）")
        self.dark_iv_required_check.setChecked(True)
        self.dark_iv_required_check.setEnabled(False)
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
        self.dark_compliance_action_combo.addItem("警告並要求確認是否進入 EL", "confirm")
        self.dark_compliance_action_combo.addItem("直接中止", "abort")
        form.addRow(self.dark_iv_required_check)
        form.addRow("關燈後穩定", self.dark_stable_spin)
        form.addRow("Start", self.dark_start_spin)
        form.addRow("Stop", self.dark_stop_spin)
        form.addRow("Step", self.dark_step_spin)
        form.addRow("掃描方向", self.dark_direction_combo)
        form.addRow("每點 Dwell", self.dark_dwell_spin)
        form.addRow("Current compliance", self.dark_compliance_spin)
        form.addRow("NPLC", self.dark_nplc_spin)
        form.addRow("Repeat", self.dark_repeat_spin)
        form.addRow("輪次間隔", self.dark_inter_delay_spin)
        form.addRow(self.dark_return_zero_check)
        form.addRow(self.dark_output_off_check)
        form.addRow("Compliance 發生時", self.dark_compliance_action_combo)
        return page

    def _build_camera_tab(self) -> QWidget:
        page = QWidget()
        form = QFormLayout(page)
        self.exposure_spin = _double_spin(0.001, 15000, 500, " ms")
        self.gain_spin = QSpinBox()
        self.gain_spin.setRange(0, 500)
        self.gain_spin.setSuffix(" %")
        self.frames_spin = QSpinBox()
        self.frames_spin.setRange(1, 999)
        self.frame_interval_spin = _double_spin(0, 600, 0.1, " s")
        self.frame_handling_combo = QComboBox()
        self.frame_handling_combo.addItem("保存全部 Frames", "save_all")
        self.frame_handling_combo.addItem("平均後保存", "average")
        self.frame_handling_combo.addItem("中位數後保存", "median")
        self.trigger_combo = QComboBox()
        self.trigger_combo.addItem("軟體觸發", "software")
        self.trigger_combo.addItem("外部觸發（預留）", "external")
        self.timeout_spin = _double_spin(0.1, 600, 20, " s")
        self.format_value = QLabel("Current resolution／RGB24（本版固定）")
        form.addRow("非 HDR 預設 Exposure", self.exposure_spin)
        form.addRow("非 HDR 預設 Gain", self.gain_spin)
        form.addRow("非 HDR 預設 Frames", self.frames_spin)
        form.addRow("非 HDR 預設 Frame interval", self.frame_interval_spin)
        form.addRow("多張處理", self.frame_handling_combo)
        form.addRow("觸發方式", self.trigger_combo)
        form.addRow("拍攝 timeout", self.timeout_spin)
        form.addRow("影像模式", self.format_value)
        note = QLabel(
            "以上四項只用於新增點位、產生點位及批次填入 EL 表格，不是量測時的全域 fallback；"
            "HDR 關閉時一律使用每列明確設定。HDR 開啟時則由「設定 → HDR」與 T0 Profile 控制。"
            "ROI、解析度與 pixel format 不允許逐點改變。"
        )
        note.setWordWrap(True)
        form.addRow(note)
        return page

    def _build_el_tab(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)

        hdr_panel = QFrame()
        hdr_panel.setObjectName("hdrPanel")
        hdr_panel.setStyleSheet(
            "QFrame#hdrPanel { background:#edf5fa; border:1px solid #b6cedd; border-radius:4px; }"
        )
        hdr_layout = QVBoxLayout(hdr_panel)
        self.hdr_enabled_check = QCheckBox("啟用 HDR")
        self.hdr_enabled_check.setToolTip("HDR 詳細參數請至主畫面的「設定 → HDR」管理")
        self.hdr_status_label = QLabel(
            "未啟用：請在下方表格逐列設定 Exposure、Gain、Frames 與間隔。"
        )
        self.hdr_status_label.setWordWrap(True)
        hdr_layout.addWidget(self.hdr_enabled_check)
        hdr_layout.addWidget(self.hdr_status_label)
        layout.addWidget(hdr_panel)

        top = QFormLayout()
        self.drive_mode_combo = QComboBox()
        self.drive_mode_combo.addItem("電流模式－Source Current", "current")
        self.drive_mode_combo.addItem("電壓模式－Source Voltage", "voltage")
        self.basis_combo = QComboBox()
        self.basis_combo.addItem("電流密度 (mA/cm²)", "current_density")
        self.basis_combo.addItem("電流 (mA)", "current")
        self.basis_combo.addItem("電壓 (V)", "voltage")
        self.el_direction_combo = QComboBox()
        self.el_direction_combo.addItem("Ascending", "ascending")
        self.el_direction_combo.addItem("Descending", "descending")
        self.el_direction_combo.addItem("Bidirectional", "bidirectional")
        self.el_repeat_spin = QSpinBox()
        self.el_repeat_spin.setRange(1, 999)
        self.el_inter_delay_spin = _double_spin(0, 3600, 1, " s")
        self.el_voltage_compliance_spin = _double_spin(0.000001, 210, 3, " V", 6)
        self.el_current_compliance_spin = _double_spin(0.000001, 10000, 20, " mA", 6)
        top.addRow("EL 驅動模式", self.drive_mode_combo)
        top.addRow("點位設定單位", self.basis_combo)
        top.addRow("掃描方向", self.el_direction_combo)
        top.addRow("Repeat", self.el_repeat_spin)
        top.addRow("輪次間隔", self.el_inter_delay_spin)
        top.addRow("Voltage compliance（電流模式）", self.el_voltage_compliance_spin)
        top.addRow("Current compliance（電壓模式）", self.el_current_compliance_spin)
        layout.addLayout(top)

        builder = QHBoxLayout()
        self.builder_mode_combo = QComboBox()
        self.builder_mode_combo.addItem("線性", "linear")
        self.builder_mode_combo.addItem("對數", "log")
        self.builder_mode_combo.addItem("自訂列表", "custom")
        self.builder_start_spin = _double_spin(0.000001, 10000, 0.1, "")
        self.builder_stop_spin = _double_spin(0.000001, 10000, 20, "")
        self.builder_step_spin = _double_spin(0.000001, 10000, 0.1, "")
        self.builder_count_spin = QSpinBox()
        self.builder_count_spin.setRange(2, 1000)
        self.builder_count_spin.setValue(8)
        self.builder_custom_edit = QLineEdit("0.1, 0.3, 1, 3, 10, 20")
        self.builder_custom_edit.setPlaceholderText("以逗號或空白分隔")
        self.generate_button = QPushButton("產生／取代表格")
        builder.addWidget(QLabel("建立方式"))
        builder.addWidget(self.builder_mode_combo)
        builder.addWidget(QLabel("Start"))
        builder.addWidget(self.builder_start_spin)
        builder.addWidget(QLabel("Stop"))
        builder.addWidget(self.builder_stop_spin)
        builder.addWidget(QLabel("Step"))
        builder.addWidget(self.builder_step_spin)
        builder.addWidget(QLabel("Log points"))
        builder.addWidget(self.builder_count_spin)
        builder.addWidget(self.builder_custom_edit, 1)
        builder.addWidget(self.generate_button)
        layout.addLayout(builder)

        self.points_table = QTableWidget(0, len(self.POINT_COLUMNS))
        self.points_table.setHorizontalHeaderLabels(self.POINT_COLUMNS)
        self.points_table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.points_table.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.points_table.verticalHeader().setVisible(False)
        self.points_table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        layout.addWidget(self.points_table, 1)
        point_buttons = QHBoxLayout()
        self.add_point_button = QPushButton("新增點位")
        self.delete_point_button = QPushButton("刪除選取")
        self.fill_camera_button = QPushButton("套用非 HDR 預設至選取列")
        point_buttons.addWidget(self.add_point_button)
        point_buttons.addWidget(self.delete_point_button)
        point_buttons.addWidget(self.fill_camera_button)
        point_buttons.addStretch()
        layout.addLayout(point_buttons)
        self.generate_button.clicked.connect(self._generate_points)
        self.add_point_button.clicked.connect(self._add_point)
        self.delete_point_button.clicked.connect(self._delete_selected_points)
        self.fill_camera_button.clicked.connect(self._fill_selected_camera)
        return page

    def _build_dark_frame_tab(self) -> QWidget:
        page = QWidget()
        form = QFormLayout(page)
        self.dark_frames_per_profile_spin = QSpinBox()
        self.dark_frames_per_profile_spin.setRange(1, 999)
        self.dark_frame_interval_spin = _double_spin(0, 600, 0.1, " s")
        self.dark_camera_delay_spin = _double_spin(0, 600, 0.3, " s")
        self.dark_combine_combo = QComboBox()
        self.dark_combine_combo.addItem("Median", "median")
        self.dark_combine_combo.addItem("Average", "average")
        self.dark_save_raw_check = QCheckBox("保存全部原始 Dark Frames")
        self.dark_save_master_check = QCheckBox("保存 Master Dark")
        self.dark_after_el_check = QCheckBox("EL 完成後再拍一組 Dark，檢查漂移")
        self.dark_profiles_label = QLabel("儲存 Recipe 後會依 EL 點位自動整理")
        self.dark_profiles_label.setWordWrap(True)
        self.dark_profiles_label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        form.addRow("每個 Profile 的 Frames", self.dark_frames_per_profile_spin)
        form.addRow("Frame interval", self.dark_frame_interval_spin)
        form.addRow("相機參數切換等待", self.dark_camera_delay_spin)
        form.addRow("Master Dark 合成", self.dark_combine_combo)
        form.addRow(self.dark_save_raw_check)
        form.addRow(self.dark_save_master_check)
        form.addRow(self.dark_after_el_check)
        form.addRow("自動產生的 Profiles", self.dark_profiles_label)
        note = QLabel("HDR 啟用時，本頁參數停用；HDR Dark 規則統一由「設定 → HDR」管理。")
        note.setWordWrap(True)
        note.setStyleSheet("color:#7a5200;")
        form.addRow(note)
        return page

    def _build_safety_tab(self) -> QWidget:
        page = QWidget()
        form = QFormLayout(page)
        self.device_match_combo = QComboBox()
        self.device_match_combo.addItem("任一支援的 Keysight B2900 系列", "any_b2900")
        self.device_match_combo.addItem("指定 VISA 位址", "specific")
        self.visa_edit = QLineEdit()
        self.visa_edit.setPlaceholderText("USB0::...::INSTR")
        self.max_current_spin = _double_spin(0.000001, 10000, 50, " mA", 6)
        self.max_voltage_spin = _double_spin(0.000001, 210, 5, " V", 6)
        self.max_power_spin = _double_spin(0.000001, 1000000, 150, " mW", 6)
        self.max_output_time_spin = _double_spin(0.1, 86400, 600, " s")
        self.max_recipe_time_spin = _double_spin(0.1, 86400, 1800, " s")
        self.stop_camera_check = QCheckBox("相機失敗時停止並關閉 SMU 輸出")
        self.stop_smu_check = QCheckBox("SMU 通訊中斷時停止 Recipe")
        form.addRow("SMU 相容條件", self.device_match_combo)
        form.addRow("指定 VISA 位址", self.visa_edit)
        form.addRow("最大允許電流", self.max_current_spin)
        form.addRow("最大允許電壓", self.max_voltage_spin)
        form.addRow("最大允許功率", self.max_power_spin)
        form.addRow("單次輸出最長時間", self.max_output_time_spin)
        form.addRow("Recipe 最長時間", self.max_recipe_time_spin)
        form.addRow(self.stop_camera_check)
        form.addRow(self.stop_smu_check)
        note = QLabel("本版不送出 *RST，也尚未執行 SMU OUTPUT；開始量測保持安全禁用。")
        note.setWordWrap(True)
        note.setStyleSheet("color:#a05a00;")
        form.addRow(note)
        return page

    def _build_output_tab(self) -> QWidget:
        page = QWidget()
        form = QFormLayout(page)
        self.output_root_edit = QLineEdit()
        browse = QPushButton("瀏覽…")
        browse.clicked.connect(self._choose_output_root)
        row = QHBoxLayout()
        row.addWidget(self.output_root_edit, 1)
        row.addWidget(browse)
        row_widget = QWidget()
        row_widget.setLayout(row)
        self.sample_required_check = QCheckBox("開始前必須輸入樣品 ID")
        self.image_format_combo = QComboBox()
        self.image_format_combo.addItems(["TIFF", "PNG"])
        self.save_raw_check = QCheckBox("保存所有原始 Frames")
        self.save_summary_csv_check = QCheckBox("輸出 Dark I–V 與 EL scan summary CSV（必要）")
        self.save_json_check = QCheckBox("輸出 JSON metadata（必要）")
        self.save_snapshot_check = QCheckBox("保存本次 Recipe 快照（必要）")
        self.export_pixel_csv_check = QCheckBox("匯出每張影像的全解析度像素 CSV（選配，預設關閉）")
        self.pixel_csv_raw_check = QCheckBox("Raw DN 矩陣（_raw.csv）")
        self.pixel_csv_corrected_check = QCheckBox("Dark-corrected 矩陣（_dark_corrected.csv）")
        self.pixel_csv_normalized_check = QCheckBox("Exposure-normalized 矩陣（_normalized.csv，DN/s）")
        form.addRow("儲存根目錄", row_widget)
        form.addRow("樣品識別", self.sample_required_check)
        form.addRow("影像格式", self.image_format_combo)
        form.addRow(self.save_raw_check)
        form.addRow(self.save_summary_csv_check)
        form.addRow(self.save_json_check)
        form.addRow(self.save_snapshot_check)
        form.addRow(QLabel("像素 CSV"))
        form.addRow(self.export_pixel_csv_check)
        form.addRow("輸出內容", self.pixel_csv_raw_check)
        form.addRow("", self.pixel_csv_corrected_check)
        form.addRow("", self.pixel_csv_normalized_check)
        note = QLabel(
            "關閉像素 CSV 不影響必要的 scan summary CSV。日後仍可從保留像素值的 TIFF、Master Dark 與 metadata 批次產生像素 CSV。"
        )
        note.setWordWrap(True)
        note.setStyleSheet("color:#687078;")
        form.addRow(note)
        return page
