from __future__ import annotations

"""Auditable HDR image products and JSON/CSV manifest output."""

import csv
import json
from pathlib import Path
from typing import TYPE_CHECKING, Any, Sequence

import numpy as np
from PIL import Image

if TYPE_CHECKING:
    from .auto_hdr import HDRResult

def save_hdr_products(
    base_path: str | Path,
    result: HDRResult,
    save_preview_png: bool = True,
) -> tuple[Path, Path | None]:
    """Save analysis float32 TIFF and optional display-only 8-bit PNG."""
    from .auto_hdr import make_preview

    base = Path(base_path)
    base.parent.mkdir(parents=True, exist_ok=True)
    linear_path = base.with_name(base.name + "_HDR_linear_float32.tiff")
    Image.fromarray(result.linear_dn_per_s.astype(np.float32), mode="F").save(linear_path, format="TIFF")
    preview_path: Path | None = None
    if save_preview_png:
        preview_path = base.with_name(base.name + "_HDR_preview_8bit.png")
        Image.fromarray(make_preview(result.linear_dn_per_s), mode="L").save(preview_path, format="PNG")
    return linear_path, preview_path

def save_hdr_capture_set(
    base_path: str | Path,
    frame_groups: Sequence[np.ndarray | Sequence[np.ndarray]],
    dark_groups: Sequence[np.ndarray | Sequence[np.ndarray]],
    result: HDRResult,
    gain_percent: int,
    hdr_settings_snapshot: dict[str, Any],
    execution_summary: dict[str, Any],
    save_preview_png: bool = True,
    profile_snapshot: dict[str, Any] | None = None,
    excluded_judgment_frames: Sequence[tuple[float, np.ndarray]] | None = None,
) -> dict[str, Any]:
    """Persist a complete, auditable HDR capture set.

    Every source EL frame and its matching Dark frame is written as TIFF.  A
    Master Dark is also saved for each exposure, followed by the quantitative
    float32 HDR product, display-only preview, and JSON/CSV manifests.  The
    manifests make it possible to reconstruct the merge without relying on
    filenames alone.
    """
    if not hdr_settings_snapshot or not execution_summary:
        raise ValueError("HDR 輸出必須包含完整系統設定快照與實際執行摘要")
    if not (len(frame_groups) == len(dark_groups) == len(result.exposures_ms)):
        raise ValueError("HDR 原始 EL、Dark 與曝光數量必須一致")
    base = Path(base_path)
    base.parent.mkdir(parents=True, exist_ok=True)
    records: list[dict[str, Any]] = []

    for exposure_index, exposure_ms in enumerate(result.exposures_ms):
        exposure_token = _exposure_token(exposure_ms)
        el_frames = _original_frames(frame_groups[exposure_index])
        dark_frames = _original_frames(dark_groups[exposure_index])
        for frame_index, array in enumerate(el_frames, start=1):
            path = base.with_name(
                f"{base.name}_exp{exposure_index + 1:02d}_{exposure_token}_EL_raw_f{frame_index:03d}.tiff"
            )
            _save_tiff(path, array)
            records.append(
                _manifest_record("el_raw", path, exposure_index, exposure_ms, gain_percent, frame_index)
            )
        for frame_index, array in enumerate(dark_frames, start=1):
            path = base.with_name(
                f"{base.name}_exp{exposure_index + 1:02d}_{exposure_token}_Dark_raw_f{frame_index:03d}.tiff"
            )
            _save_tiff(path, array)
            records.append(
                _manifest_record("dark_raw", path, exposure_index, exposure_ms, gain_percent, frame_index)
            )
        master_dark = np.median(np.stack([np.asarray(item) for item in dark_frames], axis=0), axis=0)
        master_path = base.with_name(
            f"{base.name}_exp{exposure_index + 1:02d}_{exposure_token}_MasterDark.tiff"
        )
        _save_tiff(master_path, master_dark.astype(np.float32))
        records.append(
            _manifest_record("master_dark", master_path, exposure_index, exposure_ms, gain_percent, 0)
        )

    for judgment_index, (exposure_ms, array) in enumerate(excluded_judgment_frames or (), start=1):
        path = base.with_name(
            f"{base.name}_excluded_{_exposure_token(float(exposure_ms))}_judgment_f001.tiff"
        )
        _save_tiff(path, array)
        record = _manifest_record(
            "overexposure_judgment", path, judgment_index - 1, float(exposure_ms), gain_percent, 1
        )
        record["analysis_eligible"] = False
        record["status"] = "excluded_severe_overexposure"
        records.append(record)

    for skipped_index, exposure_ms in enumerate(execution_summary.get("skipped_exposures_ms", []), start=1):
        records.append(
            {
                "kind": "exposure_skipped",
                "file": "",
                "exposure_index": skipped_index,
                "exposure_ms": float(exposure_ms),
                "gain_percent": gain_percent,
                "frame_index": "",
                "analysis_eligible": False,
                "status": "skipped_after_early_termination",
                "reason": str((execution_summary.get("early_termination") or {}).get("reason", "")),
            }
        )

    linear_path, preview_path = save_hdr_products(base, result, save_preview_png=save_preview_png)
    records.append(
        {
            "kind": "hdr_linear_float32",
            "file": linear_path.name,
            "exposure_index": "",
            "exposure_ms": "",
            "gain_percent": gain_percent,
            "frame_index": "",
            "analysis_eligible": True,
            "status": "saved",
            "reason": "",
        }
    )
    if preview_path is not None:
        records.append(
            {
                "kind": "hdr_preview_8bit",
                "file": preview_path.name,
                "exposure_index": "",
                "exposure_ms": "",
                "gain_percent": gain_percent,
                "frame_index": "",
                "analysis_eligible": False,
                "status": "saved",
                "reason": "",
            }
        )

    csv_path = base.with_name(base.name + "_HDR_file_manifest.csv")
    with csv_path.open("w", newline="", encoding="utf-8-sig") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(records[0]))
        writer.writeheader()
        writer.writerows(records)
    json_path = base.with_name(base.name + "_HDR_capture_manifest.json")
    payload = {
        "manifest_version": "1.1",
        "gain_percent": int(gain_percent),
        "exposures_ms": list(result.exposures_ms),
        "output_unit": "DN/s",
        "analysis_file": linear_path.name,
        "preview_file": preview_path.name if preview_path is not None else None,
        "source_files_required": True,
        "records": records,
        "profile_snapshot": profile_snapshot,
        "hdr_settings_snapshot": hdr_settings_snapshot,
        "execution_summary": execution_summary,
    }
    json_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return {
        "linear_tiff": linear_path,
        "preview_png": preview_path,
        "manifest_csv": csv_path,
        "manifest_json": json_path,
        "records": records,
    }

def _manifest_record(
    kind: str,
    path: Path,
    exposure_index: int,
    exposure_ms: float,
    gain_percent: int,
    frame_index: int,
) -> dict[str, Any]:
    return {
        "kind": kind,
        "file": path.name,
        "exposure_index": exposure_index + 1,
        "exposure_ms": exposure_ms,
        "gain_percent": int(gain_percent),
        "frame_index": frame_index,
        "analysis_eligible": kind != "hdr_preview_8bit",
        "status": "saved",
        "reason": "",
    }

def _exposure_token(exposure_ms: float) -> str:
    return f"{exposure_ms:.6f}".rstrip("0").rstrip(".").replace(".", "p") + "ms"

def _original_frames(group: np.ndarray | Sequence[np.ndarray]) -> list[np.ndarray]:
    data = np.asarray(group)
    if data.ndim == 2 or (data.ndim == 3 and data.shape[-1] in (3, 4)):
        return [data]
    if data.ndim >= 3:
        return [np.asarray(item) for item in data]
    raise ValueError("HDR 原始 frame group 格式無效")

def _save_tiff(path: Path, array: np.ndarray) -> None:
    data = np.asarray(array)
    if data.dtype.kind == "f":
        if data.ndim != 2:
            from .auto_hdr import _as_luminance

            data = _as_luminance(data)
        Image.fromarray(data.astype(np.float32), mode="F").save(path, format="TIFF")
        return
    if data.dtype not in (np.uint8, np.uint16):
        data = data.astype(np.uint16 if np.max(data, initial=0) > 255 else np.uint8)
    Image.fromarray(data).save(path, format="TIFF")
