from __future__ import annotations

"""Registry and QSettings persistence for main-window sidebar widgets."""

from dataclasses import dataclass
import json
import logging
from typing import Iterable

from PySide6.QtCore import QSettings
from PySide6.QtWidgets import QVBoxLayout, QWidget


LOGGER = logging.getLogger(__name__)
SETTINGS_KEY = "interface/sidebar/items"


@dataclass(frozen=True)
class SidebarItem:
    """Static metadata and the existing view container for one sidebar item."""

    id: str
    display_name: str
    widget: QWidget
    default_order: int
    default_visible: bool = True


@dataclass(frozen=True)
class SidebarItemState:
    """The only user-customizable state persisted for a sidebar item."""

    id: str
    visible: bool


class SidebarRegistry:
    """Apply sidebar order/visibility without touching controllers or hardware."""

    def __init__(
        self,
        layout: QVBoxLayout,
        settings: QSettings,
        settings_key: str = SETTINGS_KEY,
    ) -> None:
        self._layout = layout
        self._settings = settings
        self._settings_key = settings_key
        self._items: dict[str, SidebarItem] = {}
        self._active_states: list[SidebarItemState] = []

    def register(self, item: SidebarItem) -> None:
        if not item.id or item.id in self._items:
            raise ValueError(f"Sidebar item ID must be non-empty and unique: {item.id!r}")
        self._items[item.id] = item
        if self._active_states:
            # Late registration is supported for future optional modules.  The
            # new widget is inserted by default_order with default visibility.
            self.apply(self._active_states)

    @property
    def items(self) -> tuple[SidebarItem, ...]:
        return tuple(sorted(self._items.values(), key=lambda item: item.default_order))

    @property
    def active_states(self) -> list[SidebarItemState]:
        if not self._active_states:
            return self.default_states()
        return self._merge_new_items(self._active_states)

    def default_states(self) -> list[SidebarItemState]:
        return [
            SidebarItemState(item.id, item.default_visible)
            for item in self.items
        ]

    def load_states(self) -> list[SidebarItemState]:
        raw = self._settings.value(self._settings_key, "")
        if not raw:
            states = self.default_states()
            LOGGER.info("SIDEBAR settings loaded defaults")
            return states

        try:
            payload = json.loads(str(raw))
            records = payload.get("items", []) if isinstance(payload, dict) else payload
            if not isinstance(records, list):
                raise ValueError("items must be a list")
        except (TypeError, ValueError, json.JSONDecodeError) as exc:
            LOGGER.warning("SIDEBAR settings invalid; using defaults: %s", exc)
            return self.default_states()

        states: list[SidebarItemState] = []
        seen: set[str] = set()
        for record in records:
            if not isinstance(record, dict):
                LOGGER.warning("SIDEBAR settings ignored malformed item: %r", record)
                continue
            item_id = record.get("id")
            if not isinstance(item_id, str) or item_id not in self._items:
                LOGGER.warning("SIDEBAR settings ignored unknown id=%r", item_id)
                continue
            if item_id in seen:
                LOGGER.warning("SIDEBAR settings ignored duplicate id=%s", item_id)
                continue
            visible = record.get("visible")
            if not isinstance(visible, bool):
                visible = self._items[item_id].default_visible
            states.append(SidebarItemState(item_id, visible))
            seen.add(item_id)

        states = self._merge_new_items(states)
        LOGGER.info("SIDEBAR settings loaded")
        return states

    def restore(self) -> list[SidebarItemState]:
        states = self.load_states()
        self.apply(states)
        return states

    def save_and_apply(self, states: Iterable[SidebarItemState]) -> list[SidebarItemState]:
        normalized = self._normalize(states)
        payload = {
            "items": [
                {"id": state.id, "visible": state.visible}
                for state in normalized
            ]
        }
        self._settings.setValue(
            self._settings_key,
            json.dumps(payload, ensure_ascii=False, separators=(",", ":")),
        )
        self._settings.sync()
        self.apply(normalized)
        return normalized

    def apply(self, states: Iterable[SidebarItemState]) -> list[SidebarItemState]:
        normalized = self._normalize(states)
        for item in self._items.values():
            self._layout.removeWidget(item.widget)
        for index, state in enumerate(normalized):
            item = self._items[state.id]
            self._layout.insertWidget(index, item.widget)
            item.widget.setVisible(state.visible)
            if not state.visible:
                LOGGER.info("SIDEBAR item hidden id=%s", state.id)
        self._active_states = normalized
        LOGGER.info("SIDEBAR layout applied")
        return list(normalized)

    def _normalize(self, states: Iterable[SidebarItemState]) -> list[SidebarItemState]:
        normalized: list[SidebarItemState] = []
        seen: set[str] = set()
        for state in states:
            if state.id not in self._items or state.id in seen:
                continue
            normalized.append(SidebarItemState(state.id, bool(state.visible)))
            seen.add(state.id)
        return self._merge_new_items(normalized)

    def _merge_new_items(
        self, states: list[SidebarItemState]
    ) -> list[SidebarItemState]:
        merged = list(states)
        present = {state.id for state in merged}
        for item in self.items:
            if item.id in present:
                continue
            insertion = len(merged)
            for index, state in enumerate(merged):
                if self._items[state.id].default_order > item.default_order:
                    insertion = index
                    break
            merged.insert(insertion, SidebarItemState(item.id, item.default_visible))
            present.add(item.id)
        return merged
