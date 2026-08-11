from __future__ import annotations

"""Background Recipe lifecycle wiring with centralized SMU cleanup."""

from typing import Any

from PySide6.QtCore import QThread
from PySide6.QtWidgets import QMessageBox

from .measurement_worker import MeasurementProgress, MeasurementWorker
from .smu_control import SMUInterlockError, SMUOwnership


def start_background_measurement(self: Any, run: Any) -> None:
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
            return
    try:
        control.prepare_recipe_start(close_manual=True)
    except SMUInterlockError as exc:
        self.show_smu_error(str(exc))
        return
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
    thread.start()


def stop_background_measurement(self: Any) -> None:
    if self._measurement_worker is not None:
        self._measurement_worker.request_cancel()
    self.smu_manager.control.safe_shutdown(SMUOwnership.RECIPE)
    self.relay_service.safe_white_light_off("stop_measurement")


def emergency_stop_measurement(self: Any) -> None:
    if self._measurement_worker is not None:
        self._measurement_worker.request_cancel()
    self.relay_service.safe_white_light_off("measurement_abort")
    self.smu_manager.control.request_emergency_off()
    self.status_message.setText(
        "Emergency 已鎖定；新輸出已封鎖，OUTPUT OFF 將在目前 VISA I/O 完成後執行。"
    )


def _on_measurement_progress(self: Any, progress: MeasurementProgress) -> None:
    suffix = f" — {progress.message}" if progress.message else ""
    self.status_message.setText(f"{progress.phase}: {progress.current}/{progress.total}{suffix}")


def _on_measurement_finished(self: Any, _result: object) -> None:
    self.smu_manager.control.safe_shutdown(SMUOwnership.RECIPE)
    self.status_message.setText("Measurement completed")


def _on_measurement_cancelled(self: Any) -> None:
    self.smu_manager.control.safe_shutdown(SMUOwnership.RECIPE)
    self.relay_service.safe_white_light_off("measurement_cancelled")
    self.status_message.setText("Measurement stopped safely")


def _on_measurement_failed(self: Any, message: str) -> None:
    self.smu_manager.control.safe_shutdown(SMUOwnership.RECIPE)
    self.relay_service.safe_white_light_off("critical_exception_cleanup")
    self.show_error(f"Measurement failed: {message}")


def _clear_measurement_worker(self: Any) -> None:
    # This is the final safety net for normal return, cancellation and exceptions.
    self.smu_manager.control.safe_shutdown(SMUOwnership.RECIPE)
    self._measurement_worker = None
    self._measurement_thread = None
    self.stop_measurement_button.setEnabled(False)


def attach_measurement_handlers(cls: type[Any]) -> None:
    for function in (
        start_background_measurement,
        stop_background_measurement,
        emergency_stop_measurement,
        _on_measurement_progress,
        _on_measurement_finished,
        _on_measurement_cancelled,
        _on_measurement_failed,
        _clear_measurement_worker,
    ):
        setattr(cls, function.__name__, function)
