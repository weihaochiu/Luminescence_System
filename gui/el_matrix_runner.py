from __future__ import annotations

"""Safety-authoritative multi-channel EL Matrix measurement runner."""

import csv
import json
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path
from time import monotonic, sleep
from typing import Any, Callable, Mapping, Protocol
from uuid import uuid4

import numpy as np
from PySide6.QtGui import QImage

from .el_matrix_plan import ELMatrixPlan, MatrixCapture
from .measurement_output import (
    append_manifest,
    capture_timestamp,
    sanitize_filename,
    save_matrix_capture,
    sha256_file,
)
from .measurement_execution_plan import build_measurement_execution_plan
from .measurement_snapshot import (
    build_el_matrix_snapshot,
    save_el_matrix_snapshot,
    snapshot_payload,
)
from .recipe_store import ChannelRecipe, Recipe
from .numeric import format_voltage_number


@dataclass(frozen=True)
class CapturedFrame:
    image: QImage
    timestamp: datetime
    camera_temperature_c: float | None = None
    camera_metadata: dict[str, Any] = field(default_factory=dict)
    scientific_image: Any | None = None


@dataclass(frozen=True)
class MatrixRuntimeProgress:
    phase: str
    current: int
    total: int
    message: str = ""
    channel: str = ""
    sample_id: str = ""
    channel_index: int = 0
    channel_total: int = 0
    output_mode: str | None = None
    current_density_ma_cm2: float | None = None
    commanded_voltage_v: float | None = None
    gain_percent: int | None = None
    exposure_ms: float | None = None
    repeat_index: int = 0
    repeat_total: int = 0
    channel_completed: int = 0
    channel_capture_total: int = 0
    remaining_captures: int = 0
    remaining_time_s: float = 0.0
    estimated_finish: datetime | None = None


class ELMatrixHardware(Protocol):
    def prepare_shared_dark(self) -> None: ...
    def route_channel(self, logical_channel: str, check_cancel: Callable[[], None]) -> None: ...
    def run_polarity(self, channel: ChannelRecipe, check_cancel: Callable[[], None]) -> dict[str, Any]: ...
    def apply_polarity_factor(self, factor: int) -> None: ...
    def prepare_channel_dark(self) -> None: ...
    def run_dark_iv(self, settings: Any, check_cancel: Callable[[], None]) -> list[dict[str, Any]]: ...
    def set_current(self, current_a: float, voltage_compliance_v: float) -> float: ...
    def set_voltage(self, voltage_v: float, current_compliance_ma: float) -> float: ...
    def readback(self) -> Any: ...
    def capture(self, exposure_ms: float, gain_percent: int, timeout_s: float,
                check_cancel: Callable[[], None]) -> CapturedFrame: ...
    def output_off(self) -> None: ...
    def clear_routing(self) -> None: ...
    def safe_shutdown(self) -> Mapping[str, bool]: ...


def interruptible_wait(seconds: float, check_cancel: Callable[[], None]) -> None:
    deadline = monotonic() + max(0.0, seconds)
    while True:
        check_cancel()
        remaining = deadline - monotonic()
        if remaining <= 0:
            return
        sleep(min(0.05, remaining))


class _RuntimeETA:
    def __init__(self, plan: ELMatrixPlan) -> None:
        self.plan = plan
        self.remaining_exposure_s = sum(plan.exposure_sequence_after(0))
        self.remaining_captures = plan.estimate().overall_captures
        self.observed_overhead_s = plan.matrix.estimated_capture_overhead_s
        self.samples = 0
        self.remaining_fixed_s = max(
            0.0, plan.estimate().total_time_s - self.remaining_exposure_s
            - self.remaining_captures * self.observed_overhead_s,
        )

    def complete_capture(self, exposure_s: float, elapsed_s: float) -> None:
        overhead = max(0.0, elapsed_s - exposure_s)
        self.samples += 1
        alpha = 1.0 / min(self.samples, 20)
        self.observed_overhead_s += alpha * (overhead - self.observed_overhead_s)
        self.remaining_exposure_s = max(0.0, self.remaining_exposure_s - exposure_s)
        self.remaining_captures = max(0, self.remaining_captures - 1)

    def consume_fixed(self, seconds: float) -> None:
        self.remaining_fixed_s = max(0.0, self.remaining_fixed_s - max(0.0, seconds))

    def remaining_s(self) -> float:
        return (
            self.remaining_exposure_s
            + self.remaining_captures * self.observed_overhead_s
            + self.remaining_fixed_s
        )


def _execution_order(recipe: Recipe) -> list[dict[str, Any]]:
    return build_measurement_execution_plan(recipe).to_dict()["steps"]


class ELMatrixRunner:
    def __init__(
        self,
        recipe: Recipe,
        hardware: ELMatrixHardware,
        output_root: str | Path,
        *,
        report_progress: Callable[[MatrixRuntimeProgress], None],
        is_cancel_requested: Callable[[], bool],
        report_frame: Callable[[QImage], None] | None = None,
        now: Callable[[], datetime] = lambda: datetime.now().astimezone(),
        measurement_snapshot: Mapping[str, Any] | None = None,
        sample_ids: Mapping[str, str] | None = None,
        global_safety: Any | None = None,
        max_recipe_time_s: float = 1800.0,
        max_output_time_s: float = 600.0,
    ) -> None:
        supplied_sample_ids = dict(sample_ids or {})
        self.sample_ids = {
            channel.channel: supplied_sample_ids.get(channel.channel)
            or channel.channel
            for channel in recipe.enabled_channels()
        }
        self.global_safety = global_safety
        self.max_recipe_time_s = float(max_recipe_time_s)
        self.max_output_time_s = float(max_output_time_s)
        if measurement_snapshot is None:
            isolated = Recipe.from_dict(recipe.to_dict())
            measurement_snapshot = build_el_matrix_snapshot(
                isolated,
                execution_order=_execution_order(isolated),
                camera={}, smu={}, relay_mapping={}, polarity_settings={},
                sample_ids=self.sample_ids,
                global_safety=global_safety,
            )
        else:
            isolated = Recipe.from_dict(
                snapshot_payload(measurement_snapshot)["recipe"]["complete_snapshot"]
            )
        self.snapshot = measurement_snapshot
        self.recipe = isolated
        self.plan = ELMatrixPlan(
            isolated,
            sample_ids=self.sample_ids,
            global_safety=global_safety,
        )
        self.execution_plan = build_measurement_execution_plan(
            isolated,
            global_safety,
        )
        frozen_order = snapshot_payload(self.snapshot).get("execution_order", [])
        if frozen_order != self.execution_plan.to_dict()["steps"]:
            raise ValueError(
                "Measurement snapshot execution order does not match the runtime plan"
            )
        self.hardware = hardware
        self.output_root = Path(output_root)
        self.report_progress = report_progress
        self.is_cancel_requested = is_cancel_requested
        self.report_frame = report_frame or (lambda _frame: None)
        self.now = now
        self.run_id = self.now().strftime("%Y%m%d_%H%M%S") + "_" + uuid4().hex[:8]
        self.run_directory = self.output_root / self.run_id
        self._completed = 0
        self._eta = _RuntimeETA(self.plan)
        self._polarity: dict[str, dict[str, Any]] = {}
        self._run_started = 0.0
        self._output_started: float | None = None
        self._last_remaining = self.plan.estimate().total_time_s
        self._last_finish: datetime | None = None
        self._shared_dark_frames: dict[tuple[int, float], list[np.ndarray]] = {}

    def check_cancel(self) -> None:
        if self.is_cancel_requested():
            from .measurement_worker import MeasurementCancelled
            raise MeasurementCancelled()
        if self._run_started and monotonic() - self._run_started > self.max_recipe_time_s:
            raise RuntimeError("Runtime watchdog: max_recipe_time_s exceeded")
        if (
            self._output_started is not None
            and monotonic() - self._output_started > self.max_output_time_s
        ):
            raise RuntimeError(
                "Runtime watchdog: max_output_time_s exceeded for electrical setpoint"
            )

    def run(self) -> dict[str, Any]:
        self.run_directory.mkdir(parents=True, exist_ok=False)
        save_el_matrix_snapshot(
            self.run_directory / "measurement_snapshot.json", self.snapshot
        )
        self._run_started = monotonic()
        result: dict[str, Any] | None = None
        try:
            if "polarity" in self.execution_plan.keys:
                self._run_all_polarities()
            else:
                self._configure_recipe_polarity()
            if "dark_frame" in self.execution_plan.keys:
                self.hardware.prepare_shared_dark()
                self._run_shared_dark_once()
            for channel_index, channel in enumerate(self.plan.channels, start=1):
                self._run_channel(channel, channel_index)
            self.check_cancel()
            final_manifest = self._write_final_files_manifest()
            result = {
                "run_id": self.run_id,
                "output_directory": str(self.run_directory),
                "captures": self._completed,
                "snapshot_sha256": self.snapshot["snapshot_sha256"],
                "final_manifest": str(final_manifest),
                "completed_at": self.now().isoformat(timespec="seconds"),
            }
        finally:
            self._output_started = None
            shutdown_result = self.hardware.safe_shutdown()
        normalized = dict(shutdown_result)
        required = (
            "smu_output_off", "routing_off", "white_light_off",
            "ownership_released", "ok",
        )
        if not all(normalized.get(name) is True for name in required):
            raise RuntimeError("Safe shutdown did not satisfy every post-processing gate")
        if result is None:
            raise RuntimeError("Hardware measurement ended without a result")
        result["hardware_measurement_completed"] = True
        result["safe_shutdown"] = normalized
        return result

    def _route(self, channel: ChannelRecipe, channel_index: int, phase: str) -> None:
        self.check_cancel()
        self._phase(phase, f"Routing {channel.channel}", channel, channel_index)
        self.hardware.output_off()
        self.hardware.clear_routing()
        started = monotonic()
        self.hardware.route_channel(channel.channel, self.check_cancel)
        self._eta.consume_fixed(monotonic() - started)

    def _run_all_polarities(self) -> None:
        for index, channel in enumerate(self.plan.channels, start=1):
            self._route(channel, index, "Polarity Routing")
            self._phase("Polarity Check", channel.channel, channel, index)
            started = monotonic()
            result = self.hardware.run_polarity(channel, self.check_cancel)
            factor = result.get("polarity_factor")
            if result.get("polarity_check_status") != "COMPLETED" or factor not in (-1, 1):
                raise RuntimeError(f"{channel.channel} polarity could not be reliably determined")
            self._polarity[channel.channel] = dict(result)
            self._save_polarity(channel, result)
            self._eta.consume_fixed(monotonic() - started)
        self.hardware.output_off()
        self.hardware.clear_routing()

    def _configure_recipe_polarity(self) -> None:
        factor = 1 if self.recipe.geometry.forward_polarity == "positive" else -1
        for channel in self.plan.channels:
            self._polarity[channel.channel] = {
                "polarity_check_status": "CONFIGURED",
                "polarity_result": self.recipe.geometry.forward_polarity,
                "polarity_factor": factor,
                "polarity_timestamp": None,
            }

    def _save_polarity(self, channel: ChannelRecipe, result: Mapping[str, Any]) -> None:
        sample_id = self.sample_ids[channel.channel]
        folder = self.run_directory / f"{channel.channel}_{sanitize_filename(sample_id)}"
        folder.mkdir(parents=True, exist_ok=True)
        payload = dict(result)
        payload.update({
            "Channel": channel.channel,
            "SampleID": sample_id,
            "DeviceAreaCm2": channel.area_cm2,
            "SnapshotSha256": self.snapshot["snapshot_sha256"],
        })
        (folder / "polarity.json").write_text(
            json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
        )

    def _run_shared_dark_once(self) -> None:
        self._phase("Shared Dark", "Verified SMU, white light and routing OFF")
        applicable = [channel.channel for channel in self.plan.channels]
        dark_total = self.plan.estimate().shared_dark_captures
        dark_index = 0
        for gain in self.plan.gains_percent:
            for exposure in self.plan.exposures_ms:
                for repeat_index in range(1, self.plan.repeat + 1):
                    dark_index += 1
                    capture = MatrixCapture(
                        measurement_type="DARK",
                        channel="SHARED",
                        sample_id=", ".join(applicable),
                        area_cm2=None,
                        output_mode=None,
                        current_density_ma_cm2=None,
                        commanded_voltage_v=None,
                        commanded_physical_current_a=None,
                        commanded_physical_voltage_v=None,
                        gain_percent=gain,
                        exposure_ms=exposure,
                        repeat_index=repeat_index,
                        repeat_total=self.plan.repeat,
                        channel_capture_index=dark_index,
                        channel_capture_total=dark_total,
                        overall_index=self._completed + 1,
                        overall_total=self.plan.estimate().overall_captures,
                    )
                    self._capture_and_save(capture, None, applicable)

    def _run_channel(self, channel: ChannelRecipe, channel_index: int) -> None:
        self._route(channel, channel_index, "Channel Switching")
        polarity = self._polarity[channel.channel]
        self.hardware.apply_polarity_factor(int(polarity["polarity_factor"]))
        if self.recipe.dark_iv.enabled:
            self.hardware.prepare_channel_dark()
            self._phase("Dark Stabilization", channel.channel, channel, channel_index)
            started = monotonic()
            interruptible_wait(self.recipe.dark_iv.dark_stabilization_s, self.check_cancel)
            self._eta.consume_fixed(monotonic() - started)
            self._phase("Dark I-V", channel.channel, channel, channel_index)
            self._output_started = monotonic()
            try:
                rows = self.hardware.run_dark_iv(self.recipe.dark_iv, self.check_cancel)
            finally:
                self._output_started = None
            self._save_dark_iv(channel, rows)
            self.hardware.output_off()

        channel_capture_total = self.plan.estimate().el_per_channel
        channel_completed = 0
        try:
            for setpoint in self.plan.electrical_setpoints:
                self.check_cancel()
                if self.plan.matrix.output_mode == "voltage":
                    density = None
                    voltage = float(setpoint)
                    physical_current_a = None
                    physical_voltage_v = float(self.hardware.set_voltage(
                        voltage,
                        self.plan.matrix.current_compliance_ma,
                    ))
                    condition = f"V={format_voltage_number(voltage)} V"
                else:
                    density = float(setpoint)
                    voltage = None
                    physical_voltage_v = None
                    current_ma = self.recipe.matrix_source_current_ma(channel, density)
                    physical_current_a = float(self.hardware.set_current(
                        current_ma / 1000.0,
                        self.plan.matrix.voltage_compliance_v,
                    ))
                    condition = f"J={density:g} mA/cm²"
                self._output_started = monotonic()
                self._phase(
                    "Output Stabilization",
                    f"{channel.channel} — {condition}",
                    channel,
                    channel_index,
                )
                interruptible_wait(self.plan.matrix.stabilization_ms / 1000.0, self.check_cancel)
                for gain in self.plan.gains_percent:
                    for exposure in self.plan.exposures_ms:
                        for repeat_index in range(1, self.plan.repeat + 1):
                            channel_completed += 1
                            capture = MatrixCapture(
                                measurement_type="EL",
                                channel=channel.channel,
                                sample_id=self.sample_ids[channel.channel],
                                area_cm2=channel.area_cm2,
                                output_mode=self.plan.matrix.output_mode,
                                current_density_ma_cm2=density,
                                commanded_voltage_v=voltage,
                                commanded_physical_current_a=physical_current_a,
                                commanded_physical_voltage_v=physical_voltage_v,
                                gain_percent=gain,
                                exposure_ms=exposure,
                                repeat_index=repeat_index,
                                repeat_total=self.plan.repeat,
                                channel_index=channel_index,
                                channel_total=len(self.plan.channels),
                                channel_capture_index=channel_completed,
                                channel_capture_total=channel_capture_total,
                                overall_index=self._completed + 1,
                                overall_total=self.plan.estimate().overall_captures,
                            )
                            self._capture_and_save(capture, channel, None)
                self.check_cancel()
                self.hardware.output_off()
                self._output_started = None
        finally:
            self._output_started = None
            self.hardware.output_off()
            self.hardware.clear_routing()

    def _save_dark_iv(self, channel: ChannelRecipe, rows: list[dict[str, Any]]) -> None:
        sample_id = self.sample_ids[channel.channel]
        folder = self.run_directory / f"{channel.channel}_{sanitize_filename(sample_id)}" / "DARK_IV"
        folder.mkdir(parents=True, exist_ok=True)
        polarity = self._polarity[channel.channel]
        polarity_factor = int(polarity["polarity_factor"])
        if any(row.get("PolarityFactor") != polarity_factor for row in rows):
            raise RuntimeError(
                f"{channel.channel} Dark I-V polarity metadata is inconsistent"
            )
        csv_path = folder / "dark_iv.csv"
        fields = list(rows[0]) if rows else [
            "Repeat",
            "PointIndex",
            "SetVoltageV",
            "PolarityFactor",
            "CommandedVoltageV",
            "CommandedPhysicalVoltageV",
            "MeasuredVoltageV",
            "MeasuredCurrentA",
            "MeasuredPowerW",
            "ComplianceTripped",
        ]
        with csv_path.open("w", newline="", encoding="utf-8-sig") as stream:
            writer = csv.DictWriter(stream, fieldnames=fields)
            writer.writeheader()
            writer.writerows(rows)
        metadata = {
            "MeasurementType": "DARK_IV",
            "Timestamp": self.now().isoformat(timespec="seconds"),
            "Channel": channel.channel,
            "SampleID": sample_id,
            "DeviceAreaCm2": channel.area_cm2,
            "Polarity": polarity,
            "PolarityFactor": polarity_factor,
            "VoltageColumnSemantics": {
                "SetVoltageV": "recipe_device_coordinate",
                "CommandedVoltageV": "physical_smu_command",
                "CommandedPhysicalVoltageV": "physical_smu_command",
                "MeasuredVoltageV": "smu_readback",
            },
            "Settings": self.recipe.to_dict()["dark_iv"],
            "CsvPath": str(csv_path),
            "CsvSha256": sha256_file(csv_path),
            "SnapshotSha256": self.snapshot["snapshot_sha256"],
        }
        (folder / "dark_iv.json").write_text(
            json.dumps(metadata, ensure_ascii=False, indent=2), encoding="utf-8"
        )

    def _capture_and_save(self, capture: MatrixCapture, channel: ChannelRecipe | None,
                          applicable_channels: list[str] | None) -> np.ndarray:
        self.check_cancel()
        started = monotonic()
        frame = self.hardware.capture(
            capture.exposure_ms, capture.gain_percent,
            self.recipe.el_matrix.capture_timeout_s, self.check_cancel,
        )
        self.check_cancel()
        self.report_frame(frame.image)
        readback = self.hardware.readback() if capture.measurement_type == "EL" else None
        timestamp = capture_timestamp(frame.timestamp)
        metadata = self._metadata(capture, channel, applicable_channels, frame, readback, timestamp)
        folder, stem = self._output_location(capture, channel)
        output_stem = folder / stem
        # Full-resolution Pixel CSV is deliberately deferred until verified safe
        # shutdown.  Only durable capture products are written in this method.
        metadata["PixelCsvPaths"] = {}
        metadata["PixelCsvPostprocessStatus"] = (
            "pending" if self.recipe.output.export_pixel_csv else "not_requested"
        )
        saved = save_matrix_capture(
            frame.scientific_image,
            frame.image,
            output_stem,
            metadata,
            self.recipe.output,
        )
        metadata.update(saved.file_hashes)
        append_manifest(self.run_directory / "measurement_manifest.csv", metadata)
        elapsed = monotonic() - started
        self._completed += 1
        self._eta.complete_capture(capture.exposure_ms / 1000.0, elapsed)
        self._emit_capture_progress(capture, channel)
        source = np.asarray(frame.scientific_image)
        if capture.measurement_type == "DARK":
            self._shared_dark_frames.setdefault(
                (int(capture.gain_percent), float(capture.exposure_ms)), []
            ).append(source.copy())
        return source.copy()

    def _metadata(self, capture: MatrixCapture, channel: ChannelRecipe | None,
                  applicable_channels: list[str] | None, frame: CapturedFrame,
                  readback: Any, timestamp: str) -> dict[str, Any]:
        current_a = getattr(readback, "current_a", None) if readback is not None else None
        voltage_v = getattr(readback, "voltage_v", None) if readback is not None else None
        current_ma = None if current_a is None else float(current_a) * 1000.0
        measured_density = None if current_ma is None or channel is None else current_ma / channel.area_cm2
        current_mode = capture.output_mode == "current_density"
        calculated_current_ma = (
            self.recipe.matrix_source_current_ma(
                channel, float(capture.current_density_ma_cm2)
            )
            if current_mode and channel is not None
            and capture.current_density_ma_cm2 is not None
            else None
        )
        metadata: dict[str, Any] = {
            "RecipeName": self.recipe.name, "MeasurementRunID": self.run_id,
            "MeasurementType": capture.measurement_type, "Channel": capture.channel,
            "SampleID": capture.sample_id, "DeviceArea": None if channel is None else channel.area_cm2,
            "OutputMode": capture.output_mode,
            "SetCurrentDensityMaCm2": capture.current_density_ma_cm2,
            "CommandedCurrentDensity": capture.current_density_ma_cm2,
            "CalculatedSourceCurrentA": (
                None if calculated_current_ma is None else calculated_current_ma / 1000.0
            ),
            "CalculatedSourceCurrentMa": calculated_current_ma,
            "SetVoltageV": capture.commanded_voltage_v,
            # Backward-compatible EL field; its semantic is the actual physical
            # SMU command. SetVoltageV remains the device-coordinate condition.
            "CommandedVoltageV": capture.commanded_physical_voltage_v,
            "CommandedPhysicalVoltageV": capture.commanded_physical_voltage_v,
            "CommandedPhysicalCurrentA": capture.commanded_physical_current_a,
            "CommandedPhysicalCurrentMa": (
                None
                if capture.commanded_physical_current_a is None
                else capture.commanded_physical_current_a * 1000.0
            ),
            "MeasuredCurrentA": current_a,
            "MeasuredCurrentMa": current_ma,
            "MeasuredCurrentDensityMaCm2": measured_density,
            "MeasuredCurrentDensity": measured_density,
            "MeasuredVoltageV": voltage_v,
            "MeasuredVoltage": voltage_v,
            "VoltageComplianceV": (
                self.plan.matrix.voltage_compliance_v if current_mode else None
            ),
            "VoltageCompliance": (
                self.plan.matrix.voltage_compliance_v if current_mode else None
            ),
            "CurrentComplianceMa": (
                self.plan.matrix.current_compliance_ma
                if capture.output_mode == "voltage" else None
            ),
            "Gain": capture.gain_percent, "Exposure": capture.exposure_ms,
            "RepeatIndex": capture.repeat_index, "RepeatTotal": capture.repeat_total,
            "CameraTemperature": frame.camera_temperature_c, "Timestamp": timestamp,
            "DarkScope": None, "SharedDark": False, "ApplicableChannels": [],
            "PolarityCheckEnabled": self.recipe.polarity.enabled, "PolarityCheckStatus": None,
            "Polarity": None, "PolarityFactor": None, "Jsc": None, "Voc": None,
            "PolarityTimestamp": None, "SnapshotSha256": self.snapshot["snapshot_sha256"],
            **frame.camera_metadata,
        }
        if capture.measurement_type == "DARK":
            metadata.update({"DarkScope": "SHARED_SUBSTRATE", "SharedDark": True,
                             "ApplicableChannels": applicable_channels or [],
                             "PolarityCheckEnabled": False,
                             "PolarityCheckStatus": "NOT_APPLICABLE"})
        else:
            polarity = self._polarity[capture.channel]
            metadata.update({"PolarityCheckStatus": polarity["polarity_check_status"],
                             "Polarity": polarity.get("polarity_result"),
                             "PolarityFactor": polarity["polarity_factor"],
                             "Jsc": polarity.get("Jsc"), "Voc": polarity.get("Voc"),
                             "PolarityTimestamp": polarity.get("polarity_timestamp")})
        return metadata

    def _output_location(self, capture: MatrixCapture,
                         channel: ChannelRecipe | None) -> tuple[Path, str]:
        exposure = sanitize_filename(f"{capture.exposure_ms:g}")
        if channel is None:
            return self.run_directory / "DARK", (
                f"N{capture.overall_index:06d}_SHARED_DARK_G{capture.gain_percent}_"
                f"E{exposure}_R{capture.repeat_index}"
            )
        safe_sample = sanitize_filename(self.sample_ids[channel.channel])
        if capture.output_mode == "voltage":
            electrical = "V" + sanitize_filename(
                format_voltage_number(float(capture.commanded_voltage_v))
            )
        else:
            electrical = "J" + sanitize_filename(f"{capture.current_density_ma_cm2:g}")
        return self.run_directory / f"{channel.channel}_{safe_sample}" / "EL", (
            f"N{capture.overall_index:06d}_{safe_sample}_{channel.channel}_"
            f"{electrical}_G{capture.gain_percent}_E{exposure}_R{capture.repeat_index}"
        )

    def _write_final_files_manifest(self) -> Path:
        target = self.run_directory / "final_files_manifest.csv"
        files = sorted(path for path in self.run_directory.rglob("*") if path.is_file() and path != target)
        with target.open("w", newline="", encoding="utf-8-sig") as stream:
            writer = csv.DictWriter(stream, fieldnames=("RelativePath", "AbsolutePath", "SizeBytes", "Sha256"))
            writer.writeheader()
            for path in files:
                writer.writerow({"RelativePath": str(path.relative_to(self.run_directory)),
                                 "AbsolutePath": str(path), "SizeBytes": path.stat().st_size,
                                 "Sha256": sha256_file(path)})
        return target

    def _progress_time(self) -> tuple[float, datetime]:
        remaining = min(self._last_remaining, max(0.0, self._eta.remaining_s()))
        finish = self.now() + timedelta(seconds=remaining)
        if self._last_finish is not None and finish > self._last_finish:
            finish = self._last_finish
            remaining = max(0.0, (finish - self.now()).total_seconds())
        self._last_remaining = remaining
        self._last_finish = finish
        return remaining, finish

    def _emit_capture_progress(self, capture: MatrixCapture,
                               channel: ChannelRecipe | None) -> None:
        remaining_s, finish = self._progress_time()
        self.report_progress(MatrixRuntimeProgress(
            phase="Shared Dark" if channel is None else "EL", current=self._completed,
            total=self.plan.estimate().overall_captures, channel=capture.channel,
            sample_id=capture.sample_id, channel_index=capture.channel_index,
            channel_total=capture.channel_total,
            output_mode=capture.output_mode,
            current_density_ma_cm2=capture.current_density_ma_cm2,
            commanded_voltage_v=capture.commanded_voltage_v,
            gain_percent=capture.gain_percent, exposure_ms=capture.exposure_ms,
            repeat_index=capture.repeat_index, repeat_total=capture.repeat_total,
            channel_completed=capture.channel_capture_index,
            channel_capture_total=capture.channel_capture_total,
            remaining_captures=self.plan.estimate().overall_captures - self._completed,
            remaining_time_s=remaining_s, estimated_finish=finish,
        ))

    def _phase(self, phase: str, message: str, channel: ChannelRecipe | None = None,
               channel_index: int = 0) -> None:
        remaining_s, finish = self._progress_time()
        total = self.plan.estimate().overall_captures
        self.report_progress(MatrixRuntimeProgress(
            phase=phase, current=self._completed, total=total, message=message,
            channel="" if channel is None else channel.channel,
            sample_id="" if channel is None else self.sample_ids[channel.channel],
            channel_index=channel_index, channel_total=len(self.plan.channels),
            remaining_captures=total - self._completed,
            remaining_time_s=remaining_s, estimated_finish=finish,
        ))
