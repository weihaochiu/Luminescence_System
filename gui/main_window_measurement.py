from __future__ import annotations

"""Background Recipe lifecycle wiring with centralized SMU cleanup."""

import json
from pathlib import Path
from typing import Any

from PySide6.QtCore import QThread
from PySide6.QtWidgets import QMessageBox

from core.i18n import tr

from .camera_capture_bridge import CameraCaptureBridge
from .error_reporting import report_error
from .camera_exposure import ExposureMode
from .el_matrix_hardware import ELMatrixHardwareAdapter
from .el_matrix_plan import ELMatrixPlan, format_duration, format_finish_time
from .el_matrix_preflight import collect_preflight_errors
from .el_matrix_runner import ELMatrixRunner, MatrixRuntimeProgress
from .measurement_snapshot import build_el_matrix_snapshot, snapshot_payload
from .measurement_progress_dialog import MeasurementProgressDialog
from .measurement_execution_plan import (
    build_measurement_execution_plan,
    effective_matrix_capture_axes,
)
from .measurement_worker import MeasurementProgress, MeasurementWorker
from .pixel_csv_postprocessor import (
    PixelCSVPostprocessError,
    PixelCSVPostprocessor,
    PixelCSVProgress,
    verified_safe_shutdown,
)
from .polarity_settings import PolarityMeasurementSettings
from .recipe_store import Recipe
from .numeric import format_voltage_number
from .smu_control import SMUInterlockError, SMUOwnership


def _best_effort_routing_off(self: Any, source: str) -> bool:
    try:
        return bool(self.relay_service.safe_smu_output_channels_off(source))
    except Exception as exc:
        self.status_message.setText(tr("relay.safe_off_failed", reason=exc))
        return False


def _effective_capture_counts(self: Any, recipe: Recipe) -> dict[str, int]:
    try:
        return ELMatrixPlan(
            recipe,
            global_safety=self.smu_manager.control.safety.limits,
        ).capture_counts()
    except ValueError:
        return recipe.matrix_capture_counts()


def start_background_measurement(
    self: Any, run: Any, *, acquire_recipe_ownership: bool = True
) -> bool:
    if self._measurement_thread is not None:
        raise RuntimeError("Measurement is already running")
    control = self.smu_manager.control
    if acquire_recipe_ownership and control.ownership is SMUOwnership.MANUAL:
        detail = tr("measurement.manual_output_shutdown_detail") if control.output_enabled else ""
        answer = QMessageBox.question(
            self,
            tr("measurement.manual_smu_active"),
            tr("measurement.manual_smu_active_question", detail=detail),
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.Cancel,
            QMessageBox.StandardButton.Cancel,
        )
        if answer != QMessageBox.StandardButton.Yes:
            return False
    if acquire_recipe_ownership:
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
    self._measurement_hardware_active = acquire_recipe_ownership
    if acquire_recipe_ownership:
        _set_measurement_controls_locked(self, True)
    self.stop_measurement_button.setEnabled(acquire_recipe_ownership)
    self.start_measurement_button.setEnabled(False)
    thread.start()
    return True


def _set_measurement_controls_locked(self: Any, locked: bool) -> None:
    names = (
        "white_light_button", "relay_settings_action", "recipe_manager_action",
        "polarity_settings_action", "resolution_combo",
        "exposure_mode_combo", "exposure_spin", "gain_spin", "apply_manual_button",
        "capture_button", "auto_capture_button", "capture_action", "auto_capture_action",
        "connect_action", "manual_smu_panel", "device_panel", "measurement_path_button",
        "measurement_path_edit",
    )
    if locked:
        states: list[tuple[Any, bool]] = []
        for name in names:
            control = getattr(self, name, None)
            if control is not None and hasattr(control, "setEnabled"):
                states.append((control, bool(control.isEnabled())))
                control.setEnabled(False)
        for control in getattr(
            getattr(self, "measurement_control_bar", None),
            "sample_id_edits",
            {},
        ).values():
            states.append((control, bool(control.isEnabled())))
            control.setEnabled(False)
        self._measurement_locked_controls = states
        self._cancel_auto_capture()
        if self.controller.is_open:
            self.controller.switch_to_manual_exposure()
        return
    if self.emergency_manager.is_active or self.smu_manager.control.ownership in (
        SMUOwnership.FAULT, SMUOwnership.EMERGENCY,
    ):
        return
    for control, enabled in getattr(self, "_measurement_locked_controls", []):
        control.setEnabled(enabled)
    self._measurement_locked_controls = []


def stop_background_measurement(self: Any) -> None:
    if not getattr(self, "_measurement_hardware_active", False):
        return
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


def _on_measurement_progress(
    self: Any, progress: MeasurementProgress | MatrixRuntimeProgress | PixelCSVProgress
) -> None:
    dialog = getattr(self, "_measurement_progress_dialog", None)
    if isinstance(progress, PixelCSVProgress):
        self._measurement_hardware_active = False
        self.stop_measurement_button.setEnabled(False)
        if dialog is not None:
            dialog.update_postprocess_progress(progress)
        self.status_message.setText(tr("progress.pixel_csv_status", current=progress.current, total=progress.total, percent=f"{progress.percent:.1f}"))
        return
    if isinstance(progress, MatrixRuntimeProgress):
        if dialog is not None:
            dialog.update_progress(progress)
        self.status_message.setText(tr("progress.runtime", phase=progress.phase, current=progress.current, total=progress.total))
        return
    suffix = f" — {progress.message}" if progress.message else ""
    self.status_message.setText(tr("progress.runtime_details", phase=progress.phase, current=progress.current, total=progress.total, details=suffix))


def _on_measurement_finished(self: Any, result: object) -> None:
    shutdown = result.get("safe_shutdown") if isinstance(result, dict) else None
    hardware_completed = bool(
        isinstance(result, dict) and result.get("hardware_measurement_completed") is True
    )
    if not hardware_completed or not verified_safe_shutdown(shutdown):
        message = "Safe shutdown verification failed; measurement remains FAULT"
        self.status_message.setText(message)
        dialog = getattr(self, "_measurement_progress_dialog", None)
        if dialog is not None:
            dialog.set_failed(message)
        report_error(
            self,
            "SMU-203",
            context={
                "operation": "measurement_completion_safe_shutdown",
                "expected": "verified SMU OUTPUT OFF and all routing OFF",
                "actual": shutdown,
            },
        )
        return
    self._measurement_hardware_active = False
    self._last_measurement_result = dict(result)
    if self.emergency_manager.is_active:
        self.status_message.setText(tr("measurement.aborted_emergency"))
    else:
        postprocess = result.get("postprocess", {})
        post_status = str(postprocess.get("status", "not_requested"))
        if post_status in {"failed", "partial"}:
            reason = str(postprocess.get("error", "Pixel CSV 後處理失敗"))
            self.status_message.setText(tr("progress.postprocess_failed"))
            self._pixel_csv_retry_context = {
                "output_directory": result.get("output_directory"),
                "safe_shutdown": dict(shutdown),
                "base_result": dict(result),
            }
            dialog = getattr(self, "_measurement_progress_dialog", None)
            if dialog is not None:
                dialog.set_postprocess_failed(reason)
                dialog.show()
            return
        self._pixel_csv_retry_context = None
        self.status_message.setText(tr("measurement.completed"))
    dialog = getattr(self, "_measurement_progress_dialog", None)
    if dialog is not None:
        total = int(result.get("captures", 0)) if isinstance(result, dict) else 0
        postprocess = result.get("postprocess", {}) if isinstance(result, dict) else {}
        post_total = int(postprocess.get("total_files", 0))
        dialog.set_complete(
            post_total or total,
            tr("measurement.completed_with_pixel_csv")
            if postprocess.get("status") == "completed" else "硬體量測完成",
        )


def _on_measurement_cancelled(self: Any) -> None:
    if self.smu_manager.control.ownership is SMUOwnership.RECIPE:
        if self.smu_manager.control.safe_shutdown(SMUOwnership.RECIPE):
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
    if self.smu_manager.control.ownership is SMUOwnership.RECIPE:
        if self.smu_manager.control.safe_shutdown(SMUOwnership.RECIPE):
            _best_effort_routing_off(self, "critical_exception_cleanup")
            self.relay_service.safe_white_light_off("critical_exception_cleanup")
    report_error(
        self,
        "MEAS-201",
        context={
            "operation": "el_matrix_measurement",
            "recipe": getattr(self.selected_recipe, "name", None),
            "actual": message,
        },
    )
    dialog = getattr(self, "_measurement_progress_dialog", None)
    if dialog is not None:
        dialog.set_failed(message)


def _validate_camera_matrix(self: Any) -> list[str]:
    recipe = self.selected_recipe
    if recipe is None:
        return ["尚未選擇 Recipe"]
    errors = recipe.validate(self.smu_manager.control.safety.limits)
    exposure_range = self.camera_info.get("exposure_range_us")
    gain_range = self.camera_info.get("gain_range")
    axes = effective_matrix_capture_axes(recipe)
    if not axes.exposures_ms or not axes.gains_percent or axes.repeat < 1:
        errors.append("有效的相機拍攝條件不可為空")
    elif max(axes.exposures_ms) / 1000.0 > recipe.el_matrix.capture_timeout_s:
        errors.append("相機 timeout 不可短於有效曝光序列的最大曝光時間")
    if exposure_range:
        low, high = float(exposure_range[0]), float(exposure_range[1])
        if any(not low <= value * 1000.0 <= high for value in axes.exposures_ms):
            errors.append(f"Exposure 超出相機支援範圍 {low / 1000:g}～{high / 1000:g} ms")
    else:
        errors.append("相機未提供 Exposure capability，禁止開始 Matrix")
    if gain_range:
        low, high = int(gain_range[0]), int(gain_range[1])
        if any(not low <= value <= high for value in axes.gains_percent):
            errors.append(f"Gain 超出相機支援範圍 {low}～{high}%")
    else:
        errors.append("相機未提供 Gain capability，禁止開始 Matrix")
    return errors


def _measurement_summary(self: Any, plan: ELMatrixPlan) -> str:
    recipe = plan.recipe
    estimate = plan.estimate()
    execution = build_measurement_execution_plan(
        recipe, self.smu_manager.control.safety.limits
    )
    order = " → ".join(step.title for step in execution.steps)
    samples = " / ".join(
        f"{channel.channel}={plan.sample_ids.get(channel.channel, '')}"
        for channel in plan.channels
    )
    if recipe.el_matrix.output_mode == "voltage":
        electrical = (
            "Voltage："
            + ", ".join(
                format_voltage_number(value) for value in recipe.el_matrix.voltage_v
            )
            + " V"
        )
    else:
        electrical = (
            "Current Density："
            + ", ".join(
                f"{value:g}" for value in recipe.el_matrix.current_density_ma_cm2
            )
            + " mA/cm²"
        )
    return (
        "量測摘要\n\n"
        f"正式順序：{order}\n\n"
        f"Channels：{' / '.join(channel.channel for channel in plan.channels)}\n"
        f"Channel 數量：{len(plan.channels)}\n\n"
        f"樣品：{samples}\n\n"
        f"{electrical}\n"
        f"Gain：{', '.join(str(value) for value in plan.gains_percent)} %\n"
        f"Exposure：{', '.join(f'{value:g}' for value in plan.exposures_ms)} ms\n"
        f"每條件：{plan.repeat} 張\n\n"
        f"Shared Dark：{estimate.shared_dark_captures} 張\n"
        f"EL / Channel：{estimate.el_per_channel} 張\n"
        f"EL Total：{estimate.total_el_captures} 張\n"
        f"Total：{estimate.overall_captures} 張\n\n"
        f"預估純曝光時間：{format_duration(estimate.exposure_time_s)}\n"
        f"預估總量測時間：{format_duration(estimate.total_time_s)}\n"
        f"最長單一 Electrical Setpoint OUTPUT ON："
        f"{format_duration(estimate.output_on_per_setpoint_s)}\n"
        f"預計完成：{format_finish_time(estimate.estimated_finish)}"
    )


def begin_el_matrix_measurement(self: Any) -> None:
    if self.selected_recipe is not None:
        missing = self.measurement_control_bar.missing_sample_channels()
        if missing:
            channel = missing[0]
            report_error(
                self,
                "MEAS-101",
                context={"operation": "preflight", "channel": channel, "actual": "missing sample ID"},
            )
            return
    errors = _validate_camera_matrix(self)
    if errors:
        report_error(
            self,
            "MEAS-101",
            context={"operation": "camera_matrix_validation", "actual": errors},
        )
        return
    recipe = self.selected_recipe
    if recipe is None:
        return
    output_root = self.measurement_path_edit.text().strip()
    if not output_root:
        report_error(
            self,
            "MEAS-101",
            context={"operation": "output_preflight", "actual": "output path not selected"},
        )
        return
    resolution_id = recipe.output.resolution_id
    if resolution_id.startswith("sdk:"):
        self.controller.set_resolution(int(resolution_id.split(":", 1)[1]))
    elif resolution_id == "full":
        self.controller.set_resolution(0)
    sample_ids = self.measurement_control_bar.sample_ids()
    plan = ELMatrixPlan(
        recipe,
        sample_ids=sample_ids,
        global_safety=self.smu_manager.control.safety.limits,
    )
    answer = QMessageBox.question(
        self,
        tr("measurement.confirm_matrix"),
        _measurement_summary(self, plan),
        QMessageBox.StandardButton.Ok | QMessageBox.StandardButton.Cancel,
        QMessageBox.StandardButton.Cancel,
    )
    if answer != QMessageBox.StandardButton.Ok:
        return
    # Formal Recipe capture owns Exposure/Gain. Disable native SDK AE and
    # require an authoritative OFF readback before any camera configuration.
    if not self.controller.disable_auto_exposure_for_formal_measurement():
        report_error(
            self,
            "CAM-202",
            context={
                "operation": "disable_auto_exposure_for_measurement",
                "expected": "SDK auto exposure OFF",
                "actual": "unconfirmed",
            },
        )
        return
    self._active_exposure_mode = ExposureMode.MANUAL
    self._set_exposure_mode_ui(ExposureMode.MANUAL)
    camera_snapshot = dict(self.controller.capture_metadata())
    exposure_us, gain = self.controller.current_exposure()
    camera_snapshot.update({
        "ExposureCapabilityUs": self.camera_info.get("exposure_range_us"),
        "GainCapability": self.camera_info.get("gain_range"),
        "ExposureReadbackUs": exposure_us,
        "GainReadback": gain,
    })
    selected = self.device_panel.selected_smu()
    smu_metadata = self.smu_manager.connection_metadata(
        selected.visa_address if selected is not None else ""
    )
    relay_mapping = self.relay_service.smu_output_mapping()
    snapshot_recipe = Recipe.from_dict(recipe.to_dict())
    execution_plan = build_measurement_execution_plan(
        snapshot_recipe,
        self.smu_manager.control.safety.limits,
    )
    snapshot = build_el_matrix_snapshot(
        snapshot_recipe,
        execution_order=execution_plan.to_dict()["steps"],
        camera=camera_snapshot,
        smu=smu_metadata,
        relay_mapping=relay_mapping,
        polarity_settings=self.polarity_settings_store.settings,
        sample_ids=sample_ids,
        global_safety=self.smu_manager.control.safety.limits,
        output_directory=output_root,
    )
    frozen_recipe = Recipe.from_dict(
        snapshot_payload(snapshot)["recipe"]["complete_snapshot"]
    )
    current_camera = dict(self.controller.capture_metadata())
    current_camera.update({
        "exposure_range_us": self.camera_info.get("exposure_range_us"),
        "gain_range": self.camera_info.get("gain_range"),
    })
    preflight = collect_preflight_errors(
        frozen_recipe,
        smu_metadata=smu_metadata,
        smu_output_confirmed_off=self.smu_manager.control.confirm_output_off_for_routing(),
        relay_connected=self.relay_controller.connected,
        relay_settings=self.relay_settings_store.settings,
        camera_connected=self.controller.is_open,
        camera_snapshot=camera_snapshot,
        current_camera=current_camera,
        output_root=output_root,
        global_safety=self.smu_manager.control.safety.limits,
    )
    if preflight:
        report_error(
            self,
            "MEAS-101",
            context={"operation": "el_matrix_preflight", "actual": preflight},
        )
        return
    bridge = getattr(self, "_camera_capture_bridge", None)
    if bridge is None:
        bridge = CameraCaptureBridge(self.controller, self)
        self._camera_capture_bridge = bridge
    polarity_snapshot = snapshot_payload(snapshot)["polarity"]["system_settings"]["settings"]
    hardware = ELMatrixHardwareAdapter(
        self.smu_manager.control,
        self.relay_service,
        bridge,
        PolarityMeasurementSettings.from_dict(polarity_snapshot),
    )
    dialog = MeasurementProgressDialog(recipe.name, self)
    dialog.stop_requested.connect(self.stop_background_measurement)
    dialog.retry_pixel_csv_requested.connect(self.retry_pixel_csv_postprocess)
    self._measurement_progress_dialog = dialog
    dialog.show()
    def run(progress: Any, cancelled: Any) -> object:
        runner = ELMatrixRunner(
            recipe,
            hardware,
            output_root,
            report_progress=progress,
            is_cancel_requested=cancelled,
            measurement_snapshot=snapshot,
            sample_ids=sample_ids,
            global_safety=self.smu_manager.control.safety.limits,
            max_recipe_time_s=self.max_recipe_time_s,
            max_output_time_s=self.max_output_time_s,
        )
        result = runner.run()
        if not verified_safe_shutdown(result.get("safe_shutdown")):
            raise RuntimeError("Pixel CSV blocked: safe shutdown was not fully verified")
        if frozen_recipe.output.export_pixel_csv:
            progress(PixelCSVProgress(
                current=0,
                total=0,
                percent=0.0,
                remaining_time_s=0.0,
                estimated_finish=None,
                message="硬體量測完成，SMU 已安全關閉，正在產生 Pixel CSV",
            ))
            try:
                result["postprocess"] = PixelCSVPostprocessor(
                    result["output_directory"], result["safe_shutdown"]
                ).run(progress)
            except PixelCSVPostprocessError as exc:
                status_path = Path(result["output_directory"]) / "postprocess_status.json"
                status = {"status": "failed", "error": str(exc)}
                if status_path.is_file():
                    try:
                        status = json.loads(status_path.read_text(encoding="utf-8"))
                    except (OSError, ValueError):
                        pass
                status["error"] = str(exc)
                result["postprocess"] = status
        else:
            result["postprocess"] = {"status": "not_requested", "total_files": 0}
        return result

    if not start_background_measurement(self, run):
        dialog.set_stopped()
        dialog.close()


def retry_pixel_csv_postprocess(self: Any) -> None:
    context = getattr(self, "_pixel_csv_retry_context", None)
    if not context or self._measurement_thread is not None:
        return
    output_directory = context.get("output_directory")
    shutdown = context.get("safe_shutdown")
    if not output_directory or not verified_safe_shutdown(shutdown):
        self.status_message.setText(tr("progress.pixel_csv_retry_requires_safe_shutdown"))
        return
    dialog = getattr(self, "_measurement_progress_dialog", None)
    if dialog is not None:
        dialog.set_hardware_complete_starting_postprocess()
        dialog.show()

    def run(progress: Any, _cancelled: Any) -> object:
        result = dict(context.get("base_result", {}))
        try:
            result["postprocess"] = PixelCSVPostprocessor(
                output_directory, shutdown
            ).run(progress)
        except PixelCSVPostprocessError as exc:
            status_path = Path(output_directory) / "postprocess_status.json"
            status = {"status": "failed", "error": str(exc)}
            if status_path.is_file():
                try:
                    status = json.loads(status_path.read_text(encoding="utf-8"))
                except (OSError, ValueError):
                    pass
            status["error"] = str(exc)
            result["postprocess"] = status
        result["hardware_measurement_completed"] = True
        result["safe_shutdown"] = dict(shutdown)
        result["output_directory"] = str(output_directory)
        return result

    start_background_measurement(self, run, acquire_recipe_ownership=False)


def _clear_measurement_worker(self: Any) -> None:
    self._measurement_worker = None
    self._measurement_thread = None
    self._measurement_hardware_active = False
    self.stop_measurement_button.setEnabled(False)
    _set_measurement_controls_locked(self, False)
    self._update_measurement_controls()


def attach_measurement_handlers(cls: type[Any]) -> None:
    for function in (
        start_background_measurement,
        _set_measurement_controls_locked,
        _best_effort_routing_off,
        _effective_capture_counts,
        stop_background_measurement,
        emergency_stop_measurement,
        _cancel_measurement_for_emergency,
        _stop_camera_for_emergency,
        _on_measurement_progress,
        _on_measurement_finished,
        _on_measurement_cancelled,
        _on_measurement_failed,
        retry_pixel_csv_postprocess,
        _clear_measurement_worker,
        _validate_camera_matrix,
        _measurement_summary,
        begin_el_matrix_measurement,
    ):
        setattr(cls, function.__name__, function)
