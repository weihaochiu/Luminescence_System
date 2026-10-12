"""Blocking Qt serial transport; create/use it in the dedicated worker thread."""
from __future__ import annotations

import math
import time

from PySide6.QtCore import QIODevice
from PySide6.QtSerialPort import QSerialPort, QSerialPortInfo

from .protocol import ControllerError


class QtSerialTransport:
    TIMEOUT_SECONDS = 0.8
    TRAILING_WAIT_MS = 25
    MAX_RESPONSE_BYTES = 64

    def __init__(self) -> None:
        self.serial = QSerialPort()
        self._resync_needed = False
        self._usb_serial: str | None = None

    @property
    def is_open(self) -> bool:
        return self.serial.isOpen()

    def open(self, port: str, parity: str = "none") -> None:
        if self.is_open:
            raise ControllerError("Serial port already open")
        self.serial.setPortName(port)
        info = next((item for item in QSerialPortInfo.availablePorts() if item.portName() == port), None)
        serial_number = info.serialNumber() if info is not None else ""
        if self._usb_serial and serial_number != self._usb_serial:
            raise ControllerError("USB adapter serial number changed; refusing to send commands")
        settings = (
            self.serial.setBaudRate(19200),
            self.serial.setDataBits(QSerialPort.DataBits.Data8),
            self.serial.setStopBits(QSerialPort.StopBits.OneStop),
            self.serial.setParity({
                "none": QSerialPort.Parity.NoParity,
                "even": QSerialPort.Parity.EvenParity,
                "odd": QSerialPort.Parity.OddParity,
            }[parity]),
            self.serial.setFlowControl(QSerialPort.FlowControl.NoFlowControl),
        )
        if not all(settings) or not self.serial.open(QIODevice.OpenModeFlag.ReadWrite):
            raise ControllerError(f"Cannot open {port}: {self.serial.errorString()}")
        self._resync_needed = False
        if serial_number:
            self._usb_serial = serial_number

    def _check_error(self) -> None:
        if self.serial.error() not in (
            QSerialPort.SerialPortError.NoError,
            QSerialPort.SerialPortError.TimeoutError,
        ):
            raise ControllerError(self.serial.errorString())

    def exchange(self, command: bytes, response_length: int) -> bytes:
        if not self.is_open:
            raise ControllerError("Serial port is not open")
        raw = bytearray()
        try:
            if self._resync_needed:
                # Drain late responses for one full timeout. Responses carry no
                # transaction IDs; a partial reply must never become new readback.
                end = time.monotonic() + self.TIMEOUT_SECONDS
                while time.monotonic() < end:
                    self.serial.readAll()
                    self.serial.waitForReadyRead(max(1, math.ceil((end - time.monotonic()) * 1000)))
                    self._check_error()
                self._resync_needed = False
            if not self.serial.clear(QSerialPort.Direction.Input):
                raise ControllerError(f"Cannot clear input: {self.serial.errorString()}")
            self.serial.clearError()
            deadline = time.monotonic() + self.TIMEOUT_SECONDS
            if self.serial.write(command) != len(command):
                raise ControllerError("Serial write did not accept the complete command")
            while self.serial.bytesToWrite():
                remaining = math.ceil((deadline - time.monotonic()) * 1000)
                if remaining <= 0 or not self.serial.waitForBytesWritten(remaining):
                    raise ControllerError(f"Serial write failed: {self.serial.errorString()}")

            while True:
                raw.extend(bytes(self.serial.readAll()))
                if len(raw) > self.MAX_RESPONSE_BYTES:
                    raise ControllerError(f"Oversized response: {bytes(raw)!r}")
                payload = bytes(raw).strip(b"\r\n \t").removesuffix(b"#")
                remaining = math.ceil((deadline - time.monotonic()) * 1000)
                if len(payload) >= response_length:
                    # Capture optional framing/coalesced garbage without requiring
                    # CR/LF, which the manual does not specify.
                    if remaining > 0 and self.serial.waitForReadyRead(min(self.TRAILING_WAIT_MS, remaining)):
                        continue
                    self._check_error()
                    return bytes(raw)
                if remaining <= 0 or not self.serial.waitForReadyRead(remaining):
                    self._check_error()
                    raise ControllerError(f"Response timeout; partial RX={bytes(raw)!r}")
        except Exception:
            self._resync_needed = True
            raise

    def close(self) -> None:
        self.serial.close()

    def reset_identity(self) -> None:
        if self.is_open:
            raise ControllerError("Disconnect before selecting another USB adapter")
        self._usb_serial = None
