from __future__ import annotations

import unittest
from pathlib import Path
from types import SimpleNamespace

from gui.camera_auto_exposure_settings import (
    AUTO_EXPOSURE_TARGET_PERCENT_KEY,
    AUTO_EXPOSURE_TARGET_PERCENT_OPTIONS,
    DEFAULT_AUTO_EXPOSURE_TARGET_PERCENT,
    load_auto_exposure_target_percent,
    save_auto_exposure_target_percent,
    target_effective_dn,
)
from gui.camera_controller import CameraController
from gui.camera_auto_exposure_settings_dialog import CameraAutoExposureSettingsDialog
from gui.camera_exposure import ExposureMode
from gui.software_auto_exposure import SoftwareAutoExposure, SoftwareAutoExposureMode
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

    def put_AutoExpoEnable(self, mode: int) -> None:
        self.calls.append(("sdk_auto", mode))

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


def configured_controller(camera: FakeModeCamera) -> CameraController:
    controller = CameraController()
    controller._camera = camera
    controller._sensor_bit_depth = 12
    controller._raw_value_alignment = "right"
    controller._exposure_range = (100, 1_000_000, 100)
    controller._gain_range = (100, 800, 100)
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
        controller._software_auto_exposure.start_continuous()
        observed = []
        controller.exposure_changed.connect(lambda exposure, gain: observed.append((exposure, gain)))
        self.assertTrue(controller.switch_to_manual_exposure())
        self.assertEqual([("sdk_auto", 0), ("read_exposure",), ("read_gain",)], camera.calls)
        self.assertEqual([(842_500, 120)], observed)
        self.assertEqual(SoftwareAutoExposureMode.MANUAL, controller._software_auto_exposure.mode)

    def test_manual_to_continuous_keeps_sdk_ae_off(self) -> None:
        camera = FakeModeCamera()
        controller = configured_controller(camera)
        self.assertTrue(controller.enable_continuous_auto_exposure())
        self.assertEqual([("sdk_auto", 0)], camera.calls)
        self.assertEqual(SoftwareAutoExposureMode.CONTINUOUS_DN, controller._software_auto_exposure.mode)

    def test_unknown_alignment_fails_closed(self) -> None:
        camera = FakeModeCamera()
        controller = configured_controller(camera)
        controller._raw_value_alignment = "unknown"
        errors = []
        controller.error_occurred.connect(errors.append)
        self.assertFalse(controller.enable_continuous_auto_exposure())
        self.assertEqual([], camera.calls)
        self.assertIn("alignment", errors[-1])

    def test_alignment_is_known_only_when_sensor_fills_container(self) -> None:
        self.assertEqual(
            ("right", "SensorBitDepthEqualsContainerBitDepth"),
            CameraController._determine_raw_value_alignment(16, 16, 4),
        )
        self.assertEqual(
            ("unknown", "SDKDoesNotReportGrey16Alignment"),
            CameraController._determine_raw_value_alignment(12, 16, 2),
        )

    def test_resolution_restart_restores_continuous_software_mode_with_sdk_off(self) -> None:
        camera = FakeModeCamera()
        controller = resolution_controller(camera)
        controller._software_auto_exposure.start_continuous()
        try:
            controller.set_resolution(0)
            self.assertEqual([("sdk_auto", 0), ("stop",), ("size", 0), ("start",)], camera.calls)
            self.assertEqual(SoftwareAutoExposureMode.CONTINUOUS_DN, controller._software_auto_exposure.mode)
        finally:
            controller.close_camera()

    def test_resolution_restart_keeps_manual(self) -> None:
        camera = FakeModeCamera()
        controller = resolution_controller(camera)
        try:
            controller.set_resolution(0)
            self.assertEqual([("sdk_auto", 0), ("stop",), ("size", 0), ("start",)], camera.calls)
            self.assertEqual(SoftwareAutoExposureMode.MANUAL, controller._software_auto_exposure.mode)
        finally:
            controller.close_camera()

    def test_auto_once_uses_software_dn_and_sdk_off(self) -> None:
        camera = FakeModeCamera()
        controller = configured_controller(camera)
        controller.start_auto_exposure_once()
        self.assertEqual([("sdk_auto", 0)], camera.calls)
        self.assertEqual(SoftwareAutoExposureMode.AUTO_ONCE_DN, controller._software_auto_exposure.mode)

    def test_formal_manual_configuration_stops_software_ae(self) -> None:
        camera = FakeModeCamera(exposure_us=1000, gain=100)
        controller = configured_controller(camera)
        controller._software_auto_exposure.start_continuous()

        controller.set_manual_exposure(2500, 300)

        self.assertEqual(
            [("sdk_auto", 0), ("exposure", 2500), ("gain", 300),
             ("read_exposure",), ("read_gain",)],
            camera.calls,
        )
        self.assertEqual(SoftwareAutoExposureMode.MANUAL, controller._software_auto_exposure.mode)

    def test_metadata_uses_effective_dn_names(self) -> None:
        controller = configured_controller(FakeModeCamera())
        controller._effective_dn_max = 4095
        controller._latest_mean_effective_dn = 1875.3
        controller._latest_effective_dn_fraction = 1875.3 / 4095
        controller._software_auto_exposure.start_continuous()
        metadata = controller.capture_metadata()
        self.assertEqual("ContinuousDN", metadata["AutoExposureMode"])
        self.assertEqual("SoftwareDN", metadata["AutoExposureController"])
        self.assertEqual(50, metadata["AutoExposureTargetPercent"])
        self.assertEqual(2048, metadata["AutoExposureTargetDN"])
        self.assertEqual(1875.3, metadata["MeanEffectiveDN"])
        self.assertFalse(metadata["SDKAutoExposureEnabled"])
        self.assertNotIn("AutoExposureTarget", metadata)

    def test_ui_uses_dn_terms_and_settings_submenu(self) -> None:
        root = Path(__file__).parents[1]
        ui_source = (root / "gui" / "main_window_ui.py").read_text(encoding="utf-8")
        device_source = (root / "gui" / "main_window_devices.py").read_text(encoding="utf-8")
        controller_source = (root / "gui" / "camera_controller.py").read_text(encoding="utf-8")
        measurement_source = (root / "gui" / "main_window_measurement.py").read_text(encoding="utf-8")
        self.assertIn('brightness_form.addRow("目前平均 DN"', ui_source)
        self.assertIn('brightness_form.addRow("訊號比例"', ui_source)
        self.assertIn('auto_form.addRow("AE 目標"', ui_source)
        self.assertIn('auto_form.addRow("目標 DN"', ui_source)
        self.assertIn('settings_menu.addMenu("相機")', ui_source)
        self.assertNotIn("目前預覽亮度", ui_source)
        self.assertNotIn("PreviewBrightness8bit", device_source)
        self.assertNotIn("equivalent_brightness_8bit", controller_source)
        self.assertNotIn("put_AutoExpoTarget", controller_source)
        self.assertNotIn("put_AutoExpoEnable(1)", controller_source)
        self.assertNotIn("put_AutoExpoEnable(2)", controller_source)
        self.assertIn("self.controller.stop_software_auto_exposure()", measurement_source)


class SoftwareAutoExposureTests(unittest.TestCase):
    def setUp(self) -> None:
        self.ae = SoftwareAutoExposure(50)
        self.ae.start_continuous()
        self.exposure_range = (100, 10_000, 100)
        self.gain_range = (100, 800, 100)

    def decision(self, mean, exposure=1000, gain=100):
        return self.ae.update(
            mean_dn=mean,
            maximum_dn=4095,
            exposure_us=exposure,
            gain_percent=gain,
            exposure_range=self.exposure_range,
            gain_range=self.gain_range,
        )

    def test_dark_frames_increase_exposure_with_clamped_step(self) -> None:
        self.assertGreater(self.decision(500).exposure_us, 1000)
        self.assertGreater(self.decision(1500).exposure_us, 1000)

    def test_deadband_and_exact_target_make_no_adjustment(self) -> None:
        self.assertFalse(self.decision(2000).adjusted)
        self.assertFalse(self.decision(2048).adjusted)

    def test_bright_frame_decreases_exposure_at_nominal_gain(self) -> None:
        decision = self.decision(3000)
        self.assertLess(decision.exposure_us, 1000)
        self.assertEqual(100, decision.gain_percent)

    def test_exposure_max_then_dark_increases_gain(self) -> None:
        decision = self.decision(500, exposure=10_000, gain=100)
        self.assertEqual(10_000, decision.exposure_us)
        self.assertGreater(decision.gain_percent, 100)

    def test_bright_frame_reduces_gain_before_exposure(self) -> None:
        decision = self.decision(3000, exposure=5000, gain=200)
        self.assertEqual(5000, decision.exposure_us)
        self.assertLess(decision.gain_percent, 200)
        self.assertGreaterEqual(decision.gain_percent, 100)

    def test_auto_once_requires_two_consecutive_deadband_frames(self) -> None:
        self.ae.start_once()
        first = self.decision(2048)
        second = self.decision(2000)
        self.assertFalse(first.converged)
        self.assertTrue(second.converged)
        self.assertEqual(SoftwareAutoExposureMode.MANUAL, self.ae.mode)

    def test_target_change_applies_to_next_decision(self) -> None:
        self.ae.set_target_percent(40)
        decision = self.decision(1638)
        self.assertEqual(1638, decision.target_dn)
        self.assertFalse(decision.adjusted)


if __name__ == "__main__":
    unittest.main()
