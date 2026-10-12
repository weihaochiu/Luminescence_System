"""Application-owned GSP-4H session, serialized requests and verified safety bridge.

The standalone tool and production GUI share the protocol/controller/transport.
Only ControllerWorker may access the serial handle. Presentation never owns it.
"""
from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from threading import Event

from PySide6.QtCore import QObject, QEventLoop, QThread, QTimer, Signal, Slot

from tools.gsp4h_controller.controller import LightState
from tools.gsp4h_controller.discovery import ScanResult
from tools.gsp4h_controller.settings import BrightnessStore
from tools.gsp4h_controller.worker import ControllerWorker, OperationResult, available_ports


@dataclass
class _SafetyRequest:
    operation: str
    done: Event = field(default_factory=Event)
    ok: bool = False
    expired: bool = False


class LightService(QObject):
    changed = Signal()
    failed = Signal(str, str)
    fault = Signal()
    request = Signal(object)
    dispose_worker = Signal()
    safety_request = Signal(object)
    SAFETY_TIMEOUT_MS = 25000

    def __init__(self, path: Path, settings, parent=None, *, worker=None,
                 legacy_path: Path | None = None) -> None:
        super().__init__(parent)
        self.settings = settings
        self.store = BrightnessStore(path)
        self.state = LightState()
        self.levels = (0, 0, 0, 0)
        self.error = ""
        self.notice = ""
        self.scan_result: ScanResult | None = None
        self.logs: deque[str] = deque(maxlen=1500)
        self.busy = ""
        self.locks: set[str] = set()
        self._has_levels = False
        self._dirty = False
        self._pending: dict[int, int] = {}
        self._safety: list[_SafetyRequest] = []
        self._off_pending = ""
        self._cancel = worker.cancel if worker is not None else Event()
        self._worker = worker
        self._thread: QThread | None = None
        self._stopped = False
        self._stopping = False
        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.setInterval(80)
        self._timer.timeout.connect(self._flush)
        self._save_timer = QTimer(self)
        self._save_timer.setSingleShot(True)
        self._save_timer.setInterval(200)
        self._save_timer.timeout.connect(self.save)
        self.safety_request.connect(self._accept_safety)
        try:
            saved = self.store.load()
            if saved is None and legacy_path is not None and legacy_path.exists():
                saved = BrightnessStore(legacy_path).load()
                if saved is not None:
                    self.store.save(saved)
            if saved is not None:
                self.levels, self._has_levels = saved, True
        except (OSError, ValueError) as exc:
            self.error = str(exc)
            self._trace("ERROR", str(exc))

    @property
    def editable(self) -> bool:
        return (self.state.ready and not self.locks and not self._off_pending
                and not self._safety and not self._stopping
                and self.busy in ("", "brightness"))

    @property
    def can_connect(self) -> bool:
        return (not self.state.shutdown_required and not self.busy and not self.locks
                and not self._safety and not self._stopping and not self._stopped)

    @property
    def can_enable(self) -> bool:
        return self.editable and not self.busy

    def channel_name(self, channel: int) -> str:
        """Return a user label; the numeric channel remains the hardware identity."""
        if type(channel) is not int or channel not in range(1, 5):
            raise ValueError("Channel must be an integer from 1 to 4")
        return str(self.settings.value(f"light/channels/{channel}/name", "")).strip()

    def set_channel_name(self, channel: int, name: str) -> None:
        if type(channel) is not int or channel not in range(1, 5):
            raise ValueError("Channel must be an integer from 1 to 4")
        value = name.strip()
        if self.channel_name(channel) == value:
            return
        self.settings.setValue(f"light/channels/{channel}/name", value)
        self.changed.emit()  # Presentation only; never enqueue a serial command.

    def set_locked(self, reason: str, locked: bool) -> None:
        if locked:
            self.locks.add(reason)
            self._discard()
            self._cancel.set()
        else:
            self.locks.discard(reason)
        self.changed.emit()

    def _start(self) -> None:
        if self._thread is not None:
            return
        self._thread = QThread(self)
        self._worker = self._worker or ControllerWorker(self._cancel)
        self._worker.moveToThread(self._thread)
        self.request.connect(self._worker.execute)
        self.dispose_worker.connect(self._worker.dispose)
        self._worker.completed.connect(self._completed)
        self._worker.connection_fault.connect(self._connection_fault)
        self._worker.trace.connect(self._trace)
        self._thread.finished.connect(self._worker.deleteLater)
        self._thread.start()

    def _send(self, operation: str, **parameters) -> bool:
        if self.busy or self._stopping or self._stopped:
            return False
        self._start()
        self.busy = operation
        self.notice = ""
        self.changed.emit()
        self.request.emit({"operation": operation, **parameters})
        return True

    def auto_connect(self) -> bool:
        if not self.can_connect:
            return False
        self._cancel.clear()
        return self._send("scan", parity=self.parity, preferred=self.preferred_port())

    @property
    def parity(self) -> str:
        value = str(self.settings.value("light/parity", "none"))
        return value if value in ("none", "even", "odd") else "none"

    def preferred_port(self) -> str:
        serial = str(self.settings.value("light/last_serial", ""))
        if serial:
            matches = [p.name for p in available_ports() if p.serial_number == serial]
            if len(matches) == 1:
                return matches[0]
        return str(self.settings.value("light/last_port", "COM6")) or "COM6"

    def connect_port(self, port: str) -> bool:
        if not self.can_connect or not port.strip():
            return False
        self._cancel.clear()
        return self._send("connect", port=port.strip(), parity=self.parity)

    def refresh(self) -> bool:
        if self.locks or self.busy or self._safety or self._off_pending or self._stopping:
            return False
        return self.state.connected and self._send("refresh")

    def set_level(self, channel: int, value: int) -> None:
        if not self.editable or channel not in range(1, 5) or not 0 <= value <= 255:
            return
        values = list(self.levels)
        values[channel - 1] = value
        self.levels = tuple(values)
        self._has_levels = self._dirty = True
        self._save_timer.start()
        self._pending[channel] = value
        if not self._timer.isActive():
            self._timer.start()
        self.changed.emit()

    def enable(self) -> bool:
        if not self.can_enable:
            return False
        self._discard()
        if not self.save():
            return False
        self._cancel.clear()
        return self._send("enable", values=self.levels)

    def off(self, *, disconnect: bool = False) -> bool:
        if self._stopping or self._stopped:
            return False
        if disconnect and self.locks:
            return False
        self._queue_off("disconnect" if disconnect else "off")
        return True

    def _discard(self) -> None:
        self._timer.stop()
        self._pending.clear()

    def _flush(self) -> None:
        if self.busy:
            return
        if not self.editable:
            self._discard()
            return
        if self._pending:
            channel = next(iter(self._pending))
            self._send("brightness", channel=channel, value=self._pending.pop(channel))

    def save(self) -> bool:
        self._save_timer.stop()
        if not self._dirty:
            return True
        try:
            self.store.save(self.levels)
        except (OSError, ValueError) as exc:
            self.error = str(exc)
            self.failed.emit("CFG-101", str(exc))
            self.changed.emit()
            return False
        self._dirty = False
        return True

    def _queue_off(self, operation: str) -> None:
        self._cancel.set()
        self._discard()
        self.save()  # Persistence failure must never prevent hardware OFF.
        strength = {"": 0, "off": 1, "safe_off": 2, "disconnect": 3}
        if strength[operation] > strength[self._off_pending]:
            self._off_pending = operation
        if not self.busy:
            self._drain_off()
        self.changed.emit()

    def _drain_off(self) -> None:
        operation, self._off_pending = self._off_pending, ""
        if not self.state.shutdown_required:
            self._finish_safety(True)
        else:
            self._send(operation)

    @Slot(object)
    def _completed(self, result: OperationResult) -> None:
        self.busy = ""
        self.state = result.state
        self.error = result.error
        if result.scan is not None:
            self.scan_result = result.scan
            if not self.state.ready:
                self.notice = "multiple" if len(result.scan.compatible) > 1 else "no_match"
        if result.error:
            self._discard()
            self.failed.emit("COMM-203" if result.operation in ("off", "safe_off", "disconnect")
                             else "COMM-201", result.error)
        if result.operation in ("scan", "connect") and self.state.ready:
            self.settings.setValue("light/last_port", self.state.port)
            port = next((p for p in available_ports() if p.name == self.state.port), None)
            self.settings.setValue("light/last_serial", port.serial_number if port else "")
            if not self._has_levels:
                self.levels = tuple(self.state.brightness)
                self._has_levels = self._dirty = True
                self.save()
        if self._off_pending:
            self._drain_off()
        elif self._safety and result.operation in ("off", "safe_off", "disconnect"):
            self._finish_safety(not result.error and self.state.mode == "L")
        elif not result.error:
            self._flush()
        self.changed.emit()
        if result.error and self.locks.intersection({"recipe", "manual"}):
            self.fault.emit()

    @Slot(object)
    def _connection_fault(self, state: LightState) -> None:
        self.state = state
        self.error = "Serial/USB connection lost; light state unknown"
        self._cancel.set()
        self._discard()
        self.failed.emit("COMM-203", self.error)
        self.changed.emit()
        self.fault.emit()

    @Slot(str, str)
    def _trace(self, kind: str, detail: str) -> None:
        timestamp = datetime.now().astimezone().isoformat(timespec="milliseconds")
        self.logs.append(f"{timestamp} {kind} {detail}")

    @Slot(object)
    def _accept_safety(self, request: _SafetyRequest) -> None:
        if request.expired:
            request.done.set()
            return
        self._safety.append(request)
        self._queue_off(request.operation)

    def _finish_safety(self, ok: bool) -> None:
        requests, self._safety = self._safety, []
        for request in requests:
            valid = ok
            if self.state.shutdown_required:
                valid = valid and self.state.ready and self.state.mode == "L"
                if request.operation in ("safe_off", "disconnect"):
                    valid = valid and self.state.off_confirmed
                if request.operation == "disconnect":
                    valid = False
            request.ok = bool(valid and not request.expired)
            request.done.set()

    def verify_dark(self, *, zero: bool = False, disconnect: bool = False) -> bool:
        """Wait for a NEW readback, on GUI or measurement threads, with a bound.

        GUI waits pump Qt events; other threads marshal the request to the owner.
        This return value means verified completion, never mere request acceptance.
        """
        request = _SafetyRequest("disconnect" if disconnect else "safe_off" if zero else "off")
        if QThread.currentThread() == self.thread():
            self._accept_safety(request)
            loop = QEventLoop()
            timer = QTimer()
            timer.setInterval(10)
            timer.timeout.connect(lambda: loop.quit() if request.done.is_set() else None)
            deadline = QTimer()
            deadline.setSingleShot(True)
            deadline.timeout.connect(loop.quit)
            timer.start()
            deadline.start(self.SAFETY_TIMEOUT_MS)
            if not request.done.is_set():
                loop.exec()
            timer.stop()
            deadline.stop()
        else:
            self.safety_request.emit(request)
            request.done.wait(self.SAFETY_TIMEOUT_MS / 1000.0)
        if not request.done.is_set():
            request.expired = True
            return False
        return request.ok

    def shutdown(self) -> bool:
        self.set_locked("close", True)
        if not self.verify_dark(disconnect=True):
            self.set_locked("close", False)
            return False
        if not self.save():
            self.set_locked("close", False)
            return False
        self._save_timer.stop()
        if self._thread is not None and self._thread.isRunning():
            self._stopping = True
            self.dispose_worker.emit()
            loop = QEventLoop()
            self._thread.finished.connect(loop.quit)
            QTimer.singleShot(3000, loop.quit)
            if self._thread.isRunning():
                loop.exec()
            self._thread.wait(100)
            if self._thread.isRunning():
                self._stopping = False
                self.set_locked("close", False)
                return False
        self._stopped = True
        return True

    def metadata_fields(self) -> dict:
        return {"GSP4H": {"port": self.state.port,
                          "connected": self.state.connected,
                          "mode_readback": self.state.mode,
                          "brightness_readback": list(self.state.brightness),
                          "brightness_requested": list(self.levels)}}
