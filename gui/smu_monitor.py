from __future__ import annotations

"""Non-blocking periodic SMU readback scheduling."""

from PySide6.QtCore import QObject, QTimer

from .smu_control import SMUControlManager


class SMUMonitor(QObject):
    def __init__(
        self, control: SMUControlManager, interval_ms: int = 500, parent: QObject | None = None
    ) -> None:
        super().__init__(parent)
        self.control = control
        self.timer = QTimer(self)
        self.timer.setInterval(interval_ms)
        self.timer.timeout.connect(self.control.request_readback)

    def start(self) -> None:
        self.timer.start()

    def stop(self) -> None:
        self.timer.stop()
