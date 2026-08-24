from __future__ import annotations

"""Pure EL Matrix planning, ordering, capture counts, and ETA calculations."""

from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Iterable, Iterator

from .recipe_store import ChannelRecipe, Recipe
from .measurement_execution_plan import effective_matrix_capture_axes


@dataclass(frozen=True)
class MatrixCapture:
    measurement_type: str
    channel: str
    sample_id: str
    area_cm2: float | None
    output_mode: str | None
    current_density_ma_cm2: float | None
    commanded_voltage_v: float | None
    commanded_physical_current_a: float | None
    commanded_physical_voltage_v: float | None
    gain_percent: int
    exposure_ms: float
    repeat_index: int
    repeat_total: int
    channel_index: int = 0
    channel_total: int = 0
    channel_capture_index: int = 0
    channel_capture_total: int = 0
    overall_index: int = 0
    overall_total: int = 0


@dataclass(frozen=True)
class MatrixEstimate:
    shared_dark_captures: int
    el_per_channel: int
    total_el_captures: int
    overall_captures: int
    exposure_time_s: float
    total_time_s: float
    output_on_per_setpoint_s: float
    dark_iv_per_channel_s: float
    estimated_finish: datetime

    @property
    def output_on_per_j_s(self) -> float:
        """Backward-compatible name for callers predating voltage mode."""

        return self.output_on_per_setpoint_s


class ELMatrixPlan:
    """Immutable logical plan. Dark is deliberately outside the channel loop."""

    def __init__(
        self,
        recipe: Recipe,
        *,
        sample_ids: dict[str, str] | None = None,
        global_safety: object | None = None,
    ) -> None:
        errors = recipe.validate(global_safety)
        if errors:
            raise ValueError("Invalid EL Matrix Recipe: " + "; ".join(errors))
        self.recipe = recipe
        self.channels = tuple(recipe.enabled_channels())
        self.matrix = recipe.el_matrix
        self.sample_ids = dict(sample_ids or {})
        axes = effective_matrix_capture_axes(recipe)
        self.gains_percent = axes.gains_percent
        self.exposures_ms = axes.exposures_ms
        self.repeat = axes.repeat
        self.electrical_setpoints = self.matrix.active_electrical_setpoints()

    def capture_counts(self) -> dict[str, int]:
        combination = len(self.gains_percent) * len(self.exposures_ms) * self.repeat
        dark = combination if self.matrix.dark_frame_enabled else 0
        per_channel = len(self.electrical_setpoints) * combination
        total_el = len(self.channels) * per_channel
        return {
            "shared_dark": dark,
            "el_per_channel": per_channel,
            "total_el": total_el,
            "overall": dark + total_el,
        }

    def estimate(self, now: datetime | None = None) -> MatrixEstimate:
        now = now or datetime.now().astimezone()
        counts = self.capture_counts()
        exposure_sum_s = sum(self.exposures_ms) / 1000.0
        dark_exposure_s = (
            exposure_sum_s * len(self.gains_percent) * self.repeat
            if self.matrix.dark_frame_enabled else 0.0
        )
        el_exposure_s = (
            exposure_sum_s
            * len(self.gains_percent)
            * self.repeat
            * len(self.electrical_setpoints)
            * len(self.channels)
        )
        exposure_time_s = dark_exposure_s + el_exposure_s
        captures_per_setpoint = (
            len(self.gains_percent) * len(self.exposures_ms) * self.repeat
        )
        output_on_per_setpoint_s = (
            self.matrix.stabilization_ms / 1000.0
            + exposure_sum_s * len(self.gains_percent) * self.repeat
            + captures_per_setpoint * self.matrix.estimated_capture_overhead_s
        )
        stabilization_s = (
            len(self.channels)
            * len(self.electrical_setpoints)
            * self.matrix.stabilization_ms
            / 1000.0
        )
        polarity_s = (
            len(self.channels) * self.matrix.estimated_polarity_duration_s
            if self.recipe.polarity.enabled else 0.0
        )
        routing_s = (
            len(self.channels)
            * (1 + int(self.recipe.polarity.enabled))
            * self.matrix.estimated_routing_transition_s
        )
        dark_iv_s = (
            len(self.channels) * self.recipe.dark_iv_estimated_time_s()
            if self.recipe.dark_iv.enabled else 0.0
        )
        shared_setup_s = (
            self.matrix.estimated_shared_dark_overhead_s
            if self.matrix.dark_frame_enabled else 0.0
        )
        total_time_s = (
            exposure_time_s
            + counts["overall"] * self.matrix.estimated_capture_overhead_s
            + stabilization_s
            + polarity_s
            + routing_s
            + dark_iv_s
            + shared_setup_s
        )
        return MatrixEstimate(
            shared_dark_captures=counts["shared_dark"],
            el_per_channel=counts["el_per_channel"],
            total_el_captures=counts["total_el"],
            overall_captures=counts["overall"],
            exposure_time_s=exposure_time_s,
            total_time_s=total_time_s,
            output_on_per_setpoint_s=output_on_per_setpoint_s,
            dark_iv_per_channel_s=self.recipe.dark_iv_estimated_time_s(),
            estimated_finish=now + timedelta(seconds=total_time_s),
        )

    def captures(self) -> Iterator[MatrixCapture]:
        estimate = self.estimate()
        overall = 0
        applicable = ", ".join(channel.channel for channel in self.channels)
        if self.matrix.dark_frame_enabled:
            dark_index = 0
            for gain in self.gains_percent:
                for exposure in self.exposures_ms:
                    for repeat_index in range(1, self.repeat + 1):
                        overall += 1
                        dark_index += 1
                        yield MatrixCapture(
                            measurement_type="DARK",
                            channel="SHARED",
                            sample_id=applicable,
                            area_cm2=None,
                            output_mode=None,
                            current_density_ma_cm2=None,
                            commanded_voltage_v=None,
                            commanded_physical_current_a=None,
                            commanded_physical_voltage_v=None,
                            gain_percent=int(gain),
                            exposure_ms=float(exposure),
                            repeat_index=repeat_index,
                            repeat_total=self.repeat,
                            channel_capture_index=dark_index,
                            channel_capture_total=estimate.shared_dark_captures,
                            overall_index=overall,
                            overall_total=estimate.overall_captures,
                        )
        for channel_index, channel in enumerate(self.channels, start=1):
            channel_capture_index = 0
            for setpoint in self.electrical_setpoints:
                for gain in self.gains_percent:
                    for exposure in self.exposures_ms:
                        for repeat_index in range(1, self.repeat + 1):
                            overall += 1
                            channel_capture_index += 1
                            yield MatrixCapture(
                                measurement_type="EL",
                                channel=channel.channel,
                                sample_id=self.sample_ids.get(channel.channel, ""),
                                area_cm2=channel.area_cm2,
                                output_mode=self.matrix.output_mode,
                                current_density_ma_cm2=(
                                    float(setpoint)
                                    if self.matrix.output_mode == "current_density"
                                    else None
                                ),
                                commanded_voltage_v=(
                                    float(setpoint)
                                    if self.matrix.output_mode == "voltage"
                                    else None
                                ),
                                commanded_physical_current_a=None,
                                commanded_physical_voltage_v=None,
                                gain_percent=int(gain),
                                exposure_ms=float(exposure),
                                repeat_index=repeat_index,
                                repeat_total=self.repeat,
                                channel_index=channel_index,
                                channel_total=len(self.channels),
                                channel_capture_index=channel_capture_index,
                                channel_capture_total=estimate.el_per_channel,
                                overall_index=overall,
                                overall_total=estimate.overall_captures,
                            )

    def exposure_sequence_after(self, completed: int) -> Iterable[float]:
        for capture in self.captures():
            if capture.overall_index > completed:
                yield capture.exposure_ms / 1000.0


def format_duration(seconds: float) -> str:
    total = max(0, int(round(seconds)))
    hours, remainder = divmod(total, 3600)
    minutes, secs = divmod(remainder, 60)
    return f"{hours:02d}:{minutes:02d}:{secs:02d}" if hours else f"{minutes:02d}:{secs:02d}"


def format_finish_time(value: datetime, now: datetime | None = None) -> str:
    now = now or datetime.now().astimezone()
    return value.strftime("%H:%M:%S" if value.date() == now.date() else "%Y-%m-%d %H:%M:%S")
