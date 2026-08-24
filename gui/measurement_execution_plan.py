from __future__ import annotations

"""Single deterministic Recipe execution-plan source for UI and worker."""

from dataclasses import dataclass, field
from typing import Any, Iterable

from core.i18n import tr

from .recipe_store import Recipe
from .numeric import format_voltage_number


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
        electrical_steps: list[ExecutionStep] = []
        for setpoint in matrix.active_electrical_setpoints():
            gain_steps = tuple(
                ExecutionStep(
                    f"gain_{gain}",
                    tr("plan.gain", gain=gain),
                    tuple(
                        ExecutionStep(
                            f"exposure_{exposure:g}",
                            tr("plan.exposure", exposure=f"{exposure:g}"),
                            tuple(
                                _leaf(f"repeat_{index}", tr("plan.repeat", index=index))
                                for index in range(1, axes.repeat + 1)
                            ),
                        )
                        for exposure in axes.exposures_ms
                    ),
                )
                for gain in axes.gains_percent
            )
            voltage_mode = matrix.output_mode == "voltage"
            electrical_steps.append(
                ExecutionStep(
                    f"voltage_{format_voltage_number(setpoint)}"
                    if voltage_mode else f"density_{setpoint:g}",
                    tr("plan.voltage", value=format_voltage_number(setpoint))
                    if voltage_mode
                    else tr("plan.current_density", value=f"{setpoint:g}"),
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
                        _leaf("dark_iv_apply", tr("plan.dark_iv_apply")),
                        _leaf("dark_iv_measure", tr("plan.sweep_measure")),
                        _leaf("dark_iv_save", tr("plan.save_results")),
                    ),
                )
            )
        channel_steps.append(
            ExecutionStep("el_matrix", "EL Matrix", tuple(electrical_steps))
        )
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
                _leaf(f"polarity_route_{channel_key}", tr("plan.routing", channel=channel.channel)),
                _leaf(f"white_light_on_{channel_key}", tr("plan.white_light_on")),
                _leaf(f"polarity_measure_{channel_key}", tr("plan.polarity_measurement")),
                _leaf(f"polarity_determine_{channel_key}", tr("plan.determine_polarity")),
                _leaf(f"white_light_off_{channel_key}", tr("plan.white_light_off")),
            ),
        )


def _shared_dark_steps(recipe: Recipe) -> Iterable[ExecutionStep]:
    axes = effective_matrix_capture_axes(recipe)
    for gain in axes.gains_percent:
        yield ExecutionStep(
            f"dark_gain_{gain}",
            tr("plan.gain", gain=gain),
            tuple(
                ExecutionStep(
                    f"dark_exposure_{exposure:g}",
                    tr("plan.exposure", exposure=f"{exposure:g}"),
                    tuple(
                        _leaf(f"dark_repeat_{index}", tr("plan.repeat", index=index))
                        for index in range(1, axes.repeat + 1)
                    ),
                )
                for exposure in axes.exposures_ms
            ),
        )


def _output_steps(recipe: Recipe) -> tuple[ExecutionStep, ...]:
    output_titles = {"JPG with Footer": tr("plan.jpg_with_footer")}
    children = [
        _leaf(
            f"output_{label.lower().replace(' ', '_')}",
            output_titles.get(label, label),
        )
        for label in recipe.output.selected_formats()
    ]
    children.extend((
        _leaf("output_capture_records", tr("plan.capture_records_required")),
        _leaf("output_summary_csv", tr("plan.summary_csv_required")),
        _leaf("output_json_metadata", tr("plan.json_metadata_required")),
        _leaf("output_recipe_snapshot", tr("plan.recipe_snapshot_required")),
    ))
    if recipe.output.export_pixel_csv:
        pixel_products: list[ExecutionStep] = []
        if recipe.output.pixel_csv_raw:
            pixel_products.append(_leaf("pixel_csv_raw", "Raw DN"))
        if recipe.output.pixel_csv_dark_corrected:
            pixel_products.append(_leaf("pixel_csv_dark_corrected", tr("plan.dark_corrected")))
        if recipe.output.pixel_csv_exposure_normalized:
            pixel_products.append(
                _leaf("pixel_csv_exposure_normalized", tr("plan.exposure_normalized"))
            )
        children.append(
            ExecutionStep(
                "pixel_csv", tr("plan.pixel_csv_postprocess"), tuple(pixel_products)
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
            tr("plan.initialize"),
            (
                _leaf("camera_preflight", tr("plan.camera_preflight")),
                _leaf("smu_preflight", tr("plan.smu_preflight")),
                _leaf("output_preflight", tr("plan.output_preflight")),
            ),
        )
    ]
    if recipe.polarity.enabled:
        steps.append(
            ExecutionStep(
                "polarity",
                tr("plan.polarity"),
                tuple(_polarity_channel_steps(recipe)),
            )
        )
    if recipe.el_matrix.dark_frame_enabled:
        steps.append(
            ExecutionStep(
                "dark_frame",
                tr("plan.shared_dark_frame"),
                tuple(_shared_dark_steps(recipe)),
            )
        )
    steps.append(
        ExecutionStep("channels", "Channels", tuple(_matrix_channel_steps(recipe)))
    )
    steps.append(
        ExecutionStep(
            "output",
            tr("plan.output", resolution=recipe.output.resolution_id),
            _output_steps(recipe),
        )
    )
    steps.append(ExecutionStep("safe_shutdown", tr("plan.safe_shutdown")))
    return MeasurementExecutionPlan(tuple(steps))
