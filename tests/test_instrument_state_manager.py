from __future__ import annotations

import unittest

from core.i18n import Language, configure_i18n, set_language
from gui.instrument_state_manager import InstrumentStateManager, SMUInstrumentState
from gui.smu_control import SMUControlManager, SMUOperationState, SMUOwnership


class InstrumentStateManagerTests(unittest.TestCase):
    def setUp(self) -> None:
        configure_i18n(None)
        self.control = SMUControlManager()
        self.manager = InstrumentStateManager(self.control)

    def tearDown(self) -> None:
        self.control.shutdown()
        configure_i18n(None)

    def test_connection_reaches_ready_manual_and_enables_panel(self) -> None:
        self.manager.set_connecting("B2901BL")
        self.assertEqual(SMUInstrumentState.CONNECTING, self.manager.current.state)
        self.assertFalse(self.manager.current.manual_editable)

        self.manager.set_connected("Keysight B2901BL", supported=True)
        self.manager.update_output_confirmation(True)
        state = self.manager.current
        self.assertEqual(SMUInstrumentState.READY_MANUAL, state.state)
        self.assertTrue(state.manual_editable)
        self.assertTrue(state.emergency_enabled)
        self.assertIn("OUTPUT OFF", state.status_text)

    def test_busy_and_recipe_states_lock_manual_without_camera_state(self) -> None:
        self.manager.set_connected("Keysight B2901BL", supported=True)
        self.manager.update_output_confirmation(True)
        self.manager.update_operation_state(SMUOperationState.BUSY.value)
        self.assertEqual(SMUInstrumentState.TRANSITIONING, self.manager.current.state)
        self.assertFalse(self.manager.current.manual_editable)

        self.manager.update_ownership(SMUOwnership.RECIPE.value)
        self.manager.update_operation_state(SMUOperationState.RECIPE_LOCKED.value)
        self.assertEqual(SMUInstrumentState.AUTO_RUNNING, self.manager.current.state)
        self.assertFalse(self.manager.current.manual_editable)

        self.manager.update_ownership(SMUOwnership.IDLE.value)
        self.manager.update_operation_state(SMUOperationState.READY.value)
        self.assertTrue(self.manager.current.manual_editable)

    def test_manual_output_and_emergency_policy(self) -> None:
        self.manager.set_connected("Keysight B2901BL", supported=True)
        self.manager.update_output_confirmation(True)
        self.manager.update_ownership(SMUOwnership.MANUAL.value)
        self.manager.update_output(True)
        self.manager.update_operation_state(SMUOperationState.OUTPUT_ON.value)
        self.assertEqual(SMUInstrumentState.MANUAL_OUTPUT_ON, self.manager.current.state)
        self.assertFalse(self.manager.current.manual_editable)
        self.assertTrue(self.manager.current.manual_off_enabled)

        self.manager.update_operation_state(SMUOperationState.SHUTTING_DOWN.value)
        self.assertEqual(SMUInstrumentState.TRANSITIONING, self.manager.current.state)

        self.manager.update_ownership(SMUOwnership.EMERGENCY.value)
        self.manager.update_operation_state(SMUOperationState.EMERGENCY.value)
        self.assertEqual(SMUInstrumentState.EMERGENCY_STOP, self.manager.current.state)
        self.assertTrue(self.manager.current.emergency_enabled)

    def test_fault_and_disconnect_fail_closed(self) -> None:
        self.manager.set_connected("Keysight B2901BL", supported=True)
        self.manager.update_output_confirmation(True)
        self.manager.update_operation_state(SMUOperationState.FAULT.value)
        self.assertEqual(SMUInstrumentState.ERROR, self.manager.current.state)
        self.assertFalse(self.manager.current.manual_editable)

        self.manager.set_disconnected()
        self.assertEqual(SMUInstrumentState.DISCONNECTED, self.manager.current.state)
        self.assertFalse(self.manager.current.emergency_enabled)

    def test_idle_ready_output_on_is_unexpected_and_recovery_only(self) -> None:
        self.manager.set_connected("Keysight B2901BL", supported=True)
        self.manager.update_output_confirmation(True)
        self.manager.update_output(True)
        state = self.manager.current
        self.assertEqual(SMUInstrumentState.UNEXPECTED_OUTPUT_ON, state.state)
        self.assertFalse(state.manual_editable)
        self.assertTrue(state.manual_off_enabled)
        self.assertTrue(state.emergency_enabled)

    def test_ready_manual_requires_confirmed_output_off(self) -> None:
        self.manager.set_connected("Keysight B2901BL", supported=True)
        state = self.manager.current
        self.assertEqual(SMUInstrumentState.OUTPUT_UNKNOWN, state.state)
        self.assertFalse(state.manual_editable)
        self.assertTrue(state.manual_off_enabled)
        self.assertEqual("UNKNOWN", state.output_state.value)
        self.assertIn("無法確認", state.manual_lock_reason)

    def test_user_visible_snapshot_rebuilds_when_language_changes(self) -> None:
        self.assertEqual("SMU 未連線", self.manager.current.status_text)
        set_language(Language.EN_US, persist=False)
        self.assertEqual("SMU Disconnected", self.manager.current.status_text)
        self.assertIn("supported SMU", self.manager.current.manual_lock_reason)
        set_language(Language.ZH_TW, persist=False)
        self.assertEqual("SMU 未連線", self.manager.current.status_text)


if __name__ == "__main__":
    unittest.main()
