from __future__ import annotations

"""Construction and signal wiring for the main application window."""

from PySide6.QtCore import QSize, Qt
from PySide6.QtGui import QAction, QKeySequence
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDoubleSpinBox,
    QFormLayout,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QScrollArea,
    QSpinBox,
    QStatusBar,
    QStyle,
    QToolBar,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from .device_panel import DevicePanel
from .smu_manual_panel import ManualSMUPanel
from .widgets import CollapsibleSection, ImageView


class MainWindowUIMixin:
    """Own only widget construction and signal connections."""

    def _build_actions(self) -> None:
        style = self.style()
        self.refresh_action = QAction(
            style.standardIcon(QStyle.StandardPixmap.SP_BrowserReload), "重新偵測", self
        )
        self.refresh_action.setShortcut(QKeySequence("F5"))
        self.refresh_action.setToolTip("重新掃描並偵測相機（F5）")
        self.connect_action = QAction(
            style.standardIcon(QStyle.StandardPixmap.SP_DialogOpenButton), "相機連線", self
        )
        self.connect_action.setToolTip("連線或中斷目前選取的相機")
        self.capture_action = QAction(
            style.standardIcon(QStyle.StandardPixmap.SP_DialogSaveButton), "拍攝影像", self
        )
        self.capture_action.setShortcut(QKeySequence("Ctrl+S"))
        self.capture_action.setToolTip("使用目前相機設定拍攝並儲存影像（Ctrl+S）")
        self.auto_capture_action = QAction(
            style.standardIcon(QStyle.StandardPixmap.SP_DialogApplyButton), "自動曝光拍攝", self
        )
        self.auto_capture_action.setToolTip("等待自動曝光收斂後拍攝並儲存影像")
        self.fit_action = QAction(
            style.standardIcon(QStyle.StandardPixmap.SP_TitleBarMaxButton), "符合視窗", self
        )
        self.fit_action.setToolTip("縮放影像以符合目前顯示區域")
        self.actual_action = QAction(
            style.standardIcon(QStyle.StandardPixmap.SP_TitleBarNormalButton), "原始尺寸", self
        )
        self.actual_action.setToolTip("以 100% 比例顯示影像")
        self.exit_action = QAction("結束", self)
        self.exit_action.setShortcut(QKeySequence.StandardKey.Quit)
        self.about_action = QAction("關於", self)
        self.recipe_manager_action = QAction(
            style.standardIcon(QStyle.StandardPixmap.SP_FileDialogDetailedView), "Recipe 管理", self
        )
        self.recipe_manager_action.setShortcut(QKeySequence("Ctrl+R"))
        self.recipe_manager_action.setToolTip("建立、編輯、驗證或匯入／匯出 Recipe（Ctrl+R）")
        self.hdr_settings_action = QAction("HDR…", self)
        self.hdr_settings_action.setToolTip("設定共用的定量 HDR 參數與過曝提前終止規則")
        self.relay_settings_action = QAction("Relay 設定…", self)
        self.relay_settings_action.setToolTip("設定 USBRelay8 Channel、群組與手動測試")

        self.refresh_action.triggered.connect(self.refresh_devices)
        self.connect_action.triggered.connect(self.toggle_connection)
        self.capture_action.triggered.connect(self.capture_current_frame)
        self.auto_capture_action.triggered.connect(self.auto_expose_and_capture)
        self.fit_action.triggered.connect(lambda: self.image_view.fit_to_window())
        self.actual_action.triggered.connect(lambda: self.image_view.actual_size())
        self.exit_action.triggered.connect(self.close)
        self.about_action.triggered.connect(self.show_about)
        self.recipe_manager_action.triggered.connect(self.open_recipe_manager)
        self.hdr_settings_action.triggered.connect(self.open_hdr_settings)
        self.relay_settings_action.triggered.connect(self.open_relay_settings)

    def _build_menu_and_toolbar(self) -> None:
        file_menu = self.menuBar().addMenu("檔案(&F)")
        file_menu.addAction(self.capture_action)
        file_menu.addSeparator()
        file_menu.addAction(self.exit_action)

        camera_menu = self.menuBar().addMenu("相機(&C)")
        camera_menu.addAction(self.refresh_action)
        camera_menu.addAction(self.connect_action)
        camera_menu.addAction(self.auto_capture_action)

        view_menu = self.menuBar().addMenu("檢視(&V)")
        view_menu.addAction(self.fit_action)
        view_menu.addAction(self.actual_action)

        settings_menu = self.menuBar().addMenu("設定(&S)")
        settings_menu.addAction(self.recipe_manager_action)
        settings_menu.addAction(self.hdr_settings_action)
        settings_menu.addAction(self.relay_settings_action)

        help_menu = self.menuBar().addMenu("說明(&H)")
        help_menu.addAction(self.about_action)

        toolbar = QToolBar("主要工具", self)
        toolbar.setObjectName("mainToolbar")
        toolbar.setMovable(False)
        toolbar.setFloatable(False)
        toolbar.setIconSize(QSize(20, 20))
        toolbar.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)

        # 依實際操作流程排列：設備 → Recipe → 拍攝 → 影像檢視。
        toolbar.addAction(self.refresh_action)
        toolbar.addAction(self.connect_action)
        toolbar.addSeparator()
        toolbar.addAction(self.recipe_manager_action)
        toolbar.addSeparator()
        toolbar.addAction(self.capture_action)
        toolbar.addAction(self.auto_capture_action)
        toolbar.addSeparator()
        toolbar.addAction(self.fit_action)
        toolbar.addAction(self.actual_action)

        # QAction 預設會依文字長度產生不同寬度；固定所有可按按鈕的尺寸。
        self.main_toolbar = toolbar
        for action in toolbar.actions():
            if action.isSeparator():
                continue
            button = toolbar.widgetForAction(action)
            if isinstance(button, QToolButton):
                button.setFixedSize(132, 36)
        self.addToolBar(toolbar)

    def _build_central_ui(self) -> None:
        self.image_view = ImageView()

        self.device_panel = DevicePanel()
        self.camera_list = self.device_panel.camera_list

        self.capture_button = QPushButton("拍攝")
        self.capture_button.setIcon(self.style().standardIcon(QStyle.StandardPixmap.SP_DialogSaveButton))
        self.capture_button.setMinimumHeight(40)
        self.auto_capture_button = QPushButton("自動曝光後拍攝")
        self.auto_capture_button.setMinimumHeight(40)

        capture_buttons = QHBoxLayout()
        capture_buttons.addWidget(self.capture_button)
        capture_buttons.addWidget(self.auto_capture_button)

        self.resolution_combo = QComboBox()
        self.format_combo = QComboBox()
        self.format_combo.addItem("RGB24（基本預覽／拍攝）")
        self.format_combo.setEnabled(False)

        capture_content = QWidget()
        capture_layout = QVBoxLayout(capture_content)
        capture_layout.setContentsMargins(8, 8, 8, 10)
        capture_layout.addLayout(capture_buttons)
        capture_form = QFormLayout()
        capture_form.addRow("解析度", self.resolution_combo)
        capture_form.addRow("格式", self.format_combo)
        capture_layout.addLayout(capture_form)

        self.auto_exposure_check = QCheckBox("持續自動曝光")
        self.auto_target_spin = QSpinBox()
        self.auto_target_spin.setRange(16, 220)
        self.auto_target_spin.setValue(120)
        self.auto_target_spin.setToolTip("SDK 自動曝光亮度目標，數值越高影像越亮")

        self.exposure_spin = QDoubleSpinBox()
        self.exposure_spin.setDecimals(3)
        self.exposure_spin.setSuffix(" ms")
        self.exposure_spin.setKeyboardTracking(False)
        self.exposure_spin.setSingleStep(1.0)
        self.gain_spin = QSpinBox()
        self.gain_spin.setSuffix(" %")
        self.gain_spin.setKeyboardTracking(False)
        self.apply_manual_button = QPushButton("套用手動設定")

        exposure_content = QWidget()
        exposure_layout = QVBoxLayout(exposure_content)
        exposure_layout.setContentsMargins(8, 8, 8, 10)
        exposure_layout.addWidget(self.auto_exposure_check)
        exposure_form = QFormLayout()
        exposure_form.addRow("曝光目標", self.auto_target_spin)
        exposure_form.addRow("曝光時間", self.exposure_spin)
        exposure_form.addRow("Gain", self.gain_spin)
        exposure_layout.addLayout(exposure_form)
        exposure_layout.addWidget(self.apply_manual_button)

        self.manual_smu_panel = ManualSMUPanel()

        info_content = QWidget()
        info_layout = QFormLayout(info_content)
        info_layout.setContentsMargins(8, 8, 8, 10)
        self.model_value = QLabel("—")
        self.sdk_value = QLabel("—")
        self.color_value = QLabel("—")
        self.model_value.setWordWrap(True)
        info_layout.addRow("相機型號", self.model_value)
        info_layout.addRow("感測器", self.color_value)
        info_layout.addRow("SDK", self.sdk_value)

        sidebar_body = QWidget()
        sidebar_layout = QVBoxLayout(sidebar_body)
        sidebar_layout.setContentsMargins(3, 3, 3, 3)
        sidebar_layout.setSpacing(3)
        sidebar_layout.addWidget(CollapsibleSection("相機列表", self.device_panel.camera_content, True))
        sidebar_layout.addWidget(CollapsibleSection("SMU 列表", self.device_panel.smu_content, True))
        sidebar_layout.addWidget(CollapsibleSection("SMU 手動輸出", self.manual_smu_panel, True))
        sidebar_layout.addWidget(CollapsibleSection("Recipe", self.device_panel.recipe_content, True))
        sidebar_layout.addWidget(CollapsibleSection("拍攝與解析度", capture_content, True))
        sidebar_layout.addWidget(CollapsibleSection("曝光控制", exposure_content, True))
        sidebar_layout.addWidget(CollapsibleSection("相機資訊", info_content, False))
        sidebar_layout.addStretch()

        sidebar_scroll = QScrollArea()
        sidebar_scroll.setWidgetResizable(True)
        sidebar_scroll.setWidget(sidebar_body)
        sidebar_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        sidebar_scroll.setFrameShape(QFrame.Shape.NoFrame)
        sidebar_scroll.setFixedWidth(310)

        workspace_header = QFrame()
        workspace_header.setObjectName("workspaceHeader")
        header_layout = QHBoxLayout(workspace_header)
        header_layout.setContentsMargins(10, 5, 10, 5)
        self.view_title = QLabel("即時影像")
        self.view_title.setStyleSheet("font-weight: 600;")
        header_layout.addWidget(self.view_title)
        header_layout.addStretch()

        workspace = QWidget()
        workspace_layout = QVBoxLayout(workspace)
        workspace_layout.setContentsMargins(0, 0, 0, 0)
        workspace_layout.setSpacing(0)
        workspace_layout.addWidget(workspace_header)
        workspace_layout.addWidget(self.image_view, 1)

        main_area = QWidget()
        main_area_layout = QHBoxLayout(main_area)
        main_area_layout.setContentsMargins(0, 0, 0, 0)
        main_area_layout.setSpacing(1)
        main_area_layout.addWidget(sidebar_scroll)
        main_area_layout.addWidget(workspace, 1)

        operation_bar = self._build_measurement_operation_bar()
        center = QWidget()
        center_layout = QVBoxLayout(center)
        center_layout.setContentsMargins(0, 0, 0, 0)
        center_layout.setSpacing(1)
        center_layout.addWidget(main_area, 1)
        center_layout.addWidget(operation_bar)
        self.setCentralWidget(center)

        self.setStyleSheet(
            """
            QMainWindow { background: #e6e8ea; }
            QToolButton { background: #d7dadc; border: 1px solid #b7bbbe; padding: 6px; text-align: left; }
            QToolButton:hover { background: #cbdde9; }
            QPushButton { min-height: 26px; }
            QPushButton:enabled { border: 1px solid #9ba3a8; border-radius: 3px; padding: 4px 8px; }
            QPushButton:enabled:hover { border-color: #1689c9; background: #e7f5fc; }
            #workspaceHeader { background: #f1f3f4; border-bottom: 1px solid #aeb3b7; }
            #measurementBar { background: #f1f3f4; border-top: 1px solid #aeb3b7; }
            #startMeasurement { background: #1976a8; color: white; font-weight: 600; min-height: 34px; }
            #stopMeasurement { background: #b3261e; color: white; font-weight: 600; min-height: 34px; }
            #emergencyStop { background: #7f0000; color: white; font-weight: 700; min-height: 34px; border: 2px solid #4a0000; }
            QScrollArea { background: #eef0f1; }
            """
        )

    def _build_measurement_operation_bar(self) -> QFrame:
        bar = QFrame()
        bar.setObjectName("measurementBar")
        layout = QHBoxLayout(bar)
        layout.setContentsMargins(10, 7, 10, 7)
        self.sample_id_edit = QLineEdit()
        self.sample_id_edit.setPlaceholderText("輸入樣品 ID")
        self.sample_id_edit.setMaximumWidth(210)
        self.measurement_path_edit = QLineEdit()
        self.measurement_path_edit.setReadOnly(True)
        self.measurement_path_edit.setPlaceholderText("選擇量測資料儲存位置")
        self.measurement_path_edit.setMinimumWidth(230)
        self.measurement_path_edit.setText(str(self.settings.value("measurement/output_root", "")))
        self.measurement_path_button = QPushButton("瀏覽…")
        self.measurement_path_button.clicked.connect(self.choose_measurement_output_root)
        self.selected_recipe_label = QLabel("Recipe：尚未選擇")
        self.selected_recipe_label.setMinimumWidth(210)
        self.hdr_session_button = QPushButton("HDR：未設定")
        self.hdr_session_button.setMinimumWidth(155)
        self.hdr_session_button.clicked.connect(self.configure_hdr_session)
        self.white_light_status = QLabel("白光 ● 未連線")
        self.white_light_status.setMinimumWidth(105)
        self.white_light_button = QPushButton("開啟白光")
        self.white_light_button.setMinimumWidth(105)
        self.white_light_button.setEnabled(False)
        self.white_light_button.clicked.connect(self.toggle_white_light)
        self.sample_id_edit.textChanged.connect(self._on_sample_id_changed)
        self.start_measurement_button = QPushButton("開始量測")
        self.start_measurement_button.setObjectName("startMeasurement")
        self.start_measurement_button.setMinimumWidth(110)
        self.stop_measurement_button = QPushButton("停止")
        self.stop_measurement_button.setObjectName("stopMeasurement")
        self.stop_measurement_button.setMinimumWidth(90)
        self.stop_measurement_button.setEnabled(False)
        self.emergency_stop_button = QPushButton("Emergency Stop")
        self.emergency_stop_button.setObjectName("emergencyStop")
        self.emergency_stop_button.setMinimumWidth(130)
        self.emergency_stop_button.setToolTip("Immediately zero the SMU source and disable output.")
        self.start_measurement_button.clicked.connect(self._measurement_not_implemented)
        self.stop_measurement_button.clicked.connect(self.stop_background_measurement)
        self.emergency_stop_button.clicked.connect(self.emergency_stop_measurement)
        layout.addWidget(QLabel("樣品 ID"))
        layout.addWidget(self.sample_id_edit)
        layout.addWidget(QLabel("儲存位置"))
        layout.addWidget(self.measurement_path_edit, 1)
        layout.addWidget(self.measurement_path_button)
        layout.addWidget(self.selected_recipe_label)
        layout.addWidget(self.hdr_session_button)
        layout.addWidget(self.white_light_status)
        layout.addWidget(self.white_light_button)
        layout.addWidget(self.start_measurement_button)
        layout.addWidget(self.stop_measurement_button)
        layout.addWidget(self.emergency_stop_button)
        return bar

    def _build_status_bar(self) -> None:
        bar = QStatusBar(self)
        self.setStatusBar(bar)
        self.status_message = QLabel("正在偵測相機…")
        self.camera_status = QLabel("相機 —")
        self.smu_status = QLabel("SMU —")
        self.zoom_status = QLabel("縮放 —")
        self.resolution_status = QLabel("影像 —")
        self.exposure_status = QLabel("曝光 —")
        self.gain_status = QLabel("Gain —")
        self.fps_status = QLabel("FPS —")
        bar.addWidget(self.status_message, 1)
        for widget in (
            self.camera_status,
            self.smu_status,
            self.zoom_status,
            self.resolution_status,
            self.exposure_status,
            self.gain_status,
            self.fps_status,
        ):
            bar.addPermanentWidget(widget)

    def _connect_signals(self) -> None:
        self.capture_button.clicked.connect(self.capture_current_frame)
        self.auto_capture_button.clicked.connect(self.auto_expose_and_capture)
        self.apply_manual_button.clicked.connect(self.apply_manual_exposure)
        self.auto_exposure_check.toggled.connect(self.toggle_auto_exposure)
        self.auto_target_spin.editingFinished.connect(
            lambda: self.controller.set_auto_exposure_target(self.auto_target_spin.value())
        )
        self.resolution_combo.currentIndexChanged.connect(self.change_resolution)
        self.image_view.zoom_changed.connect(lambda value: self.zoom_status.setText(f"縮放 {value:.1f}%"))

        self.device_panel.smu_scan_requested.connect(self.refresh_smu_devices)
        self.device_panel.smu_connect_requested.connect(self.connect_selected_smu)
        self.device_panel.smu_disconnect_requested.connect(self.disconnect_smu)
        self.device_panel.smu_selection_changed.connect(self._remember_smu_selection)
        self.device_panel.recipe_selection_changed.connect(self.on_recipe_selected)

        self.smu_manager.scan_started.connect(self.device_panel.set_smu_scanning)
        self.smu_manager.scan_finished.connect(self.on_smu_scan_finished)
        self.smu_manager.connection_started.connect(
            lambda _address: self.device_panel.set_smu_connecting()
        )
        self.smu_manager.connected.connect(self.on_smu_connected)
        self.smu_manager.disconnected.connect(self.on_smu_disconnected)
        self.smu_manager.status_changed.connect(self.status_message.setText)
        self.smu_manager.error_occurred.connect(self.show_smu_error)
        self.smu_manager.control.error_occurred.connect(self.show_smu_error)
        self.smu_manager.control.ownership_changed.connect(
            self.manual_smu_panel.update_ownership
        )
        self.smu_manager.control.output_changed.connect(self.manual_smu_panel.update_output)
        self.smu_manager.control.command_applied.connect(self.manual_smu_panel.update_command)
        self.smu_manager.control.readback_ready.connect(self.manual_smu_panel.update_readback)
        self.manual_smu_panel.output_requested.connect(self.request_manual_smu_output)
        self.manual_smu_panel.output_off_requested.connect(self.request_manual_smu_off)
        self.manual_smu_panel.emergency_off_requested.connect(self.request_smu_emergency_off)

        self.controller.frame_ready.connect(self.on_frame_ready)
        self.controller.camera_opened.connect(self.on_camera_opened)
        self.controller.camera_closed.connect(self.on_camera_closed)
        self.controller.exposure_changed.connect(self.on_exposure_changed)
        self.controller.auto_exposure_result.connect(self.on_auto_exposure_result)
        self.controller.fps_changed.connect(
            lambda fps, total: self.fps_status.setText(f"FPS {fps:.1f}｜幀 {total}")
        )
        self.controller.status_changed.connect(self.status_message.setText)
        self.controller.error_occurred.connect(self.show_error)
