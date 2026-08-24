from __future__ import annotations

"""Measurement run context bar: Sample IDs, output directory, and controls."""

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QFrame,
    QGridLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from core.i18n import i18n, tr

from .responsive_layout import LayoutMode


class MeasurementControlBar(QFrame):
    sample_ids_changed = Signal()

    def __init__(self, parent: QFrame | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("measurementBar")
        self.layout_mode = LayoutMode.WIDE

        self.sample_label = QLabel(tr("measurement.sample_information"))
        self.sample_container = QWidget()
        self.sample_layout = QVBoxLayout(self.sample_container)
        self.sample_layout.setContentsMargins(0, 0, 0, 0)
        self.sample_layout.setSpacing(3)
        self.sample_id_edits: dict[str, QLineEdit] = {}
        self.sample_id_edit = QLineEdit()  # compatibility alias, replaced below
        self.set_active_channels(())

        self.path_label = QLabel(tr("measurement.output_directory"))
        self.measurement_path_edit = QLineEdit()
        self.measurement_path_edit.setReadOnly(True)
        self.measurement_path_edit.setPlaceholderText(tr("measurement.select_output_directory"))
        self.measurement_path_edit.textChanged.connect(self.measurement_path_edit.setToolTip)
        self.measurement_path_button = QPushButton(tr("common.browse"))

        self.recipe_label = QLabel("Recipe")
        self.selected_recipe_label = QLabel(tr("common.not_selected"))
        self.selected_recipe_label.setWordWrap(True)
        self.white_light_status = QLabel(tr("relay.white_light_disconnected"))
        self.white_light_button = QPushButton(tr("relay.white_light_on"))
        self.start_measurement_button = QPushButton(tr("measurement.start"))
        self.start_measurement_button.setObjectName("startMeasurement")
        self.stop_measurement_button = QPushButton(tr("common.stop"))
        self.stop_measurement_button.setObjectName("stopMeasurement")
        self.stop_measurement_button.setEnabled(False)

        self.grid = QGridLayout(self)
        self.grid.setContentsMargins(10, 7, 10, 7)
        self.grid.setHorizontalSpacing(7)
        self.grid.setVerticalSpacing(6)
        self._configure_size_policies()
        self.set_layout_mode(LayoutMode.WIDE)
        i18n.language_changed.connect(self.retranslate)

    def retranslate(self, _language: str = "") -> None:
        self.sample_label.setText(tr("measurement.sample_information"))
        self.path_label.setText(tr("measurement.output_directory"))
        self.measurement_path_edit.setPlaceholderText(tr("measurement.select_output_directory"))
        self.measurement_path_button.setText(tr("common.browse"))
        self.recipe_label.setText("Recipe")
        if not self.sample_id_edits:
            self.sample_id_edit.setPlaceholderText(tr("measurement.active_channels_placeholder"))
        else:
            for channel, edit in self.sample_id_edits.items():
                edit.setPlaceholderText(tr("measurement.sample_id_for_channel", channel=channel))
        self.start_measurement_button.setText(tr("measurement.start"))
        self.stop_measurement_button.setText(tr("common.stop"))
        self.refresh_metrics()

    def set_active_channels(self, channels: tuple[str, ...] | list[str]) -> None:
        previous = self.sample_ids()
        while self.sample_layout.count():
            item = self.sample_layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()
        self.sample_id_edits = {}
        for channel in channels:
            edit = QLineEdit()
            edit.setObjectName(f"sampleId_{channel}")
            edit.setPlaceholderText(tr("measurement.sample_id_for_channel", channel=channel))
            edit.setText(previous.get(channel, ""))
            edit.textChanged.connect(lambda _text: self.sample_ids_changed.emit())
            self.sample_layout.addWidget(edit)
            self.sample_id_edits[channel] = edit
        if self.sample_id_edits:
            self.sample_id_edit = next(iter(self.sample_id_edits.values()))
        else:
            placeholder = QLineEdit()
            placeholder.setPlaceholderText(tr("measurement.active_channels_placeholder"))
            placeholder.setEnabled(False)
            self.sample_layout.addWidget(placeholder)
            self.sample_id_edit = placeholder
        self.sample_ids_changed.emit()

    def sample_ids(self) -> dict[str, str]:
        return {
            channel: edit.text().strip()
            for channel, edit in self.sample_id_edits.items()
        }

    def missing_sample_channels(self) -> list[str]:
        return [channel for channel, value in self.sample_ids().items() if not value]

    def _configure_size_policies(self) -> None:
        self.measurement_path_edit.setSizePolicy(
            QSizePolicy.Policy.MinimumExpanding, QSizePolicy.Policy.Fixed
        )
        self.selected_recipe_label.setSizePolicy(
            QSizePolicy.Policy.MinimumExpanding, QSizePolicy.Policy.Preferred
        )
        self.refresh_metrics()

    def refresh_metrics(self) -> None:
        metrics = self.fontMetrics()
        self.sample_container.setMinimumWidth(metrics.horizontalAdvance("M" * 14))
        self.measurement_path_edit.setMinimumWidth(metrics.horizontalAdvance("M" * 16))

    def recommended_breakpoints(self) -> tuple[int, int]:
        return 1080, 1500

    def set_layout_mode(self, mode: LayoutMode) -> None:
        self.layout_mode = LayoutMode(mode)
        while self.grid.count():
            self.grid.takeAt(0)
        for index in range(12):
            self.grid.setColumnStretch(index, 0)
        if self.layout_mode is LayoutMode.WIDE:
            self._layout_wide()
        elif self.layout_mode is LayoutMode.STANDARD:
            self._layout_standard()
        else:
            self._layout_compact()

    def _layout_wide(self) -> None:
        widgets = (
            self.sample_label, self.sample_container, self.path_label,
            self.measurement_path_edit, self.measurement_path_button,
            self.recipe_label, self.selected_recipe_label,
            self.white_light_status, self.white_light_button,
            self.start_measurement_button, self.stop_measurement_button,
        )
        for column, widget in enumerate(widgets):
            self.grid.addWidget(widget, 0, column)
        self.grid.setColumnStretch(3, 2)
        self.grid.setColumnStretch(6, 1)

    def _layout_standard(self) -> None:
        self.grid.addWidget(self.sample_label, 0, 0)
        self.grid.addWidget(self.sample_container, 0, 1)
        self.grid.addWidget(self.recipe_label, 0, 2)
        self.grid.addWidget(self.selected_recipe_label, 0, 3, 1, 2)
        self.grid.addWidget(self.path_label, 1, 0)
        self.grid.addWidget(self.measurement_path_edit, 1, 1, 1, 4)
        self.grid.addWidget(self.measurement_path_button, 1, 5)
        self.grid.addWidget(self.white_light_status, 2, 0)
        self.grid.addWidget(self.white_light_button, 2, 1)
        self.grid.addWidget(self.start_measurement_button, 2, 3)
        self.grid.addWidget(self.stop_measurement_button, 2, 4)

    def _layout_compact(self) -> None:
        self.grid.addWidget(self.sample_label, 0, 0)
        self.grid.addWidget(self.sample_container, 0, 1, 1, 4)
        self.grid.addWidget(self.recipe_label, 1, 0)
        self.grid.addWidget(self.selected_recipe_label, 1, 1, 1, 4)
        self.grid.addWidget(self.path_label, 2, 0)
        self.grid.addWidget(self.measurement_path_edit, 2, 1, 1, 3)
        self.grid.addWidget(self.measurement_path_button, 2, 4)
        self.grid.addWidget(self.white_light_status, 3, 0, 1, 5)
        self.grid.addWidget(self.white_light_button, 4, 0)
        self.grid.addWidget(self.start_measurement_button, 4, 1)
        self.grid.addWidget(self.stop_measurement_button, 4, 2, 1, 3)
