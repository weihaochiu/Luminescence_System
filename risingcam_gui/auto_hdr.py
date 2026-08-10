from __future__ import annotations

"""Quantitative automatic-HDR planning and image fusion.

This module intentionally has no Qt, camera-SDK, or SMU dependency.  The future
measurement state machine only needs to provide probe/capture arrays and apply
the returned exposure plan.  Keeping the numerical path here prevents display
tone mapping from leaking into EL-I or k-mapping data.
"""

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Sequence

import numpy as np


QUALITY_PRESETS = {
    "fast": {"max_exposures": 3, "frames_per_exposure": 1},
    "standard": {"max_exposures": 5, "frames_per_exposure": 3},
    "high": {"max_exposures": 7, "frames_per_exposure": 5},
}


@dataclass
class DiskFrameGroup:
    """Raw frames spooled to disk so a complete HDR bracket is not kept in RAM."""

    directory: Path
    prefix: str
    paths: list[Path] = field(default_factory=list)

    def append(self, frame: np.ndarray) -> None:
        self.directory.mkdir(parents=True, exist_ok=True)
        path = self.directory / f"{self.prefix}_f{len(self.paths) + 1:03d}.npy"
        np.save(path, np.asarray(frame), allow_pickle=False)
        self.paths.append(path)

    def frames(self) -> list[np.ndarray]:
        return [np.load(path, allow_pickle=False) for path in self.paths]

    def cleanup(self) -> None:
        for path in self.paths:
            path.unlink(missing_ok=True)
        try:
            self.directory.rmdir()
        except OSError:
            pass


class HDRPlanningError(ValueError):
    """Raised when safe quantitative HDR settings cannot be constructed."""


@dataclass
class HDRRecipe:
    mode: str = "auto"  # off / auto / manual
    quality: str = "standard"
    max_exposure_segments: int = 4
    frames_per_exposure_value: int = 3
    gain_mode: str = "auto_lock"  # auto_lock / manual_lock
    locked_gain_percent: int = 10
    min_exposure_ms: float = 0.030
    max_exposure_ms: float = 15000.0
    manual_exposures_ms: list[float] = field(default_factory=lambda: [1.0, 100.0, 10000.0])
    exposure_ratio: float = 4.0
    saturation_dn: float = 245.0
    target_high_dn: float = 220.0
    low_signal_sigma: float = 5.0
    max_point_time_s: float = 60.0
    save_source_exposures: bool = True
    save_linear_float32_tiff: bool = True
    save_preview_png: bool = True
    early_stop_on_severe_overexposure: bool = True
    severe_saturation_fraction: float = 0.05
    exclude_hot_pixels: bool = True

    @property
    def enabled(self) -> bool:
        return self.mode in {"auto", "manual"}

    @property
    def preset(self) -> dict[str, int]:
        return QUALITY_PRESETS.get(self.quality, QUALITY_PRESETS["standard"])

    @property
    def frames_per_exposure(self) -> int:
        return self.frames_per_exposure_value

    @property
    def max_exposures(self) -> int:
        return self.max_exposure_segments


@dataclass(frozen=True)
class ExposurePlan:
    exposures_ms: tuple[float, ...]
    gain_percent: int
    frames_per_exposure: int
    frame_interval_s: float
    mode: str
    estimated_point_time_s: float


@dataclass
class HDRResult:
    linear_dn_per_s: np.ndarray
    source_index: np.ndarray
    valid_mask: np.ndarray
    saturated_all_mask: np.ndarray
    exposures_ms: tuple[float, ...]


@dataclass(frozen=True)
class ExposureDecision:
    exposure_ms: float
    saturation_fraction: float
    p99_9_dn: float
    severe_overexposure: bool
    action: str  # continue / terminate
    reason: str = ""


@dataclass
class ExposureSequenceResult:
    planned_exposures_ms: tuple[float, ...]
    captured_exposures_ms: tuple[float, ...]
    valid_exposures_ms: tuple[float, ...]
    excluded_exposures_ms: tuple[float, ...]
    skipped_exposures_ms: tuple[float, ...]
    frame_groups: list[list[np.ndarray] | DiskFrameGroup]
    excluded_judgment_frames: list[tuple[float, np.ndarray]]
    decisions: list[ExposureDecision]
    early_termination: dict[str, Any] | None = None

    def to_summary(self) -> dict[str, Any]:
        return {
            "planned_exposures_ms": list(self.planned_exposures_ms),
            "captured_exposures_ms": list(self.captured_exposures_ms),
            "valid_exposures_ms": list(self.valid_exposures_ms),
            "excluded_exposures_ms": list(self.excluded_exposures_ms),
            "skipped_exposures_ms": list(self.skipped_exposures_ms),
            "decisions": [
                {
                    "exposure_ms": item.exposure_ms,
                    "saturation_fraction": item.saturation_fraction,
                    "p99_9_dn": item.p99_9_dn,
                    "severe_overexposure": item.severe_overexposure,
                    "action": item.action,
                    "reason": item.reason,
                }
                for item in self.decisions
            ],
            "early_termination": self.early_termination,
        }


def config_from_settings(settings: object, enabled: bool = True) -> HDRRecipe:
    """Adapt application-wide settings to the dependency-free HDR engine."""
    return HDRRecipe(
        mode="auto" if enabled else "off",
        max_exposure_segments=int(settings.max_exposure_segments),
        frames_per_exposure_value=int(settings.frames_per_exposure),
        gain_mode=str(settings.gain_mode),
        locked_gain_percent=int(settings.locked_gain_percent),
        min_exposure_ms=float(settings.min_exposure_ms),
        max_exposure_ms=float(settings.max_exposure_ms),
        exposure_ratio=float(settings.exposure_ratio),
        saturation_dn=float(settings.saturation_dn),
        target_high_dn=float(settings.target_high_dn),
        low_signal_sigma=float(settings.minimum_snr),
        max_point_time_s=float(settings.max_point_time_s),
        save_source_exposures=bool(settings.save_source_exposures),
        save_linear_float32_tiff=bool(settings.save_linear_float32_tiff),
        save_preview_png=bool(settings.save_preview_png),
        early_stop_on_severe_overexposure=bool(settings.early_stop_on_severe_overexposure),
        severe_saturation_fraction=float(settings.severe_saturation_fraction),
        exclude_hot_pixels=bool(settings.exclude_hot_pixels),
    )


def config_from_recipe(recipe: object, settings: object | None = None) -> HDRRecipe:
    """Compatibility adapter; new code must pass the global HDR settings."""
    if settings is None:
        raise HDRPlanningError("HDR 詳細參數已移至「設定 → HDR」，必須提供 HDR 系統設定")
    return config_from_settings(settings, enabled=bool(getattr(recipe.hdr, "enabled", False)))


def parse_exposure_list(text: str) -> list[float]:
    tokens = text.replace(",", " ").replace(";", " ").split()
    values = sorted({float(token) for token in tokens})
    if not values or any(not np.isfinite(value) or value <= 0 for value in values):
        raise HDRPlanningError("HDR 曝光列表必須包含至少一個大於 0 的有限數值")
    return values


def build_exposure_bracket(
    minimum_ms: float,
    maximum_ms: float,
    exposure_ratio: float = 4.0,
    max_exposures: int = 5,
) -> list[float]:
    """Return a bounded geometric bracket including both useful endpoints."""
    if minimum_ms <= 0 or maximum_ms <= 0 or maximum_ms < minimum_ms:
        raise HDRPlanningError("HDR 最短／最長曝光範圍無效")
    if exposure_ratio <= 1:
        raise HDRPlanningError("HDR 曝光倍率必須大於 1")
    if max_exposures < 1:
        raise HDRPlanningError("HDR 至少需要一段曝光")
    if np.isclose(minimum_ms, maximum_ms) or max_exposures == 1:
        return [float(minimum_ms)]

    required = int(np.ceil(np.log(maximum_ms / minimum_ms) / np.log(exposure_ratio))) + 1
    count = max(2, min(max_exposures, required))
    values = np.geomspace(minimum_ms, maximum_ms, count)
    return [float(round(value, 6)) for value in values]


def estimate_auto_bounds(
    high_probe: np.ndarray,
    low_probe: np.ndarray,
    dark_probe: np.ndarray,
    high_probe_exposure_ms: float,
    low_probe_exposure_ms: float,
    config: HDRRecipe,
) -> tuple[float, float, dict[str, float]]:
    """Estimate global short/long exposures from high/low setpoint probes.

    A percentile is used instead of the brightest pixel so hot pixels do not
    force an unnecessarily short exposure.  The low bound uses median signal
    relative to robust dark-frame sigma.
    """
    high = _as_luminance(high_probe)
    low = _as_luminance(low_probe)
    dark = _as_luminance(dark_probe)
    if high.shape != dark.shape or low.shape != dark.shape:
        raise HDRPlanningError("預掃描影像與 Dark frame 的尺寸不一致")
    if high_probe_exposure_ms <= 0 or low_probe_exposure_ms <= 0:
        raise HDRPlanningError("預掃描曝光時間必須大於 0")

    dark_level = float(np.median(dark))
    dark_sigma = _robust_sigma(dark)
    high_level = float(np.percentile(high, 99.9))
    usable_high = max(high_level - dark_level, 1e-6)
    target_signal = max(config.target_high_dn - dark_level, 1.0)
    short_ms = high_probe_exposure_ms * target_signal / usable_high
    short_ms = float(np.clip(short_ms, config.min_exposure_ms, config.max_exposure_ms))

    low_signal = float(np.median(low - dark))
    required_low_signal = max(config.low_signal_sigma * dark_sigma, 1.0)
    if low_signal <= 0:
        long_ms = config.max_exposure_ms
    else:
        long_ms = low_probe_exposure_ms * required_low_signal / low_signal
    long_ms = float(np.clip(long_ms, short_ms, config.max_exposure_ms))
    diagnostics = {
        "dark_median_dn": dark_level,
        "dark_sigma_dn": dark_sigma,
        "high_p99_9_dn": high_level,
        "low_median_signal_dn": low_signal,
        "required_low_signal_dn": required_low_signal,
    }
    return short_ms, long_ms, diagnostics


def make_exposure_plan(
    config: HDRRecipe,
    gain_percent: int,
    frame_interval_s: float,
    auto_bounds_ms: tuple[float, float] | None = None,
) -> ExposurePlan:
    if not config.enabled:
        raise HDRPlanningError("HDR 模式目前為關閉")
    if config.quality not in QUALITY_PRESETS:
        raise HDRPlanningError("未知的 HDR 品質模式")
    if gain_percent < 0:
        raise HDRPlanningError("Gain 不可小於 0")
    if frame_interval_s < 0:
        raise HDRPlanningError("Frame interval 不可小於 0")

    if config.mode == "manual":
        exposures = sorted({float(value) for value in config.manual_exposures_ms})
    elif config.mode == "auto":
        if auto_bounds_ms is None:
            exposures = build_exposure_bracket(
                config.min_exposure_ms,
                config.max_exposure_ms,
                config.exposure_ratio,
                config.max_exposures,
            )
        else:
            exposures = build_exposure_bracket(
                max(config.min_exposure_ms, auto_bounds_ms[0]),
                min(config.max_exposure_ms, auto_bounds_ms[1]),
                config.exposure_ratio,
                config.max_exposures,
            )
    else:
        raise HDRPlanningError("HDR 模式必須是 auto 或 manual")

    if not exposures or any(value <= 0 for value in exposures):
        raise HDRPlanningError("HDR 曝光列表無效")
    if exposures[0] < config.min_exposure_ms or exposures[-1] > config.max_exposure_ms:
        raise HDRPlanningError("HDR 曝光列表超出允許範圍")

    frames = config.frames_per_exposure
    total_s = frames * sum(exposures) / 1000.0
    total_frames = frames * len(exposures)
    total_s += max(0, total_frames - 1) * frame_interval_s
    if total_s > config.max_point_time_s + 1e-9:
        raise HDRPlanningError(
            f"HDR 曝光組合預估 {total_s:.1f} s，超過每點上限 {config.max_point_time_s:.1f} s"
        )
    return ExposurePlan(
        exposures_ms=tuple(exposures),
        gain_percent=int(gain_percent),
        frames_per_exposure=frames,
        frame_interval_s=float(frame_interval_s),
        mode=config.mode,
        estimated_point_time_s=total_s,
    )


def judge_exposure_frame(
    frame: np.ndarray,
    exposure_ms: float,
    saturation_dn: float = 245.0,
    severe_saturation_fraction: float = 0.05,
    roi_mask: np.ndarray | None = None,
    hot_pixel_mask: np.ndarray | None = None,
) -> ExposureDecision:
    """Classify the first frame of an exposure segment.

    Only the effective device ROI participates. Known hot pixels can be
    excluded so one defective pixel never suppresses useful longer exposures.
    """
    image = _as_luminance(frame)
    valid = np.ones(image.shape, dtype=bool)
    if roi_mask is not None:
        roi = np.asarray(roi_mask, dtype=bool)
        if roi.shape != image.shape:
            raise ValueError("HDR 過曝判定 ROI 與影像尺寸不一致")
        valid &= roi
    if hot_pixel_mask is not None:
        hot = np.asarray(hot_pixel_mask, dtype=bool)
        if hot.shape != image.shape:
            raise ValueError("HDR 熱像素遮罩與影像尺寸不一致")
        valid &= ~hot
    pixels = image[valid]
    if not pixels.size:
        raise ValueError("HDR 過曝判定沒有可用的有效 ROI 像素")
    saturation_fraction = float(np.mean(pixels >= saturation_dn))
    p99_9 = float(np.percentile(pixels, 99.9))
    severe = saturation_fraction >= severe_saturation_fraction and p99_9 >= saturation_dn
    return ExposureDecision(
        exposure_ms=float(exposure_ms),
        saturation_fraction=saturation_fraction,
        p99_9_dn=p99_9,
        severe_overexposure=severe,
        action="terminate" if severe else "continue",
        reason=(
            f"有效 ROI 飽和比例 {saturation_fraction:.3%} 達門檻 "
            f"{severe_saturation_fraction:.3%}，P99.9={p99_9:.1f} DN"
            if severe
            else ""
        ),
    )


def capture_exposure_sequence(
    plan: ExposurePlan,
    capture_frame: Callable[[float, int, int], np.ndarray],
    saturation_dn: float = 245.0,
    severe_saturation_fraction: float = 0.05,
    early_stop_enabled: bool = True,
    roi_mask: np.ndarray | None = None,
    hot_pixel_mask: np.ndarray | None = None,
    spool_directory: str | Path | None = None,
) -> ExposureSequenceResult:
    """Capture short-to-long, terminating on the first severely clipped segment.

    ``capture_frame(exposure_ms, gain_percent, frame_number)`` is deliberately
    hardware-neutral. Frame number starts at 1. The judgment frame is retained
    even when it causes termination; remaining frames in that segment and all
    longer segments are not requested from the camera.
    """
    planned = tuple(sorted(float(value) for value in plan.exposures_ms))
    groups: list[list[np.ndarray] | DiskFrameGroup] = []
    excluded_judgments: list[tuple[float, np.ndarray]] = []
    decisions: list[ExposureDecision] = []
    captured: list[float] = []
    valid: list[float] = []
    excluded: list[float] = []
    skipped: list[float] = []
    termination: dict[str, Any] | None = None

    for segment_index, exposure_ms in enumerate(planned):
        first = np.asarray(capture_frame(exposure_ms, plan.gain_percent, 1))
        group: list[np.ndarray] | DiskFrameGroup
        if spool_directory is None:
            group = [first]
        else:
            group = DiskFrameGroup(Path(spool_directory), f"exp{segment_index + 1:02d}")
            group.append(first)
        captured.append(exposure_ms)
        decision = judge_exposure_frame(
            first,
            exposure_ms,
            saturation_dn,
            severe_saturation_fraction,
            roi_mask,
            hot_pixel_mask,
        )
        decisions.append(decision)
        if early_stop_enabled and decision.severe_overexposure:
            excluded.append(exposure_ms)
            excluded_judgments.append((exposure_ms, first))
            skipped.extend(planned[segment_index + 1 :])
            termination = {
                "terminated": True,
                "segment_index": segment_index + 1,
                "exposure_ms": exposure_ms,
                "reason": decision.reason,
                "remaining_frames_skipped": max(0, plan.frames_per_exposure - 1),
                "longer_exposures_skipped_ms": list(planned[segment_index + 1 :]),
            }
            break

        valid.append(exposure_ms)
        for frame_number in range(2, plan.frames_per_exposure + 1):
            frame = np.asarray(capture_frame(exposure_ms, plan.gain_percent, frame_number))
            if isinstance(group, DiskFrameGroup):
                group.append(frame)
            else:
                group.append(frame)
        groups.append(group)

    return ExposureSequenceResult(
        planned_exposures_ms=planned,
        captured_exposures_ms=tuple(captured),
        valid_exposures_ms=tuple(valid),
        excluded_exposures_ms=tuple(excluded),
        skipped_exposures_ms=tuple(skipped),
        frame_groups=groups,
        excluded_judgment_frames=excluded_judgments,
        decisions=decisions,
        early_termination=termination,
    )


def merge_quantitative_hdr(
    frame_groups: Sequence[np.ndarray | Sequence[np.ndarray]],
    dark_groups: Sequence[np.ndarray | Sequence[np.ndarray]],
    exposures_ms: Sequence[float],
    saturation_dn: float = 245.0,
    low_signal_sigma: float = 5.0,
    combine_method: str = "median",
) -> HDRResult:
    """Fuse exposures into linear float32 DN/s, selecting the longest valid one.

    The output is never tone mapped.  Pixels without an unsaturated measurement
    above the noise threshold are NaN and excluded by ``valid_mask``.
    """
    if not (len(frame_groups) == len(dark_groups) == len(exposures_ms)) or not exposures_ms:
        raise ValueError("曝光、EL frames 與 Dark frames 的數量必須一致且不可為空")
    order = np.argsort(np.asarray(exposures_ms, dtype=float))
    exposures = tuple(float(exposures_ms[index]) for index in order)
    if any(value <= 0 for value in exposures):
        raise ValueError("曝光時間必須大於 0")

    first = _combine_group(frame_groups[int(order[0])], combine_method)
    shape = first.shape
    linear = np.full(shape, np.nan, dtype=np.float32)
    source_index = np.full(shape, -1, dtype=np.int16)
    any_unsaturated = np.zeros(shape, dtype=bool)

    for output_index, input_index in enumerate(order):
        raw = _combine_group(frame_groups[int(input_index)], combine_method)
        dark_stack = _group_stack(dark_groups[int(input_index)])
        dark = np.median(dark_stack, axis=0) if combine_method == "median" else np.mean(dark_stack, axis=0)
        if raw.shape != shape or dark.shape != shape:
            raise ValueError("所有 HDR 與 Dark frame 尺寸必須一致")
        noise_sigma = _pixel_or_global_sigma(dark_stack)
        corrected = raw - dark
        unsaturated = raw < saturation_dn
        any_unsaturated |= unsaturated
        valid = unsaturated & (corrected >= low_signal_sigma * noise_sigma)
        normalized = corrected / (exposures[output_index] / 1000.0)
        # Exposure order is shortest to longest. Overwriting makes each pixel use
        # the longest unsaturated, above-noise exposure and therefore best SNR.
        linear[valid] = normalized[valid].astype(np.float32)
        source_index[valid] = output_index

    valid_mask = source_index >= 0
    return HDRResult(
        linear_dn_per_s=linear,
        source_index=source_index,
        valid_mask=valid_mask,
        saturated_all_mask=~any_unsaturated,
        exposures_ms=exposures,
    )


def make_preview(linear_dn_per_s: np.ndarray) -> np.ndarray:
    """Create an 8-bit log preview. Never use this array for analysis."""
    data = np.asarray(linear_dn_per_s, dtype=np.float32)
    finite = np.isfinite(data) & (data > 0)
    preview = np.zeros(data.shape, dtype=np.uint8)
    if not np.any(finite):
        return preview
    logged = np.log1p(np.maximum(data, 0))
    low, high = np.percentile(logged[finite], [0.5, 99.5])
    if high <= low:
        preview[finite] = 255
        return preview
    scaled = np.clip((logged - low) / (high - low), 0, 1)
    preview[finite] = np.round(scaled[finite] * 255).astype(np.uint8)
    return preview














def _as_luminance(array: np.ndarray) -> np.ndarray:
    data = np.asarray(array, dtype=np.float32)
    if data.ndim == 2:
        return data
    if data.ndim == 3 and data.shape[-1] >= 3:
        return 0.2126 * data[..., 0] + 0.7152 * data[..., 1] + 0.0722 * data[..., 2]
    raise ValueError("影像必須是 2D 灰階或 RGB 陣列")


def _group_stack(group: np.ndarray | Sequence[np.ndarray] | DiskFrameGroup) -> np.ndarray:
    if isinstance(group, DiskFrameGroup):
        return np.stack([_as_luminance(item) for item in group.frames()], axis=0)
    data = np.asarray(group, dtype=np.float32)
    if data.ndim in (2, 3) and (data.ndim == 2 or data.shape[-1] in (3, 4)):
        data = _as_luminance(data)[None, ...]
    elif data.ndim >= 3:
        data = np.stack([_as_luminance(item) for item in data], axis=0)
    else:
        raise ValueError("Frame group 格式無效")
    return data


def _combine_group(group: np.ndarray | Sequence[np.ndarray] | DiskFrameGroup, method: str) -> np.ndarray:
    if isinstance(group, DiskFrameGroup) and method == "average":
        frames = group.frames()
        if not frames:
            raise ValueError("Frame group must not be empty")
        total = np.zeros_like(_as_luminance(frames[0]), dtype=np.float64)
        for frame in frames:
            total += _as_luminance(frame)
        return (total / len(frames)).astype(np.float32)
    stack = _group_stack(group)
    if method == "median":
        return np.median(stack, axis=0)
    if method == "average":
        return np.mean(stack, axis=0)
    raise ValueError("combine_method 必須是 median 或 average")


def _robust_sigma(data: np.ndarray) -> float:
    median = float(np.median(data))
    mad = float(np.median(np.abs(data - median)))
    return max(1.4826 * mad, 1e-6)


def _pixel_or_global_sigma(stack: np.ndarray) -> np.ndarray | float:
    if stack.shape[0] >= 3:
        median = np.median(stack, axis=0)
        sigma = 1.4826 * np.median(np.abs(stack - median), axis=0)
        positive = sigma[sigma > 0]
        fallback = float(np.median(positive)) if positive.size else _robust_sigma(stack)
        return np.where(sigma > 0, sigma, max(fallback, 1e-6))
    return _robust_sigma(stack)


# Stable compatibility facade: existing callers may continue importing output
# functions from risingcam_gui.auto_hdr.
from .hdr_output import save_hdr_capture_set, save_hdr_products
