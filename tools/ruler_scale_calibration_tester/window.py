from __future__ import annotations

import logging
from pathlib import Path
from threading import Event
from typing import Any

import numpy as np
from PySide6.QtCore import QObject, Qt, QThread, QUrl, Signal, Slot
from PySide6.QtGui import QCloseEvent, QDesktopServices, QImage, QPixmap
from PySide6.QtWidgets import (
    QComboBox,
    QCheckBox,
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

from core.calibration import CalibrationResult, CalibrationService, VerificationMode
from core.calibration.image_utils import normalize_to_uint8
from core.i18n import tr
from gui.camera_controller import CameraController
from gui.camera_capture_bridge import CameraCaptureBridge

from .capture_history import (
    AnalysisOutcome,
    CaptureHistoryStore,
    PROJECT_ROOT,
    analyze_camera_capture,
)
from .image_loader import load_image
from .repeatability import DuplicateSourceError, RepeatabilitySession
from .ruler_auto_exposure import (
    CameraCaptureBridgeRulerAdapter,
    RulerAEAttemptRecord,
    RulerAutoExposureOutcome,
    RulerAutoExposureRunner,
)
from .source import AnalysisSource, FrameCaptureState


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
        source: AnalysisSource,
        capture_history: CaptureHistoryStore,
    ) -> None:
        super().__init__()
        self.service = service
        self.image = np.asarray(image).copy()
        self.source = source
        self.capture_history = capture_history

    @Slot()
    def run(self) -> None:
        if self.source.source_type == "camera":
            try:
                outcome = analyze_camera_capture(
                    self.service,
                    self.capture_history,
                    self.image,
                    self.source,
                )
            except Exception as exc:
                LOG.exception("Camera capture could not be persisted")
                result = CalibrationResult(
                    success=False,
                    source_type="camera",
                    source_identity=self.source.source_identity,
                    source_display_name=self.source.display_name,
                    captured_frame_sequence=self.source.frame_sequence,
                    input_dtype=str(self.image.dtype),
                    input_resolution=(self.image.shape[1], self.image.shape[0]),
                    input_min=self.image.min().item(),
                    input_max=self.image.max().item(),
                    failure_reasons=["analysis_exception"],
                    warnings=[f"Capture persistence failed: {type(exc).__name__}: {exc}"],
                )
                outcome = AnalysisOutcome(result=result, persistence_error=str(exc))
            self.finished.emit(outcome)
            return
        self.finished.emit(AnalysisOutcome(result=self.service.analyze(
            self.image,
            input_source=self.source.display_name or self.source.filename or self.source.source_type,
            source_type=self.source.source_type,
            source_identity=self.source.source_identity,
            source_display_name=self.source.display_name,
            captured_frame_sequence=self.source.frame_sequence,
            source_filename=self.source.filename,
        )))


class RulerAutoExposureWorker(QObject):
    finished = Signal(object)
    progress = Signal(object)

    def __init__(
        self,
        runner: RulerAutoExposureRunner,
        adapter: CameraCaptureBridgeRulerAdapter,
        device_name: str,
        cancel_event: Event,
    ) -> None:
        super().__init__()
        self.runner = runner
        self.adapter = adapter
        self.device_name = device_name
        self.cancel_event = cancel_event

    @Slot()
    def run(self) -> None:
        self.finished.emit(self.runner.run(
            self.adapter,
            self.device_name,
            self.cancel_event,
            self.progress.emit,
        ))


class RulerScaleTesterWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle(tr("calibration.tester.title"))
        self.resize(1500, 900)
        self.setMinimumSize(960, 650)
        self.service = CalibrationService()
        self.controller = CameraController(self)
        self._camera_bridge = CameraCaptureBridge(self.controller, self)
        self.devices: list[Any] = []
        self._frame_state = FrameCaptureState()
        self._current_input: np.ndarray | None = None
        self._current_source: AnalysisSource | None = None
        self._current_result: CalibrationResult | None = None
        self._analysis_thread: QThread | None = None
        self._analysis_worker: AnalysisWorker | None = None
        self._ruler_ae_thread: QThread | None = None
        self._ruler_ae_worker: RulerAutoExposureWorker | None = None
        self._ruler_ae_cancel = Event()
        self._ruler_ae_original_state: dict[str, object] | None = None
        self._repeatability_session = RepeatabilitySession()
        self._capture_history = CaptureHistoryStore()
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
        self.ruler_ae_enabled = QCheckBox(tr("calibration.tester.ruler_ae_enabled"))
        self.ruler_ae_cancel_button = QPushButton(tr("calibration.tester.ruler_ae_cancel"))
        self.load_button = QPushButton(tr("calibration.tester.load_image"))
        self.analyze_button = QPushButton(tr("calibration.tester.analyze_again"))
        self.save_debug_button = QPushButton(tr("calibration.tester.save_debug"))
        controls.addWidget(self.input_mode, 0, 0, 1, 2)
        controls.addWidget(self.camera_combo, 0, 2, 1, 2)
        controls.addWidget(self.ruler_ae_enabled, 0, 4, 1, 2)
        controls.addWidget(self.ruler_ae_cancel_button, 0, 6)
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
            ("live_view", "calibration.tester.tab_live"),
            ("captured", "calibration.tester.tab_captured"),
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
            ("source", "calibration.tester.analyzed_source"),
            ("ruler", "calibration.tester.ruler"),
            ("angle", "calibration.tester.angle"),
            ("ocr", "calibration.tester.ocr_numbers"),
            ("ticks", "calibration.tester.ticks"),
            ("scale", "calibration.tester.pixels_per_mm"),
            ("resolution", "calibration.tester.um_per_pixel"),
            ("span", "calibration.tester.span"),
            ("fit", "calibration.tester.fit_error"),
            ("quality", "calibration.tester.quality"),
            ("verification", "calibration.tester.verification_mode"),
            ("scale_bar", "calibration.tester.scale_bar"),
            ("failure", "calibration.tester.failure_warnings"),
        ):
            label = QLabel("—")
            label.setWordWrap(True)
            form.addRow(tr(title), label)
            self._result_labels[key] = label
        diagnostics_layout.addWidget(result_group)
        ae_group = QGroupBox(tr("calibration.tester.ruler_ae_group"))
        ae_form = QFormLayout(ae_group)
        self.ruler_ae_status_labels: dict[str, QLabel] = {}
        for key, title in (
            ("exposure", "calibration.tester.ruler_ae_exposure"),
            ("gain", "calibration.tester.ruler_ae_gain"),
            ("attempt", "calibration.tester.ruler_ae_attempt"),
            ("ruler_sat", "calibration.tester.ruler_ae_ruler_sat"),
            ("tick_sat", "calibration.tester.ruler_ae_tick_sat"),
            ("michelson", "calibration.tester.ruler_ae_michelson"),
            ("decision", "calibration.tester.ruler_ae_decision"),
        ):
            label = QLabel("—")
            label.setWordWrap(True)
            ae_form.addRow(tr(title), label)
            self.ruler_ae_status_labels[key] = label
        diagnostics_layout.addWidget(ae_group)
        self.ocr_status = QLabel()
        self.ocr_status.setWordWrap(True)
        diagnostics_layout.addWidget(self.ocr_status)

        history_group = QGroupBox(tr("calibration.tester.capture_history"))
        history_layout = QVBoxLayout(history_group)
        self.capture_history_text = QLabel()
        self.capture_history_text.setWordWrap(True)
        self.open_history_button = QPushButton(tr("calibration.tester.open_history_folder"))
        history_layout.addWidget(self.capture_history_text)
        history_layout.addWidget(self.open_history_button)
        diagnostics_layout.addWidget(history_group)

        repeat_group = QGroupBox(tr("calibration.tester.repeatability"))
        repeat_layout = QVBoxLayout(repeat_group)
        self.repeatability_text = QPlainTextEdit()
        self.repeatability_text.setReadOnly(True)
        self.repeatability_text.setMaximumBlockCount(500)
        self.clear_repeatability_button = QPushButton(tr("calibration.tester.clear_repeatability"))
        self.add_repeatability_button = QPushButton(tr("calibration.tester.add_repeatability"))
        self.export_repeatability_button = QPushButton(tr("calibration.tester.export_repeatability"))
        repeat_layout.addWidget(self.repeatability_text)
        repeat_layout.addWidget(self.add_repeatability_button)
        repeat_layout.addWidget(self.export_repeatability_button)
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
        self.ruler_ae_cancel_button.clicked.connect(self.cancel_ruler_auto_exposure)
        self.load_button.clicked.connect(self.load_image_file)
        self.analyze_button.clicked.connect(self.analyze_again)
        self.save_debug_button.clicked.connect(self.save_debug_package)
        self.clear_repeatability_button.clicked.connect(self.clear_repeatability)
        self.add_repeatability_button.clicked.connect(self.add_repeatability_run)
        self.export_repeatability_button.clicked.connect(self.export_repeatability_csv)
        self.open_history_button.clicked.connect(self.open_capture_history_folder)
        self.disconnect_button.setEnabled(False)
        self.capture_button.setEnabled(False)
        self.ruler_ae_cancel_button.setEnabled(False)
        self.analyze_button.setEnabled(False)
        self.save_debug_button.setEnabled(False)
        self.add_repeatability_button.setEnabled(False)
        self.export_repeatability_button.setEnabled(False)
        self._update_repeatability()
        self._update_capture_history(self._capture_history.statistics())

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
        self._frame_state.latest_frame = None
        self._frame_state.latest_sequence = None
        self.connect_button.setEnabled(bool(self.devices))
        self.disconnect_button.setEnabled(False)
        self.capture_button.setEnabled(False)
        LOG.info("Ruler tester camera disconnected")

    @Slot(QImage)
    def _on_preview_frame(self, image: QImage) -> None:
        self._image_labels["live_view"].set_qimage(image)

    @Slot(object, QImage, int)
    def _on_scientific_frame(self, scientific: object, preview: QImage, sequence: int) -> None:
        array = np.asarray(scientific)
        if array.ndim != 2:
            self.status.setText(tr("calibration.tester.frame_shape_rejected", shape=array.shape))
            return
        self._frame_state.update_live(array, sequence)
        self.capture_button.setEnabled(
            self._analysis_thread is None and self._ruler_ae_thread is None
        )
        self.input_mode.setText(tr("calibration.tester.input_live_frame", sequence=sequence))
        self._image_labels["live_view"].set_qimage(preview)

    @Slot(str)
    def _on_camera_error(self, message: str) -> None:
        LOG.error("Ruler tester camera error: %s", message)
        self.status.setText(tr("calibration.tester.camera_error", message=message))

    @Slot()
    def capture_and_analyze(self) -> None:
        if self._frame_state.latest_frame is None:
            self.status.setText(tr("calibration.tester.no_camera_frame"))
            return
        if self.ruler_ae_enabled.isChecked():
            self._start_ruler_auto_exposure()
            return
        try:
            metadata = self._camera_acquisition_metadata()
            self._current_input, self._current_source = self._frame_state.capture_camera(
                self.controller.device_name,
                acquisition_metadata=metadata,
            )
        except ValueError as exc:
            self.status.setText(str(exc))
            return
        self._image_labels["captured"].set_array(self._current_input)
        self.input_mode.setText(tr(
            "calibration.tester.input_captured_frame",
            source=self._current_source.display_name,
        ))
        self._start_analysis()

    def _camera_acquisition_metadata(self) -> dict[str, object]:
        metadata = dict(self.controller.capture_metadata())
        temperature = None
        try:
            temperature = self.controller.read_temperature_c()
        except Exception:
            pass
        metadata["CameraTemperatureC"] = temperature
        return metadata

    def _start_ruler_auto_exposure(self) -> None:
        if self._ruler_ae_thread is not None or not self.controller.is_open:
            return
        try:
            original_state = self._camera_acquisition_metadata()
        except Exception as exc:
            self.status.setText(str(exc))
            return
        self._ruler_ae_original_state = original_state
        self._ruler_ae_cancel.clear()
        runner = RulerAutoExposureRunner(self.service, self._capture_history)
        adapter = CameraCaptureBridgeRulerAdapter(
            self._camera_bridge,
            original_state,
        )
        thread = QThread(self)
        worker = RulerAutoExposureWorker(
            runner,
            adapter,
            self.controller.device_name,
            self._ruler_ae_cancel,
        )
        worker.moveToThread(thread)
        thread.started.connect(worker.run)
        worker.finished.connect(self._on_ruler_ae_finished)
        worker.progress.connect(self._on_ruler_ae_progress)
        worker.finished.connect(thread.quit)
        worker.finished.connect(worker.deleteLater)
        thread.finished.connect(self._ruler_ae_thread_finished)
        thread.finished.connect(thread.deleteLater)
        self._ruler_ae_thread = thread
        self._ruler_ae_worker = worker
        self._set_analysis_controls(False)
        self.ruler_ae_cancel_button.setEnabled(True)
        self.status.setText(tr("calibration.tester.ruler_ae_running"))
        thread.start()

    @Slot()
    def cancel_ruler_auto_exposure(self) -> None:
        if self._ruler_ae_thread is None:
            return
        self._ruler_ae_cancel.set()
        self.ruler_ae_cancel_button.setEnabled(False)
        self.status.setText(tr("calibration.tester.ruler_ae_cancelling"))

    @Slot(object)
    def _on_ruler_ae_progress(self, payload: object) -> None:
        if isinstance(payload, RulerAEAttemptRecord):
            self._show_ruler_ae_attempt(payload)

    def _show_ruler_ae_attempt(self, attempt: RulerAEAttemptRecord) -> None:
        self.ruler_ae_status_labels["exposure"].setText(
            "—" if attempt.actual_exposure_us is None else tr(
                "calibration.tester.ruler_ae_exposure_value",
                value=attempt.actual_exposure_us,
            )
        )
        self.ruler_ae_status_labels["gain"].setText(
            "—" if attempt.actual_gain is None else str(attempt.actual_gain)
        )
        self.ruler_ae_status_labels["attempt"].setText(str(attempt.attempt_index))
        self.ruler_ae_status_labels["ruler_sat"].setText(
            _format_percent(attempt.ruler_roi_saturation_fraction)
        )
        self.ruler_ae_status_labels["tick_sat"].setText(
            _format_percent(attempt.tick_band_saturation_fraction)
        )
        self.ruler_ae_status_labels["michelson"].setText(
            "—" if attempt.michelson_tick_contrast is None else f"{attempt.michelson_tick_contrast:.3f}"
        )
        self.ruler_ae_status_labels["decision"].setText(
            tr(
                "calibration.tester.ruler_ae_decision_value",
                decision=attempt.decision,
                reason=attempt.decision_reason,
            )
        )

    @Slot(object)
    def _on_ruler_ae_finished(self, payload: object) -> None:
        if not isinstance(payload, RulerAutoExposureOutcome):
            self.status.setText(tr("calibration.tester.invalid_result"))
            return
        self._current_result = payload.result
        if payload.result.raw_input is not None:
            self._current_input = np.asarray(payload.result.raw_input).copy()
            self._image_labels["captured"].set_array(self._current_input)
        for name, image in payload.result.debug_images.items():
            label = self._image_labels.get(name)
            if label is not None:
                label.set_array(image)
        self._show_result(payload.result)
        self.save_debug_button.setEnabled(bool(payload.result.debug_images))
        self.add_repeatability_button.setEnabled(
            payload.result.success
            and payload.result.verification_mode
            in {
                VerificationMode.TICK_HIERARCHY_VERIFIED.value,
                VerificationMode.OCR_VERIFIED.value,
            }
        )
        if payload.attempts:
            self._show_ruler_ae_attempt(payload.attempts[-1])
        if payload.history_stats is not None:
            self._update_capture_history(payload.history_stats)
        self.status.setText(
            tr("calibration.tester.ruler_ae_completed", result="PASS" if payload.success else "FAIL", reason=payload.reason)
        )

    @Slot()
    def _ruler_ae_thread_finished(self) -> None:
        self._ruler_ae_thread = None
        self._ruler_ae_worker = None
        self._ruler_ae_original_state = None
        self.ruler_ae_cancel_button.setEnabled(False)
        self._set_analysis_controls(True)

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
            loaded = load_image(path)
            self._current_input, self._current_source = self._frame_state.capture_file(path, loaded)
        except Exception as exc:
            QMessageBox.critical(self, tr("calibration.tester.load_failed"), str(exc))
            return
        self.input_mode.setText(tr("calibration.tester.input_file", name=Path(path).name))
        self._image_labels["captured"].set_array(self._current_input)
        self.analyze_button.setEnabled(True)
        self._start_analysis()

    @Slot()
    def analyze_again(self) -> None:
        if self._current_input is not None:
            self._start_analysis()

    def _start_analysis(self) -> None:
        if self._current_input is None or self._current_source is None or self._analysis_thread is not None:
            return
        self.status.setText(tr("calibration.tester.analyzing"))
        self._set_analysis_controls(False)
        self.add_repeatability_button.setEnabled(False)
        thread = QThread(self)
        worker = AnalysisWorker(
            self.service,
            self._current_input,
            self._current_source,
            self._capture_history,
        )
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
        if not isinstance(payload, AnalysisOutcome):
            self.status.setText(tr("calibration.tester.invalid_result"))
            return
        result = payload.result
        if not isinstance(result, CalibrationResult):
            self.status.setText(tr("calibration.tester.invalid_result"))
            return
        self._current_result = result
        for name, image in result.debug_images.items():
            label = self._image_labels.get(name)
            if label is not None:
                label.set_array(image)
        self._show_result(result)
        self.add_repeatability_button.setEnabled(
            result.success
            and result.verification_mode
            in {
                VerificationMode.TICK_HIERARCHY_VERIFIED.value,
                VerificationMode.OCR_VERIFIED.value,
            }
        )
        self.save_debug_button.setEnabled(bool(result.debug_images))
        result_text = (
            tr("calibration.tester.calibration_pass")
            if result.success
            else tr(
                "calibration.tester.calibration_fail",
                reasons=", ".join(result.failure_reasons),
            )
        )
        if payload.capture_id:
            result_text = tr(
                "calibration.tester.capture_saved_status",
                capture_id=payload.capture_id,
                result=result_text,
            )
        if payload.persistence_error:
            result_text = tr(
                "calibration.tester.capture_persistence_warning",
                result=result_text,
                error=payload.persistence_error,
            )
        self.status.setText(result_text)
        if payload.history_stats is not None:
            self._update_capture_history(payload.history_stats)

    @Slot()
    def _analysis_thread_finished(self) -> None:
        self._analysis_thread = None
        self._analysis_worker = None
        self._set_analysis_controls(True)

    def _set_analysis_controls(self, enabled: bool) -> None:
        self.load_button.setEnabled(enabled)
        self.analyze_button.setEnabled(enabled and self._current_input is not None)
        self.capture_button.setEnabled(
            enabled and self.controller.is_open and self._frame_state.latest_frame is not None
        )
        self.ruler_ae_enabled.setEnabled(enabled)

    def _show_result(self, result: CalibrationResult) -> None:
        numbers = []
        for item in result.detected_numbers:
            text = item.raw_text
            if item.corrected_value is not None:
                text += f"→{item.corrected_value} (rejected raw)"
            elif not item.accepted:
                text += " (rejected)"
            numbers.append(text)
        source_text = (
            result.source_display_name
            or result.source_filename
            or result.source_identity
            or result.source_type
        )
        if result.captured_frame_sequence is not None:
            source_text = tr(
                "calibration.tester.analyzed_camera_frame",
                source=source_text,
                sequence=result.captured_frame_sequence,
            )
        self._result_labels["source"].setText(source_text or "—")
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
        self._result_labels["verification"].setText(result.verification_mode)
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
        default_root = str((PROJECT_ROOT / "local" / "generated" / "debug").resolve())
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
        self._repeatability_session.clear()
        self._update_repeatability()

    @Slot()
    def add_repeatability_run(self) -> None:
        if self._current_result is None:
            return
        try:
            self._repeatability_session.add_result(self._current_result)
        except DuplicateSourceError:
            QMessageBox.warning(
                self,
                tr("calibration.tester.duplicate_repeatability_title"),
                tr("calibration.tester.duplicate_repeatability"),
            )
            return
        except ValueError as exc:
            QMessageBox.warning(self, tr("calibration.tester.repeatability"), str(exc))
            return
        self.export_repeatability_button.setEnabled(True)
        self._update_repeatability()

    @Slot()
    def export_repeatability_csv(self) -> None:
        if not self._repeatability_session.runs:
            return
        path, _ = QFileDialog.getSaveFileName(
            self,
            tr("calibration.tester.export_repeatability"),
            "ruler_repeatability.csv",
            "CSV (*.csv)",
        )
        if not path:
            return
        try:
            output = self._repeatability_session.export_csv(path)
        except Exception as exc:
            QMessageBox.critical(
                self, tr("calibration.tester.export_repeatability_failed"), str(exc)
            )
            return
        QMessageBox.information(
            self, tr("calibration.tester.export_repeatability"), str(output)
        )

    def _update_repeatability(self) -> None:
        summary = self._repeatability_session.summary()
        lines = [
            tr(
                "calibration.tester.repeat_run",
                index=f"{index:02d}",
                value=f"{run.pixels_per_mm:.6f}",
            )
            for index, run in enumerate(self._repeatability_session.runs, 1)
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
        self.export_repeatability_button.setEnabled(bool(self._repeatability_session.runs))

    def _update_capture_history(self, stats: object) -> None:
        count = int(getattr(stats, "count", 0))
        disk_bytes = int(getattr(stats, "disk_bytes", 0))
        root = str(getattr(stats, "root", self._capture_history.root.resolve()))
        self.capture_history_text.setText(tr(
            "calibration.tester.capture_history_summary",
            count=count,
            size=_format_bytes(disk_bytes),
            path=root,
        ))

    @Slot()
    def open_capture_history_folder(self) -> None:
        root = self._capture_history.root.resolve()
        root.mkdir(parents=True, exist_ok=True)
        if not QDesktopServices.openUrl(QUrl.fromLocalFile(str(root))):
            QMessageBox.warning(
                self,
                tr("calibration.tester.capture_history"),
                tr("calibration.tester.open_history_failed", path=str(root)),
            )

    def closeEvent(self, event: QCloseEvent) -> None:
        if self._ruler_ae_thread is not None and self._ruler_ae_thread.isRunning():
            self._ruler_ae_cancel.set()
            if self._ruler_ae_original_state is not None and self.controller.is_open:
                try:
                    self.controller.restore_exposure_state(self._ruler_ae_original_state)
                except Exception:
                    LOG.exception("Failed to restore ruler AE state during close")
        self.controller.close_camera()
        if self._ruler_ae_thread is not None and self._ruler_ae_thread.isRunning():
            if not self._ruler_ae_thread.wait(5000):
                self.status.setText(tr("calibration.tester.waiting_close"))
                event.ignore()
                return
        if self._analysis_thread is not None and self._analysis_thread.isRunning():
            if not self._analysis_thread.wait(5000):
                self.status.setText(tr("calibration.tester.waiting_close"))
                event.ignore()
                return
        event.accept()


def _format_stat(value: object) -> str:
    return "—" if value is None else f"{float(value):.6f}"


def _format_bytes(value: int) -> str:
    amount = float(max(0, value))
    for unit in ("B", "KiB", "MiB", "GiB", "TiB"):
        if amount < 1024.0 or unit == "TiB":
            return f"{amount:.1f} {unit}"
        amount /= 1024.0
    return f"{amount:.1f} TiB"


def _format_percent(value: float | None) -> str:
    return "—" if value is None else f"{value * 100.0:.2f}%"
