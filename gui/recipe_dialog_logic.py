from __future__ import annotations

"""Binding, persistence, migration entry points, and live plan preview."""

import json
from copy import deepcopy
from pathlib import Path
from typing import Any

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QFileDialog, QListWidgetItem, QMessageBox, QTreeWidgetItem

from .measurement_execution_plan import build_measurement_execution_plan
from .recipe_store import ChannelRecipe, Recipe


def _parse_numbers(text: str, caster: type = float) -> list[Any]:
    values = [token.strip() for token in text.replace(";", ",").split(",")]
    return [caster(token) for token in values if token]


class RecipeDialogLogicMixin:
    def _set_combo_data(self, combo: Any, value: Any) -> None:
        index = combo.findData(value)
        combo.setCurrentIndex(index if index >= 0 else 0)

    def _reload_list(self, *_args: Any, preferred_id: str = "") -> None:
        preferred_id = preferred_id or (
            self.current_recipe.recipe_id if self.current_recipe is not None else ""
        )
        query = self.search_edit.text().strip().casefold()
        self.recipe_list.blockSignals(True)
        self.recipe_list.clear()
        selected = None
        for recipe in sorted(self.store.recipes, key=lambda item: item.name.casefold()):
            if query and query not in recipe.name.casefold():
                continue
            item = QListWidgetItem(f"{recipe.name}  v{recipe.version}")
            item.setData(Qt.ItemDataRole.UserRole, recipe.recipe_id)
            self.recipe_list.addItem(item)
            if recipe.recipe_id == preferred_id:
                selected = item
        self.recipe_list.blockSignals(False)
        if selected is not None:
            self.recipe_list.setCurrentItem(selected)
        elif self.recipe_list.count():
            self.recipe_list.setCurrentRow(0)
        else:
            self.current_recipe = None
            self._set_editor_enabled(False)

    def _load_selected(self, current: QListWidgetItem | None, _previous: Any = None) -> None:
        recipe_id = str(current.data(Qt.ItemDataRole.UserRole)) if current else ""
        recipe = self.store.get(recipe_id)
        self.current_recipe = deepcopy(recipe) if recipe is not None else None
        self._set_editor_enabled(self.current_recipe is not None)
        if self.current_recipe is not None:
            self._write_recipe_to_form(self.current_recipe)

    def _set_editor_enabled(self, enabled: bool) -> None:
        self.tabs.setEnabled(enabled)
        self.save_button.setEnabled(enabled)
        self.validate_button.setEnabled(enabled)
        self.export_button.setEnabled(enabled)
        self.delete_button.setEnabled(enabled)

    def _write_recipe_to_form(self, recipe: Recipe) -> None:
        self.name_edit.setText(recipe.name)
        self._set_combo_data(self.state_combo, recipe.state)
        self.description_edit.setPlainText(recipe.description)
        self.area_spin.setValue(recipe.geometry.active_area_cm2)
        self._set_combo_data(self.forward_polarity_combo, recipe.geometry.forward_polarity)
        self.id_value.setText(recipe.recipe_id)
        self.version_value.setText(str(recipe.version))
        for row, channel in enumerate(recipe.channels[:4]):
            self.channels_table.item(row, 0).setCheckState(
                Qt.CheckState.Checked if channel.enabled else Qt.CheckState.Unchecked
            )
            self.channels_table.item(row, 2).setText(f"{channel.area_cm2:g}")

        self.polarity_enabled_check.setChecked(recipe.polarity.enabled)
        self.dark_iv_enabled_check.setChecked(recipe.dark_iv.enabled)
        self.dark_stable_spin.setValue(recipe.dark_iv.dark_stabilization_s)
        self.dark_start_spin.setValue(recipe.dark_iv.start_v)
        self.dark_stop_spin.setValue(recipe.dark_iv.stop_v)
        self.dark_step_spin.setValue(recipe.dark_iv.step_v)
        self._set_combo_data(self.dark_direction_combo, recipe.dark_iv.direction)
        self.dark_dwell_spin.setValue(recipe.dark_iv.dwell_s)
        self.dark_compliance_spin.setValue(recipe.dark_iv.current_compliance_ma)
        self.dark_nplc_spin.setValue(recipe.dark_iv.nplc)
        self.dark_repeat_spin.setValue(recipe.dark_iv.repeat_count)
        self.dark_inter_delay_spin.setValue(recipe.dark_iv.inter_scan_delay_s)
        self.dark_return_zero_check.setChecked(recipe.dark_iv.return_to_zero)
        self.dark_output_off_check.setChecked(recipe.dark_iv.output_off_after)
        self._set_combo_data(
            self.dark_compliance_action_combo, recipe.dark_iv.compliance_action
        )
        self._set_dark_iv_widgets_enabled(recipe.dark_iv.enabled)

        matrix = recipe.el_matrix
        self.dark_frame_enabled_check.setChecked(matrix.dark_frame_enabled)
        self.matrix_current_density_edit.setText(
            ", ".join(f"{value:g}" for value in matrix.current_density_ma_cm2)
        )
        self.matrix_gain_edit.setText(", ".join(str(value) for value in matrix.gains_percent))
        self.matrix_exposure_edit.setText(
            ", ".join(f"{value:g}" for value in matrix.exposures_ms)
        )
        self.matrix_repeat_spin.setValue(matrix.repeat)
        self.matrix_voltage_compliance_spin.setValue(matrix.voltage_compliance_v)
        self.matrix_stabilization_spin.setValue(matrix.stabilization_ms)
        self.matrix_capture_timeout_spin.setValue(matrix.capture_timeout_s)

        if self.resolution_combo.findData(recipe.output.resolution_id) < 0:
            self.resolution_combo.addItem(
                f"已儲存模式（{recipe.output.resolution_id}）",
                recipe.output.resolution_id,
            )
        self._set_combo_data(self.resolution_combo, recipe.output.resolution_id)
        self.output_tiff_check.setChecked(recipe.output.format_tiff)
        self.output_png_check.setChecked(recipe.output.format_png)
        self.output_jpg_check.setChecked(recipe.output.format_jpg)
        self.output_jpg_footer_check.setChecked(recipe.output.format_jpg_with_footer)
        self.save_raw_check.setChecked(recipe.output.save_raw_frames)
        self.save_summary_csv_check.setChecked(recipe.output.save_summary_csv)
        self.save_json_check.setChecked(recipe.output.save_json)
        self.save_snapshot_check.setChecked(recipe.output.save_recipe_snapshot)
        self.export_pixel_csv_check.setChecked(recipe.output.export_pixel_csv)
        self.pixel_csv_raw_check.setChecked(recipe.output.pixel_csv_raw)
        self.pixel_csv_corrected_check.setChecked(recipe.output.pixel_csv_dark_corrected)
        self.pixel_csv_normalized_check.setChecked(
            recipe.output.pixel_csv_exposure_normalized
        )
        self._refresh_execution_plan()

    def _read_form_to_recipe(self) -> Recipe:
        recipe = deepcopy(self.current_recipe or Recipe())
        recipe.name = self.name_edit.text().strip()
        recipe.measurement_type = "el_sequence"
        recipe.state = str(self.state_combo.currentData())
        recipe.description = self.description_edit.toPlainText().strip()
        recipe.geometry.active_area_cm2 = self.area_spin.value()
        recipe.geometry.forward_polarity = str(self.forward_polarity_combo.currentData())
        recipe.channels = [
            ChannelRecipe(
                channel=f"CH{row + 1}",
                enabled=self.channels_table.item(row, 0).checkState()
                == Qt.CheckState.Checked,
                area_cm2=float(self.channels_table.item(row, 2).text()),
            )
            for row in range(4)
        ]
        recipe.polarity.enabled = self.polarity_enabled_check.isChecked()
        recipe.dark_iv.enabled = self.dark_iv_enabled_check.isChecked()
        recipe.dark_iv.dark_stabilization_s = self.dark_stable_spin.value()
        recipe.dark_iv.start_v = self.dark_start_spin.value()
        recipe.dark_iv.stop_v = self.dark_stop_spin.value()
        recipe.dark_iv.step_v = self.dark_step_spin.value()
        recipe.dark_iv.direction = str(self.dark_direction_combo.currentData())
        recipe.dark_iv.dwell_s = self.dark_dwell_spin.value()
        recipe.dark_iv.current_compliance_ma = self.dark_compliance_spin.value()
        recipe.dark_iv.nplc = self.dark_nplc_spin.value()
        recipe.dark_iv.repeat_count = self.dark_repeat_spin.value()
        recipe.dark_iv.inter_scan_delay_s = self.dark_inter_delay_spin.value()
        recipe.dark_iv.return_to_zero = self.dark_return_zero_check.isChecked()
        recipe.dark_iv.output_off_after = self.dark_output_off_check.isChecked()
        recipe.dark_iv.compliance_action = str(
            self.dark_compliance_action_combo.currentData()
        )

        recipe.el_matrix.dark_frame_enabled = self.dark_frame_enabled_check.isChecked()
        recipe.el_matrix.current_density_ma_cm2 = _parse_numbers(
            self.matrix_current_density_edit.text(), float
        )
        recipe.el_matrix.gains_percent = _parse_numbers(
            self.matrix_gain_edit.text(), int
        )
        recipe.el_matrix.exposures_ms = _parse_numbers(
            self.matrix_exposure_edit.text(), float
        )
        recipe.el_matrix.repeat = self.matrix_repeat_spin.value()
        recipe.el_matrix.voltage_compliance_v = self.matrix_voltage_compliance_spin.value()
        recipe.el_matrix.stabilization_ms = self.matrix_stabilization_spin.value()
        recipe.el_matrix.capture_timeout_s = self.matrix_capture_timeout_spin.value()

        recipe.output.resolution_id = str(self.resolution_combo.currentData())
        recipe.output.format_tiff = self.output_tiff_check.isChecked()
        recipe.output.format_png = self.output_png_check.isChecked()
        recipe.output.format_jpg = self.output_jpg_check.isChecked()
        recipe.output.format_jpg_with_footer = self.output_jpg_footer_check.isChecked()
        recipe.output.save_raw_frames = self.save_raw_check.isChecked()
        recipe.output.save_summary_csv = self.save_summary_csv_check.isChecked()
        recipe.output.save_json = self.save_json_check.isChecked()
        recipe.output.save_recipe_snapshot = self.save_snapshot_check.isChecked()
        recipe.output.export_pixel_csv = self.export_pixel_csv_check.isChecked()
        recipe.output.pixel_csv_raw = self.pixel_csv_raw_check.isChecked()
        recipe.output.pixel_csv_dark_corrected = self.pixel_csv_corrected_check.isChecked()
        recipe.output.pixel_csv_exposure_normalized = (
            self.pixel_csv_normalized_check.isChecked()
        )
        return recipe

    def _refresh_execution_plan(self, *_args: Any) -> None:
        if self.current_recipe is None:
            self.execution_tree.clear()
            return
        try:
            recipe = self._read_form_to_recipe()
            plan = build_measurement_execution_plan(recipe)
        except (TypeError, ValueError):
            return
        self.execution_tree.clear()

        def add(parent: Any, step: Any, prefix: str = "") -> None:
            item = QTreeWidgetItem([prefix + step.title])
            parent.addChild(item) if isinstance(parent, QTreeWidgetItem) else parent.addTopLevelItem(item)
            for child in step.children:
                add(item, child)

        for index, step in enumerate(plan.steps, start=1):
            add(self.execution_tree, step, f"{index}. ")
        self.execution_tree.expandAll()

    def _connect_summary_updates(self) -> None:
        widgets = (
            self.name_edit, self.state_combo, self.area_spin, self.forward_polarity_combo,
            self.channels_table, self.polarity_enabled_check, self.dark_iv_enabled_check,
            self.dark_stable_spin, self.dark_start_spin, self.dark_stop_spin,
            self.dark_step_spin, self.dark_direction_combo, self.dark_dwell_spin,
            self.dark_compliance_spin, self.dark_nplc_spin, self.dark_repeat_spin,
            self.dark_inter_delay_spin, self.dark_frame_enabled_check,
            self.matrix_current_density_edit,
            self.matrix_gain_edit, self.matrix_exposure_edit, self.matrix_repeat_spin,
            self.matrix_voltage_compliance_spin, self.matrix_stabilization_spin,
            self.matrix_capture_timeout_spin, self.resolution_combo,
            self.output_tiff_check, self.output_png_check, self.output_jpg_check,
            self.output_jpg_footer_check,
        )
        for widget in widgets:
            for signal_name in (
                "textChanged", "toggled", "valueChanged", "currentIndexChanged",
                "itemChanged",
            ):
                signal = getattr(widget, signal_name, None)
                if signal is not None:
                    signal.connect(self._refresh_execution_plan)
                    break

    def _new_recipe(self) -> None:
        recipe = Recipe()
        existing = {item.name for item in self.store.recipes}
        index = 1
        while recipe.name in existing:
            index += 1
            recipe.name = f"新 EL Recipe {index}"
        self.store.upsert(recipe)
        self.current_recipe = deepcopy(recipe)
        self._reload_list(preferred_id=recipe.recipe_id)
        self.recipes_changed.emit()

    def _copy_recipe(self) -> None:
        if self.current_recipe is None:
            return
        copied = self._read_form_to_recipe().clone()
        self.store.upsert(copied)
        self.current_recipe = deepcopy(copied)
        self._reload_list(preferred_id=copied.recipe_id)
        self.recipes_changed.emit()

    def _delete_recipe(self) -> None:
        if self.current_recipe is None:
            return
        if QMessageBox.question(
            self, "刪除 Recipe", f"確定刪除「{self.current_recipe.name}」？"
        ) != QMessageBox.StandardButton.Yes:
            return
        self.store.delete(self.current_recipe.recipe_id)
        self.current_recipe = None
        self._reload_list()
        self.recipes_changed.emit()

    def _save_current(self) -> None:
        if self.current_recipe is None:
            return
        try:
            recipe = self._read_form_to_recipe()
        except ValueError as exc:
            QMessageBox.warning(self, "Recipe 欄位錯誤", str(exc))
            return
        errors = recipe.validate()
        if recipe.state == "active" and errors:
            self._show_validation(errors, recipe.validation_warnings())
            return
        self.store.upsert(recipe)
        self.current_recipe = deepcopy(self.store.get(recipe.recipe_id) or recipe)
        self._write_recipe_to_form(self.current_recipe)
        self._reload_list(preferred_id=recipe.recipe_id)
        self.recipes_changed.emit()
        QMessageBox.information(self, "已儲存", f"已儲存 Recipe「{recipe.name}」。")

    def _validate_current(self) -> None:
        if self.current_recipe is None:
            return
        try:
            recipe = self._read_form_to_recipe()
            self._show_validation(
                recipe.validate(),
                recipe.validation_warnings(),
            )
        except ValueError as exc:
            self._show_validation([str(exc)], [])

    def _show_validation(self, errors: list[str], warnings: list[str]) -> None:
        if errors:
            text = "錯誤：\n• " + "\n• ".join(errors)
            self.validation_label.setStyleSheet("color:#a01818; padding:6px;")
        elif warnings:
            text = "可儲存，但請確認：\n• " + "\n• ".join(warnings)
            self.validation_label.setStyleSheet("color:#8a5a00; padding:6px;")
        else:
            text = "Recipe 驗證通過"
            self.validation_label.setStyleSheet("color:#16823b; padding:6px;")
        self.validation_label.setText(text)

    def _import_recipe(self) -> None:
        filename, _ = QFileDialog.getOpenFileName(self, "匯入 Recipe", "", "JSON (*.json)")
        if not filename:
            return
        try:
            payload = json.loads(Path(filename).read_text(encoding="utf-8"))
            recipe = self.store.import_payload(payload)
        except Exception as exc:
            QMessageBox.warning(self, "匯入失敗", str(exc))
            return
        self.current_recipe = deepcopy(recipe)
        self._reload_list(preferred_id=recipe.recipe_id)
        self.recipes_changed.emit()

    def _export_recipe(self) -> None:
        if self.current_recipe is None:
            return
        recipe = self._read_form_to_recipe()
        filename, _ = QFileDialog.getSaveFileName(
            self, "匯出 Recipe JSON", f"{recipe.name}.json", "JSON (*.json)"
        )
        if filename:
            Path(filename).write_text(
                json.dumps(
                    {"schema_version": self.store.schema_version, "recipe": recipe.to_dict()},
                    ensure_ascii=False,
                    indent=2,
                ),
                encoding="utf-8",
            )
