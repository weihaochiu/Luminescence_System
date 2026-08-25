from __future__ import annotations

"""Main-window presentation boundary for centralized errors and diagnostics."""

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Any

from core.error_reporter import ErrorEvent

from .dialogs import ErrorDialog
from .error_center import ErrorCenterDialog
from .smu_base import SMUFaultIdentity

if TYPE_CHECKING:
    from .main_window import MainWindow


@dataclass(frozen=True)
class PendingSMUSafetyReconnect:
    target: SMUFaultIdentity
    requested_resource: str
    requested_serial: str
    error_code: str
    requested_at: str

    @classmethod
    def create(cls, target: SMUFaultIdentity, error_code: str) -> "PendingSMUSafetyReconnect":
        return cls(
            target=target,
            requested_resource=target.visa_address,
            requested_serial=target.serial_number,
            error_code=error_code,
            requested_at=datetime.now(timezone.utc).astimezone().isoformat(
                timespec="milliseconds"
            ),
        )


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
    message_key: str | None = None,
    message_args: dict[str, object] | None = None,
) -> ErrorEvent:
    return self.error_reporter.report(
        code,
        context=context,
        exception=exception,
        present=present,
        message_key=message_key,
        message_args=message_args,
    )


def _present_error(self: MainWindow, event: ErrorEvent) -> None:
    dialog = ErrorDialog(
        event,
        self,
        action_handlers=self._error_action_handlers(event),
        error_center_opener=self.open_error_center,
    )
    self._error_dialogs.add(dialog)
    dialog.finished.connect(
        lambda _result, current=dialog: self._error_dialogs.discard(current)
    )
    dialog.open()


def _error_action_handlers(self: MainWindow, event: ErrorEvent) -> dict[str, Any]:
    """Return only actions that have executable, state-safe semantics now."""

    handlers: dict[str, Any] = {}
    for action in event.definition.actions:
        if action == "safe_shutdown":
            handlers[action] = self._error_dialog_safe_shutdown
        elif action == "reconnect" and self._error_reconnect_available(event):
            handlers[action] = self._error_dialog_reconnect
        # No generic retry exists. A future retry must be registered here only
        # for a specific code/operation with reconstructable canonical state.
    return handlers


def _error_dialog_safe_shutdown(self: MainWindow, _event: ErrorEvent) -> bool:
    self.emergency_manager.trigger("error dialog safe shutdown")
    return True


def _error_reconnect_available(self: MainWindow, event: ErrorEvent) -> bool:
    if getattr(self, "_measurement_worker", None) is not None:
        return False
    subsystem = event.definition.subsystem
    if subsystem in {"camera", "relay"}:
        return True
    if subsystem != "smu" or self.smu_manager.is_busy:
        return False
    control = self.smu_manager.control
    if control.fault_identity is not None:
        connected = self.smu_manager.connected_device
        return bool(
            connected is None or control.fault_identity.matches_device(connected)
        )
    device = _smu_reconnect_target(self, event)
    if device is None:
        return False
    return bool(
        not self.smu_manager.is_connected
        or control.output_confirmed_off
    )


def _smu_reconnect_target(self: MainWindow, event: ErrorEvent):
    fault_identity = self.smu_manager.control.fault_identity
    requested_resource = str(event.context.resource or "")
    connected = self.smu_manager.connected_device
    selected = self.device_panel.selected_smu()
    candidates = [device for device in (connected, selected) if device is not None]
    candidates.extend(
        device for device in self.smu_manager.devices if device not in candidates
    )
    if fault_identity is not None:
        matches = [
            device for device in candidates if fault_identity.matches_device(device)
        ]
        return matches[0] if len(matches) == 1 else None
    if requested_resource:
        for device in candidates:
            if device.visa_address == requested_resource:
                return device
        return None
    if connected is not None:
        return connected
    if selected is not None:
        return selected
    return candidates[0] if len(candidates) == 1 else None


def _error_dialog_reconnect(self: MainWindow, event: ErrorEvent) -> bool:
    subsystem = event.definition.subsystem
    if subsystem == "camera":
        self.refresh_devices()
        return True
    if subsystem == "relay":
        self.refresh_relay_connection()
        return True
    if subsystem != "smu":
        return False
    control = self.smu_manager.control
    fault_identity = control.fault_identity
    if fault_identity is not None:
        pending = PendingSMUSafetyReconnect.create(fault_identity, event.code)
        self._pending_smu_safety_reconnect = pending
        device = _smu_reconnect_target(self, event)
        if device is None:
            self._auto_connect_after_scan = False
            self.refresh_smu_devices()
            return True
        accepted = self.smu_manager.reconnect_device_for_safety(device)
        if not accepted:
            self._pending_smu_safety_reconnect = None
        return accepted
    device = _smu_reconnect_target(self, event)
    if device is None or not self._error_reconnect_available(event):
        return False
    return self.smu_manager.reconnect_device(device)


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
        _error_action_handlers,
        _error_dialog_safe_shutdown,
        _error_reconnect_available,
        _error_dialog_reconnect,
        _on_emergency_completed,
    ):
        setattr(window_class, function.__name__, function)
