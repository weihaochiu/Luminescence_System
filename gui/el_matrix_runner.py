from __future__ import annotations

"""Modular multi-channel EL Matrix runner using existing hardware authorities."""

from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path
from time import monotonic, sleep
from typing import Any, Callable, Protocol
from uuid import uuid4

from PySide6.QtGui import QImage

from .el_matrix_plan import ELMatrixPlan, MatrixCapture
from .measurement_output import (
    append_manifest,
    capture_timestamp,
    sanitize_filename,
    save_matrix_capture,
)
from .recipe_store import ChannelRecipe, Recipe


@dataclass(frozen=True)
class CapturedFrame:
    image: QImage
    timestamp: datetime
    camera_temperature_c: float | None = None
    camera_metadata: dict[str, Any] = field(default_factory=dict)


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
    current_density_ma_cm2: float | None = None
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
    def use_default_polarity(self, channel: ChannelRecipe) -> dict[str, Any]: ...
    def set_current(self, current_a: float, voltage_compliance_v: float) -> float: ...
    def readback(self) -> Any: ...
    def capture(
        self,
        exposure_ms: float,
        gain_percent: int,
        timeout_s: float,
        check_cancel: Callable[[], None],
    ) -> CapturedFrame: ...
    def output_off(self) -> None: ...
    def clear_routing(self) -> None: ...
    def safe_shutdown(self) -> None: ...


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
        matrix = plan.matrix
        self._remaining_exposure_s = sum(plan.exposure_sequence_after(0))
        self._remaining_captures = plan.estimate().overall_captures
        self._observed_overhead_s = matrix.estimated_capture_overhead_s
        self._samples = 0
        self._remaining_stabilizations = len(plan.channels) * len(matrix.current_density_ma_cm2)
        self._remaining_polarities = len(plan.channels) if plan.recipe.polarity.enabled else 0
        self._remaining_routes = len(plan.channels)
        self._dark_overhead_pending = matrix.shared_dark_enabled
        self._matrix = matrix

    def complete_capture(self, exposure_s: float, elapsed_s: float) -> None:
        overhead = max(0.0, elapsed_s - exposure_s)
        self._samples += 1
        alpha = 1.0 / min(self._samples, 20)
        self._observed_overhead_s += alpha * (overhead - self._observed_overhead_s)
        self._remaining_exposure_s = max(0.0, self._remaining_exposure_s - exposure_s)
        self._remaining_captures = max(0, self._remaining_captures - 1)

    def complete_stabilization(self) -> None:
        self._remaining_stabilizations = max(0, self._remaining_stabilizations - 1)

    def complete_polarity(self) -> None:
        self._remaining_polarities = max(0, self._remaining_polarities - 1)

    def complete_route(self) -> None:
        self._remaining_routes = max(0, self._remaining_routes - 1)

    def complete_dark_setup(self) -> None:
        self._dark_overhead_pending = False

    def remaining_s(self) -> float:
        return (
            self._remaining_exposure_s
            + self._remaining_captures * self._observed_overhead_s
            + self._remaining_stabilizations * self._matrix.stabilization_ms / 1000.0
            + self._remaining_polarities * self._matrix.estimated_polarity_duration_s
            + self._remaining_routes * self._matrix.estimated_routing_transition_s
            + (self._matrix.estimated_shared_dark_overhead_s if self._dark_overhead_pending else 0.0)
        )


class ELMatrixRunner:
    """Execute Shared Dark once, then Channel → J → Gain → Exposure → Repeat."""

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
    ) -> None:
        self.recipe = recipe
        self.plan = ELMatrixPlan(recipe)
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

    def check_cancel(self) -> None:
        if self.is_cancel_requested():
            from .measurement_worker import MeasurementCancelled
            raise MeasurementCancelled()

    def run(self) -> dict[str, Any]:
        self.run_directory.mkdir(parents=True, exist_ok=False)
        try:
            if self.recipe.el_matrix.shared_dark_enabled:
                self._run_shared_dark_once()
            for channel_index, channel in enumerate(self.plan.channels, start=1):
                self._run_channel(channel, channel_index)
            return {
                "run_id": self.run_id,
                "output_directory": str(self.run_directory),
                "captures": self._completed,
                "completed_at": self.now().isoformat(timespec="seconds"),
            }
        finally:
            self.hardware.safe_shutdown()

    def _run_shared_dark_once(self) -> None:
        self.check_cancel()
        self._phase("Shared Dark", "Preparing verified dark state")
        self.hardware.prepare_shared_dark()
        self._eta.complete_dark_setup()
        applicable = [channel.channel for channel in self.plan.channels]
        dark_total = self.plan.estimate().shared_dark_captures
        dark_index = 0
        for gain in self.plan.matrix.gains_percent:
            for exposure in self.plan.matrix.exposures_ms:
                for repeat_index in range(1, self.plan.matrix.repeat + 1):
                    dark_index += 1
                    capture = MatrixCapture(
                        "DARK", "SHARED", ", ".join(applicable), None, None,
                        gain, exposure, repeat_index, self.plan.matrix.repeat,
                        channel_capture_index=dark_index,
                        channel_capture_total=dark_total,
                        overall_index=self._completed + 1,
                        overall_total=self.plan.estimate().overall_captures,
                    )
                    self._capture_and_save(capture, None, applicable)

    def _run_channel(self, channel: ChannelRecipe, channel_index: int) -> None:
        self.check_cancel()
        self._phase("Channel Switching", f"Routing {channel.channel}", channel, channel_index)
        self.hardware.output_off()
        self.hardware.clear_routing()
        self.hardware.route_channel(channel.channel, self.check_cancel)
        self._eta.complete_route()
        if self.recipe.polarity.enabled:
            self._phase("Polarity Check", channel.channel, channel, channel_index)
            self._polarity[channel.channel] = self.hardware.run_polarity(channel, self.check_cancel)
            self._eta.complete_polarity()
        else:
            self._polarity[channel.channel] = self.hardware.use_default_polarity(channel)

        channel_capture_total = self.plan.estimate().el_per_channel
        channel_completed = 0
        try:
            for density in self.plan.matrix.current_density_ma_cm2:
                self.check_cancel()
                current_ma = self.recipe.matrix_source_current_ma(channel, density)
                self.hardware.set_current(current_ma / 1000.0, self.plan.matrix.voltage_compliance_v)
                self._phase(
                    "J Stabilization",
                    f"{channel.channel} — J={density:g} mA/cm²",
                    channel,
                    channel_index,
                )
                interruptible_wait(self.plan.matrix.stabilization_ms / 1000.0, self.check_cancel)
                self._eta.complete_stabilization()
                for gain in self.plan.matrix.gains_percent:
                    for exposure in self.plan.matrix.exposures_ms:
                        for repeat_index in range(1, self.plan.matrix.repeat + 1):
                            channel_completed += 1
                            capture = MatrixCapture(
                                "EL", channel.channel, channel.sample_id, channel.area_cm2,
                                density, gain, exposure, repeat_index, self.plan.matrix.repeat,
                                channel_index, len(self.plan.channels), channel_completed,
                                channel_capture_total, self._completed + 1,
                                self.plan.estimate().overall_captures,
                            )
                            self._capture_and_save(capture, channel, None)
        finally:
            self.hardware.output_off()
            self.hardware.clear_routing()

    def _capture_and_save(
        self,
        capture: MatrixCapture,
        channel: ChannelRecipe | None,
        applicable_channels: list[str] | None,
    ) -> None:
        self.check_cancel()
        started = monotonic()
        frame = self.hardware.capture(
            capture.exposure_ms,
            capture.gain_percent,
            self.recipe.camera.capture_timeout_s,
            self.check_cancel,
        )
        self.report_frame(frame.image)
        readback = self.hardware.readback() if capture.measurement_type == "EL" else None
        timestamp = capture_timestamp(frame.timestamp)
        metadata = self._metadata(capture, channel, applicable_channels, frame, readback, timestamp)
        folder, stem = self._output_location(capture, channel)
        saved = save_matrix_capture(frame.image, folder / stem, metadata)
        metadata.update({
            "RawTiffPath": str(saved.tiff_path),
            "AnnotatedJpegPath": str(saved.jpeg_path),
        })
        append_manifest(self.run_directory / "measurement_manifest.csv", metadata)
        elapsed = monotonic() - started
        self._completed += 1
        self._eta.complete_capture(capture.exposure_ms / 1000.0, elapsed)
        self._emit_capture_progress(capture, channel)

    def _metadata(
        self,
        capture: MatrixCapture,
        channel: ChannelRecipe | None,
        applicable_channels: list[str] | None,
        frame: CapturedFrame,
        readback: Any,
        timestamp: str,
    ) -> dict[str, Any]:
        current_a = getattr(readback, "current_a", None) if readback is not None else None
        voltage_v = getattr(readback, "voltage_v", None) if readback is not None else None
        current_ma = None if current_a is None else float(current_a) * 1000.0
        measured_density = (
            None if current_ma is None or channel is None else current_ma / channel.area_cm2
        )
        metadata: dict[str, Any] = {
            "RecipeName": self.recipe.name,
            "MeasurementRunID": self.run_id,
            "MeasurementType": capture.measurement_type,
            "Channel": capture.channel,
            "SampleID": capture.sample_id,
            "DeviceArea": None if channel is None else channel.area_cm2,
            "CommandedCurrentDensity": capture.current_density_ma_cm2,
            "CalculatedSourceCurrentMa": (
                None if channel is None else self.recipe.matrix_source_current_ma(
                    channel, float(capture.current_density_ma_cm2)
                )
            ),
            "MeasuredCurrentMa": current_ma,
            "MeasuredCurrentDensity": measured_density,
            "MeasuredVoltage": voltage_v,
            "VoltageCompliance": self.plan.matrix.voltage_compliance_v,
            "Gain": capture.gain_percent,
            "Exposure": capture.exposure_ms,
            "RepeatIndex": capture.repeat_index,
            "RepeatTotal": capture.repeat_total,
            "CameraTemperature": frame.camera_temperature_c,
            "Timestamp": timestamp,
            "DarkScope": None,
            "SharedDark": False,
            "ApplicableChannels": [],
            "PolarityCheckEnabled": self.recipe.polarity.enabled,
            "PolarityCheckStatus": None,
            "Polarity": None,
            "PolarityFactor": None,
            "Jsc": None,
            "Voc": None,
            "PolarityTimestamp": None,
            **frame.camera_metadata,
        }
        if capture.measurement_type == "DARK":
            metadata.update({
                "DarkScope": "SHARED_SUBSTRATE",
                "SharedDark": True,
                "ApplicableChannels": applicable_channels or [],
                "PolarityCheckEnabled": False,
                "PolarityCheckStatus": "NOT_APPLICABLE",
            })
        else:
            polarity = self._polarity.get(capture.channel, {})
            metadata.update({
                "PolarityCheckEnabled": self.recipe.polarity.enabled,
                "PolarityCheckStatus": polarity.get("polarity_check_status", "SKIPPED"),
                "Polarity": polarity.get("polarity_result"),
                "PolarityFactor": polarity.get("polarity_factor"),
                "Jsc": polarity.get("Jsc"),
                "Voc": polarity.get("Voc"),
                "PolarityTimestamp": polarity.get("polarity_timestamp"),
            })
        return metadata

    def _output_location(
        self, capture: MatrixCapture, channel: ChannelRecipe | None
    ) -> tuple[Path, str]:
        exposure = sanitize_filename(f"{capture.exposure_ms:g}")
        if channel is None:
            folder = self.run_directory / "DARK"
            stem = (
                f"N{capture.overall_index:06d}_SHARED_DARK_G{capture.gain_percent}_"
                f"E{exposure}_R{capture.repeat_index}"
            )
        else:
            safe_sample = sanitize_filename(channel.sample_id)
            folder = self.run_directory / f"{channel.channel}_{safe_sample}" / "EL"
            density = sanitize_filename(f"{capture.current_density_ma_cm2:g}")
            stem = (
                f"N{capture.overall_index:06d}_{safe_sample}_{channel.channel}_"
                f"J{density}_G{capture.gain_percent}_"
                f"E{exposure}_R{capture.repeat_index}"
            )
        return folder, stem

    def _emit_capture_progress(
        self, capture: MatrixCapture, channel: ChannelRecipe | None
    ) -> None:
        remaining = self.plan.estimate().overall_captures - self._completed
        remaining_s = self._eta.remaining_s()
        self.report_progress(MatrixRuntimeProgress(
            phase="Shared Dark" if channel is None else "EL",
            current=self._completed,
            total=self.plan.estimate().overall_captures,
            channel=capture.channel,
            sample_id=capture.sample_id,
            channel_index=capture.channel_index,
            channel_total=capture.channel_total,
            current_density_ma_cm2=capture.current_density_ma_cm2,
            gain_percent=capture.gain_percent,
            exposure_ms=capture.exposure_ms,
            repeat_index=capture.repeat_index,
            repeat_total=capture.repeat_total,
            channel_completed=capture.channel_capture_index,
            channel_capture_total=capture.channel_capture_total,
            remaining_captures=remaining,
            remaining_time_s=remaining_s,
            estimated_finish=self.now() + timedelta(seconds=remaining_s),
        ))

    def _phase(
        self,
        phase: str,
        message: str,
        channel: ChannelRecipe | None = None,
        channel_index: int = 0,
    ) -> None:
        remaining_s = self._eta.remaining_s()
        total = self.plan.estimate().overall_captures
        self.report_progress(MatrixRuntimeProgress(
            phase=phase,
            current=self._completed,
            total=total,
            message=message,
            channel="" if channel is None else channel.channel,
            sample_id="" if channel is None else channel.sample_id,
            channel_index=channel_index,
            channel_total=len(self.plan.channels),
            remaining_captures=total - self._completed,
            remaining_time_s=remaining_s,
            estimated_finish=self.now() + timedelta(seconds=remaining_s),
        ))
