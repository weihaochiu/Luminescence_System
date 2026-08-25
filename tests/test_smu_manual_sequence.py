from __future__ import annotations

import threading
import time
import unittest

from PySide6.QtCore import Qt

from gui.smu_base import SMUDevice
from gui.smu_control import (
    PolarityState,
    SMUControlManager,
    SMUErrorKind,
    SMUInterlockError,
    SMUOperationState,
    SMUOwnership,
)
from gui.polarity_settings import PolarityMeasurementSettings


class SequenceSMU:
    def __init__(self, events: list[object]) -> None:
        self.device = SMUDevice(
            "USB0::SEQUENCE::INSTR",
            manufacturer="Keysight Technologies",
            model="B2901B",
            serial_number="SEQUENCE-SERIAL",
            idn="Keysight Technologies,B2901B,SEQUENCE-SERIAL,1.0",
            supported=True,
        )
        self.events = events
        self.output = False
        self.jsc_current_a = -0.002
        self.voc_v = 0.8
        self.jsc_samples: list[float] = []
        self.voc_samples: list[float] = []
        self.fail_measurement = False
        self.unconfirm_after_temporary_on = False
        self.output_on_attempts = 0
        self.fail_configuration = False
        self.query_returns_unknown = False
        self.measure_current_entered: threading.Event | None = None
        self.release_measure_current: threading.Event | None = None
        self.measure_voltage_entered: threading.Event | None = None
        self.release_measure_voltage: threading.Event | None = None

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
        if enabled:
            self.output_on_attempts += 1
        self.events.append(("OUTPUT", enabled))

    def query_output_enabled(self) -> bool | None:
        self.events.append(("QUERY_OUTPUT", self.output))
        if self.query_returns_unknown:
            return None
        if (
            self.unconfirm_after_temporary_on
            and not self.output
            and self.output_on_attempts >= 1
        ):
            return None
        return self.output

    def measure_current(self) -> float:
        self.events.append("MEASURE_JSC")
        if self.fail_measurement:
            raise RuntimeError("VI_ERROR_TMO during current measurement")
        if self.measure_current_entered is not None:
            self.measure_current_entered.set()
        if self.release_measure_current is not None:
            self.release_measure_current.wait(2.0)
        return self.jsc_samples.pop(0) if self.jsc_samples else self.jsc_current_a

    def measure_voltage(self) -> float:
        self.events.append("MEASURE_VOC")
        if self.measure_voltage_entered is not None:
            self.measure_voltage_entered.set()
        if self.release_measure_voltage is not None:
            self.release_measure_voltage.wait(2.0)
        return self.voc_samples.pop(0) if self.voc_samples else self.voc_v

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
        self.active_channel: str | None = None
        self.fail_clear = False
        self.routing = {"Ch1": 5, "Ch2": 6, "Ch3": 7, "Ch4": 8}

    def tearDown(self) -> None:
        self.control.shutdown()

    def wait_until(self, predicate, timeout: float = 2.0) -> None:
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if predicate():
                return
            time.sleep(0.005)
        self.fail("condition did not become true")

    def select_channel(self, channel_id: str, check_cancel) -> int:
        check_cancel()
        for relay in range(5, 9):
            self.events.append(("RELAY", relay, False))
        check_cancel()
        relay = self.routing[channel_id]
        self.events.append(("RELAY", relay, True))
        self.active_channel = channel_id
        check_cancel()
        return relay

    def verify_channel(self, channel_id: str) -> int | None:
        return self.routing[channel_id] if self.active_channel == channel_id else None

    def clear_channels(self) -> None:
        if self.fail_clear:
            raise RuntimeError("routing clear failed")
        for relay in range(5, 9):
            self.events.append(("RELAY", relay, False))
        self.active_channel = None

    def request(
        self,
        *,
        channel_id: str = "Ch1",
        stabilization_s: float = 0.0,
        settings: PolarityMeasurementSettings | None = None,
    ) -> bool:
        settings = settings or PolarityMeasurementSettings(
            white_light_stabilization_ms=round(stabilization_s * 1000),
            anti_flicker_enabled=False,
            jsc_settle_ms=0,
            jsc_sample_count=1,
            jsc_minimum_valid_ma_cm2=0.001,
            jsc_compliance_ma_cm2=20.0,
            voc_settle_ms=0,
            voc_sample_count=1,
            voc_minimum_valid_v=0.001,
        )
        return self.control.request_manual_output_sequence(
            channel_id,
            "CC",
            0.006,
            2.0,
            2.0,
            self.select_channel,
            self.verify_channel,
            self.clear_channels,
            lambda: self.events.append("LIGHT_ON"),
            lambda: self.events.append("LIGHT_OFF"),
            settings,
        )

    @staticmethod
    def sampling_settings() -> PolarityMeasurementSettings:
        return PolarityMeasurementSettings(
            white_light_stabilization_ms=0,
            anti_flicker_enabled=False,
            integration_nplc=5.0,
            mains_frequency_hz=60.0,
            jsc_settle_ms=0,
            jsc_sample_count=5,
            jsc_aggregation="median",
            jsc_minimum_valid_ma_cm2=0.001,
            jsc_max_variation_percent=30.0,
            jsc_compliance_ma_cm2=20.0,
            voc_settle_ms=0,
            voc_sample_count=5,
            voc_aggregation="median",
            voc_minimum_valid_v=0.001,
            voc_max_variation_percent=30.0,
            voc_compliance_v=2.0,
        )

    def capture_error_events(self) -> list[object]:
        events: list[object] = []
        self.control.error_event.connect(
            events.append,
            Qt.ConnectionType.DirectConnection,
        )
        return events

    def wait_for_abort(self) -> None:
        self.wait_until(
            lambda: self.control.ownership in {SMUOwnership.IDLE, SMUOwnership.FAULT}
            and not self.control.is_busy
        )

    def test_polarity_compliance_must_fit_smu_safety_limits(self) -> None:
        settings = PolarityMeasurementSettings(
            white_light_stabilization_ms=0,
            jsc_compliance_ma_cm2=50.0,
        )
        with self.assertRaisesRegex(ValueError, "Jsc current compliance"):
            self.control.request_manual_output_sequence(
                "Ch1",
                "CC",
                0.006,
                2.0,
                2.0,
                self.select_channel,
                self.verify_channel,
                self.clear_channels,
                lambda: None,
                lambda: None,
                settings,
            )
        self.assertFalse(self.events)

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
        final_light_off = max(
            index for index, event in enumerate(self.events) if event == "LIGHT_OFF"
        )
        self.assertLess(self.events.index("MEASURE_VOC"), final_light_off)
        self.assertLess(self.events.index("LIGHT_OFF"), self.events.index(("RELAY", 5, False)))
        self.assertLess(self.events.index(("RELAY", 5, True)), self.events.index("LIGHT_ON"))
        final_cc = [event for event in self.events if isinstance(event, tuple) and event[0] == "CC"][-1]
        self.assertAlmostEqual(0.006, final_cc[1])
        self.assertIn(("OUTPUT", True), self.events)
        self.assertEqual("Ch1", self.control.manual_routing_snapshot["active_channel_verified"])

    def test_output_off_then_on_rechecks_and_remaps_reversed_sample(self) -> None:
        self.assertTrue(self.request(channel_id="Ch1"))
        self.wait_until(lambda: self.control.output_enabled and not self.control.is_busy)
        self.assertTrue(self.control.request_manual_off())
        self.wait_until(
            lambda: self.control.ownership is SMUOwnership.IDLE
            and not self.control.is_busy
        )
        self.assertEqual(PolarityState.UNKNOWN, self.control.manual_polarity.state)
        self.assertIsNone(self.active_channel)
        first_jsc_count = self.events.count("MEASURE_JSC")

        self.driver.jsc_current_a = 0.002
        self.driver.voc_v = -0.8
        self.assertTrue(self.request(channel_id="Ch2"))
        self.wait_until(lambda: self.control.output_enabled and not self.control.is_busy)

        self.assertEqual(first_jsc_count + 1, self.events.count("MEASURE_JSC"))
        self.assertEqual(PolarityState.REVERSED, self.control.manual_polarity.state)
        self.assertEqual("Ch2", self.active_channel)
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
        self.assertEqual(PolarityState.INVALID, self.control.manual_polarity.state)
        self.assertTrue(any("polarity" in message.lower() for message in errors))

    def test_jsc_variation_is_measurement_error_with_diagnostics_and_safe_cleanup(self) -> None:
        self.driver.jsc_samples = [-0.0010, -0.0020, -0.0011, -0.0019, -0.0012]
        error_events = self.capture_error_events()

        self.assertTrue(self.request(settings=self.sampling_settings()))
        self.wait_for_abort()

        kinds = [event.kind for event in error_events]
        self.assertIn(SMUErrorKind.POLARITY_MEASUREMENT_FAILED, kinds)
        self.assertNotIn(SMUErrorKind.OPERATION_FAILED, kinds)
        event = next(
            event
            for event in error_events
            if event.kind is SMUErrorKind.POLARITY_MEASUREMENT_FAILED
        )
        self.assertEqual("Jsc", event.context["measurement_type"])
        self.assertEqual(5, event.context["sample_count"])
        self.assertEqual(30.0, event.context["configured_maximum_variation_percent"])
        self.assertGreater(event.context["variation_percent"], 30.0)
        self.assertEqual(5, len(event.context["raw_samples"]))
        self.assertEqual("OFF (confirmed)", event.context["white_light_final_state"])
        self.assertEqual("OFF (confirmed)", event.context["routing_final_state"])
        self.assertEqual("OFF (confirmed)", event.context["output_state_after_abort"])
        self.assertEqual(1, self.events.count(("OUTPUT", True)))
        self.assertFalse(self.driver.output)
        self.assertIsNone(self.active_channel)
        self.assertFalse(self.control.fault_latched)

    def test_voc_variation_is_measurement_error_and_never_reaches_formal_output(self) -> None:
        self.driver.jsc_samples = [-0.002] * 5
        self.driver.voc_samples = [0.2, 0.8, 0.3, 0.9, 0.4]
        error_events = self.capture_error_events()

        self.assertTrue(self.request(settings=self.sampling_settings()))
        self.wait_for_abort()

        event = next(
            event
            for event in error_events
            if event.kind is SMUErrorKind.POLARITY_MEASUREMENT_FAILED
        )
        self.assertEqual("Voc", event.context["measurement_type"])
        self.assertGreater(event.context["variation_percent"], 30.0)
        self.assertEqual(2, self.events.count(("OUTPUT", True)))
        self.assertFalse(self.driver.output)

    def test_inconsistent_jsc_sign_is_measurement_error(self) -> None:
        self.driver.jsc_samples = [-0.002, -0.002, 0.002, -0.002, -0.002]
        error_events = self.capture_error_events()

        self.assertTrue(self.request(settings=self.sampling_settings()))
        self.wait_for_abort()

        event = next(
            event
            for event in error_events
            if event.kind is SMUErrorKind.POLARITY_MEASUREMENT_FAILED
        )
        self.assertEqual("Jsc", event.context["measurement_type"])
        self.assertEqual("polarity.error.inconsistent_sign", event.user_message_key)
        self.assertNotIn(SMUErrorKind.OPERATION_FAILED, [item.kind for item in error_events])

    def test_invalid_jsc_voc_combination_is_measurement_error(self) -> None:
        self.driver.jsc_samples = [0.002] * 5
        self.driver.voc_samples = [0.8] * 5
        error_events = self.capture_error_events()

        self.assertTrue(self.request(settings=self.sampling_settings()))
        self.wait_for_abort()

        event = next(
            event
            for event in error_events
            if event.kind is SMUErrorKind.POLARITY_MEASUREMENT_FAILED
        )
        self.assertEqual("polarity.error.invalid_polarity", event.user_message_key)
        self.assertEqual(2, self.events.count(("OUTPUT", True)))
        self.assertFalse(self.driver.output)

    def test_visa_failure_remains_smu_operation_error(self) -> None:
        self.driver.fail_measurement = True
        error_events = self.capture_error_events()

        self.assertTrue(self.request(settings=self.sampling_settings()))
        self.wait_for_abort()

        kinds = [event.kind for event in error_events]
        self.assertIn(SMUErrorKind.OPERATION_FAILED, kinds)
        self.assertNotIn(SMUErrorKind.POLARITY_MEASUREMENT_FAILED, kinds)
        self.assertFalse(self.driver.output)

    def test_temporary_output_off_unconfirmed_remains_critical_smu_error(self) -> None:
        self.driver.unconfirm_after_temporary_on = True
        error_events = self.capture_error_events()

        self.assertTrue(self.request(settings=self.sampling_settings()))
        self.wait_for_abort()

        kinds = [event.kind for event in error_events]
        self.assertIn(SMUErrorKind.OUTPUT_OFF_UNCONFIRMED, kinds)
        self.assertNotIn(SMUErrorKind.POLARITY_MEASUREMENT_FAILED, kinds)
        self.assertIs(self.control.ownership, SMUOwnership.FAULT)
        self.assertFalse(self.control.output_confirmed_off)

    def test_white_light_failure_never_enables_output(self) -> None:
        def fail_light() -> None:
            raise RuntimeError("relay failed")

        self.assertTrue(
            self.control.request_manual_output_sequence(
                "Ch1",
                "CV",
                1.0,
                0.010,
                1.0,
                self.select_channel,
                self.verify_channel,
                self.clear_channels,
                fail_light,
                lambda: self.events.append("LIGHT_OFF"),
                PolarityMeasurementSettings(
                    white_light_stabilization_ms=0,
                    anti_flicker_enabled=False,
                    jsc_settle_ms=0,
                    jsc_sample_count=1,
                    voc_settle_ms=0,
                    voc_sample_count=1,
                ),
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

    def test_ch4_route_precedes_light_and_formal_output(self) -> None:
        self.assertTrue(self.request(channel_id="Ch4"))
        self.wait_until(lambda: self.control.output_enabled and not self.control.is_busy)
        self.assertLess(self.events.index(("RELAY", 8, True)), self.events.index("LIGHT_ON"))
        final_output_on = max(
            index for index, event in enumerate(self.events) if event == ("OUTPUT", True)
        )
        final_light_off = max(
            index for index, event in enumerate(self.events) if event == "LIGHT_OFF"
        )
        self.assertLess(final_light_off, final_output_on)
        self.assertEqual("Ch4", self.active_channel)

    def test_manual_stop_confirms_smu_off_before_clearing_relays(self) -> None:
        self.assertTrue(self.request(channel_id="Ch3"))
        self.wait_until(lambda: self.control.output_enabled and not self.control.is_busy)
        stop_start = len(self.events)
        self.assertTrue(self.control.request_manual_off())
        self.wait_until(lambda: self.control.ownership is SMUOwnership.IDLE and not self.control.is_busy)
        stopped = self.events[stop_start:]
        self.assertLess(stopped.index(("SAFE_STOP", False)), stopped.index(("RELAY", 5, False)))
        self.assertLess(
            stopped.index(("QUERY_OUTPUT", False)),
            stopped.index(("RELAY", 5, False)),
        )
        self.assertTrue(self.control.output_confirmed_off)
        self.assertIsNone(self.active_channel)
        self.assertIsNone(self.control.manual_routing_snapshot["active_channel_verified"])

    def test_routing_clear_failure_latches_fault_but_reports_smu_off(self) -> None:
        self.assertTrue(self.request(channel_id="Ch1"))
        self.wait_until(lambda: self.control.output_enabled and not self.control.is_busy)
        self.fail_clear = True
        self.assertTrue(self.control.request_manual_off())
        self.wait_until(lambda: not self.control.is_busy)
        self.assertFalse(self.driver.output)
        self.assertFalse(self.control.output_enabled)
        self.assertTrue(self.control.output_confirmed_off)
        self.assertIs(self.control.ownership, SMUOwnership.FAULT)
        self.fail_clear = False

    def test_unconfirmed_output_off_latches_fault_and_preserves_routing(self) -> None:
        self.assertTrue(self.request(channel_id="Ch1"))
        self.wait_until(lambda: self.control.output_enabled and not self.control.is_busy)
        stop_start = len(self.events)
        self.driver.query_returns_unknown = True
        try:
            self.assertTrue(self.control.request_manual_off())
            self.wait_until(
                lambda: self.control.ownership is SMUOwnership.FAULT
                and not self.control.is_busy
            )
        finally:
            self.driver.query_returns_unknown = False

        stopped = self.events[stop_start:]
        self.assertIn(("SAFE_STOP", False), stopped)
        self.assertNotIn(("RELAY", 5, False), stopped)
        self.assertEqual("Ch1", self.active_channel)
        self.assertFalse(self.control.output_confirmed_off)
        self.assertIs(self.control.operation_state, SMUOperationState.FAULT)

    def test_same_channel_after_stop_still_rechecks_polarity(self) -> None:
        self.assertTrue(self.request(channel_id="Ch1"))
        self.wait_until(lambda: self.control.output_enabled and not self.control.is_busy)
        first_count = self.events.count("MEASURE_JSC")
        self.assertTrue(self.control.request_manual_off())
        self.wait_until(lambda: self.control.ownership is SMUOwnership.IDLE and not self.control.is_busy)
        self.assertTrue(self.request(channel_id="Ch1"))
        self.wait_until(lambda: self.control.output_enabled and not self.control.is_busy)
        self.assertEqual(first_count + 1, self.events.count("MEASURE_JSC"))

    def test_live_readback_routing_mismatch_latches_fault_and_forces_smu_off(self) -> None:
        self.assertTrue(self.request(channel_id="Ch1"))
        self.wait_until(lambda: self.control.output_enabled and not self.control.is_busy)
        self.active_channel = None
        self.assertTrue(self.control.request_readback())
        self.wait_until(lambda: self.control.ownership is SMUOwnership.FAULT and not self.control.is_busy)
        self.assertFalse(self.driver.output)
        self.assertIsNone(self.control.manual_routing_snapshot["active_channel_verified"])
        self.assertTrue(self.control.fault_latched)
        with self.assertRaises(SMUInterlockError):
            self.request(channel_id="Ch2")
        self.assertFalse(self.control.request_readback())
        self.assertIs(self.control.ownership, SMUOwnership.FAULT)
        self.assertIs(self.control.operation_state, SMUOperationState.FAULT)

    def test_external_routing_fault_latches_fault_after_safe_shutdown(self) -> None:
        self.assertTrue(self.request(channel_id="Ch3"))
        self.wait_until(lambda: self.control.output_enabled and not self.control.is_busy)
        self.assertTrue(self.control.request_external_interlock("multiple routing relays"))
        self.wait_until(lambda: not self.control.is_busy)
        self.assertFalse(self.driver.output)
        self.assertIs(self.control.ownership, SMUOwnership.FAULT)
        self.assertIs(self.control.operation_state, SMUOperationState.FAULT)
        self.assertIsNone(self.active_channel)

    def test_authoritative_smu_on_blocks_relay_switch(self) -> None:
        self.driver.output = True
        self.assertTrue(self.request(channel_id="Ch2"))
        self.wait_until(lambda: self.control.ownership is SMUOwnership.IDLE and not self.control.is_busy)
        self.assertNotIn(("RELAY", 6, True), self.events)
        self.assertNotIn("LIGHT_ON", self.events)
        self.assertFalse(self.driver.output)

    def test_emergency_during_relay_switch_prevents_target_and_light(self) -> None:
        entered = threading.Event()
        release = threading.Event()

        def blocked_select(channel_id: str, check_cancel) -> int:
            for relay in range(5, 9):
                self.events.append(("RELAY", relay, False))
            entered.set()
            release.wait(2.0)
            check_cancel()
            relay = self.routing[channel_id]
            self.events.append(("RELAY", relay, True))
            return relay

        original = self.select_channel
        self.select_channel = blocked_select
        try:
            self.assertTrue(self.request(channel_id="Ch2"))
            self.assertTrue(entered.wait(1.0))
            self.assertTrue(self.control.request_emergency_off())
            release.set()
            self.wait_until(lambda: self.control.ownership is SMUOwnership.IDLE and not self.control.is_busy, 3.0)
        finally:
            self.select_channel = original
        self.assertNotIn(("RELAY", 6, True), self.events)
        self.assertNotIn("LIGHT_ON", self.events)
        self.assertIsNone(self.active_channel)

    def test_emergency_after_route_on_before_polarity_clears_route(self) -> None:
        light_entered = threading.Event()
        release = threading.Event()

        def blocked_light_on() -> None:
            self.events.append("LIGHT_ON")
            light_entered.set()
            release.wait(2.0)

        settings = PolarityMeasurementSettings(
            white_light_stabilization_ms=0,
            anti_flicker_enabled=False,
            jsc_settle_ms=0,
            jsc_sample_count=1,
            jsc_minimum_valid_ma_cm2=0.001,
            jsc_compliance_ma_cm2=20.0,
            voc_settle_ms=0,
            voc_sample_count=1,
            voc_minimum_valid_v=0.001,
        )
        self.assertTrue(
            self.control.request_manual_output_sequence(
                "Ch2", "CC", 0.006, 2.0, 2.0,
                self.select_channel, self.verify_channel, self.clear_channels,
                blocked_light_on, lambda: self.events.append("LIGHT_OFF"), settings,
            )
        )
        self.assertTrue(light_entered.wait(1.0))
        self.assertTrue(self.control.request_emergency_off())
        release.set()
        self.wait_until(lambda: self.control.ownership is SMUOwnership.IDLE and not self.control.is_busy, 3.0)
        self.assertFalse(self.driver.output)
        self.assertIsNone(self.active_channel)

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
        self.assertIsNone(self.active_channel)
        self.assertNotEqual(SMUOperationState.OUTPUT_ON, self.control.operation_state)
        final_nonzero = [
            event
            for event in self.events
            if isinstance(event, tuple)
            and event[0] in ("CC", "CV")
            and abs(event[1]) > 0.0
        ]
        self.assertEqual([], final_nonzero)

    def test_emergency_during_voc_sampling_never_reaches_formal_output(self) -> None:
        entered = threading.Event()
        release = threading.Event()
        self.driver.measure_voltage_entered = entered
        self.driver.release_measure_voltage = release
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
        self.assertIsNone(self.active_channel)
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
