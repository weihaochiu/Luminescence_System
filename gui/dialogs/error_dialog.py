from __future__ import annotations

"""Unified user-facing error dialog backed by an ErrorEvent."""

from collections.abc import Callable, Mapping

from PySide6.QtCore import Signal
from PySide6.QtGui import QFont
from PySide6.QtWidgets import (
    QApplication,
    QDialog,
    QDialogButtonBox,
    QFrame,
    QHBoxLayout,
    QLabel,
    QPlainTextEdit,
    QPushButton,
    QSizePolicy,
    QStyle,
    QVBoxLayout,
    QWidget,
)

from core.error_registry import Severity
from core.error_reporter import ErrorEvent, format_diagnostics
from core.i18n import i18n, tr


class ErrorDialog(QDialog):
    action_requested = Signal(str, object)
    view_details_requested = Signal(str)

    def __init__(
        self,
        event: ErrorEvent,
        parent: QWidget | None = None,
        *,
        action_handlers: Mapping[str, Callable[[ErrorEvent], bool | None]] | None = None,
        error_center_opener: Callable[[str], None] | None = None,
    ) -> None:
        super().__init__(parent)
        self.error_event = event
        self._handlers = dict(action_handlers or {})
        self._error_center_opener = error_center_opener
        self.setObjectName("errorDialog")
        self.setMinimumWidth(620)
        self.resize(720, 560)

        self.icon_label = QLabel()
        self.icon_label.setFixedSize(48, 48)
        self.icon_label.setPixmap(self._icon().pixmap(40, 40))
        self.title_label = QLabel()
        title_font = QFont(self.title_label.font())
        title_font.setBold(True)
        title_font.setPointSize(max(12, title_font.pointSize() + 2))
        self.title_label.setFont(title_font)
        self.title_label.setWordWrap(True)
        self.code_label = QLabel()
        self.code_label.setObjectName("errorCode")
        self.severity_label = QLabel()
        self.severity_label.setObjectName("errorSeverity")
        heading = QVBoxLayout()
        heading.addWidget(self.title_label)
        heading.addWidget(self.code_label)
        heading.addWidget(self.severity_label)
        top = QHBoxLayout()
        top.addWidget(self.icon_label, 0)
        top.addLayout(heading, 1)

        self.message_label = QLabel()
        self.message_label.setObjectName("errorMessage")
        self.message_label.setWordWrap(True)
        self.message_label.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Minimum)
        self.causes_heading = QLabel()
        self.causes_label = QLabel()
        self.causes_label.setWordWrap(True)
        self.solutions_heading = QLabel()
        self.solutions_label = QLabel()
        self.solutions_label.setWordWrap(True)

        self.details_edit = QPlainTextEdit()
        self.details_edit.setObjectName("technicalDetails")
        self.details_edit.setReadOnly(True)
        self.details_edit.setLineWrapMode(QPlainTextEdit.LineWrapMode.NoWrap)
        self.details_edit.setVisible(False)
        self.details_edit.setMinimumHeight(170)

        self.copy_button = QPushButton()
        self.copy_button.setObjectName("copyDiagnosticsButton")
        self.details_button = QPushButton()
        self.details_button.setObjectName("toggleTechnicalDetailsButton")
        self.center_button = QPushButton()
        self.center_button.setObjectName("viewErrorDetailsButton")
        self.copy_button.clicked.connect(self.copy_diagnostics)
        self.details_button.clicked.connect(self.toggle_details)
        self.center_button.clicked.connect(self.open_error_center)
        self.action_status_label = QLabel()
        self.action_status_label.setObjectName("errorActionStatus")
        self.action_status_label.setWordWrap(True)
        self.action_status_label.setVisible(False)
        self._action_status_key = ""

        button_row = QHBoxLayout()
        button_row.addWidget(self.copy_button)
        button_row.addWidget(self.details_button)
        button_row.addWidget(self.center_button)
        button_row.addStretch()
        self.action_buttons: dict[str, QPushButton] = {}
        for action in event.definition.actions:
            if action not in self._handlers:
                continue
            button = QPushButton()
            button.setObjectName(f"errorAction_{action}")
            button.clicked.connect(lambda _checked=False, selected=action: self._run_action(selected))
            self.action_buttons[action] = button
            button_row.addWidget(button)
        self.close_buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        self.close_buttons.rejected.connect(self.reject)
        button_row.addWidget(self.close_buttons)

        layout = QVBoxLayout()
        layout.addLayout(top)
        separator = QFrame()
        separator.setFrameShape(QFrame.Shape.HLine)
        layout.addWidget(separator)
        layout.addWidget(self.message_label)
        layout.addWidget(self.causes_heading)
        layout.addWidget(self.causes_label)
        layout.addWidget(self.solutions_heading)
        layout.addWidget(self.solutions_label)
        layout.addWidget(self.details_edit, 1)
        layout.addWidget(self.action_status_label)
        layout.addLayout(button_row)
        self.setLayout(layout)
        self._retranslate()
        i18n.language_changed.connect(self._retranslate)

    def _icon(self):
        pixmap = {
            Severity.INFO: QStyle.StandardPixmap.SP_MessageBoxInformation,
            Severity.WARNING: QStyle.StandardPixmap.SP_MessageBoxWarning,
            Severity.ERROR: QStyle.StandardPixmap.SP_MessageBoxCritical,
            Severity.CRITICAL: QStyle.StandardPixmap.SP_MessageBoxCritical,
        }[self.error_event.severity]
        return self.style().standardIcon(pixmap)

    @staticmethod
    def _bullet_list(items: tuple[str, ...]) -> str:
        return "\n".join(f"• {item}" for item in items)

    def _retranslate(self, _language: str = "") -> None:
        event = self.error_event
        self.setWindowTitle(event.title)
        self.title_label.setText(event.title)
        self.code_label.setText(tr("errors.code_label", code=event.code))
        severity = tr(f"errors.severity.{event.severity.value}")
        self.severity_label.setText(tr("errors.severity_label", severity=severity))
        self.message_label.setText(event.message)
        self.causes_heading.setText(tr("errors.possible_causes"))
        self.causes_label.setText(self._bullet_list(event.causes))
        self.solutions_heading.setText(tr("errors.recommended_actions"))
        self.solutions_label.setText(self._bullet_list(event.solutions))
        self.copy_button.setText(tr("common.copy_diagnostics"))
        self.details_button.setText(
            tr("common.details_hide") if self.details_edit.isVisible() else tr("common.details_show")
        )
        self.center_button.setText(tr("common.view_error_details"))
        action_keys = {
            "retry": "common.retry",
            "safe_shutdown": "common.safe_shutdown",
            "reconnect": "common.reconnect",
        }
        for action, button in self.action_buttons.items():
            button.setText(tr(action_keys[action]))
        if self._action_status_key:
            self.action_status_label.setText(tr(self._action_status_key))
        close = self.close_buttons.button(QDialogButtonBox.StandardButton.Close)
        if close is not None:
            close.setText(tr("common.close"))
        self.details_edit.setPlainText(format_diagnostics(event))

    def toggle_details(self) -> None:
        self.details_edit.setVisible(not self.details_edit.isVisible())
        self._retranslate()

    def copy_diagnostics(self) -> None:
        QApplication.clipboard().setText(format_diagnostics(self.error_event))

    def open_error_center(self) -> None:
        self.view_details_requested.emit(self.error_event.code)
        if self._error_center_opener is not None:
            self._error_center_opener(self.error_event.code)

    def _run_action(self, action: str) -> None:
        self.action_requested.emit(action, self.error_event)
        handler = self._handlers.get(action)
        if handler is None:
            return
        for button in self.action_buttons.values():
            button.setEnabled(False)
        self._action_status_key = "errors.action_started"
        self.action_status_label.setText(tr(self._action_status_key))
        self.action_status_label.setVisible(True)
        try:
            accepted = handler(self.error_event)
        except Exception:
            for button in self.action_buttons.values():
                button.setEnabled(True)
            self._action_status_key = "errors.action_failed"
            self.action_status_label.setText(tr(self._action_status_key))
            raise
        if accepted is False:
            for button in self.action_buttons.values():
                button.setEnabled(True)
            self._action_status_key = "errors.action_unavailable"
            self.action_status_label.setText(tr(self._action_status_key))
