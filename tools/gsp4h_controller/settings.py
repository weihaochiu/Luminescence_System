"""Separate, validated brightness preferences with atomic file replacement."""
from __future__ import annotations

import json
import os
from pathlib import Path
import tempfile


def validate_levels(values) -> tuple[int, int, int, int]:
    if not isinstance(values, (list, tuple)) or len(values) != 4 or any(
        type(value) is not int or not 0 <= value <= 255 for value in values
    ):
        raise ValueError("Brightness settings must contain four integers from 0 to 255")
    return tuple(values)


class BrightnessStore:
    def __init__(self, path: Path) -> None:
        self.path = Path(path)

    def load(self) -> tuple[int, int, int, int] | None:
        if not self.path.exists():
            return None
        record = json.loads(self.path.read_text(encoding="utf-8"))
        if not isinstance(record, dict) or type(record.get("schema_version")) is not int or record["schema_version"] != 1:
            raise ValueError("Unsupported brightness settings schema")
        return validate_levels(record.get("brightness"))

    def save(self, values) -> None:
        values = validate_levels(values)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary: Path | None = None
        try:
            with tempfile.NamedTemporaryFile(
                mode="w", encoding="utf-8", dir=self.path.parent,
                prefix=".brightness_", suffix=".tmp", delete=False,
            ) as stream:
                temporary = Path(stream.name)
                json.dump({"schema_version": 1, "brightness": list(values)}, stream, ensure_ascii=False, indent=2)
                stream.write("\n")
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary, self.path)
        finally:
            if temporary is not None and temporary.exists():
                temporary.unlink()
