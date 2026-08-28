from __future__ import annotations

from .models import CaptureCondition, CapturePlan, RunMode


FULL_GAINS = (100, 200, 300, 400, 500)
FULL_EXPOSURES_MS = (50, 100, 200, 500, 1000, 2000, 5000, 10000, 15000)


def build_capture_plan(
    mode: RunMode | str,
    *,
    profile: dict[str, object] | None = None,
    gains: tuple[int, ...] | None = None,
    exposures_ms: tuple[float, ...] | None = None,
    light_repeats: int | None = None,
    dark_repeats: int | None = None,
    settling_frames: int = 2,
    adaptive_early_stop: bool = True,
) -> CapturePlan:
    selected = RunMode(mode)
    if selected is RunMode.FULL:
        chosen_gains = gains or FULL_GAINS
        chosen_exposures = exposures_ms or FULL_EXPOSURES_MS
        light = 5 if light_repeats is None else light_repeats
        dark = 5 if dark_repeats is None else dark_repeats
    elif selected is RunMode.PILOT:
        chosen_gains = gains or (100,)
        chosen_exposures = exposures_ms or FULL_EXPOSURES_MS
        light = 3 if light_repeats is None else light_repeats
        dark = 0 if dark_repeats is None else dark_repeats
    else:
        chosen_gains = gains or (100,)
        chosen_exposures = exposures_ms or _quick_exposures(profile)
        light = 3 if light_repeats is None else light_repeats
        dark = 3 if dark_repeats is None else dark_repeats
    if not chosen_gains or not chosen_exposures:
        raise ValueError("Capture plan requires at least one Gain and Exposure")
    if any(int(value) <= 0 for value in chosen_gains):
        raise ValueError("Gain values must be positive")
    if any(float(value) <= 0 for value in chosen_exposures):
        raise ValueError("Exposure values must be positive")
    if light <= 0 or dark < 0 or settling_frames < 0:
        raise ValueError("Repeat and settling-frame counts are invalid")
    conditions = tuple(
        CaptureCondition(int(gain), float(exposure))
        for gain in chosen_gains
        for exposure in sorted(set(float(item) for item in chosen_exposures))
    )
    return CapturePlan(selected, conditions, int(light), int(dark), int(settling_frames), bool(adaptive_early_stop))


def _quick_exposures(profile: dict[str, object] | None) -> tuple[float, ...]:
    if not profile:
        return (50, 200, 1000, 2000, 5000, 10000)
    limits = profile.get("recommended_exposure_limits")
    if isinstance(limits, dict):
        low = float(limits.get("minimum_ms", 50))
        high = float(limits.get("maximum_ms", 10000))
        if high > low:
            values = [low * ((high / low) ** (index / 5)) for index in range(6)]
            return tuple(round(value, 3) for value in values)
    return (50, 200, 1000, 2000, 5000, 10000)


def capture_timeout_s(exposure_ms: float, settling_frames: int = 0, overhead_s: float = 3.0) -> float:
    """Timeout covers every discarded frame plus the accepted frame."""
    exposure_s = max(0.0, float(exposure_ms) / 1000.0)
    return max(5.0, exposure_s * (max(0, int(settling_frames)) + 1) * 1.5 + float(overhead_s))
