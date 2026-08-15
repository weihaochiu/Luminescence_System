from __future__ import annotations

import unittest
import tempfile
from pathlib import Path

import numpy as np
import tifffile

from gui.measurement_output import save_scientific_tiff
from gui.scientific_dn import (
    effective_dn_fraction,
    effective_dn_max,
    effective_dn_to_uint8,
    mean_effective_dn,
    scientific_to_effective_dn,
)


class ScientificDNTests(unittest.TestCase):
    def test_effective_dn_max_for_supported_depths(self) -> None:
        for bits, maximum in (
            (8, 255),
            (10, 1023),
            (12, 4095),
            (14, 16383),
            (16, 65535),
        ):
            with self.subTest(bits=bits):
                self.assertEqual(maximum, effective_dn_max(bits))

    def test_right_aligned_values_and_source_immutability(self) -> None:
        source = np.array([[0, 1024, 4095]], dtype=np.uint16)
        before = source.copy()
        effective = scientific_to_effective_dn(source, 12, 16, "right")
        np.testing.assert_array_equal(source, before)
        np.testing.assert_array_equal(effective, before)
        self.assertFalse(np.shares_memory(source, effective))

    def test_left_aligned_12_bit_full_scale_and_source_immutability(self) -> None:
        source = np.array([[0x0000, 0x8000, 0xFFF0]], dtype=np.uint16)
        before = source.copy()
        effective = scientific_to_effective_dn(source, 12, 16, "left")
        np.testing.assert_array_equal(source, before)
        np.testing.assert_array_equal(
            effective, np.array([[0, 2048, 4095]], dtype=np.uint16)
        )

    def test_mean_and_fraction_use_effective_dn(self) -> None:
        source = np.array([[0x0000, 0x8000, 0xFFF0]], dtype=np.uint16)
        mean = mean_effective_dn(source, 12, 16, "left")
        self.assertAlmostEqual((0 + 2048 + 4095) / 3, mean)
        self.assertAlmostEqual(mean / 4095, effective_dn_fraction(mean, 4095))

    def test_preview_mapping_uses_effective_dn_max(self) -> None:
        source = np.array([[0, 2048, 4095]], dtype=np.uint16)
        mapped = effective_dn_to_uint8(source, 12, 16, "right")
        np.testing.assert_array_equal(
            mapped, np.array([[0, 128, 255]], dtype=np.uint8)
        )

    def test_left_aligned_preview_shifts_before_mapping(self) -> None:
        source = np.array([[0x0000, 0x8000, 0xFFF0]], dtype=np.uint16)
        mapped = effective_dn_to_uint8(source, 12, 16, "left")
        np.testing.assert_array_equal(
            mapped, np.array([[0, 128, 255]], dtype=np.uint8)
        )

    def test_unknown_alignment_is_rejected_without_guessing(self) -> None:
        source = np.array([[0, 4095]], dtype=np.uint16)
        with self.assertRaisesRegex(ValueError, "unknown"):
            mean_effective_dn(source, 12, 16, "unknown")

    def test_left_alignment_interpretation_does_not_change_tiff_container_dn(self) -> None:
        source = np.array([[0xFFF0]], dtype=np.uint16)
        effective = scientific_to_effective_dn(source, 12, 16, "left")
        self.assertEqual(4095, int(effective[0, 0]))
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "scientific.tif"
            save_scientific_tiff(path, source)
            saved = tifffile.imread(path)
        self.assertEqual(65520, int(saved[0, 0]))
        self.assertEqual(65520, int(source[0, 0]))


if __name__ == "__main__":
    unittest.main()
