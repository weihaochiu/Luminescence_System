from __future__ import annotations

import unittest

import numpy as np
from PySide6.QtCore import QPointF, Qt
from PySide6.QtGui import QImage
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QGraphicsView, QLabel, QToolButton

from gui.main_window_devices import MainWindowDeviceMixin
from gui.scientific_dn import mean_effective_dn_roi
from gui.widgets import ImageView
from tests.qt_test_utils import ensure_qapplication


class ScientificDNROITests(unittest.TestCase):
    def test_right_aligned_12_bit_roi_mean(self) -> None:
        scientific = np.array(
            [
                [0, 10, 20, 30, 40],
                [100, 110, 120, 130, 140],
                [200, 210, 220, 230, 240],
                [300, 310, 320, 330, 340],
            ],
            dtype=np.uint16,
        )
        expected = float(np.mean([[110, 120, 130], [210, 220, 230]]))
        self.assertEqual(
            expected,
            mean_effective_dn_roi(scientific, 12, 16, "right", 1, 1, 3, 2),
        )

    def test_left_aligned_12_bit_roi_mean(self) -> None:
        effective = np.array(
            [
                [1, 2, 3, 4],
                [100, 200, 300, 400],
                [1000, 2000, 3000, 4000],
            ],
            dtype=np.uint16,
        )
        scientific = np.left_shift(effective, 4).astype(np.uint16)
        expected = float(np.mean([[200, 300], [2000, 3000]]))
        self.assertEqual(
            expected,
            mean_effective_dn_roi(scientific, 12, 16, "left", 1, 1, 2, 2),
        )

    def test_valid_single_pixel_and_edge_rois(self) -> None:
        scientific = np.arange(20, dtype=np.uint16).reshape(4, 5)
        self.assertEqual(
            0.0,
            mean_effective_dn_roi(scientific, 12, 16, "right", 0, 0, 1, 1),
        )
        self.assertEqual(
            19.0,
            mean_effective_dn_roi(scientific, 12, 16, "right", 4, 3, 1, 1),
        )

    def test_invalid_roi_bounds_are_rejected_before_numpy_slicing(self) -> None:
        scientific = np.arange(20, dtype=np.uint16).reshape(4, 5)
        invalid = (
            (-1, 0, 1, 1),
            (0, -1, 1, 1),
            (0, 0, 0, 1),
            (0, 0, 1, 0),
            (0, 0, -1, 1),
            (0, 0, 1, -1),
            (4, 0, 2, 1),
            (0, 3, 1, 2),
            (5, 0, 1, 1),
            (0, 4, 1, 1),
        )
        for roi in invalid:
            with self.subTest(roi=roi):
                with self.assertRaises(ValueError):
                    mean_effective_dn_roi(
                        scientific, 12, 16, "right", *roi
                    )

    def test_unknown_alignment_is_rejected(self) -> None:
        scientific = np.arange(20, dtype=np.uint16).reshape(4, 5)
        with self.assertRaisesRegex(ValueError, "Alignment is unknown"):
            mean_effective_dn_roi(
                scientific, 12, 16, "unknown", 0, 0, 2, 2
            )


class ImageViewROITests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.app = ensure_qapplication()

    def setUp(self) -> None:
        self.view = ImageView()
        self.view.resize(520, 420)
        self.view.show()
        self.app.processEvents()

    def tearDown(self) -> None:
        self.view.close()

    @staticmethod
    def _image(width: int, height: int) -> QImage:
        image = QImage(width, height, QImage.Format.Format_Grayscale8)
        image.fill(0)
        return image

    def _drag_scene_roi(
        self, start: tuple[float, float], end: tuple[float, float]
    ) -> tuple[int, int, int, int]:
        selected: list[tuple[int, int, int, int]] = []
        self.view.roi_selected.connect(
            lambda x, y, width, height: selected.append((x, y, width, height))
        )
        self.assertTrue(self.view.begin_roi_selection())
        QTest.mousePress(
            self.view.viewport(),
            Qt.MouseButton.LeftButton,
            pos=self.view.mapFromScene(QPointF(*start)),
        )
        QTest.mouseMove(
            self.view.viewport(),
            self.view.mapFromScene(QPointF(*end)),
        )
        QTest.mouseRelease(
            self.view.viewport(),
            Qt.MouseButton.LeftButton,
            pos=self.view.mapFromScene(QPointF(*end)),
        )
        self.assertTrue(selected)
        return selected[-1]

    def test_fit_zoom_and_pan_keep_image_pixel_coordinates(self) -> None:
        self.view.set_image(self._image(100, 80))
        self.app.processEvents()
        fit_roi = self._drag_scene_roi((10.2, 12.2), (39.8, 35.8))
        self.assertEqual((10, 12, 30, 24), fit_roi)
        self.assertEqual(QGraphicsView.DragMode.ScrollHandDrag, self.view.dragMode())
        self.assertFalse(self.view.roi_selection_mode)

        self.view.actual_size()
        self.view.scale(2.0, 2.0)
        self.view.centerOn(QPointF(55, 42))
        self.app.processEvents()
        zoomed_roi = self._drag_scene_roi((10.2, 12.2), (39.8, 35.8))
        self.assertEqual(fit_roi, zoomed_roi)

    def test_selection_is_clamped_to_image_bounds(self) -> None:
        self.view.set_image(self._image(100, 80))
        self.view.actual_size()
        self.app.processEvents()
        roi = self._drag_scene_roi((-50, -40), (150, 120))
        self.assertEqual((0, 0, 100, 80), roi)

    def test_same_resolution_retains_roi_and_resolution_change_clears(self) -> None:
        cleared: list[bool] = []
        self.view.roi_cleared.connect(lambda: cleared.append(True))
        self.view.set_image(self._image(100, 80))
        self.view.set_roi(5, 6, 20, 30)

        self.view.set_image(self._image(100, 80))
        self.assertEqual((5, 6, 20, 30), self.view.roi)
        self.assertTrue(self.view._roi_item.isVisible())
        self.assertEqual([], cleared)

        self.view.set_image(self._image(120, 80))
        self.assertIsNone(self.view.roi)
        self.assertFalse(self.view._roi_item.isVisible())
        self.assertEqual([True], cleared)

    def test_clear_roi_and_clear_image_remove_overlay(self) -> None:
        cleared: list[bool] = []
        self.view.roi_cleared.connect(lambda: cleared.append(True))
        self.view.set_image(self._image(100, 80))
        self.view.set_roi(5, 6, 20, 30)
        self.view.clear_roi()
        self.assertIsNone(self.view.roi)
        self.assertFalse(self.view._roi_item.isVisible())
        self.assertEqual([True], cleared)

        self.view.set_roi(1, 2, 3, 4)
        self.view.clear_image()
        self.assertFalse(self.view.has_image)
        self.assertIsNone(self.view.roi)
        self.assertFalse(self.view._roi_item.isVisible())
        self.assertEqual([True, True], cleared)


class _LiveViewROIHarness(MainWindowDeviceMixin):
    def __init__(self) -> None:
        class _Controller:
            is_open = True

            def __init__(self) -> None:
                self.rois: list[tuple[int, int, int, int]] = []
                self.reset_count = 0

            def set_auto_exposure_roi(
                self, x: int, y: int, width: int, height: int
            ) -> bool:
                self.rois.append((x, y, width, height))
                return True

            def reset_auto_exposure_roi(self) -> bool:
                self.reset_count += 1
                return True

        self.controller = _Controller()
        self.image_view = ImageView()
        self.select_dn_roi_button = QToolButton()
        self.clear_dn_roi_button = QToolButton()
        self.live_view_roi_value = QLabel()
        self.live_view_roi_dn_value = QLabel()
        self.live_view_ae_metering_value = QLabel()
        self.status_message = QLabel()
        self._latest_scientific_frame = None
        self._latest_effective_dn_status = {}
        self._live_view_dn_roi = None
        self.image_view.roi_selected.connect(self.on_live_view_dn_roi_selected)
        self.image_view.roi_cleared.connect(self.on_live_view_dn_roi_cleared)


class LiveViewROIDisplayTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.app = ensure_qapplication()

    def setUp(self) -> None:
        self.harness = _LiveViewROIHarness()
        image = QImage(4, 3, QImage.Format.Format_Grayscale8)
        image.fill(0)
        self.harness.image_view.set_image(image)
        self.harness.image_view.set_roi(1, 1, 2, 2)
        self.harness.on_live_view_dn_roi_selected(1, 1, 2, 2)

    def tearDown(self) -> None:
        self.harness.image_view.close()

    def test_scientific_frame_reference_and_late_context_refresh_display(self) -> None:
        scientific = np.array(
            [
                [0, 0, 0, 0],
                [0, 1000, 2000, 0],
                [0, 3000, 4000, 0],
            ],
            dtype=np.uint16,
        )
        preview = QImage(4, 3, QImage.Format.Format_Grayscale8)
        self.harness._latest_effective_dn_status = {
            "SensorBitDepth": 12,
            "ContainerBitDepth": 16,
            "RawValueAlignment": "unknown",
            "EffectiveDNMax": 4095,
        }

        self.harness.on_scientific_frame_ready(scientific, preview, 1)
        self.assertIs(scientific, self.harness._latest_scientific_frame)
        self.assertEqual(
            "ROI 平均 DN：無法判定",
            self.harness.live_view_roi_dn_value.text(),
        )

        self.harness._latest_effective_dn_status["RawValueAlignment"] = "right"
        self.harness._refresh_live_view_roi_dn()
        self.assertEqual(
            "ROI 平均 DN：2500 /4095 (61.1%)",
            self.harness.live_view_roi_dn_value.text(),
        )

    def test_selection_forwards_exact_image_pixel_roi_to_controller(self) -> None:
        self.assertEqual([(1, 1, 2, 2)], self.harness.controller.rois)
        self.harness.on_live_view_dn_roi_selected(0, 0, 4, 3)
        self.assertEqual((0, 0, 4, 3), self.harness.controller.rois[-1])

    def test_clear_requests_full_image_ae_reset_then_clears_overlay(self) -> None:
        self.harness.clear_live_view_dn_roi()
        self.assertEqual(1, self.harness.controller.reset_count)
        self.assertIsNone(self.harness.image_view.roi)
        self.assertIsNone(self.harness._live_view_dn_roi)

    def test_ae_metering_label_uses_controller_verified_state(self) -> None:
        self.harness._refresh_live_view_ae_metering_status({
            "AutoExposureROIRequested": (1, 1, 2, 2),
            "AutoExposureROIReadback": (1, 1, 2, 2),
            "AutoExposureROIMode": "CustomROI",
            "AutoExposureROIVerified": True,
            "AutoExposureROIVerificationStatus": "Verified",
        })
        self.assertEqual("AE 測光：ROI ✓", self.harness.live_view_ae_metering_value.text())

        self.harness._refresh_live_view_ae_metering_status({
            "AutoExposureROIRequested": (1, 1, 2, 2),
            "AutoExposureROIReadback": (1, 1, 1, 2),
            "AutoExposureROIMode": "CustomROI",
            "AutoExposureROIVerified": False,
            "AutoExposureROIVerificationStatus": "ReadbackMismatch",
        })
        self.assertEqual(
            "AE 測光：ROI 驗證失敗",
            self.harness.live_view_ae_metering_value.text(),
        )

    def test_roi_labels_and_controls_reset_on_resolution_change(self) -> None:
        self.assertEqual("ROI：X=1 Y=1 2×2", self.harness.live_view_roi_value.text())
        self.assertTrue(self.harness.clear_dn_roi_button.isEnabled())

        changed = QImage(5, 3, QImage.Format.Format_Grayscale8)
        changed.fill(0)
        self.harness.image_view.set_image(changed)

        self.assertIsNone(self.harness._live_view_dn_roi)
        self.assertEqual("ROI：未設定", self.harness.live_view_roi_value.text())
        self.assertEqual("ROI 平均 DN：--", self.harness.live_view_roi_dn_value.text())
        self.assertFalse(self.harness.clear_dn_roi_button.isEnabled())
        self.assertTrue(self.harness.select_dn_roi_button.isEnabled())


if __name__ == "__main__":
    unittest.main()
