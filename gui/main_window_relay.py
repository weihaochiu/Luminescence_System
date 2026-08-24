from __future__ import annotations

"""Relay-specific main-window coordination, kept outside the general coordinator."""

from PySide6.QtWidgets import QDialog, QMessageBox

from core.i18n import tr

from .relay_controller import RelayError, RelayState
from .relay_settings_dialog import RelaySettingsDialog


class MainWindowRelayMixin:
    def open_relay_settings(self) -> None:
        dialog = RelaySettingsDialog(self.relay_settings_store, self.relay_service, self)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            self._update_white_light_control()

    def refresh_relay_connection(self) -> None:
        self._update_white_light_control(self.relay_service.refresh_connection())
        self._update_measurement_controls()

    def toggle_white_light(self) -> None:
        try:
            group = self.relay_settings_store.settings.group("white_light")
            state = self.relay_service.group_state("white_light")
            if state is RelayState.ON:
                self.relay_service.group_off("white_light", "main_window")
            else:
                self.relay_service.group_on("white_light", "main_window")
        except RelayError as exc:
            self.report_error(
                "REL-203",
                context={"operation": "toggle_white_light", "actual": str(exc)},
                exception=exc,
            )
        self._update_white_light_control()

    def _update_white_light_control(self, connection_message: str | None = None) -> None:
        if not hasattr(self, "white_light_button"):
            return
        group = self.relay_settings_store.settings.group("white_light")
        state = self.relay_service.group_state("white_light")
        is_on = state is RelayState.ON
        connected = self.relay_controller.connected
        measurement_locked = getattr(self, "_measurement_worker", None) is not None
        self.white_light_button.setEnabled(
            connected and group is not None and group.enabled and not measurement_locked
        )
        self.white_light_button.setText(tr("relay.white_light_off") if is_on else tr("relay.white_light_on"))
        state_text = {
            RelayState.ON: tr("common.on"),
            RelayState.OFF: tr("common.off"),
            RelayState.PARTIAL: tr("relay.partial_state"),
            RelayState.ERROR: tr("relay.error_state"),
            RelayState.UNKNOWN: tr("common.unknown") if connected else tr("common.not_connected"),
        }[state]
        self.white_light_status.setText(tr("relay.white_light_status", state=state_text))
        self.white_light_status.setStyleSheet(
            "color:#16823b; font-weight:600;" if connected else "color:#b3261e; font-weight:600;"
        )
        if connection_message:
            self.status_message.setText(connection_message)


def attach_relay_handlers(window_type: type) -> None:
    """Install relay handlers without changing MainWindow's stable mixin contract."""
    for name in ("open_relay_settings", "refresh_relay_connection", "toggle_white_light", "_update_white_light_control"):
        setattr(window_type, name, getattr(MainWindowRelayMixin, name))
