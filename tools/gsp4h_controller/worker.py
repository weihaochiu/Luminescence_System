"""Single Qt worker owns discovery, the serial handle, and every transaction."""
from __future__ import annotations

from dataclasses import dataclass
from threading import Event
from typing import Callable

from PySide6.QtCore import QObject, Signal, Slot
from PySide6.QtSerialPort import QSerialPort, QSerialPortInfo

from .controller import EnableCancelled, LightController, LightState, Transport
from .discovery import PortInfo, ScanCancelled, ScanResult, scan_ports
from .serial_transport import QtSerialTransport


@dataclass(frozen=True)
class OperationResult:
    operation: str
    state: LightState
    error: str = ""
    scan: ScanResult | None = None
    cancelled: bool = False


def available_ports() -> list[PortInfo]:
    return [PortInfo(
        item.portName(), item.description(), item.manufacturer(),
        f"VID={item.vendorIdentifier():04X} PID={item.productIdentifier():04X}"
        if item.hasVendorIdentifier() and item.hasProductIdentifier() else "",
        item.serialNumber(),
    ) for item in QSerialPortInfo.availablePorts()]


class ControllerWorker(QObject):
    completed = Signal(object)
    trace = Signal(str, str)
    connection_fault = Signal(object)

    def __init__(
        self, cancel: Event, make_transport: Callable[[], Transport] = QtSerialTransport,
        enumerate_ports: Callable[[], list[PortInfo]] = available_ports,
    ) -> None:
        super().__init__()
        self.cancel = cancel
        self.make_transport = make_transport
        self.enumerate_ports = enumerate_ports
        self.controller: LightController | None = None

    def _log(self, kind: str, data: str) -> None:
        self.trace.emit(kind, data)

    @Slot(object)
    def execute(self, request: dict) -> None:
        # Lazily construct QSerialPort here, after moveToThread().
        if self.controller is None:
            transport = self.make_transport()
            self.controller = LightController(transport, self._log)
            if isinstance(transport, QtSerialTransport):
                transport.serial.errorOccurred.connect(self._on_serial_error)
        controller = self.controller
        operation = request["operation"]
        scan = None
        try:
            if operation == "scan":
                if controller.state.shutdown_required:
                    raise RuntimeError("Disconnect the selected controller before scanning")
                scan = scan_ports(
                    self.enumerate_ports(), self.make_transport, self.cancel, self._log,
                    preferred=request.get("preferred", "COM6"), parity=request.get("parity", "none"),
                )
                if self.cancel.is_set():
                    raise ScanCancelled()
                if scan.selected is not None:
                    controller.connect(scan.selected, request.get("parity", "none"))
            elif operation == "connect":
                controller.connect(request["port"], request.get("parity", "none"))
            elif operation == "refresh":
                controller.refresh()
            elif operation == "brightness":
                controller.set_brightness(request["channel"], request["value"])
            elif operation == "mode":
                controller.set_mode(request["mode"])
            elif operation == "off":
                controller.turn_off()
            elif operation == "safe_off":
                controller.safe_off()
            elif operation == "enable":
                def check_cancel() -> None:
                    if self.cancel.is_set():
                        raise EnableCancelled("Enable cancelled by OFF/close request")
                controller.enable(request["values"], check_cancel)
            elif operation == "disconnect":
                controller.disconnect()
            else:
                raise ValueError("Unknown controller operation")
            result = OperationResult(operation, controller.state, scan=scan)
        except ScanCancelled:
            result = OperationResult(operation, controller.state, scan=scan, cancelled=True)
        except EnableCancelled:
            result = OperationResult(operation, controller.state, cancelled=True)
        except Exception as exc:
            self._log("ERROR", str(exc))
            result = OperationResult(operation, controller.state, str(exc), scan)
        self.completed.emit(result)

    @Slot(QSerialPort.SerialPortError)
    def _on_serial_error(self, error: QSerialPort.SerialPortError) -> None:
        if error in (
            QSerialPort.SerialPortError.ResourceError,
            QSerialPort.SerialPortError.DeviceNotFoundError,
            QSerialPort.SerialPortError.ReadError,
            QSerialPort.SerialPortError.WriteError,
        ) and self.controller is not None and self.controller.state.shutdown_required:
            self._log("ERROR", "Serial/USB connection lost; light settings are unknown")
            self.controller.transport.close()
            self.connection_fault.emit(self.controller.connection_fault())

    @Slot()
    def dispose(self) -> None:
        # The window only requests this after verified disconnect, or after a
        # read-only scan that never acquired a controlling session.
        if self.controller is not None and not self.controller.state.shutdown_required:
            self.controller.transport.close()
            self.controller = None
        self.thread().quit()
