from __future__ import annotations

"""Background Recipe lifecycle wiring with centralized SMU cleanup."""

from typing import Any

from PySide6.QtCore import QThread
from PySide6.QtWidgets import QMessageBox

from .camera_capture_bridge import CameraCaptureBridge
from .el_matrix_hardware import ELMatrixHardwareAdapter
from .el_matrix_plan import ELMatrixPlan, format_duration, format_finish_time
from .el_matrix_runner import ELMatrixRunner, MatrixRuntimeProgress
from .measurement_progress_dialog import MeasurementProgressDialog
from .measurement_worker import MeasurementProgress, MeasurementWorker
from .smu_control import SMUInterlockError, SMUOwnership


def _best_effort_routing_off(self: Any, source: str) -> bool:
    try:
        return bool(self.relay_service.safe_smu_output_channels_off(source))
    except Exception as exc:
        self.status_message.setText(f"Routing Safe OFF failed: {exc}")
        return False


def start_background_measurement(self: Any, run: Any) -> bool:
    if self._measurement_thread is not None:
        raise RuntimeError("Measurement is already running")
    control = self.smu_manager.control
    if control.ownership is SMUOwnership.MANUAL:
        detail = "\n\n啟動 Recipe 前必須先安全關閉手動輸出。" if control.output_enabled else ""
        answer = QMessageBox.question(
            self,
            "手動 SMU 輸出仍在使用中",
            "SMU 目前處於手動輸出模式。" + detail +
            "\n\n是否關閉手動輸出並開始 Recipe？",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.Cancel,
            QMessageBox.StandardButton.Cancel,
        )
        if answer != QMessageBox.StandardButton.Yes:
            return False
    try:
        self.emergency_manager.begin_operator_operation()
        control.prepare_recipe_start(close_manual=True)
    except SMUInterlockError as exc:
        self.show_smu_error(str(exc))
        return False
    thread = QThread(self)
    worker = MeasurementWorker(run)
    worker.moveToThread(thread)
    thread.started.connect(worker.execute)
    worker.progress_changed.connect(self._on_measurement_progress)
    worker.finished.connect(self._on_measurement_finished)
    worker.cancelled.connect(self._on_measurement_cancelled)
    worker.failed.connect(self._on_measurement_failed)
    for signal in (worker.finished, worker.cancelled, worker.failed):
        signal.connect(thread.quit)
    thread.finished.connect(worker.deleteLater)
    thread.finished.connect(thread.deleteLater)
    thread.finished.connect(self._clear_measurement_worker)
    self._measurement_thread = thread
    self._measurement_worker = worker
    self.stop_measurement_button.setEnabled(True)
    self.start_measurement_button.setEnabled(False)
    thread.start()
    return True


def stop_background_measurement(self: Any) -> None:
    if self._measurement_worker is not None:
        self._measurement_worker.request_cancel()
    smu_safe = self.smu_manager.control.safe_shutdown(SMUOwnership.RECIPE)
    if smu_safe:
        _best_effort_routing_off(self, "stop_measurement")
    self.relay_service.safe_white_light_off("stop_measurement")


def emergency_stop_measurement(self: Any) -> None:
    workflow = "Recipe / measurement" if self._measurement_worker is not None else "idle / manual"
    report = self.emergency_manager.trigger(workflow)
    self.manual_smu_panel.reset_for_output_off()
    self._update_white_light_control()
    failed = "；".join(report.failures)
    suffix = f"；注意：{failed}" if failed else ""
    self.status_message.setText(
        "已執行緊急停止：量測已中止，SMU OUTPUT OFF 已排程，白光與相機已停止"
        + suffix
    )


def _cancel_measurement_for_emergency(self: Any) -> None:
    if self._measurement_worker is not None:
        self._measurement_worker.request_cancel()


def _stop_camera_for_emergency(self: Any) -> None:
    self._cancel_auto_capture()
    self.controller.close_camera()


def _on_measurement_progress(self: Any, progress: MeasurementProgress | MatrixRuntimeProgress) -> None:
    dialog = getattr(self, "_measurement_progress_dialog", None)
    if isinstance(progress, MatrixRuntimeProgress):
        if dialog is not None:
            dialog.update_progress(progress)
        self.status_message.setText(
            f"{progress.phase}: {progress.current}/{progress.total}"
        )
        return
    suffix = f" — {progress.message}" if progress.message else ""
    self.status_message.setText(f"{progress.phase}: {progress.current}/{progress.total}{suffix}")


def _on_measurement_finished(self: Any, result: object) -> None:
    self.smu_manager.control.safe_shutdown(SMUOwnership.RECIPE)
    _best_effort_routing_off(self, "measurement_finished")
    if self.emergency_manager.is_active:
        self.status_message.setText("ABORTED / EMERGENCY STOP")
    else:
        self.status_message.setText("Measurement completed")
    dialog = getattr(self, "_measurement_progress_dialog", None)
    if dialog is not None:
        total = int(result.get("captures", 0)) if isinstance(result, dict) else 0
        dialog.set_complete(total)


def _on_measurement_cancelled(self: Any) -> None:
    self.smu_manager.control.safe_shutdown(SMUOwnership.RECIPE)
    _best_effort_routing_off(self, "measurement_cancelled")
    self.relay_service.safe_white_light_off("measurement_cancelled")
    self.status_message.setText(
        "ABORTED / EMERGENCY STOP"
        if self.emergency_manager.is_active
        else "Measurement stopped safely"
    )
    dialog = getattr(self, "_measurement_progress_dialog", None)
    if dialog is not None:
        dialog.set_stopped()


def _on_measurement_failed(self: Any, message: str) -> None:
    self.smu_manager.control.safe_shutdown(SMUOwnership.RECIPE)
    _best_effort_routing_off(self, "critical_exception_cleanup")
    self.relay_service.safe_white_light_off("critical_exception_cleanup")
    self.show_error(f"Measurement failed: {message}")
    dialog = getattr(self, "_measurement_progress_dialog", None)
    if dialog is not None:
        dialog.set_failed(message)


def _validate_camera_matrix(self: Any) -> list[str]:
    recipe = self.selected_recipe
    if recipe is None:
        return ["尚未選擇 Recipe"]
    errors = recipe.validate()
    exposure_range = self.camera_info.get("exposure_range_us")
    gain_range = self.camera_info.get("gain_range")
    if exposure_range:
        low, high = float(exposure_range[0]), float(exposure_range[1])
        if any(not low <= value * 1000.0 <= high for value in recipe.el_matrix.exposures_ms):
            errors.append(f"Exposure 超出相機支援範圍 {low / 1000:g}～{high / 1000:g} ms")
    else:
        errors.append("相機未提供 Exposure capability，禁止開始 Matrix")
    if gain_range:
        low, high = int(gain_range[0]), int(gain_range[1])
        if any(not low <= value <= high for value in recipe.el_matrix.gains_percent):
            errors.append(f"Gain 超出相機支援範圍 {low}～{high}%")
    else:
        errors.append("相機未提供 Gain capability，禁止開始 Matrix")
    if recipe.hdr.enabled:
        errors.append("EL Matrix 第一版不執行 HDR；請先在 Recipe 關閉 HDR")
    return errors


def _measurement_summary(self: Any, plan: ELMatrixPlan) -> str:
    recipe = plan.recipe
    estimate = plan.estimate()
    return (
        "量測摘要\n\n"
        f"Channels：{' / '.join(channel.channel for channel in plan.channels)}\n"
        f"Channel 數量：{len(plan.channels)}\n\n"
        f"Current Density：{', '.join(f'{value:g}' for value in recipe.el_matrix.current_density_ma_cm2)} mA/cm²\n"
        f"Gain：{', '.join(str(value) for value in recipe.el_matrix.gains_percent)} %\n"
        f"Exposure：{', '.join(f'{value:g}' for value in recipe.el_matrix.exposures_ms)} ms\n"
        f"每條件：{recipe.el_matrix.repeat} 張\n\n"
        f"Shared Dark：{estimate.shared_dark_captures} 張\n"
        f"EL / Channel：{estimate.el_per_channel} 張\n"
        f"EL Total：{estimate.total_el_captures} 張\n"
        f"Total：{estimate.overall_captures} 張\n\n"
        f"預估純曝光時間：{format_duration(estimate.exposure_time_s)}\n"
        f"預估總量測時間：{format_duration(estimate.total_time_s)}\n"
        f"預計完成：{format_finish_time(estimate.estimated_finish)}"
    )


def begin_el_matrix_measurement(self: Any) -> None:
    errors = _validate_camera_matrix(self)
    if errors:
        QMessageBox.warning(self, "EL Matrix 無法開始", "• " + "\n• ".join(errors))
        return
    recipe = self.selected_recipe
    if recipe is None:
        return
    output_root = self.measurement_path_edit.text().strip() or recipe.output.root_directory
    if not output_root:
        QMessageBox.warning(self, "尚未設定輸出位置", "請先選擇量測資料儲存位置。")
        return
    if not recipe.polarity.enabled:
        answer = QMessageBox.warning(
            self,
            "略過白光極性確認",
            "本次量測將跳過白光 Voc/Jsc 極性確認。\n"
            "請確認所有啟用 Channel 的元件接線方向正確。",
            QMessageBox.StandardButton.Ok | QMessageBox.StandardButton.Cancel,
            QMessageBox.StandardButton.Cancel,
        )
        if answer != QMessageBox.StandardButton.Ok:
            return
    plan = ELMatrixPlan(recipe)
    answer = QMessageBox.question(
        self,
        "確認 EL Matrix 量測",
        _measurement_summary(self, plan),
        QMessageBox.StandardButton.Ok | QMessageBox.StandardButton.Cancel,
        QMessageBox.StandardButton.Cancel,
    )
    if answer != QMessageBox.StandardButton.Ok:
        return
    bridge = getattr(self, "_camera_capture_bridge", None)
    if bridge is None:
        bridge = CameraCaptureBridge(self.controller, self)
        self._camera_capture_bridge = bridge
    hardware = ELMatrixHardwareAdapter(
        self.smu_manager.control,
        self.relay_service,
        bridge,
        self.polarity_settings_store.settings,
    )
    dialog = MeasurementProgressDialog(recipe.name, self)
    dialog.stop_requested.connect(self.stop_background_measurement)
    self._measurement_progress_dialog = dialog
    dialog.show()

    def run(progress: Any, cancelled: Any) -> object:
        runner = ELMatrixRunner(
            recipe,
            hardware,
            output_root,
            report_progress=progress,
            is_cancel_requested=cancelled,
        )
        return runner.run()

    if not start_background_measurement(self, run):
        dialog.set_stopped()
        dialog.close()


def _clear_measurement_worker(self: Any) -> None:
    # This is the final safety net for normal return, cancellation and exceptions.
    self.smu_manager.control.safe_shutdown(SMUOwnership.RECIPE)
    self._measurement_worker = None
    self._measurement_thread = None
    self.stop_measurement_button.setEnabled(False)
    self._update_measurement_controls()


def attach_measurement_handlers(cls: type[Any]) -> None:
    for function in (
        start_background_measurement,
        _best_effort_routing_off,
        stop_background_measurement,
        emergency_stop_measurement,
        _cancel_measurement_for_emergency,
        _stop_camera_for_emergency,
        _on_measurement_progress,
        _on_measurement_finished,
        _on_measurement_cancelled,
        _on_measurement_failed,
        _clear_measurement_worker,
        _validate_camera_matrix,
        _measurement_summary,
        begin_el_matrix_measurement,
    ):
        setattr(cls, function.__name__, function)
