from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QHBoxLayout,
    QHeaderView,
    QLineEdit,
    QSplitter,
    QTabWidget,
    QTableView,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from core.error_registry import ErrorRegistry, Severity, default_error_registry
from core.error_reporter import ErrorEvent, ErrorReporter
from core.i18n import i18n, tr
from .error_detail_panel import ErrorDetailPanel
from .error_list_model import ErrorFilterModel, ErrorListModel


class ErrorCenterDialog(QDialog):
    def __init__(
        self,
        reporter: ErrorReporter,
        parent: QWidget | None = None,
        *,
        registry: ErrorRegistry = default_error_registry,
    ) -> None:
        super().__init__(parent)
        self.reporter = reporter
        self.registry = registry
        self.setObjectName("errorCenterDialog")
        self.setMinimumSize(820, 520)
        self.resize(1000, 680)
        self.tabs = QTabWidget()
        self.codes_page = QWidget()
        self.history_page = QWidget()
        self.search_edit = QLineEdit()
        self.search_edit.setObjectName("errorSearch")
        self.subsystem_combo = QComboBox()
        self.subsystem_combo.setObjectName("subsystemFilter")
        self.severity_combo = QComboBox()
        self.severity_combo.setObjectName("severityFilter")
        filters = QHBoxLayout()
        filters.addWidget(self.search_edit, 2)
        filters.addWidget(self.subsystem_combo, 1)
        filters.addWidget(self.severity_combo, 1)

        self.model = ErrorListModel(registry, self)
        self.proxy = ErrorFilterModel(self)
        self.proxy.setSourceModel(self.model)
        self.error_table = QTableView()
        self.error_table.setObjectName("errorCodeTable")
        self.error_table.setModel(self.proxy)
        self.error_table.setSelectionBehavior(QTableView.SelectionBehavior.SelectRows)
        self.error_table.setSelectionMode(QTableView.SelectionMode.SingleSelection)
        self.error_table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeMode.Stretch)
        self.detail_panel = ErrorDetailPanel()
        splitter = QSplitter(Qt.Orientation.Horizontal)
        splitter.addWidget(self.error_table)
        splitter.addWidget(self.detail_panel)
        splitter.setStretchFactor(0, 3)
        splitter.setStretchFactor(1, 4)
        codes_layout = QVBoxLayout(self.codes_page)
        codes_layout.addLayout(filters)
        codes_layout.addWidget(splitter)

        self.history_table = QTableWidget(0, 4)
        self.history_table.setObjectName("sessionHistoryTable")
        self.history_table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.history_table.setSelectionMode(QTableWidget.SelectionMode.SingleSelection)
        self.history_table.horizontalHeader().setSectionResizeMode(3, QHeaderView.ResizeMode.Stretch)
        history_layout = QVBoxLayout(self.history_page)
        history_layout.addWidget(self.history_table)
        self.tabs.addTab(self.codes_page, "")
        self.tabs.addTab(self.history_page, "")
        layout = QVBoxLayout(self)
        layout.addWidget(self.tabs)

        self.search_edit.textChanged.connect(lambda value: self.proxy.set_filters(search=value))
        self.subsystem_combo.currentIndexChanged.connect(lambda _index: self.proxy.set_filters(subsystem=str(self.subsystem_combo.currentData() or "")))
        self.severity_combo.currentIndexChanged.connect(lambda _index: self.proxy.set_filters(severity=str(self.severity_combo.currentData() or "")))
        self.error_table.selectionModel().currentRowChanged.connect(self._on_code_selected)
        self.history_table.currentCellChanged.connect(self._on_history_selected)
        reporter.history_changed.connect(self.refresh_history)
        i18n.language_changed.connect(self._retranslate)
        self._populate_filters()
        self._retranslate()
        self.refresh_history()
        if self.proxy.rowCount():
            self.error_table.selectRow(0)

    def _populate_filters(self) -> None:
        subsystem = self.subsystem_combo.currentData()
        severity = self.severity_combo.currentData()
        self.subsystem_combo.clear()
        self.subsystem_combo.addItem("", "")
        for value in sorted({item.subsystem for item in self.registry.all()}):
            self.subsystem_combo.addItem(value.upper(), value)
        self.severity_combo.clear()
        self.severity_combo.addItem("", "")
        for value in Severity:
            self.severity_combo.addItem("", value.value)
        self.subsystem_combo.setCurrentIndex(max(0, self.subsystem_combo.findData(subsystem)))
        self.severity_combo.setCurrentIndex(max(0, self.severity_combo.findData(severity)))

    def _retranslate(self, _language: str = "") -> None:
        self.setWindowTitle(tr("error_center.title"))
        self.search_edit.setPlaceholderText(tr("error_center.search_placeholder"))
        self.tabs.setTabText(0, tr("error_center.error_codes"))
        self.tabs.setTabText(1, tr("error_center.session_history"))
        self.subsystem_combo.setItemText(0, tr("error_center.subsystem_all"))
        self.severity_combo.setItemText(0, tr("error_center.severity_all"))
        for index, severity in enumerate(Severity, start=1):
            self.severity_combo.setItemText(index, tr(f"errors.severity.{severity.value}"))
        self.history_table.setHorizontalHeaderLabels((tr("error_center.timestamp"), tr("error_center.code"), tr("common.severity"), tr("errors.what_happened")))
        self.model.retranslate()
        self.proxy.invalidateFilter()
        self.refresh_history()

    def _on_code_selected(self, proxy_index, _previous=None) -> None:
        if not proxy_index.isValid():
            self.detail_panel.set_definition(None)
            return
        source = self.proxy.mapToSource(proxy_index)
        self.detail_panel.set_definition(self.model.definition(source.row()))

    def _on_history_selected(self, row: int, _column: int, _previous_row: int, _previous_column: int) -> None:
        history = self.reporter.history()
        if 0 <= row < len(history):
            self.open_code(history[row].code)

    def refresh_history(self) -> None:
        history = self.reporter.history()
        self.history_table.setRowCount(len(history))
        for row, event in enumerate(history):
            values = (event.context.timestamp, event.code, tr(f"errors.severity.{event.severity.value}"), event.title)
            for column, value in enumerate(values):
                self.history_table.setItem(row, column, QTableWidgetItem(value))

    def open_code(self, code: str) -> bool:
        self.tabs.setCurrentWidget(self.codes_page)
        self.subsystem_combo.setCurrentIndex(0)
        self.severity_combo.setCurrentIndex(0)
        self.search_edit.setText(str(code))
        for row in range(self.proxy.rowCount()):
            index = self.proxy.index(row, 0)
            if str(index.data()) == str(code):
                self.error_table.setCurrentIndex(index)
                self.error_table.scrollTo(index)
                self._on_code_selected(index)
                return True
        return False
