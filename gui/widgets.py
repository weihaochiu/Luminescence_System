from __future__ import annotations

import math

from PySide6.QtCore import QPointF, QRectF, Qt, Signal
from PySide6.QtGui import QBrush, QColor, QImage, QPainter, QPen, QPixmap
from PySide6.QtWidgets import (
    QFrame,
    QGraphicsPixmapItem,
    QGraphicsRectItem,
    QGraphicsScene,
    QGraphicsTextItem,
    QGraphicsView,
    QSizePolicy,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from core.i18n import i18n, tr


class ImageView(QGraphicsView):
    """Zoomable, pannable image canvas similar to the vendor viewer."""

    zoom_changed = Signal(float)
    roi_selected = Signal(int, int, int, int)
    roi_cleared = Signal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._scene = QGraphicsScene(self)
        self._pixmap_item = QGraphicsPixmapItem()
        self._scene.addItem(self._pixmap_item)
        self._roi_item = QGraphicsRectItem()
        roi_pen = QPen(QColor("#ffcc00"), 2.0)
        roi_pen.setCosmetic(True)
        self._roi_item.setPen(roi_pen)
        self._roi_item.setBrush(Qt.BrushStyle.NoBrush)
        self._roi_item.setZValue(10.0)
        self._roi_item.setAcceptedMouseButtons(Qt.MouseButton.NoButton)
        self._roi_item.setVisible(False)
        self._scene.addItem(self._roi_item)
        self._message_item = QGraphicsTextItem(tr("camera.not_connected"))
        self._message_item.setDefaultTextColor(QColor("#edf0f2"))
        self._scene.addItem(self._message_item)
        self._scene.setSceneRect(0, 0, 800, 600)
        self._center_message()
        self.setScene(self._scene)
        self.setBackgroundBrush(QBrush(QColor("#74787c")))
        self.setFrameShape(QFrame.Shape.NoFrame)
        self.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, True)
        self.setDragMode(QGraphicsView.DragMode.ScrollHandDrag)
        self.setTransformationAnchor(QGraphicsView.ViewportAnchor.AnchorUnderMouse)
        self.setResizeAnchor(QGraphicsView.ViewportAnchor.AnchorViewCenter)
        self.setMinimumSize(320, 240)
        self._has_image = False
        self._fit_mode = True
        self._roi: tuple[int, int, int, int] | None = None
        self._roi_selection_mode = False
        self._roi_selection_start: QPointF | None = None
        self._selection_previous_roi: tuple[int, int, int, int] | None = None
        i18n.language_changed.connect(self.retranslate)

    def retranslate(self, _language: str = "") -> None:
        self._message_item.setPlainText(tr("camera.not_connected"))
        self._center_message()

    def set_image(self, image: QImage) -> None:
        previous_size = (
            (self._pixmap_item.pixmap().width(), self._pixmap_item.pixmap().height())
            if self._has_image
            else None
        )
        new_size = (image.width(), image.height())
        if previous_size is not None and previous_size != new_size:
            self.clear_roi()
        self._pixmap_item.setPixmap(QPixmap.fromImage(image))
        self._message_item.setVisible(False)
        self._scene.setSceneRect(self._pixmap_item.boundingRect())
        if not self._has_image or self._fit_mode:
            self.fit_to_window()
        self._has_image = True

    def clear_image(self) -> None:
        self.clear_roi()
        self._pixmap_item.setPixmap(QPixmap())
        self._has_image = False
        self._fit_mode = True
        self.resetTransform()
        self._scene.setSceneRect(0, 0, max(self.viewport().width(), 640), max(self.viewport().height(), 480))
        self._message_item.setVisible(True)
        self._center_message()

    @property
    def has_image(self) -> bool:
        return self._has_image and not self._pixmap_item.pixmap().isNull()

    @property
    def roi(self) -> tuple[int, int, int, int] | None:
        return self._roi

    @property
    def roi_selection_mode(self) -> bool:
        return self._roi_selection_mode

    def begin_roi_selection(self) -> bool:
        if not self.has_image:
            return False
        self._roi_selection_mode = True
        self._roi_selection_start = None
        self._selection_previous_roi = self._roi
        self.setDragMode(QGraphicsView.DragMode.NoDrag)
        self.viewport().setCursor(Qt.CursorShape.CrossCursor)
        return True

    def set_roi(self, x: int, y: int, width: int, height: int) -> None:
        if not self.has_image:
            raise ValueError("Cannot set an ROI without an image")
        image_width = self._pixmap_item.pixmap().width()
        image_height = self._pixmap_item.pixmap().height()
        roi = (int(x), int(y), int(width), int(height))
        if (
            roi[0] < 0
            or roi[1] < 0
            or roi[2] <= 0
            or roi[3] <= 0
            or roi[0] + roi[2] > image_width
            or roi[1] + roi[3] > image_height
        ):
            raise ValueError("ROI must be a non-empty rectangle inside the image")
        self._roi = roi
        self._apply_roi_overlay(roi)

    def clear_roi(self) -> None:
        had_roi = self._roi is not None
        self._roi = None
        self._roi_item.setVisible(False)
        self._finish_roi_selection()
        if had_roi:
            self.roi_cleared.emit()

    def mousePressEvent(self, event) -> None:  # noqa: N802 - Qt API name
        if (
            self._roi_selection_mode
            and event.button() is Qt.MouseButton.LeftButton
            and self.has_image
        ):
            self._roi_selection_start = self._clamped_image_point(
                self.mapToScene(event.position().toPoint())
            )
            self._roi_item.setRect(QRectF(self._roi_selection_start, self._roi_selection_start))
            self._roi_item.setVisible(True)
            event.accept()
            return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event) -> None:  # noqa: N802 - Qt API name
        if self._roi_selection_mode and self._roi_selection_start is not None:
            current = self._clamped_image_point(
                self.mapToScene(event.position().toPoint())
            )
            self._roi_item.setRect(
                QRectF(self._roi_selection_start, current).normalized()
            )
            event.accept()
            return
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event) -> None:  # noqa: N802 - Qt API name
        if (
            self._roi_selection_mode
            and self._roi_selection_start is not None
            and event.button() is Qt.MouseButton.LeftButton
        ):
            current = self._clamped_image_point(
                self.mapToScene(event.position().toPoint())
            )
            roi = self._integer_roi(self._roi_selection_start, current)
            if roi is None:
                self._roi = self._selection_previous_roi
                if self._roi is None:
                    self._roi_item.setVisible(False)
                else:
                    self._apply_roi_overlay(self._roi)
            else:
                self._roi = roi
                self._apply_roi_overlay(roi)
            self._finish_roi_selection()
            if roi is not None:
                self.roi_selected.emit(*roi)
            event.accept()
            return
        super().mouseReleaseEvent(event)

    def _finish_roi_selection(self) -> None:
        self._roi_selection_mode = False
        self._roi_selection_start = None
        self._selection_previous_roi = None
        self.setDragMode(QGraphicsView.DragMode.ScrollHandDrag)
        self.viewport().unsetCursor()

    def _clamped_image_point(self, point: QPointF) -> QPointF:
        bounds = self._pixmap_item.boundingRect()
        return QPointF(
            min(max(point.x(), bounds.left()), bounds.right()),
            min(max(point.y(), bounds.top()), bounds.bottom()),
        )

    def _integer_roi(
        self, start: QPointF, end: QPointF
    ) -> tuple[int, int, int, int] | None:
        image_width = self._pixmap_item.pixmap().width()
        image_height = self._pixmap_item.pixmap().height()
        x0 = min(max(math.floor(min(start.x(), end.x())), 0), image_width)
        y0 = min(max(math.floor(min(start.y(), end.y())), 0), image_height)
        x1 = min(max(math.ceil(max(start.x(), end.x())), 0), image_width)
        y1 = min(max(math.ceil(max(start.y(), end.y())), 0), image_height)
        if x1 <= x0 or y1 <= y0:
            return None
        return x0, y0, x1 - x0, y1 - y0

    def _apply_roi_overlay(self, roi: tuple[int, int, int, int]) -> None:
        self._roi_item.setRect(QRectF(*roi))
        self._roi_item.setVisible(True)

    def fit_to_window(self) -> None:
        if self._pixmap_item.pixmap().isNull():
            return
        self.resetTransform()
        self.fitInView(self._pixmap_item, Qt.AspectRatioMode.KeepAspectRatio)
        self._fit_mode = True
        self.zoom_changed.emit(self.transform().m11() * 100.0)

    def actual_size(self) -> None:
        if self._pixmap_item.pixmap().isNull():
            return
        self.resetTransform()
        self.centerOn(self._pixmap_item)
        self._fit_mode = False
        self.zoom_changed.emit(100.0)

    def resizeEvent(self, event) -> None:  # noqa: N802 - Qt API name
        super().resizeEvent(event)
        if not self._has_image:
            self._scene.setSceneRect(0, 0, max(self.viewport().width(), 640), max(self.viewport().height(), 480))
            self._center_message()
        elif self._fit_mode:
            self.fit_to_window()

    def wheelEvent(self, event) -> None:  # noqa: N802 - Qt API name
        if self._pixmap_item.pixmap().isNull():
            return
        factor = 1.20 if event.angleDelta().y() > 0 else (1.0 / 1.20)
        proposed = self.transform().m11() * factor
        if 0.02 <= proposed <= 20.0:
            self.scale(factor, factor)
            self._fit_mode = False
            self.zoom_changed.emit(self.transform().m11() * 100.0)

    def _center_message(self) -> None:
        bounds = self._message_item.boundingRect()
        scene = self._scene.sceneRect()
        self._message_item.setPos(
            scene.center().x() - bounds.width() / 2,
            scene.center().y() - bounds.height() / 2,
        )


class CollapsibleSection(QWidget):
    """Compact accordion section used by the camera control sidebar."""

    def __init__(self, title: str, content: QWidget, expanded: bool = True) -> None:
        super().__init__()
        self._button = QToolButton()
        self._button.setText(title)
        self._button.setCheckable(True)
        self._button.setChecked(expanded)
        self._button.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        self._button.setArrowType(Qt.ArrowType.DownArrow if expanded else Qt.ArrowType.RightArrow)
        self._button.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self._button.clicked.connect(self._toggle)
        self._content = content
        self._content.setVisible(expanded)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(1)
        layout.addWidget(self._button)
        layout.addWidget(self._content)

    def _toggle(self, expanded: bool) -> None:
        self._button.setArrowType(Qt.ArrowType.DownArrow if expanded else Qt.ArrowType.RightArrow)
        self._content.setVisible(expanded)

    def set_title(self, title: str) -> None:
        self._button.setText(title)
