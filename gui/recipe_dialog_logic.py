from __future__ import annotations

"""Recipe form binding, CRUD, validation, summaries, and JSON transfer."""

import json
from copy import deepcopy
from pathlib import Path

from PySide6.QtCore import QSignalBlocker, Qt
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDoubleSpinBox,
    QFileDialog,
    QLineEdit,
    QListWidgetItem,
    QMessageBox,
    QSpinBox,
    QTextEdit,
    QWidget,
)

from .recipe_store import ChannelRecipe, Recipe


def _parse_number_list(text: str, *, integers: bool = False) -> list[float] | list[int]:
    tokens = text.replace("，", ",").replace("\n", ",").split(",")
    values = [token.strip() for token in tokens if token.strip()]
    if integers:
        return [int(token) for token in values]
    return [float(token) for token in values]


class RecipeDialogLogicMixin:
    """Own Recipe data flow while leaving page and point widgets independent."""

    def _reload_list(self, *_args: object, preferred_id: str = "") -> None:
        if not preferred_id and self.current_recipe is not None:
            preferred_id = self.current_recipe.recipe_id
        query = self.search_edit.text().strip().casefold()
        self.recipe_list.clear()
        selected_item: QListWidgetItem | None = None
        for recipe in sorted(self.store.recipes, key=lambda item: item.name.casefold()):
            if query and query not in recipe.name.casefold() and query not in recipe.description.casefold():
                continue
            state = {"active": "啟用", "draft": "草稿", "disabled": "停用"}.get(recipe.state, recipe.state)
            item = QListWidgetItem(f"{recipe.name}\n{state}｜v{recipe.version}｜{len(recipe.enabled_points())} 點")
            item.setData(Qt.ItemDataRole.UserRole, recipe.recipe_id)
            self.recipe_list.addItem(item)
            if recipe.recipe_id == preferred_id:
                selected_item = item
        if selected_item is not None:
            self.recipe_list.setCurrentItem(selected_item)
        elif self.recipe_list.count():
            self.recipe_list.setCurrentRow(0)
        else:
            self._set_editor_enabled(False)

    def _load_selected(self, current: QListWidgetItem | None, _previous: QListWidgetItem | None) -> None:
        if current is None:
            return
        recipe = self.store.get(str(current.data(Qt.ItemDataRole.UserRole)))
        if recipe is None:
            return
        self.current_recipe = deepcopy(recipe)
        self._write_recipe_to_form(self.current_recipe)
        self._set_editor_enabled(True)
        self._update_summary()

    def _write_recipe_to_form(self, recipe: Recipe) -> None:
        self.name_edit.setText(recipe.name)
        self._set_combo_data(self.state_combo, recipe.state)
        self.description_edit.setPlainText(recipe.description)
        self.area_spin.setValue(recipe.geometry.active_area_cm2)
        self._set_combo_data(self.forward_polarity_combo, recipe.geometry.forward_polarity)
        self.device_id_required_check.setChecked(recipe.geometry.device_id_required)
        self.id_value.setText(recipe.recipe_id)
        self.version_value.setText(f"v{recipe.version}")
        with QSignalBlocker(self.channels_table):
            for row, channel in enumerate(recipe.channels[:4]):
                self.channels_table.item(row, 0).setCheckState(
                    Qt.CheckState.Checked if channel.enabled else Qt.CheckState.Unchecked
                )
                self.channels_table.item(row, 1).setText(channel.channel)
                self.channels_table.item(row, 2).setText(channel.sample_id)
                self.channels_table.item(row, 3).setText(f"{channel.area_cm2:g}")
        matrix = recipe.el_matrix
        self.matrix_current_density_edit.setText(
            ", ".join(f"{value:g}" for value in matrix.current_density_ma_cm2)
        )
        self.matrix_gain_edit.setText(", ".join(str(value) for value in matrix.gains_percent))
        self.matrix_exposure_edit.setText(", ".join(f"{value:g}" for value in matrix.exposures_ms))
        self.matrix_repeat_spin.setValue(matrix.repeat)
        self.matrix_voltage_compliance_spin.setValue(matrix.voltage_compliance_v)
        self.matrix_stabilization_spin.setValue(matrix.stabilization_ms)
        self.shared_dark_enabled_check.setChecked(matrix.shared_dark_enabled)
        self.polarity_required_check.setChecked(recipe.polarity.enabled)


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
        self._set_combo_data(self.dark_compliance_action_combo, recipe.dark_iv.compliance_action)

        self.exposure_spin.setValue(recipe.camera.exposure_ms)
        self.gain_spin.setValue(recipe.camera.gain_percent)
        self.frames_spin.setValue(recipe.camera.frame_count)
        self.frame_interval_spin.setValue(recipe.camera.frame_interval_s)
        self._set_combo_data(self.frame_handling_combo, recipe.camera.frame_handling)
        self._set_combo_data(self.trigger_combo, recipe.camera.trigger_mode)
        self.timeout_spin.setValue(recipe.camera.capture_timeout_s)

        self.hdr_enabled_check.setChecked(recipe.hdr.enabled)

        self._set_combo_data(self.drive_mode_combo, recipe.el_sweep.drive_mode)
        self._set_combo_data(self.basis_combo, recipe.el_sweep.setpoint_basis)
        self._set_combo_data(self.el_direction_combo, recipe.el_sweep.scan_direction)
        self.el_repeat_spin.setValue(recipe.el_sweep.repeat_count)
        self.el_inter_delay_spin.setValue(recipe.el_sweep.inter_scan_delay_s)
        self.el_voltage_compliance_spin.setValue(recipe.el_sweep.voltage_compliance_v)
        self.el_current_compliance_spin.setValue(recipe.el_sweep.current_compliance_ma)
        self._write_points_table(recipe.el_sweep.points)

        self.dark_frames_per_profile_spin.setValue(recipe.dark_frames.frames_per_profile)
        self.dark_frame_interval_spin.setValue(recipe.dark_frames.frame_interval_s)
        self.dark_camera_delay_spin.setValue(recipe.dark_frames.camera_switch_delay_s)
        self._set_combo_data(self.dark_combine_combo, recipe.dark_frames.combine_method)
        self.dark_save_raw_check.setChecked(recipe.dark_frames.save_raw_frames)
        self.dark_save_master_check.setChecked(recipe.dark_frames.save_master_dark)
        self.dark_after_el_check.setChecked(recipe.dark_frames.capture_after_el)

        self._set_combo_data(self.device_match_combo, recipe.smu.device_match)
        self.visa_edit.setText(recipe.smu.visa_address)
        self.max_current_spin.setValue(recipe.safety.max_current_ma)
        self.max_voltage_spin.setValue(recipe.safety.max_voltage_v)
        self.max_power_spin.setValue(recipe.safety.max_power_mw)
        self.max_output_time_spin.setValue(recipe.safety.max_output_time_s)
        self.max_recipe_time_spin.setValue(recipe.safety.max_recipe_time_s)
        self.stop_camera_check.setChecked(recipe.safety.stop_on_camera_error)
        self.stop_smu_check.setChecked(recipe.safety.stop_on_smu_error)

        self.output_root_edit.setText(recipe.output.root_directory)
        self.sample_required_check.setChecked(recipe.output.sample_id_required)
        self.image_format_combo.setCurrentText(recipe.output.image_format)
        self.save_raw_check.setChecked(recipe.output.save_raw_frames)
        self.save_summary_csv_check.setChecked(recipe.output.save_summary_csv)
        self.save_json_check.setChecked(recipe.output.save_json)
        self.save_snapshot_check.setChecked(recipe.output.save_recipe_snapshot)
        with QSignalBlocker(self.export_pixel_csv_check):
            self.export_pixel_csv_check.setChecked(recipe.output.export_pixel_csv)
        self.pixel_csv_raw_check.setChecked(recipe.output.pixel_csv_raw)
        self.pixel_csv_corrected_check.setChecked(recipe.output.pixel_csv_dark_corrected)
        self.pixel_csv_normalized_check.setChecked(recipe.output.pixel_csv_exposure_normalized)
        self._sync_pixel_csv_options()
        self.visa_edit.setEnabled(recipe.smu.device_match == "specific")
        self._sync_hdr_controls()

    def _read_form_to_recipe(self) -> Recipe:
        recipe = deepcopy(self.current_recipe or Recipe())
        recipe.name = self.name_edit.text().strip()
        recipe.measurement_type = "el_sequence"
        recipe.state = str(self.state_combo.currentData())
        recipe.description = self.description_edit.toPlainText().strip()
        recipe.geometry.active_area_cm2 = self.area_spin.value()
        recipe.geometry.forward_polarity = str(self.forward_polarity_combo.currentData())
        recipe.geometry.device_id_required = self.device_id_required_check.isChecked()

        channels: list[ChannelRecipe] = []
        for row in range(self.channels_table.rowCount()):
            area_text = self.channels_table.item(row, 3).text().strip()
            try:
                area = float(area_text)
            except ValueError:
                area = float("nan")
            channels.append(ChannelRecipe(
                channel=f"CH{row + 1}",
                enabled=self.channels_table.item(row, 0).checkState() == Qt.CheckState.Checked,
                sample_id=self.channels_table.item(row, 2).text(),
                area_cm2=area,
            ))
        recipe.channels = channels
        recipe.polarity.enabled = self.polarity_required_check.isChecked()
        try:
            recipe.el_matrix.current_density_ma_cm2 = list(
                _parse_number_list(self.matrix_current_density_edit.text())
            )
        except ValueError:
            recipe.el_matrix.current_density_ma_cm2 = [float("nan")]
        try:
            recipe.el_matrix.gains_percent = list(
                _parse_number_list(self.matrix_gain_edit.text(), integers=True)
            )
        except ValueError:
            recipe.el_matrix.gains_percent = [-1]
        try:
            recipe.el_matrix.exposures_ms = list(
                _parse_number_list(self.matrix_exposure_edit.text())
            )
        except ValueError:
            recipe.el_matrix.exposures_ms = [float("nan")]
        recipe.el_matrix.repeat = self.matrix_repeat_spin.value()
        recipe.el_matrix.voltage_compliance_v = self.matrix_voltage_compliance_spin.value()
        recipe.el_matrix.stabilization_ms = self.matrix_stabilization_spin.value()
        recipe.el_matrix.shared_dark_enabled = self.shared_dark_enabled_check.isChecked()

        recipe.dark_iv.enabled = True
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
        recipe.dark_iv.compliance_action = str(self.dark_compliance_action_combo.currentData())

        recipe.camera.exposure_ms = self.exposure_spin.value()
        recipe.camera.gain_percent = self.gain_spin.value()
        recipe.camera.frame_count = self.frames_spin.value()
        recipe.camera.frame_interval_s = self.frame_interval_spin.value()
        recipe.camera.frame_handling = str(self.frame_handling_combo.currentData())
        recipe.camera.trigger_mode = str(self.trigger_combo.currentData())
        recipe.camera.capture_timeout_s = self.timeout_spin.value()

        recipe.hdr.enabled = self.hdr_enabled_check.isChecked()

        recipe.el_sweep.drive_mode = str(self.drive_mode_combo.currentData())
        recipe.el_sweep.setpoint_basis = str(self.basis_combo.currentData())
        recipe.el_sweep.scan_direction = str(self.el_direction_combo.currentData())
        recipe.el_sweep.repeat_count = self.el_repeat_spin.value()
        recipe.el_sweep.inter_scan_delay_s = self.el_inter_delay_spin.value()
        recipe.el_sweep.voltage_compliance_v = self.el_voltage_compliance_spin.value()
        recipe.el_sweep.current_compliance_ma = self.el_current_compliance_spin.value()
        recipe.el_sweep.points = self._read_points_table()

        recipe.dark_frames.frames_per_profile = self.dark_frames_per_profile_spin.value()
        recipe.dark_frames.frame_interval_s = self.dark_frame_interval_spin.value()
        recipe.dark_frames.camera_switch_delay_s = self.dark_camera_delay_spin.value()
        recipe.dark_frames.combine_method = str(self.dark_combine_combo.currentData())
        recipe.dark_frames.save_raw_frames = self.dark_save_raw_check.isChecked()
        recipe.dark_frames.save_master_dark = self.dark_save_master_check.isChecked()
        recipe.dark_frames.capture_after_el = self.dark_after_el_check.isChecked()

        recipe.smu.device_match = str(self.device_match_combo.currentData())
        recipe.smu.visa_address = self.visa_edit.text().strip()
        recipe.safety.max_current_ma = self.max_current_spin.value()
        recipe.safety.max_voltage_v = self.max_voltage_spin.value()
        recipe.safety.max_power_mw = self.max_power_spin.value()
        recipe.safety.max_output_time_s = self.max_output_time_spin.value()
        recipe.safety.max_recipe_time_s = self.max_recipe_time_spin.value()
        recipe.safety.stop_on_camera_error = self.stop_camera_check.isChecked()
        recipe.safety.stop_on_smu_error = self.stop_smu_check.isChecked()

        recipe.output.root_directory = self.output_root_edit.text().strip()
        recipe.output.sample_id_required = self.sample_required_check.isChecked()
        recipe.output.image_format = self.image_format_combo.currentText()
        recipe.output.save_raw_frames = self.save_raw_check.isChecked()
        recipe.output.save_summary_csv = self.save_summary_csv_check.isChecked()
        recipe.output.save_json = self.save_json_check.isChecked()
        recipe.output.save_recipe_snapshot = self.save_snapshot_check.isChecked()
        recipe.output.export_pixel_csv = self.export_pixel_csv_check.isChecked()
        recipe.output.pixel_csv_raw = self.pixel_csv_raw_check.isChecked()
        recipe.output.pixel_csv_dark_corrected = self.pixel_csv_corrected_check.isChecked()
        recipe.output.pixel_csv_exposure_normalized = self.pixel_csv_normalized_check.isChecked()
        return recipe

    def _new_recipe(self) -> None:
        recipe = Recipe()
        existing_names = {item.name for item in self.store.recipes}
        suffix = 1
        while recipe.name in existing_names:
            suffix += 1
            recipe.name = f"新 EL Recipe {suffix}"
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
        answer = QMessageBox.question(self, "刪除 Recipe", f"確定要刪除「{self.current_recipe.name}」？此動作無法復原。")
        if answer != QMessageBox.StandardButton.Yes:
            return
        self.store.delete(self.current_recipe.recipe_id)
        self.current_recipe = None
        self._reload_list()
        self.recipes_changed.emit()

    def _save_current(self) -> None:
        if self.current_recipe is None:
            return
        recipe = self._read_form_to_recipe()
        duplicate = next((item for item in self.store.recipes if item.recipe_id != recipe.recipe_id and item.name.casefold() == recipe.name.casefold()), None)
        if duplicate is not None:
            QMessageBox.warning(self, "名稱重複", "Recipe 名稱不可與既有 Recipe 重複。")
            return
        errors = recipe.validate()
        if recipe.state == "active" and errors:
            self._show_validation(errors, recipe.validation_warnings())
            QMessageBox.warning(self, "無法啟用 Recipe", "Recipe 尚未通過驗證。請修正右側項目，或先儲存為草稿。")
            return
        self.store.upsert(recipe)
        self.current_recipe = deepcopy(self.store.get(recipe.recipe_id) or recipe)
        self._write_recipe_to_form(self.current_recipe)
        self._reload_list(preferred_id=recipe.recipe_id)
        self._show_validation(self.current_recipe.validate(), self.current_recipe.validation_warnings())
        self.recipes_changed.emit()
        QMessageBox.information(self, "已儲存", f"已儲存 Recipe「{recipe.name}」。")

    def _validate_current(self) -> None:
        if self.current_recipe is None:
            return
        recipe = self._read_form_to_recipe()
        self._show_validation(recipe.validate(), recipe.validation_warnings())

    def _show_validation(self, errors: list[str], warnings: list[str] | None = None) -> None:
        warnings = warnings or []
        if errors:
            text = "未通過：\n• " + "\n• ".join(errors)
            if warnings:
                text += "\n\n警告：\n• " + "\n• ".join(warnings)
            self.validation_label.setText(text)
            self.validation_label.setStyleSheet("color:#c62828; padding:6px;")
        elif warnings:
            self.validation_label.setText("✓ 結構驗證通過\n\n定量警告：\n• " + "\n• ".join(warnings))
            self.validation_label.setStyleSheet("color:#a05a00; padding:6px; font-weight:600;")
        else:
            self.validation_label.setText("✓ 驗證通過；相機條件具直接定量相容性。")
            self.validation_label.setStyleSheet("color:#16823b; padding:6px; font-weight:600;")

    def _connect_summary_updates(self) -> None:
        widgets: list[QWidget] = []
        for widget_type in (QLineEdit, QTextEdit, QSpinBox, QDoubleSpinBox, QComboBox, QCheckBox):
            widgets.extend(self.findChildren(widget_type))
        for widget in widgets:
            if widget in (self.search_edit, self.builder_custom_edit):
                continue
            if isinstance(widget, QLineEdit):
                widget.textChanged.connect(self._update_summary)
            elif isinstance(widget, QTextEdit):
                widget.textChanged.connect(self._update_summary)
            elif isinstance(widget, (QSpinBox, QDoubleSpinBox)):
                widget.valueChanged.connect(self._update_summary)
            elif isinstance(widget, QComboBox):
                widget.currentIndexChanged.connect(self._update_summary)
            elif isinstance(widget, QCheckBox):
                widget.toggled.connect(self._update_summary)
        self.points_table.itemChanged.connect(self._update_summary)
        self.channels_table.itemChanged.connect(self._update_summary)
        self.drive_mode_combo.currentIndexChanged.connect(self._sync_drive_mode)
        self.device_match_combo.currentIndexChanged.connect(lambda: self.visa_edit.setEnabled(self.device_match_combo.currentData() == "specific"))
        self.export_pixel_csv_check.toggled.connect(self._on_pixel_csv_toggled)
        self.hdr_enabled_check.toggled.connect(self._sync_hdr_controls)

    def _update_summary(self, *_args: object) -> None:
        if self.current_recipe is None:
            return
        recipe = self._read_form_to_recipe()
        state = {"active": "啟用", "draft": "草稿", "disabled": "停用"}.get(recipe.state, recipe.state)
        points = recipe.enabled_points()
        channels = recipe.enabled_channels()
        counts = recipe.matrix_capture_counts()
        point_text = ", ".join(f"{point.setpoint:g}" for point in points[:12])
        if len(points) > 12:
            point_text += "…"
        profiles = recipe.dark_profiles()
        profile_text = "\n".join(
            f"• {item['exposure_ms']:g} ms / Gain {item['gain_percent']}%"
            for item in profiles if "exposure_ms" in item
        ) or "由「設定 → HDR」與 T0 Profile 在執行時建立"
        if recipe.hdr.enabled:
            self.dark_profiles_label.setText(
                f"T0 自動校正後依 HDR Profile 建立：\n{profile_text}"
            )
        else:
            self.dark_profiles_label.setText(f"共 {len(profiles)} 組：\n{profile_text}")
        drive = "定電流" if recipe.el_sweep.drive_mode == "current" else "定電壓"
        self.summary_label.setText(
            f"{recipe.name or '未命名 Recipe'}\n"
            f"狀態：{state}\n"
            f"Channels：{' / '.join(channel.channel for channel in channels) or '尚未啟用'}\n"
            f"Current Density：{', '.join(f'{value:g}' for value in recipe.el_matrix.current_density_ma_cm2)} mA/cm²\n"
            f"Gain：{', '.join(str(value) for value in recipe.el_matrix.gains_percent)} %\n"
            f"Exposure：{', '.join(f'{value:g}' for value in recipe.el_matrix.exposures_ms)} ms\n"
            f"Repeat：{recipe.el_matrix.repeat}\n\n"
            "固定執行流程\n"
            "Shared Dark（一次）→ Channel → J → Gain → Exposure → Repeat\n"
            f"Shared Dark：{counts['shared_dark']} 張\n"
            f"EL / Channel：{counts['el_per_channel']} 張\n"
            f"EL Total：{counts['total_el']} 張\n"
            f"Overall：{counts['overall']} 張\n"
            f"每 Channel 極性確認：{'啟用' if recipe.polarity.enabled else '略過（執行前警告）'}\n"
            f"定量警告：{len(recipe.validation_warnings())} 項\n\n"
            f"全解析度像素 CSV：{'啟用' if recipe.output.export_pixel_csv else '關閉（可日後由 TIFF 產生）'}\n\n"
            f"定量 HDR：{'啟用－T0 建檔／Aging 鎖定 Profile' if recipe.hdr.enabled else '關閉'}\n"
            f"HDR 原始分曝光 EL／Dark：{'強制保存' if recipe.hdr.enabled else '不適用'}\n\n"
            "TIFF 永遠保存 RAW；JPG 由同一 frame 建立下方三行 Footer。"
        )

    def _import_recipe(self) -> None:
        filename, _ = QFileDialog.getOpenFileName(self, "匯入 Recipe JSON", "", "JSON (*.json)")
        if not filename:
            return
        try:
            payload = json.loads(Path(filename).read_text(encoding="utf-8"))
            data = payload.get("recipe", payload)
            recipe = Recipe.from_dict(data)
            recipe.recipe_id = Recipe().recipe_id
            recipe.name = f"{recipe.name} - 匯入"
            recipe.state = "draft"
            recipe.version = 1
            self.store.upsert(recipe)
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
        filename, _ = QFileDialog.getSaveFileName(self, "匯出 Recipe JSON", f"{recipe.name}.json", "JSON (*.json)")
        if not filename:
            return
        Path(filename).write_text(json.dumps({"schema_version": 7, "recipe": recipe.to_dict()}, ensure_ascii=False, indent=2), encoding="utf-8")

    def _choose_output_root(self) -> None:
        selected = QFileDialog.getExistingDirectory(self, "選擇量測資料儲存根目錄")
        if selected:
            self.output_root_edit.setText(selected)

    def _set_editor_enabled(self, enabled: bool) -> None:
        self.tabs.setEnabled(enabled)
        self.copy_button.setEnabled(enabled)
        self.delete_button.setEnabled(enabled)
        self.export_button.setEnabled(enabled)
        self.validate_button.setEnabled(enabled)
        self.save_button.setEnabled(enabled)
        if not enabled:
            self.current_recipe = None
            self.summary_label.setText("請新增 Recipe。")
            self.validation_label.setText("尚未驗證")

    @staticmethod
    def _set_combo_data(combo: QComboBox, value: str) -> None:
        index = combo.findData(value)
        combo.setCurrentIndex(index if index >= 0 else 0)
