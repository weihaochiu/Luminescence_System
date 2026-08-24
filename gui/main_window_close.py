from __future__ import annotations

"""Fail-closed application shutdown coordination and operator confirmation."""

import logging
from typing import Any

from PySide6.QtGui import QCloseEvent
from PySide6.QtWidgets import QMessageBox

from core.i18n import tr


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
    reporter = getattr(self, "error_reporter", None)
    if reporter is not None:
        reporter.report(
            "SMU-203",
            context={
                "operation": "application_close",
                "expected": "verified OUTPUT OFF before application exit",
                "actual": getattr(self.smu_manager.control, "fault_reason", "unconfirmed"),
            },
            present=False,
        )
    box = QMessageBox(self)
    box.setIcon(QMessageBox.Icon.Critical)
    box.setWindowTitle(tr("errors.SMU-203.title"))
    box.setText(tr("errors.close_smu_unconfirmed"))
    retry = box.addButton(tr("common.retry_safe_shutdown"), QMessageBox.ButtonRole.ActionRole)
    cancel = box.addButton(tr("common.cancel_close"), QMessageBox.ButtonRole.RejectRole)
    force = box.addButton(tr("common.force_exit"), QMessageBox.ButtonRole.DestructiveRole)
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
        tr("common.confirm_force_exit"),
        tr("errors.force_exit_warning"),
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
