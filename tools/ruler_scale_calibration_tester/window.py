from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

import numpy as np
from PySide6.QtCore import QObject, Qt, QThread, Signal, Slot
from PySide6.QtGui import QCloseEvent, QImage, QPixmap
from PySide6.QtWidgets import (
    QComboBox,
    QFileDialog,
    QFormLayout,
    QGridLayout,
    QGroupBox,
    QLabel,
    QMainWindow,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QScrollArea,
    QSplitter,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from core.calibration import CalibrationResult, CalibrationService
from core.calibration.image_utils import normalize_to_uint8
from core.i18n import tr
from gui.camera_controller import CameraController

from .image_loader import load_image
from .repeatability import repeatability_summary


LOG = logging.getLogger(__name__)


class ImageLabel(QLabel):
    def __init__(self) -> None:
        super().__init__(tr("calibration.tester.no_image"))
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.setMinimumSize(360, 260)
        self.setStyleSheet("background:#202124; color:#ddd; border:1px solid #555;")
        self._source: QPixmap | None = None

    def set_array(self, image: np.ndarray) -> None:
        array = np.ascontiguousarray(image)
        if array.ndim == 2:
            display = normalize_to_uint8(array)
            qimage = QImage(
                display.data,
                display.shape[1],
                display.shape[0],
                display.strides[0],
                QImage.Format.Format_Grayscale8,
            ).copy()
        elif array.ndim == 3 and array.shape[2] == 3:
            display = np.ascontiguousarray(array.astype(np.uint8, copy=False))
            qimage = QImage(
                display.data,
                display.shape[1],
                display.shape[0],
                display.strides[0],
                QImage.Format.Format_BGR888,
            ).copy()
        else:
            raise ValueError(f"Unsupported display image shape: {array.shape}")
        self.set_qimage(qimage)

    def set_qimage(self, image: QImage) -> None:
        self._source = QPixmap.fromImage(image.copy())
        self._refresh()

    def resizeEvent(self, event: Any) -> None:
        super().resizeEvent(event)
        self._refresh()

    def _refresh(self) -> None:
        if self._source is None:
            return
        self.setPixmap(
            self._source.scaled(
                self.size(),
                Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation,
            )
        )


class AnalysisWorker(QObject):
    finished = Signal(object)

    def __init__(
        self,
        service: CalibrationService,
        image: np.ndarray,
        source: str,
    ) -> None:
        super().__init__()
        self.service = service
        self.image = np.asarray(image).copy()
        self.source = source

    @Slot()
    def run(self) -> None:
        self.finished.emit(self.service.analyze(self.image, input_source=self.source))


class RulerScaleTesterWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle(tr("calibration.tester.title"))
        self.resize(1500, 900)
        self.setMinimumSize(960, 650)
        self.service = CalibrationService()
        self.controller = CameraController(self)
        self.devices: list[Any] = []
        self._latest_scientific: np.ndarray | None = None
        self._current_input: np.ndarray | None = None
        self._current_source = ""
        self._current_result: CalibrationResult | None = None
        self._analysis_thread: QThread | None = None
        self._analysis_worker: AnalysisWorker | None = None
        self._repeatability_values: list[float] = []
        self._image_labels: dict[str, ImageLabel] = {}
        self._result_labels: dict[str, QLabel] = {}
        self._build_ui()
        self._connect_camera_signals()
        self.refresh_cameras()
        availability = self.service.digit_recognizer.availability()
        self.ocr_status.setText(tr(
            "calibration.tester.ocr_status",
            state=tr("common.available") if availability.available else tr("common.unavailable"),
            diagnostic=availability.diagnostic,
        ))

    def _build_ui(self) -> None:
        central = QWidget()
        root = QVBoxLayout(central)
        controls = QGridLayout()
        self.input_mode = QLabel(tr("calibration.tester.input_none"))
        self.camera_combo = QComboBox()
        self.refresh_button = QPushButton(tr("calibration.tester.refresh_cameras"))
        self.connect_button = QPushButton(tr("calibration.tester.connect_camera"))
        self.disconnect_button = QPushButton(tr("common.disconnect"))
        self.capture_button = QPushButton(tr("calibration.tester.capture_analyze"))
        self.load_button = QPushButton(tr("calibration.tester.load_image"))
        self.analyze_button = QPushButton(tr("calibration.tester.analyze_again"))
        self.save_debug_button = QPushButton(tr("calibration.tester.save_debug"))
        controls.addWidget(self.input_mode, 0, 0, 1, 2)
        controls.addWidget(self.camera_combo, 0, 2, 1, 2)
        for column, button in enumerate(
            (
                self.refresh_button,
                self.connect_button,
                self.disconnect_button,
                self.capture_button,
                self.load_button,
                self.analyze_button,
                self.save_debug_button,
            )
        ):
            controls.addWidget(button, 1, column)
        root.addLayout(controls)

        splitter = QSplitter(Qt.Orientation.Horizontal)
        self.tabs = QTabWidget()
        for key, title in (
            ("original", "calibration.tester.tab_original"),
            ("rectified", "calibration.tester.tab_rectified"),
            ("ticks_overlay", "calibration.tester.tab_ticks"),
            ("ocr_overlay", "calibration.tester.tab_ocr"),
            ("final_overlay", "calibration.tester.tab_final"),
        ):
            label = ImageLabel()
            scroll = QScrollArea()
            scroll.setWidgetResizable(True)
            scroll.setWidget(label)
            self.tabs.addTab(scroll, tr(title))
            self._image_labels[key] = label
        splitter.addWidget(self.tabs)

        diagnostics = QWidget()
        diagnostics_layout = QVBoxLayout(diagnostics)
        result_group = QGroupBox(tr("calibration.tester.result_group"))
        form = QFormLayout(result_group)
        for key, title in (
            ("ruler", "calibration.tester.ruler"),
            ("angle", "calibration.tester.angle"),
            ("ocr", "calibration.tester.ocr_numbers"),
            ("ticks", "calibration.tester.ticks"),
            ("scale", "calibration.tester.pixels_per_mm"),
            ("resolution", "calibration.tester.um_per_pixel"),
            ("span", "calibration.tester.span"),
            ("fit", "calibration.tester.fit_error"),
            ("quality", "calibration.tester.quality"),
            ("scale_bar", "calibration.tester.scale_bar"),
            ("failure", "calibration.tester.failure_warnings"),
        ):
            label = QLabel("—")
            label.setWordWrap(True)
            form.addRow(tr(title), label)
            self._result_labels[key] = label
        diagnostics_layout.addWidget(result_group)
        self.ocr_status = QLabel()
        self.ocr_status.setWordWrap(True)
        diagnostics_layout.addWidget(self.ocr_status)

        repeat_group = QGroupBox(tr("calibration.tester.repeatability"))
        repeat_layout = QVBoxLayout(repeat_group)
        self.repeatability_text = QPlainTextEdit()
        self.repeatability_text.setReadOnly(True)
        self.repeatability_text.setMaximumBlockCount(500)
        self.clear_repeatability_button = QPushButton(tr("calibration.tester.clear_repeatability"))
        repeat_layout.addWidget(self.repeatability_text)
        repeat_layout.addWidget(self.clear_repeatability_button)
        diagnostics_layout.addWidget(repeat_group, 1)
        splitter.addWidget(diagnostics)
        splitter.setStretchFactor(0, 3)
        splitter.setStretchFactor(1, 1)
        root.addWidget(splitter, 1)
        self.status = QLabel(tr("common.ready"))
        root.addWidget(self.status)
        self.setCentralWidget(central)

        self.refresh_button.clicked.connect(self.refresh_cameras)
        self.connect_button.clicked.connect(self.connect_camera)
        self.disconnect_button.clicked.connect(self.disconnect_camera)
        self.capture_button.clicked.connect(self.capture_and_analyze)
        self.load_button.clicked.connect(self.load_image_file)
        self.analyze_button.clicked.connect(self.analyze_again)
        self.save_debug_button.clicked.connect(self.save_debug_package)
        self.clear_repeatability_button.clicked.connect(self.clear_repeatability)
        self.disconnect_button.setEnabled(False)
        self.capture_button.setEnabled(False)
        self.analyze_button.setEnabled(False)
        self.save_debug_button.setEnabled(False)
        self._update_repeatability()

    def _connect_camera_signals(self) -> None:
        self.controller.frame_ready.connect(self._on_preview_frame)
        self.controller.scientific_frame_ready.connect(self._on_scientific_frame)
        self.controller.camera_opened.connect(self._on_camera_opened)
        self.controller.camera_closed.connect(self._on_camera_closed)
        self.controller.status_changed.connect(self.status.setText)
        self.controller.error_occurred.connect(self._on_camera_error)

    @Slot()
    def refresh_cameras(self) -> None:
        if self.controller.is_open:
            self.controller.close_camera()
        self.devices = self.controller.enumerate_devices()
        self.camera_combo.clear()
        for device in self.devices:
            self.camera_combo.addItem(str(device.displayname))
        self.connect_button.setEnabled(bool(self.devices))
        self.status.setText(
            tr("calibration.tester.cameras_found", count=len(self.devices))
            if self.devices
            else tr("calibration.tester.camera_unavailable_file_available")
        )

    @Slot()
    def connect_camera(self) -> None:
        index = self.camera_combo.currentIndex()
        if index < 0 or index >= len(self.devices):
            self.status.setText(tr("calibration.tester.select_camera"))
            return
        self.status.setText(tr("camera.connecting"))
        self.controller.open_device(self.devices[index])

    @Slot()
    def disconnect_camera(self) -> None:
        self.controller.close_camera()

    @Slot(object)
    def _on_camera_opened(self, info: object) -> None:
        details = info if isinstance(info, dict) else {}
        name = str(details.get("model", details.get("name", "camera")))
        self.input_mode.setText(tr("calibration.tester.input_live_camera", name=name))
        self.connect_button.setEnabled(False)
        self.disconnect_button.setEnabled(True)
        self.capture_button.setEnabled(False)
        LOG.info("Ruler tester camera connected model=%s", name)

    @Slot()
    def _on_camera_closed(self) -> None:
        self._latest_scientific = None
        self.connect_button.setEnabled(bool(self.devices))
        self.disconnect_button.setEnabled(False)
        self.capture_button.setEnabled(False)
        LOG.info("Ruler tester camera disconnected")

    @Slot(QImage)
    def _on_preview_frame(self, image: QImage) -> None:
        if self._current_source.startswith("camera:") or self._current_input is None:
            self._image_labels["original"].set_qimage(image)

    @Slot(object, QImage, int)
    def _on_scientific_frame(self, scientific: object, preview: QImage, sequence: int) -> None:
        array = np.asarray(scientific)
        if array.ndim != 2:
            self.status.setText(tr("calibration.tester.frame_shape_rejected", shape=array.shape))
            return
        self._latest_scientific = array.copy()
        self.capture_button.setEnabled(self._analysis_thread is None)
        self.input_mode.setText(tr("calibration.tester.input_live_frame", sequence=sequence))
        self._image_labels["original"].set_qimage(preview)

    @Slot(str)
    def _on_camera_error(self, message: str) -> None:
        LOG.error("Ruler tester camera error: %s", message)
        self.status.setText(tr("calibration.tester.camera_error", message=message))

    @Slot()
    def capture_and_analyze(self) -> None:
        if self._latest_scientific is None:
            self.status.setText(tr("calibration.tester.no_camera_frame"))
            return
        self._current_input = self._latest_scientific.copy()
        self._current_source = f"camera:{self.controller.device_name}"
        self._start_analysis()

    @Slot()
    def load_image_file(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self,
            "Load ruler image",
            "",
            "Images (*.png *.jpg *.jpeg *.tif *.tiff)",
        )
        if not path:
            return
        try:
            self._current_input = load_image(path)
        except Exception as exc:
            QMessageBox.critical(self, tr("calibration.tester.load_failed"), str(exc))
            return
        self._current_source = str(Path(path).resolve())
        self.input_mode.setText(tr("calibration.tester.input_file", name=Path(path).name))
        self._image_labels["original"].set_array(self._current_input)
        self.analyze_button.setEnabled(True)
        self._start_analysis()

    @Slot()
    def analyze_again(self) -> None:
        if self._current_input is not None:
            self._start_analysis()

    def _start_analysis(self) -> None:
        if self._current_input is None or self._analysis_thread is not None:
            return
        self.status.setText(tr("calibration.tester.analyzing"))
        self._set_analysis_controls(False)
        thread = QThread(self)
        worker = AnalysisWorker(self.service, self._current_input, self._current_source)
        worker.moveToThread(thread)
        thread.started.connect(worker.run)
        worker.finished.connect(self._on_analysis_finished)
        worker.finished.connect(thread.quit)
        worker.finished.connect(worker.deleteLater)
        thread.finished.connect(self._analysis_thread_finished)
        thread.finished.connect(thread.deleteLater)
        self._analysis_thread = thread
        self._analysis_worker = worker
        thread.start()

    @Slot(object)
    def _on_analysis_finished(self, payload: object) -> None:
        if not isinstance(payload, CalibrationResult):
            self.status.setText(tr("calibration.tester.invalid_result"))
            return
        self._current_result = payload
        for name, image in payload.debug_images.items():
            label = self._image_labels.get(name)
            if label is not None:
                label.set_array(image)
        self._show_result(payload)
        if payload.success and payload.pixels_per_mm is not None:
            self._repeatability_values.append(payload.pixels_per_mm)
            self._update_repeatability()
        self.save_debug_button.setEnabled(bool(payload.debug_images))
        self.status.setText(
            tr("calibration.tester.calibration_pass")
            if payload.success
            else tr("calibration.tester.calibration_fail", reasons=", ".join(payload.failure_reasons))
        )

    @Slot()
    def _analysis_thread_finished(self) -> None:
        self._analysis_thread = None
        self._analysis_worker = None
        self._set_analysis_controls(True)

    def _set_analysis_controls(self, enabled: bool) -> None:
        self.load_button.setEnabled(enabled)
        self.analyze_button.setEnabled(enabled and self._current_input is not None)
        self.capture_button.setEnabled(enabled and self.controller.is_open and self._latest_scientific is not None)

    def _show_result(self, result: CalibrationResult) -> None:
        numbers = []
        for item in result.detected_numbers:
            text = item.raw_text
            if item.corrected_value is not None:
                text += f"→{item.corrected_value} (rejected raw)"
            elif not item.accepted:
                text += " (rejected)"
            numbers.append(text)
        self._result_labels["ruler"].setText(
            tr("calibration.tester.detected")
            if result.ruler_detection and result.ruler_detection.success
            else tr("calibration.tester.not_detected")
        )
        self._result_labels["angle"].setText(
            tr("calibration.tester.angle_value", value=f"{result.ruler_angle_deg:.2f}")
            if result.ruler_angle_deg is not None else "—"
        )
        self._result_labels["ocr"].setText(
            ", ".join(numbers)
            or tr("calibration.tester.ocr_none", diagnostic=result.ocr_diagnostic)
        )
        self._result_labels["ticks"].setText(tr(
            "calibration.tester.tick_counts",
            major=len(result.detected_major_ticks),
            minor=len(result.detected_minor_ticks),
            rejected=len(result.rejected_ticks),
        ))
        self._result_labels["scale"].setText(f"{result.pixels_per_mm:.5f} px/mm" if result.pixels_per_mm is not None else "—")
        self._result_labels["resolution"].setText(f"{result.um_per_pixel:.5f} µm/px" if result.um_per_pixel is not None else "—")
        self._result_labels["span"].setText(f"{result.calibration_span_mm:.1f} mm")
        self._result_labels["fit"].setText(
            tr(
                "calibration.tester.fit_value",
                rmse=f"{result.fit_rmse_px:.3f}",
                percent=f"{result.fit_error_percent:.3f}",
            )
            if result.fit_rmse_px is not None and result.fit_error_percent is not None else "—"
        )
        self._result_labels["quality"].setText(tr(
            "calibration.tester.quality_value",
            state=result.quality_label,
            score=f"{result.quality_score:.1f}",
        ))
        self._result_labels["scale_bar"].setText(
            tr(
                "calibration.tester.scale_bar_value",
                label=result.scale_bar.label,
                pixels=f"{result.scale_bar.rendered_length_px:.1f}",
            )
            if result.scale_bar is not None else "—"
        )
        messages = result.failure_reasons + result.warnings
        self._result_labels["failure"].setText(
            ", ".join(messages) or tr("common.none")
        )

    @Slot()
    def save_debug_package(self) -> None:
        if self._current_result is None:
            return
        default_root = str((Path.cwd() / "local" / "generated" / "debug").resolve())
        root = QFileDialog.getExistingDirectory(self, "Select debug package parent directory", default_root)
        if not root:
            return
        try:
            output = self.service.save_debug_package(self._current_result, root)
        except Exception as exc:
            QMessageBox.critical(self, tr("calibration.tester.save_debug_failed"), str(exc))
            return
        QMessageBox.information(self, tr("calibration.tester.debug_saved"), str(output))

    @Slot()
    def clear_repeatability(self) -> None:
        self._repeatability_values.clear()
        self._update_repeatability()

    def _update_repeatability(self) -> None:
        summary = repeatability_summary(self._repeatability_values)
        lines = [
            tr("calibration.tester.repeat_run", index=f"{index:02d}", value=f"{value:.6f}")
            for index, value in enumerate(self._repeatability_values, 1)
        ]
        lines.extend((
            "",
            tr("calibration.tester.repeat_n", value=summary["n"]),
            tr("calibration.tester.repeat_mean", value=_format_stat(summary["mean_pixels_per_mm"])),
            tr("calibration.tester.repeat_sd", value=_format_stat(summary["sd_pixels_per_mm"])),
            tr("calibration.tester.repeat_cv", value=_format_stat(summary["cv_percent"])),
            tr("calibration.tester.repeat_min", value=_format_stat(summary["min_pixels_per_mm"])),
            tr("calibration.tester.repeat_max", value=_format_stat(summary["max_pixels_per_mm"])),
            tr("calibration.tester.repeat_deviation", value=_format_stat(summary["max_deviation_percent"])),
            tr("calibration.tester.repeat_no_threshold"),
        ))
        self.repeatability_text.setPlainText("\n".join(lines))

    def closeEvent(self, event: QCloseEvent) -> None:
        self.controller.close_camera()
        if self._analysis_thread is not None and self._analysis_thread.isRunning():
            if not self._analysis_thread.wait(5000):
                self.status.setText(tr("calibration.tester.waiting_close"))
                event.ignore()
                return
        event.accept()


def _format_stat(value: object) -> str:
    return "—" if value is None else f"{float(value):.6f}"
