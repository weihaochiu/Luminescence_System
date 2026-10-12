from __future__ import annotations

import json
from pathlib import Path
import tempfile
from time import monotonic
import unittest
from unittest.mock import patch

import numpy as np
import tifffile

from standalone.hdr_viewer.batch import generate_batch
from standalone.hdr_viewer.processing import DisplaySettings, fuse, tone_map
from standalone.hdr_viewer.scan import Cancelled, OUTPUT_MARKER, read_frame, scan_folder


def capture(root, *, run="RUN-A", sample="Sample", channel="CH1", density=10., gain=100,
            exposure=100., repeat=1, image=None, actual=None, bits=12, alignment="right", dark=False):
    folder = Path(root) / run / channel
    folder.mkdir(parents=True, exist_ok=True)
    name = f"{sample.replace('/', '_')}_{channel}_J{density:g}_G{gain}_E{exposure:g}_R{repeat}"
    path = folder / ("N000001_" + name + ".tiff")
    if image is None:
        image = np.full((4, 6), round(exposure), dtype=np.uint16)
    tifffile.imwrite(path, np.asarray(image, dtype=np.uint16))
    metadata = {"MeasurementRunID": run, "SampleID": sample, "Channel": channel,
                "MeasurementType": "DARK" if dark else "EL", "OutputMode": "current_density",
                "SetCurrentDensityMaCm2": density, "MeasuredCurrentDensityMaCm2": density + repeat * .001,
                "Gain": gain, "GainReadback": gain, "Exposure": exposure,
                "RequestedExposureMs": exposure, "ExposureUsedUs": (actual or exposure) * 1000,
                "SensorBitDepth": bits, "EffectiveDNMax": (1 << bits) - 1,
                "RawValueAlignment": alignment, "RepeatIndex": repeat}
    path.with_suffix(".json").write_text(json.dumps(metadata), encoding="utf-8")
    return path


def dataset(root):
    # Three radiances; long exposure clips the brightest region.
    rates = np.tile([100., 1000., 5000.], (4, 2))
    for exposure in (100., 1000., 10000.):
        for repeat in (1, 2):
            capture(root, exposure=exposure, repeat=repeat,
                    image=np.clip(rates * exposure / 1000, 0, 4095))
    return rates


class InventoryTests(unittest.TestCase):
    def test_runs_density_gains_and_samples_are_separate_and_repeats_join(self):
        with tempfile.TemporaryDirectory() as tmp:
            for run in ("RUN-A", "RUN-B"):
                for density in (10., 20.):
                    for gain in (100, 200):
                        for exposure in (100., 1000.):
                            for repeat in (1, 2):
                                capture(tmp, run=run, density=density, gain=gain, exposure=exposure, repeat=repeat)
            capture(tmp, sample="Other", exposure=100)
            inventory = scan_folder(tmp)
            self.assertEqual(9, len(inventory.groups))
            self.assertEqual([], inventory.issues)
            self.assertEqual(8, sum(not g.problem for g in inventory.groups))
            self.assertEqual({4}, {len(g.frames) for g in inventory.groups if not g.problem})

    def test_dark_and_generated_outputs_are_excluded_case_insensitively(self):
        with tempfile.TemporaryDirectory() as tmp:
            first = capture(tmp, exposure=100)
            upper = first.with_suffix(".TIF")
            first.rename(upper)
            capture(tmp, exposure=1000)
            capture(tmp, exposure=200, dark=True)
            out = Path(tmp) / "arbitrary_output"
            out.mkdir()
            (out / OUTPUT_MARKER).write_text("{}")
            tifffile.imwrite(out / "bad.tiff", np.zeros((2, 2), np.uint16))
            inventory = scan_folder(tmp)
            self.assertEqual(3, inventory.scanned)
            self.assertEqual(1, inventory.excluded_dark)
            self.assertEqual(2, len(inventory.groups[0].frames))

    def test_missing_run_is_not_guessed_and_identifiable_folder_fallback_is_explicit(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = capture(tmp)
            data = json.loads(path.with_suffix(".json").read_text())
            del data["MeasurementRunID"]
            path.with_suffix(".json").write_text(json.dumps(data))
            self.assertEqual(1, len(scan_folder(tmp).issues))
            (path.parent.parent / "measurement_snapshot.json").write_text("{}")
            frame = scan_folder(tmp).groups[0].frames[0]
            self.assertIn("FOLDER_RUN_ID", frame.warnings)
            self.assertTrue(frame.key.run.startswith("folder:"))

    def test_filename_only_in_original_run_folder_reports_assumptions(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = capture(tmp, run="20261009_100000_abcd1234")
            path.with_suffix(".json").unlink()
            frame = read_frame(path)
            self.assertEqual(16, frame.bit_depth)
            self.assertIn("ASSUMED_UINT16_RANGE", frame.warnings)
            self.assertEqual(10, frame.key.density)

    def test_sanitized_sample_and_actual_exposure_are_read_correctly(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = capture(tmp, sample="Sample/A", actual=100.2)
            frame = read_frame(path)
            self.assertEqual("Sample/A", frame.key.sample)
            self.assertEqual(100.2, frame.exposure_ms)
            self.assertEqual(100, frame.requested_exposure_ms)

    def test_metadata_conflict_unknown_raw_and_corrupt_files_are_reported(self):
        for field, value in (("SetCurrentDensityMaCm2", 99), ("GainReadback", 200),
                             ("RawValueAlignment", "unknown"), ("SensorBitDepth", 12.5)):
            with self.subTest(field=field), tempfile.TemporaryDirectory() as tmp:
                path = capture(tmp)
                data = json.loads(path.with_suffix(".json").read_text())
                data[field] = value
                path.with_suffix(".json").write_text(json.dumps(data))
                inventory = scan_folder(tmp)
                self.assertEqual([], inventory.groups)
                self.assertEqual(1, len(inventory.issues))
        with tempfile.TemporaryDirectory() as tmp:
            (Path(tmp) / "broken.tif").write_bytes(b"broken")
            self.assertEqual(1, len(scan_folder(tmp).issues))

    def test_format_and_camera_mismatch_prevent_generation(self):
        with tempfile.TemporaryDirectory() as tmp:
            capture(tmp, exposure=100)
            capture(tmp, exposure=1000, image=np.ones((3, 5), np.uint16))
            self.assertEqual("INCONSISTENT_FORMAT", scan_folder(tmp).groups[0].problem)
        with tempfile.TemporaryDirectory() as tmp:
            paths = [capture(tmp, exposure=e) for e in (100, 1000)]
            for index, path in enumerate(paths):
                data = json.loads(path.with_suffix(".json").read_text())
                data["CameraSerial"] = str(index)
                path.with_suffix(".json").write_text(json.dumps(data))
            self.assertEqual("INCONSISTENT_CAMERA", scan_folder(tmp).groups[0].problem)

    def test_scan_cancellation(self):
        def cancel():
            raise Cancelled()
        with tempfile.TemporaryDirectory() as tmp:
            capture(tmp)
            with self.assertRaises(Cancelled):
                scan_folder(tmp, check_cancel=cancel)


class FusionTests(unittest.TestCase):
    def test_recovers_exposure_rates_and_rejects_clipped_exposure(self):
        with tempfile.TemporaryDirectory() as tmp:
            expected = dataset(tmp)
            merged = fuse(scan_folder(tmp).groups[0])
            np.testing.assert_allclose(expected, merged.image, rtol=1e-6)
            self.assertTrue(np.all(merged.valid))
            self.assertEqual(6, len(merged.provenance))

    def test_actual_exposure_jitter_averages_within_requested_exposure(self):
        with tempfile.TemporaryDirectory() as tmp:
            for exposure in (100, 1000):
                for repeat, actual in ((1, exposure), (2, exposure * 1.01)):
                    capture(tmp, exposure=exposure, repeat=repeat, actual=actual,
                            image=np.full((4, 6), actual, np.uint16))
            group = scan_folder(tmp).groups[0]
            self.assertEqual([100, 1000], group.exposures)
            np.testing.assert_allclose(fuse(group).image, 1000)

    def test_left_alignment_matches_right_alignment(self):
        with tempfile.TemporaryDirectory() as tmp:
            for exposure in (100, 1000):
                capture(tmp, exposure=exposure, alignment="left",
                        image=np.full((4, 6), exposure, np.uint16) << 4)
            np.testing.assert_allclose(fuse(scan_folder(tmp).groups[0]).image, 1000)

    def test_unusable_pixels_are_masked_and_display_does_not_modify_hdr(self):
        with tempfile.TemporaryDirectory() as tmp:
            for exposure in (100, 1000):
                capture(tmp, exposure=exposure,
                        image=np.tile([0, 4095, exposure], (4, 2)))
            merged = fuse(scan_folder(tmp).groups[0])
            before = merged.image.copy()
            display, info = tone_map(merged.image, merged.valid, DisplaySettings())
            self.assertTrue(np.all(np.isnan(merged.image[:, :2])))
            self.assertTrue(np.all(display[:, :2] == 0))
            np.testing.assert_equal(before, merged.image)
            self.assertFalse(info["cross_group_brightness_comparable"])

    def test_correction_seam_and_post_scan_change_detection(self):
        class DarkCorrection:
            def apply(self, image, frame):
                return image - 100
            def describe(self):
                return {"name": "test-dark", "version": "1"}
        with tempfile.TemporaryDirectory() as tmp:
            for exposure in (100, 1000):
                capture(tmp, exposure=exposure, image=np.full((4, 6), 100 + exposure, np.uint16))
            group = scan_folder(tmp).groups[0]
            np.testing.assert_allclose(fuse(group, correction=DarkCorrection()).image, 1000)
            group.frames[0].metadata_path.write_text("{}")
            with self.assertRaisesRegex(ValueError, "Metadata changed"):
                fuse(group)

    def test_all_saturated_and_invalid_display_parameters_are_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            for exposure in (100, 1000):
                capture(tmp, exposure=exposure, image=np.full((4, 6), 4095, np.uint16))
            with self.assertRaisesRegex(ValueError, "No usable"):
                fuse(scan_folder(tmp).groups[0])
        with self.assertRaises(ValueError):
            DisplaySettings(gamma=float("nan")).validate()


class BatchTests(unittest.TestCase):
    def test_outputs_one_result_for_repeats_with_provenance_and_monotonic_progress(self):
        with tempfile.TemporaryDirectory() as tmp:
            expected = dataset(tmp)
            root = Path(tmp)
            original = {p: p.read_bytes() for p in root.rglob("*") if p.is_file()}
            inventory = scan_folder(root)
            events = []
            result = generate_batch(inventory, inventory.groups, root, progress=events.append)
            self.assertEqual("completed", result["status"])
            self.assertFalse(result["quantitative"])
            self.assertEqual(1, len(result["results"]))
            output = Path(result["results"][0]["folder"])
            self.assertEqual(3, len(list(output.glob("*.tiff"))) + len(list(output.glob("*_preview.png"))))
            np.testing.assert_allclose(tifffile.imread(next(output.glob("*float32.tiff"))), expected)
            self.assertEqual(np.uint16, tifffile.imread(next(output.glob("*_view.tiff"))).dtype)
            record = json.loads(next(output.glob("*.json")).read_text(encoding="utf-8"))
            self.assertEqual(6, len(record["sources"]))
            self.assertFalse(record["quantitative"])
            self.assertEqual("none", record["correction"]["name"])
            self.assertEqual(events[-1]["total"], events[-1]["completed"])
            self.assertEqual(sorted(e["completed"] for e in events), [e["completed"] for e in events])
            self.assertIsNotNone(events[-2]["remaining_s"])
            self.assertEqual(6, scan_folder(root).scanned)
            for path, content in original.items():
                self.assertEqual(content, path.read_bytes())
            other = generate_batch(inventory, inventory.groups, root)
            self.assertNotEqual(result["output_directory"], other["output_directory"])
            self.assertTrue((Path(result["output_directory"]) / "batch_summary.csv").exists())

    def test_group_failure_does_not_block_other_conditions(self):
        with tempfile.TemporaryDirectory() as tmp:
            for exposure in (100, 1000):
                capture(tmp, density=10, exposure=exposure, image=np.full((4, 6), 4095, np.uint16))
                capture(tmp, density=20, exposure=exposure)
            inventory = scan_folder(tmp)
            result = generate_batch(inventory, inventory.groups, tmp)
            self.assertEqual("completed_with_errors", result["status"])
            self.assertEqual(["failed", "completed"], [r["status"] for r in result["results"]])

    def test_cancellation_preserves_completed_group_and_removes_partial_products(self):
        with tempfile.TemporaryDirectory() as tmp:
            for density in (10, 20):
                for exposure in (100, 1000):
                    capture(tmp, density=density, exposure=exposure)
            inventory = scan_folder(tmp)
            stopped = False
            def progress(value):
                nonlocal stopped
                if value["phase"] == "write":
                    stopped = True
            def cancel():
                if stopped:
                    raise Cancelled()
            result = generate_batch(inventory, inventory.groups, tmp, progress=progress, check_cancel=cancel)
            self.assertEqual("cancelled", result["status"])
            self.assertEqual(1, len(result["results"]))
            self.assertTrue(Path(result["results"][0]["folder"]).exists())
            self.assertFalse(list(Path(result["output_directory"]).glob(".partial_*")))
        with tempfile.TemporaryDirectory() as tmp:
            dataset(tmp)
            inventory = scan_folder(tmp)
            # Cancellation during output must remove this group's partial files.
            with patch("standalone.hdr_viewer.batch.tifffile.imwrite", side_effect=Cancelled):
                result = generate_batch(inventory, inventory.groups, tmp)
            self.assertEqual("cancelled", result["status"])
            self.assertFalse(list(Path(result["output_directory"]).glob(".partial_*")))


class GuiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from tests.qt_test_utils import ensure_qapplication
        cls.app = ensure_qapplication()

    def wait_done(self, window):
        from PySide6.QtCore import QThread
        deadline = monotonic() + 15
        while window.worker is not None and monotonic() < deadline:
            self.app.processEvents()
            QThread.msleep(5)
        self.assertIsNone(window.worker)

    def test_background_scan_generate_selection_and_finish_ui(self):
        from standalone.hdr_viewer.window import HDRViewerWindow
        with tempfile.TemporaryDirectory() as tmp:
            dataset(tmp)
            window = HDRViewerWindow()
            self.addCleanup(window.close)
            window.input_path.setText(tmp)
            window.output_path.setText(tmp)
            window.scan()
            self.assertFalse(window.choose_input.isEnabled())
            self.wait_done(window)
            self.assertEqual(1, len(window.selected_groups()))
            window.set_selection(False)
            self.assertEqual([], window.selected_groups())
            window.set_selection(True)
            window.generate()
            self.wait_done(window)
            self.assertTrue(window.last_output.exists())
            self.assertTrue(window.open_output.isEnabled())
            self.assertEqual(1000, window.progress_bar.value())
            self.assertFalse(window.cancel_button.isEnabled())

    def test_cancel_and_close_wait_for_worker_and_eta_heartbeat(self):
        from threading import Event
        from standalone.hdr_viewer.window import HDRViewerWindow
        from standalone.hdr_viewer.scan import Inventory
        gate = Event()
        def delayed_scan(root, check_cancel, progress):
            gate.wait(2)
            check_cancel()
            return Inventory(Path(root), [], [], 0, 0)
        with tempfile.TemporaryDirectory() as tmp, patch("standalone.hdr_viewer.window.scan_folder", side_effect=delayed_scan):
            window = HDRViewerWindow()
            window.show()
            window.input_path.setText(tmp)
            window.scan()
            window.update_progress({"phase": "read", "completed": 1, "total": 2, "remaining_s": 60,
                                   "group_index": 1, "group_total": 1,
                                   "key": {"sample": "S", "channel": "CH1", "density": 10., "gain": 100}})
            self.assertNotEqual("—", window.finish_time.text())
            self.assertIn("00:", window.remaining.text())
            window.close()
            self.assertTrue(window.worker.cancel.is_set())
            self.assertTrue(window.isVisible())
            gate.set()
            self.wait_done(window)
            self.assertFalse(window.isVisible())

    def test_main_toolbar_launches_independent_process_and_retranslates(self):
        from PySide6.QtCore import QSettings
        from core.i18n import Language, configure_i18n, set_language
        from gui.main_window import MainWindow
        with tempfile.TemporaryDirectory() as tmp:
            settings = QSettings(str(Path(tmp) / "settings.ini"), QSettings.Format.IniFormat)
            with patch("gui.main_window.QSettings", return_value=settings), patch(
                "gui.main_window.QStandardPaths.writableLocation", return_value=tmp
            ), patch("gui.main_window.QTimer.singleShot"):
                window = MainWindow()
            try:
                self.assertIn(window.offline_viewer_action, window.main_toolbar.actions())
                with patch("gui.offline_tools.QProcess.startDetached", return_value=(True, 123)) as start:
                    window.offline_viewer_action.trigger()
                    self.assertEqual(["-m", "standalone.hdr_viewer.main"], start.call_args.args[1])
                set_language(Language.EN_US, persist=False)
                self.assertEqual("Generate HDR", window.offline_viewer_action.text())
                set_language(Language.ZH_TW, persist=False)
                self.assertEqual("HDR 生成", window.offline_viewer_action.text())
            finally:
                window.close()
                configure_i18n(None)


if __name__ == "__main__":
    unittest.main()
