from __future__ import annotations

"""Main-window coordinator for application state and lifecycle ownership."""

from pathlib import Path
from typing import Any

from PySide6.QtCore import QSettings, QStandardPaths, QTimer
from PySide6.QtGui import QCloseEvent, QImage
from PySide6.QtWidgets import QDialog, QFileDialog, QMainWindow, QMessageBox

from . import __version__
from .camera_controller import CameraController
from .emergency_manager import EmergencyManager
from .hdr_settings import HDRSettingsStore
from .hdr_settings_dialog import HDRSettingsDialog
from .hdr_workflow import HDRSessionState, choose_hdr_session
from .instrument_state_manager import InstrumentStateManager
from .main_window_devices import MainWindowDeviceMixin
from .main_window_ui import MainWindowUIMixin
from .main_window_measurement import attach_measurement_handlers
from .recipe_dialog import RecipeManagerDialog
from .recipe_store import Recipe, RecipeStore
from .polarity_settings import PolaritySettingsStore
from .polarity_settings_dialog import PolaritySettingsDialog
from .relay_controller import RelayController, RelayService
from .main_window_relay import attach_relay_handlers
from .relay_settings import RelaySettingsStore
from .smu_manager import SMUManager
from .smu_monitor import SMUMonitor
class MainWindow(QMainWindow, MainWindowUIMixin, MainWindowDeviceMixin):
    """Top-level state owner and Recipe/HDR measurement coordinator."""

    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle(f"EL 量測設備控制程式 v{__version__}")
        self.resize(1500, 900)
        self.setMinimumSize(800, 600)

        self.controller = CameraController(self)
        self.smu_manager = SMUManager(self)
        self.instrument_state_manager = InstrumentStateManager(
            self.smu_manager.control, parent=self
        )
        self.smu_monitor = SMUMonitor(self.smu_manager.control, parent=self)
        self.settings = QSettings()
        app_data = QStandardPaths.writableLocation(QStandardPaths.StandardLocation.AppDataLocation)
        recipe_path = (Path(app_data) if app_data else Path.cwd()) / "recipes.json"
        self.recipe_store = RecipeStore(recipe_path)
        hdr_settings_path = (Path(app_data) if app_data else Path.cwd()) / "hdr_settings.json"
        self.hdr_settings_store = HDRSettingsStore(
            hdr_settings_path, self.recipe_store.legacy_hdr_settings_candidate
        )
        relay_settings_path = (Path(app_data) if app_data else Path.cwd()) / "relay_settings.json"
        self.relay_settings_store = RelaySettingsStore(relay_settings_path)
        polarity_settings_path = (
            Path(app_data) if app_data else Path.cwd()
        ) / "polarity_settings.json"
        self.polarity_settings_store = PolaritySettingsStore(polarity_settings_path)
        self.relay_controller = RelayController()
        self.relay_service = RelayService(self.relay_controller, self.relay_settings_store)
        self.emergency_manager = EmergencyManager(
            self.smu_manager.control,
            self.relay_service,
            parent=self,
        )
        self.selected_recipe: Recipe | None = None
        self.hdr_session_state: HDRSessionState | None = None
        self.devices: list[Any] = []
        self.camera_info: dict[str, Any] = {}
        self.last_image: QImage | None = None
        self._pending_auto_path: str | None = None
        self._capture_next_frame = False
        self._auto_capture_converged = False
        self._measurement_thread: Any | None = None
        self._measurement_worker: Any | None = None
        self._auto_connect_after_scan = False

        self._build_actions()
        self._build_menu_and_toolbar()
        self._build_central_ui()
        self._build_status_bar()
        self._connect_signals()
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

    def refresh_recipes(self) -> None:
        try:
            self.recipe_store.load()
        except RuntimeError as exc:
            QMessageBox.warning(self, "Recipe 讀取錯誤", str(exc))
            return
        preferred = str(self.settings.value("recipe/last_selected_id", ""))
        self.device_panel.set_recipes(self.recipe_store.available(), preferred)
        if self.device_panel.selected_recipe() is None:
            self.selected_recipe = None
            self._update_measurement_controls()

    def on_recipe_selected(self, recipe_id: str) -> None:
        recipe = self.recipe_store.get(recipe_id) if recipe_id else None
        self.selected_recipe = recipe if recipe and recipe.is_available() else None
        self.hdr_session_state = None
        if self.selected_recipe is not None:
            self.settings.setValue("recipe/last_selected_id", self.selected_recipe.recipe_id)
            if self.selected_recipe.output.root_directory:
                self.measurement_path_edit.setText(self.selected_recipe.output.root_directory)
            self.status_message.setText(
                f"已選擇 Recipe：{self.selected_recipe.name} v{self.selected_recipe.version}"
            )
        self._update_measurement_controls()

    def open_recipe_manager(self) -> None:
        dialog = RecipeManagerDialog(self.recipe_store, self)
        dialog.recipes_changed.connect(self.refresh_recipes)
        dialog.exec()
        self.refresh_recipes()

    def open_hdr_settings(self) -> None:
        dialog = HDRSettingsDialog(self.hdr_settings_store, self)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            self.hdr_session_state = None
            self.status_message.setText(
                "HDR 系統設定已更新；既有量測快照與 T0 Profile 不會被覆寫"
            )
            self._update_measurement_controls()

    def open_polarity_settings(self) -> None:
        dialog = PolaritySettingsDialog(self.polarity_settings_store, self)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            self.status_message.setText(
                "極性確認共用設定已更新；後續手動輸出與 Recipe 將使用新設定"
            )

    def choose_measurement_output_root(self) -> None:
        selected = QFileDialog.getExistingDirectory(self, "選擇量測資料儲存位置")
        if selected:
            self.measurement_path_edit.setText(selected)
            self.settings.setValue("measurement/output_root", selected)
        self._update_measurement_controls()

    def configure_hdr_session(self) -> None:
        if self.selected_recipe is None:
            QMessageBox.information(self, "尚未選擇 Recipe", "請先選擇已啟用且通過驗證的 Recipe。")
            return
        initial_directory = str(
            self.settings.value("measurement/last_hdr_profile_directory", "")
            or self.measurement_path_edit.text()
        )
        state = choose_hdr_session(
            self,
            self.sample_id_edit.text(),
            self.selected_recipe,
            self.camera_info,
            initial_directory,
            self.hdr_settings_store.settings,
        )
        if state is None:
            return
        self.hdr_session_state = state
        if state.profile_path:
            self.settings.setValue(
                "measurement/last_hdr_profile_directory", str(Path(state.profile_path).parent)
            )
        self._update_measurement_controls()

    def _on_sample_id_changed(self, text: str) -> None:
        if self.hdr_session_state is not None and text.strip() != self.hdr_session_state.sample_id:
            self.hdr_session_state = None
        self._update_measurement_controls()

    def _update_measurement_controls(self) -> None:
        if not hasattr(self, "start_measurement_button"):
            return
        if self.selected_recipe is None:
            self.selected_recipe_label.setText("尚未選擇")
            self.hdr_session_button.setText("HDR：未設定")
            self.hdr_session_button.setEnabled(False)
            reason = "請先從左側選擇已啟用且通過驗證的 Recipe。"
        else:
            mode = "電流" if self.selected_recipe.el_sweep.drive_mode == "current" else "電壓"
            self.selected_recipe_label.setText(
                f"{self.selected_recipe.name} v{self.selected_recipe.version}\n"
                f"{mode}模式｜{len(self.selected_recipe.enabled_points())} EL 點｜"
                f"{len(self.selected_recipe.dark_profiles())} Dark Profiles"
            )
            if self.selected_recipe.hdr.enabled:
                self.hdr_session_button.setEnabled(True)
                self.hdr_session_button.setText(
                    self.hdr_session_state.short_label if self.hdr_session_state else "設定 HDR 量測…"
                )
                self.hdr_session_button.setToolTip(
                    "選擇首次量測（T0 自動校正）或 Aging／重複量測（匯入並鎖定 T0 Profile）"
                )
            else:
                self.hdr_session_button.setText("HDR：關閉")
                self.hdr_session_button.setEnabled(False)
                self.hdr_session_button.setToolTip("目前 Recipe 未啟用定量 HDR")
            reason = (
                "本版已完成極性確認、Dark I–V、Dark Frames 與電流／電壓 EL 的 Recipe "
                "介面及驗證；手動 SMU 輸出已具集中式安全控制，但 Recipe 尚未加入完整的"
                "四階段 SMU 與相機同步執行，"
                "因此開始量測暫不開放。"
            )
        self.start_measurement_button.setEnabled(False)
        self.start_measurement_button.setToolTip(reason)
        self.stop_measurement_button.setEnabled(False)
        self.stop_measurement_button.setToolTip("量測執行功能完成後，停止按鈕會在量測期間啟用。")

    def _measurement_not_implemented(self) -> None:
        QMessageBox.information(
            self,
            "量測執行尚未開放",
            "本版已完成四階段 Recipe 建立、驗證與選擇。SMU 安全狀態機與同步拍攝將在下一階段加入。",
        )

    def _revalidate_locked_hdr_profile(self) -> None:
        state = self.hdr_session_state
        if (
            state is None
            or state.mode != "stability_locked"
            or state.profile is None
            or self.selected_recipe is None
        ):
            return
        errors, _warnings = state.profile.compatibility_issues(
            self.sample_id_edit.text(),
            self.selected_recipe,
            self.camera_info,
            self.hdr_settings_store.settings,
        )
        if errors:
            self.hdr_session_state = None
            self._update_measurement_controls()
            QMessageBox.critical(
                self,
                "已取消 HDR Profile 鎖定",
                "連接相機後發現首次量測 Profile 不相容：\n\n• " + "\n• ".join(errors),
            )

    def show_about(self) -> None:
        QMessageBox.about(
            self,
            "關於 EL 量測設備控制程式",
            f"EL 量測設備控制程式 v{__version__}\n\n"
            "功能：即時預覽、手動曝光、手動 gain、持續自動曝光、"
            "單次自動曝光後拍攝、TIFF／PNG／JPEG 儲存，"
            "VISA SMU 掃描、選擇、安全連線、手動 CV／CC，以及 Recipe 建立、驗證與選擇。\n\n"
            "SMU 支援：Keysight B2900 系列（手動輸出需先進行實機安全驗證）\n"
            "Recipe：極性確認 → Dark I–V → Dark Frames → 電流／電壓 EL\n"
            "Recipe 自動執行仍安全停用\n"
            "相機介面：RisingCam SDK 57.27250.20241216",
        )

    def closeEvent(self, event: QCloseEvent) -> None:  # noqa: N802 - Qt API name
        self.stop_background_measurement()
        self.smu_monitor.stop()
        self.controller.close_camera()
        self.smu_manager.shutdown()
        self.relay_service.shutdown()
        event.accept()

attach_relay_handlers(MainWindow)
attach_measurement_handlers(MainWindow)
