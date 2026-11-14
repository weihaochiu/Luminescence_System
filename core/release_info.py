"""Versioned, bilingual operator release notes (no GUI or network dependency)."""
from __future__ import annotations

from datetime import date
import json
from pathlib import Path
import re

ROOT = Path(__file__).resolve().parents[1]


def version_tuple(value: str) -> tuple[int, int, int]:
    if not isinstance(value, str) or not re.fullmatch(r"\d+\.\d+\.\d+", value):
        raise ValueError("Expected a major.minor.patch version")
    return tuple(int(part) for part in value.split("."))


def validate_history(payload: object) -> list[dict]:
    if not isinstance(payload, dict) or payload.get("schema_version") != 1:
        raise ValueError("Unsupported release history")
    releases = payload.get("releases")
    if not isinstance(releases, list) or not releases or len(releases) > 1000:
        raise ValueError("Missing release history")
    previous = None
    for release in releases:
        if not isinstance(release, dict):
            raise ValueError("Invalid release entry")
        current = version_tuple(release.get("version"))
        if previous is not None and current >= previous:
            raise ValueError("Release versions must be unique and newest first")
        previous = current
        date.fromisoformat(release["date"])
        changes = release.get("changes", {})
        if not isinstance(changes, dict):
            raise ValueError("Invalid release changes")
        for language in ("zh-TW", "en-US"):
            notes = changes.get(language)
            if (not isinstance(notes, list) or not notes or len(notes) > 100
                    or any(not isinstance(note, str) or not note.strip()
                           or len(note) > 4000 for note in notes)):
                raise ValueError("Every release needs nonempty bilingual changes")
    return releases


def load_history(path: Path | None = None) -> list[dict]:
    return validate_history(json.loads((path or ROOT / "release_history.json").read_text("utf-8")))


def format_changes(releases: list[dict], language: str, *, after: str | None = None) -> str:
    selected = [entry for entry in releases
                if after is None or version_tuple(entry["version"]) > version_tuple(after)]
    return "\n\n".join(
        f"v{entry['version']}  ({entry['date']})\n" + "\n".join(
            f"• {note}" for note in entry["changes"].get(language, entry["changes"]["zh-TW"])
        ) for entry in selected
    )
