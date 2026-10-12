from __future__ import annotations

"""Non-overwriting batch products, cancellation boundaries and progress estimates."""

from dataclasses import asdict
from datetime import datetime
import csv
import json
from pathlib import Path
import re
from time import monotonic
from typing import Callable
from uuid import uuid4

import numpy as np
from PIL import Image
import tifffile

from .processing import DisplaySettings, fuse, tone_map
from .scan import Cancelled, Group, Inventory, OUTPUT_MARKER


def write_json(path: Path, value: dict):
    temporary = path.with_name(path.name + ".tmp")
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False), encoding="utf-8")
    temporary.replace(path)


def safe_name(text: str) -> str:
    return re.sub(r'[^\w.\-]+', "_", text, flags=re.UNICODE).strip(". ")[:80] or "capture"


def generate_batch(inventory: Inventory, groups: list[Group], output_parent: str | Path, *,
                   settings: DisplaySettings = DisplaySettings(),
                   check_cancel: Callable[[], None] = lambda: None,
                   progress: Callable[[dict], None] = lambda _: None) -> dict:
    settings.validate()
    if not groups:
        raise ValueError("No selected groups")
    check_cancel()
    parent = Path(output_parent).resolve()
    parent.mkdir(parents=True, exist_ok=True)
    output = parent / ("HDR_VIEW_OUTPUT_" + datetime.now().strftime("%Y%m%d_%H%M%S") + "_" + uuid4().hex[:8])
    output.mkdir(exist_ok=False)
    manifest = {"schema_version": "1.0", "hdr_viewer_output": True,
                "purpose": "viewing_only", "quantitative": False,
                "source_root": str(inventory.root), "output_directory": str(output),
                "status": "running", "created_at": datetime.now().astimezone().isoformat(),
                "scan_issues": inventory.issues, "excluded_dark_or_derived": inventory.excluded_dark,
                "results": []}
    write_json(output / OUTPUT_MARKER, manifest)
    total = sum(g.work for g in groups)
    completed = 0
    started = monotonic()
    pending: Path | None = None

    def emit(units: int, phase: str, group: Group, index: int):
        nonlocal completed
        completed = min(total, completed + units)
        elapsed = monotonic() - started
        eta = elapsed * (total - completed) / completed if completed else None
        progress({"phase": phase, "completed": completed, "total": total,
                  "group_index": index, "group_total": len(groups), "key": asdict(group.key),
                  "elapsed_s": elapsed, "remaining_s": eta})

    try:
        for index, group in enumerate(groups, 1):
            check_cancel()
            before = completed
            key = asdict(group.key)
            name = f"{index:04d}_{safe_name(group.key.sample)}_{safe_name(group.key.channel)}_J{group.key.density:g}_G{group.key.gain}"
            emit(0, "prepare", group, index)
            result = {**key, "exposure_count": len(group.exposures), "input_count": len(group.frames),
                      "status": "failed", "error": "", "folder": ""}
            try:
                merged = fuse(group, check_cancel=check_cancel,
                              step=lambda amount, phase: emit(amount, phase, group, index))
                check_cancel()
                display, display_info = tone_map(merged.image, merged.valid, settings)
                pixels = merged.image.size
                emit(pixels, "display", group, index)
                pending = output / (".partial_" + name)
                pending.mkdir(exist_ok=False)
                stem = name + "_HDR"
                tifffile.imwrite(pending / (stem + "_uncalibrated_float32.tiff"), merged.image,
                                 photometric="minisblack", metadata={"purpose": "viewing_only", "quantitative": False})
                check_cancel()
                tifffile.imwrite(pending / (stem + "_view.tiff"), display, photometric="minisblack")
                check_cancel()
                Image.fromarray((display.astype(np.uint32) * 255 // 65535).astype(np.uint8)).save(pending / (stem + "_preview.png"))
                Image.fromarray((merged.valid.astype(np.uint8) * 255)).save(pending / (stem + "_valid_mask.png"))
                record = {"schema_version": "1.0", "algorithm": "weighted_linear_assumption_v1",
                          "hdr_viewer_output": True, "purpose": "viewing_only", "quantitative": False,
                          "condition": key, "units": "uncalibrated_DN_per_s", "display": display_info,
                          "correction": merged.corrections, "sources": merged.provenance,
                          "invalid_pixel_fraction": float(np.mean(~merged.valid)),
                          "limitations": ["Unverified linear response; no dark, gain or flat-field calibration",
                                          "Fixed scene required; no motion correction",
                                          "Display copies use per-group brightness scaling",
                                          "Engineering saturation/noise weights; not quantitative"]}
                write_json(pending / (stem + ".json"), record)
                check_cancel()
                target = output / name
                pending.rename(target)
                pending = None
                result.update(status="completed", folder=str(target))
                emit(pixels, "write", group, index)
            except Cancelled:
                raise
            except Exception as exc:
                result["error"] = f"{type(exc).__name__}: {exc}"
                emit(max(0, group.work - (completed - before)), "group_failed", group, index)
            finally:
                if pending is not None:
                    # Only remove this operation's known temporary files. Never
                    # recursively delete an input or a user-selected directory.
                    if pending.resolve().parent != output.resolve() or not pending.name.startswith(".partial_"):
                        raise RuntimeError("Unsafe temporary output path")
                    for artifact in pending.iterdir():
                        if artifact.is_file():
                            artifact.unlink()
                    pending.rmdir()
                    pending = None
            manifest["results"].append(result)
            write_json(output / OUTPUT_MARKER, manifest)
        manifest["status"] = "completed" if all(r["status"] == "completed" for r in manifest["results"]) else "completed_with_errors"
    except Cancelled:
        manifest["status"] = "cancelled"
    except Exception as exc:
        manifest["status"] = "failed"
        manifest["error"] = f"{type(exc).__name__}: {exc}"
    finally:
        manifest["elapsed_s"] = monotonic() - started
        write_json(output / OUTPUT_MARKER, manifest)
        fields = ["run", "sample", "channel", "density", "gain", "exposure_count", "input_count", "status", "error", "folder"]
        with (output / "batch_summary.csv").open("w", encoding="utf-8-sig", newline="") as stream:
            writer = csv.DictWriter(stream, fieldnames=fields)
            writer.writeheader()
            writer.writerows(manifest["results"])
    return manifest
