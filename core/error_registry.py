from __future__ import annotations

"""Central error taxonomy and registry loading without GUI dependencies."""

from dataclasses import dataclass
from enum import Enum
import json
from pathlib import Path
import re
from typing import Iterable


ERROR_CODE_PATTERN = re.compile(r"^(SMU|CAM|REL|MEAS|REC|FILE|CFG|COMM|HW|SYS|UI)-\d{3}$")
ALLOWED_ACTIONS = frozenset({"retry", "reconnect", "safe_shutdown"})
VALID_SUBSYSTEMS = frozenset(
    {"smu", "camera", "relay", "measurement", "recipe", "file", "config", "communication", "hardware", "system", "ui"}
)
REGISTRY_PATH = Path(__file__).resolve().parents[1] / "resources" / "errors" / "error_registry.json"


class Severity(str, Enum):
    INFO = "info"
    WARNING = "warning"
    ERROR = "error"
    CRITICAL = "critical"


@dataclass(frozen=True)
class ErrorDefinition:
    code: str
    subsystem: str
    severity: Severity
    recoverable: bool
    title_key: str
    message_key: str
    cause_keys: tuple[str, ...]
    solution_keys: tuple[str, ...]
    actions: tuple[str, ...] = ()


class ErrorRegistry:
    def __init__(self, definitions: Iterable[ErrorDefinition]) -> None:
        self._definitions: dict[str, ErrorDefinition] = {}
        for definition in definitions:
            if definition.code in self._definitions:
                raise ValueError(f"Duplicate error code: {definition.code}")
            if ERROR_CODE_PATTERN.fullmatch(definition.code) is None:
                raise ValueError(f"Invalid error code: {definition.code}")
            if definition.subsystem not in VALID_SUBSYSTEMS:
                raise ValueError(f"Invalid subsystem for {definition.code}: {definition.subsystem}")
            if not isinstance(definition.recoverable, bool):
                raise ValueError(f"Invalid recoverable flag for {definition.code}")
            if definition.severity is Severity.CRITICAL and any(
                action in {"ignore", "continue"} for action in definition.actions
            ):
                raise ValueError(f"Critical error {definition.code} cannot be ignored")
            unknown_actions = set(definition.actions) - ALLOWED_ACTIONS
            if unknown_actions:
                raise ValueError(
                    f"Invalid action for {definition.code}: {sorted(unknown_actions)}"
                )
            if not definition.solution_keys:
                raise ValueError(f"Error {definition.code} requires at least one solution")
            self._definitions[definition.code] = definition

    @classmethod
    def from_path(cls, path: Path = REGISTRY_PATH) -> "ErrorRegistry":
        payload = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(payload, dict):
            raise ValueError("Error registry must be a JSON object")
        definitions = []
        for code, raw in payload.items():
            definitions.append(
                ErrorDefinition(
                    code=code,
                    subsystem=str(raw["subsystem"]),
                    severity=Severity(str(raw["severity"])),
                    recoverable=raw["recoverable"],
                    title_key=str(raw["title_key"]),
                    message_key=str(raw["message_key"]),
                    cause_keys=tuple(str(item) for item in raw.get("cause_keys", [])),
                    solution_keys=tuple(str(item) for item in raw.get("solution_keys", [])),
                    actions=tuple(str(item) for item in raw.get("actions", [])),
                )
            )
        return cls(definitions)

    def get(self, code: str) -> ErrorDefinition | None:
        return self._definitions.get(str(code).upper())

    def require(self, code: str) -> ErrorDefinition:
        definition = self.get(code)
        if definition is None:
            raise KeyError(code)
        return definition

    def all(self) -> tuple[ErrorDefinition, ...]:
        return tuple(self._definitions[code] for code in sorted(self._definitions))


default_error_registry = ErrorRegistry.from_path()
