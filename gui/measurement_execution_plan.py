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
    hdr_enabled: bool


def effective_matrix_capture_axes(
    recipe: Recipe,
    hdr_settings: Any | None = None,
    *,
    hdr_profile: Any | None = None,
) -> EffectiveMatrixCaptureAxes:
    """Return the one effective capture schedule shared by preview and runtime."""

    if recipe.hdr.enabled:
        if hdr_profile is not None:
            return EffectiveMatrixCaptureAxes(
                (int(hdr_profile.gain_percent),),
                tuple(float(value) for value in hdr_profile.exposure_times_ms),
                int(hdr_profile.frames_per_exposure),
                True,
            )
        if hdr_settings is not None:
            return EffectiveMatrixCaptureAxes(
                (int(hdr_settings.locked_gain_percent),),
                tuple(float(value) for value in hdr_settings.planned_exposures_ms()),
                int(hdr_settings.frames_per_exposure),
                True,
            )
        return EffectiveMatrixCaptureAxes((), (), 0, True)
    matrix = recipe.el_matrix
    return EffectiveMatrixCaptureAxes(
        tuple(int(value) for value in matrix.gains_percent),
        tuple(float(value) for value in matrix.exposures_ms),
        int(matrix.repeat),
        False,
    )


def _leaf(key: str, title: str, **details: Any) -> ExecutionStep:
    return ExecutionStep(key, title, details=details)


def _hdr_children_from_exposures(
    exposures: tuple[float, ...], early_stop_enabled: bool
) -> tuple[ExecutionStep, ...]:
    if not exposures:
        return (_leaf("hdr_settings_required", "HDR 系統設定待載入"),)
    children = [
        _leaf("hdr_base", f"Base / T0（{exposures[0]:g} ms）")
    ] if exposures else []
    children.extend(
        _leaf(f"hdr_stop_{index}", f"Stop {index}（{exposure:g} ms）")
        for index, exposure in enumerate(exposures[1:], start=1)
    )
    if early_stop_enabled:
        children.append(_leaf("hdr_early_stop", "飽和提前終止判定"))
    children.append(_leaf("hdr_merge", "線性合併 / 輸出"))
    return tuple(children)


def _matrix_channel_steps(
    recipe: Recipe,
    hdr_settings: Any | None,
    hdr_profile: Any | None,
) -> Iterable[ExecutionStep]:
    matrix = recipe.el_matrix
    axes = effective_matrix_capture_axes(
        recipe, hdr_settings, hdr_profile=hdr_profile
    )
    for channel in recipe.enabled_channels():
        density_steps: list[ExecutionStep] = []
        for density in matrix.current_density_ma_cm2:
            if recipe.hdr.enabled:
                capture_steps = (
                    ExecutionStep(
                        "hdr",
                        "HDR",
                        _hdr_children_from_exposures(
                            axes.exposures_ms,
                            bool(
                                getattr(
                                    hdr_settings,
                                    "early_stop_on_severe_overexposure",
                                    False,
                                )
                            ),
                        ),
                    ),
                )
            else:
                capture_steps = tuple(
                    ExecutionStep(
                        f"gain_{gain}",
                        f"Gain {gain}%",
                        tuple(
                            _leaf(
                                f"exposure_{exposure:g}",
                                f"Exposure {exposure:g} ms × {matrix.repeat}",
                            )
                            for exposure in matrix.exposures_ms
                        ),
                    )
                    for gain in matrix.gains_percent
                )
            density_steps.append(
                ExecutionStep(
                    f"density_{density:g}",
                    f"Current Density {density:g} mA/cm²",
                    capture_steps,
                )
            )
        yield ExecutionStep(
            f"channel_{channel.channel.lower()}", channel.channel, tuple(density_steps)
        )


def build_measurement_execution_plan(
    recipe: Recipe,
    global_settings: Any | None = None,
    *,
    hdr_settings: Any | None = None,
    hdr_profile: Any | None = None,
) -> MeasurementExecutionPlan:
    """Build the exact enabled workflow; disabled phases are absent."""

    del global_settings  # Reserved for future plan annotations; safety stays global.
    steps: list[ExecutionStep] = [
        ExecutionStep(
            "initialize",
            "初始化 / 前置檢查",
            (
                _leaf("camera_preflight", "相機與解析度確認"),
                _leaf("smu_preflight", "SMU OUTPUT OFF 與安全限制確認"),
                _leaf("output_preflight", "輸出目錄與磁碟空間確認"),
            ),
        )
    ]
    if recipe.polarity.enabled:
        steps.append(
            ExecutionStep(
                "polarity",
                "極性確認",
                (
                    _leaf("white_light_on", "White Light ON"),
                    _leaf("polarity_measure", "Polarity measurement"),
                    _leaf("polarity_determine", "Determine polarity / routing factor"),
                    _leaf("white_light_off", "White Light OFF"),
                ),
            )
        )
    if recipe.dark_iv.enabled:
        steps.append(
            ExecutionStep(
                "dark_iv",
                "Dark IV",
                (
                    _leaf("dark_iv_apply", "套用 Dark IV 設定"),
                    _leaf("dark_iv_measure", "Sweep / Measure"),
                    _leaf("dark_iv_save", "儲存結果"),
                ),
            )
        )
    if recipe.el_matrix.dark_frame_enabled:
        steps.append(
            ExecutionStep(
                "dark_frame",
                "Dark Frame",
                (_leaf("dark_frame_acquire", "拍攝 Shared Dark Matrix"),),
            )
        )
    steps.append(
        ExecutionStep(
            "el_matrix",
            "EL Matrix",
            tuple(_matrix_channel_steps(recipe, hdr_settings, hdr_profile)),
        )
    )
    steps.append(
        ExecutionStep(
            "output",
            f"輸出（{recipe.output.resolution_id}）",
            tuple(
                _leaf(f"output_{label.lower().replace(' ', '_')}", label)
                for label in recipe.output.selected_formats()
            ),
        )
    )
    return MeasurementExecutionPlan(tuple(steps))
