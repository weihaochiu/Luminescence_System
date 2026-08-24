from __future__ import annotations

"""General application settings, including the persisted UI language."""

from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QLabel,
    QVBoxLayout,
    QWidget,
)

from core.i18n import Language, i18n, set_language, tr


class GeneralSettingsDialog(QDialog):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.language_combo = QComboBox()
        self.note_label = QLabel()
        self.note_label.setWordWrap(True)
        self.buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok
            | QDialogButtonBox.StandardButton.Cancel
        )
        self.buttons.accepted.connect(self._apply)
        self.buttons.rejected.connect(self.reject)

        form = QFormLayout()
        form.addRow("", self.language_combo)
        layout = QVBoxLayout(self)
        layout.addLayout(form)
        layout.addWidget(self.note_label)
        layout.addWidget(self.buttons)

        self._retranslate()
        self.language_combo.setCurrentIndex(
            max(0, self.language_combo.findData(i18n.language.value))
        )
        i18n.language_changed.connect(self._retranslate)

    @property
    def selected_language(self) -> Language:
        return Language(str(self.language_combo.currentData()))

    def _retranslate(self, _language: str = "") -> None:
        selected = self.language_combo.currentData()
        self.setWindowTitle(tr("settings.general_title"))
        self.language_combo.clear()
        self.language_combo.addItem(tr("common.language_zh_tw"), Language.ZH_TW.value)
        self.language_combo.addItem(tr("common.language_en_us"), Language.EN_US.value)
        index = self.language_combo.findData(selected or i18n.language.value)
        self.language_combo.setCurrentIndex(max(0, index))
        form = self.layout().itemAt(0).layout()
        if isinstance(form, QFormLayout):
            label = form.labelForField(self.language_combo)
            if label is not None:
                label.setText(tr("settings.language"))
        self.note_label.setText(tr("settings.language_runtime_note"))

    def _apply(self) -> None:
        set_language(self.selected_language)
        self.accept()
