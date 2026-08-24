from __future__ import annotations

"""Recoverable, TIFF-backed Pixel CSV post-processing for EL Matrix runs."""

import csv
import json
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from time import monotonic
from typing import Any, Callable, Mapping

from core.i18n import tr

import numpy as np
import tifffile

from .measurement_output import sha256_file, write_mono_array_csv_atomic


SAFE_SHUTDOWN_KEYS = (
    "smu_output_off",
    "routing_off",
    "white_light_off",
    "ownership_released",
    "ok",
)


def verified_safe_shutdown(result: Mapping[str, Any] | None) -> bool:
    return bool(result) and all(result.get(key) is True for key in SAFE_SHUTDOWN_KEYS)


@dataclass(frozen=True)
class PixelCSVProgress:
    current: int
    total: int
    percent: float
    remaining_time_s: float
    estimated_finish: datetime | None
    message: str = ""
    phase: str = "Pixel CSV"


class PixelCSVPostprocessError(RuntimeError):
    pass


def _atomic_json(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".tmp")
    try:
        temporary.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        temporary.replace(path)
    finally:
        temporary.unlink(missing_ok=True)


def _atomic_csv(path: Path, fieldnames: list[str], rows: list[Mapping[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".tmp")
    try:
        with temporary.open("w", newline="", encoding="utf-8-sig") as stream:
            writer = csv.DictWriter(stream, fieldnames=fieldnames, extrasaction="ignore")
            writer.writeheader()
            writer.writerows(rows)
        temporary.replace(path)
    finally:
        temporary.unlink(missing_ok=True)


def _key(metadata: Mapping[str, Any]) -> tuple[int, str, int, str, tuple[int, ...]]:
    exposure = format(float(metadata["Exposure"]), ".12g")
    shape = metadata.get("ScientificShape")
    if not isinstance(shape, (list, tuple)):
        height = metadata.get("RawImageHeight", metadata.get("ImageHeight"))
        width = metadata.get("RawImageWidth", metadata.get("ImageWidth"))
        shape = () if height is None or width is None else (height, width)
    return (
        int(metadata["Gain"]),
        exposure,
        int(metadata["RepeatIndex"]),
        str(metadata.get("Resolution", "")),
        tuple(int(value) for value in shape),
    )


class PixelCSVPostprocessor:
    def __init__(
        self,
        run_directory: str | Path,
        safe_shutdown_result: Mapping[str, Any],
        *,
        now: Callable[[], datetime] = lambda: datetime.now().astimezone(),
    ) -> None:
        self.run_directory = Path(run_directory)
        self.safe_shutdown_result = dict(safe_shutdown_result)
        self.now = now
        self.status_path = self.run_directory / "postprocess_status.json"
        self.pixel_manifest_path = self.run_directory / "pixel_csv_manifest.csv"
        self.measurement_manifest_path = self.run_directory / "measurement_manifest.csv"

    def run(
        self,
        report_progress: Callable[[PixelCSVProgress], None] = lambda _progress: None,
    ) -> dict[str, Any]:
        if not verified_safe_shutdown(self.safe_shutdown_result):
            raise PixelCSVPostprocessError(
                "Pixel CSV is blocked until safe shutdown is fully verified"
            )
        previous = self._load_status()
        records = {
            str(item.get("job_id")): dict(item)
            for item in previous.get("records", [])
            if item.get("job_id")
        }
        started_at = previous.get("started_at") or self.now().isoformat(timespec="seconds")
        try:
            snapshot = json.loads(
                (self.run_directory / "measurement_snapshot.json").read_text(encoding="utf-8")
            )
            options = dict(snapshot.get("output", {}))
            metadata_items = self._capture_metadata()
            dark_by_key = {
                _key(payload): (path, payload)
                for path, payload in metadata_items
                if payload.get("MeasurementType") == "DARK"
            }
            jobs = self._jobs(metadata_items, dark_by_key, options)
        except Exception as exc:
            failure = {
                "schema_version": 1,
                "status": "failed",
                "started_at": started_at,
                "updated_at": self.now().isoformat(timespec="seconds"),
                "verified_safe_shutdown": True,
                "total_files": 0,
                "completed_files": 0,
                "records": list(records.values()),
                "error": str(exc),
            }
            _atomic_json(self.status_path, failure)
            raise PixelCSVPostprocessError(str(exc)) from exc
        status: dict[str, Any] = {
            "schema_version": 1,
            "status": "pending",
            "started_at": started_at,
            "updated_at": self.now().isoformat(timespec="seconds"),
            "verified_safe_shutdown": True,
            "total_files": len(jobs),
            "completed_files": 0,
            "records": list(records.values()),
        }
        _atomic_json(self.status_path, status)
        started = monotonic()
        completed = 0
        expected_by_metadata: dict[str, int] = {}
        for job in jobs:
            metadata_name = str(job["metadata_path"])
            expected_by_metadata[metadata_name] = expected_by_metadata.get(metadata_name, 0) + 1
        try:
            status["status"] = "processing"
            _atomic_json(self.status_path, status)
            self._emit_progress(report_progress, 0, len(jobs), started, tr("progress.pixel_csv_starting"))
            for job in jobs:
                job_id = str(job["job_id"])
                existing = records.get(job_id)
                if existing is not None and self._record_is_valid(existing, job):
                    completed += 1
                    self._emit_progress(report_progress, completed, len(jobs), started, tr("progress.verified_skipped"))
                    continue
                record = self._process_job(job)
                records[job_id] = record
                completed += 1
                self._update_capture_metadata(
                    Path(str(job["metadata_path"])),
                    records,
                    expected_by_metadata[str(job["metadata_path"])],
                )
                self._write_pixel_manifest(records)
                self._update_measurement_manifest(Path(job["metadata_path"]))
                status.update({
                    "status": "processing",
                    "updated_at": self.now().isoformat(timespec="seconds"),
                    "completed_files": completed,
                    "records": list(records.values()),
                })
                _atomic_json(self.status_path, status)
                self._emit_progress(report_progress, completed, len(jobs), started, Path(job["output_path"]).name)
            for metadata_path, _payload in metadata_items:
                expected = expected_by_metadata.get(str(metadata_path), 0)
                self._update_capture_metadata(metadata_path, records, expected)
                self._update_measurement_manifest(metadata_path)
            self._write_pixel_manifest(records)
            status.update({
                "status": "completed",
                "updated_at": self.now().isoformat(timespec="seconds"),
                "completed_at": self.now().isoformat(timespec="seconds"),
                "completed_files": len(jobs),
                "records": list(records.values()),
            })
            _atomic_json(self.status_path, status)
            self._write_final_files_manifest()
            return status
        except Exception as exc:
            status.update({
                "status": "partial" if completed else "failed",
                "updated_at": self.now().isoformat(timespec="seconds"),
                "completed_files": completed,
                "records": list(records.values()),
                "error": str(exc),
            })
            _atomic_json(self.status_path, status)
            raise PixelCSVPostprocessError(str(exc)) from exc

    def _capture_metadata(self) -> list[tuple[Path, dict[str, Any]]]:
        captures: list[tuple[Path, dict[str, Any]]] = []
        for path in sorted(self.run_directory.rglob("*.json")):
            if path.name in {"measurement_snapshot.json", "postprocess_status.json"}:
                continue
            try:
                payload = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                continue
            if payload.get("MeasurementType") in {"DARK", "EL"} and payload.get("RawTiffPath"):
                captures.append((path, payload))
        return captures

    def _jobs(
        self,
        metadata_items: list[tuple[Path, dict[str, Any]]],
        dark_by_key: Mapping[
            tuple[int, str, int, str, tuple[int, ...]], tuple[Path, dict[str, Any]]
        ],
        options: Mapping[str, Any],
    ) -> list[dict[str, Any]]:
        if not options.get("export_pixel_csv", False):
            return []
        jobs: list[dict[str, Any]] = []
        for metadata_path, payload in metadata_items:
            raw_tiff = Path(str(payload["RawTiffPath"]))
            stem = raw_tiff.with_suffix("")
            products: list[tuple[str, str]] = []
            if options.get("pixel_csv_raw", False):
                products.append(("RAW", "_pixels_raw.csv"))
            if payload.get("MeasurementType") == "EL":
                if options.get("pixel_csv_dark_corrected", False):
                    products.append(("DarkCorrected", "_pixels_dark_corrected.csv"))
                if options.get("pixel_csv_exposure_normalized", False):
                    products.append(("ExposureNormalized", "_pixels_exposure_normalized.csv"))
            dark_entry = dark_by_key.get(_key(payload)) if payload.get("MeasurementType") == "EL" else None
            for product, suffix in products:
                if product != "RAW" and dark_entry is None:
                    raise PixelCSVPostprocessError(
                        "No Shared Dark matches Gain/Exposure/Repeat/Resolution/Geometry for "
                        + str(metadata_path)
                    )
                dark_metadata = None if dark_entry is None else dark_entry[1]
                output_path = stem.with_name(stem.name + suffix)
                job_id = f"{metadata_path.relative_to(self.run_directory)}::{product}"
                jobs.append({
                    "job_id": job_id,
                    "product": product,
                    "metadata_path": str(metadata_path),
                    "source_tiff": str(raw_tiff),
                    "source_sha256": sha256_file(raw_tiff),
                    "shared_dark_tiff": None if dark_metadata is None else str(dark_metadata["RawTiffPath"]),
                    "shared_dark_sha256": None if dark_metadata is None else sha256_file(dark_metadata["RawTiffPath"]),
                    "output_path": str(output_path),
                    "exposure_ms": float(payload["Exposure"]),
                })
        return jobs

    def _process_job(self, job: Mapping[str, Any]) -> dict[str, Any]:
        source_path = Path(str(job["source_tiff"]))
        output_path = Path(str(job["output_path"]))
        source = np.asarray(tifffile.imread(source_path))
        self._validate_scientific_array(source, source_path)
        product = str(job["product"])
        if product == "RAW":
            output_array = source
            value_header = "DN"
            unit = "DN"
        else:
            dark_path = Path(str(job["shared_dark_tiff"]))
            dark = np.asarray(tifffile.imread(dark_path))
            self._validate_scientific_array(dark, dark_path)
            if dark.shape != source.shape:
                raise ValueError(
                    f"Shared Dark shape {dark.shape} does not match source "
                    f"shape {source.shape}: {source_path}"
                )
            corrected = source.astype(np.int32) - dark.astype(np.int32)
            if product == "DarkCorrected":
                output_array = corrected
                value_header = "DarkCorrectedDN"
                unit = "DN"
            else:
                exposure_ms = float(job["exposure_ms"])
                if exposure_ms <= 0:
                    raise ValueError("Exposure normalization requires Exposure > 0 ms")
                output_array = corrected.astype(np.float64) / exposure_ms
                value_header = "DN_per_ms"
                unit = "DN/ms"
        write_mono_array_csv_atomic(
            output_path, output_array, value_header=value_header
        )
        return {
            "job_id": job["job_id"],
            "product": product,
            "metadata_path": job["metadata_path"],
            "source_tiff": str(source_path),
            "source_sha256": job["source_sha256"],
            "shared_dark_tiff": job["shared_dark_tiff"],
            "shared_dark_sha256": job["shared_dark_sha256"],
            "output_csv": str(output_path),
            "output_sha256": sha256_file(output_path),
            "value_header": value_header,
            "unit": unit,
            "array_dtype": str(output_array.dtype),
            "completed_at": self.now().isoformat(timespec="seconds"),
        }

    @staticmethod
    def _validate_scientific_array(array: np.ndarray, path: Path) -> None:
        if array.dtype != np.uint16:
            raise TypeError(
                f"Scientific TIFF must contain uint16 pixels, got {array.dtype}: {path}"
            )
        if array.ndim != 2:
            raise ValueError(
                f"Scientific TIFF must be H×W mono, got shape {array.shape}: {path}"
            )

    def _record_is_valid(self, record: Mapping[str, Any], job: Mapping[str, Any]) -> bool:
        output = Path(str(record.get("output_csv", "")))
        return bool(
            record.get("source_sha256") == job.get("source_sha256")
            and record.get("shared_dark_sha256") == job.get("shared_dark_sha256")
            and record.get("value_header")
            and record.get("unit")
            and record.get("array_dtype")
            and output.is_file()
            and record.get("output_sha256") == sha256_file(output)
        )

    def _update_capture_metadata(
        self,
        metadata_path: Path,
        records: Mapping[str, Mapping[str, Any]],
        expected_products: int,
    ) -> None:
        payload = json.loads(metadata_path.read_text(encoding="utf-8"))
        related = [
            item for item in records.values()
            if Path(str(item.get("metadata_path", ""))) == metadata_path
        ]
        payload["PixelCsvPaths"] = {
            str(item["product"]): str(item["output_csv"]) for item in related
        }
        payload["PixelCsvHashes"] = {
            str(item["product"]): str(item["output_sha256"]) for item in related
        }
        payload["PixelCsvSources"] = {
            str(item["product"]): {
                "SourceTiff": item["source_tiff"],
                "SourceTiffSha256": item["source_sha256"],
                "SharedDarkTiff": item["shared_dark_tiff"],
                "SharedDarkTiffSha256": item["shared_dark_sha256"],
            }
            for item in related
        }
        payload["PixelCsvQuantities"] = {
            str(item["product"]): {
                "ValueHeader": item["value_header"],
                "Unit": item["unit"],
                "ArrayDtype": item["array_dtype"],
            }
            for item in related
        }
        payload["PixelCsvPostprocessStatus"] = (
            "completed" if len(related) >= expected_products else "processing"
        )
        _atomic_json(metadata_path, payload)

    def _write_pixel_manifest(self, records: Mapping[str, Mapping[str, Any]]) -> None:
        fields = [
            "job_id", "product", "metadata_path", "source_tiff", "source_sha256",
            "shared_dark_tiff", "shared_dark_sha256", "output_csv", "output_sha256",
            "value_header", "unit", "array_dtype", "completed_at",
        ]
        rows = [records[key] for key in sorted(records)]
        _atomic_csv(self.pixel_manifest_path, fields, rows)

    def _update_measurement_manifest(self, metadata_path: Path) -> None:
        if not self.measurement_manifest_path.is_file():
            return
        with self.measurement_manifest_path.open("r", newline="", encoding="utf-8-sig") as stream:
            reader = csv.DictReader(stream)
            rows = [dict(row) for row in reader]
            fields = list(reader.fieldnames or [])
        payload = json.loads(metadata_path.read_text(encoding="utf-8"))
        additions = [
            "PixelCsvPaths", "PixelCsvHashes", "PixelCsvSources", "PixelCsvQuantities",
            "PixelCsvPostprocessStatus",
        ]
        for field in additions:
            if field not in fields:
                fields.append(field)
        for row in rows:
            if Path(str(row.get("MetadataJsonPath", ""))) == metadata_path:
                for field in additions:
                    value = payload.get(field, {})
                    row[field] = json.dumps(value, ensure_ascii=False) if isinstance(value, dict) else str(value)
                row["MetadataJsonSha256"] = sha256_file(metadata_path)
                if "MetadataJsonSha256" not in fields:
                    fields.append("MetadataJsonSha256")
                break
        _atomic_csv(self.measurement_manifest_path, fields, rows)

    def _write_final_files_manifest(self) -> None:
        target = self.run_directory / "final_files_manifest.csv"
        files = sorted(
            path for path in self.run_directory.rglob("*")
            if path.is_file() and path != target and not path.name.endswith(".tmp")
        )
        rows = [{
            "RelativePath": str(path.relative_to(self.run_directory)),
            "AbsolutePath": str(path),
            "SizeBytes": path.stat().st_size,
            "Sha256": sha256_file(path),
        } for path in files]
        _atomic_csv(target, ["RelativePath", "AbsolutePath", "SizeBytes", "Sha256"], rows)

    def _load_status(self) -> dict[str, Any]:
        if not self.status_path.is_file():
            return {}
        try:
            return json.loads(self.status_path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return {}

    def _emit_progress(
        self,
        callback: Callable[[PixelCSVProgress], None],
        completed: int,
        total: int,
        started: float,
        message: str,
    ) -> None:
        elapsed = max(0.0, monotonic() - started)
        remaining = 0.0 if completed <= 0 else elapsed / completed * max(0, total - completed)
        callback(PixelCSVProgress(
            current=completed,
            total=total,
            percent=100.0 if total == 0 else completed / total * 100.0,
            remaining_time_s=remaining,
            estimated_finish=self.now() + timedelta(seconds=remaining),
            message=message,
        ))
