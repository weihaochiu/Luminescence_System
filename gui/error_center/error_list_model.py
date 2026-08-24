from __future__ import annotations

from PySide6.QtCore import QAbstractTableModel, QModelIndex, QSortFilterProxyModel, Qt

from core.error_registry import ErrorDefinition, ErrorRegistry
from core.i18n import tr


class ErrorListModel(QAbstractTableModel):
    HEADERS = ("error_center.code", "common.subsystem", "errors.what_happened", "common.severity")

    def __init__(self, registry: ErrorRegistry, parent=None) -> None:
        super().__init__(parent)
        self.definitions = registry.all()

    def rowCount(self, parent=QModelIndex()) -> int:
        return 0 if parent.isValid() else len(self.definitions)

    def columnCount(self, parent=QModelIndex()) -> int:
        return 0 if parent.isValid() else len(self.HEADERS)

    def data(self, index: QModelIndex, role=Qt.ItemDataRole.DisplayRole):
        if not index.isValid() or not (0 <= index.row() < len(self.definitions)):
            return None
        definition = self.definitions[index.row()]
        if role == Qt.ItemDataRole.UserRole:
            return definition
        if role != Qt.ItemDataRole.DisplayRole:
            return None
        return (
            definition.code,
            definition.subsystem.upper(),
            tr(definition.title_key),
            tr(f"errors.severity.{definition.severity.value}"),
        )[index.column()]

    def headerData(self, section, orientation, role=Qt.ItemDataRole.DisplayRole):
        if orientation == Qt.Orientation.Horizontal and role == Qt.ItemDataRole.DisplayRole:
            return tr(self.HEADERS[section])
        return super().headerData(section, orientation, role)

    def definition(self, row: int) -> ErrorDefinition:
        return self.definitions[row]

    def retranslate(self) -> None:
        if self.definitions:
            self.dataChanged.emit(self.index(0, 0), self.index(len(self.definitions) - 1, len(self.HEADERS) - 1))
        self.headerDataChanged.emit(Qt.Orientation.Horizontal, 0, len(self.HEADERS) - 1)


class ErrorFilterModel(QSortFilterProxyModel):
    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.search_text = ""
        self.subsystem = ""
        self.severity = ""
        self.setDynamicSortFilter(True)

    def set_filters(self, *, search: str | None = None, subsystem: str | None = None, severity: str | None = None) -> None:
        if search is not None:
            self.search_text = search.strip().casefold()
        if subsystem is not None:
            self.subsystem = subsystem
        if severity is not None:
            self.severity = severity
        self.invalidateFilter()

    def filterAcceptsRow(self, source_row: int, source_parent: QModelIndex) -> bool:
        model = self.sourceModel()
        definition = model.definition(source_row)
        if self.subsystem and definition.subsystem != self.subsystem:
            return False
        if self.severity and definition.severity.value != self.severity:
            return False
        haystack = " ".join((definition.code, definition.subsystem, tr(definition.title_key), tr(definition.message_key))).casefold()
        return not self.search_text or self.search_text in haystack
