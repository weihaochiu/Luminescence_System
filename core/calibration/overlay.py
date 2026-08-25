from __future__ import annotations

import cv2
import numpy as np

from core.i18n import tr

from .image_utils import angle_axis, to_bgr, transform_points
from .models import CalibrationResult, DetectedNumber, TickMark
from .ruler_rectifier import RectificationResult


def draw_ocr_overlay(
    rectified_image: np.ndarray,
    numbers: list[DetectedNumber],
) -> np.ndarray:
    overlay = cv2.cvtColor(rectified_image, cv2.COLOR_GRAY2BGR)
    for number in numbers:
        x, y, width, height = number.bbox
        color = (0, 200, 0) if number.accepted else (0, 0, 255)
        cv2.rectangle(overlay, (x, y), (x + width, y + height), color, 2)
        label = tr("calibration.overlay.raw", value=number.raw_text)
        if number.corrected_value is not None:
            label += " " + tr("calibration.overlay.corrected", value=number.corrected_value)
        cv2.putText(
            overlay,
            label,
            (max(0, x), max(14, y - 4)),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.42,
            color,
            1,
            cv2.LINE_AA,
        )
    return overlay


def draw_final_overlay(
    original_image: np.ndarray,
    result: CalibrationResult,
    rectification: RectificationResult | None,
) -> np.ndarray:
    overlay = to_bgr(original_image)
    detection = result.ruler_detection
    if detection is not None and detection.polygon:
        polygon = np.rint(np.asarray(detection.polygon)).astype(np.int32)
        cv2.polylines(overlay, [polygon], True, (0, 255, 255), 3)
        center = np.asarray(detection.center, dtype=np.float64)
        axis = angle_axis(detection.angle_deg)
        projections = (np.asarray(detection.polygon) - center) @ axis
        p1 = np.rint(center + axis * float(np.min(projections))).astype(int)
        p2 = np.rint(center + axis * float(np.max(projections))).astype(int)
        cv2.line(overlay, tuple(p1), tuple(p2), (255, 0, 255), 2)

    for tick in result.detected_minor_ticks:
        _draw_tick(overlay, tick, (0, 220, 0))
    for tick in result.detected_major_ticks:
        _draw_tick(overlay, tick, (0, 0, 255), radius=5)
        if tick.fitted_mm is not None:
            point = tuple(np.rint(tick.original_position).astype(int))
            _outlined_text(
                overlay,
                f"fit {tick.fitted_mm:g} mm",
                (point[0] + 6, point[1] - 6),
                color=(0, 180, 255),
                scale=0.38,
            )
    for tick in result.rejected_ticks:
        _draw_tick(overlay, tick, (128, 128, 128), radius=4, cross=True)

    if rectification is not None and rectification.success:
        for number in result.detected_numbers:
            _draw_number_in_original(overlay, number, rectification)

    lines = [
        f"Ruler angle: {result.ruler_angle_deg:.2f} deg" if result.ruler_angle_deg is not None else "Ruler: not detected",
        f"Scale: {result.pixels_per_mm:.4f} px/mm" if result.pixels_per_mm is not None else "Scale: unavailable",
        f"Resolution: {result.um_per_pixel:.4f} um/px" if result.um_per_pixel is not None else "Resolution: unavailable",
        f"Span: {result.calibration_span_mm:.1f} mm  Fit error: {result.fit_error_percent:.2f}%" if result.fit_error_percent is not None else "Fit: unavailable",
        f"Quality: {result.quality_label} ({result.quality_score:.1f}/100)",
    ]
    y = 28
    for line in lines:
        _outlined_text(overlay, line, (14, y))
        y += 25

    if result.success and result.scale_bar is not None:
        _draw_scale_bar(overlay, result.scale_bar.rendered_length_px, result.scale_bar.label)
    return overlay


def _draw_tick(
    image: np.ndarray,
    tick: TickMark,
    color: tuple[int, int, int],
    *,
    radius: int = 3,
    cross: bool = False,
) -> None:
    point = tuple(np.rint(tick.original_position).astype(int))
    if cross:
        cv2.drawMarker(image, point, color, cv2.MARKER_TILTED_CROSS, radius * 3, 2)
    else:
        cv2.circle(image, point, radius, color, -1)


def _draw_number_in_original(
    image: np.ndarray,
    number: DetectedNumber,
    rectification: RectificationResult,
) -> None:
    x, y, width, height = number.bbox
    corners = np.asarray(
        ((x, y), (x + width, y), (x + width, y + height), (x, y + height)),
        dtype=np.float32,
    )
    original = np.rint(transform_points(corners, rectification.rectified_to_original)).astype(np.int32)
    color = (0, 255, 0) if number.accepted else (0, 0, 255)
    cv2.polylines(image, [original], True, color, 2)
    label = tr("calibration.overlay.ocr", value=number.raw_text)
    if number.corrected_value is not None:
        label += f" -> {number.corrected_value}"
    anchor = tuple(original[0])
    _outlined_text(image, label, (anchor[0], max(14, anchor[1] - 4)), color=color, scale=0.42)


def _draw_scale_bar(image: np.ndarray, rendered_length_px: float, label: str) -> None:
    height, width = image.shape[:2]
    length = max(1, int(round(rendered_length_px)))
    margin = max(20, int(round(min(width, height) * 0.035)))
    x2 = width - margin
    x1 = max(margin, x2 - length)
    y = height - margin
    cv2.line(image, (x1, y), (x2, y), (255, 255, 255), 8, cv2.LINE_AA)
    cv2.line(image, (x1, y), (x2, y), (0, 0, 0), 3, cv2.LINE_AA)
    cv2.line(image, (x1, y - 8), (x1, y + 8), (255, 255, 255), 3)
    cv2.line(image, (x2, y - 8), (x2, y + 8), (255, 255, 255), 3)
    text_size = cv2.getTextSize(label, cv2.FONT_HERSHEY_SIMPLEX, 0.65, 2)[0]
    _outlined_text(image, label, (x1 + max(0, (length - text_size[0]) // 2), y - 14), scale=0.65)


def _outlined_text(
    image: np.ndarray,
    text: str,
    point: tuple[int, int],
    *,
    color: tuple[int, int, int] = (255, 255, 255),
    scale: float = 0.58,
) -> None:
    cv2.putText(image, text, point, cv2.FONT_HERSHEY_SIMPLEX, scale, (0, 0, 0), 4, cv2.LINE_AA)
    cv2.putText(image, text, point, cv2.FONT_HERSHEY_SIMPLEX, scale, color, 1, cv2.LINE_AA)
