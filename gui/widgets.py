from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QBrush, QColor, QImage, QPainter, QPixmap
from PySide6.QtWidgets import (
    QFrame,
    QGraphicsPixmapItem,
    QGraphicsScene,
    QGraphicsTextItem,
    QGraphicsView,
    QSizePolicy,
    QToolButton,
    QVBoxLayout,
    QWidget,
)


class ImageView(QGraphicsView):
    """Zoomable, pannable image canvas similar to the vendor viewer."""

    zoom_changed = Signal(float)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._scene = QGraphicsScene(self)
        self._pixmap_item = QGraphicsPixmapItem()
        self._scene.addItem(self._pixmap_item)
        self._message_item = QGraphicsTextItem("尚未連線相機")
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

    def set_image(self, image: QImage) -> None:
        self._pixmap_item.setPixmap(QPixmap.fromImage(image))
        self._message_item.setVisible(False)
        self._scene.setSceneRect(self._pixmap_item.boundingRect())
        if not self._has_image or self._fit_mode:
            self.fit_to_window()
        self._has_image = True

    def clear_image(self) -> None:
        self._pixmap_item.setPixmap(QPixmap())
        self._has_image = False
        self._fit_mode = True
        self.resetTransform()
        self._scene.setSceneRect(0, 0, max(self.viewport().width(), 640), max(self.viewport().height(), 480))
        self._message_item.setVisible(True)
        self._center_message()

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
