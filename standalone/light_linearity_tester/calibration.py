from __future__ import annotations

import csv
from dataclasses import dataclass, field, asdict
from datetime import datetime
import hashlib
import json
import math
from pathlib import Path

from tools.camera_linearity_qualification.capture_manifest import atomic_write_json


@dataclass
class LightCalibration:
    channel: int = 1
    source_name: str = ""
    unit: str = "relative"
    meter: str = ""
    geometry: str = ""
    measured_at: str = ""
    reference_level: int = 255
    background: float = 0.0
    readings: dict[int, float] = field(default_factory=dict)
    notes: str = ""
    schema_version: str = "1.0"

    def validate(self) -> None:
        if type(self.channel) is not int or self.channel not in range(1, 5):
            raise ValueError("通道必須是 CH1～CH4")
        if type(self.reference_level) is not int or self.reference_level not in range(1, 256):
            raise ValueError("參考 PWM 等級必須是 1～255")
        if not self.unit.strip() or not math.isfinite(self.background) or self.background < 0:
            raise ValueError("請填寫單位與有限、非負的背景讀值")
        for level, value in self.readings.items():
            if type(level) is not int or level not in range(256):
                raise ValueError("PWM 等級必須是 0～255 的整數")
            if not math.isfinite(value) or value < 0:
                raise ValueError(f"PWM {level} 的光強讀值必須是有限、非負數值")

    def relative(self, level: int) -> float | None:
        self.validate()
        measured = self.readings.get(level)
        reference = self.readings.get(self.reference_level)
        if measured is None or reference is None or reference <= self.background:
            return None
        return (measured - self.background) / (reference - self.background)

    def require_levels(self, levels: tuple[int, ...]) -> None:
        self.validate()
        missing = [level for level in levels if self.relative(level) is None or self.relative(level) <= 0]
        if missing:
            raise ValueError(f"缺少有效實測光強：PWM {missing}；請確認參考等級與背景扣除")

    def to_dict(self) -> dict:
        self.validate()
        payload = asdict(self)
        payload["readings"] = {str(k): float(v) for k, v in sorted(self.readings.items())}
        payload["background"] = float(self.background)
        return payload

    @classmethod
    def from_dict(cls, payload: dict) -> LightCalibration:
        if payload.get("schema_version") != "1.0":
            raise ValueError("不支援的光強表格式版本")
        values = dict(payload)
        values["readings"] = {int(k): float(v) for k, v in values.get("readings", {}).items()}
        result = cls(**values)
        result.validate()
        return result

    def snapshot(self) -> dict:
        payload = self.to_dict()
        encoded = json.dumps(payload, sort_keys=True, ensure_ascii=False, allow_nan=False).encode("utf-8")
        return {"calibration": payload, "sha256": hashlib.sha256(encoded).hexdigest(),
                "captured_at": datetime.now().astimezone().isoformat(timespec="seconds")}

    def save(self, path: str | Path) -> None:
        atomic_write_json(Path(path), self.to_dict())

    @classmethod
    def load(cls, path: str | Path) -> LightCalibration:
        return cls.from_dict(json.loads(Path(path).read_text(encoding="utf-8-sig")))

    def export_csv(self, path: str | Path) -> None:
        self.validate()
        with Path(path).open("w", encoding="utf-8-sig", newline="") as stream:
            writer = csv.writer(stream)
            writer.writerow(("channel", "pwm_level", "measured_intensity", "unit", "relative_intensity"))
            for level in range(256):
                writer.writerow((self.channel, level, self.readings.get(level, ""), self.unit,
                                 self.relative(level) if self.relative(level) is not None else ""))

    def import_csv(self, path: str | Path) -> None:
        """Replace readings atomically; CSV does not overwrite instrument metadata."""
        readings: dict[int, float] = {}
        seen: set[int] = set()
        with Path(path).open(encoding="utf-8-sig", newline="") as stream:
            reader = csv.DictReader(stream)
            if not {"channel", "pwm_level", "measured_intensity", "unit"} <= set(reader.fieldnames or ()):
                raise ValueError("CSV 需要 channel,pwm_level,measured_intensity,unit 欄位")
            for row in reader:
                level = int(row["pwm_level"])
                if int(row["channel"]) != self.channel or row["unit"].strip() != self.unit.strip():
                    raise ValueError("CSV 通道或單位與目前表格不同；請先選取相同通道與單位")
                if level not in range(256) or level in seen:
                    raise ValueError("CSV 有重複或超出範圍的 PWM 等級")
                seen.add(level)
                if row["measured_intensity"].strip():
                    readings[level] = float(row["measured_intensity"])
        candidate = LightCalibration.from_dict({**self.to_dict(), "readings": readings})
        self.readings = candidate.readings
