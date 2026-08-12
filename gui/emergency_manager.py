from __future__ import annotations

"""Central, idempotent emergency-stop coordination for active application systems."""

from dataclasses import dataclass
from datetime import datetime
import logging
from threading import Event, RLock
from typing import Callable

from PySide6.QtCore import QObject, Signal

from .relay_controller import RelayService
from .smu_control import SMUControlManager


LOG = logging.getLogger(__name__)


@dataclass(frozen=True)
class EmergencyReport:
    timestamp: str
    active_workflow: str
    generation: int
    smu_state_before: str
    white_light_state_before: str
    actions: dict[str, bool]
    failures: tuple[str, ...]


class EmergencyManager(QObject):
    """Set the abort latch first, then attempt every safe action independently."""

    triggered = Signal(object)
    completed = Signal(object)

    def __init__(
        self,
        smu_control: SMUControlManager,
        relay_service: RelayService,
        parent: QObject | None = None,
    ) -> None:
        super().__init__(parent)
        self.smu_control = smu_control
        self.relay_service = relay_service
        self._active = Event()
        self._lock = RLock()
        self._generation = 0
        self._abort_actions: dict[str, Callable[[], None]] = {}

    @property
    def is_active(self) -> bool:
        return self._active.is_set()

    @property
    def generation(self) -> int:
        with self._lock:
            return self._generation

    def register_abort_action(self, name: str, action: Callable[[], None]) -> None:
        with self._lock:
            self._abort_actions[str(name)] = action

    def begin_operator_operation(self) -> int:
        """Create a fresh token only when the operator explicitly starts again."""

        with self._lock:
            self._generation += 1
            generation = self._generation
            self._active.clear()
        LOG.info("EMERGENCY reset by explicit operator operation generation=%d", generation)
        return generation

    def token_is_current(self, generation: int) -> bool:
        with self._lock:
            return generation == self._generation and not self._active.is_set()

    def trigger(self, active_workflow: str = "idle") -> EmergencyReport:
        timestamp = datetime.now().astimezone().isoformat(timespec="milliseconds")
        with self._lock:
            self._generation += 1
            generation = self._generation
            self._active.set()
            abort_actions = tuple(self._abort_actions.items())

        smu_state_before = (
            "ON" if self.smu_control.output_enabled else "OFF/UNKNOWN"
        )
        try:
            white_light_state_before = self.relay_service.group_state("white_light").value
        except Exception as exc:  # noqa: BLE001 - logging must not block shutdown
            white_light_state_before = f"UNKNOWN ({exc})"

        LOG.critical(
            "GLOBAL_EMERGENCY timestamp=%s workflow=%s generation=%d smu_before=%s white_light_before=%s",
            timestamp,
            active_workflow,
            generation,
            smu_state_before,
            white_light_state_before,
        )
        self.triggered.emit(generation)

        actions: dict[str, bool] = {}
        failures: list[str] = []

        # The SMU latch must be set before any callback that may block (for
        # example, closing a camera SDK session). This invalidates a Manual
        # polarity worker before it can reach its final OUTPUT ON command.
        try:
            actions["SMU OUTPUT OFF"] = bool(self.smu_control.request_emergency_off())
            if not actions["SMU OUTPUT OFF"]:
                failures.append("SMU OUTPUT OFF: request was not accepted")
        except Exception as exc:  # noqa: BLE001 - other devices still need shutdown
            actions["SMU OUTPUT OFF"] = False
            failures.append(f"SMU OUTPUT OFF: {exc}")
            LOG.exception("GLOBAL_EMERGENCY SMU shutdown request failed")

        # White Light OFF is attempted before callbacks because camera SDK close
        # or a worker callback may block. Optical power must not wait for them.
        try:
            actions["White Light OFF"] = bool(
                self.relay_service.safe_white_light_off("global_emergency")
            )
            if not actions["White Light OFF"] and self.relay_service.controller.connected:
                failures.append("White Light OFF: could not verify OFF")
        except Exception as exc:  # noqa: BLE001 - callbacks still need cancellation
            actions["White Light OFF"] = False
            failures.append(f"White Light OFF: {exc}")
            LOG.exception("GLOBAL_EMERGENCY White Light shutdown failed")

        # Routing relays are an independent safety action so White Light or SMU
        # failures cannot prevent Ch1-Ch4 from being disconnected.
        try:
            actions["SMU routing Relays OFF"] = bool(
                self.relay_service.safe_smu_output_channels_off("global_emergency")
            )
            if actions["SMU routing Relays OFF"]:
                mark_verified = getattr(
                    self.smu_control,
                    "mark_external_routing_off_verified",
                    None,
                )
                if callable(mark_verified):
                    mark_verified()
            if (
                not actions["SMU routing Relays OFF"]
                and self.relay_service.controller.connected
            ):
                failures.append("SMU routing Relays OFF: could not verify OFF")
        except Exception as exc:  # noqa: BLE001 - callbacks still need cancellation
            actions["SMU routing Relays OFF"] = False
            failures.append(f"SMU routing Relays OFF: {exc}")
            LOG.exception("GLOBAL_EMERGENCY SMU routing shutdown failed")

        for name, action in abort_actions:
            try:
                action()
                actions[name] = True
                LOG.info("GLOBAL_EMERGENCY action=%s success", name)
            except Exception as exc:  # noqa: BLE001 - continue every safety action
                actions[name] = False
                failures.append(f"{name}: {exc}")
                LOG.exception("GLOBAL_EMERGENCY action=%s failed", name)

        report = EmergencyReport(
            timestamp=timestamp,
            active_workflow=active_workflow,
            generation=generation,
            smu_state_before=smu_state_before,
            white_light_state_before=white_light_state_before,
            actions=actions,
            failures=tuple(failures),
        )
        LOG.critical(
            "GLOBAL_EMERGENCY completed generation=%d actions=%s failures=%s final_smu=%s",
            generation,
            actions,
            failures,
            "ON" if self.smu_control.output_enabled else "OFF/PENDING_CONFIRMATION",
        )
        self.completed.emit(report)
        return report
