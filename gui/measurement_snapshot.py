from __future__ import annotations

"""Auditable measurement snapshots independent of mutable defaults."""

import json
import hashlib
from copy import deepcopy
from dataclasses import asdict, is_dataclass
from datetime import datetime
from pathlib import Path
from types import MappingProxyType
from typing import Any, Mapping


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
    polarity_settings: Any | None = None,
    polarity_result: dict[str, Any] | None = None,
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
        "polarity_measurement": {
            "system_settings_snapshot": (
                polarity_settings.snapshot() if polarity_settings is not None else None
            ),
            "result": dict(polarity_result or {}),
        },
        "el_matrix": {
            "current_density_ma_cm2": list(
                recipe.el_matrix.current_density_ma_cm2
            ),
            "gains_percent": (
                None if recipe.hdr.enabled else list(recipe.el_matrix.gains_percent)
            ),
            "exposures_ms": (
                None if recipe.hdr.enabled else list(recipe.el_matrix.exposures_ms)
            ),
            "repeat": (
                None if recipe.hdr.enabled else int(recipe.el_matrix.repeat)
            ),
            "dark_frame_enabled": bool(recipe.el_matrix.dark_frame_enabled),
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


def _plain(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {str(key): _plain(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_plain(item) for item in value]
    if is_dataclass(value):
        return _plain(asdict(value))
    return deepcopy(value)


def _freeze(value: Any) -> Any:
    if isinstance(value, dict):
        return MappingProxyType({key: _freeze(item) for key, item in value.items()})
    if isinstance(value, list):
        return tuple(_freeze(item) for item in value)
    return value


def snapshot_payload(snapshot: Mapping[str, Any]) -> dict[str, Any]:
    return _plain(snapshot)


def calculate_snapshot_hash(payload: Mapping[str, Any]) -> str:
    canonical = snapshot_payload(payload)
    canonical.pop("snapshot_sha256", None)
    encoded = json.dumps(
        canonical, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def verify_snapshot_hash(snapshot: Mapping[str, Any]) -> bool:
    return str(snapshot.get("snapshot_sha256", "")) == calculate_snapshot_hash(snapshot)


def build_el_matrix_snapshot(
    recipe: Any,
    *,
    execution_order: list[dict[str, Any]],
    camera: Mapping[str, Any],
    smu: Mapping[str, Any],
    relay_mapping: Mapping[str, int],
    polarity_settings: Any,
    started_at: str | None = None,
    sample_ids: Mapping[str, str] | None = None,
    global_safety: Any | None = None,
    hdr_settings: Any | None = None,
    hdr_session: Any | None = None,
    output_directory: str = "",
) -> Mapping[str, Any]:
    """Create a recursively immutable, content-addressed Matrix snapshot."""

    from .recipe_store import RecipeStore

    sample_mapping = dict(sample_ids or {})
    payload: dict[str, Any] = {
        "schema": "el_matrix_measurement_snapshot",
        "snapshot_version": 1,
        "started_at": started_at or _now(),
        "recipe": {
            "recipe_id": str(recipe.recipe_id),
            "version": int(recipe.version),
            "schema_version": RecipeStore.schema_version,
            "complete_snapshot": recipe.to_dict(),
        },
        "execution_order": _plain(execution_order),
        "channels": [
            {
                "channel": channel.channel,
                "sample_id": sample_mapping.get(channel.channel, ""),
                "area_cm2": channel.area_cm2,
            }
            for channel in recipe.enabled_channels()
        ],
        "polarity": {
            "required_per_channel": bool(recipe.polarity.enabled),
            "system_settings": polarity_settings.snapshot()
            if hasattr(polarity_settings, "snapshot") else _plain(polarity_settings),
        },
        "dark_iv": _plain(recipe.dark_iv),
        "camera": _plain(camera),
        "smu": _plain(smu),
        "relay": {"logical_to_physical": dict(relay_mapping)},
        "global_safety": _plain(global_safety),
        "hdr": {
            "enabled": bool(recipe.hdr.enabled),
            "system_settings": (
                hdr_settings.snapshot()
                if recipe.hdr.enabled and hasattr(hdr_settings, "snapshot")
                else _plain(hdr_settings) if recipe.hdr.enabled else None
            ),
            "session": (
                {
                    "mode": str(hdr_session.mode),
                    "sample_id": str(hdr_session.sample_id),
                    "profile_path": str(hdr_session.profile_path),
                    "profile": (
                        hdr_session.profile.to_dict()
                        if getattr(hdr_session, "profile", None) is not None
                        else None
                    ),
                }
                if recipe.hdr.enabled and hdr_session is not None
                else None
            ),
        },
        "output": _plain(recipe.output),
        "output_directory": str(output_directory),
    }
    payload["snapshot_sha256"] = calculate_snapshot_hash(payload)
    return _freeze(payload)


def save_el_matrix_snapshot(path: str | Path, snapshot: Mapping[str, Any]) -> Path:
    if not verify_snapshot_hash(snapshot):
        raise ValueError("Measurement Snapshot SHA-256 verification failed")
    return save_measurement_snapshot(path, snapshot_payload(snapshot))
