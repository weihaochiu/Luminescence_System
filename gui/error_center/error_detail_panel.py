from __future__ import annotations

from PySide6.QtWidgets import QFormLayout, QLabel, QVBoxLayout, QWidget

from core.error_registry import ErrorDefinition
from core.i18n import i18n, tr


class ErrorDetailPanel(QWidget):
    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.definition: ErrorDefinition | None = None
        self.code_value = QLabel("—")
        self.title_value = QLabel("—")
        self.title_value.setWordWrap(True)
        self.severity_value = QLabel("—")
        self.subsystem_value = QLabel("—")
        self.description_heading = QLabel()
        self.description_value = QLabel()
        self.description_value.setWordWrap(True)
        self.causes_heading = QLabel()
        self.causes_value = QLabel()
        self.causes_value.setWordWrap(True)
        self.solutions_heading = QLabel()
        self.solutions_value = QLabel()
        self.solutions_value.setWordWrap(True)
        self.form = QFormLayout()
        self.form.addRow("", self.code_value)
        self.form.addRow("", self.title_value)
        self.form.addRow("", self.severity_value)
        self.form.addRow("", self.subsystem_value)
        layout = QVBoxLayout(self)
        layout.addLayout(self.form)
        layout.addWidget(self.description_heading)
        layout.addWidget(self.description_value)
        layout.addWidget(self.causes_heading)
        layout.addWidget(self.causes_value)
        layout.addWidget(self.solutions_heading)
        layout.addWidget(self.solutions_value)
        layout.addStretch()
        i18n.language_changed.connect(self._retranslate)
        self._retranslate()

    @staticmethod
    def _bullets(keys: tuple[str, ...]) -> str:
        return "\n".join(f"• {tr(key)}" for key in keys)

    def set_definition(self, definition: ErrorDefinition | None) -> None:
        self.definition = definition
        self._retranslate()

    def _retranslate(self, _language: str = "") -> None:
        labels = ("error_center.code", "errors.what_happened", "common.severity", "error_center.related_subsystem")
        for row, key in enumerate(labels):
            item = self.form.itemAt(row, QFormLayout.ItemRole.LabelRole)
            if item and item.widget():
                item.widget().setText(tr(key))
        self.description_heading.setText(tr("error_center.description"))
        self.causes_heading.setText(tr("errors.possible_causes"))
        self.solutions_heading.setText(tr("errors.recommended_actions"))
        definition = self.definition
        if definition is None:
            for widget in (self.code_value, self.title_value, self.severity_value, self.subsystem_value, self.description_value, self.causes_value, self.solutions_value):
                widget.setText("—")
            return
        self.code_value.setText(definition.code)
        self.title_value.setText(tr(definition.title_key))
        self.severity_value.setText(tr(f"errors.severity.{definition.severity.value}"))
        self.subsystem_value.setText(definition.subsystem.upper())
        self.description_value.setText(tr(definition.message_key))
        self.causes_value.setText(self._bullets(definition.cause_keys))
        self.solutions_value.setText(self._bullets(definition.solution_keys))
