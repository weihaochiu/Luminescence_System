"""Hardware-neutral control service; its owner must serialize all calls."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Protocol

from .protocol import (
    ControllerError, brightness_command, mode_command, parse_brightness,
    parse_mode, verify_brightness_ack,
)
from .settings import validate_levels


class EnableCancelled(ControllerError):
    """The operator requested OFF while a saved configuration was being loaded."""


Log = Callable[[str, str], None]


class Transport(Protocol):
    @property
    def is_open(self) -> bool: ...
    def open(self, port: str, parity: str) -> None: ...
    def exchange(self, command: bytes, response_length: int) -> bytes: ...
    def close(self) -> None: ...


@dataclass(frozen=True)
class LightState:
    connected: bool = False
    shutdown_required: bool = False
    port: str = "COM6"
    mode: str | None = None
    brightness: tuple[int | None, ...] = (None,) * 4

    @property
    def ready(self) -> bool:
        return self.connected and self.mode is not None and all(
            value is not None for value in self.brightness
        )

    @property
    def off_confirmed(self) -> bool:
        return self.mode == "L" and self.brightness == (0, 0, 0, 0)


class LightController:
    def __init__(self, transport: Transport, log: Log | None = None) -> None:
        self.transport = transport
        self.log = log or (lambda _kind, _data: None)
        self.port = "COM6"
        self.parity = "none"
        self._session_active = False
        self._mode: str | None = None
        self._brightness: tuple[int | None, ...] = (None,) * 4

    @property
    def state(self) -> LightState:
        return LightState(
            self.transport.is_open, self._session_active, self.port,
            self._mode, self._brightness,
        )

    def _invalidate(self) -> None:
        self._mode = None
        self._brightness = (None,) * 4

    def connection_fault(self) -> LightState:
        """Retain shutdown responsibility after losing the serial connection."""
        self._invalidate()
        return self.state

    def _exchange(self, command: bytes, length: int) -> bytes:
        self.log("TX", repr(command))
        try:
            raw = self.transport.exchange(command, length)
        except Exception as exc:
            self._invalidate()
            self.log("ERROR", str(exc))
            raise ControllerError(f"{command!r}: {exc}") from exc
        self.log("RX", repr(raw))
        return raw

    def _require_open(self) -> None:
        if not self.transport.is_open:
            self._invalidate()
            raise ControllerError("Serial port is not open")

    def _require_ready(self) -> None:
        self._require_open()
        if not self.state.ready:
            raise ControllerError("Refresh all settings successfully before enabling light controls")

    def connect(self, port: str = "COM6", parity: str = "none") -> LightState:
        if self.transport.is_open or self._session_active:
            raise ControllerError("Shut down and disconnect the current session first")
        if not port.strip() or parity not in ("none", "even", "odd"):
            raise ValueError("Invalid serial port or parity")
        self._invalidate()
        reset_identity = getattr(self.transport, "reset_identity", None)
        if reset_identity is not None:
            # A new, explicitly selected session may use a different USB adapter;
            # a shutdown retry within the old session must retain its identity.
            reset_identity()
        self.transport.open(port.strip(), parity)
        self.port, self.parity = port.strip(), parity
        self._session_active = True
        self.log("INFO", f"Opened {self.port}: 19200, 8 data bits, 1 stop bit, parity={parity}")
        return self.refresh()  # Query only; never restore or enable light on connect.

    def refresh(self, check_cancel: Callable[[], None] | None = None) -> LightState:
        self._require_open()
        self._invalidate()
        try:
            if check_cancel is not None:
                check_cancel()
            mode = parse_mode(self._exchange(mode_command(), 1))
            values = []
            for channel in range(1, 5):
                if check_cancel is not None:
                    check_cancel()
                values.append(parse_brightness(self._exchange(brightness_command(channel), 5), channel))
        except Exception:
            self._invalidate()
            raise
        self._mode, self._brightness = mode, tuple(values)
        return self.state

    def set_brightness(self, channel: int, value: int) -> LightState:
        command = brightness_command(channel, value)
        self._require_ready()
        try:
            verify_brightness_ack(self._exchange(command, 1), channel)
            actual = parse_brightness(self._exchange(brightness_command(channel), 5), channel)
            if actual != value:
                raise ControllerError(f"CH{channel} readback mismatch: requested={value}, actual={actual}")
            values = list(self._brightness)
            values[channel - 1] = actual
            self._brightness = tuple(values)
            # Brightness and output mode are independent. Editing a level never
            # issues TH/TL; read the actual mode rather than assuming it is ON.
            self._mode = parse_mode(self._exchange(mode_command(), 1))
        except Exception:
            self._invalidate()
            raise
        return self.state

    def set_mode(self, mode: str) -> LightState:
        command = mode_command(mode)
        self._require_ready()
        try:
            if parse_mode(self._exchange(command, 1)) != mode:
                raise ControllerError("Global mode acknowledgement mismatch")
            actual = parse_mode(self._exchange(mode_command(), 1))
            if actual != mode:
                raise ControllerError(f"Global mode readback mismatch: requested={mode}, actual={actual}")
        except Exception:
            self._invalidate()
            raise
        self._mode = actual
        return self.state

    def turn_off(self) -> LightState:
        """Normal OFF preserves brightness; shutdown uses safe_off instead."""
        if not self._session_active:
            raise ControllerError("No controller session to turn off")
        if not self.transport.is_open:
            self.transport.open(self.port, self.parity)
        self._invalidate()
        try:
            if parse_mode(self._exchange(mode_command("L"), 1)) != "L":
                raise ControllerError("OFF acknowledgement mismatch")
        except Exception as exc:
            # A lost ACK does not prevent an authoritative query from verifying
            # L. Never fall back to the last cached mode.
            self.log("WARN", f"OFF acknowledgement unconfirmed: {exc}")
        state = self.refresh()
        if state.mode != "L":
            self._invalidate()
            raise ControllerError("OFF mode L was not verified")
        self.log("INFO", "Mode L verified; brightness values preserved")
        return state

    def enable(self, values, check_cancel: Callable[[], None] | None = None) -> LightState:
        """Apply all requested levels while dark; verify before enabling H."""
        values = validate_levels(values)
        self._require_ready()
        check_cancel = check_cancel or (lambda: None)
        try:
            check_cancel()
            self.turn_off()
            for channel, value in enumerate(values, 1):
                check_cancel()
                self.set_brightness(channel, value)
                if self.state.mode != "L":
                    raise ControllerError("Controller did not remain in mode L during configuration")
            check_cancel()
            self.set_mode("H")
            state = self.refresh(check_cancel)
            if state.mode != "H" or state.brightness != values:
                raise ControllerError("Enabled light configuration readback mismatch")
            return state
        except Exception:
            # Partial configuration must not enable the light. If cleanup itself
            # fails, invalidate every readback and retain the session for OFF retry.
            try:
                self.turn_off()
            except Exception as exc:
                self._invalidate()
                self.log("ERROR", f"Enable cleanup could not verify mode L: {exc}")
            raise

    def safe_off(self) -> LightState:
        if not self._session_active:
            raise ControllerError("No controller session to shut down")
        if not self.transport.is_open:
            # Only an explicit retry may reopen the same previously selected port.
            self.transport.open(self.port, self.parity)
        self._invalidate()
        # Try every OFF write even if an earlier acknowledgement is missing.
        for command, channel in [(mode_command("L"), None)] + [
            (brightness_command(ch, 0), ch) for ch in range(1, 5)
        ]:
            try:
                raw = self._exchange(command, 1)
                if channel is None:
                    if parse_mode(raw) != "L":
                        raise ControllerError("OFF acknowledgement mismatch")
                else:
                    verify_brightness_ack(raw, channel)
            except Exception as exc:
                self.log("WARN", f"OFF write unconfirmed; continuing: {exc}")

        failures: list[str] = []
        try:
            if parse_mode(self._exchange(mode_command(), 1)) != "L":
                failures.append("Global mode is not L")
        except Exception as exc:
            failures.append(f"Global mode: {exc}")
        for channel in range(1, 5):
            try:
                value = parse_brightness(self._exchange(brightness_command(channel), 5), channel)
                if value != 0:
                    failures.append(f"CH{channel} is {value}, expected 0")
            except Exception as exc:
                failures.append(f"CH{channel}: {exc}")
        if failures:
            self._invalidate()
            raise ControllerError("OFF readback not verified: " + "; ".join(failures))
        self._mode, self._brightness = "L", (0, 0, 0, 0)
        self.log("INFO", "OFF settings verified: mode L and CH1-CH4 brightness 0")
        return self.state

    def disconnect(self) -> LightState:
        if not self._session_active:
            return self.state
        self.safe_off()
        self.transport.close()
        if self.transport.is_open:
            raise ControllerError("Serial port did not close")
        self._session_active = False
        self.log("INFO", "Disconnected after verified OFF settings")
        return self.state
