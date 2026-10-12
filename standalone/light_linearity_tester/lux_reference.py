from __future__ import annotations

from datetime import datetime
import json
from pathlib import Path
from uuid import uuid4

from tools.camera_linearity_qualification.capture_manifest import atomic_write_json, sha256_file
from .calibration import LightCalibration


def session_root(path: str | Path) -> Path:
    root = Path(path).resolve()
    return root.parent if root.name == "SUMMARY" else root


def load_capture(root: str | Path):
    base = session_root(root) / "SUMMARY"
    manifest = json.loads((base / "capture_manifest.json").read_text(encoding="utf-8"))
    for name, field in (("measurement_snapshot.json", "snapshot_sha256"), ("condition_statistics.json", "statistics_sha256")):
        if not manifest.get(field) or sha256_file(base / name) != manifest[field]:
            raise ValueError(f"Capture evidence checksum mismatch: {name}")
    snapshot = json.loads((base / "measurement_snapshot.json").read_text(encoding="utf-8"))
    rows = json.loads((base / "condition_statistics.json").read_text(encoding="utf-8"))
    return base, manifest, snapshot, rows


def required_levels(rows: list[dict]) -> tuple[int, ...]:
    return tuple(sorted({int(row["pwm_level"]) for row in rows
                         if row.get("snr", 0) is not None and row.get("snr", 0) >= 5 and row["near_saturation_fraction"] == 0}))


def attach_lux(path: str | Path, calibration: LightCalibration, *, reproducibility_confirmed: bool) -> Path:
    base, manifest, snapshot, rows = load_capture(path)
    if not reproducibility_confirmed:
        raise ValueError("Confirm unchanged optics and reproducible warmed-up illumination before attaching LUX")
    if manifest["phase"] != "COMPLETE":
        raise ValueError("Deferred LUX requires a completed capture")
    if calibration.channel != snapshot["plan"]["channel"] or calibration.unit.strip().lower() != "lux":
        raise ValueError("LUX channel/unit does not match the capture")
    levels = required_levels(rows)
    if not levels:
        raise ValueError("No usable PWM levels to measure")
    calibration.require_levels(levels)
    reference = calibration.snapshot()
    payload = {"schema_version": "1.0", "capture_snapshot_sha256": manifest["snapshot_sha256"],
               "capture_statistics_sha256": manifest["statistics_sha256"], "reference": reference,
               "required_pwm_levels": list(levels), "reproducibility_confirmed": True}
    folder = base / "LUX"
    folder.mkdir(exist_ok=True)
    record = folder / f"lux_{datetime.now():%Y%m%d_%H%M%S}_{uuid4().hex[:8]}.json"
    atomic_write_json(record, payload)
    atomic_write_json(base / "analysis_reference.json", {"file": str(record.relative_to(base)), "sha256": sha256_file(record)})
    return record


def read_lux(base: Path, manifest: dict) -> dict | None:
    selector = base / "analysis_reference.json"
    if not selector.exists():
        return None
    selected = json.loads(selector.read_text(encoding="utf-8"))
    record = (base / selected["file"]).resolve()
    if not record.is_relative_to((base / "LUX").resolve()) or not record.is_file() or sha256_file(record) != selected["sha256"]:
        raise ValueError("Invalid deferred LUX record/checksum")
    payload = json.loads(record.read_text(encoding="utf-8"))
    if payload.get("schema_version") != "1.0" or not payload.get("reproducibility_confirmed"):
        raise ValueError("Deferred LUX record lacks reproducibility confirmation")
    if payload["capture_snapshot_sha256"] != manifest["snapshot_sha256"] or payload["capture_statistics_sha256"] != manifest["statistics_sha256"]:
        raise ValueError("LUX record belongs to a different capture")
    payload["record_sha256"] = selected["sha256"]
    return payload
