"""Configurable presentation-only sidebar support."""

from .registry import SidebarItem, SidebarItemState, SidebarRegistry
from .settings_dialog import SidebarSettingsDialog

__all__ = [
    "SidebarItem",
    "SidebarItemState",
    "SidebarRegistry",
    "SidebarSettingsDialog",
]
