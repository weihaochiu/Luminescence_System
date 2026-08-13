from __future__ import annotations

"""Adapters from the hardware-neutral EL Matrix runner to verified services."""

from datetime import datetime
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

    def use_default_polarity(self, channel: ChannelRecipe) -> dict[str, Any]:
        # Existing standard wiring is the physical-positive (+1) convention.
        self.control.set_recipe_polarity_factor(1)
        return {
            "polarity_check_status": "SKIPPED",
            "polarity_result": "STANDARD_WIRING",
            "polarity_factor": 1,
            "polarity_timestamp": datetime.now().astimezone().isoformat(timespec="seconds"),
            "Jsc": None,
            "Voc": None,
            "logical_channel": channel.channel,
        }

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

    def safe_shutdown(self) -> None:
        failures: list[str] = []
        if self.control.ownership is SMUOwnership.RECIPE:
            if not self.control.safe_shutdown(
                SMUOwnership.RECIPE, reason="EL Matrix safe shutdown"
            ):
                failures.append("SMU OUTPUT OFF could not be authoritatively confirmed")
        try:
            if not self.relay.safe_smu_output_channels_off("el_matrix_safe_shutdown"):
                failures.append("Routing safe OFF could not be verified")
        except Exception as exc:
            failures.append(f"Routing safe OFF failed: {exc}")
        try:
            if not self.relay.safe_white_light_off("el_matrix_safe_shutdown"):
                failures.append("White Light OFF could not be verified")
        except Exception as exc:
            failures.append(f"White Light OFF failed: {exc}")
        if failures:
            raise RuntimeError("; ".join(failures))
