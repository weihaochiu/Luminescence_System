from __future__ import annotations

"""RisingCam SDK AE target to scientific Effective-DN calibration."""

import json
import math
import os
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path
from time import monotonic
from typing import Any, Iterable

from core.i18n import tr
from uuid import uuid4


# Version 2 makes AE ROI geometry part of profile identity. Version 1 profiles
# were measured against an implicit full image and are intentionally ignored.
CALIBRATION_SCHEMA_VERSION = 2
CALIBRATION_CANDIDATES = (
    24,
    32,
    40,
    48,
    56,
    64,
    80,
    96,
    112,
    128,
    144,
    160,
    176,
    192,
    208,
)
CALIBRATION_TARGET_PERCENTS = (20, 30, 40, 50, 60, 70, 80)
CALIBRATION_POINT_TIMEOUT_SECONDS = 15.0
SATURATION_THRESHOLD_PERCENT = 98.0
LOW_SIGNAL_THRESHOLD_PERCENT = 1.0
MONOTONIC_TOLERANCE_PERCENTAGE_POINTS = 2.0
STABLE_FRAME_COUNT = 3
STABLE_DN_TOLERANCE_PERCENTAGE_POINTS = 1.0


def calibration_candidates(minimum: int, maximum: int) -> tuple[int, ...]:
    """Clamp the documented scan to the camera SDK range and remove duplicates."""

    low, high = int(minimum), int(maximum)
    if low > high:
        raise ValueError("SDK AE target minimum must not exceed maximum")
    return tuple(dict.fromkeys(min(max(value, low), high) for value in CALIBRATION_CANDIDATES))


@dataclass(frozen=True)
class AECalibrationIdentity:
    camera_model: str
    camera_serial: str
    width: int
    height: int
    sensor_bit_depth: int
    raw_value_alignment: str
    ae_roi: tuple[int, int, int, int]
    sdk_ae_policy: int = 1
    sdk_autoexposure_percent: int = 100

    @property
    def resolution(self) -> str:
        return f"{self.width}x{self.height}"

    @property
    def key(self) -> str:
        camera = self.camera_serial.strip() or f"model-{self.camera_model.strip()}"
        x, y, width, height = self.ae_roi
        return (
            f"camera/ae_calibration/{camera}/{self.resolution}/"
            f"roi-{x}-{y}-{width}-{height}"
        )

    def matches(self, other: "AECalibrationIdentity") -> bool:
        if self.camera_serial.strip() or other.camera_serial.strip():
            same_camera = bool(
                self.camera_serial.strip()
                and other.camera_serial.strip()
                and self.camera_serial == other.camera_serial
            )
        else:
            same_camera = bool(
                self.camera_model.strip()
                and self.camera_model == other.camera_model
            )
        return bool(
            same_camera
            and self.camera_model == other.camera_model
            and self.width == other.width
            and self.height == other.height
            and self.sensor_bit_depth == other.sensor_bit_depth
            and self.raw_value_alignment == other.raw_value_alignment
            and self.ae_roi == other.ae_roi
            and self.sdk_ae_policy == other.sdk_ae_policy
            and self.sdk_autoexposure_percent == other.sdk_autoexposure_percent
        )


@dataclass(frozen=True)
class AECalibrationPoint:
    sdk_target: int
    sdk_target_readback: int
    mean_effective_dn: float | None
    mean_effective_dn_percent: float | None
    exposure_us: int | None
    gain_percent: int | None
    converged: bool
    saturated: bool = False
    low_signal: bool = False
    convergence_source: str = ""

    @classmethod
    def measured(
        cls,
        *,
        sdk_target: int,
        sdk_target_readback: int,
        mean_effective_dn: float | None,
        mean_effective_dn_percent: float | None,
        exposure_us: int | None,
        gain_percent: int | None,
        converged: bool,
        convergence_source: str,
    ) -> "AECalibrationPoint":
        percent = (
            float(mean_effective_dn_percent)
            if mean_effective_dn_percent is not None
            else None
        )
        return cls(
            sdk_target=int(sdk_target),
            sdk_target_readback=int(sdk_target_readback),
            mean_effective_dn=(
                float(mean_effective_dn) if mean_effective_dn is not None else None
            ),
            mean_effective_dn_percent=percent,
            exposure_us=int(exposure_us) if exposure_us is not None else None,
            gain_percent=int(gain_percent) if gain_percent is not None else None,
            converged=bool(converged),
            saturated=bool(percent is not None and percent >= SATURATION_THRESHOLD_PERCENT),
            low_signal=bool(percent is not None and percent <= LOW_SIGNAL_THRESHOLD_PERCENT),
            convergence_source=str(convergence_source),
        )


@dataclass(frozen=True)
class AECalibrationProfile:
    profile_id: str
    camera_model: str
    camera_serial: str
    resolution: str
    width: int
    height: int
    sensor_bit_depth: int
    raw_value_alignment: str
    ae_roi: tuple[int, int, int, int]
    sdk_ae_policy: int
    sdk_autoexposure_percent: int
    created_at: str
    points: tuple[AECalibrationPoint, ...]
    target_mapping: dict[int, int]
    valid: bool
    invalid_reason: str = ""

    @property
    def identity(self) -> AECalibrationIdentity:
        return AECalibrationIdentity(
            camera_model=self.camera_model,
            camera_serial=self.camera_serial,
            width=self.width,
            height=self.height,
            sensor_bit_depth=self.sensor_bit_depth,
            raw_value_alignment=self.raw_value_alignment,
            ae_roi=self.ae_roi,
            sdk_ae_policy=self.sdk_ae_policy,
            sdk_autoexposure_percent=self.sdk_autoexposure_percent,
        )

    def matches(self, identity: AECalibrationIdentity) -> bool:
        return self.valid and self.identity.matches(identity)

    def calibrated_sdk_target(self, percent: int) -> int | None:
        return self.target_mapping.get(int(percent)) if self.valid else None

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["points"] = [asdict(point) for point in self.points]
        payload["target_mapping"] = {
            str(key): value for key, value in sorted(self.target_mapping.items())
        }
        return payload

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "AECalibrationProfile":
        points = tuple(AECalibrationPoint(**item) for item in payload.get("points", []))
        mapping = {
            int(key): int(value)
            for key, value in dict(payload.get("target_mapping", {})).items()
        }
        return cls(
            profile_id=str(payload["profile_id"]),
            camera_model=str(payload.get("camera_model", "")),
            camera_serial=str(payload.get("camera_serial", "")),
            resolution=str(payload.get("resolution", "")),
            width=int(payload["width"]),
            height=int(payload["height"]),
            sensor_bit_depth=int(payload["sensor_bit_depth"]),
            raw_value_alignment=str(payload["raw_value_alignment"]),
            ae_roi=tuple(int(value) for value in payload["ae_roi"]),
            sdk_ae_policy=int(payload.get("sdk_ae_policy", 1)),
            sdk_autoexposure_percent=int(payload.get("sdk_autoexposure_percent", 100)),
            created_at=str(payload["created_at"]),
            points=points,
            target_mapping=mapping,
            valid=bool(payload.get("valid", False)),
            invalid_reason=str(payload.get("invalid_reason", "")),
        )


def _usable_points(points: Iterable[AECalibrationPoint]) -> list[AECalibrationPoint]:
    return sorted(
        (
            point
            for point in points
            if point.converged
            and not point.saturated
            and not point.low_signal
            and point.mean_effective_dn_percent is not None
        ),
        key=lambda point: point.sdk_target_readback,
    )


def validate_monotonic_points(
    points: Iterable[AECalibrationPoint],
    tolerance: float = MONOTONIC_TOLERANCE_PERCENTAGE_POINTS,
) -> tuple[bool, str]:
    usable = _usable_points(points)
    if len(usable) < 2:
        return False, tr("camera.calibration_points_insufficient")
    previous = float(usable[0].mean_effective_dn_percent)
    for point in usable[1:]:
        current = float(point.mean_effective_dn_percent)
        if current < previous - float(tolerance):
            return (
                False,
                tr("camera.calibration_mapping_failed"),
            )
        previous = max(previous, current)
    return True, ""


def interpolate_sdk_target(
    points: Iterable[AECalibrationPoint],
    desired_percent: float,
    sdk_minimum: int,
    sdk_maximum: int,
) -> int:
    """Invert a monotonic SDK-target curve using piecewise-linear interpolation."""

    valid, reason = validate_monotonic_points(points)
    if not valid:
        raise ValueError(reason)
    normalized: list[tuple[float, int]] = []
    running_percent = -math.inf
    for point in _usable_points(points):
        measured = max(running_percent, float(point.mean_effective_dn_percent))
        running_percent = measured
        if normalized and math.isclose(measured, normalized[-1][0], abs_tol=1e-9):
            normalized[-1] = (measured, point.sdk_target_readback)
        else:
            normalized.append((measured, point.sdk_target_readback))
    desired = float(desired_percent)
    if len(normalized) < 2 or desired < normalized[0][0] or desired > normalized[-1][0]:
        raise ValueError(f"Calibration curve does not bracket {desired:g}% Effective DN")
    for measured, sdk_target in normalized:
        if math.isclose(desired, measured, abs_tol=1e-9):
            return min(max(int(sdk_target), int(sdk_minimum)), int(sdk_maximum))
    for (p1, sdk1), (p2, sdk2) in zip(normalized, normalized[1:]):
        if p1 <= desired <= p2 and p2 > p1:
            interpolated = sdk1 + (desired - p1) * (sdk2 - sdk1) / (p2 - p1)
            rounded = int(math.floor(interpolated + 0.5))
            return min(max(rounded, int(sdk_minimum)), int(sdk_maximum))
    raise ValueError(f"Calibration curve does not bracket {desired:g}% Effective DN")


def build_calibration_profile(
    identity: AECalibrationIdentity,
    points: Iterable[AECalibrationPoint],
    *,
    sdk_minimum: int,
    sdk_maximum: int,
    created_at: str | None = None,
    profile_id: str | None = None,
) -> AECalibrationProfile:
    ordered = tuple(sorted(points, key=lambda point: point.sdk_target))
    valid, reason = validate_monotonic_points(ordered)
    mapping: dict[int, int] = {}
    if valid:
        try:
            mapping = {
                percent: interpolate_sdk_target(
                    ordered, percent, sdk_minimum, sdk_maximum
                )
                for percent in CALIBRATION_TARGET_PERCENTS
            }
        except ValueError as exc:
            valid, reason = False, str(exc)
            mapping = {}
    return AECalibrationProfile(
        profile_id=profile_id or uuid4().hex,
        camera_model=identity.camera_model,
        camera_serial=identity.camera_serial,
        resolution=identity.resolution,
        width=identity.width,
        height=identity.height,
        sensor_bit_depth=identity.sensor_bit_depth,
        raw_value_alignment=identity.raw_value_alignment,
        ae_roi=identity.ae_roi,
        sdk_ae_policy=identity.sdk_ae_policy,
        sdk_autoexposure_percent=identity.sdk_autoexposure_percent,
        created_at=created_at or datetime.now().astimezone().isoformat(timespec="seconds"),
        points=ordered,
        target_mapping=mapping,
        valid=valid,
        invalid_reason=reason,
    )


class AECalibrationProfileStore:
    """Multi-camera JSON profile store with crash-safe replacement."""

    def __init__(self, path: str | Path | None) -> None:
        self.path = Path(path) if path is not None else None
        self._profiles: list[AECalibrationProfile] = []
        self.load()

    @property
    def profiles(self) -> tuple[AECalibrationProfile, ...]:
        return tuple(self._profiles)

    def load(self) -> None:
        self._profiles = []
        if self.path is None or not self.path.exists():
            return
        try:
            payload = json.loads(self.path.read_text(encoding="utf-8"))
            if int(payload.get("schema_version", 0)) != CALIBRATION_SCHEMA_VERSION:
                return
            self._profiles = [
                AECalibrationProfile.from_dict(item)
                for item in payload.get("profiles", [])
            ]
        except (OSError, ValueError, TypeError, KeyError, json.JSONDecodeError):
            self._profiles = []

    def matching(self, identity: AECalibrationIdentity | None) -> AECalibrationProfile | None:
        if identity is None:
            return None
        matches = [profile for profile in self._profiles if profile.matches(identity)]
        return max(matches, key=lambda profile: profile.created_at, default=None)

    def replace(self, profile: AECalibrationProfile) -> None:
        if not profile.valid:
            raise ValueError("Invalid calibration profiles cannot be persisted")
        retained = [
            item for item in self._profiles if not item.identity.matches(profile.identity)
        ]
        retained.append(profile)
        self._save_atomic(retained)
        self._profiles = retained

    def clear(self, identity: AECalibrationIdentity) -> bool:
        retained = [
            profile for profile in self._profiles if not profile.identity.matches(identity)
        ]
        changed = len(retained) != len(self._profiles)
        if changed:
            self._save_atomic(retained)
            self._profiles = retained
        return changed

    def _save_atomic(self, profiles: Iterable[AECalibrationProfile]) -> None:
        if self.path is None:
            self._profiles = list(profiles)
            return
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.path.with_name(self.path.name + ".tmp")
        payload = {
            "schema_version": CALIBRATION_SCHEMA_VERSION,
            "profiles": [profile.to_dict() for profile in profiles],
        }
        try:
            with temporary.open("w", encoding="utf-8", newline="\n") as stream:
                json.dump(payload, stream, ensure_ascii=False, indent=2)
                stream.write("\n")
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary, self.path)
        finally:
            temporary.unlink(missing_ok=True)


@dataclass
class AECalibrationRun:
    """Mutable scan state; SDK operations remain owned by CameraController."""

    identity: AECalibrationIdentity
    candidates: tuple[int, ...]
    sdk_minimum: int
    sdk_maximum: int
    point_timeout_seconds: float = CALIBRATION_POINT_TIMEOUT_SECONDS
    points: list[AECalibrationPoint] = field(default_factory=list)
    index: int = -1
    state: str = "idle"
    current_target: int | None = None
    current_readback: int | None = None
    point_started_monotonic: float = 0.0
    convergence_source: str = ""
    fresh_after_sequence: int = -1
    stable_samples: list[tuple[int, int, float]] = field(default_factory=list)

    def next_candidate(self) -> int | None:
        if len(self.points) >= 2 and all(
            point.converged and point.saturated for point in self.points[-2:]
        ):
            self.state = "complete"
            return None
        self.index += 1
        if self.index >= len(self.candidates):
            self.state = "complete"
            return None
        self.current_target = self.candidates[self.index]
        self.current_readback = None
        self.state = "starting"
        self.stable_samples.clear()
        return self.current_target

    def start_point(self, readback: int) -> None:
        self.current_readback = int(readback)
        self.point_started_monotonic = monotonic()
        self.state = "waiting_convergence"
        self.stable_samples.clear()

    def observe_stability(
        self, exposure_us: int, gain_percent: int, effective_dn_percent: float
    ) -> bool:
        if self.state != "waiting_convergence":
            return False
        self.stable_samples.append(
            (int(exposure_us), int(gain_percent), float(effective_dn_percent))
        )
        self.stable_samples = self.stable_samples[-STABLE_FRAME_COUNT:]
        if len(self.stable_samples) < STABLE_FRAME_COUNT:
            return False
        exposures = {sample[0] for sample in self.stable_samples}
        gains = {sample[1] for sample in self.stable_samples}
        percents = [sample[2] for sample in self.stable_samples]
        return bool(
            len(exposures) == 1
            and len(gains) == 1
            and max(percents) - min(percents)
            < STABLE_DN_TOLERANCE_PERCENTAGE_POINTS
        )

    def mark_converged(self, frame_sequence: int, source: str) -> None:
        self.state = "waiting_fresh_frame"
        self.fresh_after_sequence = int(frame_sequence)
        self.convergence_source = str(source)

    def record_point(
        self,
        *,
        mean_effective_dn: float | None,
        mean_effective_dn_percent: float | None,
        exposure_us: int | None,
        gain_percent: int | None,
        converged: bool,
        convergence_source: str | None = None,
    ) -> AECalibrationPoint:
        if self.current_target is None or self.current_readback is None:
            raise RuntimeError("Calibration point was not started")
        point = AECalibrationPoint.measured(
            sdk_target=self.current_target,
            sdk_target_readback=self.current_readback,
            mean_effective_dn=mean_effective_dn,
            mean_effective_dn_percent=mean_effective_dn_percent,
            exposure_us=exposure_us,
            gain_percent=gain_percent,
            converged=converged,
            convergence_source=convergence_source or self.convergence_source,
        )
        self.points.append(point)
        self.state = "point_complete"
        return point

    def estimated_remaining_seconds(self) -> int:
        remaining = max(0, len(self.candidates) - self.index - 1)
        return round(remaining * self.point_timeout_seconds)

    def build_profile(self) -> AECalibrationProfile:
        return build_calibration_profile(
            self.identity,
            self.points,
            sdk_minimum=self.sdk_minimum,
            sdk_maximum=self.sdk_maximum,
        )
