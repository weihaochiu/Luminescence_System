from __future__ import annotations

import unittest
from pathlib import Path
from types import SimpleNamespace

from PySide6.QtGui import QColor, QImage

from gui.camera_controller import CameraController
from gui.camera_exposure import (
    DEFAULT_AUTO_EXPOSURE_TARGET,
    PREVIEW_BRIGHTNESS_8BIT_MAX,
    ExposureMode,
)
from gui.image_brightness import equivalent_brightness_8bit
from tests.qt_test_utils import ensure_qapplication


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
    def __init__(self, *, auto_mode: int = 1, target_readback: int = 120) -> None:
        self.calls: list[tuple] = []
        self.auto_mode = auto_mode
        self.target_readback = target_readback

    def put_AutoExpoEnable(self, mode: int) -> None:
        self.calls.append(("auto", mode))
        self.auto_mode = mode

    def get_AutoExpoEnable(self) -> int:
        self.calls.append(("get_auto",))
        return self.auto_mode

    def put_AutoExpoTarget(self, target: int) -> None:
        self.calls.append(("target", target))

    def get_AutoExpoTarget(self) -> int:
        self.calls.append(("target_readback",))
        return self.target_readback

    def get_ExpoTime(self) -> int:
        self.calls.append(("read_exposure",))
        return 842_500

    def get_ExpoAGain(self) -> int:
        self.calls.append(("read_gain",))
        return 120

    def Stop(self) -> None:
        self.calls.append(("stop",))

    def put_eSize(self, index: int) -> None:
        self.calls.append(("size", index))

    def get_eSize(self) -> int:
        return 0

    def StartPullModeWithCallback(self, _callback, _context) -> None:
        self.calls.append(("start",))


def _resolution_controller(camera: FakeModeCamera) -> CameraController:
    controller = CameraController()
    controller._camera = camera
    resolution = SimpleNamespace(width=5, height=4)
    controller._device = SimpleNamespace(
        model=SimpleNamespace(preview=1, res=[resolution])
    )
    controller._camera_is_mono = True
    controller._scientific_pull_bits = 16
    return controller


class CameraExposureTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.app = ensure_qapplication()

    def test_modes_and_fixed_target_constants(self) -> None:
        self.assertEqual("持續自動曝光", ExposureMode.CONTINUOUS_AUTO.label)
        self.assertEqual("手動曝光", ExposureMode.MANUAL.label)
        self.assertEqual(120, DEFAULT_AUTO_EXPOSURE_TARGET)
        self.assertEqual(255, PREVIEW_BRIGHTNESS_8BIT_MAX)

    def test_capabilities_keep_hardware_and_auto_ranges_separate(self) -> None:
        result = CameraController._query_camera_capabilities(FakeCameraCapabilities())
        self.assertEqual((30, 15_000_000, 10_000), result["exposure_range_us"])
        self.assertEqual((100, 800, 100), result["gain_range"])
        self.assertEqual((40, 400_000, 110, 600), result["auto_exposure_range"])

    def test_preview_brightness_uses_fixed_eight_bit_luminance(self) -> None:
        image = QImage(8, 8, QImage.Format.Format_RGB888)
        image.fill(QColor(120, 120, 120))
        self.assertEqual(120, equivalent_brightness_8bit(image))

        red = QImage(4, 4, QImage.Format.Format_RGB888)
        red.fill(QColor(255, 0, 0))
        self.assertEqual(54, equivalent_brightness_8bit(red))
        self.assertLessEqual(equivalent_brightness_8bit(red), PREVIEW_BRIGHTNESS_8BIT_MAX)

    def test_null_image_has_no_preview_brightness(self) -> None:
        self.assertIsNone(equivalent_brightness_8bit(QImage()))

    def test_continuous_to_manual_preserves_actual_readback(self) -> None:
        controller = CameraController()
        camera = FakeModeCamera()
        controller._camera = camera
        observed: list[tuple[int, int]] = []
        controller.exposure_changed.connect(
            lambda exposure, gain: observed.append((exposure, gain))
        )

        self.assertTrue(controller.switch_to_manual_exposure())
        self.assertEqual(
            [("auto", 0), ("read_exposure",), ("read_gain",)], camera.calls
        )
        self.assertEqual([(842_500, 120)], observed)

    def test_manual_to_continuous_sets_fixed_target_before_enable(self) -> None:
        controller = CameraController()
        camera = FakeModeCamera(auto_mode=0)
        controller._camera = camera

        self.assertTrue(controller.enable_continuous_auto_exposure())
        self.assertEqual(
            [("target", 120), ("target_readback",), ("auto", 1)], camera.calls
        )

    def test_target_readback_mismatch_warns_but_continuous_ae_still_enables(self) -> None:
        controller = CameraController()
        camera = FakeModeCamera(auto_mode=0, target_readback=119)
        controller._camera = camera

        with self.assertLogs("gui.camera_controller", level="WARNING") as captured:
            self.assertTrue(controller.enable_continuous_auto_exposure())
        self.assertEqual(("auto", 1), camera.calls[-1])
        self.assertIn("readback mismatch", "\n".join(captured.output))

    def test_resolution_restart_restores_fixed_target_for_continuous_ae(self) -> None:
        camera = FakeModeCamera(auto_mode=1)
        controller = _resolution_controller(camera)
        try:
            controller.set_resolution(0)
            self.assertEqual(
                [
                    ("get_auto",),
                    ("stop",),
                    ("size", 0),
                    ("start",),
                    ("target", 120),
                    ("target_readback",),
                    ("auto", 1),
                ],
                camera.calls,
            )
        finally:
            controller.close_camera()

    def test_resolution_restart_keeps_manual_without_setting_auto_target(self) -> None:
        camera = FakeModeCamera(auto_mode=0)
        controller = _resolution_controller(camera)
        try:
            controller.set_resolution(0)
            self.assertEqual(
                [
                    ("get_auto",),
                    ("stop",),
                    ("size", 0),
                    ("start",),
                    ("auto", 0),
                ],
                camera.calls,
            )
            self.assertFalse(any(call[0] == "target" for call in camera.calls))
        finally:
            controller.close_camera()

    def test_auto_exposure_once_sets_fixed_target_before_mode_two(self) -> None:
        controller = CameraController()
        camera = FakeModeCamera(auto_mode=0)
        controller._camera = camera

        controller.start_auto_exposure_once()
        self.assertEqual(
            [("target", 120), ("target_readback",), ("auto", 2)], camera.calls
        )

    def test_camera_metadata_distinguishes_auto_mode_and_fixed_target(self) -> None:
        controller = CameraController()
        controller._camera = FakeModeCamera()
        for mode, expected_mode, expected_target in (
            (0, "manual", None),
            (1, "continuous", 120),
            (2, "auto_once", 120),
        ):
            with self.subTest(mode=mode):
                controller._auto_mode = mode
                metadata = controller.capture_metadata()
                self.assertEqual(expected_mode, metadata["AutoExposureMode"])
                self.assertEqual(expected_target, metadata["AutoExposureTarget"])

    def test_ui_has_no_target_input_and_names_preview_brightness(self) -> None:
        root = Path(__file__).parents[1]
        ui_source = (root / "gui" / "main_window_ui.py").read_text(encoding="utf-8")
        device_source = (root / "gui" / "main_window_devices.py").read_text(
            encoding="utf-8"
        )
        self.assertIn("QStackedWidget", ui_source)
        self.assertIn('exposure_form.addRow("曝光模式"', ui_source)
        self.assertIn('auto_form.addRow("目前曝光時間"', ui_source)
        self.assertIn('auto_form.addRow("目前 Gain"', ui_source)
        self.assertIn('brightness_form.addRow("目前預覽亮度"', ui_source)
        self.assertIn("PREVIEW_BRIGHTNESS_8BIT_MAX", ui_source)
        self.assertIn("PREVIEW_BRIGHTNESS_8BIT_MAX", device_source)
        self.assertIn("Live View 8-bit 預覽影像", ui_source)
        self.assertNotIn("auto_target_edit", ui_source)
        self.assertNotIn("影像亮度目標", ui_source)
        self.assertNotIn("apply_auto_exposure_target", device_source)
        self.assertNotIn("_last_valid_auto_target", device_source)


if __name__ == "__main__":
    unittest.main()
