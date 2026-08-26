from __future__ import annotations

from dataclasses import dataclass

import cv2
import numpy as np

from .config import CalibrationConfig
from .models import TickMark
from .ruler_rectifier import RectificationResult


@dataclass
class TickDetectionResult:
    ticks: list[TickMark]
    threshold: np.ndarray
    overlay: np.ndarray
    candidate_count: int


class TickDetector:
    """Detect many edge-connected ruler ticks in the rectified coordinate system."""

    def __init__(self, config: CalibrationConfig | None = None) -> None:
        self.config = config or CalibrationConfig()

    def detect(self, rectification: RectificationResult) -> TickDetectionResult:
        gray = rectification.image
        height, width = gray.shape
        block_size = max(15, (min(height, 101) // 2) * 2 + 1)
        threshold = cv2.adaptiveThreshold(
            gray,
            255,
            cv2.ADAPTIVE_THRESH_GAUSSIAN_C,
            cv2.THRESH_BINARY_INV,
            block_size,
            5,
        )
        # Remove the long ruler border first so a connected "comb" does not become
        # one contour, then retain marks perpendicular to the ruler axis.
        horizontal = cv2.morphologyEx(
            threshold,
            cv2.MORPH_OPEN,
            cv2.getStructuringElement(cv2.MORPH_RECT, (max(15, height // 2), 1)),
        )
        without_border = cv2.subtract(threshold, horizontal)
        vertical_length = max(3, int(round(height * self.config.tick_min_length_fraction)))
        vertical = cv2.morphologyEx(
            without_border,
            cv2.MORPH_OPEN,
            cv2.getStructuringElement(cv2.MORPH_RECT, (1, vertical_length)),
        )
        band_height = max(4, int(round(height * self.config.tick_edge_band_fraction)))
        candidates: list[tuple[float, float, float]] = []
        candidates.extend(self._band_candidates(vertical[:band_height], 0, height, "top"))
        candidates.extend(
            self._band_candidates(vertical[height - band_height :], height - band_height, height, "bottom")
        )
        candidates.extend(
            self._slanted_band_candidates(
                without_border[:band_height], 0, height, "top"
            )
        )
        candidates.extend(
            self._slanted_band_candidates(
                without_border[height - band_height :],
                height - band_height,
                height,
                "bottom",
            )
        )
        merged = self._merge_candidates(candidates, height)
        lengths = np.asarray([item[1] for item in merged], dtype=np.float64)
        major_cut = float(np.percentile(lengths, 82)) if lengths.size else float("inf")
        medium_cut = float(np.percentile(lengths, 58)) if lengths.size else float("inf")
        ticks: list[TickMark] = []
        overlay = cv2.cvtColor(gray, cv2.COLOR_GRAY2BGR)
        for x, length, y_center in merged:
            if length >= major_cut and length >= height * 0.22:
                kind, color = "major", (0, 0, 255)
            elif length >= medium_cut and length >= height * 0.15:
                kind, color = "medium", (0, 165, 255)
            else:
                kind, color = "minor", (0, 255, 0)
            original = rectification.to_original(np.asarray(((x, y_center),), dtype=np.float32))[0]
            tick = TickMark(
                rectified_position_px=float(x),
                original_position=(float(original[0]), float(original[1])),
                length_px=float(length),
                kind=kind,
            )
            ticks.append(tick)
            cv2.line(overlay, (round(x), 0), (round(x), height - 1), color, 1)
        return TickDetectionResult(ticks, threshold, overlay, len(candidates))

    def _band_candidates(
        self,
        band: np.ndarray,
        y_offset: int,
        full_height: int,
        edge: str,
    ) -> list[tuple[float, float, float]]:
        contours, _ = cv2.findContours(band, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        candidates: list[tuple[float, float, float]] = []
        max_width = max(3, int(round(full_height * 0.12)))
        min_length = max(3, int(round(full_height * self.config.tick_min_length_fraction)))
        for contour in contours:
            x, y, width, height = cv2.boundingRect(contour)
            if height < min_length or width > max_width or height < width * 1.35:
                continue
            touches_edge = y <= 2 if edge == "top" else y + height >= band.shape[0] - 2
            # Some rulers have a narrow border before the tick. Permit a small offset.
            allowance = max(4, band.shape[0] // 4)
            near_edge = y <= allowance if edge == "top" else y + height >= band.shape[0] - allowance
            if not (touches_edge or near_edge):
                continue
            candidates.append((x + width * 0.5, float(height), y_offset + y + height * 0.5))
        return candidates

    def _merge_candidates(
        self,
        candidates: list[tuple[float, float, float]],
        full_height: int,
    ) -> list[tuple[float, float, float]]:
        if not candidates:
            return []
        ordered = sorted(candidates, key=lambda item: item[0])
        groups: list[list[tuple[float, float, float]]] = [[ordered[0]]]
        merge_distance = max(
            self.config.tick_merge_distance_px,
            full_height * self.config.tick_merge_distance_height_fraction,
        )
        for candidate in ordered[1:]:
            if candidate[0] - groups[-1][-1][0] <= merge_distance:
                groups[-1].append(candidate)
            else:
                groups.append([candidate])
        merged: list[tuple[float, float, float]] = []
        for group in groups:
            weights = np.asarray([max(item[1], 1.0) for item in group])
            x = float(np.average([item[0] for item in group], weights=weights))
            longest = max(group, key=lambda item: item[1])
            merged.append((x, float(longest[1]), float(longest[2])))
        return merged

    def _slanted_band_candidates(
        self,
        band: np.ndarray,
        y_offset: int,
        full_height: int,
        edge: str,
    ) -> list[tuple[float, float, float]]:
        """Retain ticks with residual perspective/slant after rectification."""
        contours, _ = cv2.findContours(band, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        candidates: list[tuple[float, float, float]] = []
        minimum_length = max(
            3, int(round(full_height * self.config.tick_min_length_fraction))
        )
        maximum_width = max(
            3, int(round(full_height * self.config.tick_max_width_fraction))
        )
        allowance = max(4, band.shape[0] // 4)
        for contour in contours:
            (center_x, center_y), (rect_width, rect_height), angle = cv2.minAreaRect(contour)
            long_side = max(rect_width, rect_height)
            short_side = min(rect_width, rect_height)
            if (
                long_side < minimum_length
                or short_side > maximum_width
                or long_side < short_side * 1.8
            ):
                continue
            long_angle = angle if rect_width >= rect_height else angle + 90.0
            vertical_error = abs((long_angle - 90.0 + 90.0) % 180.0 - 90.0)
            if vertical_error > 25.0:
                continue
            _, y, _, contour_height = cv2.boundingRect(contour)
            near_edge = (
                y <= allowance
                if edge == "top"
                else y + contour_height >= band.shape[0] - allowance
            )
            if not near_edge:
                continue
            candidates.append(
                (float(center_x), float(long_side), float(y_offset + center_y))
            )
        return candidates
