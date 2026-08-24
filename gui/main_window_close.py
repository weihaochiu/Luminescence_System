from __future__ import annotations

"""Fail-closed application shutdown coordination and operator confirmation."""

import logging
from typing import Any

from PySide6.QtGui import QCloseEvent
from PySide6.QtWidgets import QMessageBox


LOG = logging.getLogger(__name__)


def closeEvent(self: Any, event: QCloseEvent) -> None:  # noqa: N802 - Qt API name
    event.ignore()
    if self._close_in_progress:
        return
    self._close_in_progress = True
    try:
        self.manual_smu_panel.flush_persistent_settings()
    except Exception:
        LOG.exception("Manual SMU settings flush failed during application close")
    self.setEnabled(False)
    self._cancel_measurement_for_emergency()
    self.smu_monitor.stop()

    while not self.smu_manager.confirm_safe_for_close():
        decision = self._unsafe_smu_close_decision()
        if decision == "retry":
            continue
        if decision == "force" and self._confirm_forced_close():
            LOG.critical("FORCED_APPLICATION_EXIT_WITH_UNCONFIRMED_SMU_OUTPUT")
            try:
                self.emergency_manager.trigger("forced application exit")
            except Exception:
                LOG.exception("Forced-exit emergency cleanup failed")
            self.smu_manager.shutdown(force=True)
            self.controller.close_camera()
            event.accept()
            return
        self._cancel_close_after_safety_failure(event)
        return

    self.relay_service.shutdown()
    self.smu_manager.shutdown(safety_confirmed=True)
    self.controller.close_camera()
    event.accept()


def _unsafe_smu_close_decision(self: Any) -> str:
    box = QMessageBox(self)
    box.setIcon(QMessageBox.Icon.Critical)
    box.setWindowTitle("無法確認 SMU 已停止輸出")
    box.setText(
        "程式無法確認 SMU OUTPUT OFF。\n"
        "SMU 可能仍處於帶電狀態。\n"
        "請立即確認 SMU 前面板 OUTPUT 狀態。"
    )
    retry = box.addButton("再次嘗試安全停止", QMessageBox.ButtonRole.ActionRole)
    cancel = box.addButton("取消關閉", QMessageBox.ButtonRole.RejectRole)
    force = box.addButton("強制結束", QMessageBox.ButtonRole.DestructiveRole)
    box.setDefaultButton(cancel)
    box.exec()
    clicked = box.clickedButton()
    if clicked is retry:
        return "retry"
    if clicked is force:
        return "force"
    return "cancel"


def _confirm_forced_close(self: Any) -> bool:
    answer = QMessageBox.warning(
        self,
        "確認強制結束",
        "目前無法確認 SMU 是否仍在輸出。\n"
        "強制關閉軟體不代表硬體已安全停止。\n\n"
        "是否仍要強制結束？",
        QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.Cancel,
        QMessageBox.StandardButton.Cancel,
    )
    return answer is QMessageBox.StandardButton.Yes


def _cancel_close_after_safety_failure(self: Any, event: QCloseEvent) -> None:
    self._close_in_progress = False
    self.setEnabled(True)
    if self.smu_manager.is_connected:
        self.smu_monitor.start()
    event.ignore()


def attach_close_handlers(cls: type[Any]) -> None:
    for function in (
        closeEvent,
        _unsafe_smu_close_decision,
        _confirm_forced_close,
        _cancel_close_after_safety_failure,
    ):
        setattr(cls, function.__name__, function)
