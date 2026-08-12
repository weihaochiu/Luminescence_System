from __future__ import annotations

from contextlib import contextmanager
import math
import os
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from gui.keysight_b2900 import KeysightB2900Driver
from gui.measurement_snapshot import build_measurement_snapshot
from gui.polarity_measurement import PolarityMeasurementError, PolarityMeasurementService
from gui.polarity_settings import PolarityMeasurementSettings, PolaritySettingsStore
from gui.recipe_store import Recipe
from gui.smu_base import SMUDevice


class SamplingDriver:
    def __init__(self, currents: list[float], voltages: list[float], nplc: bool = True) -> None:
        self.currents = iter(currents)
        self.voltages = iter(voltages)
        self.output = False
        self.events: list[object] = []
        self.nplc = nplc
        self.confirm_output = True

    def configure_voltage_source(self, value: float, compliance: float) -> None:
        self.events.append(("configure_jsc", value, compliance))

    def configure_current_source(self, value: float, compliance: float) -> None:
        self.events.append(("configure_voc", value, compliance))

    def set_output_enabled(self, enabled: bool) -> None:
        self.output = enabled
        self.events.append(("output", enabled))

    def query_output_enabled(self) -> bool | None:
        if self.output and not self.confirm_output:
            return None
        return self.output

    def measure_current(self) -> float:
        value = next(self.currents)
        self.events.append(("jsc", value))
        return value

    def measure_voltage(self) -> float:
        value = next(self.voltages)
        self.events.append(("voc", value))
        return value

    @contextmanager
    def temporary_measurement_nplc(self, mode: str, nplc: float):
        if not self.nplc:
            yield False
            return
        self.events.append(("nplc_on", mode, nplc))
        try:
            yield True
        finally:
            self.events.append(("nplc_restore", mode))


class Resource:
    def __init__(self) -> None:
        self.writes: list[str] = []
        self.responses = {
            ":SENS:CURR:NPLC?": "0.2",
            ":SENS:VOLT:NPLC?": "0.5",
            ":SENS:CURR:NPLC:AUTO?": "1",
            ":SENS:VOLT:NPLC:AUTO?": "0",
        }

    def write(self, command: str) -> None:
        self.writes.append(command)

    def query(self, command: str) -> str:
        return self.responses[command]


class PolaritySettingsTests(unittest.TestCase):
    def test_store_save_load_and_reset_defaults(self) -> None:
        with TemporaryDirectory() as directory:
            path = Path(directory) / "polarity_settings.json"
            store = PolaritySettingsStore(path)
            store.settings.jsc_sample_count = 9
            store.settings.integration_nplc = 2.0
            store.save()
            loaded = PolaritySettingsStore(path)
            self.assertEqual(9, loaded.settings.jsc_sample_count)
            self.assertEqual(2.0, loaded.settings.integration_nplc)
            loaded.reset_defaults()
            self.assertEqual(5, loaded.settings.jsc_sample_count)
            self.assertEqual(1.0, loaded.settings.integration_nplc)

    def test_recipe_contains_no_duplicate_polarity_parameters(self) -> None:
        self.assertEqual({"enabled": True}, Recipe().to_dict()["polarity"])

    def test_measurement_snapshot_captures_shared_settings_and_result(self) -> None:
        settings = PolarityMeasurementSettings(jsc_sample_count=7)
        snapshot = build_measurement_snapshot(
            Recipe(),
            type("HDR", (), {"snapshot": lambda self: {}})(),
            "test",
            polarity_settings=settings,
            polarity_result={"polarity_result": "NORMAL", "polarity_factor": 1},
        )
        polarity = snapshot["polarity_measurement"]
        self.assertEqual(7, polarity["system_settings_snapshot"]["settings"]["jsc_sample_count"])
        self.assertEqual("NORMAL", polarity["result"]["polarity_result"])

    def test_settings_menu_and_manual_use_the_global_store(self) -> None:
        root = Path(__file__).parents[1] / "gui"
        ui = (root / "main_window_ui.py").read_text(encoding="utf-8")
        devices = (root / "main_window_devices.py").read_text(encoding="utf-8")
        self.assertIn('QAction("極性確認…"', ui)
        self.assertIn("settings_menu.addAction(self.polarity_settings_action)", ui)
        self.assertIn("self.polarity_settings_store.settings", devices)


class PolarityMeasurementTests(unittest.TestCase):
    def settings(self, **overrides) -> PolarityMeasurementSettings:
        values = dict(
            white_light_stabilization_ms=0,
            anti_flicker_enabled=True,
            integration_nplc=1.0,
            jsc_settle_ms=0,
            jsc_sample_count=5,
            jsc_aggregation="median",
            jsc_minimum_valid_ma_cm2=0.1,
            jsc_max_variation_percent=10.0,
            jsc_compliance_ma_cm2=20.0,
            voc_settle_ms=0,
            voc_sample_count=5,
            voc_aggregation="median",
            voc_minimum_valid_v=0.1,
            voc_max_variation_percent=10.0,
            voc_compliance_v=2.0,
        )
        values.update(overrides)
        return PolarityMeasurementSettings(**values)

    def measure(self, driver: SamplingDriver, settings: PolarityMeasurementSettings):
        return PolarityMeasurementService().measure(
            driver,
            settings,
            1.0,
            light_on=lambda: driver.events.append("light_on"),
            light_off=lambda: driver.events.append("light_off"),
            check_cancel=lambda: None,
            wait_ms=lambda value: driver.events.append(("wait", value)),
            status=lambda value: driver.events.append(("status", value)),
        )

    def test_five_jsc_and_voc_samples_use_nplc_and_median(self) -> None:
        driver = SamplingDriver(
            [-0.00201, -0.00202, -0.00200, -0.00203, -0.00201],
            [0.801, 0.802, 0.800, 0.803, 0.801],
        )
        result = self.measure(driver, self.settings())
        self.assertEqual(5, len(result.jsc_ma_cm2.samples))
        self.assertEqual(5, len(result.voc_v.samples))
        self.assertAlmostEqual(-2.01, result.jsc_ma_cm2.representative)
        self.assertAlmostEqual(0.801, result.voc_v.representative)
        self.assertIn(("nplc_on", "CURR", 1.0), driver.events)
        self.assertIn(("nplc_on", "VOLT", 1.0), driver.events)
        self.assertIn(("nplc_restore", "CURR"), driver.events)
        self.assertIn(("nplc_restore", "VOLT"), driver.events)

    def test_mean_aggregation(self) -> None:
        stats = PolarityMeasurementService.analyze([-1.0, -2.0, -3.0], "mean", 0.1, 300, "Jsc")
        self.assertEqual(-2.0, stats.representative)

    def test_unstable_jsc_and_voc_fail(self) -> None:
        with self.assertRaisesRegex(PolarityMeasurementError, "Jsc variation"):
            PolarityMeasurementService.analyze([-0.1, -2.0, -0.3, -2.2, -0.2], "median", 0.01, 10, "Jsc")
        with self.assertRaisesRegex(PolarityMeasurementError, "Voc variation"):
            PolarityMeasurementService.analyze([0.1, 0.8, 0.2, 0.9, 0.3], "median", 0.01, 10, "Voc")

        driver = SamplingDriver(
            [-0.0001, -0.002, -0.0003, -0.0022, -0.0002],
            [0.8] * 5,
        )
        with self.assertRaisesRegex(PolarityMeasurementError, "Jsc variation"):
            self.measure(driver, self.settings())
        self.assertFalse(driver.output)
        self.assertEqual("light_off", driver.events[-1])

    def test_unconfirmed_temporary_output_is_forced_off(self) -> None:
        driver = SamplingDriver([-0.002] * 5, [0.8] * 5)
        driver.confirm_output = False
        with self.assertRaisesRegex(PolarityMeasurementError, "OUTPUT ON"):
            self.measure(driver, self.settings())
        self.assertFalse(driver.output)
        self.assertIn(("output", False), driver.events)

    def test_light_on_failure_still_attempts_light_off(self) -> None:
        driver = SamplingDriver([-0.002] * 5, [0.8] * 5)
        events: list[str] = []

        def fail_light_on() -> None:
            events.append("LIGHT_ON_ATTEMPT")
            raise RuntimeError("relay transport failed")

        with self.assertRaisesRegex(RuntimeError, "relay transport failed"):
            PolarityMeasurementService().measure(
                driver,
                self.settings(),
                1.0,
                light_on=fail_light_on,
                light_off=lambda: events.append("LIGHT_OFF"),
                check_cancel=lambda: None,
                wait_ms=lambda _milliseconds: None,
                status=lambda _message: None,
            )
        self.assertEqual(["LIGHT_ON_ATTEMPT", "LIGHT_OFF"], events)

    def test_below_threshold_inconsistent_sign_and_nan_fail(self) -> None:
        with self.assertRaisesRegex(PolarityMeasurementError, "below"):
            PolarityMeasurementService.analyze([-0.01] * 5, "median", 0.1, 10, "Jsc")
        with self.assertRaisesRegex(PolarityMeasurementError, "signs"):
            PolarityMeasurementService.analyze([-1, -1, 1, -1, -1], "median", 0.1, 300, "Jsc")
        with self.assertRaisesRegex(PolarityMeasurementError, "invalid"):
            PolarityMeasurementService.analyze([1, 1, math.nan], "mean", 0.1, 10, "Voc")

    def test_driver_without_nplc_capability_continues_without_crash(self) -> None:
        driver = SamplingDriver([-0.002] * 5, [0.8] * 5, nplc=False)
        result = self.measure(driver, self.settings())
        self.assertEqual("NORMAL", result.state)

    def test_cancellation_is_checked_between_individual_samples(self) -> None:
        driver = SamplingDriver([-0.002] * 5, [0.8] * 5)
        checks = 0

        def check() -> None:
            nonlocal checks
            checks += 1
            if checks >= 6:
                raise RuntimeError("cancelled")

        with self.assertRaisesRegex(RuntimeError, "cancelled"):
            PolarityMeasurementService().measure(
                driver,
                self.settings(),
                1.0,
                light_on=lambda: driver.events.append("light_on"),
                light_off=lambda: driver.events.append("light_off"),
                check_cancel=check,
                wait_ms=lambda _value: None,
                status=lambda _value: None,
            )
        self.assertLess(len([event for event in driver.events if isinstance(event, tuple) and event[0] == "jsc"]), 5)
        self.assertFalse(driver.output)
        self.assertEqual("light_off", driver.events[-1])

    def test_b2900_temporary_nplc_restores_both_functions(self) -> None:
        resource = Resource()
        driver = KeysightB2900Driver(resource, SMUDevice("USB", supported=True))
        with driver.temporary_measurement_nplc("CURR", 1.0):
            pass
        with driver.temporary_measurement_nplc("VOLT", 2.0):
            pass
        self.assertEqual(
            [
                ":SENS:CURR:NPLC:AUTO OFF",
                ":SENS:CURR:NPLC 1",
                ":SENS:CURR:NPLC 0.2",
                ":SENS:CURR:NPLC:AUTO ON",
                ":SENS:VOLT:NPLC:AUTO OFF",
                ":SENS:VOLT:NPLC 2",
                ":SENS:VOLT:NPLC 0.5",
                ":SENS:VOLT:NPLC:AUTO OFF",
            ],
            resource.writes,
        )


if __name__ == "__main__":
    unittest.main()
