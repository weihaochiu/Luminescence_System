from __future__ import annotations

"""Verified, temporary SDK settings for Recipe-owned one-shot AE.

All functions run on the CameraController's Qt owner thread.
"""

from typing import Any

from .camera_controller import SDKAutoExposureMode
from .camera_exposure import constrained_exposure_range_us
from .sdk import nncam
from .recipe_ae_stops import baseline_range_us
from .camera_sdk_diagnostics import sdk_call, stop_for_configuration


def restore_recipe_ae(controller: Any, state: dict[str, Any]) -> None:
    controller._auto_exposure_target_percent = state["target_percent"]
    camera = controller._camera
    if camera is None:
        raise RuntimeError("Camera disconnected during Recipe AE cleanup")
    controller._disable_sdk_auto_exposure(require_readback=True)
    stop_for_configuration(controller, "Recipe AE restore")
    sdk_call("Recipe AE restore", camera.put_AutoExpoRange, *state["range"])
    if tuple(sdk_call("Recipe AE restore", camera.get_AutoExpoRange)) != tuple(state["range"]):
        raise RuntimeError("Recipe AE range restoration readback mismatch")
    for option, value in state["options"].items():
        sdk_call("Recipe AE restore", camera.put_Option, option, value)
        if int(sdk_call("Recipe AE restore", camera.get_Option, option)) != value:
            raise RuntimeError("Recipe AE option restoration readback mismatch")
    sdk_call("Recipe AE restore", camera.put_AutoExpoTarget, state["target"])
    if int(sdk_call("Recipe AE restore", camera.get_AutoExpoTarget)) != state["target"]:
        raise RuntimeError("Recipe AE target restoration readback mismatch")
    controller._sdk_auto_exposure_policy_readback = state["options"][nncam.NNCAM_OPTION_AUTOEXP_POLICY]
    controller._sdk_auto_exposure_percent_readback = state["options"][nncam.NNCAM_OPTION_AUTOEXPOSURE_PERCENT]
    controller._sdk_auto_exposure_target_readback = state["target"]
    controller._sdk_auto_exposure_target = state["target"]
    raw = state["range"]
    controller._auto_exposure_range = (raw[1], raw[0], raw[3], raw[2])
    sdk_call("Recipe AE restore: restart preview", controller._start_stream)


def begin_recipe_ae(controller: Any, settings: dict[str, Any], state: dict[str, Any]) -> None:
    camera = controller._camera
    if camera is None or controller.ae_calibration_running:
        raise RuntimeError("Recipe AE requires a connected, available camera")
    if settings["auto_gain_mode"] not in {"auto", "fixed"}:
        raise ValueError("Invalid Recipe AE gain mode")
    controller.finish_software_triggered_capture()
    controller._continuous_auto_exposure_requested = False
    controller._disable_sdk_auto_exposure(require_readback=True)
    # Read everything before writing so partial setup can always be unwound.
    original = {
        "range": tuple(map(int, sdk_call("Recipe AE snapshot", camera.get_AutoExpoRange))),
        "target": int(sdk_call("Recipe AE snapshot", camera.get_AutoExpoTarget)),
        "target_percent": controller.auto_exposure_target_percent,
        "options": {
            option: int(sdk_call("Recipe AE snapshot", camera.get_Option, option)) for option in (
                nncam.NNCAM_OPTION_AUTOEXP_POLICY,
                nncam.NNCAM_OPTION_AUTOEXPOSURE_PERCENT,
            )
        },
    }
    state.update(original)
    # Runtime DN/alignment updates use this value when refreshing SDK targets.
    # Keep them on the Recipe target for the entire AE interval.
    controller._auto_exposure_target_percent = settings["auto_target_percent"]
    hardware_range = constrained_exposure_range_us(sdk_call("Recipe AE setup", camera.get_ExpTimeRange))
    if hardware_range is None:
        raise RuntimeError("Recipe AE exposure capabilities are unavailable")
    if float(settings["auto_max_exposure_ms"]) * 1000 > hardware_range[1]:
        raise ValueError("Recipe AE maximum exposure is outside camera capabilities")
    minimum, maximum = baseline_range_us(
        settings.get("auto_exposure_stops", [0.0]),
        float(settings["auto_max_exposure_ms"]), hardware_range)
    gain_low, gain_high, _default = map(int, sdk_call("Recipe AE setup", camera.get_ExpoAGainRange))
    fixed = settings["auto_gain_mode"] == "fixed"
    if fixed:
        gain = int(settings["auto_gain_percent"])
        if not gain_low <= gain <= gain_high:
            raise ValueError("Recipe AE fixed Gain is outside camera capabilities")
        min_gain = max_gain = gain
    else:
        min_gain = max(gain_low, original["range"][3])
        max_gain = min(gain_high, original["range"][2])
        if min_gain > max_gain:
            raise ValueError("Recipe AE Gain limits do not intersect hardware capabilities")
    requested_range = (maximum, minimum, max_gain, min_gain)
    # Some SDK/model combinations reject AE option writes while acquiring,
    # even with AE disabled. Configure and verify with acquisition stopped.
    stop_for_configuration(controller, "Recipe AE setup")
    sdk_call("Recipe AE setup", camera.put_AutoExpoRange, *requested_range)
    if tuple(sdk_call("Recipe AE setup", camera.get_AutoExpoRange)) != requested_range:
        raise RuntimeError("Recipe AE range readback mismatch")
    if fixed:
        sdk_call("Recipe AE setup", camera.put_ExpoAGain, gain)
        if int(sdk_call("Recipe AE setup", camera.get_ExpoAGain)) != gain:
            raise RuntimeError("Recipe AE fixed Gain readback mismatch")
    for option, value in (
        (nncam.NNCAM_OPTION_AUTOEXP_POLICY, 0 if fixed else 1),
        (nncam.NNCAM_OPTION_AUTOEXPOSURE_PERCENT, 100),
    ):
        sdk_call("Recipe AE setup", camera.put_Option, option, value)
        if int(sdk_call("Recipe AE setup", camera.get_Option, option)) != value:
            raise RuntimeError("Recipe AE policy/metering readback mismatch")
    target, calibrated = controller.calibrated_sdk_target(settings["auto_target_percent"])
    if controller._write_sdk_auto_exposure_target_value(camera, target) != target:
        raise RuntimeError("Recipe AE target readback mismatch")
    controller._sdk_auto_exposure_policy_readback = 0 if fixed else 1
    controller._sdk_auto_exposure_percent_readback = 100
    controller._auto_exposure_range = (minimum, maximum, min_gain, max_gain)
    state["result_metadata"] = {
        "RecipeAETargetPercent": settings["auto_target_percent"],
        "RecipeAESDKTarget": target,
        "RecipeAECalibrationApplied": calibrated,
        "RecipeAEPolicy": 0 if fixed else 1,
        "RecipeAEMinGain": min_gain,
        "RecipeAEMaxGain": max_gain,
        "RecipeAEMaxExposureMs": maximum / 1000.0,
        "RecipeAEMinExposureMs": minimum / 1000.0,
        "RecipeAEExposureCeilingMs": settings["auto_max_exposure_ms"],
        "RecipeAEROI": controller._auto_exposure_roi_readback,
    }
    sdk_call("Recipe AE setup: start acquisition", controller._start_stream)
    controller._enable_sdk_auto_exposure(SDKAutoExposureMode.ONCE)
