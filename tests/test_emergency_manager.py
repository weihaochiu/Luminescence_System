from __future__ import annotations

import unittest

from gui.emergency_manager import EmergencyManager


class FakeSMUControl:
    def __init__(self) -> None:
        self.output_enabled = True
        self.calls = 0

    def request_emergency_off(self) -> bool:
        self.calls += 1
        self.output_enabled = False
        return True


class FakeState:
    value = "ON"


class FakeRelayController:
    connected = True


class FakeRelayService:
    def __init__(self) -> None:
        self.controller = FakeRelayController()
        self.calls = 0

    def group_state(self, _group_id: str) -> FakeState:
        return FakeState()

    def safe_white_light_off(self, _source: str) -> bool:
        self.calls += 1
        return True


class EmergencyManagerTests(unittest.TestCase):
    def setUp(self) -> None:
        self.smu = FakeSMUControl()
        self.relay = FakeRelayService()
        self.manager = EmergencyManager(self.smu, self.relay)

    def test_every_action_runs_even_when_one_abort_handler_fails(self) -> None:
        calls: list[str] = []

        def fail() -> None:
            calls.append("failed workflow")
            raise RuntimeError("worker failure")

        self.manager.register_abort_action("Recipe abort", fail)
        self.manager.register_abort_action("Camera stop", lambda: calls.append("camera"))
        report = self.manager.trigger("Recipe")

        self.assertTrue(self.manager.is_active)
        self.assertEqual(["failed workflow", "camera"], calls)
        self.assertEqual(1, self.smu.calls)
        self.assertEqual(1, self.relay.calls)
        self.assertFalse(report.actions["Recipe abort"])
        self.assertTrue(report.actions["Camera stop"])
        self.assertTrue(any("worker failure" in failure for failure in report.failures))

    def test_repeated_idle_emergency_is_idempotent_and_never_reenables_output(self) -> None:
        first = self.manager.trigger("idle")
        second = self.manager.trigger("idle")
        self.assertGreater(second.generation, first.generation)
        self.assertFalse(self.smu.output_enabled)
        self.assertEqual(2, self.smu.calls)
        self.assertEqual(2, self.relay.calls)

    def test_smu_abort_latch_is_requested_before_other_callbacks(self) -> None:
        observed: list[int] = []
        self.manager.register_abort_action(
            "slow camera callback",
            lambda: observed.append(self.smu.calls),
        )
        self.manager.trigger("manual polarity")
        self.assertEqual([1], observed)

    def test_explicit_new_operation_uses_new_generation_token(self) -> None:
        stale = self.manager.begin_operator_operation()
        self.assertTrue(self.manager.token_is_current(stale))
        self.manager.trigger("manual polarity")
        self.assertFalse(self.manager.token_is_current(stale))
        fresh = self.manager.begin_operator_operation()
        self.assertTrue(self.manager.token_is_current(fresh))


if __name__ == "__main__":
    unittest.main()
