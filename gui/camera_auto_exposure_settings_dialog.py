from __future__ import annotations

from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QLabel,
    QVBoxLayout,
)

from .camera_auto_exposure_settings import (
    AUTO_EXPOSURE_TARGET_PERCENT_OPTIONS,
    load_auto_exposure_target_percent,
    save_auto_exposure_target_percent,
)


class CameraAutoExposureSettingsDialog(QDialog):
    """Edit the whole-frame Effective-DN target used by software AE."""

    def __init__(self, settings, parent=None) -> None:
        super().__init__(parent)
        self._settings = settings
        self.setWindowTitle("相機自動曝光設定")
        self.setModal(True)

        self.target_percent_combo = QComboBox()
        for percent in AUTO_EXPOSURE_TARGET_PERCENT_OPTIONS:
            self.target_percent_combo.addItem(f"{percent} %", percent)
        current = load_auto_exposure_target_percent(settings)
        self.target_percent_combo.setCurrentIndex(
            self.target_percent_combo.findData(current)
        )

        form = QFormLayout()
        form.addRow("自動曝光目標", self.target_percent_combo)
        explanation = QLabel(
            "目標 DN 依 EffectiveDNMax × 百分比計算。\n"
            "統計區域固定為 Scientific MONO16 全畫面平均 Effective DN。"
        )
        explanation.setWordWrap(True)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok
            | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)

        layout = QVBoxLayout(self)
        layout.addLayout(form)
        layout.addWidget(explanation)
        layout.addWidget(buttons)

    @property
    def target_percent(self) -> int:
        return int(self.target_percent_combo.currentData())

    def accept(self) -> None:
        save_auto_exposure_target_percent(self._settings, self.target_percent)
        super().accept()
