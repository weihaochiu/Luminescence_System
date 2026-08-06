from __future__ import annotations

"""EL point-table editing and HDR/non-HDR presentation rules."""

import math

from PySide6.QtCore import QSignalBlocker, Qt
from PySide6.QtGui import QBrush, QColor
from PySide6.QtWidgets import QMessageBox, QTableWidgetItem

from .recipe_store import ELPoint


class RecipeDialogPointsMixin:
    """Own point generation, parsing, camera cells, and HDR table state."""

    def _write_points_table(self, points: list[ELPoint]) -> None:
        with QSignalBlocker(self.points_table):
            self.points_table.setRowCount(0)
            for point in points:
                self._append_point_row(point)

    def _append_point_row(self, point: ELPoint) -> None:
        row = self.points_table.rowCount()
        self.points_table.insertRow(row)
        values = [
            "1" if point.enabled else "0",
            f"{point.setpoint:g}",
            f"{point.dwell_s:g}",
            f"{point.exposure_ms:g}",
            str(point.gain_percent),
            str(point.frame_count),
            f"{point.frame_interval_s:g}",
        ]
        for column, value in enumerate(values):
            item = QTableWidgetItem(value)
            if column == 0:
                item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
                item.setCheckState(Qt.CheckState.Checked if value == "1" else Qt.CheckState.Unchecked)
                item.setText("")
            elif column in self.CAMERA_COLUMNS:
                item.setData(self.CAMERA_VALUE_ROLE, value)
            self.points_table.setItem(row, column, item)

    def _read_points_table(self) -> list[ELPoint]:
        points: list[ELPoint] = []
        for row in range(self.points_table.rowCount()):
            try:
                camera_values = [
                    self._camera_cell_value(row, column)
                    for column in self.CAMERA_COLUMNS
                ]
                points.append(
                    ELPoint(
                        enabled=self.points_table.item(row, 0).checkState() == Qt.CheckState.Checked,
                        setpoint=float(self.points_table.item(row, 1).text()),
                        dwell_s=float(self.points_table.item(row, 2).text()),
                        exposure_ms=float(camera_values[0]),
                        gain_percent=int(float(camera_values[1])),
                        frame_count=int(float(camera_values[2])),
                        frame_interval_s=float(camera_values[3]),
                    )
                )
            except (AttributeError, TypeError, ValueError):
                enabled_item = self.points_table.item(row, 0)
                points.append(
                    ELPoint(
                        enabled=enabled_item is None or enabled_item.checkState() == Qt.CheckState.Checked,
                        setpoint=-1,
                        exposure_ms=0,
                        gain_percent=-1,
                        frame_count=0,
                        frame_interval_s=-1,
                    )
                )
        return points

    def _generate_points(self) -> None:
        mode = str(self.builder_mode_combo.currentData())
        values: list[float] = []
        try:
            if mode == "linear":
                start, stop, step = self.builder_start_spin.value(), self.builder_stop_spin.value(), self.builder_step_spin.value()
                count = int(math.floor((stop - start) / step + 1e-9)) + 1
                if count < 1 or count > 5000:
                    raise ValueError("線性掃描點數必須介於 1–5000")
                values = [start + index * step for index in range(count)]
                if values[-1] < stop - step * 1e-6:
                    values.append(stop)
            elif mode == "log":
                start, stop, count = self.builder_start_spin.value(), self.builder_stop_spin.value(), self.builder_count_spin.value()
                if start <= 0 or stop <= start:
                    raise ValueError("對數掃描需要 0 < Start < Stop")
                ratio = (stop / start) ** (1 / (count - 1))
                values = [start * ratio**index for index in range(count)]
            else:
                tokens = self.builder_custom_edit.text().replace(",", " ").replace(";", " ").split()
                values = [float(token) for token in tokens]
                if not values:
                    raise ValueError("自訂列表不可空白")
            if any(value <= 0 for value in values):
                raise ValueError("EL 設定值必須大於 0")
        except ValueError as exc:
            QMessageBox.warning(self, "無法產生點位", str(exc))
            return
        points = [
            ELPoint(
                setpoint=value,
                exposure_ms=self.exposure_spin.value(),
                gain_percent=self.gain_spin.value(),
                frame_count=self.frames_spin.value(),
                frame_interval_s=self.frame_interval_spin.value(),
            )
            for value in values
        ]
        self._write_points_table(points)
        self._sync_hdr_controls()
        self._update_summary()

    def _add_point(self) -> None:
        self._append_point_row(
            ELPoint(
                exposure_ms=self.exposure_spin.value(),
                gain_percent=self.gain_spin.value(),
                frame_count=self.frames_spin.value(),
                frame_interval_s=self.frame_interval_spin.value(),
            )
        )
        self._sync_hdr_controls()
        self._update_summary()

    def _delete_selected_points(self) -> None:
        rows = sorted({index.row() for index in self.points_table.selectedIndexes()}, reverse=True)
        for row in rows:
            self.points_table.removeRow(row)
        self._update_summary()

    def _fill_selected_camera(self) -> None:
        rows = sorted({index.row() for index in self.points_table.selectedIndexes()})
        for row in rows:
            values = (
                f"{self.exposure_spin.value():g}",
                str(self.gain_spin.value()),
                str(self.frames_spin.value()),
                f"{self.frame_interval_spin.value():g}",
            )
            for column, value in zip(self.CAMERA_COLUMNS, values):
                item = self.points_table.item(row, column)
                item.setData(self.CAMERA_VALUE_ROLE, value)
                item.setText(value)
        self._update_summary()

    def _on_pixel_csv_toggled(self, checked: bool) -> None:
        if checked:
            answer = QMessageBox.warning(
                self,
                "全解析度像素 CSV 容量提醒",
                "IMX585 全解析度 3840 × 2160 包含約 829 萬個像素。\n\n"
                "每一種像素 CSV（Raw、Dark-corrected 或 Exposure-normalized）"
                "通常可能占用約 50–150 MB；若三種皆輸出，單一 EL 點可能達"
                "約 150–450 MB。多點掃描的總容量可能達數 GB。實際大小會因"
                "像素數值與 CSV 格式而異。\n\n"
                "即使不啟用此選項，只要保留未經影像增強的高位深 TIFF、"
                "Master Dark 與 metadata，之後仍可產生像素 CSV。\n\n"
                "仍要啟用全解析度像素 CSV 嗎？",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No,
            )
            if answer != QMessageBox.StandardButton.Yes:
                with QSignalBlocker(self.export_pixel_csv_check):
                    self.export_pixel_csv_check.setChecked(False)
        self._sync_pixel_csv_options()
        self._update_summary()

    def _sync_pixel_csv_options(self, *_args: object) -> None:
        enabled = self.export_pixel_csv_check.isChecked()
        self.pixel_csv_raw_check.setEnabled(enabled)
        self.pixel_csv_corrected_check.setEnabled(enabled)
        self.pixel_csv_normalized_check.setEnabled(enabled)

    def _sync_hdr_controls(self, *_args: object) -> None:
        enabled = self.hdr_enabled_check.isChecked()
        if enabled:
            self.image_format_combo.setCurrentText("TIFF")
            for check in (
                self.save_raw_check,
                self.dark_save_raw_check,
                self.dark_save_master_check,
            ):
                check.setChecked(True)
        for widget in (
            self.exposure_spin,
            self.gain_spin,
            self.frames_spin,
            self.frame_interval_spin,
            self.frame_handling_combo,
        ):
            widget.setEnabled(not enabled)
        self.image_format_combo.setEnabled(not enabled)
        self.save_raw_check.setEnabled(not enabled)
        self.dark_save_raw_check.setEnabled(not enabled)
        self.dark_save_master_check.setEnabled(not enabled)
        for widget in (
            self.dark_frames_per_profile_spin,
            self.dark_frame_interval_spin,
            self.dark_camera_delay_spin,
            self.dark_combine_combo,
            self.dark_after_el_check,
        ):
            widget.setEnabled(not enabled)
        self.fill_camera_button.setEnabled(not enabled)
        self.hdr_status_label.setText(
            "已啟用 HDR：下方相機欄位由「設定 → HDR」及 T0 Profile 控制。"
            if enabled
            else "未啟用：請在下方表格逐列設定 Exposure、Gain、Frames 與間隔。"
        )
        self.hdr_status_label.setStyleSheet(
            "color:#1b5e20; font-weight:600;" if enabled else "color:#4f5b62;"
        )
        with QSignalBlocker(self.points_table):
            for row in range(self.points_table.rowCount()):
                for column in self.CAMERA_COLUMNS:
                    item = self.points_table.item(row, column)
                    if item is None:
                        continue
                    if enabled:
                        if item.text() != self.HDR_CELL_TEXT:
                            item.setData(self.CAMERA_VALUE_ROLE, item.text())
                        item.setText(self.HDR_CELL_TEXT)
                        item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsEditable)
                        item.setBackground(QColor("#e5e7eb"))
                        item.setForeground(QColor("#6b7280"))
                        item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
                        item.setToolTip("HDR 啟用時由「設定 → HDR」及 T0 Profile 控制")
                    else:
                        stored_value = item.data(self.CAMERA_VALUE_ROLE)
                        if stored_value is not None:
                            item.setText(str(stored_value))
                        item.setFlags(item.flags() | Qt.ItemFlag.ItemIsEditable)
                        item.setBackground(QBrush())
                        item.setForeground(QBrush())
                        item.setTextAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
                        item.setToolTip("HDR 關閉時為必填")
        self._update_summary()

    def _camera_cell_value(self, row: int, column: int) -> str:
        item = self.points_table.item(row, column)
        if item is None:
            raise ValueError("相機欄位不存在")
        stored_value = item.data(self.CAMERA_VALUE_ROLE)
        if self.hdr_enabled_check.isChecked() and stored_value is not None:
            return str(stored_value)
        return item.text()

    def _sync_drive_mode(self) -> None:
        current_mode = self.drive_mode_combo.currentData() == "current"
        self.el_voltage_compliance_spin.setEnabled(current_mode)
        self.el_current_compliance_spin.setEnabled(not current_mode)
        wanted = "current_density" if current_mode else "voltage"
        if current_mode and self.basis_combo.currentData() == "voltage":
            self._set_combo_data(self.basis_combo, wanted)
        elif not current_mode:
            self._set_combo_data(self.basis_combo, wanted)
        self._update_summary()
