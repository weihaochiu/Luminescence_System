from __future__ import annotations

"""Construction and signal wiring for the main application window."""

from PySide6.QtCore import QSize, Qt
from PySide6.QtGui import QAction, QKeySequence
from PySide6.QtWidgets import (
    QComboBox,
    QDoubleSpinBox,
    QFormLayout,
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QSplitter,
    QSpinBox,
    QStatusBar,
    QStyle,
    QStackedWidget,
    QToolBar,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from core.i18n import tr
from .camera_exposure import ExposureMode
from .device_panel import DevicePanel
from .measurement_control_bar import MeasurementControlBar
from .responsive_layout import LayoutMode, ResponsiveLayoutManager
from .sidebar import SidebarItem, SidebarRegistry, SidebarSettingsDialog
from .smu_manual_panel import ManualSMUPanel
from .widgets import CollapsibleSection, ImageView


class MainWindowUIMixin:
    """Own only widget construction and signal connections."""

    def _build_actions(self) -> None:
        style = self.style()
        self.refresh_action = QAction(
            style.standardIcon(QStyle.StandardPixmap.SP_BrowserReload), tr("toolbar.refresh_devices"), self
        )
        self.refresh_action.setShortcut(QKeySequence("F5"))
        self.refresh_action.setToolTip(tr("toolbar.refresh_devices_tooltip"))
        self.connect_action = QAction(
            style.standardIcon(QStyle.StandardPixmap.SP_DialogOpenButton), tr("toolbar.camera_connection"), self
        )
        self.connect_action.setToolTip(tr("toolbar.camera_connection_tooltip"))
        self.capture_action = QAction(
            style.standardIcon(QStyle.StandardPixmap.SP_DialogSaveButton), tr("toolbar.capture_image"), self
        )
        self.capture_action.setShortcut(QKeySequence("Ctrl+S"))
        self.capture_action.setToolTip(tr("toolbar.capture_image_tooltip"))
        self.auto_capture_action = QAction(
            style.standardIcon(QStyle.StandardPixmap.SP_DialogApplyButton), tr("toolbar.auto_capture"), self
        )
        self.auto_capture_action.setToolTip(tr("toolbar.auto_capture_tooltip"))
        self.temperature_chart_action = QAction(tr("camera.temperature_chart"), self)
        self.temperature_chart_action.setToolTip(tr("camera.temperature_chart_tooltip"))
        self.fit_action = QAction(
            style.standardIcon(QStyle.StandardPixmap.SP_TitleBarMaxButton), tr("view.fit_window"), self
        )
        self.fit_action.setToolTip(tr("view.fit_window_tooltip"))
        self.actual_action = QAction(
            style.standardIcon(QStyle.StandardPixmap.SP_TitleBarNormalButton), tr("view.actual_size"), self
        )
        self.actual_action.setToolTip(tr("view.actual_size_tooltip"))
        self.exit_action = QAction(tr("app.exit"), self)
        self.exit_action.setShortcut(QKeySequence.StandardKey.Quit)
        self.about_action = QAction(tr("app.about"), self)
        self.recipe_manager_action = QAction(
            style.standardIcon(QStyle.StandardPixmap.SP_FileDialogDetailedView), tr("recipe.manager"), self
        )
        self.recipe_manager_action.setShortcut(QKeySequence("Ctrl+R"))
        self.recipe_manager_action.setToolTip(tr("recipe.manager_tooltip"))
        self.polarity_settings_action = QAction(tr("settings.polarity"), self)
        self.camera_auto_exposure_settings_action = QAction(
            tr("settings.auto_exposure"), self
        )
        self.camera_auto_exposure_settings_action.setToolTip(
            tr("settings.auto_exposure_tooltip")
        )
        self.polarity_settings_action.setToolTip(tr("settings.polarity_tooltip"))
        self.relay_settings_action = QAction(tr("settings.relay"), self)
        self.smu_safety_settings_action = QAction(tr("settings.smu_safety"), self)
        self.smu_safety_settings_action.setToolTip(
            tr("settings.smu_safety_tooltip")
        )
        self.relay_settings_action.setToolTip(tr("settings.relay_tooltip"))
        self.sidebar_settings_action = QAction(tr("settings.sidebar"), self)
        self.sidebar_settings_action.setToolTip(tr("settings.sidebar_tooltip"))
        self.smu_auto_connect_action = QAction(tr("settings.smu_auto_connect"), self)
        self.smu_auto_connect_action.setCheckable(True)
        self.smu_auto_connect_action.setChecked(
            self.settings.value("devices/auto_connect_smu", True, type=bool)
        )
        self.smu_auto_connect_action.setToolTip(
            tr("settings.smu_auto_connect_tooltip")
        )
        self.general_settings_action = QAction(tr("settings.general"), self)
        self.error_center_action = QAction(tr("error_center.title"), self)

        self.refresh_action.triggered.connect(self.refresh_devices)
        self.connect_action.triggered.connect(self.toggle_connection)
        self.capture_action.triggered.connect(self.capture_current_frame)
        self.auto_capture_action.triggered.connect(self.auto_expose_and_capture)
        self.temperature_chart_action.triggered.connect(self.open_temperature_chart)
        self.fit_action.triggered.connect(lambda: self.image_view.fit_to_window())
        self.actual_action.triggered.connect(lambda: self.image_view.actual_size())
        self.exit_action.triggered.connect(self.close)
        self.about_action.triggered.connect(self.show_about)
        self.recipe_manager_action.triggered.connect(self.open_recipe_manager)
        self.polarity_settings_action.triggered.connect(self.open_polarity_settings)
        self.camera_auto_exposure_settings_action.triggered.connect(
            self.open_camera_auto_exposure_settings
        )
        self.smu_safety_settings_action.triggered.connect(self.open_smu_safety_settings)
        self.relay_settings_action.triggered.connect(self.open_relay_settings)
        self.sidebar_settings_action.triggered.connect(self.open_sidebar_settings)
        self.smu_auto_connect_action.toggled.connect(
            lambda enabled: self.settings.setValue("devices/auto_connect_smu", enabled)
        )
        self.general_settings_action.triggered.connect(self.open_general_settings)
        self.error_center_action.triggered.connect(self.open_error_center)

    def _build_menu_and_toolbar(self) -> None:
        file_menu = self.menuBar().addMenu(tr("menu.file"))
        file_menu.addAction(self.capture_action)
        file_menu.addSeparator()
        file_menu.addAction(self.exit_action)

        camera_menu = self.menuBar().addMenu(tr("menu.camera"))
        camera_menu.addAction(self.refresh_action)
        camera_menu.addAction(self.connect_action)
        camera_menu.addAction(self.auto_capture_action)
        camera_menu.addSeparator()
        camera_menu.addAction(self.temperature_chart_action)

        view_menu = self.menuBar().addMenu(tr("menu.view"))
        view_menu.addAction(self.fit_action)
        view_menu.addAction(self.actual_action)

        settings_menu = self.menuBar().addMenu(tr("menu.settings"))
        settings_menu.addAction(self.general_settings_action)
        settings_menu.addSeparator()
        interface_menu = settings_menu.addMenu(tr("menu.interface"))
        interface_menu.addAction(self.sidebar_settings_action)
        camera_settings_menu = settings_menu.addMenu(tr("menu.camera_plain"))
        camera_settings_menu.addAction(self.camera_auto_exposure_settings_action)
        settings_menu.addSeparator()
        settings_menu.addAction(self.recipe_manager_action)
        settings_menu.addAction(self.polarity_settings_action)
        settings_menu.addAction(self.smu_safety_settings_action)
        settings_menu.addAction(self.relay_settings_action)
        settings_menu.addSeparator()
        settings_menu.addAction(self.smu_auto_connect_action)

        help_menu = self.menuBar().addMenu(tr("menu.help"))
        help_menu.addAction(self.error_center_action)
        help_menu.addSeparator()
        help_menu.addAction(self.about_action)

        toolbar = QToolBar(tr("toolbar.main"), self)
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
        self.emergency_stop_button = QPushButton(tr("common.emergency_stop"))
        self.emergency_stop_button.setObjectName("globalEmergencyStop")
        self.emergency_stop_button.setToolTip(
            tr("common.emergency_stop_tooltip")
        )
        toolbar.addWidget(self.emergency_stop_button)

        # Use font metrics so Windows DPI scaling cannot clip toolbar labels. Qt
        # moves excess actions into its overflow menu on compact windows.
        self.main_toolbar = toolbar
        metrics = toolbar.fontMetrics()
        for action in toolbar.actions():
            if action.isSeparator():
                continue
            button = toolbar.widgetForAction(action)
            if isinstance(button, QToolButton):
                button.setMinimumWidth(metrics.horizontalAdvance(action.text()) + 46)
                button.setMinimumHeight(metrics.height() + 18)
        self.addToolBar(toolbar)

    def _build_central_ui(self) -> None:
        self.image_view = ImageView()

        self.device_panel = DevicePanel()
        self.camera_list = self.device_panel.camera_list

        self.capture_button = QPushButton(tr("camera.capture"))
        self.capture_button.setIcon(self.style().standardIcon(QStyle.StandardPixmap.SP_DialogSaveButton))
        self.capture_button.setMinimumHeight(40)
        self.auto_capture_button = QPushButton(tr("camera.capture_after_auto_exposure"))
        self.auto_capture_button.setMinimumHeight(40)

        capture_buttons = QHBoxLayout()
        capture_buttons.addWidget(self.capture_button)
        capture_buttons.addWidget(self.auto_capture_button)

        self.resolution_combo = QComboBox()
        self.format_combo = QComboBox()
        self.format_combo.addItem(tr("camera.format_rgb24"), "rgb24")
        self.format_combo.setEnabled(False)

        capture_content = QWidget()
        capture_layout = QVBoxLayout(capture_content)
        capture_layout.setContentsMargins(8, 8, 8, 10)
        capture_layout.addLayout(capture_buttons)

        resolution_content = QWidget()
        resolution_layout = QVBoxLayout(resolution_content)
        resolution_layout.setContentsMargins(8, 8, 8, 10)
        capture_form = QFormLayout()
        capture_form.addRow(tr("camera.resolution"), self.resolution_combo)
        capture_form.addRow(tr("camera.format"), self.format_combo)
        resolution_layout.addLayout(capture_form)

        self.exposure_mode_combo = QComboBox()
        for mode in ExposureMode:
            self.exposure_mode_combo.addItem(mode.label, mode.value)

        self.exposure_spin = QDoubleSpinBox()
        self.exposure_spin.setDecimals(3)
        self.exposure_spin.setSuffix(" ms")
        self.exposure_spin.setKeyboardTracking(False)
        self.exposure_spin.setSingleStep(1.0)
        self.gain_spin = QSpinBox()
        self.gain_spin.setSuffix(" %")
        self.gain_spin.setKeyboardTracking(False)
        self.apply_manual_button = QPushButton(tr("camera.apply_manual_settings"))

        self.current_exposure_value = QLabel("--")
        self.current_gain_value = QLabel("--")
        auto_page = QWidget()
        auto_form = QFormLayout(auto_page)
        auto_form.setContentsMargins(0, 0, 0, 0)
        auto_form.addRow(tr("camera.exposure_current"), self.current_exposure_value)
        auto_form.addRow(tr("camera.gain_current"), self.current_gain_value)
        self.auto_exposure_target_percent_value = QLabel(
            f"{self.controller.auto_exposure_target_percent} %"
        )
        self.auto_exposure_target_dn_value = QLabel(tr("common.undetermined"))
        auto_form.addRow(tr("camera.ae_target"), self.auto_exposure_target_percent_value)
        auto_form.addRow(tr("camera.target_dn"), self.auto_exposure_target_dn_value)

        manual_page = QWidget()
        manual_layout = QVBoxLayout(manual_page)
        manual_layout.setContentsMargins(0, 0, 0, 0)
        manual_form = QFormLayout()
        manual_form.addRow(tr("camera.exposure_time"), self.exposure_spin)
        manual_form.addRow(tr("camera.gain"), self.gain_spin)
        manual_layout.addLayout(manual_form)
        manual_layout.addWidget(self.apply_manual_button)

        self.exposure_stack = QStackedWidget()
        self.exposure_stack.addWidget(auto_page)
        self.exposure_stack.addWidget(manual_page)
        self.mean_effective_dn_value = QLabel(tr("common.undetermined"))
        self.mean_effective_dn_value.setToolTip(
            tr("camera.mean_effective_dn_tooltip")
        )
        self.effective_dn_percent_value = QLabel("--")
        self.sensor_bit_depth_value = QLabel("--")
        self.raw_value_alignment_value = QLabel("Unknown")
        self.camera_connection_hint = QLabel(tr("camera.connect_first"))
        self.camera_connection_hint.setStyleSheet("color: #a66a00;")

        exposure_content = QWidget()
        exposure_layout = QVBoxLayout(exposure_content)
        exposure_layout.setContentsMargins(8, 8, 8, 10)
        exposure_form = QFormLayout()
        exposure_form.addRow(tr("camera.exposure_mode"), self.exposure_mode_combo)
        exposure_layout.addLayout(exposure_form)
        exposure_layout.addWidget(self.exposure_stack)
        exposure_separator = QFrame()
        exposure_separator.setFrameShape(QFrame.Shape.HLine)
        exposure_layout.addWidget(exposure_separator)
        brightness_form = QFormLayout()
        brightness_form.addRow(tr("camera.mean_dn_current"), self.mean_effective_dn_value)
        brightness_form.addRow(tr("camera.signal_ratio"), self.effective_dn_percent_value)
        brightness_form.addRow("Sensor", self.sensor_bit_depth_value)
        brightness_form.addRow("Alignment", self.raw_value_alignment_value)
        exposure_layout.addLayout(brightness_form)
        exposure_layout.addWidget(self.camera_connection_hint)

        temperature_content = QWidget()
        temperature_layout = QVBoxLayout(temperature_content)
        temperature_layout.setContentsMargins(8, 8, 8, 10)
        self.camera_temperature_value = QLabel("N/A")
        self.camera_temperature_value.setStyleSheet("font-size: 18px; font-weight: 600;")
        self.temperature_chart_button = QPushButton(tr("camera.open_temperature_chart"))
        temperature_layout.addWidget(self.camera_temperature_value)
        temperature_layout.addWidget(self.temperature_chart_button)

        self.manual_smu_panel = ManualSMUPanel(
            limits=self.smu_manager.control.safety.limits,
            settings=self.settings,
        )

        info_content = QWidget()
        info_layout = QFormLayout(info_content)
        info_layout.setContentsMargins(8, 8, 8, 10)
        self.model_value = QLabel("—")
        self.sdk_value = QLabel("—")
        self.color_value = QLabel("—")
        self.model_value.setWordWrap(True)
        info_layout.addRow(tr("camera.model"), self.model_value)
        info_layout.addRow(tr("camera.sensor"), self.color_value)
        info_layout.addRow("SDK", self.sdk_value)

        sidebar_body = QWidget()
        sidebar_layout = QVBoxLayout(sidebar_body)
        sidebar_layout.setContentsMargins(3, 3, 3, 3)
        sidebar_layout.setSpacing(3)
        sidebar_layout.addStretch()
        sections = (
            SidebarItem("camera_connection", tr("toolbar.camera_connect"), CollapsibleSection(tr("toolbar.camera_connect"), self.device_panel.camera_content, True), 10),
            SidebarItem("smu_connection", tr("toolbar.smu_connect"), CollapsibleSection(tr("toolbar.smu_connect"), self.device_panel.smu_content, True), 20),
            SidebarItem("manual_smu", tr("toolbar.manual_smu"), CollapsibleSection(tr("smu.manual_output"), self.manual_smu_panel, True), 30),
            SidebarItem("recipe", tr("recipe.selection"), CollapsibleSection(tr("recipe.title"), self.device_panel.recipe_content, True), 40),
            SidebarItem("manual_capture", tr("camera.manual_capture"), CollapsibleSection(tr("camera.manual_capture"), capture_content, True), 50),
            SidebarItem("resolution", tr("camera.resolution"), CollapsibleSection(tr("camera.resolution"), resolution_content, True), 60),
            SidebarItem("exposure", tr("camera.exposure_control"), CollapsibleSection(tr("camera.exposure_control"), exposure_content, True), 70),
            SidebarItem("temperature", tr("camera.temperature"), CollapsibleSection(tr("camera.temperature"), temperature_content, True), 75),
            SidebarItem("camera_info", tr("camera.information"), CollapsibleSection(tr("camera.information"), info_content, False), 80),
        )
        self.sidebar_registry = SidebarRegistry(sidebar_layout, self.settings)
        for item in sections:
            self.sidebar_registry.register(item)
        self.sidebar_registry.restore()

        sidebar_scroll = QScrollArea()
        sidebar_scroll.setWidgetResizable(True)
        sidebar_scroll.setWidget(sidebar_body)
        sidebar_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        sidebar_scroll.setFrameShape(QFrame.Shape.NoFrame)
        sidebar_scroll.setMinimumWidth(
            max(235, self.fontMetrics().horizontalAdvance("SMU 手動輸出 MMMMMMMMMM"))
        )
        self.device_sidebar_scroll = sidebar_scroll

        workspace_header = QFrame()
        workspace_header.setObjectName("workspaceHeader")
        header_layout = QHBoxLayout(workspace_header)
        header_layout.setContentsMargins(10, 5, 10, 5)
        self.view_title = QLabel(tr("camera.live_view"))
        self.view_title.setStyleSheet("font-weight: 600;")
        header_layout.addWidget(self.view_title)
        header_layout.addStretch()
        self.select_dn_roi_button = QToolButton()
        self.select_dn_roi_button.setText(tr("camera.select_dn_roi"))
        self.select_dn_roi_button.setToolTip(
            tr("camera.select_dn_roi_tooltip")
        )
        self.clear_dn_roi_button = QToolButton()
        self.clear_dn_roi_button.setText(tr("camera.clear_roi"))
        self.clear_dn_roi_button.setToolTip(
            tr("camera.clear_roi_tooltip")
        )
        self.live_view_roi_value = QLabel(tr("camera.roi_not_set"))
        self.live_view_roi_value.setMinimumWidth(0)
        self.live_view_roi_value.setSizePolicy(
            QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred
        )
        self.live_view_roi_dn_value = QLabel(tr("camera.roi_mean_dn_empty"))
        self.live_view_roi_dn_value.setMinimumWidth(0)
        self.live_view_roi_dn_value.setSizePolicy(
            QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred
        )
        self.live_view_roi_dn_value.setToolTip(
            tr("camera.roi_mean_dn_tooltip")
        )
        self.live_view_ae_metering_value = QLabel(tr("camera.ae_metering_empty"))
        self.live_view_ae_metering_value.setMinimumWidth(0)
        self.live_view_ae_metering_value.setSizePolicy(
            QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred
        )
        self.select_dn_roi_button.setEnabled(False)
        self.clear_dn_roi_button.setEnabled(False)
        for widget in (
            self.select_dn_roi_button,
            self.clear_dn_roi_button,
            self.live_view_roi_value,
            self.live_view_roi_dn_value,
            self.live_view_ae_metering_value,
        ):
            header_layout.addWidget(widget)

        workspace = QWidget()
        workspace_layout = QVBoxLayout(workspace)
        workspace_layout.setContentsMargins(0, 0, 0, 0)
        workspace_layout.setSpacing(0)
        workspace_layout.addWidget(workspace_header)
        workspace_layout.addWidget(self.image_view, 1)
        workspace.setMinimumWidth(320)

        self.main_splitter = QSplitter(Qt.Orientation.Horizontal)
        self.main_splitter.setChildrenCollapsible(False)
        self.main_splitter.addWidget(sidebar_scroll)
        self.main_splitter.addWidget(workspace)
        self.main_splitter.setStretchFactor(0, 0)
        self.main_splitter.setStretchFactor(1, 1)
        self.main_splitter.setSizes([300, 1200])

        operation_bar = self._build_measurement_operation_bar()
        center = QWidget()
        center_layout = QVBoxLayout(center)
        center_layout.setContentsMargins(0, 0, 0, 0)
        center_layout.setSpacing(1)
        center_layout.addWidget(self.main_splitter, 1)
        center_layout.addWidget(operation_bar)
        self.setCentralWidget(center)
        self.responsive_layout_manager = ResponsiveLayoutManager(
            self, operation_bar, parent=self
        )
        self.responsive_layout_manager.mode_changed.connect(
            self._on_responsive_layout_changed
        )

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
            #globalEmergencyStop { background: #9b111e; color: white; font-weight: 700; border: 2px solid #5e0000; padding: 4px 12px; }
            #globalEmergencyStop:hover { background: #b71c1c; border-color: #3f0000; }
            QScrollArea { background: #eef0f1; }
            """
        )

    def _build_measurement_operation_bar(self) -> QFrame:
        bar = MeasurementControlBar()
        self.measurement_control_bar = bar
        for name in (
            "sample_id_edit",
            "sample_id_edits",
            "measurement_path_edit",
            "measurement_path_button",
            "selected_recipe_label",
            "white_light_status",
            "white_light_button",
            "start_measurement_button",
            "stop_measurement_button",
        ):
            setattr(self, name, getattr(bar, name))
        self.measurement_path_edit.setText(str(self.settings.value("measurement/output_root", "")))
        self.measurement_path_button.clicked.connect(self.choose_measurement_output_root)
        self.white_light_button.setEnabled(False)
        self.white_light_button.clicked.connect(self.toggle_white_light)
        bar.sample_ids_changed.connect(self._on_sample_ids_changed)
        self.start_measurement_button.clicked.connect(self.begin_el_matrix_measurement)
        self.stop_measurement_button.clicked.connect(self.stop_background_measurement)
        return bar

    def _on_responsive_layout_changed(self, mode: LayoutMode) -> None:
        if not hasattr(self, "fps_status"):
            return
        compact = mode is LayoutMode.COMPACT
        standard = mode is LayoutMode.STANDARD
        self.zoom_status.setVisible(not compact)
        self.resolution_status.setVisible(not compact)
        self.exposure_status.setVisible(not compact)
        self.gain_status.setVisible(not compact)
        self.fps_status.setVisible(not compact and not standard)

    def _build_status_bar(self) -> None:
        bar = QStatusBar(self)
        self.setStatusBar(bar)
        self.status_message = QLabel(tr("camera.detecting"))
        self.camera_status = QLabel(tr("camera.status_empty"))
        self.smu_status = QLabel("SMU —")
        self.zoom_status = QLabel(tr("view.zoom_empty"))
        self.resolution_status = QLabel(tr("camera.image_status_empty"))
        self.exposure_status = QLabel(tr("camera.exposure_status_empty"))
        self.gain_status = QLabel(tr("camera.gain_status_empty"))
        self.fps_status = QLabel(tr("camera.fps_empty"))
        self.temperature_status = QLabel(tr("camera.temperature_unavailable"))
        bar.addWidget(self.status_message, 1)
        for widget in (
            self.camera_status,
            self.smu_status,
            self.zoom_status,
            self.resolution_status,
            self.exposure_status,
            self.gain_status,
            self.fps_status,
            self.temperature_status,
        ):
            bar.addPermanentWidget(widget)

    def _connect_signals(self) -> None:
        self.capture_button.clicked.connect(self.capture_current_frame)
        self.auto_capture_button.clicked.connect(self.auto_expose_and_capture)
        self.temperature_chart_button.clicked.connect(self.open_temperature_chart)
        self.apply_manual_button.clicked.connect(self.apply_manual_exposure)
        self.exposure_mode_combo.currentIndexChanged.connect(self.change_exposure_mode)
        self.resolution_combo.currentIndexChanged.connect(self.change_resolution)
        self.image_view.zoom_changed.connect(lambda value: self.zoom_status.setText(tr("view.zoom_percent", value=f"{value:.1f}")))
        self.select_dn_roi_button.clicked.connect(
            self.begin_live_view_dn_roi_selection
        )
        self.clear_dn_roi_button.clicked.connect(self.clear_live_view_dn_roi)
        self.image_view.roi_selected.connect(self.on_live_view_dn_roi_selected)
        self.image_view.roi_cleared.connect(self.on_live_view_dn_roi_cleared)

        self.device_panel.smu_scan_requested.connect(self.refresh_smu_devices)
        self.device_panel.smu_connect_requested.connect(self.connect_selected_smu)
        self.device_panel.smu_disconnect_requested.connect(self.disconnect_smu)
        self.device_panel.smu_selection_changed.connect(self._remember_smu_selection)
        self.device_panel.recipe_selection_changed.connect(self.on_recipe_selected)

        self.smu_manager.scan_started.connect(self.device_panel.set_smu_scanning)
        self.smu_manager.scan_finished.connect(self.on_smu_scan_finished)
        self.smu_manager.connection_started.connect(self.on_smu_connection_started)
        self.smu_manager.connected.connect(self.on_smu_connected)
        self.smu_manager.connected.connect(lambda _device: self._update_measurement_controls())
        self.smu_manager.connection_failed.connect(self.on_smu_connection_failed)
        self.smu_manager.disconnected.connect(self.on_smu_disconnected)
        self.smu_manager.disconnected.connect(self._update_measurement_controls)
        self.smu_manager.error_occurred.connect(self.show_smu_error)
        self.smu_manager.control.error_occurred.connect(self.show_smu_error)
        self.instrument_state_manager.state_changed.connect(self.update_smu_ui_state)
        self.smu_manager.control.manual_polarity_changed.connect(
            self.manual_smu_panel.update_polarity
        )
        self.smu_manager.control.manual_sequence_status.connect(
            self.manual_smu_panel.update_sequence_status
        )
        self.smu_manager.control.manual_sequence_finished.connect(
            self.on_manual_smu_sequence_finished
        )
        self.smu_manager.control.manual_channel_changed.connect(
            self.manual_smu_panel.update_active_channel
        )
        self.smu_manager.control.command_applied.connect(self.manual_smu_panel.update_command)
        self.smu_manager.control.readback_ready.connect(self.manual_smu_panel.update_readback)
        self.manual_smu_panel.output_requested.connect(self.request_manual_smu_output)
        self.manual_smu_panel.output_off_requested.connect(self.request_manual_smu_off)
        self.manual_smu_panel.handover_requested.connect(
            self.request_recipe_to_manual_handover
        )
        self.emergency_stop_button.clicked.connect(self.emergency_stop_measurement)
        self.instrument_state_manager.refresh()

        self.controller.frame_ready.connect(self.on_frame_ready)
        self.controller.scientific_frame_ready.connect(
            self.on_scientific_frame_ready
        )
        self.controller.camera_opened.connect(self.on_camera_opened)
        self.controller.camera_opened.connect(lambda _info: self._update_measurement_controls())
        self.controller.camera_closing.connect(self.temperature_monitor.stop)
        self.controller.camera_closed.connect(self.on_camera_closed)
        self.controller.camera_closed.connect(self._update_measurement_controls)
        self.controller.exposure_changed.connect(self.on_exposure_changed)
        self.controller.exposure_status_changed.connect(self.on_exposure_status_changed)
        self.controller.effective_dn_status_changed.connect(
            self.on_effective_dn_status_changed
        )
        self.controller.auto_exposure_result.connect(self.on_auto_exposure_result)
        self.controller.ae_calibration_finished.connect(
            self.on_ae_calibration_finished
        )
        self.controller.fps_changed.connect(
            lambda fps, total: self.fps_status.setText(tr("camera.fps_frames", fps=f"{fps:.1f}", total=total))
        )
        self.controller.status_changed.connect(self.status_message.setText)
        self.controller.error_occurred.connect(self.show_error)
        self.temperature_monitor.session_started.connect(self.temperature_chart.start_session)
        self.temperature_monitor.sample_received.connect(self.on_temperature_sample)
        self.temperature_monitor.sample_received.connect(self.temperature_chart.add_sample)
        self.temperature_monitor.availability_changed.connect(
            self.on_temperature_availability_changed
        )

    def open_sidebar_settings(self) -> None:
        dialog = SidebarSettingsDialog(self.sidebar_registry, self)
        dialog.exec()
