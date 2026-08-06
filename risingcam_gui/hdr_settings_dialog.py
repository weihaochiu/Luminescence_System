from __future__ import annotations

"""Editor for application-wide quantitative HDR settings."""

from copy import deepcopy

from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QDoubleSpinBox,
    QFormLayout,
    QLabel,
    QMessageBox,
    QSpinBox,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from .hdr_settings import HDRSettingsStore, HDRSystemSettings


def _double(minimum: float, maximum: float, value: float, suffix: str = "", decimals: int = 3) -> QDoubleSpinBox:
    widget = QDoubleSpinBox()
    widget.setRange(minimum, maximum)
    widget.setDecimals(decimals)
    widget.setValue(value)
    widget.setSuffix(suffix)
    widget.setKeyboardTracking(False)
    return widget


class HDRSettingsDialog(QDialog):
    def __init__(self, store: HDRSettingsStore, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.store = store
        self.setWindowTitle("HDR 系統設定")
        self.resize(720, 680)
        self.setMinimumSize(650, 580)
        self._build_ui()
        self._write_settings(store.settings)

    def _build_ui(self) -> None:
        intro = QLabel(
            "這裡的設定供所有啟用 HDR 的 Recipe 共用。Recipe 只保存是否啟用；每次量測仍會把"
            "當下完整設定寫入不可變的量測快照。"
        )
        intro.setWordWrap(True)
        intro.setStyleSheet("background:#edf5fa; border:1px solid #b6cedd; padding:9px;")

        tabs = QTabWidget()
        tabs.addTab(self._build_planning_tab(), "曝光規劃")
        tabs.addTab(self._build_termination_tab(), "過曝判定")
        tabs.addTab(self._build_output_tab(), "Dark／輸出")

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self._save)
        buttons.rejected.connect(self.reject)
        layout = QVBoxLayout(self)
        layout.addWidget(intro)
        layout.addWidget(tabs, 1)
        layout.addWidget(buttons)

    def _build_planning_tab(self) -> QWidget:
        page = QWidget()
        form = QFormLayout(page)
        self.strategy = QComboBox()
        self.strategy.addItem("自動決定實際曝光段數", "auto")
        self.strategy.addItem("依曝光級距建立固定上限組合", "fixed_bracket")
        self.prioritize_single = QCheckBox("先嘗試用單一曝光涵蓋所有量測點")
        self.max_segments = QSpinBox()
        self.max_segments.setRange(1, 20)
        self.max_segments.setSuffix(" 段（上限）")
        self.frames = QSpinBox()
        self.frames.setRange(1, 999)
        self.frames.setSuffix(" frames／段")
        self.frame_interval = _double(0, 600, 0.1, " s")
        self.gain_mode = QComboBox()
        self.gain_mode.addItem("T0 預掃描選定後鎖定", "auto_lock")
        self.gain_mode.addItem("使用指定 Gain 並鎖定", "manual_lock")
        self.locked_gain = QSpinBox()
        self.locked_gain.setRange(0, 500)
        self.locked_gain.setSuffix(" %")
        self.min_exposure = _double(0.001, 15000, 0.030, " ms", 6)
        self.max_exposure = _double(0.001, 15000, 15000, " ms", 3)
        self.exposure_ratio = _double(1.01, 100, 4, " ×", 2)
        self.target_high = _double(1, 254, 220, " DN", 1)
        self.minimum_snr = _double(0.1, 100, 5, " σ", 1)
        self.max_point_time = _double(0.1, 3600, 60, " s", 1)
        form.addRow("HDR 策略", self.strategy)
        form.addRow(self.prioritize_single)
        form.addRow("最大曝光段數", self.max_segments)
        form.addRow("每段平均張數", self.frames)
        form.addRow("Frame 間隔", self.frame_interval)
        form.addRow("Gain 模式", self.gain_mode)
        form.addRow("指定 Gain", self.locked_gain)
        form.addRow("最短曝光", self.min_exposure)
        form.addRow("最長曝光", self.max_exposure)
        form.addRow("曝光級距", self.exposure_ratio)
        form.addRow("高亮目標", self.target_high)
        form.addRow("最低有效訊號", self.minimum_snr)
        form.addRow("每點最長 HDR 時間", self.max_point_time)
        note = QLabel("「最大 4 段」不是強制拍滿 4 段；單曝光足夠時只拍 1 段。")
        note.setWordWrap(True)
        note.setStyleSheet("color:#7a5200;")
        form.addRow(note)
        return page

    def _build_termination_tab(self) -> QWidget:
        page = QWidget()
        form = QFormLayout(page)
        self.saturation_dn = _double(1, 255, 245, " DN", 1)
        self.early_stop = QCheckBox("嚴重過曝時立即停止目前段並跳過所有更長曝光")
        self.severe_fraction = _double(0.001, 100, 5, " %", 3)
        self.exclude_hot = QCheckBox("排除已知熱像素")
        self.save_judgment = QCheckBox("保存造成判定的第一張原始影像")
        self.order = QLabel("短曝光 → 長曝光（固定）")
        self.region = QLabel("有效元件 ROI（排除背景與遮罩外區域）")
        self.judgment_count = QLabel("每段先拍 1 張；嚴重過曝時不再完成剩餘平均張數")
        form.addRow("曝光順序", self.order)
        form.addRow("判定範圍", self.region)
        form.addRow("判斷幀", self.judgment_count)
        form.addRow("飽和判定值", self.saturation_dn)
        form.addRow("嚴重過曝比例", self.severe_fraction)
        form.addRow(self.early_stop)
        form.addRow(self.exclude_hot)
        form.addRow(self.save_judgment)
        note = QLabel(
            "例如規劃 4 段而第 2 段第一張的有效 ROI 已嚴重過曝：第 2 段剩餘 frames 與第 3、4 段"
            "均不再拍攝；第 2 段判斷幀仍保存，量測紀錄標記其無效並寫入提前終止原因。"
        )
        note.setWordWrap(True)
        note.setStyleSheet("background:#fff6df; border:1px solid #dfc783; padding:8px;")
        form.addRow(note)
        return page

    def _build_output_tab(self) -> QWidget:
        page = QWidget()
        form = QFormLayout(page)
        self.dark_frames = QSpinBox()
        self.dark_frames.setRange(1, 999)
        self.dark_combine = QComboBox()
        self.dark_combine.addItem("Median", "median")
        self.dark_combine.addItem("Average", "average")
        self.save_preview = QCheckBox("另存 8-bit 預覽 PNG（不可用於定量）")
        self.allow_supplemental = QCheckBox("Aging 低訊號時允許另存補充長曝光結果")
        required = QLabel(
            "固定保存：所有實際拍攝的原始 EL、原始 Dark、每段 Master Dark、過曝判斷幀、"
            "Float32 HDR TIFF、Profile、JSON／CSV manifest。未拍攝的後續段記為 Skipped。"
        )
        required.setWordWrap(True)
        required.setStyleSheet("background:#edf7ed; border:1px solid #b7d3b8; padding:8px;")
        form.addRow("每曝光 Dark frames", self.dark_frames)
        form.addRow("Master Dark 合成", self.dark_combine)
        form.addRow("Dark 方法", QLabel("每次量測依相同曝光重新拍攝（固定）"))
        form.addRow("HDR 算法", QLabel("linear_exposure_normalized_v1（固定）"))
        form.addRow("定量輸出", QLabel("Float32 TIFF／DN/s／Gamma 1.0（固定）"))
        form.addRow(self.save_preview)
        form.addRow(self.allow_supplemental)
        form.addRow(required)
        return page

    def _write_settings(self, settings: HDRSystemSettings) -> None:
        self._set_combo(self.strategy, settings.strategy)
        self.prioritize_single.setChecked(settings.prioritize_single_exposure)
        self.max_segments.setValue(settings.max_exposure_segments)
        self.frames.setValue(settings.frames_per_exposure)
        self.frame_interval.setValue(settings.frame_interval_s)
        self._set_combo(self.gain_mode, settings.gain_mode)
        self.locked_gain.setValue(settings.locked_gain_percent)
        self.min_exposure.setValue(settings.min_exposure_ms)
        self.max_exposure.setValue(settings.max_exposure_ms)
        self.exposure_ratio.setValue(settings.exposure_ratio)
        self.target_high.setValue(settings.target_high_dn)
        self.minimum_snr.setValue(settings.minimum_snr)
        self.max_point_time.setValue(settings.max_point_time_s)
        self.saturation_dn.setValue(settings.saturation_dn)
        self.early_stop.setChecked(settings.early_stop_on_severe_overexposure)
        self.severe_fraction.setValue(settings.severe_saturation_fraction * 100.0)
        self.exclude_hot.setChecked(settings.exclude_hot_pixels)
        self.save_judgment.setChecked(settings.save_judgment_frame)
        self.dark_frames.setValue(settings.dark_frames_per_exposure)
        self._set_combo(self.dark_combine, settings.dark_combine_method)
        self.save_preview.setChecked(settings.save_preview_png)
        self.allow_supplemental.setChecked(settings.allow_supplemental_long_exposure)

    def _read_settings(self) -> HDRSystemSettings:
        settings = deepcopy(self.store.settings)
        settings.strategy = str(self.strategy.currentData())
        settings.prioritize_single_exposure = self.prioritize_single.isChecked()
        settings.max_exposure_segments = self.max_segments.value()
        settings.frames_per_exposure = self.frames.value()
        settings.frame_interval_s = self.frame_interval.value()
        settings.gain_mode = str(self.gain_mode.currentData())
        settings.locked_gain_percent = self.locked_gain.value()
        settings.min_exposure_ms = self.min_exposure.value()
        settings.max_exposure_ms = self.max_exposure.value()
        settings.exposure_ratio = self.exposure_ratio.value()
        settings.target_high_dn = self.target_high.value()
        settings.minimum_snr = self.minimum_snr.value()
        settings.max_point_time_s = self.max_point_time.value()
        settings.saturation_dn = self.saturation_dn.value()
        settings.early_stop_on_severe_overexposure = self.early_stop.isChecked()
        settings.severe_saturation_fraction = self.severe_fraction.value() / 100.0
        settings.exclude_hot_pixels = self.exclude_hot.isChecked()
        settings.save_judgment_frame = self.save_judgment.isChecked()
        settings.dark_frames_per_exposure = self.dark_frames.value()
        settings.dark_combine_method = str(self.dark_combine.currentData())
        settings.save_preview_png = self.save_preview.isChecked()
        settings.allow_supplemental_long_exposure = self.allow_supplemental.isChecked()
        return settings

    def _save(self) -> None:
        settings = self._read_settings()
        errors = settings.validate()
        if errors:
            QMessageBox.warning(self, "HDR 設定無效", "• " + "\n• ".join(errors))
            return
        self.store.settings = settings
        try:
            self.store.save()
        except Exception as exc:
            QMessageBox.critical(self, "無法保存 HDR 設定", str(exc))
            return
        self.accept()

    @staticmethod
    def _set_combo(combo: QComboBox, value: str) -> None:
        index = combo.findData(value)
        combo.setCurrentIndex(max(0, index))
