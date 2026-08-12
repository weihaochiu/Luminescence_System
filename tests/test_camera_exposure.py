from __future__ import annotations

import unittest
from pathlib import Path

from PySide6.QtGui import QColor, QImage

from gui.camera_controller import CameraController
from gui.camera_exposure import ExposureMode, validate_auto_target
from gui.image_brightness import equivalent_brightness_8bit


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
    def __init__(self) -> None:
        self.calls: list[tuple] = []

    def put_AutoExpoEnable(self, mode: int) -> None:
        self.calls.append(("auto", mode))

    def put_AutoExpoTarget(self, target: int) -> None:
        self.calls.append(("target", target))

    def get_ExpoTime(self) -> int:
        self.calls.append(("read_exposure",))
        return 842_500

    def get_ExpoAGain(self) -> int:
        self.calls.append(("read_gain",))
        return 120


class CameraExposureTests(unittest.TestCase):
    def test_modes_have_required_traditional_chinese_labels(self) -> None:
        self.assertEqual("持續自動曝光", ExposureMode.CONTINUOUS_AUTO.label)
        self.assertEqual("手動曝光", ExposureMode.MANUAL.label)

    def test_target_validation_never_clamps(self) -> None:
        self.assertEqual(120, validate_auto_target(120))
        for invalid in (15, 221):
            with self.subTest(value=invalid), self.assertRaisesRegex(ValueError, "16–220"):
                validate_auto_target(invalid)

    def test_capabilities_keep_hardware_and_auto_ranges_separate(self) -> None:
        result = CameraController._query_camera_capabilities(FakeCameraCapabilities())
        self.assertEqual((30, 15_000_000, 10_000), result["exposure_range_us"])
        self.assertEqual((100, 800, 100), result["gain_range"])
        self.assertEqual((40, 400_000, 110, 600), result["auto_exposure_range"])

    def test_brightness_uses_eight_bit_luminance(self) -> None:
        image = QImage(8, 8, QImage.Format.Format_RGB888)
        image.fill(QColor(120, 120, 120))
        self.assertEqual(120, equivalent_brightness_8bit(image))

        red = QImage(4, 4, QImage.Format.Format_RGB888)
        red.fill(QColor(255, 0, 0))
        self.assertEqual(54, equivalent_brightness_8bit(red))

    def test_null_image_has_no_brightness(self) -> None:
        self.assertIsNone(equivalent_brightness_8bit(QImage()))

    def test_mode_switch_preserves_actual_values_and_applies_target_first(self) -> None:
        controller = CameraController()
        camera = FakeModeCamera()
        controller._camera = camera
        observed: list[tuple[int, int]] = []
        controller.exposure_changed.connect(lambda exposure, gain: observed.append((exposure, gain)))

        self.assertTrue(controller.switch_to_manual_exposure())
        self.assertEqual(
            [("auto", 0), ("read_exposure",), ("read_gain",)], camera.calls
        )
        self.assertEqual([(842_500, 120)], observed)

        camera.calls.clear()
        self.assertTrue(controller.enable_continuous_auto_exposure(130))
        self.assertEqual([("target", 130), ("auto", 1)], camera.calls)

    def test_ui_uses_mode_stack_and_required_terms(self) -> None:
        root = Path(__file__).parents[1]
        source = (root / "gui" / "main_window_ui.py").read_text(encoding="utf-8")
        self.assertIn("QStackedWidget", source)
        self.assertIn('exposure_form.addRow("曝光模式"', source)
        self.assertIn('auto_form.addRow("影像亮度目標"', source)
        self.assertIn('brightness_form.addRow("目前影像亮度"', source)
        self.assertNotIn('"曝光目標"', source)
        self.assertNotIn('"曝光亮度"', source)


if __name__ == "__main__":
    unittest.main()
