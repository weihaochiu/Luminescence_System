from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import tempfile
from typing import Any


SCHEMA_VERSION = "1.0.0"


def atomic_write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(prefix=path.name + ".", suffix=".tmp", dir=path.parent)
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as stream:
            json.dump(payload, stream, ensure_ascii=False, indent=2, sort_keys=True)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        temporary.replace(path)
    finally:
        temporary.unlink(missing_ok=True)


def sha256_file(path: str | Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


class CaptureManifest:
    def __init__(self, path: str | Path, session_id: str, mode: str) -> None:
        self.path = Path(path)
        self.payload: dict[str, Any] = {
            "schema_version": SCHEMA_VERSION,
            "session_id": session_id,
            "mode": mode,
            "phase": "INITIALIZED",
            "frames": [],
            "skipped_conditions": [],
            "events": [],
        }
        self.flush()

    def flush(self) -> None:
        atomic_write_json(self.path, self.payload)

    def set_phase(self, phase: str) -> None:
        self.payload["phase"] = str(phase)
        self.flush()

    def add_frame(self, frame: dict[str, Any]) -> None:
        self.payload["frames"].append(dict(frame))
        self.flush()

    def add_skip(self, condition: dict[str, Any], trigger: str) -> None:
        self.payload["skipped_conditions"].append({**condition, "trigger": trigger})
        self.flush()

    def add_event(self, kind: str, detail: str) -> None:
        self.payload["events"].append({"kind": str(kind), "detail": str(detail)})
        self.flush()
