from __future__ import annotations

"""Verified, temporary SDK settings for Recipe-owned one-shot AE.

All functions run on the CameraController's Qt owner thread.
"""

import json
import logging
from time import monotonic
from typing import Any

from .camera_controller import SDKAutoExposureMode
from .camera_exposure import (
    constrained_exposure_range_us, SDK_AUTO_EXPOSURE_MAX_US,
    SDK_AUTO_EXPOSURE_MAX_GAIN_PERCENT,
)
from .sdk import nncam
from .recipe_ae_stops import native_baseline_range_us
from .camera_sdk_diagnostics import sdk_call, stop_for_configuration


LOG = logging.getLogger(__name__)


def _restart_recipe_stream(controller: Any, stage: str) -> None:
    # The rectangle belongs to the SDK image pipeline. A verified rectangle in
    # the previous stream does not establish what the restarted pipeline uses.
    controller._auto_exposure_roi_verified = False
    controller._auto_exposure_roi_readback = None
    controller._auto_exposure_roi_verification_status = "Pending"
    controller._latest_metering_mean_effective_dn = None
    controller._latest_metering_effective_dn_fraction = None
    sdk_call(stage, controller._start_stream)


def _reapply_recipe_roi(controller: Any, state: dict[str, Any], stage: str) -> None:
    requested = state["roi"]
    if not controller._apply_auto_exposure_roi(
        requested, reason=stage, refresh_profile=False,
    ):
        raise RuntimeError(
            f"{stage}: AE ROI verification failed; requested={requested}; "
            f"readback={controller._auto_exposure_roi_readback}; "
            f"{controller._auto_exposure_roi_error}"
        )


def verify_recipe_ae_roi(
    controller: Any, expected: tuple[int, int, int, int], generation: int,
) -> None:
    """Read the native rectangle again when accepting a convergence event."""
    try:
        actual = tuple(map(int, sdk_call(
            "Recipe AE result ROI", controller._camera.get_AEAuxRect,
        )))
    except Exception as exc:
        controller._auto_exposure_roi_readback = None
        controller._set_auto_exposure_roi_failure(
            tuple(expected), "ReadbackFailed", "RECIPE_AE_RESULT_ROI_FAILED", str(exc),
        )
        raise
    if (not controller._auto_exposure_roi_verified or actual != tuple(expected)
            or generation != controller._stream_generation):
        controller._auto_exposure_roi_readback = actual
        detail = (
            f"Recipe AE ROI changed; requested={expected}; native_readback={actual}; "
            f"expected_stream={generation}; current_stream={controller._stream_generation}"
        )
        controller._set_auto_exposure_roi_failure(
            tuple(expected), "ReadbackMismatch", "RECIPE_AE_RESULT_ROI_FAILED", detail,
        )
        raise RuntimeError(detail)


def verify_recipe_ae_configuration(controller: Any, metadata: dict[str, Any]) -> None:
    """Check the running pipeline, not just values echoed before Start."""
    camera = controller._camera
    expected_range = (
        round(metadata["RecipeAEMaxExposureMs"] * 1000),
        round(metadata["RecipeAEMinExposureMs"] * 1000),
        metadata["RecipeAEMaxGain"], metadata["RecipeAEMinGain"],
    )
    actual_range = _read_ae_range(camera, "Recipe AE verification")
    if actual_range != expected_range:
        raise RuntimeError(f"Recipe AE limits changed: expected={expected_range}, actual={actual_range}")
    for option, expected in (
        (nncam.NNCAM_OPTION_AUTOEXP_POLICY, metadata["RecipeAEPolicy"]),
        (nncam.NNCAM_OPTION_AUTOEXPOSURE_PERCENT, metadata.get("RecipeAEMeteringPercent", 100)),
        (nncam.NNCAM_OPTION_UPSIDE_DOWN, 0),
    ):
        actual = int(sdk_call("Recipe AE verification", camera.get_Option, option))
        if actual != expected:
            raise RuntimeError(f"Recipe AE option {option:#x} changed: expected={expected}, actual={actual}")
    target = int(sdk_call("Recipe AE verification", camera.get_AutoExpoTarget))
    if target != metadata["RecipeAESDKTarget"]:
        raise RuntimeError(f"Recipe AE target changed: expected={metadata['RecipeAESDKTarget']}, actual={target}")


def _seed_within_limits(camera: Any, limits: tuple[int, int, int, int]) -> tuple[int, int]:
    maximum, minimum, max_gain, min_gain = limits
    exposure = int(sdk_call("Recipe AE initial settings", camera.get_ExpoTime))
    gain = int(sdk_call("Recipe AE initial settings", camera.get_ExpoAGain))
    requested_exposure = min(maximum, max(minimum, exposure))
    requested_gain = min(max_gain, max(min_gain, gain))
    if exposure != requested_exposure:
        sdk_call("Recipe AE initial settings", camera.put_ExpoTime, requested_exposure)
    if gain != requested_gain:
        sdk_call("Recipe AE initial settings", camera.put_ExpoAGain, requested_gain)
    actual = (
        int(sdk_call("Recipe AE initial settings", camera.get_ExpoTime)),
        int(sdk_call("Recipe AE initial settings", camera.get_ExpoAGain)),
    )
    if actual != (requested_exposure, requested_gain):
        raise RuntimeError(f"Recipe AE initial Exposure/Gain readback mismatch: requested={(requested_exposure, requested_gain)}, actual={actual}")
    return actual


def recipe_ae_failure_context(controller: Any, state: dict[str, Any]) -> str:
    """Capture owner-thread diagnostics before temporary settings are restored.

    Getter values describe the current camera settings; last-frame DN and its
    embedded exposure metadata are separate because frames can arrive later.
    Diagnostic read failures must not replace the original measurement error.
    """
    valid_frame = controller._scientific_frame_validated
    details = {
        "RequestedROI": state.get("roi"),
        "ROIStreamGeneration": state.get("result_metadata", {}).get("RecipeAEROIStreamGeneration"),
        "CurrentStreamGeneration": controller._stream_generation,
        "ROIVerified": controller._auto_exposure_roi_verified,
        "TargetPercent": controller.auto_exposure_target_percent,
        "ElapsedSeconds": monotonic() - state["started_at"] if "started_at" in state else None,
        "RecipeConfiguration": state.get("result_metadata", {}),
        "LastScientificFrameValid": valid_frame,
        "LastFrameROIMeanDN": controller._latest_metering_mean_effective_dn if valid_frame else None,
        "LastFrameROIMeanPercent": (
            controller._latest_metering_effective_dn_fraction * 100
            if valid_frame and controller._latest_metering_effective_dn_fraction is not None else None
        ),
        "LastFrameMetadata": dict(controller._frame_capture_metadata.get(controller._frame_sequence, {}))
        if valid_frame else {},
    }
    for name, method in (
        ("NativeROIReadback", "get_AEAuxRect"),
        ("ExposureReadbackUs", "get_ExpoTime"),
        ("GainReadbackPercent", "get_ExpoAGain"),
        ("NativeTargetReadback", "get_AutoExpoTarget"),
        ("AEMinTimeGain", "get_MinAutoExpoTimeAGain"),
        ("AEMaxTimeGain", "get_MaxAutoExpoTimeAGain"),
    ):
        try:
            details[name] = sdk_call("Recipe AE failure snapshot", getattr(controller._camera, method))
        except Exception as exc:
            details[name] = f"unavailable: {exc}"
    try:
        details["UpsideDownReadback"] = sdk_call(
            "Recipe AE failure snapshot", controller._camera.get_Option,
            nncam.NNCAM_OPTION_UPSIDE_DOWN,
        )
    except Exception as exc:
        details["UpsideDownReadback"] = f"unavailable: {exc}"
    for name, option in (
        ("PolicyReadback", nncam.NNCAM_OPTION_AUTOEXP_POLICY),
        ("MeteringPercentReadback", nncam.NNCAM_OPTION_AUTOEXPOSURE_PERCENT),
        ("ExposureDampingReadback", nncam.NNCAM_OPTION_AUTOEXP_EXPOTIME_DAMP),
        ("GainDampingReadback", nncam.NNCAM_OPTION_AUTOEXP_GAIN_DAMP),
    ):
        try:
            details[name] = sdk_call("Recipe AE failure snapshot", controller._camera.get_Option, option)
        except Exception as exc:
            details[name] = f"unavailable: {exc}"
    text = json.dumps(details, ensure_ascii=False)
    LOG.error("RECIPE_AE_FAILURE_CONTEXT %s", text)
    return text


def _read_ae_range(camera: Any, stage: str) -> tuple[int, int, int, int]:
    # Use the same individual limit APIs as camera capability discovery.
    # The combined get_AutoExpoRange can fail on deployed camera/SDK pairs.
    min_time, min_gain = map(int, sdk_call(stage, camera.get_MinAutoExpoTimeAGain))
    max_time, max_gain = map(int, sdk_call(stage, camera.get_MaxAutoExpoTimeAGain))
    if not (0 < min_time <= max_time and 0 < min_gain <= max_gain):
        raise RuntimeError(f"{stage}: Invalid AE limits {(max_time, min_time, max_gain, min_gain)}")
    return max_time, min_time, max_gain, min_gain


def _write_ae_range(camera: Any, requested: tuple[int, int, int, int], stage: str) -> None:
    max_time, min_time, max_gain, min_gain = requested
    if not (0 < min_time <= max_time <= SDK_AUTO_EXPOSURE_MAX_US
            and 0 < min_gain <= max_gain <= SDK_AUTO_EXPOSURE_MAX_GAIN_PERCENT):
        raise ValueError(f"{stage}: Requested limits exceed native SDK AE capabilities: {requested}")
    current_max_time, current_min_time, current_max_gain, current_min_gain = _read_ae_range(camera, stage)
    # Expand the upper limits before moving the lower limits. This also works
    # when exposure and gain move in opposite directions, or fixed Gain rises
    # above the old maximum. AE is disabled; acquisition must be active because
    # the bundled SDK applies these limits to its running image pipeline.
    expanded = max(current_max_time, max_time), max(current_max_gain, max_gain)
    if expanded != (current_max_time, current_max_gain):
        sdk_call(stage, camera.put_MaxAutoExpoTimeAGain, *expanded)
    if (min_time, min_gain) != (current_min_time, current_min_gain):
        sdk_call(stage, camera.put_MinAutoExpoTimeAGain, min_time, min_gain)
    if (max_time, max_gain) != expanded:
        sdk_call(stage, camera.put_MaxAutoExpoTimeAGain, max_time, max_gain)
    actual = _read_ae_range(camera, stage)
    if actual != requested:
        raise RuntimeError(f"{stage}: AE range readback mismatch; requested={requested}, actual={actual}")


def restore_recipe_ae(controller: Any, state: dict[str, Any]) -> None:
    camera = controller._camera
    if camera is None:
        raise RuntimeError("Camera disconnected during Recipe AE cleanup")
    if "range" not in state:
        # Snapshot reads failed before any Recipe parameter was written.
        if state.get("stream_stopped"):
            _restart_recipe_stream(controller, "Recipe AE snapshot cleanup: restart preview")
            _reapply_recipe_roi(controller, state, "RECIPE_AE_SNAPSHOT_CLEANUP_ROI")
        return
    controller._auto_exposure_target_percent = state["target_percent"]
    controller._disable_sdk_auto_exposure(require_readback=True)
    stop_for_configuration(controller, "Recipe AE restore")
    for option, value in state["options"].items():
        sdk_call("Recipe AE restore", camera.put_Option, option, value)
        if int(sdk_call("Recipe AE restore", camera.get_Option, option)) != value:
            raise RuntimeError("Recipe AE option restoration readback mismatch")
    sdk_call("Recipe AE restore", camera.put_AutoExpoTarget, state["target"])
    if int(sdk_call("Recipe AE restore", camera.get_AutoExpoTarget)) != state["target"]:
        raise RuntimeError("Recipe AE target restoration readback mismatch")
    _restart_recipe_stream(controller, "Recipe AE restore: restart preview")
    _write_ae_range(camera, state["range"], "Recipe AE restore")
    _reapply_recipe_roi(controller, state, "RECIPE_AE_RESTORE_ROI")
    raw = state["range"]
    verify_recipe_ae_configuration(controller, {
        "RecipeAEMaxExposureMs": raw[0] / 1000.0,
        "RecipeAEMinExposureMs": raw[1] / 1000.0,
        "RecipeAEMaxGain": raw[2], "RecipeAEMinGain": raw[3],
        "RecipeAEPolicy": state["options"][nncam.NNCAM_OPTION_AUTOEXP_POLICY],
        "RecipeAESDKTarget": state["target"],
        "RecipeAEMeteringPercent": state["options"][nncam.NNCAM_OPTION_AUTOEXPOSURE_PERCENT],
    })
    controller._sdk_auto_exposure_policy_readback = state["options"][nncam.NNCAM_OPTION_AUTOEXP_POLICY]
    controller._sdk_auto_exposure_percent_readback = state["options"][nncam.NNCAM_OPTION_AUTOEXPOSURE_PERCENT]
    controller._sdk_auto_exposure_target_readback = state["target"]
    controller._sdk_auto_exposure_target = state["target"]
    controller._auto_exposure_range = (raw[1], raw[0], raw[3], raw[2])


def begin_recipe_ae(controller: Any, settings: dict[str, Any], state: dict[str, Any],
                    *, mode: SDKAutoExposureMode = SDKAutoExposureMode.ONCE) -> None:
    if mode not in {SDKAutoExposureMode.ONCE, SDKAutoExposureMode.CONTINUOUS}:
        raise ValueError("Recipe AE requires Once or Continuous mode")
    camera = controller._camera
    if camera is None or controller.ae_calibration_running:
        raise RuntimeError("Recipe AE requires a connected, available camera")
    if settings["auto_gain_mode"] not in {"auto", "fixed"}:
        raise ValueError("Invalid Recipe AE gain mode")
    if not controller._auto_exposure_roi_verified or controller._auto_exposure_roi_readback is None:
        raise RuntimeError("Recipe AE requires a verified channel metering ROI")
    state["roi"] = controller._validate_auto_exposure_roi(
        controller._auto_exposure_roi_requested or controller._auto_exposure_roi_readback,
    )
    controller.finish_software_triggered_capture()
    controller._continuous_auto_exposure_requested = False
    controller._disable_sdk_auto_exposure(require_readback=True)
    # Snapshot live pipeline limits BEFORE Stop can destroy/reset that pipeline.
    original = {
        "range": _read_ae_range(camera, "Recipe AE snapshot"),
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
    stop_for_configuration(controller, "Recipe AE snapshot")
    state["stream_stopped"] = True
    # Runtime DN/alignment updates use this value when refreshing SDK targets.
    # Keep them on the Recipe target for the entire AE interval.
    controller._auto_exposure_target_percent = settings["auto_target_percent"]
    hardware_range = constrained_exposure_range_us(sdk_call("Recipe AE setup", camera.get_ExpTimeRange))
    if hardware_range is None:
        raise RuntimeError("Recipe AE exposure capabilities are unavailable")
    if float(settings["auto_max_exposure_ms"]) * 1000 > hardware_range[1]:
        raise ValueError("Recipe AE maximum exposure is outside camera capabilities")
    minimum, maximum = native_baseline_range_us(
        settings.get("auto_exposure_stops", [0.0]),
        float(settings["auto_max_exposure_ms"]), hardware_range)
    gain_low, gain_high, _default = map(int, sdk_call("Recipe AE setup", camera.get_ExpoAGainRange))
    gain_high = min(gain_high, SDK_AUTO_EXPOSURE_MAX_GAIN_PERCENT)
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
    # Avoid starting a first frame at an inherited 15 s exposure when this AE
    # run only permits 5 s (or less with positive Stops). Recheck after Start.
    _seed_within_limits(camera, requested_range)
    # Stop is needed for the policy options above, but the time/Gain setters
    # return E_UNEXPECTED without an active SDK acquisition pipeline.
    _restart_recipe_stream(controller, "Recipe AE setup: start acquisition")
    _write_ae_range(camera, requested_range, "Recipe AE setup")
    _reapply_recipe_roi(controller, state, "RECIPE_AE_SETUP_ROI")
    initial_exposure, initial_gain = _seed_within_limits(camera, requested_range)
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
        "RecipeAESDKMaxExposureMs": SDK_AUTO_EXPOSURE_MAX_US / 1000.0,
        "RecipeAEROI": controller._auto_exposure_roi_readback,
        "RecipeAEROIVerified": controller._auto_exposure_roi_verified,
        "RecipeAEROIStreamGeneration": controller._stream_generation,
        "RecipeAEInitialExposureUs": initial_exposure,
        "RecipeAEInitialGainPercent": initial_gain,
    }
    verify_recipe_ae_configuration(controller, state["result_metadata"])
    state["started_at"] = monotonic()
    controller._enable_sdk_auto_exposure(mode)
