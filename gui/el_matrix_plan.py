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

    def __init__(
        self,
        recipe: Recipe,
        *,
        sample_ids: dict[str, str] | None = None,
        hdr_settings: object | None = None,
        hdr_profile: object | None = None,
        global_safety: object | None = None,
    ) -> None:
        if recipe.hdr.enabled and hdr_settings is None and hdr_profile is None:
            raise ValueError("HDR Recipe requires global HDR settings or a locked T0 Profile")
        errors = recipe.validate(hdr_settings, global_safety)
        if errors:
            raise ValueError("Invalid EL Matrix Recipe: " + "; ".join(errors))
        self.recipe = recipe
        self.channels = tuple(recipe.enabled_channels())
        self.matrix = recipe.el_matrix
        self.sample_ids = dict(sample_ids or {})
        self.hdr_settings = hdr_settings
        self.hdr_profile = hdr_profile
        axes = effective_matrix_capture_axes(
            recipe, hdr_settings, hdr_profile=hdr_profile
        )
        self.gains_percent = axes.gains_percent
        self.exposures_ms = axes.exposures_ms
        self.repeat = axes.repeat

    def capture_counts(self) -> dict[str, int]:
        combination = len(self.gains_percent) * len(self.exposures_ms) * self.repeat
        dark = combination if self.matrix.dark_frame_enabled else 0
        per_channel = len(self.matrix.current_density_ma_cm2) * combination
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
            * len(self.matrix.current_density_ma_cm2)
            * len(self.channels)
        )
        exposure_time_s = dark_exposure_s + el_exposure_s
        captures_per_j = len(self.gains_percent) * len(self.exposures_ms) * self.repeat
        output_on_per_j_s = (
            self.matrix.stabilization_ms / 1000.0
            + exposure_sum_s * len(self.gains_percent) * self.repeat
            + captures_per_j * self.matrix.estimated_capture_overhead_s
        )
        stabilization_s = (
            len(self.channels)
            * len(self.matrix.current_density_ma_cm2)
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
            output_on_per_j_s=output_on_per_j_s,
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
                            "DARK", "SHARED", applicable, None, None,
                            int(gain), float(exposure), repeat_index, self.repeat,
                            channel_capture_index=dark_index,
                            channel_capture_total=estimate.shared_dark_captures,
                            overall_index=overall,
                            overall_total=estimate.overall_captures,
                        )
        for channel_index, channel in enumerate(self.channels, start=1):
            channel_capture_index = 0
            for density in self.matrix.current_density_ma_cm2:
                for gain in self.gains_percent:
                    for exposure in self.exposures_ms:
                        for repeat_index in range(1, self.repeat + 1):
                            overall += 1
                            channel_capture_index += 1
                            yield MatrixCapture(
                                "EL", channel.channel,
                                self.sample_ids.get(channel.channel, ""),
                                channel.area_cm2,
                                float(density), int(gain), float(exposure), repeat_index,
                                self.repeat, channel_index, len(self.channels),
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
