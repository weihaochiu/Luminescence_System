from __future__ import annotations

"""Single deterministic Recipe execution-plan source for UI and worker."""

from dataclasses import dataclass, field
from typing import Any, Iterable

from .recipe_store import Recipe


@dataclass(frozen=True)
class ExecutionStep:
    key: str
    title: str
    children: tuple["ExecutionStep", ...] = field(default_factory=tuple)
    details: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        payload: dict[str, Any] = {"key": self.key, "title": self.title}
        if self.details:
            payload["details"] = dict(self.details)
        if self.children:
            payload["children"] = [child.to_dict() for child in self.children]
        return payload


@dataclass(frozen=True)
class MeasurementExecutionPlan:
    steps: tuple[ExecutionStep, ...]

    @property
    def keys(self) -> tuple[str, ...]:
        return tuple(step.key for step in self.steps)

    def to_dict(self) -> dict[str, Any]:
        return {"steps": [step.to_dict() for step in self.steps]}


@dataclass(frozen=True)
class EffectiveMatrixCaptureAxes:
    gains_percent: tuple[int, ...]
    exposures_ms: tuple[float, ...]
    repeat: int


def effective_matrix_capture_axes(recipe: Recipe) -> EffectiveMatrixCaptureAxes:
    """Return the capture schedule owned exclusively by Recipe.el_matrix."""

    matrix = recipe.el_matrix
    return EffectiveMatrixCaptureAxes(
        tuple(int(value) for value in matrix.gains_percent),
        tuple(float(value) for value in matrix.exposures_ms),
        int(matrix.repeat),
    )


def _leaf(key: str, title: str, **details: Any) -> ExecutionStep:
    return ExecutionStep(key, title, details=details)


def _matrix_channel_steps(recipe: Recipe) -> Iterable[ExecutionStep]:
    matrix = recipe.el_matrix
    axes = effective_matrix_capture_axes(recipe)
    for channel in recipe.enabled_channels():
        density_steps: list[ExecutionStep] = []
        for density in matrix.current_density_ma_cm2:
            gain_steps = tuple(
                ExecutionStep(
                    f"gain_{gain}",
                    f"Gain {gain}%",
                    tuple(
                        ExecutionStep(
                            f"exposure_{exposure:g}",
                            f"Exposure {exposure:g} ms",
                            tuple(
                                _leaf(f"repeat_{index}", f"Repeat {index}")
                                for index in range(1, axes.repeat + 1)
                            ),
                        )
                        for exposure in axes.exposures_ms
                    ),
                )
                for gain in axes.gains_percent
            )
            density_steps.append(
                ExecutionStep(
                    f"density_{density:g}",
                    f"Current Density {density:g} mA/cm²",
                    gain_steps,
                )
            )
        channel_steps: list[ExecutionStep] = []
        if recipe.dark_iv.enabled:
            channel_steps.append(
                ExecutionStep(
                    "dark_iv",
                    "Dark IV",
                    (
                        _leaf("dark_iv_apply", "套用 Dark IV 設定"),
                        _leaf("dark_iv_measure", "Sweep / Measure"),
                        _leaf("dark_iv_save", "保存結果"),
                    ),
                )
            )
        channel_steps.append(ExecutionStep("el_matrix", "EL Matrix", tuple(density_steps)))
        yield ExecutionStep(
            f"channel_{channel.channel.lower()}", channel.channel, tuple(channel_steps)
        )


def _polarity_channel_steps(recipe: Recipe) -> Iterable[ExecutionStep]:
    for channel in recipe.enabled_channels():
        channel_key = channel.channel.lower()
        yield ExecutionStep(
            f"polarity_{channel_key}",
            channel.channel,
            (
                _leaf(f"polarity_route_{channel_key}", f"Routing {channel.channel}"),
                _leaf(f"white_light_on_{channel_key}", "White Light ON"),
                _leaf(f"polarity_measure_{channel_key}", "Polarity Measurement"),
                _leaf(f"polarity_determine_{channel_key}", "Determine polarity"),
                _leaf(f"white_light_off_{channel_key}", "White Light OFF"),
            ),
        )


def _shared_dark_steps(recipe: Recipe) -> Iterable[ExecutionStep]:
    axes = effective_matrix_capture_axes(recipe)
    for gain in axes.gains_percent:
        yield ExecutionStep(
            f"dark_gain_{gain}",
            f"Gain {gain}%",
            tuple(
                ExecutionStep(
                    f"dark_exposure_{exposure:g}",
                    f"Exposure {exposure:g} ms",
                    tuple(
                        _leaf(f"dark_repeat_{index}", f"Repeat {index}")
                        for index in range(1, axes.repeat + 1)
                    ),
                )
                for exposure in axes.exposures_ms
            ),
        )


def _output_steps(recipe: Recipe) -> tuple[ExecutionStep, ...]:
    children = [
        _leaf(f"output_{label.lower().replace(' ', '_')}", label)
        for label in recipe.output.selected_formats()
    ]
    children.extend((
        _leaf("output_capture_records", "Capture Records（必要）"),
        _leaf("output_summary_csv", "Summary CSV（必要）"),
        _leaf("output_json_metadata", "JSON Metadata（必要）"),
        _leaf("output_recipe_snapshot", "Recipe Snapshot（必要）"),
    ))
    if recipe.output.export_pixel_csv:
        pixel_products: list[ExecutionStep] = []
        if recipe.output.pixel_csv_raw:
            pixel_products.append(_leaf("pixel_csv_raw", "Raw DN"))
        if recipe.output.pixel_csv_dark_corrected:
            pixel_products.append(_leaf("pixel_csv_dark_corrected", "Dark-corrected"))
        if recipe.output.pixel_csv_exposure_normalized:
            pixel_products.append(
                _leaf("pixel_csv_exposure_normalized", "Exposure-normalized（DN/ms）")
            )
        children.append(
            ExecutionStep(
                "pixel_csv", "Pixel CSV（Safe Shutdown 後處理）", tuple(pixel_products)
            )
        )
    return tuple(children)


def build_measurement_execution_plan(
    recipe: Recipe,
    global_settings: Any | None = None,
) -> MeasurementExecutionPlan:
    """Build the exact enabled workflow in the same order used by the runner."""

    del global_settings
    steps: list[ExecutionStep] = [
        ExecutionStep(
            "initialize",
            "初始化 / 前置檢查",
            (
                _leaf("camera_preflight", "相機連線 / 能力檢查"),
                _leaf("smu_preflight", "SMU OUTPUT OFF / 身分確認"),
                _leaf("output_preflight", "輸出目錄 / 空間 / 快照檢查"),
            ),
        )
    ]
    if recipe.polarity.enabled:
        steps.append(
            ExecutionStep(
                "polarity",
                "極性確認",
                tuple(_polarity_channel_steps(recipe)),
            )
        )
    if recipe.el_matrix.dark_frame_enabled:
        steps.append(
            ExecutionStep(
                "dark_frame",
                "Shared Dark Frame",
                tuple(_shared_dark_steps(recipe)),
            )
        )
    steps.append(
        ExecutionStep("channels", "Channels", tuple(_matrix_channel_steps(recipe)))
    )
    steps.append(
        ExecutionStep(
            "output",
            f"輸出（{recipe.output.resolution_id}）",
            _output_steps(recipe),
        )
    )
    steps.append(ExecutionStep("safe_shutdown", "Safe Shutdown"))
    return MeasurementExecutionPlan(tuple(steps))
