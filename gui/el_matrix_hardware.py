from __future__ import annotations

"""Adapters from the hardware-neutral EL Matrix runner to verified services."""

from typing import Any, Callable

from .camera_capture_bridge import CameraCaptureBridge
from .el_matrix_runner import CapturedFrame, interruptible_wait
from .recipe_store import ChannelRecipe
from .smu_control import SMUControlManager, SMUOwnership


def relay_channel_id(logical_channel: str) -> str:
    normalized = logical_channel.strip().upper()
    if normalized not in {f"CH{index}" for index in range(1, 5)}:
        raise ValueError(f"Unsupported logical channel: {logical_channel}")
    return "Ch" + normalized[2:]


class ELMatrixHardwareAdapter:
    def __init__(
        self,
        control: SMUControlManager,
        relay_service: Any,
        camera_bridge: CameraCaptureBridge,
        polarity_settings: Any,
        status: Callable[[str], None] = lambda _message: None,
    ) -> None:
        self.control = control
        self.relay = relay_service
        self.camera = camera_bridge
        self.polarity_settings = polarity_settings
        self.status = status

    def prepare_shared_dark(self) -> None:
        self.output_off()
        if not self.relay.safe_white_light_off("el_matrix_shared_dark"):
            raise RuntimeError("White Light OFF could not be verified for Shared Dark")
        self.clear_routing()

    def route_channel(
        self, logical_channel: str, check_cancel: Callable[[], None]
    ) -> None:
        self.relay.select_smu_output_channel(
            relay_channel_id(logical_channel),
            self.control.confirm_output_off_for_routing,
            check_cancel,
            source="el_matrix_channel_switch",
        )

    def run_polarity(
        self, channel: ChannelRecipe, check_cancel: Callable[[], None]
    ) -> dict[str, Any]:
        route_id = relay_channel_id(channel.channel)

        def verified_light_on() -> None:
            self.relay.verify_smu_output_channel_state(route_id, "el_matrix_polarity_pre_light")
            self.relay.group_on("white_light", "el_matrix_polarity")

        def verified_light_off() -> None:
            if not self.relay.safe_white_light_off("el_matrix_polarity"):
                raise RuntimeError("White Light OFF verification failed after polarity")

        payload = self.control.recipe_polarity_measurement(
            self.polarity_settings,
            channel.area_cm2,
            light_on=verified_light_on,
            light_off=verified_light_off,
            check_cancel=check_cancel,
            wait_ms=lambda milliseconds: interruptible_wait(
                milliseconds / 1000.0, check_cancel
            ),
            status=self.status,
        )
        payload["logical_channel"] = channel.channel
        return payload

    def apply_polarity_factor(self, factor: int) -> None:
        self.control.set_recipe_polarity_factor(factor)

    def prepare_channel_dark(self) -> None:
        self.output_off()
        if not self.relay.safe_white_light_off("el_matrix_channel_dark"):
            raise RuntimeError("White Light OFF could not be verified for channel Dark I-V")

    def run_dark_iv(
        self,
        settings: Any,
        check_cancel: Callable[[], None],
    ) -> list[dict[str, Any]]:
        if settings.step_v <= 0:
            raise ValueError("Dark I-V step must be greater than zero")
        ascending: list[float] = []
        value = float(settings.start_v)
        direction = 1.0 if settings.stop_v >= settings.start_v else -1.0
        while (value - settings.stop_v) * direction <= 1e-12:
            ascending.append(value)
            value += direction * float(settings.step_v)
        points = ascending
        if settings.direction == "bidirectional":
            points = ascending + list(reversed(ascending[:-1]))
        rows: list[dict[str, Any]] = []
        for repeat in range(1, max(1, int(settings.repeat_count)) + 1):
            for point_index, voltage in enumerate(points, start=1):
                check_cancel()
                self.control.recipe_output(
                    "CV", float(voltage), float(settings.current_compliance_ma) / 1000.0
                )
                interruptible_wait(float(settings.dwell_s), check_cancel)
                reading = self.control.recipe_readback()
                rows.append({
                    "Repeat": repeat,
                    "PointIndex": point_index,
                    "CommandedVoltageV": float(voltage),
                    "MeasuredVoltageV": reading.voltage_v,
                    "MeasuredCurrentA": reading.current_a,
                    "MeasuredPowerW": reading.power_w,
                    "ComplianceTripped": reading.compliance_tripped,
                })
            if repeat < max(1, int(settings.repeat_count)):
                interruptible_wait(float(settings.inter_scan_delay_s), check_cancel)
        return rows

    def set_current(self, current_a: float, voltage_compliance_v: float) -> float:
        return self.control.recipe_output("CC", current_a, voltage_compliance_v)

    def readback(self) -> Any:
        return self.control.recipe_readback()

    def capture(
        self,
        exposure_ms: float,
        gain_percent: int,
        timeout_s: float,
        check_cancel: Callable[[], None],
    ) -> CapturedFrame:
        return self.camera.capture(
            exposure_ms, gain_percent, timeout_s, check_cancel
        )

    def output_off(self) -> None:
        if self.control.ownership is SMUOwnership.RECIPE:
            self.control.recipe_output_off("EL Matrix transition")

    def clear_routing(self) -> None:
        self.relay.clear_smu_output_channels("el_matrix_channel_switch")
        self.relay.verify_smu_output_channel_state(None, "el_matrix_channel_switch")

    def safe_shutdown(self) -> dict[str, bool]:
        failures: list[str] = []
        smu_output_off = False
        if self.control.ownership is SMUOwnership.RECIPE:
            smu_output_off = bool(self.control.safe_shutdown(
                SMUOwnership.RECIPE, reason="EL Matrix safe shutdown"
            ))
            if not smu_output_off:
                failures.append("SMU OUTPUT OFF could not be authoritatively confirmed")
        else:
            smu_output_off = bool(
                self.control.ownership is SMUOwnership.IDLE
                and self.control.last_shutdown_ok is True
                and self.control.output_confirmed_off
            )
            if not smu_output_off:
                failures.append("SMU OUTPUT OFF/ownership release was not verified")
        routing_off = False
        try:
            routing_off = bool(
                self.relay.safe_smu_output_channels_off("el_matrix_safe_shutdown")
            )
            if not routing_off:
                failures.append("Routing safe OFF could not be verified")
        except Exception as exc:
            failures.append(f"Routing safe OFF failed: {exc}")
        white_light_off = False
        try:
            white_light_off = bool(
                self.relay.safe_white_light_off("el_matrix_safe_shutdown")
            )
            if not white_light_off:
                failures.append("White Light OFF could not be verified")
        except Exception as exc:
            failures.append(f"White Light OFF failed: {exc}")
        ownership_released = self.control.ownership is SMUOwnership.IDLE
        if not ownership_released:
            failures.append("SMU ownership was not safely released")
        if failures:
            reason = "; ".join(failures)
            self.control.request_external_interlock(
                "EL Matrix safe shutdown verification failed: " + reason
            )
            raise RuntimeError(reason)
        return {
            "smu_output_off": smu_output_off,
            "routing_off": routing_off,
            "white_light_off": white_light_off,
            "ownership_released": ownership_released,
            "ok": True,
        }
