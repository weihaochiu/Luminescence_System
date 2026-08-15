from __future__ import annotations

"""Pure Effective-DN software auto-exposure decisions."""

from dataclasses import dataclass
from enum import Enum

from .camera_auto_exposure_settings import target_effective_dn


class SoftwareAutoExposureMode(str, Enum):
    MANUAL = "Manual"
    CONTINUOUS_DN = "ContinuousDN"
    AUTO_ONCE_DN = "AutoOnceDN"


@dataclass(frozen=True)
class SoftwareAutoExposureDecision:
    exposure_us: int
    gain_percent: int
    adjusted: bool
    converged: bool
    target_dn: int


class SoftwareAutoExposure:
    """Exposure-first controller evaluated once per new scientific frame."""

    def __init__(
        self,
        target_percent: int = 50,
        deadband_fraction: float = 0.05,
        required_once_frames: int = 2,
    ) -> None:
        self.target_percent = int(target_percent)
        self.deadband_fraction = float(deadband_fraction)
        self.required_once_frames = int(required_once_frames)
        self.mode = SoftwareAutoExposureMode.MANUAL
        self._consecutive_converged = 0

    def set_target_percent(self, target_percent: int) -> None:
        # target_effective_dn performs the shared option validation.
        target_effective_dn(1, target_percent)
        self.target_percent = int(target_percent)
        self._consecutive_converged = 0

    def start_continuous(self) -> None:
        self.mode = SoftwareAutoExposureMode.CONTINUOUS_DN
        self._consecutive_converged = 0

    def start_once(self) -> None:
        self.mode = SoftwareAutoExposureMode.AUTO_ONCE_DN
        self._consecutive_converged = 0

    def stop(self) -> None:
        self.mode = SoftwareAutoExposureMode.MANUAL
        self._consecutive_converged = 0

    @property
    def is_active(self) -> bool:
        return self.mode is not SoftwareAutoExposureMode.MANUAL

    def update(
        self,
        *,
        mean_dn: float,
        maximum_dn: int,
        exposure_us: int,
        gain_percent: int,
        exposure_range: tuple[int, int, int],
        gain_range: tuple[int, int, int],
    ) -> SoftwareAutoExposureDecision:
        target_dn = target_effective_dn(maximum_dn, self.target_percent)
        current_exposure = int(exposure_us)
        current_gain = int(gain_percent)
        if not self.is_active:
            return SoftwareAutoExposureDecision(
                current_exposure, current_gain, False, False, target_dn
            )

        tolerance = target_dn * self.deadband_fraction
        if abs(float(mean_dn) - target_dn) <= tolerance:
            if self.mode is SoftwareAutoExposureMode.AUTO_ONCE_DN:
                self._consecutive_converged += 1
                converged = self._consecutive_converged >= self.required_once_frames
                if converged:
                    self.stop()
            else:
                converged = False
            return SoftwareAutoExposureDecision(
                current_exposure, current_gain, False, converged, target_dn
            )

        self._consecutive_converged = 0
        exp_min, exp_max, exp_default = (int(value) for value in exposure_range)
        gain_min, gain_max, gain_default = (int(value) for value in gain_range)
        # RisingCam range tuple item 3 is the factory default, not a step.
        # Keep the names explicit so neither value can accidentally influence
        # controller increments.
        _ = exp_default, gain_default
        preferred_gain = min(max(100, gain_min), gain_max)
        ratio = min(max(target_dn / max(float(mean_dn), 1.0), 0.5), 2.0)
        new_exposure = current_exposure
        new_gain = current_gain

        if mean_dn < target_dn:
            if current_exposure < exp_max:
                requested = round(current_exposure * ratio)
                if requested == current_exposure:
                    requested += 1
                new_exposure = min(max(requested, exp_min), exp_max)
            elif current_gain < gain_max:
                requested = round(current_gain * ratio)
                if requested == current_gain:
                    requested += 1
                new_gain = min(max(requested, gain_min), gain_max)
        else:
            if current_gain > preferred_gain:
                requested = round(current_gain * ratio)
                if requested == current_gain:
                    requested -= 1
                new_gain = min(max(requested, preferred_gain), gain_max)
            elif current_exposure > exp_min:
                requested = round(current_exposure * ratio)
                if requested == current_exposure:
                    requested -= 1
                new_exposure = min(max(requested, exp_min), exp_max)

        return SoftwareAutoExposureDecision(
            new_exposure,
            new_gain,
            (new_exposure, new_gain) != (current_exposure, current_gain),
            False,
            target_dn,
        )
