"""Main-window integration for the application-owned optical controller."""
from pathlib import Path

from PySide6.QtCore import QStandardPaths, QTimer

from core.i18n import tr
from .light_panel import LightSettingsDialog
from .light_service import LightService
from .smu_control import SMUOperationState, SMUOwnership


def initialize_light(self, application_directory: Path) -> None:
    legacy = Path(QStandardPaths.writableLocation(QStandardPaths.StandardLocation.GenericConfigLocation))
    self.light_service = LightService(
        application_directory / "light_brightness.json", self.settings, self,
        legacy_path=legacy / "Luminescence_GSP4H" / "brightness.json")
    self._light_settings_dialog = None
    self.light_service.failed.connect(self._on_light_error)
    self.light_service.fault.connect(self._on_light_fault)
    self.instrument_state_manager.state_changed.connect(self._sync_light_policy)
    self.emergency_manager.triggered.connect(lambda _generation: self.light_service.set_locked("emergency", True))
    self.emergency_manager.light_service = self.light_service


def open_light_settings(self) -> None:
    if self._light_settings_dialog is None:
        self._light_settings_dialog = LightSettingsDialog(self.light_service, self)
        self._light_settings_dialog.destroyed.connect(lambda: setattr(self, "_light_settings_dialog", None))
    self._light_settings_dialog.show()
    self._light_settings_dialog.raise_()
    self._light_settings_dialog.activateWindow()


def _sync_light_policy(self, *_args) -> None:
    control = self.smu_manager.control
    self.light_service.set_locked("manual", control.ownership is SMUOwnership.MANUAL
                                  and control.operation_state in (SMUOperationState.BUSY,
                                                                  SMUOperationState.SHUTTING_DOWN))
    self.light_service.set_locked("emergency", self.emergency_manager.is_active
                                  or control.ownership in (SMUOwnership.FAULT, SMUOwnership.EMERGENCY))


def _on_light_error(self, code: str, detail: str) -> None:
    self.report_error(code, context={"operation": "gsp4h_control", "resource": self.light_service.state.port,
                                     "actual": detail}, present=False)
    self.status_message.setText(tr("light.operation_failed", detail=detail))


def _on_light_fault(self) -> None:
    control = self.smu_manager.control
    if (getattr(self, "_measurement_hardware_active", False)
            or control.operation_state is SMUOperationState.BUSY) and not self.emergency_manager.is_active:
        # Queue to avoid re-entering a verification wait from its own completion.
        QTimer.singleShot(0, lambda: self.emergency_manager.trigger("GSP4H light state unknown"))


def _prepare_light_for_measurement(self, reason: str) -> bool:
    emergency = getattr(self, "emergency_manager", None)
    generation = emergency.generation if emergency is not None else None
    self.light_service.set_locked(reason, True)
    if self.light_service.verify_dark():
        if emergency is not None and emergency.generation != generation and emergency.is_active:
            self.light_service.set_locked(reason, False)
            return False
        return True
    self.light_service.set_locked(reason, False)
    self._on_light_error("COMM-203", tr("light.dark_unconfirmed"))
    return False


def attach_light_handlers(cls: type) -> None:
    for function in (initialize_light, open_light_settings, _sync_light_policy,
                     _on_light_error, _on_light_fault, _prepare_light_for_measurement):
        setattr(cls, function.__name__, function)
