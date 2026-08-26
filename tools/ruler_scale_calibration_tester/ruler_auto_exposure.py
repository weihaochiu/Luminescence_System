from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime
import logging
from threading import Event
from typing import Any, Callable, Protocol

import numpy as np

from core.calibration.acquisition_quality import (
    RulerAcquisitionMetrics,
    RulerAcquisitionQualityEvaluator,
)
from core.calibration.models import CalibrationResult
from core.i18n import tr

from .capture_history import CaptureHistoryStats, CaptureHistoryStore
from .source import AnalysisSource


LOG = logging.getLogger(__name__)


@dataclass(frozen=True)
class RulerAutoExposureConfig:
    """Provisional targets derived from the first ten real ruler captures."""

    provisional_global_saturation_max: float = 0.07
    provisional_ruler_saturation_max: float = 0.15
    provisional_tick_saturation_max: float = 0.15
    provisional_michelson_min: float = 0.50
    provisional_normalized_contrast_min: float = 0.14
    provisional_metric_relative_delta_max: float = 0.05
    provisional_angle_delta_max_deg: float = 2.0
    provisional_polygon_delta_max_fraction: float = 0.03
    required_consecutive_acceptable_frames: int = 2
    maximum_exposure_adjustments: int = 6
    maximum_candidate_retries: int = 2
    maximum_total_attempts: int = 12
    settling_frames: int = 1
    severe_clipping_multiplier: float = 0.50
    clipping_multiplier: float = 0.70
    weak_signal_multiplier: float = 2.00
    mild_signal_multiplier: float = 1.40
    gain_multiplier: float = 1.25


@dataclass(frozen=True)
class RulerCameraLimits:
    exposure_min_us: int
    exposure_max_us: int
    gain_min: int
    gain_max: int


@dataclass(frozen=True)
class AcquiredRulerFrame:
    raw: np.ndarray
    metadata: dict[str, object]
    frame_sequence: int | None = None
    captured_at: str = ""


class RulerCameraAdapter(Protocol):
    def snapshot_state(self) -> dict[str, object]: ...
    def limits(self) -> RulerCameraLimits: ...
    def capture(
        self,
        exposure_us: int,
        gain: int,
        settling_frames: int,
        check_cancel: Callable[[], None],
    ) -> AcquiredRulerFrame: ...
    def restore_state(self, state: dict[str, object]) -> None: ...


@dataclass(frozen=True)
class RulerAEDecision:
    action: str
    reason: str
    requested_exposure_us: int
    requested_gain: int
    acceptable: bool = False


@dataclass
class RulerAEAttemptRecord:
    attempt_index: int
    requested_exposure_us: int
    actual_exposure_us: int | None
    requested_gain: int
    actual_gain: int | None
    global_saturation_fraction: float | None
    ruler_roi_saturation_fraction: float | None
    tick_band_saturation_fraction: float | None
    normalized_tick_contrast: float | None
    michelson_tick_contrast: float | None
    accepted_tick_count: int
    periodicity_support: float
    hierarchy_verified: bool
    ruler_candidate_confidence: float
    ruler_candidate_reliable: bool
    ruler_candidate_reasons: list[str]
    polygon: list[list[float]]
    angle_deg: float | None
    decision: str
    decision_reason: str
    next_requested_exposure_us: int
    next_requested_gain: int
    capture_id: str = ""

    def to_dict(self) -> dict[str, object]:
        payload = asdict(self)
        payload["periodic_support"] = self.periodicity_support
        return payload


@dataclass
class RulerAutoExposureOutcome:
    success: bool
    reason: str
    result: CalibrationResult
    attempts: list[RulerAEAttemptRecord] = field(default_factory=list)
    history_stats: CaptureHistoryStats | None = None


class RulerAECancelled(RuntimeError):
    pass


class RulerAutoExposureDecisionEngine:
    def __init__(self, config: RulerAutoExposureConfig | None = None) -> None:
        self.config = config or RulerAutoExposureConfig()

    def decide(
        self,
        metrics: RulerAcquisitionMetrics,
        exposure_us: int,
        gain: int,
        limits: RulerCameraLimits,
        *,
        candidate_retry_count: int,
        exposure_adjustment_count: int,
    ) -> RulerAEDecision:
        config = self.config
        if not metrics.candidate.reliable:
            action = (
                "retry_candidate"
                if candidate_retry_count < config.maximum_candidate_retries
                else "fail"
            )
            return RulerAEDecision(
                action,
                "ruler_candidate_unreliable:" + ",".join(metrics.candidate.reasons),
                exposure_us,
                gain,
            )
        ruler_sat = metrics.ruler_roi_saturation_fraction
        tick_sat = metrics.tick_band_saturation_fraction
        if ruler_sat is None or tick_sat is None:
            return RulerAEDecision("fail", "ruler_quality_metrics_unavailable", exposure_us, gain)
        local_clipping = max(ruler_sat, tick_sat)
        if local_clipping > max(
            config.provisional_ruler_saturation_max,
            config.provisional_tick_saturation_max,
        ):
            if exposure_adjustment_count >= config.maximum_exposure_adjustments:
                return RulerAEDecision("fail", "maximum_exposure_adjustments_reached", exposure_us, gain)
            multiplier = (
                config.severe_clipping_multiplier
                if local_clipping >= 0.50
                else config.clipping_multiplier
            )
            requested = max(limits.exposure_min_us, int(round(exposure_us * multiplier)))
            if requested >= exposure_us:
                return RulerAEDecision("fail", "clipping_at_minimum_exposure", exposure_us, gain)
            return RulerAEDecision("reduce_exposure", "ruler_or_tick_band_clipping", requested, gain)

        michelson = metrics.michelson_tick_contrast
        normalized = metrics.normalized_tick_contrast
        weak_contrast = (
            michelson is None
            or normalized is None
            or michelson < config.provisional_michelson_min
            or normalized < config.provisional_normalized_contrast_min
        )
        if weak_contrast:
            if exposure_us < limits.exposure_max_us:
                if exposure_adjustment_count >= config.maximum_exposure_adjustments:
                    return RulerAEDecision("fail", "maximum_exposure_adjustments_reached", exposure_us, gain)
                multiplier = (
                    config.weak_signal_multiplier
                    if michelson is None or michelson < config.provisional_michelson_min * 0.5
                    else config.mild_signal_multiplier
                )
                requested = min(limits.exposure_max_us, int(round(exposure_us * multiplier)))
                if requested > exposure_us:
                    return RulerAEDecision("increase_exposure", "low_tick_contrast", requested, gain)
            if gain < limits.gain_max and local_clipping <= 0.02:
                if exposure_adjustment_count >= config.maximum_exposure_adjustments:
                    return RulerAEDecision(
                        "fail",
                        "maximum_exposure_adjustments_reached",
                        exposure_us,
                        gain,
                    )
                requested_gain = min(
                    limits.gain_max,
                    max(gain + 1, int(round(gain * config.gain_multiplier))),
                )
                return RulerAEDecision("increase_gain", "exposure_max_low_signal", exposure_us, requested_gain)
            return RulerAEDecision("fail", "low_tick_contrast_at_camera_limit", exposure_us, gain)

        if not metrics.hierarchy_verified:
            return RulerAEDecision("fail", "tick_hierarchy_not_verified", exposure_us, gain)
        return RulerAEDecision("hold_for_stability", "quality_targets_met", exposure_us, gain, True)

    def stable(
        self,
        previous: RulerAcquisitionMetrics,
        current: RulerAcquisitionMetrics,
    ) -> bool:
        config = self.config
        for before, after in (
            (previous.ruler_roi_saturation_fraction, current.ruler_roi_saturation_fraction),
            (previous.tick_band_saturation_fraction, current.tick_band_saturation_fraction),
            (previous.normalized_tick_contrast, current.normalized_tick_contrast),
            (previous.michelson_tick_contrast, current.michelson_tick_contrast),
            (previous.periodicity_support, current.periodicity_support),
        ):
            if before is None or after is None:
                return False
            denominator = max(abs(before), abs(after), 1e-6)
            if abs(after - before) / denominator > config.provisional_metric_relative_delta_max:
                return False
        before_angle = previous.candidate.angle_deg
        after_angle = current.candidate.angle_deg
        if before_angle is None or after_angle is None:
            return False
        angle_delta = abs((after_angle - before_angle + 90.0) % 180.0 - 90.0)
        if angle_delta > config.provisional_angle_delta_max_deg:
            return False
        return self._polygon_stable(previous.candidate.polygon, current.candidate.polygon)

    def _polygon_stable(
        self,
        previous: tuple[tuple[float, float], ...],
        current: tuple[tuple[float, float], ...],
    ) -> bool:
        if len(previous) != 4 or len(current) != 4:
            return False
        before = np.asarray(previous, dtype=np.float64)
        after = np.asarray(current, dtype=np.float64)
        diagonal = max(float(np.linalg.norm(np.ptp(before, axis=0))), 1.0)
        best = min(
            float(np.mean(np.linalg.norm(np.roll(after, shift, axis=0) - before, axis=1)))
            for shift in range(4)
        )
        return best / diagonal <= self.config.provisional_polygon_delta_max_fraction


class RulerAutoExposureRunner:
    """Acquisition-layer state machine. Physical calibration remains in CalibrationService."""

    def __init__(
        self,
        service: Any,
        history: CaptureHistoryStore,
        evaluator: RulerAcquisitionQualityEvaluator | None = None,
        engine: RulerAutoExposureDecisionEngine | None = None,
    ) -> None:
        self.service = service
        self.history = history
        self.evaluator = evaluator or RulerAcquisitionQualityEvaluator()
        self.engine = engine or RulerAutoExposureDecisionEngine()

    def run(
        self,
        camera: RulerCameraAdapter,
        device_name: str,
        cancel_event: Event | None = None,
        attempt_callback: Callable[[RulerAEAttemptRecord], None] | None = None,
    ) -> RulerAutoExposureOutcome:
        cancel = cancel_event or Event()
        original_state = camera.snapshot_state()
        limits = camera.limits()
        exposure = int(original_state.get("ExposureReadbackUs") or limits.exposure_min_us)
        exposure = min(max(exposure, limits.exposure_min_us), limits.exposure_max_us)
        gain = limits.gain_min
        attempts: list[RulerAEAttemptRecord] = []
        candidate_retries = 0
        adjustments = 0
        acceptable_count = 0
        previous_acceptable: RulerAcquisitionMetrics | None = None
        last_result = CalibrationResult(success=False, failure_reasons=["ruler_ae_not_started"])

        def check_cancel() -> None:
            if cancel.is_set():
                raise RulerAECancelled("ruler_auto_exposure_cancelled")

        try:
            while True:
                check_cancel()
                capture_requested_exposure = exposure
                capture_requested_gain = gain
                acquired = camera.capture(
                    capture_requested_exposure,
                    capture_requested_gain,
                    self.engine.config.settling_frames,
                    check_cancel,
                )
                metadata = dict(acquired.metadata)
                actual_exposure = metadata.get("ExposureReadbackUs")
                actual_gain = metadata.get("GainReadback")
                if actual_exposure is not None:
                    exposure = int(actual_exposure)
                if actual_gain is not None:
                    gain = int(actual_gain)
                timestamp = acquired.captured_at or datetime.now().astimezone().isoformat(timespec="milliseconds")
                source = AnalysisSource(
                    source_type="camera",
                    source_identity=f"camera|{device_name}|frame={acquired.frame_sequence}|captured={timestamp}",
                    frame_sequence=acquired.frame_sequence,
                    display_name=tr(
                        "calibration.tester.camera_frame_source",
                        device=device_name,
                        sequence=acquired.frame_sequence,
                    ),
                    capture_timestamp=timestamp,
                    acquisition_metadata=metadata,
                )
                pending = self.history.begin_capture(acquired.raw, source)
                metrics: RulerAcquisitionMetrics | None = None
                try:
                    last_result = self.service.analyze(
                        acquired.raw,
                        input_source=source.display_name,
                        source_type="camera",
                        source_identity=source.source_identity,
                        source_display_name=source.display_name,
                        captured_frame_sequence=source.frame_sequence,
                    )
                    if not isinstance(last_result, CalibrationResult):
                        raise TypeError("Calibration service returned an invalid result")
                except Exception as exc:
                    LOG.exception("[RULER_AE] calibration analysis failed")
                    last_result = CalibrationResult(
                        success=False,
                        source_type="camera",
                        source_identity=source.source_identity,
                        source_display_name=source.display_name,
                        captured_frame_sequence=source.frame_sequence,
                        timestamp=datetime.now().astimezone().isoformat(timespec="seconds"),
                        input_dtype=str(acquired.raw.dtype),
                        input_resolution=(acquired.raw.shape[1], acquired.raw.shape[0]),
                        input_min=int(acquired.raw.min()),
                        input_max=int(acquired.raw.max()),
                        failure_reasons=["analysis_exception"],
                        warnings=[f"{type(exc).__name__}: {exc}"],
                    )
                    decision = RulerAEDecision(
                        "fail", "analysis_exception", exposure, gain
                    )
                else:
                    effective_dn_max = metadata.get("EffectiveDNMax")
                    alignment = str(metadata.get("RawValueAlignment") or "unknown")
                    if effective_dn_max is None:
                        decision = RulerAEDecision(
                            "fail", "effective_dn_metadata_unavailable", exposure, gain
                        )
                    elif alignment.lower() not in {"right", "left"}:
                        decision = RulerAEDecision(
                            "fail", "raw_value_alignment_unverified", exposure, gain
                        )
                    else:
                        try:
                            metrics = self.evaluator.evaluate(
                                acquired.raw,
                                last_result,
                                int(effective_dn_max),
                                alignment,
                            )
                        except Exception as exc:
                            LOG.exception("[RULER_AE] acquisition quality evaluation failed")
                            last_result.warnings.append(f"{type(exc).__name__}: {exc}")
                            decision = RulerAEDecision(
                                "fail", "quality_evaluation_exception", exposure, gain
                            )
                        else:
                            decision = self.engine.decide(
                                metrics,
                                exposure,
                                gain,
                                limits,
                                candidate_retry_count=candidate_retries,
                                exposure_adjustment_count=adjustments,
                            )
                if metrics is not None:
                    if decision.acceptable:
                        stable = previous_acceptable is not None and self.engine.stable(previous_acceptable, metrics)
                        acceptable_count = acceptable_count + 1 if stable else 1
                        previous_acceptable = metrics
                        if acceptable_count >= self.engine.config.required_consecutive_acceptable_frames:
                            decision = RulerAEDecision("accept", "stable_quality_targets_met", exposure, gain, True)
                    else:
                        acceptable_count = 0
                        previous_acceptable = None
                if (
                    len(attempts) + 1 >= self.engine.config.maximum_total_attempts
                    and decision.action not in {"accept", "fail"}
                ):
                    decision = RulerAEDecision(
                        "fail",
                        "maximum_total_attempts_reached",
                        exposure,
                        gain,
                    )
                if metrics is None:
                    record = RulerAEAttemptRecord(
                        len(attempts) + 1, capture_requested_exposure, int(actual_exposure) if actual_exposure is not None else None,
                        capture_requested_gain, int(actual_gain) if actual_gain is not None else None,
                        None, None, None, None, None, 0, 0.0, False, 0.0, False,
                        ["quality_metrics_unavailable"], [], None, decision.action, decision.reason,
                        decision.requested_exposure_us, decision.requested_gain,
                    )
                else:
                    record = RulerAEAttemptRecord(
                        attempt_index=len(attempts) + 1,
                        requested_exposure_us=capture_requested_exposure,
                        actual_exposure_us=int(actual_exposure) if actual_exposure is not None else None,
                        requested_gain=capture_requested_gain,
                        actual_gain=int(actual_gain) if actual_gain is not None else None,
                        global_saturation_fraction=metrics.global_saturation_fraction,
                        ruler_roi_saturation_fraction=metrics.ruler_roi_saturation_fraction,
                        tick_band_saturation_fraction=metrics.tick_band_saturation_fraction,
                        normalized_tick_contrast=metrics.normalized_tick_contrast,
                        michelson_tick_contrast=metrics.michelson_tick_contrast,
                        accepted_tick_count=metrics.accepted_tick_count,
                        periodicity_support=metrics.periodicity_support,
                        hierarchy_verified=metrics.hierarchy_verified,
                        ruler_candidate_confidence=metrics.candidate.confidence,
                        ruler_candidate_reliable=metrics.candidate.reliable,
                        ruler_candidate_reasons=list(metrics.candidate.reasons),
                        polygon=[list(point) for point in metrics.candidate.polygon],
                        angle_deg=metrics.candidate.angle_deg,
                        decision=decision.action,
                        decision_reason=decision.reason,
                        next_requested_exposure_us=decision.requested_exposure_us,
                        next_requested_gain=decision.requested_gain,
                    )
                record.capture_id = pending.capture_id
                attempts.append(record)
                last_result.diagnostics["ruler_auto_exposure_attempt"] = record.to_dict()
                last_result.diagnostics["ruler_auto_exposure_attempts"] = [
                    item.to_dict() for item in attempts
                ]
                last_result.diagnostics["ruler_auto_exposure_config"] = asdict(self.engine.config)
                if decision.action == "fail":
                    last_result.success = False
                    if decision.reason.startswith("ruler_candidate_unreliable"):
                        last_result.failure_reasons.append("ruler_candidate_unreliable")
                    elif decision.reason in {"analysis_exception", "quality_evaluation_exception"}:
                        last_result.failure_reasons.append("ruler_auto_exposure_exception")
                    else:
                        last_result.failure_reasons.append("ruler_auto_exposure_nonconvergent")
                self.history.finalize(pending, last_result)
                if attempt_callback is not None:
                    attempt_callback(record)
                LOG.info(
                    "[RULER_AE] attempt=%s exposure=%s gain=%s candidate_confidence=%.3f "
                    "global_sat=%s ruler_sat=%s tick_sat=%s michelson=%s decision=%s reason=%s",
                    record.attempt_index, record.actual_exposure_us, record.actual_gain,
                    record.ruler_candidate_confidence, record.global_saturation_fraction,
                    record.ruler_roi_saturation_fraction, record.tick_band_saturation_fraction,
                    record.michelson_tick_contrast, record.decision, record.decision_reason,
                )
                if decision.action == "accept":
                    return RulerAutoExposureOutcome(True, decision.reason, last_result, attempts, self.history.statistics())
                if decision.action == "fail":
                    return RulerAutoExposureOutcome(False, decision.reason, last_result, attempts, self.history.statistics())
                if decision.action == "retry_candidate":
                    candidate_retries += 1
                else:
                    candidate_retries = 0
                if decision.action in {"reduce_exposure", "increase_exposure", "increase_gain"}:
                    adjustments += 1
                exposure = decision.requested_exposure_us
                gain = decision.requested_gain
        except RulerAECancelled as exc:
            last_result.success = False
            last_result.failure_reasons.append("ruler_auto_exposure_cancelled")
            return RulerAutoExposureOutcome(False, str(exc), last_result, attempts, self.history.statistics())
        except Exception as exc:
            LOG.exception("[RULER_AE] acquisition failed")
            last_result.success = False
            last_result.failure_reasons.append("ruler_auto_exposure_exception")
            last_result.warnings.append(f"{type(exc).__name__}: {exc}")
            return RulerAutoExposureOutcome(False, str(exc), last_result, attempts, self.history.statistics())
        finally:
            try:
                camera.restore_state(original_state)
            except Exception:
                LOG.exception("[RULER_AE] failed to restore original camera state")


class CameraCaptureBridgeRulerAdapter:
    """Adapt the existing formal camera bridge without creating another SDK stream."""

    def __init__(
        self,
        bridge: Any,
        original_state: dict[str, object],
        *,
        timeout_s: float = 15.0,
    ) -> None:
        self.bridge = bridge
        self.original_state = dict(original_state)
        self.timeout_s = float(timeout_s)

    def snapshot_state(self) -> dict[str, object]:
        return dict(self.original_state)

    def limits(self) -> RulerCameraLimits:
        state = self.original_state
        exposure = int(state.get("ExposureReadbackUs") or 1)
        gain = int(state.get("GainReadback") or 0)
        return RulerCameraLimits(
            exposure_min_us=int(state.get("ExposureMinUs") or max(1, exposure // 100)),
            exposure_max_us=int(state.get("ExposureMaxUs") or max(exposure, 60_000_000)),
            gain_min=int(state.get("GainMin") if state.get("GainMin") is not None else gain),
            gain_max=int(state.get("GainMax") if state.get("GainMax") is not None else gain),
        )

    def capture(
        self,
        exposure_us: int,
        gain: int,
        settling_frames: int,
        check_cancel: Callable[[], None],
    ) -> AcquiredRulerFrame:
        captured = None
        for _ in range(max(0, int(settling_frames)) + 1):
            captured = self.bridge.capture(
                float(exposure_us) / 1000.0,
                int(gain),
                self.timeout_s,
                check_cancel,
                accept_actual_readback=True,
            )
        if captured is None or captured.scientific_image is None:
            raise RuntimeError("Ruler AE capture did not return a scientific frame")
        metadata = dict(captured.camera_metadata)
        metadata["CameraTemperatureC"] = captured.camera_temperature_c
        return AcquiredRulerFrame(
            raw=np.asarray(captured.scientific_image).copy(),
            metadata=metadata,
            frame_sequence=metadata.get("FrameSequence"),
            captured_at=captured.timestamp.astimezone().isoformat(timespec="milliseconds"),
        )

    def restore_state(self, state: dict[str, object]) -> None:
        if not bool(getattr(self.bridge.controller, "is_open", False)):
            return
        self.bridge.restore_state(state)
