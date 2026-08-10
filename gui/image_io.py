from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from PIL import Image
from PySide6.QtGui import QImage


def save_image_and_metadata(image: QImage, path: str, metadata: dict[str, Any]) -> tuple[Path, Path]:
    """Save a QImage with Pillow and write a UTF-8 JSON sidecar."""
    output = Path(path)
    if not output.suffix:
        output = output.with_suffix(".png")
    output.parent.mkdir(parents=True, exist_ok=True)

    rgb = image.convertToFormat(QImage.Format.Format_RGB888)
    raw = bytes(rgb.bits())
    pil_image = Image.frombuffer(
        "RGB",
        (rgb.width(), rgb.height()),
        raw,
        "raw",
        "RGB",
        rgb.bytesPerLine(),
        1,
    ).copy()

    suffix = output.suffix.lower()
    save_kwargs: dict[str, Any] = {}
    if suffix in {".jpg", ".jpeg"}:
        save_kwargs = {"quality": 95, "subsampling": 0}
    elif suffix in {".tif", ".tiff"}:
        save_kwargs = {"compression": "tiff_lzw"}
    pil_image.save(output, **save_kwargs)

    sidecar = output.with_suffix(output.suffix + ".json")
    sidecar.write_text(json.dumps(metadata, ensure_ascii=False, indent=2), encoding="utf-8")
    return output, sidecar
