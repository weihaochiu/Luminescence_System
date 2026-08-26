from __future__ import annotations

import unittest
from pathlib import Path
from types import SimpleNamespace

from gui.camera_auto_exposure_settings import (
    AUTO_EXPOSURE_TARGET_PERCENT_KEY,
    AUTO_EXPOSURE_TARGET_PERCENT_OPTIONS,
    DEFAULT_AUTO_EXPOSURE_TARGET_PERCENT,
    default_sdk_target_guess,
    load_auto_exposure_target_percent,
    save_auto_exposure_target_percent,
    target_effective_dn,
)
from gui.camera_controller import CameraController, SDKAutoExposureMode
from gui.camera_auto_exposure_settings_dialog import CameraAutoExposureSettingsDialog
from gui.camera_exposure import ExposureMode
from gui.scientific_dn_alignment import AlignmentVerifier
from gui.sdk import nncam
from tests.qt_test_utils import ensure_qapplication


class FakeSettings:
    def __init__(self, value=None) -> None:
        self.data = {}
        if value is not None:
            self.data[AUTO_EXPOSURE_TARGET_PERCENT_KEY] = value

    def value(self, key, default=None):
        return self.data.get(key, default)

    def setValue(self, key, value) -> None:
        self.data[key] = value


class FakeCameraCapabilities:
    def get_ExpTimeRange(self):
        return 30, 15_000_000, 10_000

    def get_ExpoAGainRange(self):
        return 100, 800, 100

    def get_AutoExpoRange(self):
        return 350_000, 30, 500, 100

    def get_MinAutoExpoTimeAGain(self):
        return 40, 110

    def get_MaxAutoExpoTimeAGain(self):
        return 400_000, 600


class FakeModeCamera:
    def __init__(self, *, exposure_us: int = 842_500, gain: int = 120) -> None:
        self.calls: list[tuple] = []
        self.exposure_us = exposure_us
        self.gain = gain
        self.auto_exposure_enable = 0
        self.auto_exposure_target = 120
        self.ae_aux_rect = (0, 0, 4, 3)
        self.options = {
            nncam.NNCAM_OPTION_AUTOEXP_POLICY: 1,
            nncam.NNCAM_OPTION_AUTOEXPOSURE_PERCENT: 100,
            nncam.NNCAM_OPTION_AUTOEXP_EXPOTIME_DAMP: 0,
            nncam.NNCAM_OPTION_AUTOEXP_GAIN_DAMP: 0,
            nncam.NNCAM_OPTION_OVEREXP_POLICY: 0,
        }

    def put_AutoExpoEnable(self, mode: int) -> None:
        self.calls.append(("sdk_auto", mode))
        self.auto_exposure_enable = mode

    def get_AutoExpoEnable(self) -> int:
        self.calls.append(("read_sdk_auto",))
        return self.auto_exposure_enable

    def put_AutoExpoTarget(self, target: int) -> None:
        self.calls.append(("sdk_target", target))
        self.auto_exposure_target = target

    def get_AutoExpoTarget(self) -> int:
        self.calls.append(("read_sdk_target",))
        return self.auto_exposure_target

    def put_AEAuxRect(self, x: int, y: int, width: int, height: int) -> None:
        self.calls.append(("ae_roi", x, y, width, height))
        self.ae_aux_rect = (x, y, width, height)

    def get_AEAuxRect(self) -> tuple[int, int, int, int]:
        self.calls.append(("read_ae_roi",))
        return self.ae_aux_rect

    def put_Option(self, option: int, value: int) -> None:
        self.calls.append(("option", option, value))
        self.options[option] = value

    def get_Option(self, option: int) -> int:
        self.calls.append(("read_option", option))
        return self.options[option]

    def get_ExpoTime(self) -> int:
        self.calls.append(("read_exposure",))
        return self.exposure_us

    def get_ExpoAGain(self) -> int:
        self.calls.append(("read_gain",))
        return self.gain

    def put_ExpoTime(self, value: int) -> None:
        self.calls.append(("exposure", value))
        self.exposure_us = value

    def put_ExpoAGain(self, value: int) -> None:
        self.calls.append(("gain", value))
        self.gain = value

    def Stop(self) -> None:
        self.calls.append(("stop",))

    def put_eSize(self, index: int) -> None:
        self.calls.append(("size", index))

    def get_eSize(self) -> int:
        return 0

    def StartPullModeWithCallback(self, _callback, _context) -> None:
        self.calls.append(("start",))

    def Close(self) -> None:
        pass


class StickyAutoExposureCamera(FakeModeCamera):
    def get_AutoExpoEnable(self) -> int:
        self.calls.append(("read_sdk_auto",))
        return 1


def configured_controller(camera: FakeModeCamera) -> CameraController:
    controller = CameraController()
    controller._camera = camera
    controller._width, controller._height = 4, 3
    controller._sensor_bit_depth = 12
    controller._raw_value_alignment = "right"
    controller._exposure_range = (100, 1_000_000, 10_000)
    controller._gain_range = (100, 800, 100)
    controller._auto_exposure_range = (40, 400_000, 110, 600)
    controller._auto_exposure_roi_requested = (0, 0, 4, 3)
    controller._auto_exposure_roi_readback = (0, 0, 4, 3)
    controller._auto_exposure_roi_mode = "FullImage"
    controller._auto_exposure_roi_verified = True
    controller._auto_exposure_roi_verification_status = "Verified"
    return controller


def resolution_controller(camera: FakeModeCamera) -> CameraController:
    controller = configured_controller(camera)
    resolution = SimpleNamespace(width=5, height=4)
    controller._device = SimpleNamespace(model=SimpleNamespace(preview=1, res=[resolution]))
    controller._camera_is_mono = True
    controller._scientific_pull_bits = 16
    return controller


class CameraExposureTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.app = ensure_qapplication()

    def test_modes_and_default_target_percent(self) -> None:
        self.assertEqual("持續自動曝光", ExposureMode.CONTINUOUS_AUTO.label)
        self.assertEqual("手動曝光", ExposureMode.MANUAL.label)
        self.assertEqual(50, DEFAULT_AUTO_EXPOSURE_TARGET_PERCENT)
        self.assertEqual((20, 30, 40, 50, 60, 70, 80), AUTO_EXPOSURE_TARGET_PERCENT_OPTIONS)

    def test_target_percentage_conversions(self) -> None:
        cases = ((255, 50, 128), (4095, 40, 1638), (4095, 50, 2048), (16383, 50, 8192))
        for maximum, percent, expected in cases:
            with self.subTest(maximum=maximum, percent=percent):
                self.assertEqual(expected, target_effective_dn(maximum, percent))

    def test_uncalibrated_initial_guess_is_deterministic_and_clamped(self) -> None:
        expected = {20: 51, 30: 77, 40: 102, 50: 128, 60: 153, 70: 179, 80: 204}
        for percent, target in expected.items():
            with self.subTest(percent=percent):
                self.assertEqual(target, default_sdk_target_guess(percent))
                self.assertGreaterEqual(target, nncam.NNCAM_AETARGET_MIN)
                self.assertLessEqual(target, nncam.NNCAM_AETARGET_MAX)

    def test_settings_store_integer_percent_and_invalid_falls_back(self) -> None:
        settings = FakeSettings()
        self.assertEqual(50, load_auto_exposure_target_percent(settings))
        save_auto_exposure_target_percent(settings, 40)
        self.assertEqual(40, settings.data[AUTO_EXPOSURE_TARGET_PERCENT_KEY])
        self.assertEqual(40, load_auto_exposure_target_percent(settings))
        self.assertEqual(50, load_auto_exposure_target_percent(FakeSettings(45)))

    def test_settings_dialog_offers_only_supported_percentages(self) -> None:
        settings = FakeSettings(50)
        dialog = CameraAutoExposureSettingsDialog(settings)
        try:
            self.assertEqual(
                list(AUTO_EXPOSURE_TARGET_PERCENT_OPTIONS),
                [
                    dialog.target_percent_combo.itemData(index)
                    for index in range(dialog.target_percent_combo.count())
                ],
            )
            self.assertEqual(50, dialog.target_percent)
            dialog.target_percent_combo.setCurrentIndex(
                dialog.target_percent_combo.findData(40)
            )
            dialog.accept()
            self.assertEqual(40, settings.data[AUTO_EXPOSURE_TARGET_PERCENT_KEY])
        finally:
            dialog.close()

    def test_capabilities_keep_hardware_and_sdk_auto_ranges_separate(self) -> None:
        result = CameraController._query_camera_capabilities(FakeCameraCapabilities())
        self.assertEqual((30, 15_000_000, 10_000), result["exposure_range_us"])
        self.assertEqual((100, 800, 100), result["gain_range"])
        self.assertEqual((40, 400_000, 110, 600), result["auto_exposure_range"])

    def test_continuous_to_manual_disables_sdk_ae_and_preserves_readback(self) -> None:
        camera = FakeModeCamera()
        controller = configured_controller(camera)
        controller._sdk_auto_exposure_mode = SDKAutoExposureMode.CONTINUOUS
        camera.auto_exposure_enable = 1
        observed = []
        controller.exposure_changed.connect(lambda exposure, gain: observed.append((exposure, gain)))
        self.assertTrue(controller.switch_to_manual_exposure())
        self.assertEqual(("sdk_auto", 0), camera.calls[0])
        self.assertEqual(("read_sdk_auto",), camera.calls[1])
        self.assertEqual([(842_500, 120)], observed)
        self.assertEqual(SDKAutoExposureMode.MANUAL, controller._sdk_auto_exposure_mode)

    def test_manual_to_continuous_configures_native_sdk_ae_in_order(self) -> None:
        camera = FakeModeCamera()
        controller = configured_controller(camera)
        self.assertTrue(controller.enable_continuous_auto_exposure())
        policy = ("option", nncam.NNCAM_OPTION_AUTOEXP_POLICY, 1)
        full_average = ("option", nncam.NNCAM_OPTION_AUTOEXPOSURE_PERCENT, 100)
        target = ("sdk_target", 128)
        enabled = ("sdk_auto", 1)
        self.assertLess(camera.calls.index(policy), camera.calls.index(target))
        self.assertLess(camera.calls.index(full_average), camera.calls.index(target))
        self.assertLess(camera.calls.index(target), camera.calls.index(enabled))
        self.assertNotIn(("exposure", 0), camera.calls)
        self.assertFalse(any(call[0] in {"exposure", "gain"} for call in camera.calls))
        self.assertEqual(SDKAutoExposureMode.CONTINUOUS, controller._sdk_auto_exposure_mode)

    def test_unknown_alignment_does_not_block_native_sdk_ae(self) -> None:
        camera = FakeModeCamera()
        controller = configured_controller(camera)
        controller._raw_value_alignment = "unknown"
        controller._alignment_verifier = AlignmentVerifier(12, 16)
        self.assertTrue(controller.enable_continuous_auto_exposure())
        self.assertIn(("sdk_auto", 1), camera.calls)
        self.assertTrue(controller._continuous_auto_exposure_requested)
        self.assertEqual(SDKAutoExposureMode.CONTINUOUS, controller._sdk_auto_exposure_mode)

    def test_alignment_is_known_only_when_sensor_fills_container(self) -> None:
        self.assertEqual(
            ("right", "SensorBitDepthEqualsContainerBitDepth"),
            CameraController._determine_raw_value_alignment(16, 16, 4),
        )
        self.assertEqual(
            ("unknown", "RuntimeVerificationPending"),
            CameraController._determine_raw_value_alignment(12, 16, 2),
        )

    def test_target_change_only_updates_sdk_target(self) -> None:
        camera = FakeModeCamera()
        controller = configured_controller(camera)
        controller._effective_dn_max = 4095
        controller.enable_continuous_auto_exposure()
        camera.calls.clear()
        with self.assertLogs("gui.camera_controller", level="INFO") as captured:
            controller.set_auto_exposure_target_percent(40)
        self.assertEqual(("sdk_target", 102), camera.calls[0])
        self.assertEqual(("read_sdk_target",), camera.calls[1])
        self.assertFalse(any(call[0] in {"exposure", "gain"} for call in camera.calls))
        self.assertEqual(1638, controller._effective_dn_status()["AutoExposureTargetDN"])
        calibration = "\n".join(captured.output)
        self.assertIn("UserTargetPercent=40%", calibration)
        self.assertIn("EffectiveDNTarget=1638/4095", calibration)
        self.assertIn("SDKAutoExposureTarget=102", calibration)

    def test_resolution_restart_restores_native_continuous_mode(self) -> None:
        camera = FakeModeCamera()
        controller = resolution_controller(camera)
        controller._sdk_auto_exposure_mode = SDKAutoExposureMode.CONTINUOUS
        camera.auto_exposure_enable = 1
        try:
            controller.set_resolution(0)
            self.assertIn(("sdk_auto", 0), camera.calls)
            self.assertIn(("stop",), camera.calls)
            self.assertIn(("start",), camera.calls)
            self.assertIn(("sdk_auto", 1), camera.calls)
            self.assertEqual(SDKAutoExposureMode.CONTINUOUS, controller._sdk_auto_exposure_mode)
        finally:
            controller.close_camera()

    def test_resolution_restart_keeps_manual(self) -> None:
        camera = FakeModeCamera()
        controller = resolution_controller(camera)
        try:
            controller.set_resolution(0)
            self.assertIn(("sdk_auto", 0), camera.calls)
            self.assertNotIn(("sdk_auto", 1), camera.calls)
            self.assertEqual(SDKAutoExposureMode.MANUAL, controller._sdk_auto_exposure_mode)
        finally:
            controller.close_camera()

    def test_auto_once_uses_sdk_mode_two_and_convergence_locks_ae(self) -> None:
        camera = FakeModeCamera()
        controller = configured_controller(camera)
        results = []
        controller.auto_exposure_result.connect(
            lambda success, message: results.append((success, message))
        )
        controller.start_auto_exposure_once()
        self.assertIn(("sdk_auto", 2), camera.calls)
        self.assertEqual(SDKAutoExposureMode.ONCE, controller._sdk_auto_exposure_mode)
        controller._handle_sdk_event(nncam.NNCAM_EVENT_AUTOEXPO_CONV)
        self.assertIn(("sdk_auto", 0), camera.calls)
        self.assertEqual(SDKAutoExposureMode.MANUAL, controller._sdk_auto_exposure_mode)
        self.assertTrue(results[-1][0])

    def test_formal_manual_configuration_verifies_sdk_ae_off_first(self) -> None:
        camera = FakeModeCamera(exposure_us=1000, gain=100)
        controller = configured_controller(camera)
        controller._sdk_auto_exposure_mode = SDKAutoExposureMode.CONTINUOUS
        camera.auto_exposure_enable = 1

        controller.set_manual_exposure(2500, 300)

        off_index = camera.calls.index(("sdk_auto", 0))
        off_readback_index = camera.calls.index(("read_sdk_auto",))
        exposure_index = camera.calls.index(("exposure", 2500))
        gain_index = camera.calls.index(("gain", 300))
        self.assertLess(off_index, off_readback_index)
        self.assertLess(off_readback_index, exposure_index)
        self.assertLess(exposure_index, gain_index)
        self.assertEqual(SDKAutoExposureMode.MANUAL, controller._sdk_auto_exposure_mode)

    def test_formal_measurement_is_blocked_when_sdk_ae_off_readback_fails(self) -> None:
        camera = StickyAutoExposureCamera()
        controller = configured_controller(camera)
        errors = []
        controller.error_occurred.connect(errors.append)
        self.assertFalse(controller.disable_auto_exposure_for_formal_measurement())
        self.assertIn(("sdk_auto", 0), camera.calls)
        self.assertIn("read back 1", errors[-1])

    def test_metadata_uses_effective_dn_names(self) -> None:
        camera = FakeModeCamera()
        controller = configured_controller(camera)
        controller._effective_dn_max = 4095
        controller._latest_mean_effective_dn = 1875.3
        controller._latest_effective_dn_fraction = 1875.3 / 4095
        controller._sdk_auto_exposure_mode = SDKAutoExposureMode.CONTINUOUS
        controller._sdk_auto_exposure_enable_readback = 1
        controller._sdk_auto_exposure_target_readback = 128
        controller._sdk_auto_exposure_policy_readback = 1
        controller._sdk_auto_exposure_percent_readback = 100
        controller._sdk_auto_exposure_exposure_damping_readback = 0
        controller._sdk_auto_exposure_gain_damping_readback = 0
        controller._sdk_overexposure_policy_readback = 0
        metadata = controller.capture_metadata()
        self.assertEqual("Continuous", metadata["AutoExposureMode"])
        self.assertEqual("RisingCamSDK", metadata["AutoExposureController"])
        self.assertEqual(50, metadata["AutoExposureTargetPercent"])
        self.assertEqual(2048, metadata["EffectiveDNTarget"])
        self.assertEqual(128, metadata["SDKAutoExposureTarget"])
        self.assertEqual(128, metadata["SDKAutoExposureTargetReadback"])
        self.assertEqual(1, metadata["SDKAutoExposurePolicy"])
        self.assertEqual(100, metadata["SDKAutoExposurePercent"])
        self.assertEqual(0, metadata["SDKAutoExposureExposureDamping"])
        self.assertEqual(0, metadata["SDKAutoExposureGainDamping"])
        self.assertEqual(0, metadata["SDKOverexposurePolicy"])
        self.assertEqual(40, metadata["AutoExposureMinExposure"])
        self.assertEqual(400_000, metadata["AutoExposureMaxExposure"])
        self.assertEqual(100, metadata["ExposureMinUs"])
        self.assertEqual(1_000_000, metadata["ExposureMaxUs"])
        self.assertEqual(10_000, metadata["ExposureDefaultUs"])
        self.assertEqual(100, metadata["GainMin"])
        self.assertEqual(800, metadata["GainMax"])
        self.assertEqual(100, metadata["GainDefault"])
        self.assertEqual(1875.3, metadata["MeanEffectiveDN"])
        self.assertFalse(metadata["AutoExposureCalibrationApplied"])
        self.assertIsNone(metadata["AutoExposureCalibrationProfileId"])
        self.assertIsNone(metadata["AutoExposureCalibrationDate"])
        self.assertIsNone(metadata["AutoExposureCalibrationResolution"])
        self.assertTrue(metadata["SDKAutoExposureEnabled"])
        self.assertNotIn("AutoExposureTarget", metadata)

    def test_restore_exposure_state_restores_readbacks_then_continuous_ae(self) -> None:
        camera = FakeModeCamera(exposure_us=9000, gain=450)
        controller = configured_controller(camera)
        controller._sdk_auto_exposure_mode = SDKAutoExposureMode.MANUAL
        controller.restore_exposure_state({
            "ExposureReadbackUs": 2500,
            "GainReadback": 150,
            "AutoExposureMode": SDKAutoExposureMode.CONTINUOUS.value,
        })
        self.assertEqual(2500, camera.exposure_us)
        self.assertEqual(150, camera.gain)
        self.assertEqual(1, camera.auto_exposure_enable)
        self.assertEqual(SDKAutoExposureMode.CONTINUOUS, controller._sdk_auto_exposure_mode)
        off_index = camera.calls.index(("sdk_auto", 0))
        exposure_index = camera.calls.index(("exposure", 2500))
        gain_index = camera.calls.index(("gain", 150))
        on_index = len(camera.calls) - 1 - camera.calls[::-1].index(("sdk_auto", 1))
        self.assertLess(off_index, exposure_index)
        self.assertLess(exposure_index, gain_index)
        self.assertLess(gain_index, on_index)

    def test_ui_uses_dn_terms_and_settings_submenu(self) -> None:
        root = Path(__file__).parents[1]
        ui_source = (root / "gui" / "main_window_ui.py").read_text(encoding="utf-8")
        device_source = (root / "gui" / "main_window_devices.py").read_text(encoding="utf-8")
        controller_source = (root / "gui" / "camera_controller.py").read_text(encoding="utf-8")
        measurement_source = (root / "gui" / "main_window_measurement.py").read_text(encoding="utf-8")
        self.assertIn('brightness_form.addRow(tr("camera.mean_dn_current")', ui_source)
        self.assertIn('brightness_form.addRow(tr("camera.signal_ratio")', ui_source)
        self.assertIn('auto_form.addRow(tr("camera.ae_target")', ui_source)
        self.assertIn('auto_form.addRow(tr("camera.target_dn")', ui_source)
        self.assertIn('settings_menu.addMenu(tr("menu.camera_plain"))', ui_source)
        self.assertNotIn("目前預覽亮度", ui_source)
        self.assertNotIn("PreviewBrightness8bit", device_source)
        self.assertNotIn("equivalent_brightness_8bit", controller_source)
        self.assertIn("put_AutoExpoTarget", controller_source)
        self.assertIn("SDKAutoExposureMode.CONTINUOUS", controller_source)
        self.assertIn("SDKAutoExposureMode.ONCE", controller_source)
        self.assertNotIn("SoftwareAutoExposure", controller_source)
        self.assertNotIn("_apply_software_auto_exposure", controller_source)
        self.assertIn(
            "self.controller.disable_auto_exposure_for_formal_measurement()",
            measurement_source,
        )


if __name__ == "__main__":
    unittest.main()
