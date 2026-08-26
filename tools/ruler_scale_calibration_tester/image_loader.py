from __future__ import annotations

from pathlib import Path

import cv2
import numpy as np
from PIL import Image
import tifffile


SUPPORTED_SUFFIXES = {".png", ".jpg", ".jpeg", ".tif", ".tiff"}


def load_image(path: str | Path) -> np.ndarray:
    source = Path(path)
    suffix = source.suffix.casefold()
    if suffix not in SUPPORTED_SUFFIXES:
        raise ValueError(f"Unsupported image format: {source.suffix}")
    if suffix in {".tif", ".tiff"}:
        try:
            array = np.asarray(tifffile.imread(source))
        except ValueError as exc:
            if "imagecodecs" not in str(exc).casefold():
                raise
            with Image.open(source) as image:
                array = np.asarray(image.copy())
    else:
        with Image.open(source) as image:
            array = np.asarray(image.copy())
    if array.ndim == 3 and array.shape[-1] == 3:
        array = cv2.cvtColor(array, cv2.COLOR_RGB2BGR)
    elif array.ndim == 3 and array.shape[-1] == 4:
        array = cv2.cvtColor(array, cv2.COLOR_RGBA2BGRA)
    elif array.ndim not in {2, 3}:
        raise ValueError(f"Expected one image, got shape {array.shape}")
    return np.ascontiguousarray(array)


def iter_images(root: str | Path) -> list[Path]:
    source = Path(root)
    if source.is_file():
        return [source] if source.suffix.casefold() in SUPPORTED_SUFFIXES else []
    if not source.is_dir():
        raise FileNotFoundError(source)
    return sorted(
        path for path in source.rglob("*")
        if path.is_file() and path.suffix.casefold() in SUPPORTED_SUFFIXES
    )
