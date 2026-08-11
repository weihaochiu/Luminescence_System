from __future__ import annotations

import threading
import time
import unittest

from gui.smu_base import SMUDevice, SMUDriver
from gui.smu_control import (
    PolarityService,
    SMUControlManager,
    SMUInterlockError,
    SMUOperationState,
    SMUOwnership,
    SMUSafetyService,
)
from gui.smu_manager import SMUManager


class FakeSMU(SMUDriver):
    def __init__(self) -> None:
        super().__init__(object(), SMUDevice("FAKE", supported=True))
        self.commands: list[tuple] = []
        self.output = False
        self.voltage = 0.0
        self.current = 0.0
        self.fail_configure = False
        self.safe_stop_failures: list[str] = []
        self.block_configure = False
        self.configure_started = threading.Event()
        self.continue_configure = threading.Event()
        self.query_returns_unknown = False
        self.concurrent_io = False
        self._active_io = 0
        self._guard = threading.Lock()

    def _enter(self) -> None:
        with self._guard:
            self._active_io += 1
            if self._active_io > 1:
                self.concurrent_io = True

    def _leave(self) -> None:
        with self._guard:
            self._active_io -= 1

    def configure_voltage_source(self, volts: float, current_compliance_a: float) -> None:
        self._enter()
        try:
            self.configure_started.set()
            if self.block_configure:
                self.continue_configure.wait(timeout=1.0)
            if self.fail_configure:
                raise RuntimeError("configure failed")
            self.voltage = volts
            self.commands.append(("CV", volts, current_compliance_a))
        finally:
            self._leave()

    def configure_current_source(self, amps: float, voltage_compliance_v: float) -> None:
        self._enter()
        try:
            self.configure_started.set()
            if self.block_configure:
                self.continue_configure.wait(timeout=1.0)
            if self.fail_configure:
                raise RuntimeError("configure failed")
            self.current = amps
            self.commands.append(("CC", amps, voltage_compliance_v))
        finally:
            self._leave()

    def set_output_enabled(self, enabled: bool) -> None:
        self.output = enabled
        self.commands.append(("OUTPUT", enabled))

    def safe_stop(self) -> list[str]:
        self._enter()
        try:
            self.voltage = 0.0
            self.current = 0.0
            if not self.safe_stop_failures:
                self.output = False
            self.commands.extend([("VOLT", 0.0), ("CURR", 0.0), ("OUTPUT", False)])
            return list(self.safe_stop_failures)
        finally:
            self._leave()

    def measure_voltage(self) -> float:
        self._enter()
        try:
            time.sleep(0.02)
            return self.voltage
        finally:
            self._leave()

    def measure_current(self) -> float:
        return self.current

    def query_output_enabled(self) -> bool | None:
        return None if self.query_returns_unknown else self.output

    def query_compliance_tripped(self, mode: str) -> bool:
        return False


class SMUControlTests(unittest.TestCase):
    def setUp(self) -> None:
        self.driver = FakeSMU()
        self.control = SMUControlManager()
        self.control.bind_driver(self.driver)
        self.control.set_confirmed_polarity_factor(1)

    def tearDown(self) -> None:
        self.control.shutdown()

    def wait_until(self, predicate, timeout: float = 1.0) -> None:
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if predicate():
                return
            time.sleep(0.005)
        self.fail("Timed out waiting for asynchronous SMU operation")

    def test_manual_cc_on_off_returns_to_idle(self) -> None:
        self.assertTrue(self.control.request_manual_output("CC", 0.010, 2.0))
        self.wait_until(lambda: self.control.output_enabled)
        self.assertIn(("CC", 0.010, 2.0), self.driver.commands)
        self.wait_until(lambda: not self.control.is_busy)
        self.assertTrue(self.control.request_manual_off())
        self.wait_until(lambda: self.control.ownership is SMUOwnership.IDLE)
        self.assertFalse(self.driver.output)

    def test_manual_cv_on_off_returns_to_idle(self) -> None:
        self.assertTrue(self.control.request_manual_output("CV", 1.2, 0.020))
        self.wait_until(lambda: self.control.output_enabled)
        self.assertIn(("CV", 1.2, 0.020), self.driver.commands)
        self.wait_until(lambda: not self.control.is_busy)
        self.assertTrue(self.control.request_manual_off())
        self.wait_until(lambda: self.control.ownership is SMUOwnership.IDLE)

    def test_polarity_translation_is_shared_and_idempotent(self) -> None:
        polarity = PolarityService()
        self.assertIsNone(polarity.factor)
        self.assertFalse(polarity.is_confirmed)
        polarity.set_confirmed_factor(-1)
        polarity.set_confirmed_factor(-1)
        self.assertEqual(-1, polarity.factor)
        self.assertEqual(-0.010, polarity.to_physical(0.010))
        observed_factors: list[object] = []
        self.control.polarity_changed.connect(observed_factors.append)
        self.control.set_confirmed_polarity_factor(-1)
        self.assertEqual([-1], observed_factors)
        self.control.request_manual_output("CC", 0.010, 2.0)
        self.wait_until(lambda: self.control.output_enabled)
        self.assertIn(("CC", -0.010, 2.0), self.driver.commands)

    def test_manual_and_recipe_are_interlocked_below_gui(self) -> None:
        self.control.request_manual_output("CC", 0.001, 2.0)
        self.wait_until(lambda: self.control.output_enabled)
        with self.assertRaises(SMUInterlockError):
            self.control.acquire_recipe()
        self.control.safe_shutdown(SMUOwnership.MANUAL)
        self.control.acquire_recipe()
        with self.assertRaises(SMUInterlockError):
            self.control.acquire(SMUOwnership.MANUAL)

    def test_manual_to_recipe_requires_zero_off_release_then_acquire(self) -> None:
        self.control.request_manual_output("CC", 0.010, 2.0)
        self.wait_until(lambda: self.control.output_enabled)
        with self.assertRaises(SMUInterlockError):
            self.control.prepare_recipe_start(close_manual=False)
        self.control.prepare_recipe_start(close_manual=True)
        self.assertEqual(SMUOwnership.RECIPE, self.control.ownership)
        self.assertFalse(self.driver.output)
        self.assertEqual(
            [("VOLT", 0.0), ("CURR", 0.0), ("OUTPUT", False)],
            self.driver.commands[-3:],
        )

    def test_recipe_cleanup_and_exception_style_finally_leave_output_off(self) -> None:
        self.control.acquire_recipe()
        try:
            self.control.recipe_output("CV", 1.0, 0.020)
            raise RuntimeError("simulated Recipe failure")
        except RuntimeError:
            pass
        finally:
            self.control.safe_shutdown(SMUOwnership.RECIPE)
        self.assertFalse(self.driver.output)
        self.assertEqual(SMUOwnership.IDLE, self.control.ownership)

    def test_emergency_off_clears_output_and_ownership(self) -> None:
        self.control.request_manual_output("CC", 0.002, 2.0)
        self.wait_until(lambda: self.control.output_enabled)
        self.assertTrue(self.control.request_emergency_off())
        self.wait_until(lambda: self.control.ownership is SMUOwnership.IDLE)
        self.assertFalse(self.driver.output)

    def test_double_manual_request_preserves_first_operation_ownership(self) -> None:
        self.driver.block_configure = True
        self.assertTrue(self.control.request_manual_output("CC", 0.002, 2.0))
        self.assertTrue(self.driver.configure_started.wait(timeout=1.0))

        self.assertFalse(self.control.request_manual_output("CC", 0.003, 2.0))
        self.assertEqual(SMUOwnership.MANUAL, self.control.ownership)
        self.assertEqual(SMUOperationState.BUSY, self.control.operation_state)
        self.assertFalse(self.driver.output)

        self.driver.continue_configure.set()
        self.wait_until(lambda: self.control.output_enabled and not self.control.is_busy)
        self.assertEqual(SMUOwnership.MANUAL, self.control.ownership)
        self.assertTrue(self.control.request_manual_off())
        self.wait_until(
            lambda: self.control.ownership is SMUOwnership.IDLE
            and not self.control.is_busy
        )
        self.assertFalse(self.driver.output)

    def test_emergency_between_configure_and_output_prevents_output_on(self) -> None:
        self.driver.block_configure = True
        self.assertTrue(self.control.request_manual_output("CC", 0.002, 2.0))
        self.assertTrue(self.driver.configure_started.wait(timeout=1.0))

        self.assertTrue(self.control.request_emergency_off())
        self.assertTrue(self.control.emergency_latched)
        self.assertEqual(SMUOwnership.EMERGENCY, self.control.ownership)
        self.driver.continue_configure.set()

        self.wait_until(
            lambda: self.control.ownership is SMUOwnership.IDLE
            and not self.control.is_busy
        )
        self.assertFalse(self.driver.output)
        self.assertNotIn(("OUTPUT", True), self.driver.commands)
        self.assertFalse(self.control.emergency_latched)

    def test_unknown_polarity_rejects_manual_without_driver_commands(self) -> None:
        driver = FakeSMU()
        control = SMUControlManager()
        control.bind_driver(driver)
        try:
            with self.assertRaisesRegex(SMUInterlockError, "尚未確認元件極性"):
                control.request_manual_output("CC", 0.002, 2.0)
            self.assertEqual([], driver.commands)
            self.assertEqual(SMUOwnership.IDLE, control.ownership)
        finally:
            control.shutdown()

    def test_unknown_polarity_rejects_recipe_without_driver_commands(self) -> None:
        driver = FakeSMU()
        control = SMUControlManager()
        control.bind_driver(driver)
        try:
            control.acquire_recipe()
            with self.assertRaisesRegex(SMUInterlockError, "尚未確認元件極性"):
                control.recipe_output("CV", 1.0, 0.020)
            self.assertEqual([], driver.commands)
        finally:
            control.shutdown()

    def test_confirmed_polarity_restores_output_for_both_factors(self) -> None:
        for factor in (1, -1):
            self.control.set_confirmed_polarity_factor(factor)
            self.assertTrue(self.control.request_manual_output("CC", 0.002, 2.0))
            self.wait_until(lambda: self.control.output_enabled and not self.control.is_busy)
            self.assertIn(("CC", factor * 0.002, 2.0), self.driver.commands)
            self.assertTrue(self.control.request_manual_off())
            self.wait_until(
                lambda: self.control.ownership is SMUOwnership.IDLE
                and not self.control.is_busy
            )

    def test_safe_stop_failure_does_not_claim_confirmed_safe(self) -> None:
        self.assertTrue(self.control.request_manual_output("CC", 0.002, 2.0))
        self.wait_until(lambda: self.control.output_enabled and not self.control.is_busy)
        self.driver.safe_stop_failures = [":OUTP OFF: VISA failure"]

        self.assertFalse(self.control.safe_shutdown(SMUOwnership.MANUAL))
        self.assertFalse(self.control.output_confirmed_off)
        self.assertFalse(self.control.last_shutdown_ok)
        self.assertEqual(SMUOwnership.FAULT, self.control.ownership)
        self.assertEqual(SMUOperationState.FAULT, self.control.operation_state)
        self.driver.safe_stop_failures = []

    def test_safety_rejects_setpoint_power_and_compliance(self) -> None:
        safety = SMUSafetyService()
        with self.assertRaises(ValueError):
            safety.validate("CC", 0.051, 2.0)
        with self.assertRaises(ValueError):
            safety.validate("CV", 5.0, 0.050)
        with self.assertRaises(ValueError):
            safety.validate("CC", 0.010, 5.1)

    def test_readback_and_recipe_io_are_serialized(self) -> None:
        self.assertTrue(self.control.request_readback())
        self.control.acquire_recipe()
        worker = threading.Thread(
            target=lambda: self.control.recipe_output("CC", 0.001, 2.0)
        )
        worker.start()
        worker.join(timeout=1.0)
        self.assertFalse(worker.is_alive())
        self.assertFalse(self.driver.concurrent_io)

    def test_configuration_failure_cleans_up_manual_ownership(self) -> None:
        self.driver.fail_configure = True
        self.control.request_manual_output("CC", 0.001, 2.0)
        self.wait_until(lambda: self.control.ownership is SMUOwnership.IDLE)
        self.assertFalse(self.driver.output)


class SMUManagerDisconnectTests(unittest.TestCase):
    def test_unknown_output_readback_rejects_normal_disconnect(self) -> None:
        manager = SMUManager()
        driver = FakeSMU()
        driver.query_returns_unknown = True
        device = SMUDevice("FAKE", supported=True)
        manager._driver = driver
        manager.connected_device = device
        manager.control.bind_driver(driver)
        try:
            self.assertFalse(manager.disconnect(force=False))
            self.assertTrue(manager.is_connected)
            self.assertIs(driver, manager._driver)
        finally:
            driver.query_returns_unknown = False
            manager.shutdown()


if __name__ == "__main__":
    unittest.main()
