from __future__ import annotations

import unittest
from types import SimpleNamespace
from unittest.mock import Mock

from gui.main_window import MainWindow


class FakeCloseEvent:
    def __init__(self) -> None:
        self.accepted = False
        self.ignore_calls = 0

    def accept(self) -> None:
        self.accepted = True

    def ignore(self) -> None:
        self.ignore_calls += 1
        self.accepted = False


def close_fixture(confirmations: list[bool]) -> tuple[SimpleNamespace, list[str]]:
    events: list[str] = []

    class Manager:
        is_connected = True

        def confirm_safe_for_close(self) -> bool:
            events.append("SMU_CONFIRM_OFF")
            return confirmations.pop(0)

        def shutdown(self, **kwargs) -> bool:
            events.append(f"SMU_SHUTDOWN:{kwargs}")
            return True

    fixture = SimpleNamespace(
        _close_in_progress=False,
        manual_smu_panel=SimpleNamespace(
            flush_persistent_settings=lambda: events.append("SETTINGS_FLUSH")
        ),
        setEnabled=lambda enabled: events.append(f"GUI_ENABLED:{enabled}"),
        _cancel_measurement_for_emergency=lambda: events.append("STOP_WORKERS"),
        smu_monitor=SimpleNamespace(
            stop=lambda: events.append("MONITOR_STOP"),
            start=lambda: events.append("MONITOR_START"),
        ),
        smu_manager=Manager(),
        relay_service=SimpleNamespace(
            shutdown=lambda: events.append("RELAY_SHUTDOWN")
        ),
        controller=SimpleNamespace(
            close_camera=lambda: events.append("CAMERA_CLOSE")
        ),
        emergency_manager=SimpleNamespace(
            trigger=lambda reason: events.append(f"EMERGENCY:{reason}")
        ),
    )
    fixture._cancel_close_after_safety_failure = (
        lambda event: MainWindow._cancel_close_after_safety_failure(fixture, event)
    )
    return fixture, events


class CloseSafetyTests(unittest.TestCase):
    def test_confirmed_off_closes_in_safe_order(self) -> None:
        window, events = close_fixture([True])
        window._unsafe_smu_close_decision = Mock(return_value="cancel")
        window._confirm_forced_close = Mock(return_value=False)
        event = FakeCloseEvent()

        MainWindow.closeEvent(window, event)

        self.assertTrue(event.accepted)
        self.assertLess(events.index("SETTINGS_FLUSH"), events.index("GUI_ENABLED:False"))
        self.assertLess(events.index("SETTINGS_FLUSH"), events.index("SMU_CONFIRM_OFF"))
        self.assertLess(events.index("MONITOR_STOP"), events.index("SMU_CONFIRM_OFF"))
        self.assertLess(events.index("SMU_CONFIRM_OFF"), events.index("RELAY_SHUTDOWN"))
        self.assertLess(events.index("RELAY_SHUTDOWN"), events.index("SMU_SHUTDOWN:{'safety_confirmed': True}"))
        self.assertLess(events.index("SMU_SHUTDOWN:{'safety_confirmed': True}"), events.index("CAMERA_CLOSE"))
        window._unsafe_smu_close_decision.assert_not_called()

    def test_unknown_output_cancel_keeps_gui_running(self) -> None:
        window, events = close_fixture([False])
        window._unsafe_smu_close_decision = Mock(return_value="cancel")
        window._confirm_forced_close = Mock(return_value=False)
        event = FakeCloseEvent()

        MainWindow.closeEvent(window, event)

        self.assertFalse(event.accepted)
        self.assertFalse(window._close_in_progress)
        self.assertIn("GUI_ENABLED:True", events)
        self.assertIn("MONITOR_START", events)
        self.assertNotIn("RELAY_SHUTDOWN", events)
        self.assertEqual(1, events.count("SETTINGS_FLUSH"))

    def test_retry_safe_stop_then_closes(self) -> None:
        window, events = close_fixture([False, True])
        window._unsafe_smu_close_decision = Mock(return_value="retry")
        window._confirm_forced_close = Mock(return_value=False)
        event = FakeCloseEvent()

        MainWindow.closeEvent(window, event)

        self.assertTrue(event.accepted)
        self.assertEqual(2, events.count("SMU_CONFIRM_OFF"))
        self.assertIn("RELAY_SHUTDOWN", events)
        self.assertEqual(1, events.count("SETTINGS_FLUSH"))

    def test_force_exit_requires_second_confirmation_and_logs_critical(self) -> None:
        window, events = close_fixture([False])
        window._unsafe_smu_close_decision = Mock(return_value="force")
        window._confirm_forced_close = Mock(return_value=True)
        event = FakeCloseEvent()

        with self.assertLogs("gui.main_window_close", level="CRITICAL") as captured:
            MainWindow.closeEvent(window, event)

        self.assertTrue(event.accepted)
        self.assertEqual(1, events.count("SETTINGS_FLUSH"))
        window._confirm_forced_close.assert_called_once()
        self.assertIn("EMERGENCY:forced application exit", events)
        self.assertIn("SMU_SHUTDOWN:{'force': True}", events)
        self.assertTrue(
            any(
                "FORCED_APPLICATION_EXIT_WITH_UNCONFIRMED_SMU_OUTPUT" in message
                for message in captured.output
            )
        )

    def test_reject_second_force_confirmation_cancels_close(self) -> None:
        window, events = close_fixture([False])
        window._unsafe_smu_close_decision = Mock(return_value="force")
        window._confirm_forced_close = Mock(return_value=False)
        event = FakeCloseEvent()

        MainWindow.closeEvent(window, event)

        self.assertFalse(event.accepted)
        self.assertNotIn("SMU_SHUTDOWN:{'force': True}", events)
        self.assertEqual(1, events.count("SETTINGS_FLUSH"))

    def test_settings_flush_failure_does_not_block_fail_closed_shutdown(self) -> None:
        window, events = close_fixture([True])

        def fail_flush() -> None:
            events.append("SETTINGS_FLUSH")
            raise RuntimeError("settings backend unavailable")

        window.manual_smu_panel.flush_persistent_settings = fail_flush
        window._unsafe_smu_close_decision = Mock(return_value="cancel")
        window._confirm_forced_close = Mock(return_value=False)
        event = FakeCloseEvent()

        with self.assertLogs("gui.main_window_close", level="ERROR") as captured:
            MainWindow.closeEvent(window, event)

        self.assertTrue(event.accepted)
        self.assertLess(events.index("SETTINGS_FLUSH"), events.index("SMU_CONFIRM_OFF"))
        self.assertLess(events.index("SMU_CONFIRM_OFF"), events.index("RELAY_SHUTDOWN"))
        self.assertIn("SMU_SHUTDOWN:{'safety_confirmed': True}", events)
        self.assertIn("CAMERA_CLOSE", events)
        self.assertTrue(
            any("Manual SMU settings flush failed" in message for message in captured.output)
        )


if __name__ == "__main__":
    unittest.main()
