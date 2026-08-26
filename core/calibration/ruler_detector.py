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
    candidate_diagnostics: list[dict[str, object]] | None = None
    threshold_audit: dict[str, object] | None = None


@dataclass
class _Candidate:
    score: float
    polygon: np.ndarray
    rect: tuple[tuple[float, float], tuple[float, float], float]
    method: str
    aspect: float
    area_fraction: float
    rectangularity: float
    periodicity: float
    contrast: float
    border_support: float
    edge_support: float
    tick_comb_support: float = 0.0

    @property
    def axis_angle_deg(self) -> float:
        (_, _), (width, height), angle = self.rect
        return normalize_axis_angle(angle if width >= height else angle + 90.0)


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
        otsu_threshold, bright = cv2.threshold(
            blurred, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU
        )
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
            if area_fraction < 0.09 and aspect > 5.0:
                score = max(0.0, score - 0.12)
            candidate_polygon = self._perspective_polygon(contour, box, box_area)
            color = (0, int(100 + 155 * score), 255)
            cv2.polylines(overlay, [np.rint(candidate_polygon).astype(np.int32)], True, color, 1)
            contrast_score = self._component_contrast_score(gray, contour)
            candidates.append(_Candidate(
                score,
                candidate_polygon,
                rect,
                "contour",
                float(aspect),
                float(area_fraction),
                float(rectangularity),
                float(periodicity_score),
                float(contrast_score),
                float(self._touches_border(contour, width, height)),
                float(edge_score),
            ))

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
            # Very thin, small bright strips are a common glare/shadow fragment
            # of a larger ruler body. Keep them as candidates, but do not let
            # aspect ratio alone outrank whole-body edge evidence.
            if area_fraction < 0.09 and aspect > 5.0:
                score = max(0.0, score - 0.12)
            candidate_polygon = self._perspective_polygon(contour, box, box_area)
            cv2.polylines(
                overlay,
                [np.rint(candidate_polygon).astype(np.int32)],
                True,
                (255, int(100 + 155 * score), 0),
                2,
            )
            candidates.append(
                _Candidate(
                    score,
                    candidate_polygon,
                    rect,
                    "bright_body",
                    float(aspect),
                    float(area_fraction),
                    float(rectangularity),
                    float(periodicity_score),
                    float(contrast_score),
                    float(border_touching),
                    float(edge_score),
                )
            )

        candidates.extend(self._edge_pair_candidates(gray, edges))
        candidates.extend(self._tick_comb_candidates(gray, edges))
        candidates = self._deduplicate_candidates(candidates)

        edge_pair_candidates = [
            candidate for candidate in candidates if candidate.method == "edge_pair"
        ]
        for candidate in candidates:
            if candidate.method != "tick_comb" or not edge_pair_candidates:
                continue
            aligned = max(
                edge.score
                * max(
                    0.0,
                    1.0
                    - self._axis_angle_error(
                        candidate.axis_angle_deg, edge.axis_angle_deg
                    )
                    / 18.0,
                )
                for edge in edge_pair_candidates
            )
            perpendicular = max(
                edge.score
                * max(
                    0.0,
                    1.0
                    - self._axis_angle_error(
                        candidate.axis_angle_deg,
                        (edge.axis_angle_deg + 90.0) % 180.0,
                    )
                    / 18.0,
                )
                for edge in edge_pair_candidates
            )
            candidate.score = float(
                np.clip(candidate.score + 0.25 * aligned - 0.25 * perpendicular, 0.0, 1.0)
            )

        whole_body_candidates = [
            candidate
            for candidate in candidates
            if candidate.method in {"bright_body", "contour"}
            and candidate.area_fraction >= 0.10
        ]
        for candidate in candidates:
            if candidate.method != "tick_comb" or not whole_body_candidates:
                continue
            best_body = max(
                whole_body_candidates,
                key=lambda body: body.score
                * max(
                    0.0,
                    1.0
                    - self._axis_angle_error(
                        candidate.axis_angle_deg, body.axis_angle_deg
                    )
                    / 25.0,
                ),
            )
            disagreement = self._axis_angle_error(
                candidate.axis_angle_deg, best_body.axis_angle_deg
            )
            if disagreement <= 15.0:
                best_body.score = float(
                    min(1.0, best_body.score + 0.25 * candidate.score)
                )
            elif disagreement >= 25.0:
                candidate.score = float(
                    max(0.0, candidate.score - 0.10 * best_body.score)
                )

        tick_candidates = [
            candidate for candidate in candidates if candidate.method == "tick_comb"
        ]
        original_tick_scores = {id(candidate): candidate.score for candidate in tick_candidates}
        for candidate in tick_candidates:
            consensus = sum(
                original_tick_scores[id(other)]
                for other in tick_candidates
                if other is not candidate
                and self._axis_angle_error(
                    candidate.axis_angle_deg, other.axis_angle_deg
                )
                <= 18.0
            )
            candidate.score = float(
                min(1.0, candidate.score + 0.08 * min(1.0, consensus))
            )

        # Tick-comb support is relatively expensive. Audit only the strongest
        # geometric candidates, then use it as an independent reranking cue.
        for candidate in sorted(candidates, key=lambda item: item.score, reverse=True)[:6]:
            _, support = self._tick_comb_axis_angle(edges, candidate.axis_angle_deg)
            if candidate.method != "tick_comb":
                candidate.tick_comb_support = support

        ranked = sorted(candidates, key=lambda item: item.score, reverse=True)
        best = ranked[0] if ranked else None

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

        for rank, candidate in enumerate(ranked[:3], start=1):
            points = np.rint(candidate.polygon).astype(np.int32)
            selected = candidate is best
            color = (0, 255, 0) if selected else (0, 200, 255)
            cv2.polylines(overlay, [points], True, color, 3 if selected else 2)
            anchor = tuple(points[np.argmin(points[:, 0] + points[:, 1])])
            candidate_annotation = f"#{rank} {candidate.method} {candidate.score:.3f}"
            if selected:
                candidate_annotation += " SELECTED"
            cv2.putText(
                overlay,
                candidate_annotation,
                (max(4, int(anchor[0])), max(22, int(anchor[1]) - 7)),
                cv2.FONT_HERSHEY_SIMPLEX,
                0.62,
                color,
                2,
                cv2.LINE_AA,
            )

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

        candidate_diagnostics = [
            {
                "rank": rank,
                "selected": candidate is best,
                "score": candidate.score,
                "method": candidate.method,
                "aspect": candidate.aspect,
                "area_fraction": candidate.area_fraction,
                "rectangularity": candidate.rectangularity,
                "periodicity": candidate.periodicity,
                "contrast": candidate.contrast,
                "border_support": candidate.border_support,
                "edge_support": candidate.edge_support,
                "tick_comb_support": candidate.tick_comb_support,
                "angle_deg": candidate.axis_angle_deg,
                "polygon": candidate.polygon.tolist(),
            }
            for rank, candidate in enumerate(ranked[:10], start=1)
        ]
        percentile_levels = (55, 65, 75, 85)
        threshold_audit = {
            "otsu_level_dn8": float(otsu_threshold),
            "otsu_bright_fraction": float(np.mean(bright > 0)),
            "percentile_levels_dn8": {
                str(level): float(np.percentile(blurred, level))
                for level in percentile_levels
            },
            "bright_fractions": {
                str(level): float(
                    np.mean(blurred >= float(np.percentile(blurred, level)))
                )
                for level in percentile_levels
            },
        }
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
            candidate_diagnostics=candidate_diagnostics,
            threshold_audit=threshold_audit,
        )

    def _edge_pair_candidates(
        self, gray: np.ndarray, edges: np.ndarray
    ) -> list[_Candidate]:
        """Build whole-ruler hypotheses from clusters of long parallel edges."""
        scale = min(1.0, 900.0 / min(gray.shape))
        small_edges = (
            edges
            if scale == 1.0
            else cv2.resize(edges, None, fx=scale, fy=scale, interpolation=cv2.INTER_NEAREST)
        )
        small_gray = (
            gray
            if scale == 1.0
            else cv2.resize(gray, None, fx=scale, fy=scale, interpolation=cv2.INTER_AREA)
        )
        minimum = max(35, int(round(min(small_edges.shape) * 0.085)))
        lines = cv2.HoughLinesP(
            small_edges,
            1,
            np.pi / 360.0,
            threshold=max(35, minimum // 2),
            minLineLength=minimum,
            maxLineGap=max(10, int(round(min(small_edges.shape) * 0.035))),
        )
        if lines is None:
            return []
        brightness_threshold = float(np.percentile(small_gray, 90.0))
        bright_lines: list[np.ndarray] = []
        for line in lines[:, 0]:
            x1, y1, x2, y2 = (int(value) for value in line)
            center_x = (x1 + x2) // 2
            center_y = (y1 + y2) // 2
            patch = small_gray[
                max(0, center_y - 7) : min(small_gray.shape[0], center_y + 8),
                max(0, center_x - 7) : min(small_gray.shape[1], center_x + 8),
            ]
            if patch.size and float(np.percentile(patch, 75.0)) >= brightness_threshold:
                bright_lines.append(line)
        line_data = self._line_data(np.asarray(bright_lines)) if bright_lines else []
        clusters = self._orientation_clusters(line_data, half_width_deg=4.0, limit=5)
        return self._line_cluster_candidates(
            gray,
            edges,
            clusters,
            scale,
            method="edge_pair",
            angle_offset_deg=0.0,
            minimum_lines=2,
        )

    def _tick_comb_candidates(
        self, gray: np.ndarray, edges: np.ndarray
    ) -> list[_Candidate]:
        """Build hypotheses from repeated shorter marks perpendicular to the axis."""
        scale = min(1.0, 900.0 / min(gray.shape))
        small_edges = (
            edges
            if scale == 1.0
            else cv2.resize(edges, None, fx=scale, fy=scale, interpolation=cv2.INTER_NEAREST)
        )
        minimum = max(12, int(round(min(small_edges.shape) * 0.012)))
        maximum = max(minimum + 1, int(round(min(small_edges.shape) * 0.18)))
        lines = cv2.HoughLinesP(
            small_edges,
            1,
            np.pi / 180.0,
            threshold=max(18, minimum),
            minLineLength=minimum,
            maxLineGap=max(4, int(round(min(small_edges.shape) * 0.006))),
        )
        if lines is None:
            return []
        line_data = [
            item for item in self._line_data(lines[:, 0]) if item[1] <= maximum
        ]
        clusters = self._orientation_clusters(line_data, half_width_deg=7.0, limit=4)
        return self._line_cluster_candidates(
            gray,
            edges,
            clusters,
            scale,
            method="tick_comb",
            angle_offset_deg=90.0,
            minimum_lines=6,
        )

    def _line_cluster_candidates(
        self,
        gray: np.ndarray,
        edges: np.ndarray,
        clusters: list[list[tuple[float, float, np.ndarray]]],
        scale: float,
        *,
        method: str,
        angle_offset_deg: float,
        minimum_lines: int,
    ) -> list[_Candidate]:
        image_area = float(gray.size)
        output: list[_Candidate] = []
        for cluster in clusters:
            if len(cluster) < minimum_lines:
                continue
            points = np.asarray(
                [
                    point
                    for _, _, line in cluster
                    for point in ((line[0], line[1]), (line[2], line[3]))
                ],
                dtype=np.float32,
            ) / scale
            comb_support = 0.0
            if angle_offset_deg:
                centers = np.asarray(
                    [((line[0] + line[2]) * 0.5, (line[1] + line[3]) * 0.5) for _, _, line in cluster],
                    dtype=np.float32,
                ) / scale
                lengths = np.asarray([length / scale for _, length, _ in cluster])
                tick_angle = self._weighted_axis_angle(
                    [angle for angle, _, _ in cluster],
                    [length for _, length, _ in cluster],
                )
                axis_angle = (tick_angle + angle_offset_deg) % 180.0
                axis = np.asarray((np.cos(np.deg2rad(axis_angle)), np.sin(np.deg2rad(axis_angle))))
                cross = np.asarray((-axis[1], axis[0]))
                center = centers.mean(axis=0)
                along = (centers - center) @ axis
                across = (centers - center) @ cross
                half_length = max(20.0, (float(along.max()) - float(along.min())) * 0.55)
                half_width = max(12.0, float(np.percentile(lengths, 90)) * 0.75)
                center = center + axis * ((float(along.max()) + float(along.min())) * 0.5)
                center = center + cross * ((float(across.max()) + float(across.min())) * 0.5)
                rect = ((float(center[0]), float(center[1])), (half_length * 2, half_width * 2), axis_angle)
                comb_support = self._comb_regularity_score(
                    centers, axis, min(gray.shape), float(np.hypot(*gray.shape))
                )
            else:
                axis_angle = self._weighted_axis_angle(
                    [angle for angle, _, _ in cluster],
                    [length for _, length, _ in cluster],
                )
                rect = self._oriented_bounding_rect(points, axis_angle)
            (_, _), (rw, rh), _ = rect
            long_side, short_side = max(rw, rh), min(rw, rh)
            if short_side < 8 or long_side <= short_side:
                continue
            raw_area_fraction = long_side * short_side / image_area
            raw_aspect = long_side / short_side
            if raw_area_fraction < 0.12 and raw_aspect > 4.0:
                expansion = min(5.0, raw_aspect / 2.5)
                if rw >= rh:
                    rect = (rect[0], (rw, rh * expansion), rect[2])
                else:
                    rect = (rect[0], (rw * expansion, rh), rect[2])
                (_, _), (rw, rh), _ = rect
                long_side, short_side = max(rw, rh), min(rw, rh)
            aspect = long_side / short_side
            area_fraction = long_side * short_side / image_area
            if (
                aspect < 1.35
                or area_fraction < self.config.min_ruler_area_fraction
                or area_fraction > self.config.max_ruler_area_fraction
            ):
                continue
            box = cv2.boxPoints(rect)
            periodicity = self._tick_periodicity_score(gray, rect)
            edge_support = self._parallel_edge_score(edges, box)
            contrast = self._component_contrast_score(gray, box.astype(np.float32))
            border = float(self._touches_border(box.astype(np.int32), gray.shape[1], gray.shape[0]))
            total_line_length = sum(length for _, length, _ in cluster) / scale
            line_support = float(np.clip(total_line_length / max(long_side * 5.0, 1.0), 0.0, 1.0))
            rectangularity = float(np.clip(line_support, 0.0, 1.0))
            aspect_score = float(np.clip((aspect - 1.35) / 5.0, 0.0, 1.0))
            area_score = float(np.clip(area_fraction / 0.30, 0.0, 1.0))
            score = float(
                0.13 * aspect_score
                + 0.25 * area_score
                + 0.20 * line_support
                + 0.12 * edge_support
                + 0.12 * periodicity
                + 0.12 * contrast
                + 0.06 * border
            )
            if method == "tick_comb":
                score = float(0.55 * score + 0.35 * comb_support + 0.10 * periodicity)
            if area_fraction > 0.75:
                score *= max(0.35, 1.0 - (area_fraction - 0.75) * 2.0)
            output.append(_Candidate(
                score,
                box.astype(np.float32),
                rect,
                method,
                float(aspect),
                float(area_fraction),
                rectangularity,
                float(periodicity),
                float(contrast),
                border,
                float(edge_support),
                float(comb_support),
            ))
        return output

    @staticmethod
    def _line_data(lines: np.ndarray) -> list[tuple[float, float, np.ndarray]]:
        output: list[tuple[float, float, np.ndarray]] = []
        for line in lines:
            x1, y1, x2, y2 = line
            length = float(np.hypot(x2 - x1, y2 - y1))
            angle = (float(np.degrees(np.arctan2(y2 - y1, x2 - x1))) + 180.0) % 180.0
            output.append((angle, length, line))
        return output

    @classmethod
    def _orientation_clusters(
        cls,
        lines: list[tuple[float, float, np.ndarray]],
        *,
        half_width_deg: float,
        limit: int,
    ) -> list[list[tuple[float, float, np.ndarray]]]:
        scored: list[tuple[float, float, list[tuple[float, float, np.ndarray]]]] = []
        for center in np.arange(0.0, 180.0, 2.0):
            selected = [
                item
                for item in lines
                if cls._axis_angle_error(item[0], float(center)) <= half_width_deg
            ]
            if selected:
                scored.append((sum(item[1] for item in selected), float(center), selected))
        output: list[list[tuple[float, float, np.ndarray]]] = []
        chosen_angles: list[float] = []
        for _, center, selected in sorted(scored, key=lambda item: item[0], reverse=True):
            if any(cls._axis_angle_error(center, angle) <= 10.0 for angle in chosen_angles):
                continue
            output.append(selected)
            chosen_angles.append(center)
            if len(output) >= limit:
                break
        return output

    @staticmethod
    def _weighted_axis_angle(angles: list[float], weights: list[float]) -> float:
        doubled = np.deg2rad(np.asarray(angles) * 2.0)
        values = np.asarray(weights)
        sine = float(np.average(np.sin(doubled), weights=values))
        cosine = float(np.average(np.cos(doubled), weights=values))
        return (float(np.degrees(np.arctan2(sine, cosine))) * 0.5) % 180.0

    @staticmethod
    def _oriented_bounding_rect(
        points: np.ndarray, axis_angle_deg: float
    ) -> tuple[tuple[float, float], tuple[float, float], float]:
        axis = np.asarray(
            (np.cos(np.deg2rad(axis_angle_deg)), np.sin(np.deg2rad(axis_angle_deg)))
        )
        cross = np.asarray((-axis[1], axis[0]))
        origin = points.mean(axis=0)
        along = (points - origin) @ axis
        across = (points - origin) @ cross
        along_low, along_high = np.percentile(along, (2.0, 98.0))
        across_low, across_high = np.percentile(across, (2.0, 98.0))
        center = (
            origin
            + axis * ((along_low + along_high) * 0.5)
            + cross * ((across_low + across_high) * 0.5)
        )
        return (
            (float(center[0]), float(center[1])),
            (
                max(1.0, float(along_high - along_low)),
                max(1.0, float(across_high - across_low)),
            ),
            float(axis_angle_deg),
        )

    @staticmethod
    def _comb_regularity_score(
        centers: np.ndarray,
        axis: np.ndarray,
        minimum_image_dimension: int,
        image_diagonal: float,
    ) -> float:
        positions = sorted(float(value) for value in centers @ axis)
        merge_distance = max(3.0, minimum_image_dimension * 0.0055)
        groups: list[list[float]] = []
        for position in positions:
            if not groups or position - groups[-1][-1] > merge_distance:
                groups.append([position])
            else:
                groups[-1].append(position)
        if len(groups) < 5:
            return 0.0
        merged = np.asarray([float(np.mean(group)) for group in groups])
        gaps = np.diff(merged)
        median_gap = float(np.median(gaps))
        if median_gap <= 0:
            return 0.0
        valid = gaps[(gaps > median_gap * 0.45) & (gaps < median_gap * 1.8)]
        if valid.size < 3:
            return 0.0
        coefficient = float(np.std(valid) / max(np.mean(valid), 1e-6))
        coverage = float(valid.size / max(gaps.size, 1))
        count_support = float(np.clip((len(groups) - 5) / 30.0, 0.0, 1.0))
        consistency = float(np.clip((0.55 - coefficient) / 0.40, 0.0, 1.0)) * coverage
        span_support = float(
            np.clip((merged[-1] - merged[0]) / max(image_diagonal * 0.55, 1.0), 0.0, 1.0)
        )
        return float(0.55 * count_support + 0.30 * consistency + 0.15 * span_support)

    @classmethod
    def _deduplicate_candidates(cls, candidates: list[_Candidate]) -> list[_Candidate]:
        ranked = sorted(candidates, key=lambda item: item.score, reverse=True)
        output: list[_Candidate] = []
        for candidate in ranked:
            (cx, cy), (width, height), _ = candidate.rect
            long_side = max(width, height)
            duplicate = False
            for kept in output:
                (kx, ky), (kw, kh), _ = kept.rect
                distance = float(np.hypot(cx - kx, cy - ky))
                if (
                    candidate.method == kept.method
                    and distance <= max(8.0, long_side * 0.04)
                    and cls._axis_angle_error(candidate.axis_angle_deg, kept.axis_angle_deg) <= 3.0
                    and abs(long_side - max(kw, kh)) <= max(12.0, long_side * 0.08)
                ):
                    duplicate = True
                    break
            if not duplicate:
                output.append(candidate)
        return output

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
        cv2.drawContours(mask, [np.rint(contour).astype(np.int32)], -1, 255, -1)
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
        threshold = np.median(centered) + 1.5 * np.median(
            np.abs(centered - np.median(centered))
        )
        peaks = int(np.count_nonzero(centered > threshold))
        density = peaks / max(len(centered), 1)
        return float(np.clip(density / 0.12, 0.0, 1.0))
