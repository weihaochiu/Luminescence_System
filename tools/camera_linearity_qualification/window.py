from __future__ import annotations

from datetime import datetime, timedelta
import json
import logging
from pathlib import Path
from threading import Event
from time import monotonic
from typing import Any

import numpy as np
from PySide6.QtCore import QObject, QPoint, QRect, Qt, QThread, QTimer, Signal, Slot
from PySide6.QtGui import QCloseEvent, QImage, QMouseEvent, QPainter, QPen, QPixmap
from PySide6.QtWidgets import (
    QApplication, QCheckBox, QComboBox, QFileDialog, QFormLayout, QGridLayout,
    QGroupBox, QHBoxLayout, QLabel, QLineEdit, QMainWindow, QMessageBox,
    QPlainTextEdit, QProgressBar, QPushButton, QSpinBox, QTabWidget, QVBoxLayout,
    QWidget,
)

from gui.camera_capture_bridge import CameraCaptureBridge
from gui.camera_controller import CameraController
from core.i18n import tr

from .analysis import CameraLinearityAnalyzer
from .capture_plan import FULL_EXPOSURES_MS, FULL_GAINS, build_capture_plan
from .capture_runner import CameraCaptureBridgeAdapter, CaptureProgress, CaptureRunner
from .models import ROI, RunMode
from .profile import load_profile
from .settings import QualificationCriteria
from .image_loader import load_folder


LOG = logging.getLogger(__name__)
PROJECT_ROOT = Path(__file__).resolve().parents[2]


class ROIImageLabel(QLabel):
    roi_changed = Signal(object)

    def __init__(self) -> None:
        super().__init__("Waiting for Scientific MONO16 frame")
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.setMinimumSize(640, 420)
        self.setStyleSheet("background:#202124;color:#ddd;border:1px solid #555")
        self._image: QImage | None = None
        self._roi: ROI | None = None
        self._drag_start: QPoint | None = None
        self._drag_end: QPoint | None = None

    @property
    def roi(self) -> ROI | None:
        return self._roi

    def reset_full(self) -> None:
        if self._image is None:
            self._roi = None
        else:
            self._roi = ROI(0, 0, self._image.width(), self._image.height())
        self.roi_changed.emit(self._roi)
        self.update()

    def set_frame(self, image: QImage) -> None:
        self._image = image.copy()
        if self._roi is not None:
            try: self._roi.validate(image.width(), image.height())
            except ValueError: self._roi = None
        self.update()

    def paintEvent(self, event: Any) -> None:
        super().paintEvent(event)
        if self._image is None: return
        painter = QPainter(self)
        target = self._target_rect()
        painter.drawImage(target, self._image)
        if self._roi:
            scale_x, scale_y = target.width() / self._image.width(), target.height() / self._image.height()
            rectangle = QRect(
                round(target.left() + self._roi.x * scale_x), round(target.top() + self._roi.y * scale_y),
                max(1, round(self._roi.width * scale_x)), max(1, round(self._roi.height * scale_y)),
            )
            painter.setPen(QPen(Qt.GlobalColor.red, 3)); painter.drawRect(rectangle)
        if self._drag_start is not None and self._drag_end is not None:
            painter.setPen(QPen(Qt.GlobalColor.yellow, 2)); painter.drawRect(QRect(self._drag_start, self._drag_end).normalized())

    def mousePressEvent(self, event: QMouseEvent) -> None:
        if self._image is not None and event.button() == Qt.MouseButton.LeftButton:
            self._drag_start = event.position().toPoint(); self._drag_end = self._drag_start; self.update()

    def mouseMoveEvent(self, event: QMouseEvent) -> None:
        if self._drag_start is not None:
            self._drag_end = event.position().toPoint(); self.update()

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:
        if self._drag_start is None or self._image is None: return
        self._drag_end = event.position().toPoint()
        selected = QRect(self._drag_start, self._drag_end).normalized().intersected(self._target_rect())
        target = self._target_rect(); self._drag_start = self._drag_end = None
        if selected.width() >= 3 and selected.height() >= 3:
            scale_x, scale_y = self._image.width() / target.width(), self._image.height() / target.height()
            self._roi = ROI(
                max(0, round((selected.left() - target.left()) * scale_x)),
                max(0, round((selected.top() - target.top()) * scale_y)),
                max(1, round(selected.width() * scale_x)), max(1, round(selected.height() * scale_y)),
            )
            self._roi.validate(self._image.width(), self._image.height())
            self.roi_changed.emit(self._roi)
        self.update()

    def _target_rect(self) -> QRect:
        if self._image is None: return self.rect()
        size = self._image.size(); size.scale(self.size(), Qt.AspectRatioMode.KeepAspectRatio)
        return QRect((self.width() - size.width()) // 2, (self.height() - size.height()) // 2, size.width(), size.height())


class WorkRequest(QObject):
    progress = Signal(object)
    confirmation = Signal(str, object, object, object)
    finished = Signal(object)

    def __init__(self, runner: CaptureRunner, warmup_s: int, analyze: bool) -> None:
        super().__init__(); self.runner = runner; self.warmup_s = int(warmup_s); self.analyze = analyze

    def confirm(self, phase: str, payload: dict[str, Any]) -> bool:
        completed = Event(); response: dict[str, bool] = {}
        self.confirmation.emit(phase, payload, completed, response)
        while not completed.wait(.05):
            if self.runner.cancel_event.is_set(): return False
        return bool(response.get("accepted"))

    @Slot()
    def run(self) -> None:
        try:
            deadline = monotonic() + self.warmup_s
            while monotonic() < deadline:
                if self.runner.cancel_event.wait(min(.1, deadline - monotonic())): break
            result = self.runner.run()
            outcome = None
            if result.completed and self.analyze and result.pilot_readiness is None:
                outcome = CameraLinearityAnalyzer(self.runner.criteria).analyze_folder(
                    result.session_dir, mode=self.runner.plan.mode,
                    synthetic=False, full_frame_confirmed=True,
                )
            self.finished.emit((result, outcome, None))
        except Exception as exc:
            LOG.exception("Camera qualification run failed")
            self.finished.emit((None, None, exc))


class AnalyzeRequest(QObject):
    finished = Signal(object)
    def __init__(self, folder: Path, criteria: QualificationCriteria, roi: ROI | None, full_confirmed: bool) -> None:
        super().__init__(); self.folder = folder; self.criteria = criteria; self.roi = roi; self.full_confirmed = full_confirmed
    @Slot()
    def run(self) -> None:
        try: self.finished.emit((CameraLinearityAnalyzer(self.criteria).analyze_folder(self.folder, roi=self.roi, full_frame_confirmed=self.full_confirmed), None))
        except Exception as exc: self.finished.emit((None, exc))


class LogHandler(logging.Handler):
    def __init__(self, signal: Signal) -> None:
        super().__init__(); self.signal = signal
    def emit(self, record: logging.LogRecord) -> None:
        self.signal.emit(self.format(record))


class CameraLinearityQualificationWindow(QMainWindow):
    log_message = Signal(str)
    def __init__(self) -> None:
        super().__init__(); self.setWindowTitle(tr("camera.linearity.title")); self.resize(1500, 950); self.setMinimumSize(1050, 700)
        self.controller = CameraController(self); self.bridge = CameraCaptureBridge(self.controller, self)
        self.devices: list[Any] = []; self.latest_scientific: np.ndarray | None = None; self.criteria = QualificationCriteria()
        self._thread: QThread | None = None; self._worker: QObject | None = None; self._cancel = Event(); self._close_when_idle = False
        self._build_ui(); self._wire(); self.refresh_cameras(); self._install_log_handler()
        self.temperature_timer = QTimer(self); self.temperature_timer.setInterval(1000); self.temperature_timer.timeout.connect(self._refresh_temperature)

    def _build_ui(self) -> None:
        tabs = QTabWidget(); self.setCentralWidget(tabs)
        capture = QWidget(); layout = QHBoxLayout(capture); left = QWidget(); left_layout = QVBoxLayout(left)
        camera_group = QGroupBox(tr("camera.linearity.camera_stream")); camera_form = QFormLayout(camera_group)
        self.camera_combo = QComboBox(); buttons = QWidget(); button_layout = QHBoxLayout(buttons); button_layout.setContentsMargins(0,0,0,0)
        self.refresh_button = QPushButton(tr("camera.linearity.refresh")); self.connect_button = QPushButton(tr("camera.linearity.connect")); self.disconnect_button = QPushButton(tr("camera.linearity.disconnect"))
        for button in (self.refresh_button,self.connect_button,self.disconnect_button): button_layout.addWidget(button)
        self.camera_labels = {key: QLabel("—") for key in ("live","pixel","depth","dnmax","alignment","exposure_range","gain_range","temperature")}
        camera_form.addRow(tr("camera.linearity.camera"), self.camera_combo); camera_form.addRow(buttons); camera_form.addRow(tr("camera.linearity.live_view"), self.camera_labels["live"])
        for title,key in ((tr("camera.linearity.scientific_mono16"),"pixel"),(tr("camera.linearity.sensor_bit_depth"),"depth"),(tr("camera.linearity.effective_dn_max"),"dnmax"),(tr("camera.linearity.raw_alignment"),"alignment"),(tr("camera.linearity.exposure_range"),"exposure_range"),(tr("camera.linearity.gain_range"),"gain_range"),(tr("camera.linearity.camera_temperature"),"temperature")): camera_form.addRow(title,self.camera_labels[key])
        left_layout.addWidget(camera_group)
        roi_group = QGroupBox(tr("camera.linearity.roi_group")); roi_form = QFormLayout(roi_group); self.roi_value=QLabel(tr("camera.linearity.not_selected")); self.roi_reset=QPushButton(tr("camera.linearity.reset_full")); roi_form.addRow(tr("camera.linearity.roi_coordinates"),self.roi_value); roi_form.addRow(self.roi_reset); left_layout.addWidget(roi_group)
        plan_group = QGroupBox(tr("camera.linearity.capture_plan")); plan_form=QFormLayout(plan_group)
        self.output_path=QLineEdit(str(PROJECT_ROOT / "local" / "camera_linearity")); browse=QPushButton(tr("camera.linearity.browse")); out_row=QWidget(); out_l=QHBoxLayout(out_row); out_l.setContentsMargins(0,0,0,0); out_l.addWidget(self.output_path); out_l.addWidget(browse)
        self.gains=QLineEdit(", ".join(map(str,FULL_GAINS))); self.exposures=QLineEdit(", ".join(f"{x:g}" for x in FULL_EXPOSURES_MS))
        self.light_repeats=_spin(1,20,5); self.dark_repeats=_spin(0,20,5); self.settling=_spin(0,20,2); self.timeout_overhead=_spin(0,60,3); self.timeout_overhead.setToolTip(tr("camera.linearity.timeout_tooltip")); self.warmup=_spin(0,3600,0)
        self.mode=QComboBox(); self.mode.addItem(tr("camera.linearity.mode_pilot"),RunMode.PILOT.value); self.mode.addItem(tr("camera.linearity.mode_full"),RunMode.FULL.value); self.mode.addItem(tr("camera.linearity.mode_quick"),RunMode.QUICK.value); self.mode.setCurrentIndex(1)
        self.adaptive_stop=QCheckBox(tr("camera.linearity.adaptive_stop")); self.adaptive_stop.setChecked(True)
        for title,widget in ((tr("camera.linearity.output_folder"),out_row),(tr("camera.linearity.mode"),self.mode),(tr("camera.linearity.gain_list"),self.gains),(tr("camera.linearity.exposure_list"),self.exposures),(tr("camera.linearity.light_repeats"),self.light_repeats),(tr("camera.linearity.dark_repeats"),self.dark_repeats),(tr("camera.linearity.settling_frames"),self.settling),(tr("camera.linearity.timeout_overhead"),self.timeout_overhead),(tr("camera.linearity.warmup"),self.warmup),("",self.adaptive_stop)): plan_form.addRow(title,widget)
        left_layout.addWidget(plan_group)
        actions=QGridLayout(); self.start_button=QPushButton(tr("camera.linearity.start")); self.stop_button=QPushButton(tr("camera.linearity.stop_safely")); self.emergency_button=QPushButton(tr("camera.linearity.emergency_close")); actions.addWidget(self.start_button,0,0); actions.addWidget(self.stop_button,0,1); actions.addWidget(self.emergency_button,1,0,1,2); left_layout.addLayout(actions); left_layout.addStretch(1)
        self.live_view=ROIImageLabel(); right=QWidget(); right_layout=QVBoxLayout(right); right_layout.addWidget(self.live_view,1)
        status_group=QGroupBox(tr("camera.linearity.run_status")); status_form=QFormLayout(status_group); self.run_labels={key:QLabel("—") for key in ("condition","count","percent","elapsed","remaining","finish","metrics","decision","message")}; self.progress_bar=QProgressBar()
        for title,key in ((tr("camera.linearity.current_condition"),"condition"),(tr("camera.linearity.completed_total"),"count"),(tr("camera.linearity.progress"),"percent"),(tr("camera.linearity.elapsed"),"elapsed"),(tr("camera.linearity.remaining"),"remaining"),(tr("camera.linearity.estimated_finish"),"finish"),(tr("camera.linearity.roi_metrics"),"metrics"),(tr("camera.linearity.live_decision"),"decision"),(tr("camera.linearity.reason"),"message")): status_form.addRow(title,self.run_labels[key])
        status_form.addRow(self.progress_bar); right_layout.addWidget(status_group)
        layout.addWidget(left,0); layout.addWidget(right,1); tabs.addTab(capture,tr("camera.linearity.tab_capture"))

        existing=QWidget(); existing_layout=QVBoxLayout(existing); existing_form=QFormLayout(); self.existing_path=QLineEdit(); existing_browse=QPushButton(tr("camera.linearity.select_folder")); existing_row=QWidget(); existing_row_l=QHBoxLayout(existing_row); existing_row_l.setContentsMargins(0,0,0,0); existing_row_l.addWidget(self.existing_path); existing_row_l.addWidget(existing_browse); self.existing_roi=QLineEdit(); self.existing_roi.setPlaceholderText(tr("camera.linearity.roi_override_placeholder")); self.full_frame_confirm=QCheckBox(tr("camera.linearity.confirm_full_frame")); self.analyze_existing_button=QPushButton(tr("camera.linearity.run_preflight")); self.preflight_text=QPlainTextEdit(); self.preflight_text.setReadOnly(True); existing_form.addRow(tr("camera.linearity.dataset_folder"),existing_row); existing_form.addRow(tr("camera.linearity.roi_override"),self.existing_roi); existing_form.addRow("",self.full_frame_confirm); existing_layout.addLayout(existing_form); existing_layout.addWidget(self.analyze_existing_button); existing_layout.addWidget(self.preflight_text,1); tabs.addTab(existing,tr("camera.linearity.tab_existing"))

        results=QWidget(); results_layout=QVBoxLayout(results); self.results_text=QPlainTextEdit(); self.results_text.setReadOnly(True); self.results_folder=QLineEdit(); self.results_folder.setReadOnly(True); results_layout.addWidget(self.results_text,1); results_layout.addWidget(self.results_folder); tabs.addTab(results,tr("camera.linearity.tab_results"))
        settings=QWidget(); settings_layout=QVBoxLayout(settings); settings_layout.addWidget(QLabel(tr("camera.linearity.criteria_json"))); self.criteria_editor=QPlainTextEdit(json.dumps(self.criteria.to_dict(),indent=2)); self.apply_criteria=QPushButton(tr("camera.linearity.apply_criteria")); self.profile_path=QLineEdit(); profile_browse=QPushButton(tr("camera.linearity.select_profile")); profile_row=QWidget(); profile_l=QHBoxLayout(profile_row); profile_l.setContentsMargins(0,0,0,0); profile_l.addWidget(self.profile_path); profile_l.addWidget(profile_browse); settings_layout.addWidget(self.criteria_editor,1); settings_layout.addWidget(self.apply_criteria); form=QFormLayout(); form.addRow(tr("camera.linearity.quick_profile"),profile_row); settings_layout.addLayout(form); tabs.addTab(settings,tr("camera.linearity.tab_settings"))
        log_tab=QWidget(); log_layout=QVBoxLayout(log_tab); self.log_text=QPlainTextEdit(); self.log_text.setReadOnly(True); self.log_text.setMaximumBlockCount(5000); log_layout.addWidget(self.log_text); tabs.addTab(log_tab,tr("camera.linearity.tab_log"))
        self.stop_button.setEnabled(False); self.disconnect_button.setEnabled(False)
        self._browse_output=browse; self._browse_existing=existing_browse; self._browse_profile=profile_browse

    def _wire(self) -> None:
        self.refresh_button.clicked.connect(self.refresh_cameras); self.connect_button.clicked.connect(self.connect_camera); self.disconnect_button.clicked.connect(self.disconnect_camera)
        self.controller.camera_opened.connect(self._camera_opened); self.controller.camera_closed.connect(self._camera_closed); self.controller.frame_ready.connect(self.live_view.set_frame); self.controller.scientific_frame_ready.connect(self._scientific_frame); self.controller.error_occurred.connect(lambda message: LOG.error("Camera: %s",message))
        self.live_view.roi_changed.connect(self._roi_changed); self.roi_reset.clicked.connect(self.live_view.reset_full); self.start_button.clicked.connect(self.start_capture); self.stop_button.clicked.connect(self.stop_safely); self.emergency_button.clicked.connect(self.emergency_close)
        self._browse_output.clicked.connect(lambda: self._choose_folder(self.output_path)); self._browse_existing.clicked.connect(lambda: self._choose_folder(self.existing_path)); self._browse_profile.clicked.connect(self._choose_profile)
        self.analyze_existing_button.clicked.connect(self.analyze_existing); self.apply_criteria.clicked.connect(self._apply_criteria); self.log_message.connect(self.log_text.appendPlainText)
        self.mode.currentIndexChanged.connect(self._mode_changed)

    def _install_log_handler(self) -> None:
        handler=LogHandler(self.log_message); handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s")); logging.getLogger().addHandler(handler); self._log_handler=handler

    @Slot()
    def refresh_cameras(self) -> None:
        if self.controller.is_open: self.controller.close_camera()
        self.devices=self.controller.enumerate_devices(); self.camera_combo.clear()
        for device in self.devices: self.camera_combo.addItem(str(device.displayname))
        self.connect_button.setEnabled(bool(self.devices)); LOG.info("Found %d camera(s)",len(self.devices))

    @Slot()
    def connect_camera(self) -> None:
        index=self.camera_combo.currentIndex()
        if 0 <= index < len(self.devices): self.controller.open_device(self.devices[index])

    @Slot()
    def disconnect_camera(self) -> None:
        self.controller.close_camera()

    @Slot(object)
    def _camera_opened(self, info: object) -> None:
        data=info if isinstance(info,dict) else {}; self.connect_button.setEnabled(False); self.disconnect_button.setEnabled(True); self.temperature_timer.start()
        self.camera_labels["live"].setText(tr("camera.linearity.active")); self.camera_labels["pixel"].setText(str(data.get("scientific_pixel_format","UNKNOWN"))); self.camera_labels["depth"].setText(str(data.get("scientific_bit_depth","—"))); self.camera_labels["dnmax"].setText(str(data.get("effective_dn_max","—"))); self.camera_labels["alignment"].setText(str(data.get("raw_value_alignment","unknown"))); self.camera_labels["exposure_range"].setText(str(data.get("exposure_range_us","—"))); self.camera_labels["gain_range"].setText(str(data.get("gain_range","—")))

    @Slot()
    def _camera_closed(self) -> None:
        self.temperature_timer.stop(); self.connect_button.setEnabled(bool(self.devices)); self.disconnect_button.setEnabled(False); self.camera_labels["live"].setText(tr("camera.linearity.disconnected")); self.camera_labels["temperature"].setText("N/A"); self.latest_scientific=None

    @Slot(object,QImage,int)
    def _scientific_frame(self, scientific: object, preview: QImage, sequence: int) -> None:
        self.latest_scientific=np.asarray(scientific).copy(); self.live_view.set_frame(preview); self.camera_labels["live"].setText(tr("camera.linearity.active_sequence",sequence=sequence))

    @Slot()
    def _refresh_temperature(self) -> None:
        try: value=self.controller.read_temperature_c(); self.camera_labels["temperature"].setText("N/A" if value is None else tr("camera.linearity.temperature_value",value=f"{value:.1f}"))
        except Exception: self.camera_labels["temperature"].setText("N/A")

    @Slot(object)
    def _roi_changed(self, value: object) -> None:
        self.roi_value.setText(tr("camera.linearity.not_selected") if not isinstance(value,ROI) else tr("camera.linearity.roi_value",x=value.x,y=value.y,width=value.width,height=value.height))

    @Slot()
    def start_capture(self) -> None:
        if self._thread is not None or not self.controller.is_open or self.latest_scientific is None:
            QMessageBox.warning(self,tr("camera.linearity.cannot_start"),tr("camera.linearity.connect_camera_first")); return
        roi=self.live_view.roi
        if roi is None:
            answer=QMessageBox.question(self,tr("camera.linearity.use_full_title"),tr("camera.linearity.use_full_question"))
            if answer != QMessageBox.StandardButton.Yes: return
            self.live_view.reset_full(); roi=self.live_view.roi
        try:
            mode=RunMode(self.mode.currentData()); profile=load_profile(self.profile_path.text()) if mode is RunMode.QUICK and self.profile_path.text().strip() else None
            selected_gains = _numbers(self.gains.text(),int) if mode is RunMode.FULL else (100,)
            selected_exposures = _numbers(self.exposures.text(),float) if mode is not RunMode.QUICK else None
            plan=build_capture_plan(mode,profile=profile,gains=selected_gains,exposures_ms=selected_exposures,light_repeats=self.light_repeats.value(),dark_repeats=(0 if mode is RunMode.PILOT else self.dark_repeats.value()),settling_frames=self.settling.value(),adaptive_early_stop=self.adaptive_stop.isChecked())
            original_state=dict(self.controller.capture_metadata())
            try: original_state["CameraTemperatureC"]=self.controller.read_temperature_c()
            except Exception: original_state["CameraTemperatureC"]=None
            adapter=CameraCaptureBridgeAdapter(self.bridge,self.controller,original_state); self._cancel.clear()
            run_criteria_payload=self.criteria.to_dict(); run_criteria_payload["capture_timeout_overhead_s"]=self.timeout_overhead.value(); run_criteria=QualificationCriteria.from_dict(run_criteria_payload)
            runner=CaptureRunner(adapter,plan,self.output_path.text(),roi,criteria=run_criteria,cancel_event=self._cancel)
            worker=WorkRequest(runner,self.warmup.value(),True); runner.confirm_phase=worker.confirm
            runner.progress=worker.progress.emit
            thread=QThread(self); worker.moveToThread(thread); thread.started.connect(worker.run); worker.progress.connect(self._on_progress); worker.confirmation.connect(self._confirm_phase); worker.finished.connect(self._capture_finished); worker.finished.connect(thread.quit); worker.finished.connect(worker.deleteLater); thread.finished.connect(self._thread_finished); thread.finished.connect(thread.deleteLater)
            self._thread=thread; self._worker=worker; self._set_busy(True); thread.start()
        except Exception as exc: QMessageBox.critical(self,tr("camera.linearity.invalid_plan"),str(exc))

    @Slot(object)
    def _on_progress(self,payload:object)->None:
        if not isinstance(payload,CaptureProgress): return
        percent=round(payload.completed_frames/max(1,payload.total_frames)*100); self.progress_bar.setValue(percent); self.run_labels["condition"].setText(f"{payload.phase} — {payload.condition}"); self.run_labels["count"].setText(f"{payload.completed_frames} / {payload.total_frames}"); self.run_labels["percent"].setText(f"{percent}%"); self.run_labels["elapsed"].setText(_duration(payload.elapsed_s)); self.run_labels["remaining"].setText(_duration(payload.eta_s)); self.run_labels["finish"].setText("—" if payload.eta_s is None else (datetime.now()+timedelta(seconds=payload.eta_s)).strftime("%Y-%m-%d %H:%M:%S")); self.run_labels["metrics"].setText(f"{payload.median_dn:.2f} / {payload.p99_dn:.2f} / {payload.saturation_fraction:.5%}"); self.run_labels["decision"].setText(payload.status); self.run_labels["message"].setText(payload.message)

    @Slot(str,object,object,object)
    def _confirm_phase(self,phase:str,payload:object,completed:object,response:object)->None:
        data=payload if isinstance(payload,dict) else {}; text=str(data.get("instruction") or data.get("warning") or phase)
        if data.get("camera_temperature_c") is not None: text += f"\n\nCamera temperature: {float(data['camera_temperature_c']):.1f} °C"
        if data.get("dark_median") is not None: text += f"\nDark median: {float(data['dark_median']):.2f} DN\nMatching Light median: {float(data['light_median']):.2f} DN"
        answer=QMessageBox.question(self,tr("camera.linearity.confirm_phase",phase=phase),text,QMessageBox.StandardButton.Yes|QMessageBox.StandardButton.No)
        if isinstance(response,dict): response["accepted"]=answer==QMessageBox.StandardButton.Yes
        if isinstance(completed,Event): completed.set()

    @Slot(object)
    def _capture_finished(self,payload:object)->None:
        result,outcome,error=payload
        if error: QMessageBox.critical(self,tr("camera.linearity.qualification_failed"),str(error)); self.results_text.setPlainText(str(error))
        elif result:
            self.results_folder.setText(str(result.session_dir));
            if result.pilot_readiness: self.results_text.setPlainText(f"Pilot result: {result.pilot_readiness}\nNo formal PASS profile was created.")
            elif outcome: self._show_outcome(outcome)

    @Slot()
    def _thread_finished(self)->None:
        self._thread=None; self._worker=None; self._set_busy(False)
        if self._close_when_idle: self.controller.close_camera(); QTimer.singleShot(0,self.close)

    @Slot()
    def stop_safely(self)->None:
        self._cancel.set(); self.run_labels["message"].setText(tr("camera.linearity.safe_stop_waiting")); self.stop_button.setEnabled(False)

    @Slot()
    def emergency_close(self)->None:
        self._cancel.set(); self.controller.close_camera(); self.run_labels["message"].setText(tr("camera.linearity.emergency_requested"))

    @Slot()
    def analyze_existing(self)->None:
        if self._thread is not None: return
        folder=Path(self.existing_path.text());
        try: roi=_parse_roi(self.existing_roi.text())
        except ValueError as exc: QMessageBox.warning(self,tr("camera.linearity.invalid_roi"),str(exc)); return
        if roi is None and not self.full_frame_confirm.isChecked():
            try:
                frames,_errors=load_folder(folder)
                metadata_rois={frame.roi for frame in frames if frame.roi is not None}
            except Exception as exc:
                QMessageBox.warning(self,tr("camera.linearity.preflight_failed"),str(exc)); return
            if not frames or len(metadata_rois)!=1:
                QMessageBox.warning(self,tr("camera.linearity.roi_confirmation_required"),tr("camera.linearity.roi_confirmation_message")); return
        worker=AnalyzeRequest(folder,self.criteria,roi,self.full_frame_confirm.isChecked()); thread=QThread(self); worker.moveToThread(thread); thread.started.connect(worker.run); worker.finished.connect(self._analysis_finished); worker.finished.connect(thread.quit); worker.finished.connect(worker.deleteLater); thread.finished.connect(self._thread_finished); thread.finished.connect(thread.deleteLater); self._thread=thread; self._worker=worker; self._set_busy(True); thread.start()

    @Slot(object)
    def _analysis_finished(self,payload:object)->None:
        outcome,error=payload
        if error: QMessageBox.critical(self,tr("camera.linearity.analysis_failed"),str(error)); self.preflight_text.setPlainText(str(error))
        else: self.preflight_text.setPlainText(json.dumps(outcome.preflight.to_dict(),ensure_ascii=False,indent=2)); self._show_outcome(outcome)

    def _show_outcome(self,outcome:Any)->None:
        self.results_text.setPlainText(json.dumps(outcome.summary,ensure_ascii=False,indent=2)); self.results_folder.setText(str(outcome.output_dir or ""))

    def _set_busy(self,busy:bool)->None:
        self.start_button.setEnabled(not busy); self.analyze_existing_button.setEnabled(not busy); self.stop_button.setEnabled(busy)

    def _choose_folder(self,target:QLineEdit)->None:
        value=QFileDialog.getExistingDirectory(self,tr("camera.linearity.select_folder_title"),target.text() or str(PROJECT_ROOT));
        if value: target.setText(value)

    def _choose_profile(self)->None:
        value,_=QFileDialog.getOpenFileName(self,tr("camera.linearity.select_profile_title"),str(PROJECT_ROOT),"JSON (*.json)");
        if value: self.profile_path.setText(value)

    def _apply_criteria(self)->None:
        try: self.criteria=QualificationCriteria.from_dict(json.loads(self.criteria_editor.toPlainText())); QMessageBox.information(self,tr("camera.linearity.criteria"),tr("camera.linearity.criteria_applied"))
        except Exception as exc: QMessageBox.warning(self,tr("camera.linearity.invalid_criteria"),str(exc))

    @Slot(int)
    def _mode_changed(self,_index:int)->None:
        mode=RunMode(self.mode.currentData())
        if mode is RunMode.FULL: self.light_repeats.setValue(5); self.dark_repeats.setValue(5); self.gains.setText(", ".join(map(str,FULL_GAINS))); self.exposures.setEnabled(True)
        elif mode is RunMode.PILOT: self.light_repeats.setValue(3); self.dark_repeats.setValue(0); self.gains.setText(tr("camera.linearity.gain_100")); self.exposures.setEnabled(True)
        else: self.light_repeats.setValue(3); self.dark_repeats.setValue(3); self.gains.setText(tr("camera.linearity.gain_100")); self.exposures.setEnabled(False)

    def closeEvent(self,event:QCloseEvent)->None:
        if self._thread is not None:
            if not self._close_when_idle:
                answer=QMessageBox.question(self,tr("camera.linearity.safe_stop"),tr("camera.linearity.safe_stop_question"))
                if answer!=QMessageBox.StandardButton.Yes: event.ignore(); return
                self._close_when_idle=True; self._cancel.set()
            event.ignore(); return
        self.temperature_timer.stop(); self.controller.close_camera(); logging.getLogger().removeHandler(self._log_handler); event.accept()


def _spin(minimum:int,maximum:int,value:int)->QSpinBox:
    box=QSpinBox(); box.setRange(minimum,maximum); box.setValue(value); return box


def _numbers(text:str,kind:Any)->tuple[Any,...]:
    values=tuple(kind(item.strip()) for item in text.split(",") if item.strip());
    if not values: raise ValueError("List cannot be empty")
    return values


def _parse_roi(text:str)->ROI|None:
    if not text.strip(): return None
    values=_numbers(text,int)
    if len(values)!=4: raise ValueError("ROI must be x,y,width,height")
    return ROI(*values)


def _duration(seconds:float|None)->str:
    if seconds is None: return "—"
    seconds=max(0,int(seconds)); hours,remainder=divmod(seconds,3600); minutes,seconds=divmod(remainder,60); return f"{hours:02d}:{minutes:02d}:{seconds:02d}"
