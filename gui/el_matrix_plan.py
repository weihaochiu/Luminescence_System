from __future__ import annotations

"""Pure EL Matrix planning, ordering, capture counts, and ETA calculations."""

from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Iterable, Iterator

from .recipe_store import ChannelRecipe, Recipe


@dataclass(frozen=True)
class MatrixCapture:
    measurement_type: str
    channel: str
    sample_id: str
    area_cm2: float | None
    current_density_ma_cm2: float | None
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
    output_on_per_j_s: float
    dark_iv_per_channel_s: float
    estimated_finish: datetime


class ELMatrixPlan:
    """Immutable logical plan. Dark is deliberately outside the channel loop."""

    def __init__(self, recipe: Recipe) -> None:
        errors = recipe.validate()
        if errors:
            raise ValueError("Invalid EL Matrix Recipe: " + "; ".join(errors))
        self.recipe = recipe
        self.channels = tuple(recipe.enabled_channels())
        self.matrix = recipe.el_matrix

    def estimate(self, now: datetime | None = None) -> MatrixEstimate:
        now = now or datetime.now().astimezone()
        counts = self.recipe.matrix_capture_counts()
        exposure_sum_s = sum(self.matrix.exposures_ms) / 1000.0
        dark_exposure_s = (
            exposure_sum_s * len(self.matrix.gains_percent) * self.matrix.repeat
            if self.matrix.shared_dark_enabled else 0.0
        )
        el_exposure_s = (
            exposure_sum_s
            * len(self.matrix.gains_percent)
            * self.matrix.repeat
            * len(self.matrix.current_density_ma_cm2)
            * len(self.channels)
        )
        exposure_time_s = dark_exposure_s + el_exposure_s
        total_time_s = self.recipe.matrix_estimated_time_s()
        return MatrixEstimate(
            shared_dark_captures=counts["shared_dark"],
            el_per_channel=counts["el_per_channel"],
            total_el_captures=counts["total_el"],
            overall_captures=counts["overall"],
            exposure_time_s=exposure_time_s,
            total_time_s=total_time_s,
            output_on_per_j_s=self.recipe.matrix_output_on_time_s(),
            dark_iv_per_channel_s=self.recipe.dark_iv_estimated_time_s(),
            estimated_finish=now + timedelta(seconds=total_time_s),
        )

    def captures(self) -> Iterator[MatrixCapture]:
        estimate = self.estimate()
        overall = 0
        applicable = ", ".join(channel.channel for channel in self.channels)
        if self.matrix.shared_dark_enabled:
            dark_index = 0
            for gain in self.matrix.gains_percent:
                for exposure in self.matrix.exposures_ms:
                    for repeat_index in range(1, self.matrix.repeat + 1):
                        overall += 1
                        dark_index += 1
                        yield MatrixCapture(
                            "DARK", "SHARED", applicable, None, None,
                            int(gain), float(exposure), repeat_index, self.matrix.repeat,
                            channel_capture_index=dark_index,
                            channel_capture_total=estimate.shared_dark_captures,
                            overall_index=overall,
                            overall_total=estimate.overall_captures,
                        )
        for channel_index, channel in enumerate(self.channels, start=1):
            channel_capture_index = 0
            for density in self.matrix.current_density_ma_cm2:
                for gain in self.matrix.gains_percent:
                    for exposure in self.matrix.exposures_ms:
                        for repeat_index in range(1, self.matrix.repeat + 1):
                            overall += 1
                            channel_capture_index += 1
                            yield MatrixCapture(
                                "EL", channel.channel, channel.sample_id, channel.area_cm2,
                                float(density), int(gain), float(exposure), repeat_index,
                                self.matrix.repeat, channel_index, len(self.channels),
                                channel_capture_index, estimate.el_per_channel,
                                overall, estimate.overall_captures,
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
