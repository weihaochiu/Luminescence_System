from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
import math


class Retention(str, Enum):
    FULL = "full"
    ROI = "roi_and_first_full"
    SUMMARY = "summary_only"


@dataclass(frozen=True)
class LightPlan:
    channel: int
    levels: tuple[int, ...]
    gains: tuple[int, ...]
    exposures_ms: tuple[float, ...]
    repeats: int = 5
    dark_repeats: int = 5
    settling_frames: int = 2
    settle_s: float = 1.0
    jitter_s: float = 0.02
    retention: Retention = Retention.FULL
    require_measured: bool = True
    pwm_frequency_hz: float | None = None
    adaptive_stop: bool = True
    warmup_s: float = 0.0

    def validate(self) -> None:
        if type(self.channel) is not int or self.channel not in range(1, 5):
            raise ValueError("通道必須是 1～4")
        for values, low, high, label in ((self.levels, 1, 255, "PWM"), (self.gains, 1, 65535, "Gain")):
            if not values or any(type(x) is not int or not low <= x <= high for x in values) or len(set(values)) != len(values):
                raise ValueError(f"{label} 列表不可為空、重複或超出範圍；PWM 0 用於 Dark")
        if not self.exposures_ms or any(not math.isfinite(x) or not .03 <= x <= 15000 for x in self.exposures_ms) or len(set(self.exposures_ms)) != len(self.exposures_ms):
            raise ValueError("曝光必須是 0.03～15000 ms 的有限、不重複數值")
        if type(self.repeats) is not int or not 1 <= self.repeats <= 100 or type(self.dark_repeats) is not int or not 1 <= self.dark_repeats <= 100:
            raise ValueError("Light／Dark 張數必須是 1～100")
        if type(self.settling_frames) is not int or not 0 <= self.settling_frames <= 20:
            raise ValueError("丟棄幀數必須是 0～20")
        if any(not math.isfinite(x) or x < 0 for x in (self.settle_s, self.jitter_s, self.warmup_s)):
            raise ValueError("等待時間必須是有限、非負數值")
        if self.pwm_frequency_hz is not None and (not math.isfinite(self.pwm_frequency_hz) or self.pwm_frequency_hz <= 0):
            raise ValueError("PWM 頻率必須大於 0，未知時留空")
        Retention(self.retention)

    @property
    def condition_count(self) -> int:
        return len(self.levels) * len(self.gains) * len(self.exposures_ms)

    def estimate(self, width: int, height: int, roi_width: int, roi_height: int) -> dict:
        self.validate()
        if min(width, height, roi_width, roi_height) <= 0 or roi_width > width or roi_height > height:
            raise ValueError("影像／ROI 尺寸無效")
        full_bytes, roi_bytes = width * height * 2, roi_width * roi_height * 2
        light = self.condition_count * self.repeats
        # Matching dark is recaptured immediately before each Light condition.
        dark = self.condition_count * self.dark_repeats
        first = self.condition_count * 2
        if self.retention == Retention.FULL:
            pixel_bytes = (light + dark) * full_bytes
        elif self.retention == Retention.ROI:
            pixel_bytes = first * full_bytes + (light + dark - first) * roi_bytes
        else:
            pixel_bytes = 0
        exposure_s = len(self.levels) * len(self.gains) * sum(self.exposures_ms) / 1000 * (self.repeats + self.dark_repeats)
        minimum_s = exposure_s * (self.settling_frames + 1) + self.condition_count * self.settle_s * 2 + self.warmup_s
        return {"light_frames": light, "dark_frames": dark, "pixel_bytes": pixel_bytes,
                "estimated_bytes": pixel_bytes + (light + dark) * 8192 + self.condition_count * 4096 + 1024 * 1024,
                "minimum_seconds": minimum_s, "retention": self.retention.value,
                "note": "未壓縮像素＋metadata 估算；不含相機讀出／串口／存檔延遲，提前停止可能減少張數"}
