from __future__ import annotations
from datetime import datetime
import json
from pathlib import Path
from threading import Event
from time import monotonic
import math
import numpy as np
from PySide6.QtCore import QObject, QThread, Signal, Slot, Qt, QTimer
from PySide6.QtSerialPort import QSerialPortInfo
from PySide6.QtWidgets import QCheckBox, QComboBox, QDialog, QDoubleSpinBox, QFileDialog, QFormLayout, QHBoxLayout, QLabel, QLineEdit, QMessageBox, QPushButton, QSpinBox, QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget, QProgressBar, QScrollArea
from tools.camera_linearity_qualification.window import CameraLinearityQualificationWindow
from tools.gsp4h_controller.controller import LightController
from tools.gsp4h_controller.serial_transport import QtSerialTransport
from .analysis import write_report
from .calibration import LightCalibration
from .capture import LightCaptureRunner, VerifiedCameraAdapter
from .plan import LightPlan, Retention
from .messages import msg
from .paths import DATA_ROOT, LEGACY_DATA_ROOT
from .automatic import AutomaticCaptureRunner, AutomaticSettings, REQUESTED_GAINS
from .lux_reference import attach_lux
from .lux_dialog import LuxDialog

class CaptureProgressDialog(QDialog):
    stop_requested = Signal()

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle(msg('線性度測試進度', 'Linearity test progress'))
        self.setWindowModality(Qt.WindowModality.ApplicationModal)
        self.resize(570, 300)
        layout = QVBoxLayout(self)
        self.condition = QLabel(msg('準備測試／等待相機暖機', 'Preparing / waiting for camera warmup'))
        self.condition.setWordWrap(True)
        self.count = QLabel(msg('0 張', '0 frames'))
        self.bar = QProgressBar()
        self.bar.setRange(0, 0)
        self.elapsed = QLabel()
        self.remaining = QLabel(msg('剩餘時間：正在估算', 'Remaining time: estimating'))
        self.wait_label = QLabel()
        self.wait_label.setWordWrap(True)
        self.stop = QPushButton(msg('安全停止（等待目前相機操作完成後關燈）', 'Stop safely (turn off light after the current camera operation)'))
        self.stop.clicked.connect(self.request_stop)
        for widget in (self.condition, self.count, self.bar, self.elapsed, self.remaining, self.wait_label, self.stop):
            layout.addWidget(widget)
        self.started = monotonic()
        self.last_frame_started = self.started
        self.timer = QTimer(self)
        self.timer.setInterval(500)
        self.timer.timeout.connect(self.tick)
        self.timer.start()
        self.tick()

    def tick(self) -> None:
        self.elapsed.setText(msg(f'已經過 {monotonic() - self.started:.1f} 秒；介面每 0.5 秒更新', f'Elapsed {monotonic() - self.started:.1f} s; display updates every 0.5 s'))
        self.wait_label.setText(msg(f'目前等待 {monotonic() - self.last_frame_started:.1f} 秒（曝光、讀出、通訊或存檔中）', f'Waiting {monotonic() - self.last_frame_started:.1f} s (exposure, readout, communication or saving)'))

    def request_stop(self) -> None:
        self.stop.setEnabled(False)
        self.condition.setText(msg('已要求安全停止；等待目前操作返回後驗證關燈', 'Safe stop requested; waiting to verify light OFF'))
        self.stop_requested.emit()

    def reject(self) -> None:
        self.request_stop()

    def closeEvent(self, event) -> None:
        self.request_stop()
        event.ignore()

class DeviceWorker(QObject):
    completed = Signal(object)
    progress = Signal(object)
    trace = Signal(str)

    def __init__(self, cancel: Event, make_transport=QtSerialTransport) -> None:
        super().__init__()
        self.cancel = cancel
        self.make_transport = make_transport
        self.light = None

    @Slot(object)
    def execute(self, request: dict) -> None:
        result = {'operation': request['operation'], 'error': '', 'session': None, 'summary': None}
        try:
            operation = request['operation']
            if operation == 'analyze':
                result['summary'] = write_report(request['session'])
                result['session'] = request['session']
            else:
                if self.light is None:
                    transport = self.make_transport()
                    if isinstance(transport, QtSerialTransport):
                        transport.serial.setParent(self)
                    self.light = LightController(transport, lambda kind, message: self.trace.emit(f'{kind}: {message}'))
                if operation == 'connect':
                    self.light.connect(request['port'], request['parity'])
                elif operation == 'apply':
                    if request.get('guided'):
                        self.light.safe_off()
                    values = [0] * 4
                    values[request['channel'] - 1] = request['level']
                    if request['level']:

                        def check():
                            if self.cancel.is_set():
                                raise RuntimeError(msg('已取消點燈', 'Light enable cancelled'))
                        self.light.enable(values, check)
                    else:
                        self.light.safe_off()
                    if request.get('guided'):
                        delay = float(request.get('settle_s', 1.))
                        if not math.isfinite(delay) or not 0 <= delay <= 3600:
                            raise ValueError('Invalid guided settling delay')
                        if self.cancel.wait(delay):
                            raise RuntimeError(msg('LUX 量測切光已取消', 'Guided LUX switching cancelled'))
                        state = self.light.refresh()
                        if state.mode != ('H' if request['level'] else 'L') or state.brightness != tuple(values):
                            raise RuntimeError(msg('穩定等待後 PWM 讀回不符', 'PWM readback mismatch after settling'))
                elif operation == 'off':
                    self.light.safe_off()
                elif operation == 'disconnect':
                    self.light.disconnect()
                elif operation == 'capture':
                    runner = request['runner']
                    runner.light = self.light
                    runner.progress = self.progress.emit
                    session = runner.run()
                    result['session'] = str(session)
                    self.progress.emit({'message': msg('拍攝已結束；正在檢查影像與產生數值報告', 'Capture ended; checking images and generating reports')})
                    result['summary'] = write_report(session)
                    if result['summary']['run_phase'] != 'COMPLETE':
                        manifest = json.loads((session / 'SUMMARY' / 'capture_manifest.json').read_text(encoding='utf-8'))
                        result['error'] = f"{manifest['phase']}: {manifest['error'] or ''} {'; '.join(manifest['cleanup_errors'])}"
                elif operation == 'attach_lux':
                    self.light.safe_off()
                    attach_lux(request['session'], request['calibration'], reproducibility_confirmed=True)
                    result['session'] = request['session']
                    result['summary'] = write_report(request['session'])
                else:
                    raise ValueError(msg('不支援的操作', 'Unsupported operation'))
        except Exception as exc:
            result['error'] = str(exc)
            if result['operation'] in ('apply', 'capture', 'attach_lux') and self.light is not None:
                try:
                    self.light.safe_off()
                except Exception as cleanup:
                    result['error'] += msg(f'；關燈未驗證：{cleanup}', f'; light OFF not verified: {cleanup}')
        result['state'] = self.light.state if self.light is not None else None
        self.completed.emit(result)

class LightLinearityWindow(CameraLinearityQualificationWindow):
    request = Signal(object)

    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle(msg('GSP-4H 光源／相機線性度驗證 — 手動光強參考', 'GSP-4H light / camera linearity — manually measured illumination'))
        self.profiles = {channel: LightCalibration(channel=channel, unit='lux') for channel in range(1, 5)}
        self.profile_dir = DATA_ROOT / 'calibrations'
        for channel in self.profiles:
            path = self.profile_dir / f'CH{channel}.json'
            if not path.exists():
                path = LEGACY_DATA_ROOT / 'calibrations' / f'CH{channel}.json'
            if path.exists():
                try:
                    profile = LightCalibration.load(path)
                    if profile.channel != channel:
                        raise ValueError(msg('保存的通道不一致', 'Saved channel does not match'))
                    self.profiles[channel] = profile
                except Exception as exc:
                    self.log_message.emit(msg(f'CH{channel} 光強表載入失敗：{exc}', f'CH{channel} illumination table load failed: {exc}'))
        self.active_channel = 1
        self.job_busy = False
        self.closing = False
        self.light_ready = False
        self.light_connected = False
        self.lux_dialog = None
        self.meter_off_pending = False
        self.mode.blockSignals(True)
        self.mode.removeItem(2)
        self.mode.blockSignals(False)
        self.gains.setText(', '.join(map(str, REQUESTED_GAINS)))
        self.dark_repeats.setMinimum(1)
        self.light_repeats.setMaximum(100)
        self.dark_repeats.setMaximum(100)
        self.output_path.setText(str(DATA_ROOT / 'runs'))
        self.adaptive_stop.setText(msg('接近飽和時跳過同 PWM／Gain 的更長曝光', 'Skip longer exposures for the same PWM / Gain near saturation'))
        self.warmup.setToolTip(msg('拍攝前相機等待時間；光源穩定等待另設於光源頁面', 'Camera warmup delay; light settling is configured on the light tab'))
        self.profile_path.setEnabled(False)
        self._browse_profile.setEnabled(False)
        self.criteria_editor.setReadOnly(True)
        self.existing_roi.setEnabled(False)
        self.full_frame_confirm.setEnabled(False)
        self.existing_roi.setPlaceholderText(msg('新工具重讀當次保存的數值統計，不重新選 ROI', 'Read saved statistics; ROI cannot be changed for this operation'))
        self.apply_criteria.setEnabled(False)
        self.criteria_editor.setPlainText(msg('新工具的回歸門檻固定並保存於每次測試 SUMMARY/measurement_snapshot.json。\nR² ≥ 0.999，最大相對殘差 ≤ 2%，CV／時間條紋 ≤ 2%，SNR ≥ 5，至少 5 點。\n本工具不讀取舊版 camera-only profile。', 'Regression thresholds are saved in SUMMARY/measurement_snapshot.json.\nR² >= 0.999, maximum relative residual <= 2%, CV / temporal bands <= 2%, SNR >= 5, at least 5 points.\nOld camera-only profiles are not used.'))
        self._add_source_tab()
        self._load_editor(self.profiles[1])
        self.device_worker = DeviceWorker(self._cancel)
        self.device_thread = QThread(self)
        self.device_worker.moveToThread(self.device_thread)
        self.request.connect(self.device_worker.execute)
        self.device_worker.completed.connect(self._device_completed)
        self.device_worker.progress.connect(self._capture_progress)
        self.device_worker.trace.connect(self.log_message.emit)
        self.device_thread.finished.connect(self.device_worker.deleteLater)
        self.device_thread.finished.connect(self._devices_finished)
        self.device_thread.start()
        self.progress_dialog = None
        self._set_busy(False)

    def _add_source_tab(self) -> None:
        tabs = self.centralWidget()
        page = QWidget()
        layout = QVBoxLayout(page)
        info = QLabel(msg('手動光強表：各通道分開保存；留空表示未量測，不插值。\n實測相對值 = (讀值－背景) / (參考等級讀值－背景)。請維持相同單位、位置、距離與光源條件。\n數值與報告存 SUMMARY；影像存 IMAGES。PWM 頻率未知時留空，軟體不宣稱硬體同步。', 'Measured illumination: separate tables per channel; blanks remain unmeasured, without interpolation.\nRelative intensity = (reading - background) / (reference reading - background). Keep units, position, distance and source conditions fixed.\nStatistics / reports: SUMMARY; images: IMAGES. Leave unknown PWM frequency blank. Hardware synchronization is not verified.'))
        info.setWordWrap(True)
        self.source_help = info
        self.manual_source_help = info.text()
        layout.addWidget(info)
        form = QFormLayout()
        self.source_form = form
        self.automatic_mode = QCheckBox(msg('一鍵自動檢測：Gain 指定集合全測，PWM／曝光自動規劃，拍完補 LUX',
                                            'Automatic: test requested Gains, plan PWM/exposure, fill LUX after capture'))
        self.automatic_mode.setChecked(True)
        form.addRow(self.automatic_mode)
        self.port = QComboBox()
        self.port.setEditable(True)
        self.port.addItems([item.portName() for item in QSerialPortInfo.availablePorts()])
        if self.port.count() == 0:
            self.port.setEditText('COM6')
        self.parity = QComboBox()
        self.parity.addItem(msg('無', 'None'), 'none')
        self.parity.addItem(msg('偶', 'Even'), 'even')
        self.parity.addItem(msg('奇', 'Odd'), 'odd')
        self.source_status = QLabel(msg('未連線；連線不自動點燈', 'Disconnected; connecting does not enable light'))
        buttons = QWidget()
        row = QHBoxLayout(buttons)
        self.source_connect = QPushButton(msg('連線 GSP-4H', 'Connect GSP-4H'))
        self.source_off = QPushButton(msg('安全關燈', 'Turn off safely'))
        self.source_disconnect = QPushButton(msg('安全斷線', 'Disconnect safely'))
        for button in (self.source_connect, self.source_off, self.source_disconnect):
            row.addWidget(button)
        self.channel = QComboBox()
        for i in range(1, 5):
            self.channel.addItem(msg(f'CH{i}', f'CH{i}'), i)
        self.manual_level = QSpinBox()
        self.manual_level.setRange(0, 255)
        self.manual_apply = QPushButton(msg('套用此等級供光強計量測（其他通道歸零）', 'Apply level for meter measurement (other channels set to zero)'))
        self.name = QLineEdit()
        self.unit = QLineEdit('lux')
        self.meter = QLineEdit()
        self.geometry = QLineEdit()
        self.measured_at = QLineEdit()
        self.notes = QLineEdit()
        self.reference = QSpinBox()
        self.reference.setRange(1, 255)
        self.reference.setValue(255)
        self.background = QLineEdit('0')
        self.levels = QLineEdit('16,32,64,96,128,160,192,255')
        self.frequency = QLineEdit()
        self.frequency.setPlaceholderText(msg('Hz；未知留空，填寫不會改變硬體頻率', 'Hz; leave unknown blank; this does not change hardware frequency'))
        self.settle_seconds = QDoubleSpinBox()
        self.settle_seconds.setRange(0, 3600)
        self.settle_seconds.setValue(1)
        self.measured_required = QCheckBox(msg('測試前要求每個 PWM 等級都有有效實測光強', 'Require valid measured illumination for every tested PWM level'))
        self.measured_required.setChecked(True)
        self.retention = QComboBox()
        self.retention.addItem(msg('全部完整原始影像＋數值摘要', 'All full RAW images + statistics'), Retention.FULL.value)
        self.retention.addItem(msg('每條件首張全幅＋其餘原始 ROI＋摘要', 'First full frame per condition + remaining RAW ROI frames + statistics'), Retention.ROI.value)
        self.retention.addItem(msg('僅數值摘要（不保留影像，無法重算 ROI）', 'Statistics only (no images; ROI cannot be recalculated)'), Retention.SUMMARY.value)
        self.estimate_button = QPushButton(msg('估算空間與測試時間', 'Estimate storage and duration'))
        self.estimate_label = QLabel(msg('連接相機後可依解析度與 ROI 估算；包含每張的丟棄幀時間', 'Connect camera to estimate from resolution / ROI, including discarded frames'))
        self.estimate_label.setWordWrap(True)
        for title, widget in (('PORT', self.port), ('Parity', self.parity), (msg('通訊', 'Connection'), buttons), (msg('設備讀回', 'Device readback'), self.source_status), (msg('光源通道', 'Light channel'), self.channel), (msg('手動量測 PWM', 'PWM for manual measurement'), self.manual_level), ('', self.manual_apply), (msg('光源名稱／顏色', 'Source name / color'), self.name), (msg('光強計單位', 'Meter unit'), self.unit), (msg('光強計型號／識別', 'Meter model / identity'), self.meter), (msg('位置／距離／光學條件', 'Position / distance / optics'), self.geometry), (msg('量測日期', 'Measurement date'), self.measured_at), (msg('備註', 'Notes'), self.notes), (msg('正規化參考等級', 'Normalization reference level'), self.reference), (msg('背景／零點讀值', 'Background / zero reading'), self.background), (msg('測試 PWM 列表', 'Test PWM levels'), self.levels), (msg('PWM 頻率', 'PWM frequency'), self.frequency), (msg('每次切光後穩定秒數', 'Settling seconds after light switching'), self.settle_seconds), ('', self.measured_required), (msg('保存模式', 'Retention mode'), self.retention), ('', self.estimate_button), (msg('預估', 'Estimate'), self.estimate_label)):
            form.addRow(title, widget)
        layout.addLayout(form)
        self.table = QTableWidget(256, 3)
        self.table.setHorizontalHeaderLabels([msg('PWM 等級', 'PWM level'), msg('手動實測光強', 'Measured illumination'), msg('相對強度（參考=1）', 'Relative intensity (reference=1)')])
        for level in range(256):
            for column, text in ((0, str(level)), (1, ''), (2, msg('未量測', 'Unmeasured'))):
                item = QTableWidgetItem(text)
                if column != 1:
                    item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsEditable)
                self.table.setItem(level, column, item)
        self.table.horizontalHeader().setStretchLastSection(True)
        layout.addWidget(self.table, 1)
        file_buttons = QHBoxLayout()
        self.save_table = QPushButton(msg('保存光強表 JSON', 'Save illumination table JSON'))
        self.load_table = QPushButton(msg('載入光強表 JSON', 'Load illumination table JSON'))
        self.import_csv = QPushButton(msg('匯入 CSV', 'Import CSV'))
        self.export_csv = QPushButton(msg('匯出 0～255 CSV', 'Export 0-255 CSV'))
        for button in (self.save_table, self.load_table, self.import_csv, self.export_csv):
            file_buttons.addWidget(button)
        layout.addLayout(file_buttons)
        layout.addStretch(1)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setWidget(page)
        self.table.setMinimumHeight(320)
        tabs.insertTab(1, scroll, msg('GSP-4H／手動光強表', 'GSP-4H / measured illumination'))
        self.source_page = page
        self.source_connect.clicked.connect(lambda: self._dispatch({'operation': 'connect', 'port': self.port.currentText(), 'parity': self.parity.currentData()}))
        self.source_off.clicked.connect(lambda: self._dispatch({'operation': 'off'}))
        self.source_disconnect.clicked.connect(lambda: self._dispatch({'operation': 'disconnect'}))
        self.manual_apply.clicked.connect(lambda: self._dispatch({'operation': 'apply', 'channel': self.active_channel, 'level': self.manual_level.value()}))
        self.channel.currentIndexChanged.connect(self._channel_changed)
        self.table.itemChanged.connect(self._refresh_relative)
        self.reference.valueChanged.connect(self._refresh_relative)
        self.background.editingFinished.connect(self._refresh_relative)
        self.estimate_button.clicked.connect(self.estimate)
        self.save_table.clicked.connect(lambda: self._file_action('save'))
        self.load_table.clicked.connect(lambda: self._file_action('load'))
        self.import_csv.clicked.connect(lambda: self._file_action('import'))
        self.export_csv.clicked.connect(lambda: self._file_action('export'))
        self.automatic_mode.toggled.connect(self._automatic_controls)

    def _automatic_controls(self, *_args):
        automatic = self.automatic_mode.isChecked()
        for widget in (self.levels, self.exposures, self.mode, self.measured_required, self.adaptive_stop):
            widget.setEnabled(not automatic and not self.job_busy)
        if automatic:
            self.mode.blockSignals(True)
            self.mode.setCurrentIndex(1)
            self.mode.blockSignals(False)
            self.light_repeats.setMinimum(5)
            self.dark_repeats.setMinimum(5)
        else:
            self.light_repeats.setMinimum(1)
            self.dark_repeats.setMinimum(1)
        self.start_button.setText(msg('一鍵自動檢測', 'Automatic qualification') if automatic else msg('開始固定矩陣測試', 'Start fixed matrix'))
        # The one-click flow does not present a pre-capture LUX table or manual
        # exposure/PWM lists. Keep them available in fixed-matrix mode.
        for widget in (self.levels, self.reference, self.background, self.unit, self.measured_at, self.measured_required):
            widget.setVisible(not automatic)
            caption = self.source_form.labelForField(widget)
            if caption:
                caption.setVisible(not automatic)
        self.table.setVisible(not automatic)
        for widget in (self.save_table, self.load_table, self.import_csv, self.export_csv):
            widget.setVisible(not automatic)
        for widget in (self.exposures, self.mode):
            widget.setVisible(not automatic)
            form = widget.parentWidget().layout()
            if isinstance(form, QFormLayout):
                caption = form.labelForField(widget)
                if caption:
                    caption.setVisible(not automatic)
        self.source_help.setText(msg('先連線、選通道與 ROI，再按一鍵自動檢測。\nGain 清單可在「拍攝＋分析」頁修改；預設 100、200、300、400、500、1000、2000、3000、5000%。PWM／曝光自動規劃，LUX 拍完再填。\n可先用手動 PWM 開燈暖機；頻率未知留空。數值摘要與影像分開保存。',
                                     'Connect, select channel and ROI, then start automatic qualification.\nEdit the Gain list on Capture + Analyze; defaults: 100, 200, 300, 400, 500, 1000, 2000, 3000, 5000%. PWM/exposure are planned automatically; fill LUX afterwards.\nManual PWM can warm up the source; leave unknown frequency blank. Statistics and images are stored separately.') if automatic else self.manual_source_help)

    def _read_editor(self) -> LightCalibration:
        profile = LightCalibration(channel=self.active_channel, source_name=self.name.text(), unit=self.unit.text(), meter=self.meter.text(), geometry=self.geometry.text(), measured_at=self.measured_at.text(), notes=self.notes.text(), reference_level=self.reference.value(), background=float(self.background.text()))
        profile.readings = {i: float(self.table.item(i, 1).text()) for i in range(256) if self.table.item(i, 1).text().strip()}
        profile.validate()
        return profile

    def _load_editor(self, profile: LightCalibration) -> None:
        self.table.blockSignals(True)
        self.reference.blockSignals(True)
        self.name.setText(profile.source_name)
        self.unit.setText(profile.unit)
        self.meter.setText(profile.meter)
        self.geometry.setText(profile.geometry)
        self.measured_at.setText(profile.measured_at or datetime.now().astimezone().isoformat(timespec='seconds'))
        self.notes.setText(profile.notes)
        self.reference.setValue(profile.reference_level)
        self.background.setText(f'{profile.background:g}')
        for level in range(256):
            self.table.item(level, 1).setText(str(profile.readings.get(level, '')))
        self.reference.blockSignals(False)
        self.table.blockSignals(False)
        self._refresh_relative()

    def _refresh_relative(self, *_args) -> None:
        self.table.blockSignals(True)
        try:
            profile = self._read_editor()
            for level in range(256):
                relative = profile.relative(level)
                text = msg('未量測／缺參考', 'Unmeasured / missing reference') if relative is None else f'{relative:.8g}'
                self.table.item(level, 2).setText(text)
        except (ValueError, TypeError):
            for level in range(256):
                self.table.item(level, 2).setText(msg('輸入無效', 'Invalid input'))
        finally:
            self.table.blockSignals(False)

    def _save_current(self) -> LightCalibration:
        profile = self._read_editor()
        profile.save(self.profile_dir / f'CH{profile.channel}.json')
        self.profiles[profile.channel] = profile
        return profile

    def _channel_changed(self, _index) -> None:
        new = self.channel.currentData()
        try:
            self._save_current()
        except Exception as exc:
            self.channel.blockSignals(True)
            self.channel.setCurrentIndex(self.active_channel - 1)
            self.channel.blockSignals(False)
            QMessageBox.warning(self, msg('光強表無效', 'Invalid illumination table'), str(exc))
            return
        self.active_channel = new
        self._load_editor(self.profiles[new])

    def _file_action(self, action: str) -> None:
        try:
            if action == 'load':
                path, _ = QFileDialog.getOpenFileName(self, msg('載入光強表', 'Load illumination table'), str(self.profile_dir), 'JSON (*.json)')
                if path:
                    profile = LightCalibration.load(path)
                    self._save_current()
                    self.active_channel = profile.channel
                    self.channel.blockSignals(True)
                    self.channel.setCurrentIndex(profile.channel - 1)
                    self.channel.blockSignals(False)
                    self.profiles[profile.channel] = profile
                    self._load_editor(profile)
                    self._save_current()
            else:
                profile = self._read_editor()
                if action == 'import':
                    path, _ = QFileDialog.getOpenFileName(self, msg('匯入實測光強', 'Import measured illumination'), '', 'CSV (*.csv)')
                    if path:
                        profile.import_csv(path)
                        self._load_editor(profile)
                        self._save_current()
                else:
                    extension = 'json' if action == 'save' else 'csv'
                    path, _ = QFileDialog.getSaveFileName(self, msg('匯出光強表', 'Export illumination table'), f'CH{profile.channel}.{extension}', f'{extension.upper()} (*.{extension})')
                    if path:
                        if action == 'save':
                            profile.save(path)
                        else:
                            profile.export_csv(path)
                        self._save_current()
        except Exception as exc:
            QMessageBox.warning(self, msg('光強表操作失敗', 'Illumination table operation failed'), str(exc))

    def _plan(self) -> LightPlan:

        def numbers(text, kind):
            return tuple((kind(x.strip()) for x in text.split(',') if x.strip()))
        automatic = self.automatic_mode.isChecked()
        plan = LightPlan(self.active_channel, (128,) if automatic else numbers(self.levels.text(), int),
                         numbers(self.gains.text(), int),
                         (200.,) if automatic else numbers(self.exposures.text(), float),
                         self.light_repeats.value(), self.dark_repeats.value(), self.settling.value(), self.settle_seconds.value(),
                         0.02, Retention(self.retention.currentData()), False if automatic else self.measured_required.isChecked(),
                         float(self.frequency.text()) if self.frequency.text().strip() else None, self.adaptive_stop.isChecked(), self.warmup.value())
        plan.validate()
        return plan

    def estimate(self) -> dict | None:
        try:
            if self.latest_scientific is None:
                raise ValueError(msg('請先連接相機取得實際解析度', 'Connect the camera to obtain actual resolution'))
            roi = self.live_view.roi
            height, width = np.asarray(self.latest_scientific).shape
            plan = self._plan()
            if self.automatic_mode.isChecked():
                from dataclasses import replace
                minimum_plan = replace(plan, levels=(1, 32, 64, 128, 255), exposures_ms=(50., 70.711, 100., 141.421, 200.))
                result = minimum_plan.estimate(width, height, roi.width if roi else width, roi.height if roi else height)
                self.estimate_label.setText(msg(f"自動規劃：{len(plan.gains)} 個 Gain，各組目標至少五個有效 PWM／曝光點。\n若採最低點數，正式影像至少 {result['light_frames'] + result['dark_frames']} 張，約 {result['estimated_bytes'] / 1e9:.2f} GB；實際會因預掃描、EV 跨度而增加，執行時持續更新。",
                                                 f"Automatic planning: {len(plan.gains)} Gains; aim for >=5 usable PWM/exposure points.\nAt the minimum point count, formal capture needs at least {result['light_frames'] + result['dark_frames']} frames, about {result['estimated_bytes'] / 1e9:.2f} GB; scouting and EV coverage add data. Progress updates during capture."))
                return result
            result = plan.estimate(width, height, roi.width if roi else width, roi.height if roi else height)
            seconds = result['minimum_seconds']
            self.estimate_label.setText(msg(f"Light {result['light_frames']}／Dark {result['dark_frames']} 張；約 {result['estimated_bytes'] / 1000000000.0:.2f} GB。\n曝光＋丟棄幀＋等待約 {seconds / 3600:.2f} 小時；實際另加讀出、通訊與存檔時間。提前停止可能減少。", f"Light {result['light_frames']} / Dark {result['dark_frames']} frames; about {result['estimated_bytes'] / 1000000000.0:.2f} GB.\nExposure + discarded frames + settling: {seconds / 3600:.2f} h; add readout, communication and saving. Early stopping may reduce this."))
            return result
        except Exception as exc:
            QMessageBox.warning(self, msg('無法估算', 'Cannot estimate'), str(exc))
            return None

    def _dispatch(self, request: dict) -> None:
        if self.job_busy:
            self._cancel.set()
            return
        self._cancel.clear()
        self.job_busy = True
        self._set_busy(True)
        if self.lux_dialog:
            self.lux_dialog.set_busy(True)
        if request['operation'] in ('capture', 'analyze', 'attach_lux'):
            self.progress_dialog = CaptureProgressDialog(self)
            self.progress_dialog.stop_requested.connect(self.stop_safely)
            if request['operation'] == 'analyze':
                self.progress_dialog.condition.setText(msg('驗證檔案／產生分析報告', 'Checking files / generating reports'))
                self.progress_dialog.stop.setEnabled(False)
            self.progress_dialog.show()
        self.request.emit(request)

    def _capture_progress(self, payload) -> None:
        if isinstance(payload, dict):
            if payload.get('indeterminate') and self.progress_dialog:
                self.progress_dialog.bar.setRange(0, 0)
            if 'message' in payload:
                self.run_labels['message'].setText(payload['message'])
                if self.progress_dialog:
                    self.progress_dialog.condition.setText(payload['message'])
                    self.progress_dialog.last_frame_started = monotonic()
                return
            text = msg(f"{payload['phase']} — {payload['condition']}\n第 {payload['repeat']}／{payload['repeats']} 張；曝光 {payload['exposure_ms']:g} ms", f"{payload['phase']} — {payload['condition']}\nFrame {payload['repeat']}/{payload['repeats']}; exposure {payload['exposure_ms']:g} ms")
            self.run_labels['condition'].setText(text)
            if self.progress_dialog:
                self.progress_dialog.condition.setText(text)
                self.progress_dialog.last_frame_started = monotonic()
        else:
            self._on_progress(payload)
            if self.progress_dialog:
                self.progress_dialog.bar.setRange(0, max(1, payload.total_frames))
                self.progress_dialog.bar.setValue(payload.completed_frames)
                self.progress_dialog.count.setText(msg(f'已保存／統計 {payload.completed_frames}／{payload.total_frames} 張', f'Saved / measured {payload.completed_frames}/{payload.total_frames} frames'))
                self.progress_dialog.remaining.setText(msg('自動選點中，總張數與剩餘時間尚未固定', 'Automatic planning: final frame count and ETA are not fixed') if payload.eta_s is None else msg(f'預估剩餘 {payload.eta_s / 60:.1f} 分鐘（依目前速度，隨條件更新）', f'Estimated remaining {payload.eta_s / 60:.1f} minutes (current rate; changes with conditions)'))

    def start_capture(self) -> None:
        if self.job_busy or not self.light_ready or (not self.controller.is_open) or (self.latest_scientific is None):
            QMessageBox.warning(self, msg('尚未就緒', 'Not ready'), msg('請連接相機及 GSP-4H，並確認 Scientific MONO16。', 'Connect camera and GSP-4H and verify Scientific MONO16.'))
            return
        try:
            automatic = self.automatic_mode.isChecked()
            profile = LightCalibration(channel=self.active_channel, unit='lux', source_name=self.name.text(), meter=self.meter.text(), geometry=self.geometry.text(), notes=self.notes.text()) if automatic else self._save_current()
            plan = self._plan()
            if plan.require_measured:
                profile.require_levels(plan.levels)
            roi = self.live_view.roi
            if roi is None:
                if QMessageBox.question(self, msg('ROI', 'ROI'), msg('使用全幅影像作為分析 ROI？', 'Use the full image as the analysis ROI?')) != QMessageBox.StandardButton.Yes:
                    return
                self.live_view.reset_full()
                roi = self.live_view.roi
            estimate = self.estimate()
            if estimate is None:
                return
            import shutil
            output = Path(self.output_path.text()).resolve()
            ancestor = output
            while not ancestor.exists():
                ancestor = ancestor.parent
            if shutil.disk_usage(ancestor).free < estimate['estimated_bytes']:
                raise ValueError(msg('可用硬碟空間低於預估需求；請改保存模式或縮小矩陣', 'Free disk space is below the estimate; change retention or reduce the matrix'))
            message = self.estimate_label.text() + (msg('\n\n請確認相機／光源已暖機，ROI 照明均勻且配置固定。程式會自動切光與試拍，最後引導量測 LUX。', '\n\nConfirm camera/source warmup, uniform ROI illumination and fixed optics. Automatic switching/scouting is followed by guided LUX measurement.') if automatic else msg('\n\n請確認光強表對應目前光源、量測位置與光學条件；光源已暖機且照明均勻。\n開始後將自動切換亮／暗並只啟用所選通道。', '\n\nConfirm the table matches the current source, meter position and optics, and that illumination is warmed up and uniform.\nThe test switches Light / Dark automatically and enables only the selected channel.'))
            if QMessageBox.question(self, msg('開始測試', 'Start test'), message) != QMessageBox.StandardButton.Yes:
                return
            original = dict(self.controller.capture_metadata())
            adapter = VerifiedCameraAdapter(self.bridge, self.controller, original)
            runner_type = AutomaticCaptureRunner if automatic else LightCaptureRunner
            runner = runner_type(adapter, None, plan, profile, output, roi, cancel=self._cancel)
            self._dispatch({'operation': 'capture', 'runner': runner})
        except Exception as exc:
            QMessageBox.warning(self, msg('測試設定無效', 'Invalid test settings'), str(exc))

    def analyze_existing(self) -> None:
        if not self.job_busy:
            self._dispatch({'operation': 'analyze', 'session': self.existing_path.text()})

    def _mode_changed(self, _index) -> None:
        pilot = self.mode.currentIndex() == 0
        self.light_repeats.setValue(3 if pilot else 5)
        self.dark_repeats.setValue(3 if pilot else 5)
        self.exposures.setEnabled(True)

    def _set_busy(self, busy: bool) -> None:
        super()._set_busy(busy)
        self.stop_button.setEnabled(busy)
        if not hasattr(self, 'source_page'):
            return
        for widget in (self.source_page, self.gains, self.exposures, self.mode, self.retention, self.output_path, self.light_repeats, self.dark_repeats, self.settling, self.warmup, self.roi_reset, self.live_view, self.adaptive_stop, self._browse_output):
            widget.setEnabled(not busy)
        self.source_connect.setEnabled(not busy and (not self.light_connected))
        self.source_off.setEnabled(not busy and self.light_connected)
        self.source_disconnect.setEnabled(not busy and self.light_connected)
        self.manual_apply.setEnabled(not busy and self.light_ready)
        self.start_button.setEnabled(not busy and self.light_ready)
        self.refresh_button.setEnabled(not busy)
        self.connect_button.setEnabled(not busy and (not self.controller.is_open) and bool(self.devices))
        self.disconnect_button.setEnabled(not busy and self.controller.is_open)
        self._automatic_controls()

    def _device_completed(self, result: dict) -> None:
        self.job_busy = False
        if self.progress_dialog:
            self.progress_dialog.timer.stop()
            self.progress_dialog.hide()
            self.progress_dialog.deleteLater()
            self.progress_dialog = None
        state = result['state']
        self.light_connected = bool(state and state.shutdown_required)
        self.light_ready = bool(state and state.ready)
        self.source_status.setText(msg(f'最近設備讀回：mode={state.mode}, CH1～4={state.brightness}', f'Latest device readback: mode={state.mode}, CH1-4={state.brightness}') if state else msg('未連線', 'Disconnected'))
        self._set_busy(False)
        if self.lux_dialog:
            self.lux_dialog.set_busy(False)
            self.lux_dialog.show_readback(state, result['error'], result['operation'])
            if result['operation'] == 'attach_lux':
                self.lux_dialog.saving = False
                if not result['error']:
                    self.lux_dialog.accept()
                    self.lux_dialog.deleteLater()
                    self.lux_dialog = None
        if result['session']:
            self.results_folder.setText(str(Path(result['session']) / 'SUMMARY'))
        if result['summary']:
            self.results_text.setPlainText(json.dumps(result['summary'], ensure_ascii=False, indent=2))
            self.preflight_text.setPlainText(msg('使用該次測試保存的光強表及數值摘要重新產生報告；不套用目前編輯中的表格。', "Reports use that run's saved illumination table and statistics, without applying the currently edited table."))
        if result['error']:
            self.closing = False
            QMessageBox.warning(self, msg('操作未完成', 'Operation incomplete'), result['error'])
            if self.meter_off_pending:
                self.meter_off_pending = False
                if self.light_connected:
                    self._dispatch({'operation': 'off'})
        elif self.closing:
            if result['operation'] == 'disconnect':
                self.device_thread.quit()
            else:
                self._dispatch({'operation': 'disconnect'})
        elif self.meter_off_pending:
            self.meter_off_pending = False
            if self.light_connected:
                self._dispatch({'operation': 'off'})
        elif result['operation'] in ('capture', 'analyze') and result['summary'] and result['summary'].get('analysis_state') == 'AWAITING_LUX' and result['summary']['run_phase'] == 'COMPLETE':
            self._open_lux(result['session'])

    def _open_lux(self, session):
        if self.lux_dialog is not None:
            return
        if not self.light_ready:
            QMessageBox.information(self, msg('LUX 尚待補填', 'LUX measurement pending'),
                                   msg('請連接 GSP-4H 後再次分析此資料夾，即可開啟引導量測。拍攝資料已保存。',
                                       'Connect GSP-4H and analyze this folder again to open guided measurement. Capture data is saved.'))
            return
        self.lux_dialog = LuxDialog(session, self)
        dialog = self.lux_dialog
        self.lux_dialog.apply_requested.connect(lambda channel, level: self._dispatch({'operation': 'apply', 'channel': channel, 'level': level, 'guided': True, 'settle_s': dialog.settle_s}))
        self.lux_dialog.reference_ready.connect(lambda calibration: self._dispatch({'operation': 'attach_lux', 'session': str(session), 'calibration': calibration}))
        self.lux_dialog.off_requested.connect(self._close_lux)
        self.lux_dialog.show()
        QTimer.singleShot(0, dialog.start)

    def _close_lux(self):
        dialog = self.lux_dialog
        self.lux_dialog = None
        if dialog:
            dialog.deleteLater()
        if self.job_busy:
            self._cancel.set()
            self.meter_off_pending = True
        elif self.light_connected:
            self._dispatch({'operation': 'off'})

    def emergency_close(self) -> None:
        self._cancel.set()
        self.controller.close_camera()
        self.run_labels['message'].setText(msg('已停止相機；光源於 worker 下一安全邊界關閉，等待關燈讀回。', 'Camera stopped; waiting for the light worker to turn off and verify readback.'))
        if not self.job_busy and self.light_connected:
            self._dispatch({'operation': 'off'})

    def _devices_finished(self) -> None:
        if self.closing:
            QTimer.singleShot(0, self.close)

    def closeEvent(self, event) -> None:
        if self.device_thread.isRunning():
            event.ignore()
            if self.closing:
                return
            try:
                self._save_current()
            except Exception as exc:
                QMessageBox.warning(self, msg('光強表尚未保存', 'Illumination table not saved'), str(exc))
                return
            if self.job_busy:
                if QMessageBox.question(self, msg('停止測試', 'Stop test'), msg('安全停止目前操作並關燈後退出？', 'Stop safely, turn off the light and exit?')) != QMessageBox.StandardButton.Yes:
                    return
                self.closing = True
                self._cancel.set()
            else:
                self.closing = True
                self._dispatch({'operation': 'disconnect'})
            return
        super().closeEvent(event)
