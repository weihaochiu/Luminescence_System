from __future__ import annotations

"""Cancelable background execution primitives for measurement workflows."""

from dataclasses import dataclass
from threading import Event
from typing import Callable

from PySide6.QtCore import QObject, Signal, Slot


class MeasurementCancelled(Exception):
    """The measurement was stopped by the operator."""


@dataclass(frozen=True)
class MeasurementProgress:
    phase: str
    current: int
    total: int
    message: str = ""


class MeasurementWorker(QObject):
    """Execute an acquisition callable outside the GUI thread.

    The callable owns blocking hardware I/O and receives callbacks for progress
    reporting and cooperative cancellation. Widgets must only consume signals.
    """

    started = Signal()
    progress_changed = Signal(object)
    finished = Signal(object)
    cancelled = Signal()
    failed = Signal(str)

    def __init__(self, run: Callable[[Callable[..., None], Callable[[], bool]], object]) -> None:
        super().__init__()
        self._run = run
        self._cancel_requested = Event()

    @Slot()
    def execute(self) -> None:
        self.started.emit()
        try:
            result = self._run(self.report_progress, self.is_cancel_requested)
            if self.is_cancel_requested():
                self.cancelled.emit()
            else:
                self.finished.emit(result)
        except MeasurementCancelled:
            self.cancelled.emit()
        except Exception as exc:
            self.failed.emit(str(exc))

    @Slot()
    def request_cancel(self) -> None:
        self._cancel_requested.set()

    def is_cancel_requested(self) -> bool:
        return self._cancel_requested.is_set()

    def check_cancelled(self) -> None:
        if self.is_cancel_requested():
            raise MeasurementCancelled()

    def report_progress(
        self,
        phase: str | object,
        current: int | None = None,
        total: int | None = None,
        message: str = "",
    ) -> None:
        if current is None and total is None and not isinstance(phase, str):
            self.progress_changed.emit(phase)
            return
        if current is None or total is None:
            raise TypeError("current and total are required for text progress")
        self.progress_changed.emit(MeasurementProgress(str(phase), current, total, message))
