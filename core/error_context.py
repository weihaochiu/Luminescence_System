from __future__ import annotations

"""Bounded, serializable diagnostics attached to an error event."""

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
import traceback as traceback_module
import re
from typing import Any, Mapping


MAX_TEXT_LENGTH = 2_000
MAX_TRACEBACK_LENGTH = 12_000
SENSITIVE_FRAGMENTS = (
    "password", "passwd", "secret", "token", "credential", "api_key",
    "apikey", "authorization",
)
REDACTED = "[REDACTED]"
_AUTHORIZATION_RE = re.compile(
    r"(?i)(\bauthorization\b\s*[:=]\s*)(?:bearer\s+)?[^\s,;&]+"
)
_SECRET_VALUE_RE = re.compile(
    r"(?i)(\b(?:password|passwd|token|secret|api[_-]?key|apikey|credential)\b"
    r"\s*[:=]\s*)(?:\"[^\"]*\"|'[^']*'|[^\s,;&]+)"
)
_BEARER_RE = re.compile(r"(?i)(\bbearer\s+)[A-Za-z0-9._~+/=-]+")


def sanitize_text(value: object) -> str:
    """Redact common credentials embedded in arbitrary diagnostic text."""

    text = str(value)
    text = _AUTHORIZATION_RE.sub(lambda match: match.group(1) + REDACTED, text)
    text = _SECRET_VALUE_RE.sub(lambda match: match.group(1) + REDACTED, text)
    return _BEARER_RE.sub(lambda match: match.group(1) + REDACTED, text)


def _bounded(value: object, limit: int = MAX_TEXT_LENGTH) -> str:
    text = sanitize_text(value)
    return text if len(text) <= limit else text[:limit] + "…[truncated]"


@dataclass(frozen=True)
class ErrorContext:
    timestamp: str = field(
        default_factory=lambda: datetime.now(timezone.utc).astimezone().isoformat(timespec="milliseconds")
    )
    subsystem: str | None = None
    channel: str | None = None
    instrument: str | None = None
    resource: str | None = None
    operation: str | None = None
    command: str | None = None
    expected: str | None = None
    actual: str | None = None
    setpoint: str | None = None
    source_mode: str | None = None
    compliance: str | None = None
    recipe: str | None = None
    sample_id: str | None = None
    exception_type: str | None = None
    exception_message: str | None = None
    traceback: str | None = None
    extra: Mapping[str, str] = field(default_factory=dict)

    @classmethod
    def build(
        cls,
        values: Mapping[str, object] | None = None,
        *,
        exception: BaseException | None = None,
        subsystem: str | None = None,
    ) -> "ErrorContext":
        source = dict(values or {})
        known = {item.name for item in cls.__dataclass_fields__.values()} - {"extra"}
        clean: dict[str, Any] = {}
        extra: dict[str, str] = {}
        for key, value in source.items():
            if value is None:
                continue
            if any(fragment in key.casefold() for fragment in SENSITIVE_FRAGMENTS):
                value = REDACTED
            if key in known:
                clean[key] = _bounded(value, MAX_TRACEBACK_LENGTH if key == "traceback" else MAX_TEXT_LENGTH)
            else:
                extra[str(key)] = _bounded(value)
        if subsystem and "subsystem" not in clean:
            clean["subsystem"] = subsystem
        if exception is not None:
            clean["exception_type"] = type(exception).__name__
            clean["exception_message"] = _bounded(exception)
            clean["traceback"] = _bounded(
                "".join(traceback_module.format_exception(exception)),
                MAX_TRACEBACK_LENGTH,
            )
        clean["extra"] = extra
        return cls(**clean)

    def as_dict(self) -> dict[str, object]:
        payload = asdict(self)
        extra = payload.pop("extra", {})
        payload = {key: value for key, value in payload.items() if value not in (None, "")}
        payload.update(extra)
        return payload
