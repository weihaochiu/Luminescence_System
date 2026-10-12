"""The ASCII commands documented in the two-page GSP-4H manual."""
from __future__ import annotations

import re


class ControllerError(RuntimeError):
    """Communication or readback could not be verified."""


def channel_letter(channel: int) -> str:
    if type(channel) is not int or channel not in range(1, 5):
        raise ValueError("Channel must be an integer from 1 to 4")
    return "ABCD"[channel - 1]


def brightness_command(channel: int, value: int | None = None) -> bytes:
    letter = channel_letter(channel)
    if value is None:
        return f"S{letter}#".encode("ascii")
    if type(value) is not int or not 0 <= value <= 255:
        raise ValueError("Brightness must be an integer from 0 to 255")
    return f"S{letter}{value:04d}#".encode("ascii")


def mode_command(mode: str | None = None) -> bytes:
    if mode is None:
        return b"T#"
    if mode not in ("H", "L"):
        raise ValueError("Global mode must be H or L")
    return f"T{mode}#".encode("ascii")


def response_text(raw: bytes) -> str:
    try:
        return raw.decode("ascii").strip("\r\n \t").removesuffix("#")
    except UnicodeDecodeError as exc:
        raise ControllerError(f"Non-ASCII response: {raw!r}") from exc


def parse_brightness(raw: bytes, channel: int) -> int:
    letter = channel_letter(channel)
    text = response_text(raw)
    if not re.fullmatch(r"[A-Da-d][0-9]{4}", text):
        raise ControllerError(f"Invalid brightness response: {raw!r}")
    if text[0].upper() != letter:
        raise ControllerError(f"Wrong response channel for CH{channel}: {raw!r}")
    value = int(text[1:])
    if not 0 <= value <= 255:
        raise ControllerError(f"Out-of-range brightness response: {raw!r}")
    return value


def parse_mode(raw: bytes) -> str:
    text = response_text(raw)
    if text not in ("H", "h", "L", "l"):
        # Do not treat the printed I/l ambiguity as a verified OFF response.
        raise ControllerError(f"Invalid global mode response: {raw!r}")
    return text.upper()


def verify_brightness_ack(raw: bytes, channel: int) -> None:
    letter = channel_letter(channel)
    if response_text(raw) not in (letter, letter.lower()):
        raise ControllerError(f"Invalid CH{channel} acknowledgement: {raw!r}")
