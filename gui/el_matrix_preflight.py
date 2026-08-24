from __future__ import annotations

"""Aggregated, side-effect-minimal EL Matrix preflight validation."""

import shutil
from pathlib import Path
from typing import Any, Mapping
from uuid import uuid4

from core.i18n import tr

from .el_matrix_plan import ELMatrixPlan
from .measurement_execution_plan import effective_matrix_capture_axes
from .recipe_store import Recipe


def estimate_required_bytes(
    recipe: Recipe,
    width: int,
    height: int,
    *,
    global_safety: Any | None = None,
) -> int:
    pixels = max(1, int(width)) * max(1, int(height))
    captures = ELMatrixPlan(
        recipe,
        global_safety=global_safety,
    ).capture_counts()["overall"]
    # RAW TIFF + annotated JPEG + metadata and manifest allowance.
    per_capture = pixels * 6 + 16_384
    if recipe.output.export_pixel_csv:
        selected = sum((
            recipe.output.pixel_csv_raw,
            recipe.output.pixel_csv_dark_corrected,
            recipe.output.pixel_csv_exposure_normalized,
        ))
        per_capture += pixels * 36 * selected
    return int(captures * per_capture * 1.10)


def collect_preflight_errors(
    recipe: Recipe,
    *,
    smu_metadata: Mapping[str, Any],
    smu_output_confirmed_off: bool,
    relay_connected: bool,
    relay_settings: Any,
    camera_connected: bool,
    camera_snapshot: Mapping[str, Any],
    current_camera: Mapping[str, Any],
    output_root: str | Path,
    global_safety: Any | None = None,
) -> list[str]:
    errors = list(recipe.validate(global_safety))
    if not smu_metadata.get("connected"):
        errors.append(tr("preflight.smu_disconnected"))
    if not smu_metadata.get("supported"):
        errors.append(tr("preflight.smu_unsupported"))
    manufacturer = str(smu_metadata.get("manufacturer", "")).casefold()
    model = str(smu_metadata.get("model", "")).casefold()
    if "keysight" not in manufacturer or not model.startswith("b29"):
        errors.append(tr("preflight.smu_identity_mismatch"))
    if not smu_output_confirmed_off:
        errors.append(tr("preflight.smu_off_unconfirmed"))

    if not relay_connected:
        errors.append(tr("preflight.relay_disconnected"))
    try:
        errors.extend(tr("preflight.relay_settings", detail=item) for item in relay_settings.validate())
        mapping = dict(relay_settings.smu_output_channels)
        expected = {f"Ch{index}" for index in range(1, 5)}
        if set(mapping) != expected or len(set(mapping.values())) != 4:
            errors.append(tr("preflight.relay_mapping_invalid"))
        white = relay_settings.group("white_light")
        if white is None or not white.enabled:
            errors.append(tr("preflight.white_light_missing"))
        elif set(mapping.values()) & set(white.members):
            errors.append(tr("preflight.relay_mapping_overlap"))
    except Exception as exc:
        errors.append(tr("preflight.relay_mapping_unverified", detail=exc))

    if not camera_connected:
        errors.append(tr("preflight.camera_disconnected"))
    if current_camera.get("ScientificMeasurementReady") is not True:
        errors.append(tr("preflight.camera_scientific_unverified"))
    exposure_range = current_camera.get("exposure_range_us")
    gain_range = current_camera.get("gain_range")
    axes = effective_matrix_capture_axes(recipe)
    if not exposure_range:
        errors.append(tr("preflight.camera_exposure_capability_missing"))
    else:
        low, high = float(exposure_range[0]), float(exposure_range[1])
        if any(not low <= value * 1000.0 <= high for value in axes.exposures_ms):
            errors.append(tr("preflight.camera_exposure_out_of_range", low=f"{low:g}", high=f"{high:g}"))
    if not gain_range:
        errors.append(tr("preflight.camera_gain_capability_missing"))
    else:
        low, high = int(gain_range[0]), int(gain_range[1])
        if any(not low <= value <= high for value in axes.gains_percent):
            errors.append(tr("preflight.camera_gain_out_of_range", low=low, high=high))
    for key in ("ResolutionId", "Resolution", "PixelFormat", "BitDepth", "ContainerDtype"):
        if current_camera.get(key) != camera_snapshot.get(key):
            errors.append(tr("preflight.camera_snapshot_mismatch", key=key, snapshot=repr(camera_snapshot.get(key)), current=repr(current_camera.get(key))))

    root = Path(output_root)
    try:
        root.mkdir(parents=True, exist_ok=True)
        probe = root / f".el_matrix_preflight_{uuid4().hex}.tmp"
        probe.write_bytes(b"preflight")
        probe.unlink()
        required = estimate_required_bytes(
            recipe,
            int(camera_snapshot.get("ImageWidth", 0)),
            int(camera_snapshot.get("ImageHeight", 0)),
            global_safety=global_safety,
        )
        available = shutil.disk_usage(root).free
        if available < required:
            errors.append(tr("preflight.disk_space_insufficient", required=required, available=available))
    except Exception as exc:
        errors.append(tr("preflight.output_unwritable", detail=exc))
    # Keep the dialog useful: report each unique blocker exactly once.
    return list(dict.fromkeys(errors))
