from __future__ import annotations

"""Folder-based standalone UI. All inventory and fusion work runs off the UI thread."""

from datetime import datetime, timedelta
from pathlib import Path
from threading import Event
from time import monotonic

from PySide6.QtCore import QThread, QTimer, Qt, QUrl, Signal
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (
    QAbstractItemView, QDoubleSpinBox, QFileDialog, QFormLayout, QHBoxLayout,
    QHeaderView, QLabel, QLineEdit, QMainWindow, QMessageBox, QProgressBar,
    QPushButton, QTableWidget, QTableWidgetItem, QTextEdit, QVBoxLayout, QWidget,
)

from .batch import generate_batch
from .messages import msg, phase_text, problem_text, status_text
from .processing import DisplaySettings
from .scan import Cancelled, Inventory, scan_folder


class Worker(QThread):
    progress = Signal(object)
    result = Signal(object)

    def __init__(self, operation: str, arguments: dict, parent=None):
        super().__init__(parent)
        self.operation, self.arguments = operation, arguments
        self.cancel = Event()

    def check_cancel(self):
        if self.cancel.is_set():
            raise Cancelled()

    def run(self):
        try:
            function = scan_folder if self.operation == "scan" else generate_batch
            value = function(**self.arguments, check_cancel=self.check_cancel, progress=self.progress.emit)
            self.result.emit({"operation": self.operation, "value": value})
        except Cancelled:
            self.result.emit({"operation": self.operation, "cancelled": True})
        except Exception as exc:
            self.result.emit({"operation": self.operation, "error": f"{type(exc).__name__}: {exc}"})


def duration(seconds: float) -> str:
    value = max(0, int(seconds))
    return f"{value // 3600:02d}:{value // 60 % 60:02d}:{value % 60:02d}"


class HDRViewerWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle(msg("批次 HDR 生成 — 僅供觀看", "Batch HDR Generator — Viewing Only"))
        self.resize(1160, 780)
        self.inventory: Inventory | None = None
        self.worker: Worker | None = None
        self.last_output: Path | None = None
        self._closing = False
        self._started = 0.0
        self._last_progress: dict = {}
        self._last_progress_at = 0.0
        self._pending_result: dict | None = None
        content = QWidget()
        self.setCentralWidget(content)
        layout = QVBoxLayout(content)
        notice = QLabel(msg(
            "選擇原始 EL TIFF 資料夾：自動掃描子資料夾，按批次／樣品／通道／電流密度／Gain 分組。\n"
            "僅供觀看：假設線性、未套用校正。各組預覽獨立調整亮度，不可用於 EL 定量比較。",
            "Select original EL TIFF folder: subfolders are grouped by run / sample / channel / current density / Gain.\n"
            "Viewing only: assumed linear response, no calibration. Previews scale each group independently; not for quantitative EL comparison."))
        notice.setWordWrap(True)
        layout.addWidget(notice)
        self.input_path, self.output_path = QLineEdit(), QLineEdit()
        self.input_path.setReadOnly(True)
        self.output_path.setReadOnly(True)
        self.choose_input = QPushButton(msg("選取照片資料夾", "Choose Capture Folder"))
        self.choose_output = QPushButton(msg("選取輸出位置", "Choose Output Location"))
        self.scan_button = QPushButton(msg("重新掃描", "Rescan"))
        self.choose_input.clicked.connect(self.pick_input)
        self.choose_output.clicked.connect(self.pick_output)
        self.scan_button.clicked.connect(self.scan)
        for edit, buttons in ((self.input_path, (self.choose_input, self.scan_button)),
                              (self.output_path, (self.choose_output,))):
            row = QHBoxLayout()
            row.addWidget(edit, 1)
            for button in buttons:
                row.addWidget(button)
            layout.addLayout(row)
        self.table = QTableWidget(0, 9)
        self.table.setHorizontalHeaderLabels([
            msg("生成", "Select"), msg("批次", "Run"), msg("樣品", "Sample"), msg("通道", "Channel"),
            msg("J (mA/cm²)", "J (mA/cm²)"), msg("增益 (%)", "Gain (%)"), msg("曝光 (ms)", "Exposure (ms)"),
            msg("原圖張數", "Frames"), msg("狀態", "Status")])
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)
        self.table.horizontalHeader().setStretchLastSection(True)
        layout.addWidget(self.table, 1)
        actions = QHBoxLayout()
        self.select_all = QPushButton(msg("全選有效組", "Select Eligible Groups"))
        self.select_none = QPushButton(msg("清除選取", "Clear Selection"))
        self.select_all.clicked.connect(lambda: self.set_selection(True))
        self.select_none.clicked.connect(lambda: self.set_selection(False))
        actions.addWidget(self.select_all)
        actions.addWidget(self.select_none)
        actions.addStretch()
        self.gamma, self.compression = QDoubleSpinBox(), QDoubleSpinBox()
        self.gamma.setRange(.1, 10)
        self.gamma.setValue(2.2)
        self.compression.setRange(1, 10000)
        self.compression.setValue(100)
        actions.addWidget(QLabel(msg("觀看 Gamma", "Display Gamma")))
        actions.addWidget(self.gamma)
        actions.addWidget(QLabel(msg("亮度壓縮", "Compression")))
        actions.addWidget(self.compression)
        layout.addLayout(actions)
        self.phase, self.group_label = QLabel(), QLabel()
        self.phase.setWordWrap(True)
        self.group_label.setWordWrap(True)
        layout.addWidget(self.phase)
        layout.addWidget(self.group_label)
        self.progress_bar = QProgressBar()
        self.progress_bar.setRange(0, 1000)
        layout.addWidget(self.progress_bar)
        form = QFormLayout()
        self.elapsed, self.remaining, self.finish_time = QLabel("—"), QLabel("—"), QLabel("—")
        form.addRow(msg("已用時間", "Elapsed"), self.elapsed)
        form.addRow(msg("預估剩餘時間", "Estimated Remaining"), self.remaining)
        form.addRow(msg("預估完成時間", "Estimated Finish"), self.finish_time)
        layout.addLayout(form)
        self.log = QTextEdit()
        self.log.setReadOnly(True)
        self.log.setMaximumHeight(130)
        layout.addWidget(self.log)
        bottom = QHBoxLayout()
        self.generate_button = QPushButton(msg("生成所選 HDR", "Generate Selected HDR"))
        self.cancel_button = QPushButton(msg("取消", "Cancel"))
        self.open_output = QPushButton(msg("開啟結果資料夾", "Open Result Folder"))
        self.generate_button.clicked.connect(self.generate)
        self.cancel_button.clicked.connect(self.request_cancel)
        self.open_output.clicked.connect(self.show_output)
        for button in (self.generate_button, self.cancel_button, self.open_output):
            bottom.addWidget(button)
        layout.addLayout(bottom)
        self.timer = QTimer(self)
        self.timer.setInterval(500)
        self.timer.timeout.connect(self.tick)
        self.set_busy(False)

    def set_busy(self, busy: bool):
        for widget in (self.choose_input, self.choose_output, self.scan_button, self.table,
                       self.select_all, self.select_none, self.gamma, self.compression):
            widget.setEnabled(not busy)
        self.generate_button.setEnabled(not busy and self.inventory is not None)
        self.cancel_button.setEnabled(busy)
        self.open_output.setEnabled(not busy and self.last_output is not None)

    def pick_input(self):
        path = QFileDialog.getExistingDirectory(self, msg("選擇原始照片資料夾", "Select Original Capture Folder"), self.input_path.text())
        if path:
            self.input_path.setText(path)
            if not self.output_path.text():
                self.output_path.setText(path)
            self.scan()

    def pick_output(self):
        path = QFileDialog.getExistingDirectory(self, msg("選擇輸出位置", "Select Output Location"), self.output_path.text())
        if path:
            self.output_path.setText(path)

    def start_worker(self, operation: str, arguments: dict):
        if self.worker is not None:
            return
        self._pending_result = None
        self._started = monotonic()
        self._last_progress = {}
        self._last_progress_at = self._started
        self.set_busy(True)
        self.progress_bar.setRange(0, 0)
        self.group_label.clear()
        self.phase.setText(msg("正在掃描…", "Scanning…") if operation == "scan" else msg("準備生成…", "Preparing generation…"))
        self.worker = Worker(operation, arguments, self)
        self.worker.progress.connect(self.update_progress)
        self.worker.result.connect(self.receive_result)
        self.worker.finished.connect(self.worker_finished)
        self.timer.start()
        self.worker.start()

    def scan(self):
        if not self.input_path.text() or self.worker is not None:
            return
        self.inventory = None
        self.table.setRowCount(0)
        self.log.clear()
        self.start_worker("scan", {"root": self.input_path.text()})

    def selected_groups(self):
        if self.inventory is None:
            return []
        return [g for i, g in enumerate(self.inventory.groups) if not g.problem
                and self.table.item(i, 0).checkState() == Qt.CheckState.Checked]

    def set_selection(self, selected: bool):
        if self.inventory:
            for index, group in enumerate(self.inventory.groups):
                if not group.problem:
                    self.table.item(index, 0).setCheckState(Qt.CheckState.Checked if selected else Qt.CheckState.Unchecked)

    def generate(self):
        groups = self.selected_groups()
        if not groups or not self.output_path.text():
            QMessageBox.information(self, msg("尚未就緒", "Not Ready"), msg("請選擇有效組別及輸出位置。", "Select eligible groups and an output location."))
            return
        self.start_worker("generate", {"inventory": self.inventory, "groups": groups,
                          "output_parent": self.output_path.text(),
                          "settings": DisplaySettings(self.gamma.value(), self.compression.value())})

    def update_progress(self, value: dict):
        self._last_progress, self._last_progress_at = value, monotonic()
        if value["phase"] == "scan":
            self.phase.setText(msg(f"已掃描 {value['scanned']} 張 TIFF", f"Scanned {value['scanned']} TIFF files"))
        else:
            self.progress_bar.setRange(0, 1000)
            self.progress_bar.setValue(round(1000 * value["completed"] / max(1, value["total"])))
            self.phase.setText(phase_text(value["phase"]))
            key = value["key"]
            self.group_label.setText(msg(
                f"組別 {value['group_index']} / {value['group_total']}：{key['sample']} / {key['channel']} / J={key['density']:g} / G{key['gain']}",
                f"Group {value['group_index']} / {value['group_total']}: {key['sample']} / {key['channel']} / J={key['density']:g} / G{key['gain']}"))
        self.tick()

    def tick(self):
        if self.worker is None:
            return
        now = monotonic()
        self.elapsed.setText(duration(now - self._started))
        eta = self._last_progress.get("remaining_s")
        if eta is None:
            self.remaining.setText(msg("估算中；依實際處理速度更新", "Estimating; updates from processing speed"))
            self.finish_time.setText("—")
        else:
            remaining = max(0, eta - (now - self._last_progress_at))
            self.remaining.setText(duration(remaining))
            self.finish_time.setText((datetime.now().astimezone() + timedelta(seconds=remaining)).strftime("%Y-%m-%d %H:%M:%S"))

    def request_cancel(self):
        if self.worker:
            self.worker.cancel.set()
            self.cancel_button.setEnabled(False)
            self.phase.setText(msg("取消中，等待目前檔案處理結束…", "Cancelling; waiting for current file operation…"))

    def receive_result(self, value: dict):
        self._pending_result = value

    def worker_finished(self):
        worker = self.worker
        self.worker = None
        self.timer.stop()
        if worker:
            worker.deleteLater()
        value = self._pending_result or {"error": "Worker ended without result"}
        self.progress_bar.setRange(0, 1000)
        if "error" in value:
            self.phase.setText(msg("處理失敗，詳情如下", "Processing failed; details below"))
            self.log.setPlainText(value["error"])
        elif value.get("cancelled"):
            self.phase.setText(status_text("cancelled"))
        elif value["operation"] == "scan":
            self.populate(value["value"])
        else:
            result = value["value"]
            self.last_output = Path(result["output_directory"])
            self.phase.setText(status_text(result["status"]))
            self.progress_bar.setValue(1000 if result["status"].startswith("completed") else self.progress_bar.value())
            lines = [str(self.last_output)]
            if result.get("error"):
                lines.append(result["error"])
            for row in result["results"]:
                lines.append(f"{row['sample']} / {row['channel']} / J={row['density']:g} / G{row['gain']}: {status_text(row['status'])} {row['error']}")
            self.log.setPlainText("\n".join(lines))
        self.remaining.setText("—")
        self.finish_time.setText("—")
        self.set_busy(False)
        if self._closing:
            self.close()

    def populate(self, inventory: Inventory):
        self.inventory = inventory
        self.table.setRowCount(len(inventory.groups))
        for index, group in enumerate(inventory.groups):
            check = QTableWidgetItem()
            check.setFlags(Qt.ItemFlag.ItemIsUserCheckable | Qt.ItemFlag.ItemIsEnabled if not group.problem else Qt.ItemFlag.NoItemFlags)
            check.setCheckState(Qt.CheckState.Unchecked if group.problem else Qt.CheckState.Checked)
            self.table.setItem(index, 0, check)
            key = group.key
            state = problem_text(group.problem) if group.problem else msg("可生成", "Ready")
            warnings = sorted({w for f in group.frames for w in f.warnings})
            if warnings and not group.problem:
                state += msg("（有資料假設）", " (metadata assumptions)")
            values = [key.run, key.sample, key.channel, f"{key.density:g}", str(key.gain),
                      ", ".join(f"{e:g}" for e in group.exposures), str(len(group.frames)), state]
            for column, text in enumerate(values, 1):
                item = QTableWidgetItem(text)
                item.setToolTip(text + ("\n" + ", ".join(warnings) if column == 8 and warnings else ""))
                self.table.setItem(index, column, item)
        self.table.setColumnWidth(1, 200)
        eligible = sum(not g.problem for g in inventory.groups)
        self.phase.setText(msg(f"掃描完成：{eligible} 組可生成；{len(inventory.issues)} 個輸入問題；排除 {inventory.excluded_dark} 張 Dark／衍生圖。",
                              f"Scan complete: {eligible} eligible groups; {len(inventory.issues)} input issues; {inventory.excluded_dark} Dark/derived files excluded."))
        self.log.setPlainText("\n".join(f"{i['path']}: {i['detail']}" for i in inventory.issues))

    def show_output(self):
        if self.last_output:
            QDesktopServices.openUrl(QUrl.fromLocalFile(str(self.last_output)))

    def closeEvent(self, event):
        if self.worker is not None:
            self._closing = True
            self.request_cancel()
            event.ignore()
        else:
            event.accept()
