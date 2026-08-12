from __future__ import annotations

"""Compact Traditional-Chinese editor for shared polarity measurement settings."""

from copy import deepcopy

from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QDoubleSpinBox,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPushButton,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from .polarity_settings import PolarityMeasurementSettings, PolaritySettingsStore


def _double(minimum: float, maximum: float, suffix: str, decimals: int = 3) -> QDoubleSpinBox:
    widget = QDoubleSpinBox()
    widget.setRange(minimum, maximum)
    widget.setDecimals(decimals)
    widget.setSuffix(suffix)
    widget.setKeyboardTracking(False)
    return widget


class PolaritySettingsDialog(QDialog):
    def __init__(self, store: PolaritySettingsStore, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.store = store
        self.setWindowTitle("極性確認設定")
        self.resize(620, 720)
        self._build_ui()
        self._write(store.settings)

    def _build_ui(self) -> None:
        intro = QLabel(
            "這份設定由 SMU 手動輸出與 Recipe 極性確認共用；每次量測會另存當次設定與結果快照。"
        )
        intro.setWordWrap(True)
        intro.setStyleSheet("background:#edf5fa; border:1px solid #b6cedd; padding:8px;")

        self.light_stabilization = QSpinBox()
        self.light_stabilization.setRange(0, 600000)
        self.light_stabilization.setSuffix(" ms")
        light = self._group("白光", (("白光開啟後穩定等待時間", self.light_stabilization),))

        self.anti_flicker = QCheckBox("啟用抗光源閃爍量測")
        self.mains_frequency = _double(40, 70, " Hz", 2)
        self.integration_nplc = _double(0.001, 100, " PLC", 3)
        flicker = self._group(
            "抗閃爍",
            (("", self.anti_flicker), ("市電頻率", self.mains_frequency), ("Integration / Aperture", self.integration_nplc)),
        )

        self.jsc_settle = self._milliseconds()
        self.jsc_samples = self._samples()
        self.jsc_aggregation = self._aggregation()
        self.jsc_minimum = _double(0.000001, 1000, " mA/cm²", 6)
        self.jsc_variation = _double(0, 1000, " %", 3)
        self.jsc_compliance = _double(0.000001, 1000, " mA/cm²", 6)
        jsc = self._group(
            "Jsc",
            (
                ("Settle Time", self.jsc_settle),
                ("取樣次數", self.jsc_samples),
                ("統計方式", self.jsc_aggregation),
                ("Current Compliance", self.jsc_compliance),
            ),
        )

        self.voc_settle = self._milliseconds()
        self.voc_samples = self._samples()
        self.voc_aggregation = self._aggregation()
        self.voc_minimum = _double(0.000001, 10, " V", 6)
        self.voc_variation = _double(0, 1000, " %", 3)
        self.voc_compliance = _double(0.000001, 10, " V", 6)
        voc = self._group(
            "Voc",
            (
                ("Settle Time", self.voc_settle),
                ("取樣次數", self.voc_samples),
                ("統計方式", self.voc_aggregation),
                ("Voltage Compliance", self.voc_compliance),
            ),
        )
        decision = self._group(
            "判定條件",
            (
                ("最小有效 |Jsc|", self.jsc_minimum),
                ("Jsc 最大允許變異", self.jsc_variation),
                ("最小有效 |Voc|", self.voc_minimum),
                ("Voc 最大允許變異", self.voc_variation),
            ),
        )

        self.restore_defaults = QPushButton("恢復預設值")
        self.restore_defaults.clicked.connect(
            lambda: self._write(PolarityMeasurementSettings())
        )
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self._save)
        buttons.rejected.connect(self.reject)
        footer = QHBoxLayout()
        footer.addWidget(self.restore_defaults)
        footer.addStretch()
        footer.addWidget(buttons)

        layout = QVBoxLayout(self)
        layout.addWidget(intro)
        for group in (light, flicker, jsc, voc, decision):
            layout.addWidget(group)
        layout.addLayout(footer)

    @staticmethod
    def _group(title: str, rows: tuple[tuple[str, QWidget], ...]) -> QGroupBox:
        group = QGroupBox(title)
        form = QFormLayout(group)
        for label, widget in rows:
            form.addRow(label, widget) if label else form.addRow(widget)
        return group

    @staticmethod
    def _milliseconds() -> QSpinBox:
        widget = QSpinBox()
        widget.setRange(0, 600000)
        widget.setSuffix(" ms")
        return widget

    @staticmethod
    def _samples() -> QSpinBox:
        widget = QSpinBox()
        widget.setRange(1, 1000)
        return widget

    @staticmethod
    def _aggregation() -> QComboBox:
        widget = QComboBox()
        widget.addItem("Median", "median")
        widget.addItem("Mean", "mean")
        return widget

    def _write(self, value: PolarityMeasurementSettings) -> None:
        self.light_stabilization.setValue(value.white_light_stabilization_ms)
        self.anti_flicker.setChecked(value.anti_flicker_enabled)
        self.mains_frequency.setValue(value.mains_frequency_hz)
        self.integration_nplc.setValue(value.integration_nplc)
        self.jsc_settle.setValue(value.jsc_settle_ms)
        self.jsc_samples.setValue(value.jsc_sample_count)
        self._set_combo(self.jsc_aggregation, value.jsc_aggregation)
        self.jsc_minimum.setValue(value.jsc_minimum_valid_ma_cm2)
        self.jsc_variation.setValue(value.jsc_max_variation_percent)
        self.jsc_compliance.setValue(value.jsc_compliance_ma_cm2)
        self.voc_settle.setValue(value.voc_settle_ms)
        self.voc_samples.setValue(value.voc_sample_count)
        self._set_combo(self.voc_aggregation, value.voc_aggregation)
        self.voc_minimum.setValue(value.voc_minimum_valid_v)
        self.voc_variation.setValue(value.voc_max_variation_percent)
        self.voc_compliance.setValue(value.voc_compliance_v)

    def _read(self) -> PolarityMeasurementSettings:
        value = deepcopy(self.store.settings)
        value.white_light_stabilization_ms = self.light_stabilization.value()
        value.anti_flicker_enabled = self.anti_flicker.isChecked()
        value.mains_frequency_hz = self.mains_frequency.value()
        value.integration_nplc = self.integration_nplc.value()
        value.jsc_settle_ms = self.jsc_settle.value()
        value.jsc_sample_count = self.jsc_samples.value()
        value.jsc_aggregation = str(self.jsc_aggregation.currentData())
        value.jsc_minimum_valid_ma_cm2 = self.jsc_minimum.value()
        value.jsc_max_variation_percent = self.jsc_variation.value()
        value.jsc_compliance_ma_cm2 = self.jsc_compliance.value()
        value.voc_settle_ms = self.voc_settle.value()
        value.voc_sample_count = self.voc_samples.value()
        value.voc_aggregation = str(self.voc_aggregation.currentData())
        value.voc_minimum_valid_v = self.voc_minimum.value()
        value.voc_max_variation_percent = self.voc_variation.value()
        value.voc_compliance_v = self.voc_compliance.value()
        return value

    def _save(self) -> None:
        value = self._read()
        errors = value.validate()
        if errors:
            QMessageBox.warning(self, "極性確認設定無效", "• " + "\n• ".join(errors))
            return
        self.store.settings = value
        try:
            self.store.save()
        except Exception as exc:
            QMessageBox.critical(self, "無法保存極性確認設定", str(exc))
            return
        self.accept()

    @staticmethod
    def _set_combo(combo: QComboBox, value: str) -> None:
        combo.setCurrentIndex(max(0, combo.findData(value)))
