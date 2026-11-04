from __future__ import annotations

import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest

import numpy as np
from PIL import Image
import tifffile

from gui.image_colorbar import GrayscaleColorbar
from gui.measurement_output import annotated_jpeg_image, save_matrix_capture, scientific_to_visualization


class GrayscaleColorbarTests(unittest.TestCase):
    def test_source_is_unchanged_for_small_tall_and_wide_rois(self):
        for width, height in ((2, 2), (40, 40), (640, 480), (160, 900), (900, 80)):
            with self.subTest(size=(width, height)):
                pixels = np.random.default_rng(17).integers(0, 256, (height, width, 3), dtype=np.uint8)
                source = Image.fromarray(pixels)
                before = source.tobytes()
                colorbar = GrayscaleColorbar(4095)
                result = annotated_jpeg_image(source, ("Sample ID: EL-001",), colorbar=colorbar)
                self.assertGreater(result.width, width)
                self.assertGreater(result.height, height)
                self.assertEqual(before, source.tobytes())
                self.assertEqual(before, result.crop((0, 0, width, height)).tobytes())
                layout = colorbar.layout(source.size)
                left, top, right, bottom = layout["bar_box"]
                self.assertGreater(left, width)
                self.assertLess(right, result.width)
                self.assertGreaterEqual(top, 0)
                self.assertLessEqual(bottom, layout["height"])
                # Tick labels stay separate, including minimum-height tiny ROIs.
                ys = [y for _, y in layout["ticks"]]
                self.assertTrue(all(b - a >= layout["line_height"] for a, b in zip(ys, ys[1:])))

    def test_ramp_and_source_use_the_same_dn_to_gray_mapping(self):
        for bits in (8, 10, 12, 14, 16):
            with self.subTest(bits=bits):
                maximum = (1 << bits) - 1
                colorbar = GrayscaleColorbar(maximum)
                source = Image.new("L", (160, 300))
                result = colorbar.append_to(source)
                left, top, _, bottom = colorbar.layout(source.size)["bar_box"]
                dn = np.rint(np.linspace(maximum, 0, bottom - top)).astype(np.uint16)
                preview = np.asarray(scientific_to_visualization(dn[:, None], bits, "right"))[:, 0]
                actual = np.asarray(result)[top:bottom, left, 0]
                np.testing.assert_array_equal(preview, actual)
                self.assertEqual(255, int(actual[0]))
                self.assertEqual(0, int(actual[-1]))
                self.assertTrue(np.all(np.diff(actual.astype(int)) <= 0))


class CaptureColorbarTests(unittest.TestCase):
    def metadata(self, bits=12, alignment="right", measurement_type="EL"):
        return {"MeasurementType": measurement_type, "SampleID": "EL-001", "Channel": "CH1",
                "CommandedCurrentDensity": 10, "Gain": 100, "Exposure": 100,
                "RepeatIndex": 1, "RepeatTotal": 1, "Timestamp": "2026-11-04 14:30:00",
                "ApplicableChannels": ["CH1"], "SensorBitDepth": bits, "ContainerBitDepth": 16,
                "RawValueAlignment": alignment}

    def save(self, root, raw, metadata, footer=True, stem="capture"):
        output = SimpleNamespace(format_tiff=True, format_png=True, format_jpg=True,
                                 format_jpg_with_footer=footer)
        return save_matrix_capture(raw, Image.new("L", (1, 1)), Path(root) / stem, metadata, output)

    def test_real_sensor_range_and_legend_geometry_are_saved_for_el_and_dark(self):
        for bits in (8, 10, 12, 14, 16):
            for measurement_type in ("EL", "DARK"):
                with self.subTest(bits=bits, type=measurement_type), tempfile.TemporaryDirectory() as root:
                    raw = np.array([[0, 1], [2, 3]], dtype=np.uint16)
                    saved = self.save(root, raw, self.metadata(bits, measurement_type=measurement_type))
                    payload = json.loads(saved.metadata_path.read_text(encoding="utf-8"))
                    legend = payload["FooterColorbar"]
                    self.assertEqual((1 << bits) - 1, legend["Maximum"])
                    self.assertEqual(0, legend["Minimum"])
                    self.assertEqual("Effective DN", legend["Quantity"])
                    self.assertEqual("linear", legend["Scale"])
                    self.assertEqual("grayscale", legend["ColorMap"])
                    self.assertEqual("right", legend["Position"])
                    self.assertEqual([2, 2], payload["ScientificShape"])
                    self.assertEqual(2, payload["RawImageWidth"])
                    self.assertEqual(2, payload["RawImageHeight"])
                    self.assertGreater(legend["BarRect"]["X"], 2)
                    np.testing.assert_array_equal(raw, tifffile.imread(saved.tiff_path))
                    with Image.open(saved.png_path) as png, Image.open(saved.jpeg_path) as jpg:
                        self.assertEqual((2, 2), png.size)
                        self.assertEqual((2, 2), jpg.size)
                    with Image.open(saved.footer_jpeg_path) as annotated:
                        self.assertGreater(annotated.width, 2)
                        self.assertEqual([annotated.width, annotated.height],
                                         [payload["AnnotatedJpegWidth"], payload["AnnotatedJpegHeight"]])

    def test_left_and_right_alignment_produce_the_same_effective_dn_legend_and_image(self):
        effective = np.array([[0, 1024], [2048, 4095]], dtype=np.uint16)
        with tempfile.TemporaryDirectory() as root:
            right = self.save(root, effective, self.metadata(), stem="right")
            left = self.save(root, effective << 4, self.metadata(alignment="left"), stem="left")
            right_meta = json.loads(right.metadata_path.read_text(encoding="utf-8"))
            left_meta = json.loads(left.metadata_path.read_text(encoding="utf-8"))
            self.assertEqual(right_meta["FooterColorbar"], left_meta["FooterColorbar"])
            with Image.open(right.footer_jpeg_path) as a, Image.open(left.footer_jpeg_path) as b:
                self.assertEqual(a.tobytes(), b.tobytes())
            np.testing.assert_array_equal(effective << 4, tifffile.imread(left.tiff_path))

    def test_unknown_alignment_labels_the_actual_container_mapping(self):
        raw = np.array([[0, 4095], [32768, 65535]], dtype=np.uint16)
        with tempfile.TemporaryDirectory() as root:
            saved = self.save(root, raw, self.metadata(alignment="unknown"))
            legend = json.loads(saved.metadata_path.read_text(encoding="utf-8"))["FooterColorbar"]
            self.assertEqual("Container DN", legend["Quantity"])
            self.assertEqual(65535, legend["Maximum"])
            with Image.open(saved.png_path) as preview:
                np.testing.assert_array_equal(np.array([[0, 16], [128, 255]], dtype=np.uint8), np.asarray(preview))

    def test_range_does_not_change_with_each_frames_peak(self):
        with tempfile.TemporaryDirectory() as root:
            legends = []
            for peak in (4, 2048, 4095):
                saved = self.save(root, np.full((2, 2), peak, dtype=np.uint16), self.metadata(), stem=str(peak))
                legends.append(json.loads(saved.metadata_path.read_text(encoding="utf-8"))["FooterColorbar"])
            self.assertTrue(all(legend == legends[0] for legend in legends))

    def test_plain_output_does_not_acquire_an_annotation(self):
        with tempfile.TemporaryDirectory() as root:
            saved = self.save(root, np.zeros((2, 2), dtype=np.uint16), self.metadata(), footer=False)
            self.assertIsNone(saved.footer_jpeg_path)
            payload = json.loads(saved.metadata_path.read_text(encoding="utf-8"))
            self.assertIsNone(payload["FooterColorbar"])
            self.assertIsNone(payload["AnnotatedJpegWidth"])

    def test_legacy_rgb_does_not_get_a_misleading_single_grayscale_legend(self):
        with tempfile.TemporaryDirectory() as root:
            saved = self.save(root, np.zeros((2, 2, 3), dtype=np.uint16), self.metadata())
            payload = json.loads(saved.metadata_path.read_text(encoding="utf-8"))
            self.assertIsNone(payload["FooterColorbar"])
            with Image.open(saved.footer_jpeg_path) as image:
                self.assertEqual(2, image.width)


if __name__ == "__main__":
    unittest.main()
