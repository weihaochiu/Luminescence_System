from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

from gui.camera_ae_calibration import (
    AECalibrationIdentity,
    AECalibrationPoint,
    AECalibrationProfileStore,
    AECalibrationRun,
    CALIBRATION_TARGET_PERCENTS,
    build_calibration_profile,
    calibration_candidates,
    interpolate_sdk_target,
)
from gui.camera_auto_exposure_settings import default_sdk_target_guess
from gui.camera_controller import CameraController, SDKAutoExposureMode
from gui.sdk import nncam
from tests.qt_test_utils import ensure_qapplication
from tests.test_camera_exposure import FakeModeCamera, configured_controller


def point(sdk: int, percent: float, *, converged: bool = True) -> AECalibrationPoint:
    return AECalibrationPoint.measured(
        sdk_target=sdk,
        sdk_target_readback=sdk,
        mean_effective_dn=percent * 4095 / 100,
        mean_effective_dn_percent=percent,
        exposure_us=50_000 + sdk,
        gain_percent=100,
        converged=converged,
        convergence_source="test",
    )


def identity(
    *,
    serial: str = "SERIAL-A",
    width: int = 3840,
    height: int = 2160,
    ae_roi: tuple[int, int, int, int] | None = None,
):
    return AECalibrationIdentity(
        camera_model="IUA8300KMB",
        camera_serial=serial,
        width=width,
        height=height,
        sensor_bit_depth=12,
        raw_value_alignment="right",
        ae_roi=ae_roi or (0, 0, width, height),
    )


def full_curve() -> list[AECalibrationPoint]:
    return [
        point(20, 10),
        point(40, 20),
        point(60, 30),
        point(80, 40),
        point(100, 50),
        point(120, 60),
        point(140, 70),
        point(160, 80),
        point(180, 90),
    ]


class CameraAECalibrationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.app = ensure_qapplication()

    def test_piecewise_interpolation_15_to_23_percent_returns_36(self) -> None:
        result = interpolate_sdk_target(
            [point(30, 15), point(40, 23)],
            20,
            nncam.NNCAM_AETARGET_MIN,
            nncam.NNCAM_AETARGET_MAX,
        )
        self.assertEqual(36, result)

    def test_interpolation_uses_sdk_target_readback_as_measured_axis(self) -> None:
        first = point(30, 15)
        second = point(40, 23)
        first = AECalibrationPoint(**{**first.__dict__, "sdk_target_readback": 32})
        second = AECalibrationPoint(**{**second.__dict__, "sdk_target_readback": 42})
        self.assertEqual(
            38,
            interpolate_sdk_target([first, second], 20, 16, 220),
        )

    def test_complete_monotonic_profile_builds_all_operator_targets(self) -> None:
        profile = build_calibration_profile(
            identity(),
            full_curve(),
            sdk_minimum=nncam.NNCAM_AETARGET_MIN,
            sdk_maximum=nncam.NNCAM_AETARGET_MAX,
        )
        self.assertTrue(profile.valid)
        self.assertEqual(set(CALIBRATION_TARGET_PERCENTS), set(profile.target_mapping))
        self.assertEqual(40, profile.target_mapping[20])
        self.assertEqual(160, profile.target_mapping[80])

    def test_severely_non_monotonic_profile_is_invalid(self) -> None:
        curve = full_curve()
        curve[4] = point(100, 22)
        profile = build_calibration_profile(
            identity(), curve, sdk_minimum=16, sdk_maximum=220
        )
        self.assertFalse(profile.valid)
        self.assertIn("單調映射", profile.invalid_reason)

    def test_saturation_plateau_is_not_used_for_interpolation(self) -> None:
        saturated = point(200, 99)
        self.assertTrue(saturated.saturated)
        curve = full_curve() + [saturated, point(210, 99.5)]
        profile = build_calibration_profile(
            identity(), curve, sdk_minimum=16, sdk_maximum=220
        )
        self.assertTrue(profile.valid)
        self.assertEqual(160, profile.target_mapping[80])

    def test_profile_camera_serial_mismatch_does_not_apply(self) -> None:
        store = AECalibrationProfileStore(None)
        profile = build_calibration_profile(
            identity(serial="SERIAL-A"), full_curve(), sdk_minimum=16, sdk_maximum=220
        )
        store.replace(profile)
        self.assertIsNone(store.matching(identity(serial="SERIAL-B")))

    def test_profile_resolution_mismatch_does_not_apply(self) -> None:
        store = AECalibrationProfileStore(None)
        profile = build_calibration_profile(
            identity(width=3840, height=2160),
            full_curve(),
            sdk_minimum=16,
            sdk_maximum=220,
        )
        store.replace(profile)
        self.assertIsNone(store.matching(identity(width=1920, height=1080)))

    def test_profile_ae_roi_mismatch_does_not_apply(self) -> None:
        store = AECalibrationProfileStore(None)
        profile = build_calibration_profile(
            identity(), full_curve(), sdk_minimum=16, sdk_maximum=220
        )
        store.replace(profile)
        self.assertIsNone(
            store.matching(identity(ae_roi=(100, 200, 800, 600)))
        )

    def test_calibrated_20_percent_uses_profile_target_not_51(self) -> None:
        camera = FakeModeCamera()
        controller = configured_controller(camera)
        controller._width, controller._height = 3840, 2160
        controller._auto_exposure_roi_requested = (0, 0, 3840, 2160)
        controller._auto_exposure_roi_readback = (0, 0, 3840, 2160)
        controller._auto_exposure_roi_mode = "FullImage"
        controller._device = SimpleNamespace(
            id="SERIAL-A",
            displayname="IUA8300KMB",
            model=SimpleNamespace(name="IUA8300KMB"),
        )
        profile = build_calibration_profile(
            identity(), full_curve(), sdk_minimum=16, sdk_maximum=220
        )
        controller._ae_calibration_store.replace(profile)
        controller._refresh_ae_calibration_profile()
        controller._sdk_auto_exposure_mode = SDKAutoExposureMode.CONTINUOUS
        camera.auto_exposure_enable = 1
        camera.calls.clear()
        controller.set_auto_exposure_target_percent(20)
        self.assertIn(("sdk_target", 40), camera.calls)
        self.assertNotIn(("sdk_target", 51), camera.calls)
        self.assertTrue(controller.capture_metadata()["AutoExposureCalibrationApplied"])

    def test_uncalibrated_runtime_uses_guess_and_marks_not_applied(self) -> None:
        camera = FakeModeCamera()
        controller = configured_controller(camera)
        controller._effective_dn_max = 4095
        controller._sdk_auto_exposure_mode = SDKAutoExposureMode.CONTINUOUS
        camera.auto_exposure_enable = 1
        controller.set_auto_exposure_target_percent(20)
        metadata = controller.capture_metadata()
        self.assertEqual(default_sdk_target_guess(20), metadata["SDKAutoExposureTarget"])
        self.assertFalse(metadata["AutoExposureCalibrationApplied"])

    def test_continuous_calibrated_target_change_never_writes_exposure_or_gain(self) -> None:
        camera = FakeModeCamera()
        controller = configured_controller(camera)
        controller._width, controller._height = 3840, 2160
        controller._auto_exposure_roi_requested = (0, 0, 3840, 2160)
        controller._auto_exposure_roi_readback = (0, 0, 3840, 2160)
        controller._auto_exposure_roi_mode = "FullImage"
        controller._device = SimpleNamespace(
            id="SERIAL-A",
            displayname="IUA8300KMB",
            model=SimpleNamespace(name="IUA8300KMB"),
        )
        controller._ae_calibration_store.replace(
            build_calibration_profile(
                identity(), full_curve(), sdk_minimum=16, sdk_maximum=220
            )
        )
        controller._refresh_ae_calibration_profile()
        controller._sdk_auto_exposure_mode = SDKAutoExposureMode.CONTINUOUS
        camera.calls.clear()
        controller.set_auto_exposure_target_percent(30)
        self.assertEqual(("sdk_target", 60), camera.calls[0])
        self.assertFalse(any(call[0] in {"exposure", "gain"} for call in camera.calls))

    def test_scan_has_15_unique_clamped_targets_and_stable_fallback(self) -> None:
        candidates = calibration_candidates(16, 220)
        self.assertEqual(15, len(candidates))
        self.assertEqual(len(candidates), len(set(candidates)))
        run = AECalibrationRun(identity(), candidates, 16, 220)
        run.next_candidate()
        run.start_point(candidates[0])
        self.assertFalse(run.observe_stability(50_000, 100, 20.0))
        self.assertFalse(run.observe_stability(50_000, 100, 20.4))
        self.assertTrue(run.observe_stability(50_000, 100, 20.7))

    def test_calibration_uses_native_once_and_cancel_leaves_ae_off(self) -> None:
        camera = FakeModeCamera()
        controller = configured_controller(camera)
        controller._width, controller._height = 3840, 2160
        controller._auto_exposure_roi_requested = (0, 0, 3840, 2160)
        controller._auto_exposure_roi_readback = (0, 0, 3840, 2160)
        controller._auto_exposure_roi_mode = "FullImage"
        controller._device = SimpleNamespace(
            id="SERIAL-A",
            displayname="IUA8300KMB",
            model=SimpleNamespace(name="IUA8300KMB"),
        )
        controller._sdk_auto_exposure_mode = SDKAutoExposureMode.CONTINUOUS
        camera.auto_exposure_enable = 1
        self.assertTrue(controller.start_ae_calibration())
        first_target = calibration_candidates(16, 220)[0]
        self.assertIn(("option", nncam.NNCAM_OPTION_AUTOEXP_POLICY, 1), camera.calls)
        self.assertIn(("option", nncam.NNCAM_OPTION_AUTOEXPOSURE_PERCENT, 100), camera.calls)
        self.assertIn(("sdk_target", first_target), camera.calls)
        self.assertIn(("sdk_auto", 2), camera.calls)
        self.assertFalse(any(call[0] in {"exposure", "gain"} for call in camera.calls))
        controller.cancel_ae_calibration()
        self.assertEqual(0, camera.auto_exposure_enable)
        self.assertEqual(SDKAutoExposureMode.MANUAL, controller.sdk_auto_exposure_mode)

    def test_profile_store_json_round_trip_is_identity_scoped(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "camera_ae_calibration.json"
            profile = build_calibration_profile(
                identity(), full_curve(), sdk_minimum=16, sdk_maximum=220
            )
            store = AECalibrationProfileStore(path)
            store.replace(profile)
            reloaded = AECalibrationProfileStore(path)
            matched = reloaded.matching(identity())
            self.assertIsNotNone(matched)
            self.assertEqual(profile.target_mapping, matched.target_mapping)
            self.assertFalse(path.with_name(path.name + ".tmp").exists())


if __name__ == "__main__":
    unittest.main()
