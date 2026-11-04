from __future__ import annotations

import threading
import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

from PySide6.QtCore import QPointF, QTimer, Qt
from PySide6.QtGui import QImage
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QPushButton

from gui.camera_controller import CameraController
from gui.main_window_devices import MainWindowDeviceMixin
from gui.recipe_roi_dialog import RecipeROIDialog
from gui.sdk import nncam
from gui.widgets import ImageView
from tests.qt_test_utils import ensure_qapplication
from tests.test_recipe_channel_roi import CameraSignals


class PreviewEventTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = ensure_qapplication()

    def setUp(self):
        self.controller = CameraController()
        self.controller._camera = Mock()
        self.addCleanup(self.controller.close_camera)

    def send_images(self, count, generation=None):
        controller = self.controller
        context = (controller, controller._stream_generation if generation is None else generation)
        thread = threading.Thread(target=lambda: [
            controller._camera_callback(nncam.NNCAM_EVENT_IMAGE, context)
            for _ in range(count)
        ])
        thread.start()
        thread.join(3)
        self.assertFalse(thread.is_alive())

    def test_preview_burst_does_not_delay_cancel_behind_every_frame(self):
        cancel = QPushButton()
        processed_at_cancel = []
        with patch.object(self.controller, "_pull_live_frame") as pull:
            cancel.clicked.connect(lambda: processed_at_cancel.append(pull.call_count))
            self.send_images(2000)
            QTimer.singleShot(0, cancel.click)
            self.app.processEvents()
            self.app.processEvents()
            self.assertEqual([1], processed_at_cancel)
            self.assertEqual(1, pull.call_count)
            # A later frame must still be delivered after the burst.
            self.send_images(1)
            self.app.processEvents()
            self.assertEqual(2, pull.call_count)

    def test_notification_during_pull_schedules_next_frame(self):
        def pull_frame():
            if pull.call_count == 1:
                self.send_images(20)

        with patch.object(self.controller, "_pull_live_frame", side_effect=pull_frame) as pull:
            self.send_images(20)
            self.app.processEvents()
            self.app.processEvents()
            self.assertEqual(2, pull.call_count)

    def test_stale_stream_notification_cannot_block_restarted_preview(self):
        with patch.object(self.controller, "_pull_live_frame") as pull:
            self.send_images(10)
            self.controller._stream_generation += 1
            self.send_images(10)
            self.app.processEvents()
            self.assertEqual(1, pull.call_count)
            self.send_images(1)
            self.app.processEvents()
            self.assertEqual(2, pull.call_count)

    def test_formal_trigger_frames_and_camera_errors_are_not_coalesced(self):
        self.controller._software_trigger_capture_active = True
        errors = []
        self.controller.error_occurred.connect(errors.append)
        with patch.object(self.controller, "_pull_live_frame") as pull:
            self.send_images(3)
            self.controller._camera_callback(
                nncam.NNCAM_EVENT_ERROR,
                (self.controller, self.controller._stream_generation),
            )
            self.app.processEvents()
            self.assertEqual(3, pull.call_count)
            self.assertEqual(1, len(errors))


class ROIPreviewTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = ensure_qapplication()

    def setUp(self):
        self.camera = CameraSignals()
        self.dialog = RecipeROIDialog(self.camera, ("CH1",))
        self.dialog.show()
        self.app.processEvents()
        self.addCleanup(self.dialog.deleteLater)
        self.addCleanup(self.dialog.reject)
        self.image = QImage(3840, 2160, QImage.Format.Format_Grayscale8)
        self.image.fill(0)

    def test_4k_burst_renders_latest_frame_once_and_preserves_drag(self):
        self.camera.frame_ready.emit(self.image)
        view = self.dialog.view
        start = view.mapFromScene(QPointF(800, 600))
        end = view.mapFromScene(QPointF(1600, 1200))
        QTest.mousePress(view.viewport(), Qt.MouseButton.LeftButton, pos=start)
        with patch.object(view, "set_image", wraps=view.set_image) as render:
            for _ in range(50):
                self.camera.frame_ready.emit(self.image)
            latest = self.image.copy()
            latest.fill(123)
            self.camera.frame_ready.emit(latest)
            self.assertEqual(0, render.call_count)
            QTest.qWait(180)
            self.assertEqual(1, render.call_count)
            self.assertEqual(123, render.call_args.args[0].pixelColor(0, 0).red())
        QTest.mouseMove(view.viewport(), end)
        QTest.mouseRelease(view.viewport(), Qt.MouseButton.LeftButton, pos=end)
        x, y, width, height = view.roi
        for actual, expected in zip((x, y, width, height), (800, 600, 800, 600)):
            self.assertAlmostEqual(actual, expected, delta=10)
        self.assertTrue(self.dialog.next_button.isEnabled())

    def test_cancel_stops_pending_render_and_disconnects_live_frames(self):
        self.camera.frame_ready.emit(self.image)
        with patch.object(self.dialog.view, "set_image") as render:
            self.camera.frame_ready.emit(self.image)
            self.dialog.reject()
            self.camera.frame_ready.emit(self.image)
            QTest.qWait(180)
            render.assert_not_called()
        self.assertFalse(self.dialog._frame_timer.isActive())
        self.assertFalse(self.dialog._preview_timer.isActive())

    def test_resolution_change_rejects_before_deferred_render(self):
        self.camera.frame_ready.emit(self.image)
        self.camera.frame_ready.emit(self.image)
        self.camera.frame_ready.emit(QImage(1920, 1080, QImage.Format.Format_Grayscale8))
        self.assertTrue(self.dialog.error)
        self.assertFalse(self.dialog.isVisible())
        self.assertFalse(self.dialog._preview_timer.isActive())

    def test_same_size_frames_preserve_view_transform_without_refitting(self):
        view = ImageView()
        self.addCleanup(view.deleteLater)
        with patch.object(view, "fit_to_window", wraps=view.fit_to_window) as fit:
            view.set_image(self.image)
            initial = view.transform()
            for _ in range(10):
                view.set_image(self.image)
            self.assertEqual(1, fit.call_count)
            self.assertEqual(initial, view.transform())
            view.set_image(QImage(640, 480, QImage.Format.Format_Grayscale8))
            self.assertEqual(2, fit.call_count)

    def test_main_window_preview_is_paused_during_recipe_roi_preparation(self):
        owner = SimpleNamespace(_measurement_starting=True, last_image=None, image_view=Mock())
        MainWindowDeviceMixin.on_frame_ready(owner, self.image)
        self.assertIsNone(owner.last_image)
        owner.image_view.set_image.assert_not_called()
        frame = object()
        with patch.object(MainWindowDeviceMixin, "_refresh_live_view_roi_dn") as refresh:
            MainWindowDeviceMixin.on_scientific_frame_ready(owner, frame, self.image, 1)
            self.assertIs(frame, owner._latest_scientific_frame)
            refresh.assert_not_called()


if __name__ == "__main__":
    unittest.main()
