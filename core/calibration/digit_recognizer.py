from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
import re
import shutil
from typing import Any

import cv2
import numpy as np

from .config import CalibrationConfig
from .models import DetectedNumber


@dataclass(frozen=True)
class OCRAvailability:
    available: bool
    diagnostic: str


class DigitRecognizer(ABC):
    @abstractmethod
    def availability(self) -> OCRAvailability:
        raise NotImplementedError

    @abstractmethod
    def recognize(self, rectified_image: np.ndarray) -> list[DetectedNumber]:
        raise NotImplementedError


class UnavailableDigitRecognizer(DigitRecognizer):
    def __init__(self, diagnostic: str = "OCR backend was not configured") -> None:
        self.diagnostic = diagnostic

    def availability(self) -> OCRAvailability:
        return OCRAvailability(False, self.diagnostic)

    def recognize(self, rectified_image: np.ndarray) -> list[DetectedNumber]:
        return []


class TesseractDigitRecognizer(DigitRecognizer):
    """Restricted numeric OCR using a locally installed Tesseract executable."""

    def __init__(self, config: CalibrationConfig | None = None) -> None:
        self.config = config or CalibrationConfig()
        self._module: Any | None = None
        self._availability: OCRAvailability | None = None

    def availability(self) -> OCRAvailability:
        if self._availability is not None:
            return self._availability
        try:
            import pytesseract  # type: ignore
        except Exception as exc:
            self._availability = OCRAvailability(False, f"pytesseract unavailable: {exc}")
            return self._availability
        executable = shutil.which("tesseract")
        configured = str(getattr(pytesseract.pytesseract, "tesseract_cmd", "tesseract"))
        if executable is None and configured.casefold() == "tesseract":
            self._availability = OCRAvailability(
                False,
                "Tesseract executable was not found on PATH; install it explicitly and restart",
            )
            return self._availability
        try:
            version = pytesseract.get_tesseract_version()
        except Exception as exc:
            self._availability = OCRAvailability(False, f"Tesseract executable unavailable: {exc}")
            return self._availability
        self._module = pytesseract
        self._availability = OCRAvailability(True, f"Tesseract {version}")
        return self._availability

    def recognize(self, rectified_image: np.ndarray) -> list[DetectedNumber]:
        if not self.availability().available or self._module is None:
            return []
        variants: list[DetectedNumber] = []
        for orientation in (0, 180):
            image = rectified_image if orientation == 0 else cv2.rotate(rectified_image, cv2.ROTATE_180)
            variants.extend(self._recognize_orientation(image, orientation))
        return self._choose_orientation(variants)

    def _recognize_orientation(
        self,
        image: np.ndarray,
        orientation: int,
    ) -> list[DetectedNumber]:
        height, width = image.shape
        enlarged = cv2.resize(image, None, fx=2.0, fy=2.0, interpolation=cv2.INTER_CUBIC)
        processed = cv2.adaptiveThreshold(
            enlarged,
            255,
            cv2.ADAPTIVE_THRESH_GAUSSIAN_C,
            cv2.THRESH_BINARY,
            31,
            9,
        )
        data = self._module.image_to_data(
            processed,
            config="--psm 6 -c tessedit_char_whitelist=0123456789",
            output_type=self._module.Output.DICT,
        )
        results: list[DetectedNumber] = []
        for index, text in enumerate(data.get("text", [])):
            cleaned = re.sub(r"\D", "", str(text))
            if not cleaned:
                continue
            confidence = float(data["conf"][index])
            if confidence < self.config.ocr_min_confidence:
                continue
            x = int(round(float(data["left"][index]) / 2.0))
            y = int(round(float(data["top"][index]) / 2.0))
            box_width = int(round(float(data["width"][index]) / 2.0))
            box_height = int(round(float(data["height"][index]) / 2.0))
            if orientation == 180:
                x = width - (x + box_width)
                y = height - (y + box_height)
            results.append(
                DetectedNumber(
                    value=int(cleaned),
                    raw_text=str(text),
                    bbox=(x, y, box_width, box_height),
                    center=(x + box_width * 0.5, y + box_height * 0.5),
                    confidence=confidence,
                    orientation_deg=orientation,
                )
            )
        return results

    @staticmethod
    def _choose_orientation(items: list[DetectedNumber]) -> list[DetectedNumber]:
        groups = {orientation: [item for item in items if item.orientation_deg == orientation] for orientation in (0, 180)}
        def score(group: list[DetectedNumber]) -> tuple[int, float, float]:
            ordered = sorted(group, key=lambda item: item.center[0])
            continuity = sum(
                1 for left, right in zip(ordered, ordered[1:])
                if abs((right.value or 0) - (left.value or 0)) == 1
            )
            return continuity, sum(item.confidence for item in group), float(len(group))
        selected = max(groups, key=lambda orientation: score(groups[orientation]))
        return sorted(groups[selected], key=lambda item: item.center[0])


class StaticDigitRecognizer(DigitRecognizer):
    """Deterministic injected backend for algorithm tests; never used as runtime fallback."""

    def __init__(self, detections: list[DetectedNumber], available: bool = True) -> None:
        self.detections = detections
        self.available = available

    def availability(self) -> OCRAvailability:
        return OCRAvailability(self.available, "injected test backend")

    def recognize(self, rectified_image: np.ndarray) -> list[DetectedNumber]:
        return [DetectedNumber(**vars(item)) for item in self.detections] if self.available else []
