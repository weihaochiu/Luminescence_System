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
    bright_component_mask: np.ndarray
    candidate_count: int = 0
    selected_method: str = ""
    selected_score: float | None = None
    tick_comb_axis_angle_deg: float | None = None
    tick_comb_support: float = 0.0
    orientation_disagreement_deg: float | None = None


@dataclass
class _Candidate:
    score: float
    polygon: np.ndarray
    rect: tuple[tuple[float, float], tuple[float, float], float]
    method: str


class RulerDetector:
    """Find an elongated rectangular region using several independent cues."""

    def __init__(self, config: CalibrationConfig | None = None) -> None:
        self.config = config or CalibrationConfig()

    def detect(self, image: np.ndarray) -> tuple[RulerDetection, RulerDetectionArtifacts]:
        gray = np.ascontiguousarray(normalize_to_uint8(image))
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
        component_blur = cv2.GaussianBlur(gray, (9, 9), 0)
        _, bright_components = cv2.threshold(
            component_blur, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU
        )
        component_close_size = max(5, int(round(min(height, width) * 0.01)))
        bright_components = cv2.morphologyEx(
            bright_components,
            cv2.MORPH_CLOSE,
            cv2.getStructuringElement(
                cv2.MORPH_ELLIPSE, (component_close_size, component_close_size)
            ),
        )

        contours: list[np.ndarray] = []
        for mask in (edge_mask, bright, dark):
            found, _ = cv2.findContours(mask, cv2.RETR_LIST, cv2.CHAIN_APPROX_SIMPLE)
            contours.extend(found)

        overlay = cv2.cvtColor(gray, cv2.COLOR_GRAY2BGR)
        candidates: list[_Candidate] = []
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
            candidates.append(_Candidate(score, candidate_polygon, rect, "contour"))

        component_contours, _ = cv2.findContours(
            bright_components, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE
        )
        for contour in component_contours:
            contour_area = float(cv2.contourArea(contour))
            if contour_area <= 0:
                continue
            rect = cv2.minAreaRect(contour)
            (_, _), (rw, rh), _ = rect
            long_side, short_side = max(rw, rh), min(rw, rh)
            if short_side < 8 or long_side <= short_side:
                continue
            box = cv2.boxPoints(rect)
            box_area = float(long_side * short_side)
            area_fraction = box_area / image_area
            component_area_fraction = contour_area / image_area
            aspect = long_side / short_side
            rectangularity = min(1.0, contour_area / max(box_area, 1.0))
            if (
                aspect < self.config.partial_ruler_min_aspect_ratio
                or area_fraction < self.config.min_ruler_area_fraction
                or area_fraction > self.config.max_ruler_area_fraction
                or rectangularity < self.config.partial_ruler_min_rectangularity
            ):
                continue
            periodicity_score = self._tick_periodicity_score(gray, rect)
            border_touching = self._touches_border(contour, width, height)
            standard_aspect = aspect >= self.config.min_ruler_aspect_ratio
            partial_supported = (
                border_touching
                and component_area_fraction >= self.config.partial_ruler_min_area_fraction
                and periodicity_score >= self.config.partial_ruler_min_periodicity
            )
            if not (standard_aspect or partial_supported):
                continue
            aspect_score = np.clip(
                (aspect - self.config.partial_ruler_min_aspect_ratio) / 5.0, 0.0, 1.0
            )
            area_score = np.clip(component_area_fraction / 0.25, 0.0, 1.0)
            edge_score = self._parallel_edge_score(edges, box)
            contrast_score = self._component_contrast_score(gray, contour)
            score = float(
                0.12 * aspect_score
                + 0.20 * area_score
                + 0.20 * rectangularity
                + 0.10 * edge_score
                + 0.25 * periodicity_score
                + 0.08 * contrast_score
                + 0.05 * float(border_touching)
            )
            candidate_polygon = self._perspective_polygon(contour, box, box_area)
            cv2.polylines(
                overlay,
                [np.rint(candidate_polygon).astype(np.int32)],
                True,
                (255, int(100 + 155 * score), 0),
                2,
            )
            candidates.append(
                _Candidate(score, candidate_polygon, rect, "bright_component")
            )

        best = max(candidates, key=lambda item: item.score, default=None)

        if best is None or best.score < self.config.min_ruler_confidence:
            detection = RulerDetection(
                success=False,
                confidence=0.0 if best is None else best.score,
                reason="ruler_not_found",
            )
        else:
            score, box, rect = best.score, best.polygon, best.rect
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

        tick_comb_angle: float | None = None
        tick_comb_support = 0.0
        orientation_disagreement: float | None = None
        if detection.success:
            tick_comb_angle, tick_comb_support = self._tick_comb_axis_angle(
                edges, detection.angle_deg
            )
            if tick_comb_angle is not None:
                orientation_disagreement = self._axis_angle_error(
                    detection.angle_deg, tick_comb_angle
                )

        return detection, RulerDetectionArtifacts(
            gray,
            edges,
            overlay,
            bright_components,
            candidate_count=len(candidates),
            selected_method="" if best is None else best.method,
            selected_score=None if best is None else best.score,
            tick_comb_axis_angle_deg=tick_comb_angle,
            tick_comb_support=tick_comb_support,
            orientation_disagreement_deg=orientation_disagreement,
        )

    @staticmethod
    def _tick_comb_axis_angle(
        edges: np.ndarray,
        ruler_axis_angle_deg: float,
    ) -> tuple[float | None, float]:
        minimum_length = max(18, int(round(min(edges.shape) * 0.012)))
        maximum_length = max(minimum_length + 1, int(round(min(edges.shape) * 0.18)))
        lines = cv2.HoughLinesP(
            edges,
            1,
            np.pi / 180.0,
            threshold=max(20, minimum_length),
            minLineLength=minimum_length,
            maxLineGap=max(4, int(round(min(edges.shape) * 0.004))),
        )
        if lines is None:
            return None, 0.0
        target_tick_angle = (ruler_axis_angle_deg + 90.0) % 180.0
        angles: list[float] = []
        weights: list[float] = []
        for x1, y1, x2, y2 in lines[:, 0]:
            length = float(np.hypot(x2 - x1, y2 - y1))
            if length > maximum_length:
                continue
            angle = (float(np.degrees(np.arctan2(y2 - y1, x2 - x1))) + 180.0) % 180.0
            if RulerDetector._axis_angle_error(angle, target_tick_angle) > 20.0:
                continue
            angles.append(angle)
            weights.append(length)
        if len(angles) < 2:
            return None, min(1.0, len(angles) / 8.0)
        doubled = np.deg2rad(np.asarray(angles) * 2.0)
        weight_array = np.asarray(weights)
        sine = float(np.average(np.sin(doubled), weights=weight_array))
        cosine = float(np.average(np.cos(doubled), weights=weight_array))
        tick_angle = (float(np.degrees(np.arctan2(sine, cosine))) * 0.5) % 180.0
        axis_angle = (tick_angle - 90.0) % 180.0
        coherence = float(np.hypot(sine, cosine))
        support = float(np.clip((len(angles) / 24.0) * coherence, 0.0, 1.0))
        return axis_angle, support

    @staticmethod
    def _axis_angle_error(first: float, second: float) -> float:
        return abs((first - second + 90.0) % 180.0 - 90.0)

    @staticmethod
    def _touches_border(contour: np.ndarray, width: int, height: int) -> bool:
        x, y, box_width, box_height = cv2.boundingRect(contour)
        margin = 2
        return (
            x <= margin
            or y <= margin
            or x + box_width >= width - margin
            or y + box_height >= height - margin
        )

    @staticmethod
    def _component_contrast_score(gray: np.ndarray, contour: np.ndarray) -> float:
        mask = np.zeros_like(gray)
        cv2.drawContours(mask, [contour], -1, 255, -1)
        radius = max(5, int(round(min(gray.shape) * 0.012)))
        dilated = cv2.dilate(
            mask,
            cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (radius, radius)),
        )
        ring = cv2.subtract(dilated, mask)
        inside = gray[mask > 0]
        outside = gray[ring > 0]
        if inside.size == 0 or outside.size == 0:
            return 0.0
        contrast = float(np.median(inside) - np.median(outside))
        return float(np.clip(contrast / 128.0, 0.0, 1.0))

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
