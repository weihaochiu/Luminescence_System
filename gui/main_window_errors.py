from __future__ import annotations

"""Main-window presentation boundary for centralized errors and diagnostics."""

from typing import TYPE_CHECKING, Any

from core.error_reporter import ErrorEvent

from .dialogs import ErrorDialog
from .error_center import ErrorCenterDialog

if TYPE_CHECKING:
    from .main_window import MainWindow


def open_error_center(self: MainWindow, code: str | None = None) -> None:
    if self._error_center_dialog is None:
        self._error_center_dialog = ErrorCenterDialog(self.error_reporter, self)
    if code:
        self._error_center_dialog.open_code(code)
    self._error_center_dialog.show()
    self._error_center_dialog.raise_()
    self._error_center_dialog.activateWindow()


def report_error(
    self: MainWindow,
    code: str,
    *,
    context: dict[str, object] | None = None,
    exception: BaseException | None = None,
    present: bool = True,
) -> ErrorEvent:
    return self.error_reporter.report(
        code, context=context, exception=exception, present=present
    )


def _present_error(self: MainWindow, event: ErrorEvent) -> None:
    dialog = ErrorDialog(
        event,
        self,
        action_handlers={
            "safe_shutdown": self._error_dialog_safe_shutdown,
            "reconnect": self._error_dialog_reconnect,
        },
        error_center_opener=self.open_error_center,
    )
    self._error_dialogs.add(dialog)
    dialog.finished.connect(
        lambda _result, current=dialog: self._error_dialogs.discard(current)
    )
    dialog.open()


def _error_dialog_safe_shutdown(self: MainWindow, _event: ErrorEvent) -> None:
    self.emergency_manager.trigger("error dialog safe shutdown")


def _error_dialog_reconnect(self: MainWindow, event: ErrorEvent) -> None:
    if event.definition.subsystem == "relay":
        self.refresh_relay_connection()
    else:
        self.refresh_devices()


def _on_emergency_completed(self: MainWindow, report: object) -> None:
    failures = tuple(getattr(report, "failures", ()))
    if not failures:
        return
    actions = dict(getattr(report, "actions", {}))
    code = "HW-001" if actions.get("SMU OUTPUT OFF") is True else "SMU-203"
    self.report_error(
        code,
        context={
            "operation": "global_emergency_stop",
            "expected": "SMU OUTPUT OFF; Relay routing OFF; White Light OFF",
            "actual": "; ".join(failures),
            "emergency_actions": actions,
        },
    )


def attach_error_handlers(window_class: type[Any]) -> None:
    for function in (
        open_error_center,
        report_error,
        _present_error,
        _error_dialog_safe_shutdown,
        _error_dialog_reconnect,
        _on_emergency_completed,
    ):
        setattr(window_class, function.__name__, function)
