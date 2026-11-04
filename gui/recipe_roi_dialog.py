from __future__ import annotations

"""Live, channel-labelled ROI preparation before any Recipe output is enabled."""

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QDialog, QHBoxLayout, QLabel, QPushButton, QVBoxLayout

from core.i18n import tr

from .recipe_roi import validate_channel_rois
from .widgets import ImageView


class RecipeROIDialog(QDialog):
    def __init__(self, controller, channels, parent=None):
        super().__init__(parent)
        self.controller = controller
        self.channels = tuple(channels)
        self.rois = {}
        self.error = ""
        self._size = None
        self._index = 0
        self._connections = []
        self.setWindowTitle(tr("recipe.roi_title"))
        self.resize(1000, 740)
        self.prompt = QLabel()
        self.prompt.setWordWrap(True)
        self.coordinates = QLabel(tr("camera.roi_not_set"))
        self.view = ImageView()
        self.redraw = QPushButton(tr("camera.select_dn_roi"))
        self.redraw.clicked.connect(self._redraw)
        fit = QPushButton(tr("recipe.roi_fit"))
        fit.clicked.connect(self.view.fit_to_window)
        self.next_button = QPushButton()
        self.next_button.clicked.connect(self._next)
        cancel = QPushButton(tr("common.cancel"))
        cancel.clicked.connect(self.reject)
        buttons = QHBoxLayout()
        for widget in (self.redraw, fit, self.next_button, cancel):
            buttons.addWidget(widget)
        layout = QVBoxLayout(self)
        layout.addWidget(self.prompt)
        layout.addWidget(self.coordinates)
        layout.addWidget(self.view, 1)
        layout.addLayout(buttons)
        self.view.roi_selected.connect(self._selected)
        self._connect(controller.frame_ready, self._frame)
        self._connect(controller.camera_closed, self.reject)
        self._connect(controller.error_occurred, self._fail)
        self._frame_timer = QTimer(self)
        self._frame_timer.setSingleShot(True)
        self._frame_timer.setInterval(30000)
        self._frame_timer.timeout.connect(lambda: self._fail(tr("recipe.roi_frame_timeout")))
        self._frame_timer.start()
        self._prompt()
        # Wait for a NEW white-light frame; an old preview may belong to the
        # resolution used before Recipe preparation.

    def _connect(self, signal, slot):
        signal.connect(slot)
        self._connections.append((signal, slot))

    def done(self, result):
        self._frame_timer.stop()
        for signal, slot in self._connections:
            signal.disconnect(slot)
        self._connections.clear()
        super().done(result)

    def _fail(self, message):
        self.error = str(message)
        self.reject()

    def _frame(self, image):
        self._frame_timer.start()
        size = (image.width(), image.height())
        if self._size is not None and size != self._size:
            self._fail(tr("recipe.roi_resolution_changed"))
            return
        first = self._size is None
        self._size = size
        self.view.set_image(image)
        if first:
            self.redraw.setEnabled(True)
            self.view.begin_roi_selection()

    def _prompt(self):
        channel = self.channels[self._index]
        self.prompt.setText(tr("recipe.roi_prompt", channel=channel, roi=channel[2:],
                               current=self._index + 1, total=len(self.channels)))
        self.coordinates.setText(tr("camera.roi_not_set"))
        self.next_button.setText(tr("recipe.roi_finish") if self._index == len(self.channels) - 1
                                 else tr("recipe.roi_next"))
        self.next_button.setEnabled(False)
        self.redraw.setEnabled(self.view.has_image)

    def _selected(self, x, y, width, height):
        self.coordinates.setText(tr("camera.roi_coordinates", x=x, y=y, width=width, height=height))
        self.next_button.setEnabled(True)

    def _redraw(self):
        self.next_button.setEnabled(False)
        self.view.begin_roi_selection()

    def _next(self):
        if self.view.roi is None or self.view.roi_selection_mode:
            return
        self.rois[self.channels[self._index]] = self.view.roi
        if self._index == len(self.channels) - 1:
            self.rois = validate_channel_rois(self.rois, self.channels, *self._size)
            self.accept()
            return
        self._index += 1
        self.view.clear_roi()
        self._prompt()
        self.view.begin_roi_selection()
