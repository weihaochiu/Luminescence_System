from __future__ import annotations

"""Persistent, hardware-location-independent relay configuration."""

from dataclasses import asdict, dataclass, field
import json
from pathlib import Path
import re
from typing import Any

from core.i18n import tr


@dataclass
class RelayChannel:
    number: int
    enabled: bool = True
    display_name: str = ""
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
    smu_output_channels: dict[str, int] = field(default_factory=dict)

    @classmethod
    def defaults(cls) -> "RelaySettings":
        channels = [RelayChannel(number=index) for index in range(1, 9)]
        channels[0] = RelayChannel(1, True, "白光－L", "White Light AC Line")
        channels[1] = RelayChannel(2, True, "白光－N", "White Light AC Neutral")
        for index, relay in enumerate(range(5, 9), start=1):
            channels[relay - 1] = RelayChannel(
                relay,
                True,
                f"SMU 輸出 Ch{index}",
                f"Break-before-make routing for SMU Ch{index}",
            )
        return cls(
            channels=channels,
            groups=[RelayGroup("white_light", "白光", [1, 2])],
            smu_output_channels={f"Ch{index}": index + 4 for index in range(1, 5)},
        )

    def group(self, group_id: str) -> RelayGroup | None:
        return next((item for item in self.groups if item.group_id == group_id), None)

    def validate(self) -> list[str]:
        errors: list[str] = []
        numbers = [item.number for item in self.channels]
        if sorted(numbers) != list(range(1, 9)):
            errors.append(tr("relay.validation.channels_complete"))
        group_ids: set[str] = set()
        assigned_channels: dict[int, str] = {}
        for group in self.groups:
            if not re.fullmatch(r"[a-z][a-z0-9_]*", group.group_id):
                errors.append(tr("relay.validation.group_id_format", group_id=group.group_id))
            if group.group_id in group_ids:
                errors.append(tr("relay.validation.group_id_duplicate", group_id=group.group_id))
            group_ids.add(group.group_id)
            if not group.display_name.strip():
                errors.append(tr("relay.validation.group_name_missing", group_id=group.group_id))
            if not group.members:
                errors.append(tr("relay.validation.group_member_missing", group_id=group.group_id))
            if len(group.members) != len(set(group.members)):
                errors.append(tr("relay.validation.group_member_duplicate", group_id=group.group_id))
            for channel in group.members:
                if channel not in range(1, 9):
                    errors.append(tr("relay.validation.group_channel_invalid", group_id=group.group_id, channel=channel))
                    continue
                if group.enabled and channel in assigned_channels:
                    errors.append(tr("relay.validation.channel_group_conflict", channel=channel, first=assigned_channels[channel], second=group.group_id))
                if group.enabled:
                    assigned_channels[channel] = group.group_id
        white_light = self.group("white_light")
        if white_light is None or set(white_light.members) != {1, 2}:
            errors.append(tr("relay.validation.white_light_members"))
        expected_smu_ids = {f"Ch{index}" for index in range(1, 5)}
        actual_smu_ids = set(self.smu_output_channels)
        if actual_smu_ids != expected_smu_ids:
            errors.append(tr("relay.validation.smu_channels_complete"))
        relay_numbers = list(self.smu_output_channels.values())
        if any(not isinstance(number, int) or number not in range(1, 9) for number in relay_numbers):
            errors.append(tr("relay.validation.smu_relay_range"))
        if len(relay_numbers) != len(set(relay_numbers)):
            errors.append(tr("relay.validation.smu_relay_unique"))
        if white_light is not None and set(relay_numbers) & set(white_light.members):
            errors.append(tr("relay.validation.smu_white_light_overlap"))
        enabled_by_number = {channel.number: channel.enabled for channel in self.channels}
        for channel_id, relay_number in self.smu_output_channels.items():
            if relay_number in range(1, 9) and not enabled_by_number.get(relay_number, False):
                errors.append(tr("relay.validation.smu_relay_disabled", channel=channel_id, relay=relay_number))
        routing_relays = set(relay_numbers)
        for group in self.groups:
            overlap = routing_relays & set(group.members)
            if group.enabled and overlap:
                channels = "、".join(f"CH{channel}" for channel in sorted(overlap))
                errors.append(tr("relay.validation.routing_group_overlap", group_id=group.group_id, channels=channels))
        return errors

    def to_dict(self) -> dict[str, Any]:
        return {
            "device": {"vid": self.vid, "pid": self.pid, "product": self.product},
            "channels": [asdict(item) for item in self.channels],
            "groups": [asdict(item) for item in self.groups],
            "smu_output_channels": dict(self.smu_output_channels),
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
                display_name=("" if str(item.get("display_name", "")) == "未使用" else str(item.get("display_name", ""))), description=str(item.get("description", "")),
            )
            for item in raw_channels if isinstance(item, dict) and 1 <= int(item.get("number", 0)) <= 8
        }
        channels = [channel_by_number.get(item.number, item) for item in defaults.channels]
        groups = [
            RelayGroup(str(item.get("group_id", "")), str(item.get("display_name", "")),
                       [int(channel) for channel in item.get("members", [])], bool(item.get("enabled", True)))
            for item in source.get("groups", []) if isinstance(item, dict)
        ]
        raw_smu_channels = source.get("smu_output_channels")
        smu_output_channels = (
            {
                str(channel_id): int(relay_number)
                for channel_id, relay_number in raw_smu_channels.items()
            }
            if isinstance(raw_smu_channels, dict)
            else dict(defaults.smu_output_channels)
        )
        if not isinstance(raw_smu_channels, dict):
            # V1 files had no routing schema. Make the new default Relay 5-8
            # routes usable while preserving any explicit channel labels.
            for relay_number in smu_output_channels.values():
                channels[relay_number - 1].enabled = True
                if channels[relay_number - 1].display_name == "未使用":
                    default_channel = defaults.channels[relay_number - 1]
                    channels[relay_number - 1].display_name = default_channel.display_name
                    channels[relay_number - 1].description = default_channel.description
        return cls(int(device.get("vid", defaults.vid)), int(device.get("pid", defaults.pid)),
                   str(device.get("product", defaults.product)), channels, groups or defaults.groups,
                   smu_output_channels)


class RelaySettingsStore:
    schema_version = 2

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
