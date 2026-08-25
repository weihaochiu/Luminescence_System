from __future__ import annotations

"""Structured error reporting, logging, and bounded session history."""

from collections import deque
from dataclasses import dataclass
import json
import logging
from typing import Callable, Mapping

from PySide6.QtCore import QObject, Signal

from .error_context import ErrorContext
from .error_registry import ErrorDefinition, ErrorRegistry, Severity, default_error_registry
from .i18n import tr


STRUCTURED_LOGGER = logging.getLogger("luminescence.errors")
DEFAULT_HISTORY_LIMIT = 500
UNKNOWN_ERROR_CODE = "SYS-001"


@dataclass(frozen=True)
class ErrorEvent:
    definition: ErrorDefinition
    context: ErrorContext
    requested_code: str
    message_key: str | None = None
    message_args: Mapping[str, object] | None = None

    @property
    def code(self) -> str:
        return self.definition.code

    @property
    def severity(self) -> Severity:
        return self.definition.severity

    @property
    def title(self) -> str:
        return tr(self.definition.title_key)

    @property
    def message(self) -> str:
        return tr(self.message_key or self.definition.message_key, **dict(self.message_args or {}))

    @property
    def causes(self) -> tuple[str, ...]:
        return tuple(tr(key) for key in self.definition.cause_keys)

    @property
    def solutions(self) -> tuple[str, ...]:
        return tuple(tr(key) for key in self.definition.solution_keys)


class ErrorReporter(QObject):
    reported = Signal(object)
    critical_reported = Signal(object)
    history_changed = Signal()

    def __init__(
        self,
        registry: ErrorRegistry = default_error_registry,
        *,
        history_limit: int = DEFAULT_HISTORY_LIMIT,
        presenter: Callable[[ErrorEvent], None] | None = None,
        parent: QObject | None = None,
    ) -> None:
        super().__init__(parent)
        if history_limit <= 0:
            raise ValueError("history_limit must be positive")
        self.registry = registry
        self._history: deque[ErrorEvent] = deque(maxlen=history_limit)
        self.presenter = presenter

    @property
    def history_limit(self) -> int:
        return int(self._history.maxlen or 0)

    def history(self) -> tuple[ErrorEvent, ...]:
        return tuple(self._history)

    def clear_history(self) -> None:
        self._history.clear()
        self.history_changed.emit()

    def report(
        self,
        code: str,
        *,
        context: Mapping[str, object] | None = None,
        exception: BaseException | None = None,
        present: bool = True,
        message_key: str | None = None,
        message_args: Mapping[str, object] | None = None,
    ) -> ErrorEvent:
        requested = str(code).upper()
        definition = self.registry.get(requested)
        values = dict(context or {})
        if definition is None:
            definition = self.registry.require(UNKNOWN_ERROR_CODE)
            values["requested_error_code"] = requested
        error_context = ErrorContext.build(
            values,
            exception=exception,
            subsystem=definition.subsystem,
        )
        event = ErrorEvent(
            definition,
            error_context,
            requested,
            message_key=message_key,
            message_args=dict(message_args or {}),
        )
        self._history.append(event)
        log_payload = {
            "timestamp": error_context.timestamp,
            "severity": definition.severity.value,
            "error_code": definition.code,
            "subsystem": definition.subsystem,
            "message_key": definition.message_key,
            "presented_message_key": message_key or definition.message_key,
            "context": error_context.as_dict(),
            "exception": error_context.exception_message,
        }
        log_level = {
            Severity.INFO: logging.INFO,
            Severity.WARNING: logging.WARNING,
            Severity.ERROR: logging.ERROR,
            Severity.CRITICAL: logging.CRITICAL,
        }[definition.severity]
        STRUCTURED_LOGGER.log(log_level, "ERROR_EVENT %s", json.dumps(log_payload, ensure_ascii=False, sort_keys=True))
        self.reported.emit(event)
        self.history_changed.emit()
        if definition.severity is Severity.CRITICAL:
            self.critical_reported.emit(event)
        if present and self.presenter is not None:
            self.presenter(event)
        return event


def format_diagnostics(event: ErrorEvent) -> str:
    lines = [
        f"Error Code: {event.code}",
        f"Timestamp: {event.context.timestamp}",
        f"Severity: {event.severity.value.upper()}",
        f"Subsystem: {event.definition.subsystem}",
        f"Message: {event.message}",
    ]
    for key, value in event.context.as_dict().items():
        if key in {"timestamp", "subsystem"}:
            continue
        label = key.replace("_", " ").title()
        lines.append(f"{label}: {value}")
    return "\n".join(lines)
