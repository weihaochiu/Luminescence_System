from __future__ import annotations

"""Aggregated, side-effect-minimal EL Matrix preflight validation."""

import shutil
from pathlib import Path
from typing import Any, Mapping
from uuid import uuid4

from .recipe_store import Recipe


def estimate_required_bytes(recipe: Recipe, width: int, height: int) -> int:
    pixels = max(1, int(width)) * max(1, int(height))
    captures = recipe.matrix_capture_counts()["overall"]
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
) -> list[str]:
    errors = list(recipe.validate())
    if not smu_metadata.get("connected"):
        errors.append("SMU 未連線")
    if not smu_metadata.get("supported"):
        errors.append("目前 SMU 不是已支援且完成初始化的 Keysight B2900")
    manufacturer = str(smu_metadata.get("manufacturer", "")).casefold()
    model = str(smu_metadata.get("model", "")).casefold()
    if "keysight" not in manufacturer or not model.startswith("b29"):
        errors.append("SMU identity 與 Keysight B2900 要求不符")
    expected_visa = recipe.smu.visa_address.strip()
    actual_visa = str(smu_metadata.get("visa_address", "")).strip()
    if expected_visa and expected_visa != actual_visa:
        errors.append(
            f"Recipe VISA address 不符：expected={expected_visa!r}, actual={actual_visa!r}"
        )
    if not smu_output_confirmed_off:
        errors.append("SMU OUTPUT OFF 未經實際 readback 確認")

    if not relay_connected:
        errors.append("Relay 未連線")
    try:
        errors.extend(f"Relay 設定：{item}" for item in relay_settings.validate())
        mapping = dict(relay_settings.smu_output_channels)
        expected = {f"Ch{index}" for index in range(1, 5)}
        if set(mapping) != expected or len(set(mapping.values())) != 4:
            errors.append("Relay CH1～CH4 logical mapping 不完整或不唯一")
        white = relay_settings.group("white_light")
        if white is None or not white.enabled:
            errors.append("white_light group 不存在或未啟用")
        elif set(mapping.values()) & set(white.members):
            errors.append("Relay routing mapping 與 white_light group 重疊")
    except Exception as exc:
        errors.append(f"Relay mapping 無法驗證：{exc}")

    if not camera_connected:
        errors.append("Camera 未連線")
    exposure_range = current_camera.get("exposure_range_us")
    gain_range = current_camera.get("gain_range")
    if not exposure_range:
        errors.append("Camera 未提供 Exposure SDK capability")
    else:
        low, high = float(exposure_range[0]), float(exposure_range[1])
        if any(not low <= value * 1000.0 <= high for value in recipe.el_matrix.exposures_ms):
            errors.append(f"Exposure 超出 Camera SDK capability：{low:g}～{high:g} us")
    if not gain_range:
        errors.append("Camera 未提供 Gain SDK capability")
    else:
        low, high = int(gain_range[0]), int(gain_range[1])
        if any(not low <= value <= high for value in recipe.el_matrix.gains_percent):
            errors.append(f"Gain 超出 Camera SDK capability：{low}～{high}")
    for key in ("Resolution", "PixelFormat", "BitDepth"):
        if current_camera.get(key) != camera_snapshot.get(key):
            errors.append(
                f"Camera {key} 與 Measurement Snapshot 不符："
                f"snapshot={camera_snapshot.get(key)!r}, current={current_camera.get(key)!r}"
            )

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
        )
        available = shutil.disk_usage(root).free
        if available < required:
            errors.append(
                f"輸出磁碟空間不足：estimated={required} bytes, available={available} bytes"
            )
    except Exception as exc:
        errors.append(f"輸出目錄不可建立或不可寫入：{exc}")
    # Keep the dialog useful: report each unique blocker exactly once.
    return list(dict.fromkeys(errors))
