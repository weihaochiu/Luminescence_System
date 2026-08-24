from __future__ import annotations

"""Presentation-boundary helper that locates the application ErrorReporter."""

from typing import Mapping

from PySide6.QtWidgets import QWidget

from core.error_reporter import ErrorEvent, ErrorReporter
from .dialogs import ErrorDialog


def report_error(
    widget: QWidget,
    code: str,
    *,
    context: Mapping[str, object] | None = None,
    exception: BaseException | None = None,
    present: bool = True,
) -> ErrorEvent:
    current: object | None = widget
    while current is not None:
        reporter = getattr(current, "error_reporter", None)
        if isinstance(reporter, ErrorReporter):
            return reporter.report(code, context=context, exception=exception, present=present)
        parent = getattr(current, "parent", None)
        current = parent() if callable(parent) else None
    reporter = ErrorReporter()
    event = reporter.report(code, context=context, exception=exception, present=False)
    # Production dialogs are parented under MainWindow and always find its
    # reporter/presenter. An isolated widget (notably a unit-test fixture) has
    # no owner able to retain or deep-link a modeless dialog, so logging the
    # event is the safe non-blocking fallback.
    return event
