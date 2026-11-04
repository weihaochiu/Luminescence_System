from __future__ import annotations

import csv
import json
import tempfile
import threading
import time
import unittest
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

import numpy as np
import tifffile
from PIL import Image, ImageDraw
from PySide6.QtCore import QObject, Signal
from PySide6.QtGui import QImage
from PySide6.QtWidgets import QDialog

from gui.camera_capture_bridge import CameraCaptureBridge
from gui.el_matrix_runner import ELMatrixRunner
from gui.main_window_measurement import _select_recipe_rois, _clear_measurement_worker
from gui.el_matrix_preflight import estimate_required_bytes
from gui.measurement_execution_plan import build_measurement_execution_plan
from gui.measurement_output import annotated_jpeg_image, footer_layout
from gui.measurement_snapshot import build_el_matrix_snapshot, verify_snapshot_hash
from gui.measurement_worker import MeasurementCancelled
from gui.pixel_csv_postprocessor import PixelCSVPostprocessor, _key
from gui.recipe_roi import crop_channel_frame, validate_channel_rois
from gui.recipe_roi_dialog import RecipeROIDialog
from gui.smu_control import SMUOwnership
from tests.qt_test_utils import ensure_qapplication
from tests.test_el_matrix import _FakeHardware, _small_recipe


ROIS = {"CH2": (0, 0, 2, 2), "CH4": (2, 1, 2, 2)}


def recipe_for(channels=("CH2", "CH4"), auto=False):
    recipe = _small_recipe(4)
    for channel in recipe.channels:
        channel.enabled = channel.channel in channels
    recipe.polarity.enabled = False
    recipe.dark_iv.enabled = False
    recipe.el_matrix.current_density_ma_cm2 = [2]
    recipe.el_matrix.gains_percent = [100]
    recipe.el_matrix.exposures_ms = [1]
    recipe.el_matrix.exposure_mode = "auto" if auto else "manual"
    recipe.output.export_pixel_csv = True
    recipe.output.pixel_csv_raw = True
    recipe.output.pixel_csv_dark_corrected = True
    recipe.output.pixel_csv_exposure_normalized = True
    recipe.output.format_png = True
    recipe.output.format_jpg = True
    return recipe


def roi_snapshot(recipe, rois):
    return build_el_matrix_snapshot(
        recipe, execution_order=build_measurement_execution_plan(recipe).to_dict()["steps"],
        camera={"ImageWidth": 4, "ImageHeight": 3, "ChannelROIs": rois},
        smu={}, relay_mapping={}, polarity_settings={},
    )


class ROIHardware(_FakeHardware):
    def __init__(self, fail_roi=False):
        super().__init__()
        self.active_roi = None
        self.fail_roi = fail_roi

    def set_channel_roi(self, roi, check_cancel):
        check_cancel()
        self.events.append(("roi", roi))
        if self.fail_roi:
            raise RuntimeError("ROI verification failed")
        self.active_roi = roi

    def auto_exposure(self, settings, check_cancel):
        check_cancel()
        self.events.append(("ae_roi", self.active_roi))
        return {"exposure_us": 1000, "gain_percent": 100,
                "metadata": {"RecipeAEROI": self.active_roi}}

    def capture(self, *args):
        frame = super().capture(*args)
        # Different source locations must remain distinguishable even when
        # ROIs share a size. Dark correction should yield exactly 100 DN.
        last_dark = max((i for i, event in enumerate(self.events) if event == "prepare_dark"), default=-1)
        last_output = max((i for i, event in enumerate(self.events)
                           if isinstance(event, tuple) and event[0] == "set_current"), default=-1)
        light = last_output > last_dark
        gradient = np.arange(12, dtype=np.uint16).reshape(3, 4)
        return replace(frame, scientific_image=gradient + (100 if light else 0))


class CameraSignals(QObject):
    frame_ready = Signal(QImage)
    camera_closed = Signal()
    error_occurred = Signal(str)

    def __init__(self):
        super().__init__()
        self.calls = []
        self.verify = True

    def set_auto_exposure_roi(self, *roi):
        self.calls.append((threading.get_ident(), roi))
        return self.verify


class Emergency(QObject):
    triggered = Signal(int)
    is_active = False

    def begin_operator_operation(self):
        pass


class RecipeROIDialogTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = ensure_qapplication()

    def test_enabled_channel_counts_and_sparse_channel_identity(self):
        for channels in (("CH3",), ("CH2", "CH4"), ("CH1", "CH2", "CH4"),
                         ("CH1", "CH2", "CH3", "CH4")):
            with self.subTest(channels=channels):
                camera = CameraSignals()
                dialog = RecipeROIDialog(camera, channels)
                self.assertFalse(dialog.next_button.isEnabled())
                image = QImage(4, 3, QImage.Format.Format_RGB888)
                camera.frame_ready.emit(image)
                for channel in channels:
                    self.assertIn(channel, dialog.prompt.text())
                    self.assertIn("ROI" + channel[2:], dialog.prompt.text())
                    dialog.view.set_roi(0, 0, 2, 2)
                    dialog.view._finish_roi_selection()
                    dialog.view.roi_selected.emit(0, 0, 2, 2)
                    dialog.next_button.click()
                self.assertEqual(QDialog.DialogCode.Accepted, dialog.result())
                self.assertEqual(set(channels), set(dialog.rois))
                dialog.deleteLater()

    def test_resolution_change_disconnect_error_and_cancel_reject(self):
        for action in ("resize", "disconnect", "error", "cancel", "timeout"):
            camera = CameraSignals()
            dialog = RecipeROIDialog(camera, ("CH2", "CH4"))
            dialog.show()
            camera.frame_ready.emit(QImage(4, 3, QImage.Format.Format_RGB888))
            if action == "resize":
                camera.frame_ready.emit(QImage(5, 3, QImage.Format.Format_RGB888))
            elif action == "disconnect":
                camera.camera_closed.emit()
            elif action == "error":
                camera.error_occurred.emit("camera failed")
            elif action == "timeout":
                dialog._frame_timer.timeout.emit()
            else:
                dialog.reject()
            self.assertEqual(QDialog.DialogCode.Rejected, dialog.result())
            self.assertFalse(dialog.isVisible())
            self.assertEqual({}, dialog.rois)
            self.assertEqual([], dialog._connections)
            dialog.deleteLater()

    def test_redraw_cannot_confirm_old_roi(self):
        dialog = RecipeROIDialog(CameraSignals(), ("CH1",))
        dialog._frame(QImage(4, 3, QImage.Format.Format_RGB888))
        dialog.view.set_roi(0, 0, 2, 2)
        dialog._selected(0, 0, 2, 2)
        dialog.redraw.click()
        self.assertFalse(dialog.next_button.isEnabled())
        dialog._next()
        self.assertEqual({}, dialog.rois)
        dialog.reject()


class RecipeROIPreparationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = ensure_qapplication()

    def owner(self):
        control = Mock(ownership=SMUOwnership.IDLE)
        control.confirm_output_off_for_routing.return_value = True
        control.safe_shutdown.return_value = True
        control.prepare_recipe_start.side_effect = lambda **kw: setattr(control, "ownership", SMUOwnership.RECIPE)
        camera = Mock(is_open=True, auto_exposure_roi=(0, 0, 4, 3))
        camera.capture_metadata.return_value = {
            "ImageWidth": 4, "ImageHeight": 3, "ExposureReadbackUs": 1000,
            "GainReadback": 100, "AutoExposureMode": "manual",
        }
        owner = SimpleNamespace(smu_manager=SimpleNamespace(control=control), controller=camera,
                                emergency_manager=Emergency(), relay_service=Mock(), light_service=Mock(),
                                _prepare_light_for_measurement=Mock(return_value=True),
                                _update_white_light_control=Mock())
        owner.relay_service.safe_white_light_off.return_value = True
        return owner

    def prepare(self, owner, *, accepted=True, dialog_error=""):
        dialog = Mock(rois=ROIS, error=dialog_error)
        dialog.exec.return_value = QDialog.DialogCode.Accepted if accepted else QDialog.DialogCode.Rejected
        with patch("gui.main_window_measurement.RecipeROIDialog", return_value=dialog), \
             patch("gui.main_window_measurement._set_measurement_controls_locked"), \
             patch("gui.main_window_measurement.report_error") as reported:
            result = _select_recipe_rois(owner, recipe_for())
        return result, reported

    def test_white_light_cleanup_and_owned_smu_off_before_return(self):
        owner = self.owner()
        result, reported = self.prepare(owner)
        self.assertEqual(ROIS, result)
        owner.relay_service.group_on.assert_called_once_with("white_light", "recipe_roi")
        owner.relay_service.safe_white_light_off.assert_called_once()
        owner.smu_manager.control.safe_shutdown.assert_called_once_with(SMUOwnership.RECIPE)
        owner.controller.restore_exposure_state.assert_called_once()
        self.assertFalse(owner._measurement_starting)
        reported.assert_not_called()

    def test_cancel_still_turns_white_light_off_and_releases_ownership(self):
        owner = self.owner()
        result, reported = self.prepare(owner, accepted=False)
        self.assertIsNone(result)
        owner.relay_service.safe_white_light_off.assert_called_once()
        owner.smu_manager.control.safe_shutdown.assert_called_once()
        reported.assert_not_called()

    def test_unverified_white_light_off_blocks_measurement(self):
        owner = self.owner()
        owner.relay_service.safe_white_light_off.return_value = False
        result, reported = self.prepare(owner)
        self.assertIsNone(result)
        owner.controller.disable_auto_exposure_for_formal_measurement.assert_called_once()
        owner.smu_manager.control.safe_shutdown.assert_called_once()
        reported.assert_called_once()

    def test_smu_shutdown_exception_does_not_leave_start_guard_locked(self):
        owner = self.owner()
        owner.smu_manager.control.safe_shutdown.side_effect = RuntimeError("shutdown failed")
        result, reported = self.prepare(owner)
        self.assertIsNone(result)
        self.assertFalse(owner._measurement_starting)
        owner.light_service.set_locked.assert_called_with("recipe_roi", False)
        reported.assert_called_once()

    def test_camera_failure_during_selection_does_not_start_measurement(self):
        owner = self.owner()
        result, reported = self.prepare(owner, accepted=False, dialog_error="camera failed")
        self.assertIsNone(result)
        owner.relay_service.safe_white_light_off.assert_called_once()
        reported.assert_called_once()

    def test_white_light_on_failure_still_cleans_up(self):
        owner = self.owner()
        owner.relay_service.group_on.side_effect = RuntimeError("light failure")
        result, reported = self.prepare(owner)
        self.assertIsNone(result)
        owner.relay_service.safe_white_light_off.assert_called_once()
        owner.smu_manager.control.safe_shutdown.assert_called_once()
        reported.assert_called_once()

    def test_routing_and_smu_verification_fail_before_light_on(self):
        for failure in ("routing", "smu"):
            owner = self.owner()
            if failure == "routing":
                owner.relay_service.safe_smu_output_channels_off.return_value = False
            else:
                owner.smu_manager.control.confirm_output_off_for_routing.return_value = False
            result, reported = self.prepare(owner)
            self.assertIsNone(result)
            owner.relay_service.group_on.assert_not_called()
            reported.assert_called_once()

    def test_completion_restores_original_live_view_roi(self):
        for roi in (None, (1, 0, 2, 2)):
            owner = self.owner()
            owner._recipe_rois_active = True
            owner._live_view_dn_roi = roi
            owner.stop_measurement_button = Mock()
            owner._update_measurement_controls = Mock()
            with patch("gui.main_window_measurement._set_measurement_controls_locked"):
                _clear_measurement_worker(owner)
            if roi is None:
                owner.controller.reset_auto_exposure_roi.assert_called_once()
            else:
                owner.controller.set_auto_exposure_roi.assert_called_once_with(*roi)
            self.assertFalse(owner._recipe_rois_active)


class RecipeROIRunnerTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = ensure_qapplication()

    def runner(self, root, hardware=None, recipe=None, rois=None):
        recipe = recipe or recipe_for()
        return ELMatrixRunner(
            recipe, hardware or ROIHardware(), root, report_progress=lambda _: None,
            is_cancel_requested=lambda: False, measurement_snapshot=roi_snapshot(recipe, rois or ROIS),
        )

    def test_required_mapping_invalid_bounds_and_integer_validation(self):
        for rois in ({"CH2": ROIS["CH2"]}, {**ROIS, "CH1": (0, 0, 1, 1)},
                     {**ROIS, "CH4": (3, 1, 2, 2)}, {**ROIS, "CH4": (0.0, 0, 2, 2)},
                     {**ROIS, "CH4": (False, 0, 2, 2)}, {**ROIS, "CH4": (0, 0, 0, 2)}):
            with self.subTest(rois=rois), self.assertRaises(ValueError):
                validate_channel_rois(rois, ROIS, 4, 3)

    def test_crop_keeps_scientific_values_and_source_unchanged(self):
        source = np.arange(12, dtype=np.uint16).reshape(3, 4) * 16
        before = source.copy()
        crop = crop_channel_frame(source, ROIS["CH4"])
        np.testing.assert_array_equal(crop, before[1:3, 2:4])
        np.testing.assert_array_equal(source, before)

    def test_every_output_is_channel_roi_and_dark_correction_matches_coordinates(self):
        with tempfile.TemporaryDirectory() as root:
            runner = self.runner(root)
            result = runner.run()
            self.assertTrue(verify_snapshot_hash(runner.snapshot))
            self.assertEqual([("roi", ROIS["CH2"]), ("roi", ROIS["CH4"])],
                             [event for event in runner.hardware.events if isinstance(event, tuple) and event[0] == "roi"])
            directory = Path(result["output_directory"])
            metadata = [json.loads(p.read_text(encoding="utf-8")) for p in directory.rglob("*.json")
                        if p.name != "measurement_snapshot.json"]
            self.assertEqual(4, len(metadata))  # 2 EL + 2 crops of ONE Dark acquisition
            self.assertEqual(3, result["captures"])
            self.assertEqual(3, len([e for e in runner.hardware.events if isinstance(e, tuple) and e[0] == "capture"]))
            for item in metadata:
                roi = ROIS[item["Channel"]]
                self.assertEqual(list(roi), item["ChannelROI"])
                self.assertEqual("ROI" + item["Channel"][2:], item["ROIId"])
                self.assertEqual([2, 2], item["ScientificShape"])
                source = np.arange(12, dtype=np.uint16).reshape(3, 4)
                if item["MeasurementType"] == "EL":
                    source += 100
                expected = crop_channel_frame(source, roi)
                np.testing.assert_array_equal(expected, tifffile.imread(item["RawTiffPath"]))
                for key in ("PngPath", "JpegPath", "FooterJpegPath"):
                    with Image.open(item[key]) as image:
                        self.assertEqual(2, image.width)
                        if key != "FooterJpegPath":
                            self.assertEqual(2, image.height)
            status = PixelCSVPostprocessor(directory, result["safe_shutdown"]).run()
            self.assertEqual("completed", status["status"])
            for path in directory.rglob("*_pixels_dark_corrected.csv"):
                with path.open(encoding="utf-8-sig", newline="") as stream:
                    values = [float(row["DarkCorrectedDN"]) for row in csv.DictReader(stream)]
                self.assertEqual([100.0] * 4, values)

    def test_auto_exposure_switches_exact_roi_before_each_channel(self):
        with tempfile.TemporaryDirectory() as root:
            runner = self.runner(root, recipe=recipe_for(auto=True))
            result = runner.run()
            self.assertEqual([("ae_roi", ROIS["CH2"]), ("ae_roi", ROIS["CH4"])],
                             [e for e in runner.hardware.events if isinstance(e, tuple) and e[0] == "ae_roi"])
            directory = Path(result["output_directory"])
            PixelCSVPostprocessor(directory, result["safe_shutdown"]).run()
            for path in directory.rglob("*_pixels_dark_corrected.csv"):
                with path.open(encoding="utf-8-sig", newline="") as stream:
                    values = [float(row["DarkCorrectedDN"]) for row in csv.DictReader(stream)]
                self.assertEqual([100.0] * 4, values)

    def test_failed_roi_stops_before_channel_output_and_shuts_down(self):
        with tempfile.TemporaryDirectory() as root:
            hardware = ROIHardware(fail_roi=True)
            with self.assertRaisesRegex(RuntimeError, "ROI verification"):
                self.runner(root, hardware=hardware).run()
            self.assertTrue(hardware.safe)
            self.assertFalse(any(isinstance(e, tuple) and e[0] in {"set_current", "ae_roi"}
                                 for e in hardware.events))

    def test_resolution_change_rejects_output_and_shuts_down(self):
        hardware = ROIHardware()
        original = hardware.capture
        hardware.capture = lambda *a: replace(original(*a), scientific_image=np.zeros((4, 4), dtype=np.uint16))
        with tempfile.TemporaryDirectory() as root:
            with self.assertRaisesRegex(RuntimeError, "resolution changed"):
                self.runner(root, hardware=hardware).run()
            self.assertTrue(hardware.safe)
            self.assertFalse(list(Path(root).rglob("*.tiff")))

    def test_dark_pairing_distinguishes_same_size_different_roi_and_channel(self):
        metadata = {"Gain": 100, "Exposure": 10, "RepeatIndex": 1,
                    "ScientificShape": [2, 2], "Channel": "CH2", "ChannelROI": ROIS["CH2"]}
        self.assertNotEqual(_key(metadata), _key({**metadata, "ChannelROI": ROIS["CH4"]}))
        self.assertNotEqual(_key(metadata), _key({**metadata, "Channel": "CH4"}))

    def test_disk_estimate_counts_dark_products_for_every_channel(self):
        recipe = recipe_for()
        full_rois = {name: (0, 0, 4, 3) for name in ROIS}
        legacy = estimate_required_bytes(recipe, 4, 3)
        per_channel = estimate_required_bytes(recipe, 4, 3, channel_rois=full_rois)
        cropped = estimate_required_bytes(recipe, 4, 3, channel_rois=ROIS)
        self.assertGreater(per_channel, legacy)
        self.assertLess(cropped, per_channel)


class RecipeROIBridgeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = ensure_qapplication()

    def dispatch(self, verify=True, cancel=False):
        camera = CameraSignals()
        camera.verify = verify
        bridge = CameraCaptureBridge(camera)
        failures = []
        cancelled = threading.Event()
        def check():
            if cancelled.is_set():
                raise MeasurementCancelled()
        def worker():
            try:
                bridge.set_metering_roi(ROIS["CH4"], check)
            except Exception as exc:
                failures.append(exc)
        thread = threading.Thread(target=worker)
        thread.start()
        if cancel:
            cancelled.set()
            thread.join(1)
        deadline = time.monotonic() + 3
        while thread.is_alive() and time.monotonic() < deadline:
            self.app.processEvents()
            time.sleep(.002)
        thread.join(.1)
        self.app.processEvents()
        self.assertFalse(thread.is_alive())
        self.assertIsNone(bridge._pending_roi)
        return camera, failures

    def test_sdk_roi_runs_on_owner_thread_with_exact_coordinates(self):
        camera, failures = self.dispatch()
        self.assertEqual([], failures)
        self.assertEqual([(threading.get_ident(), ROIS["CH4"])], camera.calls)

    def test_verification_failure_is_not_silently_ignored(self):
        _, failures = self.dispatch(verify=False)
        self.assertIsInstance(failures[0], RuntimeError)

    def test_cancelled_request_does_not_write_late_roi(self):
        camera, failures = self.dispatch(cancel=True)
        self.assertEqual([], camera.calls)
        self.assertIsInstance(failures[0], MeasurementCancelled)


class RecipeROIFooterTests(unittest.TestCase):
    def test_footer_fits_roi_width_and_height_budget_without_changing_pixels(self):
        for width, height in ((2048, 1536), (640, 480), (160, 900), (900, 80), (40, 40), (2, 2)):
            with self.subTest(size=(width, height)):
                lines = ("Sample ID: a long sample identifier", "CH4 | Gain=100% | Exposure=1 ms | Repeat=1/1",
                         "Measured: I=1.2 mA | V=1 V | Camera=39.8 C | 2026-11-04")
                font, visible, padding, _, _, footer_height = footer_layout(width, height, lines)
                self.assertLessEqual(footer_height, max(32, round(height * .3)))
                draw = ImageDraw.Draw(Image.new("RGB", (1, 1)))
                for line in visible:
                    box = draw.textbbox((0, 0), line, font=font)
                    self.assertLessEqual(box[2] - box[0], max(0, width - 2 * padding))
                source = Image.new("RGB", (width, height), (12, 34, 56))
                annotated = annotated_jpeg_image(source, lines)
                self.assertEqual(width, annotated.width)
                self.assertEqual(height + footer_height, annotated.height)
                self.assertEqual(source.tobytes(), annotated.crop((0, 0, width, height)).tobytes())
