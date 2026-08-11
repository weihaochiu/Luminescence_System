from __future__ import annotations

"""Persistent, hardware-location-independent relay configuration."""

from dataclasses import asdict, dataclass, field
import json
from pathlib import Path
import re
from typing import Any


@dataclass
class RelayChannel:
    number: int
    enabled: bool = True
    display_name: str = "未使用"
    description: str = ""


@dataclass
class RelayGroup:
    group_id: str
    display_name: str
    members: list[int] = field(default_factory=list)
    enabled: bool = True


@dataclass
class RelaySettings:
    vid: int = 0x16C0
    pid: int = 0x05DF
    product: str = "USBRelay8"
    channels: list[RelayChannel] = field(default_factory=list)
    groups: list[RelayGroup] = field(default_factory=list)

    @classmethod
    def defaults(cls) -> "RelaySettings":
        channels = [RelayChannel(number=index) for index in range(1, 9)]
        channels[0] = RelayChannel(1, True, "白光－L", "White Light AC Line")
        channels[1] = RelayChannel(2, True, "白光－N", "White Light AC Neutral")
        return cls(channels=channels, groups=[RelayGroup("white_light", "白光", [1, 2])])

    def group(self, group_id: str) -> RelayGroup | None:
        return next((item for item in self.groups if item.group_id == group_id), None)

    def validate(self) -> list[str]:
        errors: list[str] = []
        numbers = [item.number for item in self.channels]
        if sorted(numbers) != list(range(1, 9)):
            errors.append("Channel 必須完整且唯一地包含 CH1～CH8")
        group_ids: set[str] = set()
        assigned_channels: dict[int, str] = {}
        for group in self.groups:
            if not re.fullmatch(r"[a-z][a-z0-9_]*", group.group_id):
                errors.append(f"Group ID「{group.group_id}」只能使用小寫英數與底線，且須以英文字母開頭")
            if group.group_id in group_ids:
                errors.append(f"Group ID 重複：{group.group_id}")
            group_ids.add(group.group_id)
            if not group.display_name.strip():
                errors.append(f"Group「{group.group_id}」缺少顯示名稱")
            if not group.members:
                errors.append(f"Group「{group.group_id}」至少需要一個 Channel")
            if len(group.members) != len(set(group.members)):
                errors.append(f"Group「{group.group_id}」含有重複 Channel")
            for channel in group.members:
                if channel not in range(1, 9):
                    errors.append(f"Group「{group.group_id}」含有無效 Channel：CH{channel}")
                    continue
                if group.enabled and channel in assigned_channels:
                    errors.append(
                        f"CH{channel} 同時位於啟用的 Group「{assigned_channels[channel]}」與「{group.group_id}」"
                    )
                if group.enabled:
                    assigned_channels[channel] = group.group_id
        return errors

    def to_dict(self) -> dict[str, Any]:
        return {
            "device": {"vid": self.vid, "pid": self.pid, "product": self.product},
            "channels": [asdict(item) for item in self.channels],
            "groups": [asdict(item) for item in self.groups],
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any] | None) -> "RelaySettings":
        defaults = cls.defaults()
        source = data or {}
        device = source.get("device", {})
        raw_channels = source.get("channels", [])
        channel_by_number = {
            int(item.get("number", 0)): RelayChannel(
                number=int(item.get("number", 0)), enabled=bool(item.get("enabled", True)),
                display_name=str(item.get("display_name", "未使用")), description=str(item.get("description", "")),
            )
            for item in raw_channels if isinstance(item, dict) and 1 <= int(item.get("number", 0)) <= 8
        }
        channels = [channel_by_number.get(item.number, item) for item in defaults.channels]
        groups = [
            RelayGroup(str(item.get("group_id", "")), str(item.get("display_name", "")),
                       [int(channel) for channel in item.get("members", [])], bool(item.get("enabled", True)))
            for item in source.get("groups", []) if isinstance(item, dict)
        ]
        return cls(int(device.get("vid", defaults.vid)), int(device.get("pid", defaults.pid)),
                   str(device.get("product", defaults.product)), channels, groups or defaults.groups)


class RelaySettingsStore:
    schema_version = 1

    def __init__(self, path: Path) -> None:
        self.path = path
        self.settings = RelaySettings.defaults()
        self.load()

    def load(self) -> None:
        if not self.path.exists():
            self.save()
            return
        payload = json.loads(self.path.read_text(encoding="utf-8"))
        self.settings = RelaySettings.from_dict(payload.get("relay_settings", payload))
        errors = self.settings.validate()
        if errors:
            raise RuntimeError("Relay 設定檔無效：" + "；".join(errors))

    def save(self) -> None:
        errors = self.settings.validate()
        if errors:
            raise ValueError("Relay 設定無效：" + "；".join(errors))
        self.path.parent.mkdir(parents=True, exist_ok=True)
        payload = {"schema_version": self.schema_version, "relay_settings": self.settings.to_dict()}
        temporary = self.path.with_suffix(self.path.suffix + ".tmp")
        temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        temporary.replace(self.path)
