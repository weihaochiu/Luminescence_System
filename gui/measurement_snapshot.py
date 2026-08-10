from __future__ import annotations

"""Auditable measurement snapshots independent of mutable defaults."""

import json
from datetime import datetime
from pathlib import Path
from typing import Any


def _now() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def build_measurement_snapshot(
    recipe: Any,
    hdr_settings: Any,
    measurement_role: str,
    camera_info: dict[str, Any] | None = None,
    hdr_profile: Any | None = None,
    exposure_plan: Any | None = None,
    execution_summary: dict[str, Any] | None = None,
    output_records: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Capture the complete effective configuration used by one measurement."""
    profile_payload = hdr_profile.to_dict() if hdr_profile is not None else None
    plan_payload = None
    if exposure_plan is not None:
        plan_payload = {
            "planned_exposures_ms": list(exposure_plan.exposures_ms),
            "gain_percent": int(exposure_plan.gain_percent),
            "frames_per_exposure": int(exposure_plan.frames_per_exposure),
            "frame_interval_s": float(exposure_plan.frame_interval_s),
            "mode": str(exposure_plan.mode),
            "estimated_point_time_s": float(exposure_plan.estimated_point_time_s),
        }
    return {
        "schema": "el_measurement_effective_settings_snapshot",
        "snapshot_version": "1.0",
        "captured_at": _now(),
        "measurement_role": measurement_role,
        "recipe": {
            "recipe_id": str(recipe.recipe_id),
            "name": str(recipe.name),
            "version": int(recipe.version),
            "complete_snapshot": recipe.to_dict(),
        },
        "hdr": {
            "enabled_by_recipe": bool(recipe.hdr.enabled),
            "system_settings_snapshot": hdr_settings.snapshot() if recipe.hdr.enabled else None,
            "t0_profile_snapshot": profile_payload,
            "effective_exposure_plan": plan_payload,
            "execution": execution_summary,
        },
        "camera": dict(camera_info or {}),
        "smu_scan": {
            "drive_mode": recipe.el_sweep.drive_mode,
            "setpoint_basis": recipe.el_sweep.setpoint_basis,
            "scan_direction": recipe.el_sweep.scan_direction,
            "repeat_count": recipe.el_sweep.repeat_count,
            "points": [
                {
                    "setpoint": point.setpoint,
                    "dwell_s": point.dwell_s,
                    "exposure_ms": None if recipe.hdr.enabled else point.exposure_ms,
                    "gain_percent": None if recipe.hdr.enabled else point.gain_percent,
                    "frames": None if recipe.hdr.enabled else point.frame_count,
                    "frame_interval_s": None if recipe.hdr.enabled else point.frame_interval_s,
                }
                for point in recipe.enabled_points()
            ],
        },
        "output_records": list(output_records or []),
    }


def save_measurement_snapshot(path: str | Path, snapshot: dict[str, Any]) -> Path:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_suffix(target.suffix + ".tmp")
    temporary.write_text(json.dumps(snapshot, ensure_ascii=False, indent=2), encoding="utf-8")
    temporary.replace(target)
    return target
