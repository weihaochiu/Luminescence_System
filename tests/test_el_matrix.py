from __future__ import annotations

from contextlib import contextmanager
import tempfile
import csv
import json
import threading
import time
import unittest
from types import SimpleNamespace
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from unittest.mock import patch

import numpy as np
import tifffile
from PIL import Image
from PySide6.QtCore import QObject, Signal
from PySide6.QtGui import QColor, QImage

from gui.el_matrix_plan import ELMatrixPlan
from gui.el_matrix_hardware import ELMatrixHardwareAdapter
from gui.el_matrix_preflight import collect_preflight_errors
from gui.camera_capture_bridge import CameraCaptureBridge
from gui.el_matrix_runner import CapturedFrame, ELMatrixRunner
from gui.measurement_snapshot import (
    build_el_matrix_snapshot,
    snapshot_payload,
    verify_snapshot_hash,
)
from gui.measurement_output import (
    annotated_jpeg_image,
    format_dark_footer,
    format_el_footer,
    sanitize_filename,
    save_matrix_capture,
    save_pixel_csv_products,
    sha256_file,
)
from gui.measurement_execution_plan import build_measurement_execution_plan
from gui.measurement_progress_dialog import MeasurementProgressDialog
from gui.main_window_devices import MainWindowDeviceMixin
from gui.keysight_b2900 import KeysightB2900Driver
from gui.smu_base import SMUDevice
from gui.recipe_store import Recipe
from gui.recipe_dialog import RecipeManagerDialog
from gui.recipe_store import RecipeStore
from gui.polarity_settings import PolarityMeasurementSettings
from gui.relay_settings import RelaySettings
from gui.smu_control import SMUControlManager, SMUOwnership, SMUSafetyLimits
from tests.qt_test_utils import ensure_qapplication


@dataclass
class _Readback:
    current_a: float = 0.0008
    voltage_v: float = 1.24


class _FakeHardware:
    def __init__(self, fail_capture: bool = False) -> None:
        self.events: list[object] = []
        self.fail_capture = fail_capture
        self.polarity_calls = 0
        self.default_polarity_calls = 0
        self.safe = False

    def prepare_shared_dark(self) -> None:
        self.events.append("prepare_dark")

    def route_channel(self, channel, _check_cancel) -> None:
        self.events.append(("route", channel))

    def run_polarity(self, channel, _check_cancel):
        self.polarity_calls += 1
        self.events.append(("polarity", channel.channel))
        return {
            "polarity_check_status": "COMPLETED",
            "polarity_result": "NORMAL",
            "polarity_factor": 1,
            "polarity_timestamp": "2026-08-14T06:00:00+08:00",
            "Jsc": {"representative": -10},
            "Voc": {"representative": 1.1},
        }

    def apply_polarity_factor(self, factor):
        self.events.append(("apply_polarity", factor))

    def prepare_channel_dark(self):
        self.events.append("prepare_channel_dark")

    def run_dark_iv(self, _settings, _check_cancel):
        self.events.append("dark_iv")
        return [{
            "Repeat": 1,
            "PointIndex": 1,
            "SetVoltageV": 0.0,
            "PolarityFactor": 1,
            "CommandedVoltageV": 0.0,
            "CommandedPhysicalVoltageV": 0.0,
            "MeasuredVoltageV": 0.0,
            "MeasuredCurrentA": 0.0,
            "MeasuredPowerW": 0.0,
            "ComplianceTripped": False,
        }]

    def set_current(self, current_a, compliance):
        self.events.append(("set_current", current_a, compliance))
        return current_a

    def set_voltage(self, voltage_v, compliance_ma):
        self.events.append(("set_voltage", voltage_v, compliance_ma))
        return voltage_v

    def readback(self):
        self.events.append("readback")
        return _Readback()

    def capture(self, exposure, gain, _timeout, _check_cancel):
        self.events.append(("capture", exposure, gain))
        if self.fail_capture:
            raise RuntimeError("camera failed")
        image = QImage(4, 3, QImage.Format.Format_RGB888)
        image.fill(QColor(10, 20, 30))
        return CapturedFrame(
            image,
            datetime(2026, 8, 14, 6, 44, 12).astimezone(),
            39.8,
            {
                "CameraModel": "Fake", "CameraSerial": "SN1", "PixelFormat": "MONO16",
                "BitDepth": 12, "SensorBitDepth": 12, "ContainerBitDepth": 16,
                "ContainerDtype": "uint16", "Channels": 1,
                "RawValueAlignment": "right",
            },
            np.full((3, 4), 1024, dtype=np.uint16),
        )

    def output_off(self):
        self.events.append("output_off")

    def clear_routing(self):
        self.events.append("clear_routing")

    def safe_shutdown(self):
        self.safe = True
        self.events.append("safe_shutdown")
        return {
            "smu_output_off": True,
            "routing_off": True,
            "white_light_off": True,
            "ownership_released": True,
            "ok": True,
        }


class _RecordingSMUDriver:
    def __init__(self) -> None:
        self.device = SMUDevice(
            "USB0::EL-MATRIX::INSTR",
            manufacturer="Keysight Technologies",
            model="B2901B",
            serial_number="EL-MATRIX-SERIAL",
            idn="Keysight Technologies,B2901B,EL-MATRIX-SERIAL,1.0",
            supported=True,
        )
        self.commands: list[tuple[object, ...]] = []
        self.output = False
        self.voltage_v = 0.0
        self.current_a = 0.0
        self.compliance_tripped = False
        self.configure_voltage_calls = 0

    def configure_voltage_source(
        self, voltage_v: float, current_compliance_a: float
    ) -> None:
        self.configure_voltage_calls += 1
        self.voltage_v = voltage_v
        self.current_a = 0.0008 if voltage_v >= 0 else -0.0008
        self.commands.append(("CV", voltage_v, current_compliance_a))

    def configure_current_source(
        self, current_a: float, voltage_compliance_v: float
    ) -> None:
        self.current_a = current_a
        self.voltage_v = 1.2 if current_a >= 0 else -1.2
        self.commands.append(("CC", current_a, voltage_compliance_v))

    def set_output_enabled(self, enabled: bool) -> None:
        self.output = enabled
        self.commands.append(("OUTPUT", enabled))

    def update_voltage_source_level(self, voltage_v: float) -> None:
        self.voltage_v = voltage_v
        self.current_a = 0.0008 if voltage_v >= 0 else -0.0008
        self.commands.append(("CV", voltage_v, 0.020))

    def update_current_source_level(self, current_a: float) -> None:
        self.current_a = current_a
        self.voltage_v = 1.2 if current_a >= 0 else -1.2
        self.commands.append(("CC", current_a, 3.0))

    @contextmanager
    def temporary_measurement_nplc(self, _mode: str, _nplc: float):
        yield True

    def safe_stop(self) -> list[str]:
        self.output = False
        self.commands.append(("OUTPUT", False))
        return []

    def query_output_enabled(self) -> bool:
        return self.output

    def measure_voltage(self) -> float:
        return self.voltage_v

    def measure_current(self) -> float:
        return self.current_a

    def query_compliance_tripped(self, _mode: str) -> bool:
        return self.compliance_tripped


class _KeysightSweepResource:
    def __init__(self) -> None:
        self.writes: list[str] = []
        self.transactions: list[str] = []
        self.output = False
        self.source_mode = "VOLT"
        self.voltage_v = 0.0
        self.current_nplc = 0.2
        self.current_nplc_auto = True

    def write(self, command: str) -> None:
        self.writes.append(command)
        self.transactions.append(command)
        if command == ":OUTP ON":
            self.output = True
        elif command == ":OUTP OFF":
            self.output = False
        elif command.startswith(":SOUR:FUNC:MODE "):
            self.source_mode = command.rsplit(" ", 1)[-1]
        elif command.startswith(":SOUR:VOLT "):
            self.voltage_v = float(command.rsplit(" ", 1)[-1])
        elif command.startswith(":SENS:CURR:NPLC "):
            self.current_nplc = float(command.rsplit(" ", 1)[-1])
        elif command == ":SENS:CURR:NPLC:AUTO ON":
            self.current_nplc_auto = True
        elif command == ":SENS:CURR:NPLC:AUTO OFF":
            self.current_nplc_auto = False

    def query(self, command: str) -> str:
        self.transactions.append(command)
        responses = {
            ":OUTP?": "1" if self.output else "0",
            ":SOUR:FUNC:MODE?": self.source_mode,
            ":SOUR:VOLT?": str(self.voltage_v),
            ":SENS:CURR:NPLC?": str(self.current_nplc),
            ":SENS:CURR:NPLC:AUTO?": "1" if self.current_nplc_auto else "0",
            ":MEAS:VOLT?": str(self.voltage_v),
            ":MEAS:CURR?": str(self.voltage_v / 1000.0),
            ":SENS:CURR:PROT:TRIP?": "0",
        }
        return responses[command]


class _ControlBackedHardware(_FakeHardware):
    def __init__(self, control: SMUControlManager, polarity_factor: int) -> None:
        super().__init__()
        self.control = control
        self.polarity_factor = polarity_factor

    def run_polarity(self, channel, _check_cancel):
        self.events.append(("polarity", channel.channel))
        return {
            "polarity_check_status": "COMPLETED",
            "polarity_result": (
                "NORMAL" if self.polarity_factor == 1 else "REVERSED"
            ),
            "polarity_factor": self.polarity_factor,
            "polarity_timestamp": "2026-08-14T06:00:00+08:00",
            "Jsc": {"representative": -10},
            "Voc": {"representative": 1.1},
        }

    def apply_polarity_factor(self, factor):
        self.events.append(("apply_polarity", factor))
        self.control.set_recipe_polarity_factor(factor)

    def run_dark_iv(self, settings, check_cancel):
        self.events.append("dark_iv")
        return ELMatrixHardwareAdapter.run_dark_iv(self, settings, check_cancel)

    def set_current(self, current_a, compliance):
        physical = self.control.recipe_output("CC", current_a, compliance)
        self.events.append(("set_current", current_a, compliance, physical))
        return physical

    def set_voltage(self, voltage_v, compliance_ma):
        physical = self.control.recipe_output(
            "CV", voltage_v, compliance_ma / 1000.0
        )
        self.events.append(("set_voltage", voltage_v, compliance_ma, physical))
        return physical

    def readback(self):
        return self.control.recipe_readback()

    def output_off(self):
        self.events.append("output_off")
        if (
            self.control.ownership is SMUOwnership.RECIPE
            and self.control.output_enabled
        ):
            self.control.recipe_output_off("test transition")

    def safe_shutdown(self):
        ok = self.control.safe_shutdown(SMUOwnership.RECIPE)
        self.safe = ok
        self.events.append("safe_shutdown")
        return {
            "smu_output_off": ok,
            "routing_off": True,
            "white_light_off": True,
            "ownership_released": self.control.ownership is SMUOwnership.IDLE,
            "ok": ok,
        }


def _small_recipe(channel_count: int = 2) -> Recipe:
    recipe = Recipe()
    for index, channel in enumerate(recipe.channels):
        channel.enabled = index < channel_count
        channel.area_cm2 = 0.1 + index * 0.1
    recipe.el_matrix.current_density_ma_cm2 = [2.0, 4.0]
    recipe.el_matrix.gains_percent = [100, 200]
    recipe.el_matrix.exposures_ms = [1.0]
    recipe.el_matrix.repeat = 1
    recipe.el_matrix.stabilization_ms = 0
    recipe.el_matrix.estimated_capture_overhead_s = 0
    recipe.el_matrix.estimated_polarity_duration_s = 0
    recipe.el_matrix.estimated_routing_transition_s = 0
    recipe.el_matrix.estimated_shared_dark_overhead_s = 0
    recipe.dark_iv.dark_stabilization_s = 0
    recipe.dark_iv.start_v = 0
    recipe.dark_iv.stop_v = 0.1
    recipe.dark_iv.step_v = 0.1
    recipe.dark_iv.dwell_s = 0
    recipe.dark_iv.nplc = 0.001
    return recipe


class ELMatrixRecipeAndPlanTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.app = ensure_qapplication()

    def test_recipe_dialog_exposes_fixed_channel_table_and_shared_matrix(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            store = RecipeStore(Path(directory) / "recipes.json")
            store.upsert(Recipe())
            dialog = RecipeManagerDialog(store)
            self.app.processEvents()
            self.assertEqual(4, dialog.channels_table.rowCount())
            self.assertEqual("CH1", dialog.channels_table.item(0, 1).text())
            self.assertTrue(dialog.matrix_current_density_edit.text())
            self.assertTrue(dialog.dark_frame_enabled_check.isChecked())
            self.assertEqual(4, dialog.tabs.count())
            dialog.close()

    def test_recipe_model_defaults_round_trip_and_legacy_default(self) -> None:
        default = Recipe()
        self.assertEqual("current_density", default.el_matrix.output_mode)
        current_round_trip = Recipe.from_dict(default.to_dict())
        self.assertEqual("current_density", current_round_trip.el_matrix.output_mode)
        voltage = Recipe()
        voltage.el_matrix.output_mode = "voltage"
        voltage.el_matrix.voltage_v = [0.75, 1.05]
        voltage.el_matrix.current_compliance_ma = 12.5
        loaded = Recipe.from_dict(voltage.to_dict())
        self.assertEqual("voltage", loaded.el_matrix.output_mode)
        self.assertEqual([0.75, 1.05], loaded.el_matrix.voltage_v)
        self.assertEqual(12.5, loaded.el_matrix.current_compliance_ma)
        legacy = Recipe.from_dict({
            "el_matrix": {
                "current_density_ma_cm2": [3.0, 7.0],
                "voltage_compliance_v": 2.5,
            }
        })
        self.assertEqual("current_density", legacy.el_matrix.output_mode)
        self.assertEqual([3.0, 7.0], legacy.el_matrix.current_density_ma_cm2)

    def test_dialog_mode_switch_preserves_both_lists_and_compliance_values(self) -> None:
        recipe = Recipe()
        recipe.el_matrix.current_density_ma_cm2 = [2.0, 9.0]
        recipe.el_matrix.voltage_v = [0.8, 1.15]
        with tempfile.TemporaryDirectory() as directory:
            store = RecipeStore(Path(directory) / "recipes.json")
            store.upsert(recipe)
            dialog = RecipeManagerDialog(store)
            try:
                self.app.processEvents()
                self.assertEqual(
                    "current_density", dialog.matrix_output_mode_combo.currentData()
                )
                self.assertFalse(dialog.matrix_current_density_edit.isHidden())
                self.assertTrue(dialog.matrix_voltage_edit.isHidden())
                self.assertFalse(dialog.matrix_voltage_compliance_spin.isHidden())
                self.assertTrue(dialog.matrix_current_compliance_spin.isHidden())
                dialog.matrix_output_mode_combo.setCurrentIndex(
                    dialog.matrix_output_mode_combo.findData("voltage")
                )
                self.app.processEvents()
                self.assertTrue(dialog.matrix_current_density_edit.isHidden())
                self.assertFalse(dialog.matrix_voltage_edit.isHidden())
                self.assertTrue(dialog.matrix_voltage_compliance_spin.isHidden())
                self.assertFalse(dialog.matrix_current_compliance_spin.isHidden())
                dialog.matrix_voltage_edit.setText("0.9, 1.2")
                dialog.matrix_current_compliance_spin.setValue(18.0)
                serialized_plan = json.dumps(
                    build_measurement_execution_plan(
                        dialog._read_form_to_recipe()
                    ).to_dict(),
                    ensure_ascii=False,
                )
                self.assertIn("Voltage 0.9 V", serialized_plan)
                preview_titles = []
                root = dialog.execution_tree.invisibleRootItem()
                pending = [root.child(index) for index in range(root.childCount())]
                while pending:
                    item = pending.pop()
                    preview_titles.append(item.text(0))
                    pending.extend(
                        item.child(index) for index in range(item.childCount())
                    )
                self.assertTrue(any("Voltage 0.9 V" in title for title in preview_titles))
                dialog.matrix_output_mode_combo.setCurrentIndex(
                    dialog.matrix_output_mode_combo.findData("current_density")
                )
                result = dialog._read_form_to_recipe()
                self.assertEqual([2.0, 9.0], result.el_matrix.current_density_ma_cm2)
                self.assertEqual([0.9, 1.2], result.el_matrix.voltage_v)
                self.assertEqual(18.0, result.el_matrix.current_compliance_ma)
            finally:
                dialog.close()

    def test_dialog_inactive_invalid_values_are_ignored_but_active_values_fail(self) -> None:
        recipe = Recipe()
        recipe.el_matrix.current_density_ma_cm2 = [2.0, 4.0]
        recipe.el_matrix.voltage_v = [0.8, 1.0, 1.2]
        with tempfile.TemporaryDirectory() as directory:
            store = RecipeStore(Path(directory) / "recipes.json")
            store.upsert(recipe)
            dialog = RecipeManagerDialog(store)
            try:
                self.app.processEvents()
                dialog.matrix_current_density_edit.setText("2, 4, 6")
                for invalid in ("nan", "inf", "-inf", "abc"):
                    with self.subTest(inactive_voltage=invalid):
                        dialog.matrix_voltage_edit.setText(invalid)
                        with patch(
                            "gui.recipe_dialog_logic.QMessageBox.information"
                        ):
                            dialog._save_current()
                        saved = store.get(recipe.recipe_id)
                        self.assertIsNotNone(saved)
                        self.assertEqual(
                            [2.0, 4.0, 6.0],
                            saved.el_matrix.current_density_ma_cm2,
                        )
                        self.assertEqual(
                            [0.8, 1.0, 1.2], saved.el_matrix.voltage_v
                        )

                dialog.matrix_current_density_edit.setText("nan")
                with self.assertRaisesRegex(ValueError, "Current Density List"):
                    dialog._read_form_to_recipe()
                dialog.matrix_output_mode_combo.setCurrentIndex(
                    dialog.matrix_output_mode_combo.findData("voltage")
                )
                dialog.matrix_voltage_edit.setText("inf")
                with self.assertRaisesRegex(ValueError, "Voltage List"):
                    dialog._read_form_to_recipe()
                dialog.matrix_voltage_edit.clear()
                with self.assertRaisesRegex(ValueError, "不可空白"):
                    dialog._read_form_to_recipe()
                dialog.matrix_voltage_edit.setText("0.9, 1.1")
                dialog.matrix_current_density_edit.setText("-inf")
                with patch(
                    "gui.recipe_dialog_logic.QMessageBox.information"
                ):
                    dialog._save_current()
                saved = store.get(recipe.recipe_id)
                self.assertIsNotNone(saved)
                self.assertEqual(
                    [2.0, 4.0, 6.0], saved.el_matrix.current_density_ma_cm2
                )
                self.assertEqual([0.9, 1.1], saved.el_matrix.voltage_v)
            finally:
                dialog.close()
    def test_enabled_channels_are_fixed_order_and_disabled_are_skipped(self) -> None:
        recipe = _small_recipe(3)
        recipe.channels[1].enabled = False
        self.assertEqual(["CH1", "CH3"], [item.channel for item in recipe.enabled_channels()])

    def test_channel_counts_one_through_four_do_not_multiply_shared_dark(self) -> None:
        for count in range(1, 5):
            recipe = _small_recipe(count)
            counts = recipe.matrix_capture_counts()
            self.assertEqual(2, counts["shared_dark"])
            self.assertEqual(count * 4, counts["total_el"])
            self.assertEqual(2 + count * 4, counts["overall"])

    def test_validation_rejects_invalid_channel_area_j_repeat_gain_exposure_and_compliance(self) -> None:
        cases = []
        recipe = _small_recipe(1); recipe.channels[0].area_cm2 = 0; cases.append(recipe)
        recipe = _small_recipe(1); recipe.el_matrix.current_density_ma_cm2 = [0]; cases.append(recipe)
        recipe = _small_recipe(1); recipe.el_matrix.current_density_ma_cm2 = [-1]; cases.append(recipe)
        recipe = _small_recipe(1); recipe.el_matrix.repeat = 0; cases.append(recipe)
        recipe = _small_recipe(1); recipe.el_matrix.gains_percent = [-1]; cases.append(recipe)
        recipe = _small_recipe(1); recipe.el_matrix.exposures_ms = [0]; cases.append(recipe)
        recipe = _small_recipe(1); recipe.el_matrix.voltage_compliance_v = 99; cases.append(recipe)
        for recipe in cases:
            with self.subTest(recipe=recipe.to_dict()):
                self.assertTrue(recipe.validate())

    def test_matrix_order_is_channel_j_gain_exposure_repeat(self) -> None:
        recipe = _small_recipe(2)
        recipe.el_matrix.exposures_ms = [1, 2]
        recipe.el_matrix.repeat = 2
        el = [capture for capture in ELMatrixPlan(recipe).captures() if capture.measurement_type == "EL"]
        keys = [
            (item.channel, item.current_density_ma_cm2, item.gain_percent, item.exposure_ms, item.repeat_index)
            for item in el
        ]
        self.assertEqual(("CH1", 2, 100, 1, 1), keys[0])
        self.assertEqual(("CH1", 2, 100, 1, 2), keys[1])
        self.assertEqual(("CH1", 2, 100, 2, 1), keys[2])
        self.assertLess(keys.index(("CH1", 4, 100, 1, 1)), keys.index(("CH2", 2, 100, 1, 1)))

    def test_voltage_plan_uses_v_gain_exposure_repeat_and_dark_is_unchanged(self) -> None:
        recipe = _small_recipe(1)
        recipe.el_matrix.output_mode = "voltage"
        recipe.el_matrix.voltage_v = [0.8, 1.0, 1.2]
        recipe.el_matrix.current_density_ma_cm2 = [2.0] * 9
        recipe.el_matrix.exposures_ms = [1.0, 2.0]
        recipe.el_matrix.repeat = 2
        plan = ELMatrixPlan(recipe)
        counts = plan.capture_counts()
        self.assertEqual(8, counts["shared_dark"])
        self.assertEqual(24, counts["el_per_channel"])
        el = [item for item in plan.captures() if item.measurement_type == "EL"]
        keys = [
            (
                item.commanded_voltage_v,
                item.gain_percent,
                item.exposure_ms,
                item.repeat_index,
            )
            for item in el
        ]
        self.assertEqual((0.8, 100, 1.0, 1), keys[0])
        self.assertEqual((0.8, 100, 1.0, 2), keys[1])
        self.assertEqual((0.8, 100, 2.0, 1), keys[2])
        self.assertLess(keys.index((1.0, 100, 1.0, 1)), keys.index((1.2, 100, 1.0, 1)))
        payload = json.dumps(
            build_measurement_execution_plan(recipe).to_dict(), ensure_ascii=False
        )
        self.assertIn("Voltage 0.8 V", payload)
        self.assertNotIn("Current Density 2", payload)

    def test_mode_specific_safety_validation_and_power(self) -> None:
        limits = SMUSafetyLimits()
        current = _small_recipe(1)
        current.el_matrix.voltage_v = [float("nan")]
        current.el_matrix.current_compliance_ma = float("inf")
        self.assertEqual([], current.validate(limits))
        current.el_matrix.current_density_ma_cm2 = [600.0]
        self.assertTrue(any("Source Current" in item for item in current.validate(limits)))

        voltage = _small_recipe(1)
        voltage.el_matrix.output_mode = "voltage"
        voltage.el_matrix.voltage_v = [1.0, 1.2]
        voltage.el_matrix.current_density_ma_cm2 = [float("nan")]
        voltage.el_matrix.voltage_compliance_v = float("inf")
        self.assertEqual([], voltage.validate(limits))
        voltage.el_matrix.voltage_v = [float("nan")]
        self.assertTrue(any("Voltage List" in item for item in voltage.validate(limits)))
        voltage.el_matrix.voltage_v = [6.0]
        self.assertTrue(any("Voltage List 超過" in item for item in voltage.validate(limits)))
        voltage.el_matrix.voltage_v = [1.0]
        voltage.el_matrix.current_compliance_ma = 60.0
        self.assertTrue(any("Current Compliance" in item for item in voltage.validate(limits)))
        voltage.el_matrix.voltage_v = [5.0]
        voltage.el_matrix.current_compliance_ma = 50.0
        self.assertEqual(250.0, voltage.matrix_worst_power_mw())
        self.assertTrue(any("最壞 Compliance 功率" in item for item in voltage.validate(limits)))

    def test_eta_dark_once_stabilization_per_channel_j_and_mock_finish(self) -> None:
        recipe = _small_recipe(2)
        recipe.el_matrix.stabilization_ms = 500
        recipe.el_matrix.estimated_polarity_duration_s = 3
        recipe.el_matrix.estimated_routing_transition_s = 2
        recipe.el_matrix.estimated_shared_dark_overhead_s = 1
        now = datetime(2026, 8, 14, 6, 0, 0).astimezone()
        estimate = ELMatrixPlan(recipe).estimate(now)
        # Exposure: dark 2 ms + EL (2 ch * 2 J * 2 gain * 1 ms) = 10 ms.
        dark_iv = 2 * recipe.dark_iv_estimated_time_s()
        expected = 0.010 + (2 * 2 * 0.5) + (2 * 3) + (2 * 2 * 2) + 1 + dark_iv
        self.assertAlmostEqual(expected, estimate.total_time_s, places=6)
        self.assertEqual(now.timestamp() + expected, estimate.estimated_finish.timestamp())


class ELMatrixRunnerTests(unittest.TestCase):
    def _run_physical_command_case(
        self, output_mode: str, polarity_factor: int
    ) -> tuple[dict[str, object], list[tuple[object, ...]], str, str, dict[str, str]]:
        recipe = _small_recipe(1)
        recipe.el_matrix.dark_frame_enabled = False
        recipe.dark_iv.enabled = False
        recipe.el_matrix.gains_percent = [100]
        recipe.el_matrix.exposures_ms = [1.0]
        recipe.el_matrix.current_density_ma_cm2 = [10.0]
        recipe.el_matrix.output_mode = output_mode
        recipe.el_matrix.voltage_v = [1.0]
        recipe.el_matrix.current_compliance_ma = 20.0
        driver = _RecordingSMUDriver()
        control = SMUControlManager()
        control.bind_driver(driver, output_confirmed_off=True)
        control.acquire_recipe()
        hardware = _ControlBackedHardware(control, polarity_factor)
        try:
            with tempfile.TemporaryDirectory() as directory:
                result = ELMatrixRunner(
                    recipe,
                    hardware,
                    directory,
                    report_progress=lambda _item: None,
                    is_cancel_requested=lambda: False,
                ).run()
                run_directory = Path(result["output_directory"])
                metadata_path = next(
                    run_directory.rglob(
                        "*_V1.0_*.json"
                        if output_mode == "voltage"
                        else "*_J10_*.json"
                    )
                )
                metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
                footer = "\n".join(format_el_footer(metadata))
                with (run_directory / "measurement_manifest.csv").open(
                    "r", newline="", encoding="utf-8-sig"
                ) as stream:
                    manifest_row = next(csv.DictReader(stream))
                return (
                    metadata,
                    list(driver.commands),
                    metadata_path.name,
                    footer,
                    manifest_row,
                )
        finally:
            control.shutdown(safety_confirmed=True)

    def _run_dark_iv_physical_command_case(
        self, polarity_factor: int
    ) -> tuple[
        list[dict[str, str]],
        dict[str, object],
        list[tuple[object, ...]],
        list[object],
        dict[str, object],
    ]:
        recipe = _small_recipe(1)
        recipe.el_matrix.dark_frame_enabled = False
        recipe.dark_iv.enabled = True
        recipe.dark_iv.start_v = 0.0
        recipe.dark_iv.stop_v = 1.0
        recipe.dark_iv.step_v = 1.0
        recipe.dark_iv.direction = "bidirectional"
        recipe.dark_iv.current_compliance_ma = 20.0
        recipe.dark_iv.repeat_count = 1
        recipe.el_matrix.current_density_ma_cm2 = [2.0]
        recipe.el_matrix.gains_percent = [100]
        recipe.el_matrix.exposures_ms = [1.0]
        driver = _RecordingSMUDriver()
        control = SMUControlManager()
        control.bind_driver(driver, output_confirmed_off=True)
        control.acquire_recipe()
        hardware = _ControlBackedHardware(control, polarity_factor)
        try:
            with tempfile.TemporaryDirectory() as directory:
                result = ELMatrixRunner(
                    recipe,
                    hardware,
                    directory,
                    report_progress=lambda _item: None,
                    is_cancel_requested=lambda: False,
                ).run()
                run_directory = Path(result["output_directory"])
                with next(run_directory.rglob("dark_iv.csv")).open(
                    "r", newline="", encoding="utf-8-sig"
                ) as stream:
                    rows = list(csv.DictReader(stream))
                dark_metadata = json.loads(
                    next(run_directory.rglob("dark_iv.json")).read_text(
                        encoding="utf-8"
                    )
                )
                self.assertEqual(
                    sha256_file(next(run_directory.rglob("dark_iv.csv"))),
                    dark_metadata["CsvSha256"],
                )
                snapshot = json.loads(
                    (run_directory / "measurement_snapshot.json").read_text(
                        encoding="utf-8"
                    )
                )
                return (
                    rows,
                    dark_metadata,
                    list(driver.commands),
                    list(hardware.events),
                    snapshot,
                )
        finally:
            control.shutdown(safety_confirmed=True)

    def test_dark_iv_metadata_uses_returned_physical_voltage_for_both_polarities(self) -> None:
        for factor in (-1, 1):
            with self.subTest(polarity_factor=factor):
                rows, dark_metadata, commands, events, snapshot = (
                    self._run_dark_iv_physical_command_case(factor)
                )
                setpoints = [0.0, 1.0, 0.0]
                physical = [value * factor for value in setpoints]
                cv_commands = [
                    command for command in commands if command[0] == "CV"
                ]
                self.assertEqual(
                    [("CV", value, 0.020) for value in physical],
                    cv_commands,
                )
                self.assertEqual(setpoints, [float(row["SetVoltageV"]) for row in rows])
                self.assertEqual(
                    physical,
                    [float(row["CommandedVoltageV"]) for row in rows],
                )
                self.assertEqual(
                    physical,
                    [float(row["CommandedPhysicalVoltageV"]) for row in rows],
                )
                self.assertEqual(
                    physical,
                    [float(row["MeasuredVoltageV"]) for row in rows],
                )
                self.assertEqual([factor] * 3, [int(row["PolarityFactor"]) for row in rows])
                for expected_voltage, row in zip(physical, rows):
                    expected_current = 0.0008 if expected_voltage >= 0 else -0.0008
                    self.assertEqual(expected_current, float(row["MeasuredCurrentA"]))
                    self.assertEqual(
                        expected_voltage * expected_current,
                        float(row["MeasuredPowerW"]),
                    )
                    self.assertEqual("False", row["ComplianceTripped"])
                self.assertEqual(factor, dark_metadata["PolarityFactor"])
                self.assertEqual(
                    factor, dark_metadata["Polarity"]["polarity_factor"]
                )
                self.assertEqual(
                    "recipe_device_coordinate",
                    dark_metadata["VoltageColumnSemantics"]["SetVoltageV"],
                )
                self.assertEqual(
                    "physical_smu_command",
                    dark_metadata["VoltageColumnSemantics"][
                        "CommandedPhysicalVoltageV"
                    ],
                )
                self.assertNotIn(
                    "CommandedPhysicalVoltageV",
                    json.dumps(snapshot, ensure_ascii=False),
                )
                dark_position = events.index("dark_iv")
                self.assertIn("output_off", events[dark_position + 1:])
                self.assertFalse(any(
                    command[0] == "CV" and command[1] not in physical
                    for command in commands
                ))

    def test_dark_iv_forward_reverse_and_bidirectional_scans_keep_voltage_semantics(self) -> None:
        cases = (
            (0.0, 1.0, "forward", [0.0, 1.0]),
            (1.0, 0.0, "forward", [1.0, 0.0]),
            (0.0, 1.0, "reverse", [1.0, 0.0]),
            (1.0, 0.0, "reverse", [0.0, 1.0]),
            (0.0, 1.0, "bidirectional", [0.0, 1.0, 0.0]),
        )
        for factor in (-1, 1):
            for start, stop, direction, expected_setpoints in cases:
                with self.subTest(
                    factor=factor, start=start, stop=stop, direction=direction
                ):
                    driver = _RecordingSMUDriver()
                    control = SMUControlManager()
                    control.bind_driver(driver, output_confirmed_off=True)
                    control.acquire_recipe()
                    control.set_recipe_polarity_factor(factor)
                    adapter = ELMatrixHardwareAdapter(
                        control,
                        SimpleNamespace(),
                        SimpleNamespace(),
                        SimpleNamespace(),
                    )
                    settings = SimpleNamespace(
                        start_v=start,
                        stop_v=stop,
                        step_v=1.0,
                        direction=direction,
                        repeat_count=1,
                        current_compliance_ma=20.0,
                        nplc=1.0,
                        dwell_s=0.0,
                        inter_scan_delay_s=0.0,
                    )
                    try:
                        rows = adapter.run_dark_iv(settings, lambda: None)
                        expected_physical = [
                            value * factor for value in expected_setpoints
                        ]
                        self.assertEqual(
                            expected_setpoints,
                            [row["SetVoltageV"] for row in rows],
                        )
                        self.assertEqual(
                            expected_physical,
                            [row["CommandedPhysicalVoltageV"] for row in rows],
                        )
                        self.assertEqual(
                            [("CV", value, 0.020) for value in expected_physical],
                            [
                                command
                                for command in driver.commands
                                if command[0] == "CV"
                            ],
                        )
                        adapter.output_off()
                        self.assertFalse(driver.output)
                    finally:
                        control.safe_shutdown(SMUOwnership.RECIPE)

    def test_keysight_dark_iv_keeps_output_on_between_sweep_points(self) -> None:
        resource = _KeysightSweepResource()
        driver = KeysightB2900Driver(
            resource,
            SMUDevice(
                "USB0::KEYSIGHT-SWEEP::INSTR",
                manufacturer="Keysight Technologies",
                model="B2901B",
                serial_number="SWEEP-SERIAL",
                supported=True,
            ),
        )
        control = SMUControlManager()
        control.bind_driver(driver, output_confirmed_off=True)
        control.acquire_recipe()
        control.set_recipe_polarity_factor(1)
        adapter = ELMatrixHardwareAdapter(
            control,
            SimpleNamespace(),
            SimpleNamespace(),
            SimpleNamespace(),
        )
        settings = SimpleNamespace(
            start_v=0.0,
            stop_v=1.0,
            step_v=0.5,
            direction="forward",
            repeat_count=1,
            current_compliance_ma=20.0,
            nplc=1.0,
            dwell_s=0.0,
            inter_scan_delay_s=0.0,
        )
        try:
            rows = adapter.run_dark_iv(settings, lambda: None)
            self.assertEqual([0.0, 0.5, 1.0], [row["SetVoltageV"] for row in rows])
            self.assertEqual(1, resource.writes.count(":OUTP ON"))
            self.assertEqual(2, resource.writes.count(":OUTP OFF"))
            output_on = resource.writes.index(":OUTP ON")
            final_output_off = len(resource.writes) - 1 - resource.writes[::-1].index(
                ":OUTP OFF"
            )
            self.assertNotIn(":OUTP OFF", resource.writes[output_on + 1:final_output_off])
            self.assertEqual(1, resource.writes.count(":SOUR:FUNC:MODE VOLT"))
            self.assertIn(":SENS:CURR:NPLC 1", resource.writes)
            self.assertIn(":SENS:CURR:NPLC 0.2", resource.writes)
            self.assertFalse(resource.output)
            self.assertTrue(control.output_confirmed_off)
        finally:
            control.safe_shutdown(SMUOwnership.RECIPE)
            control.shutdown(safety_confirmed=True)

    def test_dark_iv_compliance_and_cancel_paths_still_safe_shutdown(self) -> None:
        for stage in ("compliance", "cancel"):
            with self.subTest(stage=stage), tempfile.TemporaryDirectory() as directory:
                recipe = _small_recipe(1)
                recipe.el_matrix.dark_frame_enabled = False
                recipe.dark_iv.enabled = True
                recipe.dark_iv.start_v = 1.0
                recipe.dark_iv.stop_v = 0.0
                recipe.dark_iv.step_v = 1.0
                recipe.dark_iv.dwell_s = 0.0
                driver = _RecordingSMUDriver()
                driver.compliance_tripped = stage == "compliance"
                control = SMUControlManager()
                control.bind_driver(driver, output_confirmed_off=True)
                control.acquire_recipe()
                hardware = _ControlBackedHardware(control, -1)

                def cancelled() -> bool:
                    return stage == "cancel" and any(
                        command[0] == "CV" for command in driver.commands
                    )

                try:
                    with self.assertRaises(Exception):
                        ELMatrixRunner(
                            recipe,
                            hardware,
                            directory,
                            report_progress=lambda _item: None,
                            is_cancel_requested=cancelled,
                        ).run()
                    self.assertTrue(hardware.safe)
                    self.assertFalse(driver.output)
                    self.assertIs(control.ownership, SMUOwnership.IDLE)
                    self.assertIn(("CV", -1.0, 0.020), driver.commands)
                finally:
                    control.shutdown(safety_confirmed=True)

    def test_current_density_metadata_tracks_positive_and_negative_physical_commands(self) -> None:
        for factor in (-1, 1):
            with self.subTest(polarity_factor=factor):
                metadata, commands, filename, footer, manifest = (
                    self._run_physical_command_case("current_density", factor)
                )
                expected = 0.001 * factor
                self.assertIn(("CC", expected, 3.0), commands)
                self.assertEqual(10.0, metadata["SetCurrentDensityMaCm2"])
                self.assertEqual(0.001, metadata["CalculatedSourceCurrentA"])
                self.assertEqual(factor, metadata["PolarityFactor"])
                self.assertEqual(expected, metadata["CommandedPhysicalCurrentA"])
                self.assertEqual(
                    expected * 1000.0,
                    metadata["CommandedPhysicalCurrentMa"],
                )
                self.assertIsNone(metadata["CommandedPhysicalVoltageV"])
                self.assertIn("_J10_", filename)
                self.assertIn("J=10 mA/cm²", footer)
                self.assertEqual(str(expected), manifest["CommandedPhysicalCurrentA"])
                self.assertEqual("", manifest["CommandedPhysicalVoltageV"])

    def test_voltage_metadata_tracks_positive_and_negative_physical_commands(self) -> None:
        for factor in (-1, 1):
            with self.subTest(polarity_factor=factor):
                metadata, commands, filename, footer, manifest = (
                    self._run_physical_command_case("voltage", factor)
                )
                expected = 1.0 * factor
                self.assertIn(("CV", expected, 0.020), commands)
                self.assertEqual(1.0, metadata["SetVoltageV"])
                self.assertEqual(factor, metadata["PolarityFactor"])
                self.assertEqual(expected, metadata["CommandedVoltageV"])
                self.assertEqual(expected, metadata["CommandedPhysicalVoltageV"])
                self.assertIsNone(metadata["CommandedPhysicalCurrentA"])
                self.assertIn("_V1.0_", filename)
                self.assertNotIn("_V-1.0_", filename)
                self.assertIn("V=1.0 V", footer)
                self.assertNotIn("V=-1.0 V", footer)
                self.assertEqual(str(expected), manifest["CommandedPhysicalVoltageV"])
                self.assertEqual("", manifest["CommandedPhysicalCurrentA"])

    def test_runner_dark_once_stabilizes_once_per_j_and_keeps_output_during_inner_matrix(self) -> None:
        recipe = _small_recipe(2)
        hardware = _FakeHardware()
        progress = []
        with tempfile.TemporaryDirectory() as directory:
            result = ELMatrixRunner(
                recipe, hardware, directory,
                report_progress=progress.append,
                is_cancel_requested=lambda: False,
                sample_ids={"CH1": "Sample/A", "CH2": "Sample B"},
                now=lambda: datetime(2026, 8, 14, 6, 0, 0).astimezone(),
            ).run()
            run_directory = Path(result["output_directory"])
            self.assertTrue(run_directory.is_dir())
            self.assertTrue((run_directory / "measurement_snapshot.json").is_file())
            self.assertTrue(Path(result["final_manifest"]).is_file())
            self.assertTrue((run_directory / "CH1_Sample_A").is_dir())
            self.assertTrue((run_directory / "CH2_Sample B").is_dir())
            manifest = (run_directory / "measurement_manifest.csv").read_text(
                encoding="utf-8-sig"
            )
            self.assertIn("Sample/A", manifest)
            self.assertIn("Sample B", manifest)
            current_metadata = json.loads(
                next(run_directory.rglob("*_J2_*.json")).read_text(encoding="utf-8")
            )
            self.assertEqual("current_density", current_metadata["OutputMode"])
            self.assertEqual(2.0, current_metadata["SetCurrentDensityMaCm2"])
            self.assertAlmostEqual(0.0002, current_metadata["CalculatedSourceCurrentA"])
            self.assertIsNone(current_metadata["SetVoltageV"])
        self.assertEqual(1, hardware.events.count("prepare_dark"))
        self.assertEqual(2, hardware.polarity_calls)
        self.assertEqual(2, hardware.events.count("dark_iv"))
        self.assertEqual(4, len([event for event in hardware.events if isinstance(event, tuple) and event[0] == "set_current"]))
        self.assertTrue(hardware.safe)
        completed = [item.current for item in progress]
        self.assertEqual(sorted(completed), completed)
        remaining = [item.remaining_time_s for item in progress]
        self.assertEqual(sorted(remaining, reverse=True), remaining)
        finishes = [item.estimated_finish for item in progress]
        self.assertEqual(sorted(finishes, reverse=True), finishes)
        self.assertEqual(recipe.matrix_capture_counts()["overall"], completed[-1])
        # Every route is preceded by both authoritative OUTPUT OFF and routing clear.
        for index, event in enumerate(hardware.events):
            if isinstance(event, tuple) and event[0] == "route":
                self.assertIn("output_off", hardware.events[:index])
                self.assertEqual("clear_routing", hardware.events[index - 1])

    def test_polarity_can_be_disabled_and_is_removed_from_execution(self) -> None:
        recipe = _small_recipe(3)
        recipe.polarity.enabled = False
        self.assertEqual([], recipe.validate())
        self.assertEqual(3, len(ELMatrixPlan(recipe).channels))

    def test_voltage_runner_sets_cv_once_per_setpoint_and_writes_v_outputs(self) -> None:
        recipe = _small_recipe(1)
        recipe.el_matrix.output_mode = "voltage"
        recipe.el_matrix.voltage_v = [0.8, 1.0]
        recipe.el_matrix.current_compliance_ma = 15.0
        hardware = _FakeHardware()
        progress = []
        with tempfile.TemporaryDirectory() as directory:
            result = ELMatrixRunner(
                recipe,
                hardware,
                directory,
                report_progress=progress.append,
                is_cancel_requested=lambda: False,
            ).run()
            run_directory = Path(result["output_directory"])
            voltage_json = next(run_directory.rglob("*_V0.8_*.json"))
            self.assertTrue(any(run_directory.rglob("*_V1.0_*.json")))
            metadata = json.loads(voltage_json.read_text(encoding="utf-8"))
            manifest = (run_directory / "measurement_manifest.csv").read_text(
                encoding="utf-8-sig"
            )
        voltage_events = [
            event for event in hardware.events
            if isinstance(event, tuple) and event[0] == "set_voltage"
        ]
        self.assertEqual(
            [("set_voltage", 0.8, 15.0), ("set_voltage", 1.0, 15.0)],
            voltage_events,
        )
        self.assertFalse(any(
            isinstance(event, tuple) and event[0] == "set_current"
            for event in hardware.events
        ))
        self.assertEqual("voltage", metadata["OutputMode"])
        self.assertEqual(0.8, metadata["SetVoltageV"])
        self.assertIsNone(metadata["SetCurrentDensityMaCm2"])
        self.assertIsNone(metadata["CalculatedSourceCurrentA"])
        self.assertEqual(0.0008, metadata["MeasuredCurrentA"])
        self.assertEqual(8.0, metadata["MeasuredCurrentDensityMaCm2"])
        self.assertIn("OutputMode", manifest)
        capture_progress = [item for item in progress if item.commanded_voltage_v is not None]
        self.assertEqual(0.8, capture_progress[0].commanded_voltage_v)
        dialog = MeasurementProgressDialog("Voltage")
        try:
            dialog.update_progress(capture_progress[-1])
            self.assertIn("V=1.0 V", dialog.condition_value.text())
            self.assertNotIn("J=", dialog.condition_value.text())
        finally:
            dialog.set_stopped()
            dialog.close()

    def test_hardware_adapter_cv_uses_recipe_output_and_converts_ma_to_a(self) -> None:
        calls = []
        control = SimpleNamespace(
            recipe_output=lambda *args: calls.append(args) or args[1]
        )
        adapter = ELMatrixHardwareAdapter(
            control, SimpleNamespace(), SimpleNamespace(), SimpleNamespace()
        )
        self.assertEqual(0.001, adapter.set_current(0.001, 3.0))
        self.assertEqual(1.1, adapter.set_voltage(1.1, 20.0))
        self.assertEqual([("CC", 0.001, 3.0), ("CV", 1.1, 0.02)], calls)

    def test_all_polarities_precede_shared_dark_and_channel_dark_iv(self) -> None:
        recipe = _small_recipe(2)
        hardware = _FakeHardware()
        with tempfile.TemporaryDirectory() as directory:
            ELMatrixRunner(recipe, hardware, directory,
                           report_progress=lambda _item: None,
                           is_cancel_requested=lambda: False).run()
        polarity_positions = [i for i, event in enumerate(hardware.events)
                              if isinstance(event, tuple) and event[0] == "polarity"]
        shared_position = hardware.events.index("prepare_dark")
        self.assertTrue(all(position < shared_position for position in polarity_positions))
        self.assertEqual(2, hardware.events.count("dark_iv"))
        for position, event in enumerate(hardware.events):
            if event == "dark_iv":
                self.assertIn("output_off", hardware.events[position + 1:])

    def test_matrix_time_estimates_remain_available_for_global_watchdogs(self) -> None:
        four = Recipe()
        for channel in four.channels:
            channel.enabled = True
        self.assertGreater(four.matrix_estimated_time_s(), 4500)

        repeat = Recipe()
        repeat.el_matrix.current_density_ma_cm2 = [2]
        repeat.el_matrix.repeat = 10
        self.assertAlmostEqual(1806.925, repeat.matrix_output_on_time_s(), places=3)

    def test_dark_iv_is_covered_by_continuous_output_watchdog(self) -> None:
        class SlowDarkHardware(_FakeHardware):
            def run_dark_iv(self, _settings, check_cancel):
                self.events.append("dark_iv")
                time.sleep(0.02)
                check_cancel()
                return []

        recipe = _small_recipe(1)
        recipe.el_matrix.dark_frame_enabled = False
        hardware = SlowDarkHardware()
        with tempfile.TemporaryDirectory() as directory:
            with self.assertRaisesRegex(RuntimeError, "max_output_time_s"):
                ELMatrixRunner(
                    recipe,
                    hardware,
                    directory,
                    report_progress=lambda _item: None,
                    is_cancel_requested=lambda: False,
                    max_output_time_s=0.001,
                ).run()
        self.assertTrue(hardware.safe)

    def test_runtime_error_always_reaches_shared_safe_shutdown(self) -> None:
        recipe = _small_recipe(1)
        hardware = _FakeHardware(fail_capture=True)
        with tempfile.TemporaryDirectory() as directory:
            with self.assertRaisesRegex(RuntimeError, "camera failed"):
                ELMatrixRunner(
                    recipe, hardware, directory,
                    report_progress=lambda _item: None,
                    is_cancel_requested=lambda: False,
                ).run()
        self.assertTrue(hardware.safe)

    def test_relay_smu_save_and_cancel_failures_all_use_safe_shutdown(self) -> None:
        recipe = _small_recipe(1)
        for stage in ("relay", "smu", "save", "cancel"):
            hardware = _FakeHardware()
            if stage == "relay":
                hardware.route_channel = lambda *_args: (_ for _ in ()).throw(RuntimeError("relay failed"))
            elif stage == "smu":
                hardware.set_current = lambda *_args: (_ for _ in ()).throw(RuntimeError("smu failed"))
            cancel_calls = 0
            def cancelled() -> bool:
                nonlocal cancel_calls
                cancel_calls += 1
                return stage == "cancel" and cancel_calls > 2
            target = "gui.el_matrix_runner.save_matrix_capture" if stage == "save" else "builtins.id"
            replacement = (
                lambda *_args, **_kwargs: (_ for _ in ()).throw(RuntimeError("save failed"))
                if stage == "save" else id
            )
            with self.subTest(stage=stage), tempfile.TemporaryDirectory() as directory:
                with patch(target, replacement):
                    with self.assertRaises(Exception):
                        ELMatrixRunner(
                            recipe, hardware, directory,
                            report_progress=lambda _item: None,
                            is_cancel_requested=cancelled,
                        ).run()
                self.assertTrue(hardware.safe)

    def test_safe_shutdown_failure_cannot_report_completion(self) -> None:
        recipe = _small_recipe(1)
        hardware = _FakeHardware()
        def failed_shutdown():
            hardware.events.append("safe_shutdown_failed")
            raise RuntimeError("safe shutdown verification failed")
        hardware.safe_shutdown = failed_shutdown
        with tempfile.TemporaryDirectory() as directory:
            with self.assertRaisesRegex(RuntimeError, "safe shutdown"):
                ELMatrixRunner(
                    recipe, hardware, directory,
                    report_progress=lambda _item: None,
                    is_cancel_requested=lambda: False,
                ).run()


class MatrixImageOutputTests(unittest.TestCase):
    def _metadata(self, measurement_type: str = "EL") -> dict[str, object]:
        return {
            "MeasurementType": measurement_type,
            "SampleID": "perovskite/TOPCon",
            "Channel": "CH1" if measurement_type == "EL" else "SHARED",
            "CommandedCurrentDensity": 12,
            "Gain": 500,
            "Exposure": 6000,
            "RepeatIndex": 1,
            "RepeatTotal": 1,
            "MeasuredCurrentMa": 1.19800000000003,
            "MeasuredVoltage": 1.24,
            "CameraTemperature": 39.8,
            "Timestamp": "2026-08-14 06:44:12",
            "ApplicableChannels": ["CH1", "CH2", "CH3"],
        }

    def test_raw_tiff_keeps_dimensions_and_pixels_while_jpeg_footer_is_below(self) -> None:
        raw = np.arange(8 * 6, dtype=np.uint16).reshape(6, 8)
        before = raw.copy()
        output = Recipe().output
        with tempfile.TemporaryDirectory() as directory:
            saved = save_matrix_capture(
                raw, Image.new("L", (8, 6)), Path(directory) / "capture",
                self._metadata(), output,
            )
            payload = json.loads(saved.metadata_path.read_text(encoding="utf-8"))
            self.assertEqual(str(saved.tiff_path), payload["RawTiffPath"])
            self.assertEqual(str(saved.footer_jpeg_path), payload["AnnotatedJpegPath"])
            self.assertEqual(str(saved.metadata_path), payload["MetadataJsonPath"])
            tiff = tifffile.imread(saved.tiff_path)
            np.testing.assert_array_equal(before, tiff)
            with Image.open(saved.footer_jpeg_path) as jpeg:
                self.assertEqual(8, jpeg.width)
                self.assertGreater(jpeg.height, 6)
        np.testing.assert_array_equal(before, raw)

    def test_uncompressed_annotated_buffer_preserves_the_complete_source_region(self) -> None:
        raw = Image.new("RGB", (200, 60), (12, 34, 56))
        annotated = annotated_jpeg_image(raw, format_el_footer(self._metadata()))
        self.assertEqual(raw.tobytes(), annotated.crop((0, 0, raw.width, raw.height)).tobytes())

    def test_footer_formatters_and_filename_sanitization(self) -> None:
        el_lines = "\n".join(format_el_footer(self._metadata()))
        for expected in ("perovskite/TOPCon", "CH1", "J=12", "Gain=500%", "6,000 ms", "1.198 mA", "1.24 V", "39.8 °C"):
            self.assertIn(expected, el_lines)
        dark_lines = "\n".join(format_dark_footer(self._metadata("DARK")))
        self.assertIn("Shared Dark", dark_lines)
        self.assertIn("CH1, CH2, CH3", dark_lines)
        self.assertNotIn("J=0", dark_lines)
        self.assertEqual("perovskite_TOPCon", sanitize_filename("perovskite/TOPCon"))

    def test_voltage_footer_identifies_commanded_voltage(self) -> None:
        metadata = self._metadata()
        metadata.update({
            "OutputMode": "voltage",
            "SetVoltageV": 1.05,
            "CommandedCurrentDensity": None,
        })
        rendered = "\n".join(format_el_footer(metadata))
        self.assertIn("V=1.05 V", rendered)
        self.assertNotIn("J=", rendered)

    def test_pixel_csv_products_follow_output_options(self) -> None:
        recipe = Recipe()
        recipe.output.export_pixel_csv = True
        image = np.array([[10, 20]], dtype=np.uint16)
        dark = np.array([[1, 30]], dtype=np.uint16)
        with tempfile.TemporaryDirectory() as directory:
            paths = save_pixel_csv_products(
                image, Path(directory) / "capture", recipe.output,
                dark_array=dark, exposure_ms=10,
            )
            self.assertEqual({"RAW", "DarkCorrected"}, set(paths))
            for path in paths.values():
                self.assertTrue(Path(path).is_file())


class MeasurementSnapshotAndPreflightTests(unittest.TestCase):
    def test_snapshot_is_deep_immutable_and_hash_matches_saved_content(self) -> None:
        recipe = _small_recipe(1)
        snapshot = build_el_matrix_snapshot(
            recipe, execution_order=[{"phase": "polarity"}],
            camera={"CameraModel": "Fake", "ImageWidth": 4, "ImageHeight": 3,
                    "Resolution": "4x3", "PixelFormat": "RGB24", "BitDepth": 8},
            smu={"model": "B2901BL"}, relay_mapping={"Ch1": 5},
            polarity_settings=PolarityMeasurementSettings(),
            sample_ids={"CH1": "ORIGINAL"},
        )
        recipe.channels[0].area_cm2 = 999
        self.assertNotIn("sample_id", snapshot["recipe"]["complete_snapshot"]["channels"][0])
        self.assertEqual("ORIGINAL", snapshot["channels"][0]["sample_id"])
        self.assertTrue(verify_snapshot_hash(snapshot))
        self.assertEqual("current_density", snapshot["el_matrix"]["output_mode"])
        self.assertEqual([0.8, 1.0, 1.1, 1.2], list(snapshot["el_matrix"]["voltage_v"]))
        self.assertEqual(3.0, snapshot["el_matrix"]["voltage_compliance_v"])
        self.assertEqual(20.0, snapshot["el_matrix"]["current_compliance_ma"])
        with self.assertRaises(TypeError):
            snapshot["camera"]["CameraModel"] = "changed"

    def test_preflight_aggregates_visa_and_relay_mapping_mismatch(self) -> None:
        recipe = _small_recipe(1)
        relay = RelaySettings.defaults()
        relay.smu_output_channels["Ch2"] = relay.smu_output_channels["Ch1"]
        camera = {"Resolution": "4x3", "PixelFormat": "RGB24", "BitDepth": 8,
                  "ImageWidth": 4, "ImageHeight": 3}
        current = dict(camera)
        current.update({
            "ScientificMeasurementReady": True,
            "exposure_range_us": (1, 1000000, 1),
            "gain_range": (0, 500, 1),
        })
        with tempfile.TemporaryDirectory() as directory:
            errors = collect_preflight_errors(
                recipe,
                smu_metadata={"connected": True, "supported": True,
                              "manufacturer": "Keysight Technologies", "model": "B2901BL",
                              "visa_address": "USB::ACTUAL"},
                smu_output_confirmed_off=True, relay_connected=True,
                relay_settings=relay, camera_connected=True,
                camera_snapshot=camera, current_camera=current, output_root=directory,
            )
        self.assertFalse(any("VISA" in item for item in errors))
        self.assertTrue(any("不可重複" in item or "不完整或不唯一" in item for item in errors))

    def test_preflight_blocks_until_actual_scientific_frame_is_validated(self) -> None:
        recipe = _small_recipe(1)
        camera = {
            "Resolution": "4x3",
            "PixelFormat": "MONO16",
            "BitDepth": 12,
            "ContainerDtype": "uint16",
            "ImageWidth": 4,
            "ImageHeight": 3,
        }
        current = dict(camera)
        current.update({
            "ScientificMeasurementReady": False,
            "exposure_range_us": (1, 1_000_000, 1),
            "gain_range": (0, 500, 1),
        })
        with tempfile.TemporaryDirectory() as directory:
            errors = collect_preflight_errors(
                recipe,
                smu_metadata={
                    "connected": True,
                    "supported": True,
                    "manufacturer": "Keysight Technologies",
                    "model": "B2901BL",
                },
                smu_output_confirmed_off=True,
                relay_connected=True,
                relay_settings=RelaySettings.defaults(),
                camera_connected=True,
                camera_snapshot=camera,
                current_camera=current,
                output_root=directory,
            )
        self.assertTrue(any("scientific MONO16" in item for item in errors))
        self.assertTrue(any("uint16 H×W frame" in item for item in errors))


class _FakeCameraController(QObject):
    frame_ready = Signal(QImage)

    def __init__(self) -> None:
        super().__init__()
        self.is_open = True
        self.device_name = "Fake Camera"
        self.requested = (0, 0)
        self.configure_calls = 0
        self.restored_state = None

    def set_manual_exposure(self, exposure_us: int, gain: int) -> None:
        self.configure_calls += 1
        self.requested = (exposure_us, gain)

    def current_exposure(self):
        return self.requested

    def read_temperature_c(self):
        return 39.8

    def restore_exposure_state(self, state):
        self.restored_state = dict(state)


class _SequencedCameraController(_FakeCameraController):
    frame_ready_sequenced = Signal(QImage, int)

    def __init__(self) -> None:
        super().__init__()
        self.frame_sequence = 10


class _RoundedCameraController(_FakeCameraController):
    def set_manual_exposure(self, exposure_us: int, gain: int) -> None:
        self.configure_calls += 1
        self.requested = (exposure_us - 3, gain + 1)


class CameraCaptureBridgeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.app = ensure_qapplication()

    def test_bridge_reuses_one_existing_live_frame_without_second_capture(self) -> None:
        controller = _FakeCameraController()
        bridge = CameraCaptureBridge(controller)
        result: list[CapturedFrame] = []
        live_view: list[QImage] = []
        controller.frame_ready.connect(lambda image: live_view.append(image.copy()))
        failure: list[Exception] = []

        def worker() -> None:
            try:
                result.append(bridge.capture(50, 200, 2, lambda: None))
            except Exception as exc:
                failure.append(exc)

        thread = threading.Thread(target=worker)
        thread.start()
        deadline = time.monotonic() + 1
        while controller.configure_calls == 0 and time.monotonic() < deadline:
            self.app.processEvents()
            time.sleep(0.005)
        image = QImage(5, 4, QImage.Format.Format_RGB888)
        image.fill(QColor(1, 2, 3))
        controller.frame_ready.emit(image)
        while thread.is_alive() and time.monotonic() < deadline:
            self.app.processEvents()
            time.sleep(0.005)
        thread.join(timeout=0.1)
        self.assertFalse(failure)
        self.assertEqual(1, controller.configure_calls)
        self.assertEqual(1, len(result))
        self.assertEqual(1, len(live_view))
        self.assertEqual((5, 4), (result[0].image.width(), result[0].image.height()))

    def test_bridge_discards_queued_old_generation_after_setting_change(self) -> None:
        controller = _SequencedCameraController()
        bridge = CameraCaptureBridge(controller)
        result: list[CapturedFrame] = []
        thread = threading.Thread(
            target=lambda: result.append(bridge.capture(50, 200, 2, lambda: None))
        )
        thread.start()
        deadline = time.monotonic() + 1
        while controller.configure_calls == 0 and time.monotonic() < deadline:
            self.app.processEvents(); time.sleep(0.005)
        old = QImage(2, 2, QImage.Format.Format_RGB888); old.fill(QColor(255, 0, 0))
        new = QImage(3, 2, QImage.Format.Format_RGB888); new.fill(QColor(0, 255, 0))
        controller.frame_ready_sequenced.emit(old, 10)
        controller.frame_sequence = 11
        controller.frame_ready_sequenced.emit(new, 11)
        while thread.is_alive() and time.monotonic() < deadline:
            self.app.processEvents(); time.sleep(0.005)
        thread.join(timeout=0.1)
        self.assertEqual((3, 2), (result[0].image.width(), result[0].image.height()))

    def test_bridge_discards_settling_frames_without_reconfiguring_camera(self) -> None:
        controller = _SequencedCameraController()
        bridge = CameraCaptureBridge(controller)
        result: list[CapturedFrame] = []
        thread = threading.Thread(
            target=lambda: result.append(bridge.capture(
                50, 200, 2, lambda: None, settling_frames=2
            ))
        )
        thread.start()
        deadline = time.monotonic() + 1
        while controller.configure_calls == 0 and time.monotonic() < deadline:
            self.app.processEvents(); time.sleep(0.005)
        for sequence, width in ((11, 2), (12, 3), (13, 4)):
            controller.frame_sequence = sequence
            image = QImage(width, 2, QImage.Format.Format_RGB888)
            controller.frame_ready_sequenced.emit(image, sequence)
            self.app.processEvents()
        while thread.is_alive() and time.monotonic() < deadline:
            self.app.processEvents(); time.sleep(0.005)
        thread.join(timeout=0.1)
        self.assertEqual(1, controller.configure_calls)
        self.assertEqual((4, 2), (result[0].image.width(), result[0].image.height()))

    def test_bridge_restores_camera_state_on_owner_thread(self) -> None:
        controller = _FakeCameraController()
        bridge = CameraCaptureBridge(controller)
        failure: list[Exception] = []
        state = {"ExposureReadbackUs": 2500, "GainReadback": 150}

        def worker() -> None:
            try:
                bridge.restore_state(state, timeout_s=1.0)
            except Exception as exc:
                failure.append(exc)

        thread = threading.Thread(target=worker)
        thread.start()
        deadline = time.monotonic() + 1
        while thread.is_alive() and time.monotonic() < deadline:
            self.app.processEvents()
            time.sleep(0.005)
        thread.join(timeout=0.1)
        self.assertFalse(failure)
        self.assertEqual(state, controller.restored_state)

    def test_bridge_can_preserve_actual_calibration_readback(self) -> None:
        controller = _RoundedCameraController()
        bridge = CameraCaptureBridge(controller)
        result: list[CapturedFrame] = []
        failure: list[Exception] = []

        def worker() -> None:
            try:
                result.append(bridge.capture(
                    50,
                    200,
                    2,
                    lambda: None,
                    accept_actual_readback=True,
                ))
            except Exception as exc:
                failure.append(exc)

        thread = threading.Thread(target=worker)
        thread.start()
        deadline = time.monotonic() + 1
        while controller.configure_calls == 0 and time.monotonic() < deadline:
            self.app.processEvents()
            time.sleep(0.005)
        image = QImage(3, 2, QImage.Format.Format_RGB888)
        controller.frame_ready.emit(image)
        while thread.is_alive() and time.monotonic() < deadline:
            self.app.processEvents()
            time.sleep(0.005)
        thread.join(timeout=0.1)
        self.assertFalse(failure)
        self.assertEqual(49_997, result[0].camera_metadata["ExposureReadbackUs"])
        self.assertEqual(201, result[0].camera_metadata["GainReadback"])

    def test_progress_window_is_modeless_and_close_does_not_request_stop(self) -> None:
        dialog = MeasurementProgressDialog("EL_Matrix_Standard")
        stops: list[bool] = []
        dialog.stop_requested.connect(lambda: stops.append(True))
        self.assertFalse(dialog.isModal())
        dialog.show()
        self.app.processEvents()
        dialog.close()
        self.app.processEvents()
        self.assertFalse(stops)
        self.assertFalse(dialog.isVisible())
        dialog.set_stopped()

    def test_live_view_updates_without_reenabling_capture_controls(self) -> None:
        class _Widget:
            def __init__(self): self.enabled = True; self.value = None
            def setEnabled(self, value): self.enabled = bool(value)
            def setText(self, value): self.value = value
        class _View:
            def __init__(self): self.image = None
            def set_image(self, image): self.image = image.copy()
        window = SimpleNamespace(
            _measurement_worker=object(), last_image=None, image_view=_View(),
            resolution_status=_Widget(), capture_button=_Widget(),
            auto_capture_button=_Widget(), capture_action=_Widget(),
            auto_capture_action=_Widget(), _capture_next_frame=False,
            _pending_auto_path=None,
        )
        image = QImage(7, 5, QImage.Format.Format_RGB888)
        MainWindowDeviceMixin.on_frame_ready(window, image)
        self.assertEqual((7, 5), (window.image_view.image.width(), window.image_view.image.height()))
        for name in ("capture_button", "auto_capture_button", "capture_action", "auto_capture_action"):
            self.assertFalse(getattr(window, name).enabled)


if __name__ == "__main__":
    unittest.main()
