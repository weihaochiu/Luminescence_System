from __future__ import annotations

from dataclasses import dataclass

import cv2
import numpy as np

from .config import CalibrationConfig
from .image_utils import normalize_axis_angle, normalize_to_uint8
from .models import RulerDetection


@dataclass
class RulerDetectionArtifacts:
    normalized: np.ndarray
    edges: np.ndarray
    candidates_overlay: np.ndarray


class RulerDetector:
    """Find an elongated rectangular region using several independent cues."""

    def __init__(self, config: CalibrationConfig | None = None) -> None:
        self.config = config or CalibrationConfig()

    def detect(self, image: np.ndarray) -> tuple[RulerDetection, RulerDetectionArtifacts]:
        gray = normalize_to_uint8(image)
        height, width = gray.shape
        image_area = float(height * width)
        clahe = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8)).apply(gray)
        blurred = cv2.GaussianBlur(clahe, (5, 5), 0)
        edges = cv2.Canny(blurred, 45, 135)
        close_size = max(5, int(round(min(height, width) * 0.015)))
        kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (close_size, close_size))
        edge_mask = cv2.morphologyEx(edges, cv2.MORPH_CLOSE, kernel)
        _, bright = cv2.threshold(blurred, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
        _, dark = cv2.threshold(blurred, 0, 255, cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU)

        contours: list[np.ndarray] = []
        for mask in (edge_mask, bright, dark):
            found, _ = cv2.findContours(mask, cv2.RETR_LIST, cv2.CHAIN_APPROX_SIMPLE)
            contours.extend(found)

        overlay = cv2.cvtColor(gray, cv2.COLOR_GRAY2BGR)
        best: tuple[float, np.ndarray, tuple[tuple[float, float], tuple[float, float], float]] | None = None
        seen: set[tuple[int, int, int, int]] = set()
        for contour in contours:
            contour_area = float(cv2.contourArea(contour))
            if contour_area <= 0:
                continue
            rect = cv2.minAreaRect(contour)
            (cx, cy), (rw, rh), _ = rect
            long_side, short_side = max(rw, rh), min(rw, rh)
            if short_side < 8 or long_side <= short_side:
                continue
            box = cv2.boxPoints(rect)
            x, y, bw, bh = cv2.boundingRect(np.rint(box).astype(np.int32))
            signature = (x // 4, y // 4, bw // 4, bh // 4)
            if signature in seen:
                continue
            seen.add(signature)
            box_area = float(long_side * short_side)
            area_fraction = box_area / image_area
            aspect = long_side / short_side
            rectangularity = min(1.0, contour_area / max(box_area, 1.0))
            if (
                aspect < self.config.min_ruler_aspect_ratio
                or area_fraction < self.config.min_ruler_area_fraction
                or area_fraction > self.config.max_ruler_area_fraction
            ):
                continue

            aspect_score = np.clip(
                (aspect - self.config.min_ruler_aspect_ratio) / 7.0, 0.0, 1.0
            )
            area_score = np.clip(area_fraction / 0.12, 0.0, 1.0)
            edge_score = self._parallel_edge_score(edges, box)
            periodicity_score = self._tick_periodicity_score(gray, rect)
            score = float(
                0.27 * aspect_score
                + 0.20 * area_score
                + 0.23 * rectangularity
                + 0.15 * edge_score
                + 0.15 * periodicity_score
            )
            candidate_polygon = self._perspective_polygon(contour, box, box_area)
            color = (0, int(100 + 155 * score), 255)
            cv2.polylines(overlay, [np.rint(candidate_polygon).astype(np.int32)], True, color, 1)
            if best is None or score > best[0]:
                best = (score, candidate_polygon, rect)

        if best is None or best[0] < self.config.min_ruler_confidence:
            detection = RulerDetection(
                success=False,
                confidence=0.0 if best is None else best[0],
                reason="ruler_not_found",
            )
        else:
            score, box, rect = best
            (cx, cy), (rw, rh), rect_angle = rect
            angle = rect_angle if rw >= rh else rect_angle + 90.0
            angle = normalize_axis_angle(angle)
            polygon = [(float(point[0]), float(point[1])) for point in box]
            detection = RulerDetection(
                success=True,
                polygon=polygon,
                center=(float(cx), float(cy)),
                angle_deg=angle,
                confidence=score,
            )
            cv2.polylines(overlay, [np.rint(box).astype(np.int32)], True, (0, 255, 0), 3)
            axis = np.asarray((np.cos(np.deg2rad(angle)), np.sin(np.deg2rad(angle))))
            half = max(rw, rh) * 0.5
            p1 = np.rint(np.asarray((cx, cy)) - axis * half).astype(int)
            p2 = np.rint(np.asarray((cx, cy)) + axis * half).astype(int)
            cv2.line(overlay, tuple(p1), tuple(p2), (255, 0, 255), 2)

        return detection, RulerDetectionArtifacts(gray, edges, overlay)

    @staticmethod
    def _perspective_polygon(
        contour: np.ndarray,
        fallback: np.ndarray,
        box_area: float,
    ) -> np.ndarray:
        hull = cv2.convexHull(contour)
        perimeter = cv2.arcLength(hull, True)
        approximation = cv2.approxPolyDP(hull, 0.02 * perimeter, True).reshape(-1, 2)
        if (
            approximation.shape == (4, 2)
            and cv2.isContourConvex(approximation.astype(np.float32))
            and cv2.contourArea(approximation.astype(np.float32)) >= box_area * 0.5
        ):
            edges = [
                np.linalg.norm(approximation[(index + 1) % 4] - approximation[index])
                for index in range(4)
            ]
            if min(edges) >= 6:
                return approximation.astype(np.float32)
        return fallback.astype(np.float32)

    @staticmethod
    def _parallel_edge_score(edges: np.ndarray, box: np.ndarray) -> float:
        lengths = [float(np.linalg.norm(box[(i + 1) % 4] - box[i])) for i in range(4)]
        long_indices = np.argsort(lengths)[-2:]
        samples: list[float] = []
        for index in long_indices:
            p1 = box[index]
            p2 = box[(index + 1) % 4]
            mask = np.zeros_like(edges)
            cv2.line(mask, tuple(np.rint(p1).astype(int)), tuple(np.rint(p2).astype(int)), 255, 5)
            values = edges[mask > 0]
            samples.append(float(np.count_nonzero(values)) / max(values.size, 1))
        return float(np.clip(np.mean(samples) * 3.0, 0.0, 1.0)) if samples else 0.0

    @staticmethod
    def _tick_periodicity_score(
        gray: np.ndarray,
        rect: tuple[tuple[float, float], tuple[float, float], float],
    ) -> float:
        (cx, cy), (rw, rh), angle = rect
        if rw < rh:
            rw, rh = rh, rw
            angle += 90.0
        out_w = max(16, min(800, int(round(rw))))
        out_h = max(12, min(180, int(round(rh))))
        rotation = cv2.getRotationMatrix2D((cx, cy), angle, 1.0)
        rotated = cv2.warpAffine(gray, rotation, (gray.shape[1], gray.shape[0]))
        roi = cv2.getRectSubPix(rotated, (out_w, out_h), (cx, cy))
        if roi.size == 0 or roi.shape[1] < 20:
            return 0.0
        band = max(3, roi.shape[0] // 3)
        edge_bands = np.vstack((roi[:band], roi[-band:]))
        gradient = np.abs(cv2.Sobel(edge_bands, cv2.CV_32F, 1, 0, ksize=3))
        projection = gradient.mean(axis=0)
        centered = projection - np.median(projection)
        if float(np.max(centered)) <= 0:
            return 0.0
        threshold = np.median(centered) + 1.5 * np.median(np.abs(centered - np.median(centered)))
        peaks = int(np.count_nonzero(centered > threshold))
        density = peaks / max(len(centered), 1)
        return float(np.clip(density / 0.12, 0.0, 1.0))
