from __future__ import annotations

"""Runtime verification of effective-DN alignment in uint16 containers."""

from dataclasses import dataclass
from enum import Enum

import numpy as np


class AlignmentVerificationState(str, Enum):
    UNKNOWN = "Unknown"
    COLLECTING = "Collecting"
    VERIFIED_RIGHT = "VerifiedRight"
    VERIFIED_LEFT = "VerifiedLeft"
    AMBIGUOUS = "Ambiguous"


@dataclass(frozen=True)
class AlignmentEvidence:
    frames: int
    sampled_pixels: int
    nonzero_pixels: int
    above_right_max_pixels: int
    above_right_max_ratio: float
    low_bits_zero_pixels: int
    low_bits_zero_ratio: float
    nonzero_low_bits_pixels: int
    nonzero_low_bit_patterns: tuple[int, ...]


class AlignmentVerifier:
    """Accumulate multi-frame sampled evidence without modifying source frames."""

    def __init__(
        self,
        sensor_bit_depth: int,
        container_bit_depth: int,
        *,
        min_frames: int = 5,
        max_frames: int = 10,
        samples_per_frame: int = 20_000,
        min_sampled_pixels: int = 50_000,
        min_nonzero_pixels: int = 1_000,
    ) -> None:
        self.sensor_bit_depth = int(sensor_bit_depth)
        self.container_bit_depth = int(container_bit_depth)
        if not 1 <= self.sensor_bit_depth < self.container_bit_depth <= 16:
            raise ValueError(
                "Runtime alignment verification requires "
                "1 <= SensorBitDepth < ContainerBitDepth <= 16"
            )
        if not 1 <= min_frames <= max_frames:
            raise ValueError("Frame limits must satisfy 1 <= min_frames <= max_frames")
        self.min_frames = int(min_frames)
        self.max_frames = int(max_frames)
        self.samples_per_frame = max(int(samples_per_frame), 1)
        self.min_sampled_pixels = max(int(min_sampled_pixels), 1)
        self.min_nonzero_pixels = max(int(min_nonzero_pixels), 1)
        self.shift = self.container_bit_depth - self.sensor_bit_depth
        self._right_max = (1 << self.sensor_bit_depth) - 1
        self._low_mask = (1 << self.shift) - 1
        self.state = AlignmentVerificationState.UNKNOWN
        self._frames = 0
        self._sampled = 0
        self._nonzero = 0
        self._above_right_max = 0
        self._low_zero = 0
        self._nonzero_low_bits = 0
        self._low_patterns: set[int] = set()

    @property
    def is_final(self) -> bool:
        return self.state in {
            AlignmentVerificationState.VERIFIED_RIGHT,
            AlignmentVerificationState.VERIFIED_LEFT,
            AlignmentVerificationState.AMBIGUOUS,
        }

    @property
    def alignment(self) -> str:
        if self.state is AlignmentVerificationState.VERIFIED_RIGHT:
            return "right"
        if self.state is AlignmentVerificationState.VERIFIED_LEFT:
            return "left"
        return "unknown"

    @property
    def source(self) -> str:
        if self.alignment in {"right", "left"}:
            return "RuntimeVerified"
        if self.state is AlignmentVerificationState.AMBIGUOUS:
            return "AmbiguousRuntimeEvidence"
        if (
            self._frames >= self.max_frames
            and (
                self._sampled < self.min_sampled_pixels
                or self._nonzero < self.min_nonzero_pixels
            )
        ):
            return "InsufficientSignal"
        return "RuntimeVerificationPending"

    @property
    def evidence(self) -> AlignmentEvidence:
        nonzero = max(self._nonzero, 1)
        return AlignmentEvidence(
            frames=self._frames,
            sampled_pixels=self._sampled,
            nonzero_pixels=self._nonzero,
            above_right_max_pixels=self._above_right_max,
            above_right_max_ratio=self._above_right_max / nonzero,
            low_bits_zero_pixels=self._low_zero,
            low_bits_zero_ratio=self._low_zero / nonzero,
            nonzero_low_bits_pixels=self._nonzero_low_bits,
            nonzero_low_bit_patterns=tuple(sorted(self._low_patterns)),
        )

    def add_frame(self, scientific: np.ndarray) -> AlignmentVerificationState:
        if self.is_final:
            return self.state
        source = np.asarray(scientific)
        if source.dtype != np.uint16:
            raise TypeError("Scientific DN source must be a uint16 ndarray")
        if source.ndim != 2:
            raise ValueError("Scientific DN source must be an H×W array")

        # A fixed-stride view gives deterministic coverage without copying a
        # full-resolution frame. Only the small sampled array is materialized.
        flat = source.reshape(-1)
        stride = max(flat.size // self.samples_per_frame, 1)
        sample = flat[::stride][: self.samples_per_frame]
        nonzero_values = sample[sample != 0]
        low_bits = np.bitwise_and(nonzero_values, self._low_mask)

        self._frames += 1
        self._sampled += int(sample.size)
        self._nonzero += int(nonzero_values.size)
        self._above_right_max += int(np.count_nonzero(nonzero_values > self._right_max))
        low_zero = int(np.count_nonzero(low_bits == 0))
        self._low_zero += low_zero
        self._nonzero_low_bits += int(low_bits.size) - low_zero
        if low_bits.size:
            self._low_patterns.update(
                int(value) for value in np.unique(low_bits[low_bits != 0])
            )

        self.state = AlignmentVerificationState.COLLECTING
        enough_volume = (
            self._frames >= self.min_frames
            and self._sampled >= self.min_sampled_pixels
            and self._nonzero >= self.min_nonzero_pixels
        )
        if enough_volume:
            evidence = self.evidence
            # Right alignment requires both an empty high-bit region and strong
            # variation in bits that a left-aligned container must keep zero.
            high_region_empty = evidence.above_right_max_pixels == 0
            varied_low_bits = (
                evidence.nonzero_low_bits_pixels >= 100
                and len(evidence.nonzero_low_bit_patterns) >= min(3, self._low_mask)
            )
            if high_region_empty and varied_low_bits:
                self.state = AlignmentVerificationState.VERIFIED_RIGHT
                return self.state

            # Left alignment requires the padding bits to be zero for at least
            # 99.9% of nonzero values plus values that cannot fit in an
            # unshifted sensor-width DN. This deliberately leaves dark,
            # quantized data ambiguous instead of guessing.
            left_padding_fixed = evidence.low_bits_zero_ratio >= 0.999
            left_scale_visible = (
                evidence.above_right_max_pixels >= 100
                and evidence.above_right_max_ratio >= 0.01
            )
            if left_padding_fixed and left_scale_visible:
                self.state = AlignmentVerificationState.VERIFIED_LEFT
                return self.state

        if self._frames >= self.max_frames and enough_volume:
            self.state = AlignmentVerificationState.AMBIGUOUS
        return self.state
