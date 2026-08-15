from __future__ import annotations

import unittest

import numpy as np

from gui.scientific_dn_alignment import (
    AlignmentVerificationState,
    AlignmentVerifier,
)


def _frames(pattern: list[int], count: int = 10):
    frame = np.resize(np.asarray(pattern, dtype=np.uint16), (200, 200))
    for _ in range(count):
        yield frame


class AlignmentVerifierTests(unittest.TestCase):
    def test_12_bit_right_alignment_uses_multiframe_low_bit_variation(self) -> None:
        values = [0, 1, 2, 3, 15, 16, 31, 255, 1023, 2048, 4095]
        verifier = AlignmentVerifier(12, 16)
        frame = next(_frames(values, 1))
        before = frame.copy()
        for _ in range(5):
            state = verifier.add_frame(frame)
        self.assertEqual(AlignmentVerificationState.VERIFIED_RIGHT, state)
        self.assertEqual("right", verifier.alignment)
        self.assertEqual("RuntimeVerified", verifier.source)
        self.assertGreaterEqual(verifier.evidence.sampled_pixels, 50_000)
        self.assertGreaterEqual(verifier.evidence.nonzero_pixels, 1_000)
        np.testing.assert_array_equal(before, frame)

    def test_12_bit_left_alignment_uses_fixed_padding_and_visible_scale(self) -> None:
        values = [0, 0x0010, 0x0100, 0x1230, 0x8000, 0xFFF0]
        verifier = AlignmentVerifier(12, 16)
        for sample in _frames(values, 5):
            state = verifier.add_frame(sample)
        self.assertEqual(AlignmentVerificationState.VERIFIED_LEFT, state)
        self.assertEqual("left", verifier.alignment)
        self.assertGreaterEqual(verifier.evidence.low_bits_zero_ratio, 0.999)

    def test_tiny_dark_samples_remain_unknown_with_insufficient_signal(self) -> None:
        verifier = AlignmentVerifier(12, 16)
        frame = np.resize(np.asarray([0, 1, 2], dtype=np.uint16), (10, 10))
        for _ in range(10):
            state = verifier.add_frame(frame)
        self.assertEqual(AlignmentVerificationState.COLLECTING, state)
        self.assertEqual("unknown", verifier.alignment)
        self.assertEqual("InsufficientSignal", verifier.source)

    def test_all_zero_frames_remain_unknown(self) -> None:
        verifier = AlignmentVerifier(12, 16)
        frame = np.zeros((200, 200), dtype=np.uint16)
        for _ in range(10):
            state = verifier.add_frame(frame)
        self.assertEqual(AlignmentVerificationState.COLLECTING, state)
        self.assertEqual("InsufficientSignal", verifier.source)

    def test_quantized_low_range_evidence_is_ambiguous(self) -> None:
        # These values fit right alignment but also keep all left-padding bits
        # zero, so content alone cannot distinguish the two interpretations.
        verifier = AlignmentVerifier(12, 16)
        values = [0x0010, 0x0100, 0x0200, 0x0800, 0x0FF0]
        for sample in _frames(values, 10):
            state = verifier.add_frame(sample)
        self.assertEqual(AlignmentVerificationState.AMBIGUOUS, state)
        self.assertEqual("AmbiguousRuntimeEvidence", verifier.source)
        self.assertEqual("unknown", verifier.alignment)


if __name__ == "__main__":
    unittest.main()
