from __future__ import annotations

import threading
import time
import unittest

from PySide6.QtCore import Qt

from gui.smu_control import (
    PolarityState,
    SMUControlManager,
    SMUOperationState,
    SMUOwnership,
)


class SequenceSMU:
    def __init__(self, events: list[object]) -> None:
        self.events = events
        self.output = False
        self.jsc_current_a = -0.002
        self.voc_v = 0.8
        self.fail_configuration = False
        self.measure_current_entered: threading.Event | None = None
        self.release_measure_current: threading.Event | None = None

    def configure_voltage_source(self, volts: float, compliance: float) -> None:
        if self.fail_configuration:
            raise RuntimeError("configuration failure")
        self.events.append(("CV", volts, compliance))

    def configure_current_source(self, amps: float, compliance: float) -> None:
        if self.fail_configuration:
            raise RuntimeError("configuration failure")
        self.events.append(("CC", amps, compliance))

    def set_output_enabled(self, enabled: bool) -> None:
        self.output = enabled
        self.events.append(("OUTPUT", enabled))

    def query_output_enabled(self) -> bool:
        self.events.append(("QUERY_OUTPUT", self.output))
        return self.output

    def measure_current(self) -> float:
        self.events.append("MEASURE_JSC")
        if self.measure_current_entered is not None:
            self.measure_current_entered.set()
        if self.release_measure_current is not None:
            self.release_measure_current.wait(2.0)
        return self.jsc_current_a

    def measure_voltage(self) -> float:
        self.events.append("MEASURE_VOC")
        return self.voc_v

    def query_compliance_tripped(self, _mode: str) -> bool:
        return False

    def safe_stop(self) -> list[str]:
        self.output = False
        self.events.append(("SAFE_STOP", False))
        return []


class ManualSMUSequenceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.events: list[object] = []
        self.driver = SequenceSMU(self.events)
        self.control = SMUControlManager()
        self.control.bind_driver(self.driver, output_confirmed_off=True)

    def tearDown(self) -> None:
        self.control.shutdown()

    def wait_until(self, predicate, timeout: float = 2.0) -> None:
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if predicate():
                return
            time.sleep(0.005)
        self.fail("condition did not become true")

    def request(self, *, stabilization_s: float = 0.0) -> bool:
        return self.control.request_manual_output_sequence(
            "CC",
            0.006,
            2.0,
            2.0,
            lambda: self.events.append("LIGHT_ON"),
            lambda: self.events.append("LIGHT_OFF"),
            stabilization_s=stabilization_s,
        )

    def test_current_density_sequence_measures_polarity_before_output(self) -> None:
        results = []
        self.control.manual_polarity_changed.connect(
            results.append,
            Qt.ConnectionType.DirectConnection,
        )
        self.assertTrue(self.request())
        self.wait_until(
            lambda: self.control.operation_state is SMUOperationState.OUTPUT_ON
            and not self.control.is_busy
        )

        self.assertTrue(self.driver.output)
        self.assertEqual(PolarityState.NORMAL, results[-1].state)
        self.assertEqual(1, results[-1].factor)
        self.assertLess(self.events.index("LIGHT_ON"), self.events.index("MEASURE_JSC"))
        self.assertLess(self.events.index("MEASURE_JSC"), self.events.index("MEASURE_VOC"))
        self.assertLess(self.events.index("MEASURE_VOC"), self.events.index("LIGHT_OFF"))
        final_cc = [event for event in self.events if isinstance(event, tuple) and event[0] == "CC"][-1]
        self.assertAlmostEqual(0.006, final_cc[1])
        self.assertEqual(("OUTPUT", True), self.events[-2])

    def test_output_off_then_on_rechecks_and_remaps_reversed_sample(self) -> None:
        self.assertTrue(self.request())
        self.wait_until(lambda: self.control.output_enabled and not self.control.is_busy)
        self.assertTrue(self.control.request_manual_off())
        self.wait_until(
            lambda: self.control.ownership is SMUOwnership.IDLE
            and not self.control.is_busy
        )
        self.assertEqual(PolarityState.UNKNOWN, self.control.manual_polarity.state)
        first_jsc_count = self.events.count("MEASURE_JSC")

        self.driver.jsc_current_a = 0.002
        self.driver.voc_v = -0.8
        self.assertTrue(self.request())
        self.wait_until(lambda: self.control.output_enabled and not self.control.is_busy)

        self.assertEqual(first_jsc_count + 1, self.events.count("MEASURE_JSC"))
        self.assertEqual(PolarityState.REVERSED, self.control.manual_polarity.state)
        final_cc = [event for event in self.events if isinstance(event, tuple) and event[0] == "CC"][-1]
        self.assertAlmostEqual(-0.006, final_cc[1])

    def test_failed_polarity_never_leaves_output_on(self) -> None:
        self.driver.jsc_current_a = 0.002
        self.driver.voc_v = 0.8
        errors: list[str] = []
        self.control.error_occurred.connect(
            errors.append,
            Qt.ConnectionType.DirectConnection,
        )
        self.assertTrue(self.request())
        self.wait_until(
            lambda: self.control.ownership is SMUOwnership.IDLE
            and not self.control.is_busy
        )
        self.assertFalse(self.driver.output)
        self.assertEqual(PolarityState.FAILED, self.control.manual_polarity.state)
        self.assertTrue(any("polarity" in message.lower() for message in errors))

    def test_white_light_failure_never_enables_output(self) -> None:
        def fail_light() -> None:
            raise RuntimeError("relay failed")

        self.assertTrue(
            self.control.request_manual_output_sequence(
                "CV",
                1.0,
                0.010,
                1.0,
                fail_light,
                lambda: self.events.append("LIGHT_OFF"),
                stabilization_s=0.0,
            )
        )
        self.wait_until(
            lambda: self.control.ownership is SMUOwnership.IDLE
            and not self.control.is_busy
        )
        self.assertFalse(self.driver.output)
        self.assertNotIn("MEASURE_JSC", self.events)

    def test_smu_communication_failure_never_claims_output_on(self) -> None:
        self.driver.fail_configuration = True
        self.assertTrue(self.request())
        self.wait_until(
            lambda: self.control.ownership is SMUOwnership.IDLE
            and not self.control.is_busy
        )
        self.assertFalse(self.driver.output)
        self.assertNotEqual(SMUOperationState.OUTPUT_ON, self.control.operation_state)

    def test_emergency_during_polarity_invalidates_late_worker_result(self) -> None:
        entered = threading.Event()
        release = threading.Event()
        self.driver.measure_current_entered = entered
        self.driver.release_measure_current = release
        self.assertTrue(self.request())
        self.assertTrue(entered.wait(1.0))

        self.assertTrue(self.control.request_emergency_off())
        release.set()
        self.wait_until(
            lambda: self.control.ownership is SMUOwnership.IDLE
            and not self.control.is_busy,
            timeout=3.0,
        )

        self.assertFalse(self.driver.output)
        self.assertNotEqual(SMUOperationState.OUTPUT_ON, self.control.operation_state)
        final_nonzero = [
            event
            for event in self.events
            if isinstance(event, tuple)
            and event[0] in ("CC", "CV")
            and abs(event[1]) > 0.0
        ]
        self.assertEqual([], final_nonzero)


if __name__ == "__main__":
    unittest.main()
