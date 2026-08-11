from __future__ import annotations

"""Logical-pixel responsive layout selection for Qt widgets."""

from dataclasses import dataclass
from enum import Enum
from typing import Any

from PySide6.QtCore import QEvent, QObject, QTimer, Signal


class LayoutMode(str, Enum):
    WIDE = "WIDE"
    STANDARD = "STANDARD"
    COMPACT = "COMPACT"


@dataclass(frozen=True)
class ResponsiveThresholds:
    """Centralized breakpoints expressed in Qt logical pixels."""

    standard_min_width: int = 1080
    wide_min_width: int = 1500

    @classmethod
    def from_font_metrics(
        cls,
        metrics: Any,
        standard_content_width: int = 0,
        wide_content_width: int = 0,
    ) -> "ResponsiveThresholds":
        em_width = max(8, int(metrics.horizontalAdvance("M")))
        standard = max(1080, 108 * em_width, int(standard_content_width))
        wide = max(1500, 150 * em_width, int(wide_content_width))
        return cls(
            standard_min_width=min(standard, 1400),
            wide_min_width=max(min(wide, 1800), min(standard, 1400) + 160),
        )


def effective_logical_width(
    window_width: int,
    available_width: int | None = None,
    content_width: int | None = None,
) -> int:
    """Return the usable width from Qt logical-pixel geometry values."""

    candidates = [int(window_width)]
    if available_width is not None and available_width > 0:
        candidates.append(int(available_width))
    if content_width is not None and content_width > 0:
        candidates.append(int(content_width))
    return max(0, min(candidates))


def layout_mode_for_width(
    width: int,
    thresholds: ResponsiveThresholds | None = None,
) -> LayoutMode:
    selected = thresholds or ResponsiveThresholds()
    if width >= selected.wide_min_width:
        return LayoutMode.WIDE
    if width >= selected.standard_min_width:
        return LayoutMode.STANDARD
    return LayoutMode.COMPACT


class ResponsiveLayoutManager(QObject):
    """Observe live Qt geometry and reconfigure one shared control bar."""

    mode_changed = Signal(object)

    def __init__(self, window: Any, control_bar: Any, parent: QObject | None = None) -> None:
        super().__init__(parent or window)
        self.window = window
        self.control_bar = control_bar
        self._mode: LayoutMode | None = None
        self._update_pending = False
        self.last_device_pixel_ratio = 1.0
        window.installEventFilter(self)
        control_bar.installEventFilter(self)
        QTimer.singleShot(0, self.update_now)

    @property
    def mode(self) -> LayoutMode | None:
        return self._mode

    def eventFilter(self, watched: QObject, event: QEvent) -> bool:  # noqa: N802
        if watched in (self.window, self.control_bar) and event.type() == QEvent.Type.Resize:
            self.schedule_update()
        return super().eventFilter(watched, event)

    def schedule_update(self) -> None:
        if self._update_pending:
            return
        self._update_pending = True
        QTimer.singleShot(0, self.update_now)

    def update_now(self) -> None:
        self._update_pending = False
        screen = self.window.screen()
        available_width = screen.availableGeometry().width() if screen is not None else None
        content_width = self.control_bar.width() if self.control_bar.width() > 0 else None
        self.last_device_pixel_ratio = float(self.window.devicePixelRatioF())
        standard_width, wide_width = self.control_bar.recommended_breakpoints()
        thresholds = ResponsiveThresholds.from_font_metrics(
            self.control_bar.fontMetrics(),
            standard_content_width=standard_width,
            wide_content_width=wide_width,
        )
        usable_width = effective_logical_width(
            self.window.width(),
            available_width=available_width,
            content_width=content_width,
        )
        mode = layout_mode_for_width(usable_width, thresholds)
        if mode is self._mode:
            return
        self._mode = mode
        self.control_bar.set_layout_mode(mode)
        self.mode_changed.emit(mode)
