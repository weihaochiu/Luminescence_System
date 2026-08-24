from __future__ import annotations

"""Main-window coordinator for application state and lifecycle ownership."""

from pathlib import Path
from typing import Any

from PySide6.QtCore import QSettings, QStandardPaths, QTimer
from PySide6.QtGui import QImage
from PySide6.QtWidgets import QDialog, QFileDialog, QMainWindow, QMessageBox

from core.error_reporter import ErrorReporter
from core.i18n import configure_i18n, i18n, tr
from . import __version__
from .camera_auto_exposure_settings import load_auto_exposure_target_percent
from .camera_auto_exposure_settings_dialog import (
    CameraAutoExposureSettingsDialog,
)
from .camera_controller import CameraController
from .camera_temperature_chart import CameraTemperatureChart
from .camera_temperature_monitor import CameraTemperatureMonitor
from .emergency_manager import EmergencyManager
from .general_settings_dialog import GeneralSettingsDialog
from .instrument_state_manager import InstrumentStateManager
from .main_window_devices import MainWindowDeviceMixin
from .main_window_ui import MainWindowUIMixin
from .main_window_measurement import attach_measurement_handlers
from .main_window_close import attach_close_handlers
from .main_window_errors import attach_error_handlers
from .recipe_dialog import RecipeManagerDialog
from .recipe_store import Recipe, RecipeStore
from .polarity_settings import PolaritySettingsStore
from .polarity_settings_dialog import PolaritySettingsDialog
from .relay_controller import RelayController, RelayService
from .main_window_relay import attach_relay_handlers
from .relay_settings import RelaySettingsStore
from .smu_manager import SMUManager
from .smu_monitor import SMUMonitor
from .smu_safety_dialog import SMUSafetyDialog, load_global_safety


class MainWindow(QMainWindow, MainWindowUIMixin, MainWindowDeviceMixin):
    """Top-level state owner and Recipe measurement coordinator."""

    def __init__(self) -> None:
        super().__init__()
        self.settings = QSettings()
        configure_i18n(self.settings)
        self.setWindowTitle(tr("app.title", version=__version__))
        self.resize(1500, 900)
        self.setMinimumSize(800, 600)

        app_data = QStandardPaths.writableLocation(QStandardPaths.StandardLocation.AppDataLocation)
        application_directory = Path(app_data) if app_data else Path.cwd()
        self.controller = CameraController(
            self,
            auto_exposure_target_percent=load_auto_exposure_target_percent(
                self.settings
            ),
            ae_calibration_store_path=(
                application_directory / "camera_ae_calibration.json"
            ),
        )
        self.temperature_monitor = CameraTemperatureMonitor(
            self.controller.read_temperature_c,
            lambda: self.controller.is_open,
            application_directory / "logs",
            parent=self,
        )
        self.temperature_chart = CameraTemperatureChart(self)
        self.smu_manager = SMUManager(self)
        self.instrument_state_manager = InstrumentStateManager(
            self.smu_manager.control, parent=self
        )
        self.smu_monitor = SMUMonitor(self.smu_manager.control, parent=self)
        limits, self.max_recipe_time_s, self.max_output_time_s = load_global_safety(
            self.settings
        )
        self.smu_manager.control.safety.limits = limits
        recipe_path = application_directory / "recipes.json"
        self.recipe_store = RecipeStore(recipe_path)
        relay_settings_path = application_directory / "relay_settings.json"
        self.relay_settings_store = RelaySettingsStore(relay_settings_path)
        polarity_settings_path = (
            application_directory
        ) / "polarity_settings.json"
        self.polarity_settings_store = PolaritySettingsStore(polarity_settings_path)
        self.relay_controller = RelayController()
        self.relay_service = RelayService(self.relay_controller, self.relay_settings_store)
        self.relay_service.set_routing_fault_handler(
            self.smu_manager.control.request_external_interlock
        )
        self.smu_manager.control.configure_safety_recovery(
            lambda: self.relay_service.safe_smu_output_channels_off("smu_recovery"),
            lambda: self.relay_service.safe_white_light_off("smu_recovery"),
        )
        self.emergency_manager = EmergencyManager(
            self.smu_manager.control,
            self.relay_service,
            parent=self,
        )
        self.error_reporter = ErrorReporter(parent=self)
        self.error_reporter.presenter = self._present_error
        self._error_center_dialog = None
        self._error_dialogs: set[object] = set()
        self.emergency_manager.completed.connect(self._on_emergency_completed)
        self.selected_recipe: Recipe | None = None
        self.devices: list[Any] = []
        self.camera_info: dict[str, Any] = {}
        self.last_image: QImage | None = None
        self._latest_scientific_frame: Any | None = None
        self._latest_effective_dn_status: dict[str, Any] = {}
        self._live_view_dn_roi: tuple[int, int, int, int] | None = None
        self._pending_auto_path: str | None = None
        self._capture_next_frame = False
        self._auto_capture_converged = False
        self._measurement_thread: Any | None = None
        self._measurement_worker: Any | None = None
        self._auto_connect_after_scan = False
        self._smu_reconnect_safety_pending = False
        self._close_in_progress = False

        self._build_actions()
        self._build_menu_and_toolbar()
        self._build_central_ui()
        self._build_status_bar()
        self._connect_signals()
        i18n.language_changed.connect(self._retranslate_application_shell)
        self._set_camera_controls_enabled(False)
        self.refresh_recipes()

        self.auto_capture_timer = QTimer(self)
        self.auto_capture_timer.setSingleShot(True)
        self.auto_capture_timer.setInterval(15000)
        self.auto_capture_timer.timeout.connect(self._on_auto_capture_timeout)
        self.emergency_manager.register_abort_action(
            "Measurement / Recipe abort",
            self._cancel_measurement_for_emergency,
        )
        self.emergency_manager.register_abort_action(
            "Camera acquisition stop",
            self._stop_camera_for_emergency,
        )

        QTimer.singleShot(50, self.refresh_devices)
        QTimer.singleShot(300, self.auto_connect_smu_on_startup)
        QTimer.singleShot(500, self.refresh_relay_connection)

    def _retranslate_application_shell(self, _language: str = "") -> None:
        self.setWindowTitle(tr("app.title", version=__version__))
        if hasattr(self, "main_toolbar"):
            self._retranslate_ui()

    def open_general_settings(self) -> None:
        GeneralSettingsDialog(self).exec()

    def refresh_recipes(self) -> None:
        try:
            self.recipe_store.load()
        except RuntimeError as exc:
            self.report_error(
                "REC-101",
                context={"operation": "load_recipe_store", "resource": str(self.recipe_store.path)},
                exception=exc,
            )
            return
        preferred = str(self.settings.value("recipe/last_selected_id", ""))
        self.device_panel.set_recipes(
            self.recipe_store.available(),
            preferred,
            global_safety=self.smu_manager.control.safety.limits,
        )
        if self.device_panel.selected_recipe() is None:
            self.selected_recipe = None
            if hasattr(self, "measurement_control_bar"):
                self.measurement_control_bar.set_active_channels([])
            self._update_measurement_controls()

    def on_recipe_selected(self, recipe_id: str) -> None:
        recipe = self.recipe_store.get(recipe_id) if recipe_id else None
        self.selected_recipe = recipe if recipe and recipe.is_available() else None
        if self.selected_recipe is not None:
            self.settings.setValue("recipe/last_selected_id", self.selected_recipe.recipe_id)
            self.measurement_control_bar.set_active_channels(
                [channel.channel for channel in self.selected_recipe.enabled_channels()]
            )
            self.status_message.setText(
                tr("recipe.selected_status", name=self.selected_recipe.name, version=self.selected_recipe.version)
            )
        else:
            self.measurement_control_bar.set_active_channels([])
        self._update_measurement_controls()

    def open_recipe_manager(self) -> None:
        dialog = RecipeManagerDialog(
            self.recipe_store,
            self,
            camera_resolutions=list(self.camera_info.get("resolutions", [])),
        )
        dialog.recipes_changed.connect(self.refresh_recipes)
        dialog.exec()
        self.refresh_recipes()

    def open_polarity_settings(self) -> None:
        dialog = PolaritySettingsDialog(self.polarity_settings_store, self)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            self.status_message.setText(tr("settings.polarity_updated"))

    def open_camera_auto_exposure_settings(self) -> None:
        dialog = CameraAutoExposureSettingsDialog(
            self.settings,
            self,
            controller=self.controller,
            measurement_running=lambda: self._measurement_worker is not None,
        )
        if dialog.exec() == QDialog.DialogCode.Accepted:
            self.controller.set_auto_exposure_target_percent(
                dialog.target_percent
            )
            self.status_message.setText(tr("camera.ae_target_updated", value=dialog.target_percent))

    def open_smu_safety_settings(self) -> None:
        dialog = SMUSafetyDialog(
            self.smu_manager.control.safety, self.settings, self
        )
        if dialog.exec() == QDialog.DialogCode.Accepted:
            _limits, self.max_recipe_time_s, self.max_output_time_s = load_global_safety(
                self.settings
            )
            self.refresh_recipes()
            self.status_message.setText(tr("settings.smu_safety_updated"))

    def choose_measurement_output_root(self) -> None:
        selected = QFileDialog.getExistingDirectory(self, tr("file.select_measurement_output"))
        if selected:
            self.measurement_path_edit.setText(selected)
            self.settings.setValue("measurement/output_root", selected)
        self._update_measurement_controls()

    def _on_sample_ids_changed(self) -> None:
        self._update_measurement_controls()

    def _update_measurement_controls(self) -> None:
        if not hasattr(self, "start_measurement_button"):
            return
        if self.selected_recipe is None:
            self.selected_recipe_label.setText(tr("common.not_selected"))
            reason = tr("measurement.select_valid_recipe")
        else:
            counts = self._effective_capture_counts(self.selected_recipe)
            self.selected_recipe_label.setText(
                tr("recipe.list_summary", name=self.selected_recipe.name,
                   version=self.selected_recipe.version,
                   channels=len(self.selected_recipe.enabled_channels()),
                   captures=counts["overall"])
            )
            blockers = []
            if not self.controller.is_open: blockers.append(tr("camera.not_connected"))
            if not self.smu_manager.is_connected: blockers.append(tr("smu.not_connected"))
            if not self.relay_controller.connected: blockers.append(tr("relay.not_connected"))
            if not self.measurement_path_edit.text().strip():
                blockers.append(tr("measurement.output_not_set"))
            missing_samples = self.measurement_control_bar.missing_sample_channels()
            if missing_samples:
                blockers.append(tr("measurement.sample_ids_missing", channels=", ".join(missing_samples)))
            reason = "; ".join(blockers) if blockers else tr("measurement.start_matrix")
        running = self._measurement_worker is not None
        if running:
            reason = tr("measurement.running")
        self.start_measurement_button.setEnabled(
            bool(self.selected_recipe is not None and not blockers and not running)
            if self.selected_recipe else False
        )
        self.start_measurement_button.setToolTip(reason)
        self.stop_measurement_button.setEnabled(self._measurement_worker is not None)
        self.stop_measurement_button.setToolTip(tr("measurement.safe_stop_tooltip"))

    def show_about(self) -> None:
        QMessageBox.about(
            self,
            tr("app.about_title"),
            tr("app.about_text", version=__version__),
        )

attach_relay_handlers(MainWindow)
attach_measurement_handlers(MainWindow)
attach_close_handlers(MainWindow)
attach_error_handlers(MainWindow)
