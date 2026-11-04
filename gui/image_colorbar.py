from __future__ import annotations

"""A linear grayscale legend outside the unchanged mono visualization."""

from dataclasses import dataclass

import numpy as np
from PIL import Image, ImageDraw, ImageFont


def _font(size: int):
    for name in ("arial.ttf", "DejaVuSans.ttf"):
        try:
            return ImageFont.truetype(name, size)
        except OSError:
            pass
    return ImageFont.load_default(size=size)


@dataclass(frozen=True)
class GrayscaleColorbar:
    maximum: int
    quantity: str = "Effective DN"

    def layout(self, size: tuple[int, int]) -> dict:
        width, height = size
        font_size = max(10, min(28, round(min(width, height) / 36)))
        font = _font(font_size)
        probe = ImageDraw.Draw(Image.new("RGB", (1, 1)))
        box = probe.textbbox((0, 0), "Ag", font=font)
        line_height = box[3] - box[1]
        padding = max(8, font_size)
        gap = max(5, font_size // 2)
        bar_width = max(12, round(font_size * 1.2))
        values = sorted({round(self.maximum * i / 4) for i in range(5)}, reverse=True)
        label_width = max(probe.textbbox((0, 0), text, font=font)[2]
                          for text in (self.quantity, "Linear"))
        number_width = probe.textbbox((0, 0), str(self.maximum), font=font)[2]
        panel_width = 2 * padding + max(label_width, bar_width + gap + 5 + number_width)
        top = padding + 2 * (line_height + gap)
        # Leave enough room for labels even when the ROI is only a few pixels high.
        panel_height = max(height, top + (len(values) - 1) * (line_height + gap) + 1
                           + line_height // 2 + padding)
        bottom = panel_height - padding - line_height // 2
        ticks = [(value, top + round((self.maximum - value) / self.maximum * (bottom - top - 1)))
                 for value in values]
        return {"font": font, "padding": padding, "line_height": line_height, "gap": gap,
                "width": panel_width, "height": panel_height,
                "bar_box": (width + padding, top, width + padding + bar_width, bottom),
                "ticks": ticks}

    def append_to(self, source: Image.Image) -> Image.Image:
        layout = self.layout(source.size)
        result = Image.new("RGB", (source.width + layout["width"], layout["height"]), "white")
        result.paste(source, (0, 0))
        draw = ImageDraw.Draw(result)
        font, padding = layout["font"], layout["padding"]
        for index, text in enumerate((self.quantity, "Linear")):
            box = draw.textbbox((0, 0), text, font=font)
            y = padding + index * (layout["line_height"] + layout["gap"])
            draw.text((source.width + padding - box[0], y - box[1]), text, font=font, fill="black")
        left, top, right, bottom = layout["bar_box"]
        dn = np.rint(np.linspace(self.maximum, 0, bottom - top)).astype(np.uint32)
        # Match effective_dn_to_uint8's integer rounding, including both endpoints.
        gray = ((dn * 255 + self.maximum // 2) // self.maximum).astype(np.uint8)
        ramp = np.repeat(gray[:, None], right - left, axis=1)
        result.paste(Image.fromarray(ramp), (left, top))
        draw.rectangle((left - 1, top - 1, right, bottom), outline=(128, 128, 128))
        for value, y in layout["ticks"]:
            draw.line((right, y, right + 4, y), fill="black")
            text = str(value)
            box = draw.textbbox((0, 0), text, font=font)
            draw.text((right + 5 + layout["gap"] - box[0], y - (box[1] + box[3]) / 2),
                      text, font=font, fill="black")
        return result

    def describe(self, size: tuple[int, int]) -> dict:
        layout = self.layout(size)
        left, top, right, bottom = layout["bar_box"]
        return {"Position": "right", "ColorMap": "grayscale", "Scale": "linear",
                "Quantity": self.quantity, "Minimum": 0, "Maximum": self.maximum,
                "DisplayGrayRange": [0, 255], "Ticks": [v for v, _ in layout["ticks"]],
                "SourceImageRect": {"X": 0, "Y": 0, "Width": size[0], "Height": size[1]},
                "BarRect": {"X": left, "Y": top, "Width": right - left, "Height": bottom - top}}
