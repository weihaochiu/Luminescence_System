from __future__ import annotations

import threading
import time
import unittest

from gui.smu_base import SMUDevice, SMUDriver
from gui.smu_control import (
    PolarityService,
    SMUControlManager,
    SMUInterlockError,
    SMUOwnership,
    SMUSafetyService,
)


class FakeSMU(SMUDriver):
    def __init__(self) -> None:
        super().__init__(object(), SMUDevice("FAKE", supported=True))
        self.commands: list[tuple] = []
        self.output = False
        self.voltage = 0.0
        self.current = 0.0
        self.fail_configure = False
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
            if self.fail_configure:
                raise RuntimeError("configure failed")
            self.voltage = volts
            self.commands.append(("CV", volts, current_compliance_a))
        finally:
            self._leave()

    def configure_current_source(self, amps: float, voltage_compliance_v: float) -> None:
        self._enter()
        try:
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
            self.output = False
            self.commands.extend([("VOLT", 0.0), ("CURR", 0.0), ("OUTPUT", False)])
            return []
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

    def query_output_enabled(self) -> bool:
        return self.output

    def query_compliance_tripped(self, mode: str) -> bool:
        return False


class SMUControlTests(unittest.TestCase):
    def setUp(self) -> None:
        self.driver = FakeSMU()
        self.control = SMUControlManager()
        self.control.bind_driver(self.driver)

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
        self.assertTrue(self.control.request_manual_off())
        self.wait_until(lambda: self.control.ownership is SMUOwnership.IDLE)
        self.assertFalse(self.driver.output)

    def test_manual_cv_on_off_returns_to_idle(self) -> None:
        self.assertTrue(self.control.request_manual_output("CV", 1.2, 0.020))
        self.wait_until(lambda: self.control.output_enabled)
        self.assertIn(("CV", 1.2, 0.020), self.driver.commands)
        self.assertTrue(self.control.request_manual_off())
        self.wait_until(lambda: self.control.ownership is SMUOwnership.IDLE)

    def test_polarity_translation_is_shared_and_idempotent(self) -> None:
        polarity = PolarityService()
        polarity.set_confirmed_factor(-1)
        polarity.set_confirmed_factor(-1)
        self.assertEqual(-1, polarity.factor)
        self.assertEqual(-0.010, polarity.to_physical(0.010))
        self.control.set_confirmed_polarity_factor(-1)
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


if __name__ == "__main__":
    unittest.main()
