from __future__ import annotations

"""Shared, flicker-resistant Jsc/Voc sampling used by Manual and Recipe flows."""

from contextlib import nullcontext
from dataclasses import asdict, dataclass
import logging
import math
from statistics import fmean, median, pstdev
from typing import Any, Callable, ContextManager

from .polarity_settings import PolarityMeasurementSettings


LOG = logging.getLogger(__name__)


@dataclass(frozen=True)
class SampleStatistics:
    samples: tuple[float, ...]
    representative: float
    standard_deviation: float
    value_range: float
    variation_percent: float
    aggregation: str


@dataclass(frozen=True)
class PolarityMeasurementResult:
    state: str
    factor: int | None
    jsc_ma_cm2: SampleStatistics
    voc_v: SampleStatistics
    settings_snapshot: dict[str, Any]
    failure_reason: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "Jsc": asdict(self.jsc_ma_cm2),
            "Voc": asdict(self.voc_v),
            "polarity_result": self.state,
            "polarity_factor": self.factor,
            "failure_reason": self.failure_reason,
            "settings_snapshot": self.settings_snapshot,
        }


class PolarityMeasurementError(RuntimeError):
    def __init__(
        self,
        message: str,
        result: PolarityMeasurementResult | None = None,
        details: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(message)
        self.result = result
        self.details = dict(details or {})


class PolarityMeasurementService:
    """Own the single sampling, aggregation, stability, and sign algorithm."""

    def measure(
        self,
        driver: Any,
        settings: PolarityMeasurementSettings,
        area_cm2: float,
        *,
        light_on: Callable[[], None],
        light_off: Callable[[], None],
        check_cancel: Callable[[], None],
        wait_ms: Callable[[int], None],
        status: Callable[[str], None],
    ) -> PolarityMeasurementResult:
        if area_cm2 <= 0:
            raise ValueError("Device area must be greater than 0 cm²")
        errors = settings.validate()
        if errors:
            raise ValueError("Polarity settings are invalid: " + "; ".join(errors))
        snapshot = settings.snapshot()
        light_shutdown_required = False
        partial_results: dict[str, Any] = {}
        try:
            check_cancel()
            status("開啟白光…")
            # The relay may switch before its transport reports an error, so an
            # attempted ON always requires a best-effort OFF in ``finally``.
            light_shutdown_required = True
            light_on()
            wait_ms(settings.white_light_stabilization_ms)

            status("量測 Jsc…")
            current_compliance_a = settings.jsc_compliance_ma_cm2 * area_cm2 / 1000.0
            driver.configure_voltage_source(0.0, current_compliance_a)
            with self._integration_context(driver, "CURR", settings):
                jsc_a = self._sample_output(
                    driver,
                    settings.jsc_sample_count,
                    settings.jsc_settle_ms,
                    driver.measure_current,
                    check_cancel,
                    wait_ms,
                )
            jsc_density = tuple(value * 1000.0 / area_cm2 for value in jsc_a)
            jsc = self.analyze(
                jsc_density,
                settings.jsc_aggregation,
                settings.jsc_minimum_valid_ma_cm2,
                settings.jsc_max_variation_percent,
                "Jsc",
            )
            partial_results["Jsc"] = asdict(jsc)

            status("量測 Voc…")
            driver.configure_current_source(0.0, settings.voc_compliance_v)
            with self._integration_context(driver, "VOLT", settings):
                voc_samples = self._sample_output(
                    driver,
                    settings.voc_sample_count,
                    settings.voc_settle_ms,
                    driver.measure_voltage,
                    check_cancel,
                    wait_ms,
                )
            voc = self.analyze(
                voc_samples,
                settings.voc_aggregation,
                settings.voc_minimum_valid_v,
                settings.voc_max_variation_percent,
                "Voc",
            )
            partial_results["Voc"] = asdict(voc)

            status("判斷極性…")
            if voc.representative > 0 and jsc.representative < 0:
                state, factor = "NORMAL", 1
            elif voc.representative < 0 and jsc.representative > 0:
                state, factor = "REVERSED", -1
            else:
                raise PolarityMeasurementError(
                    "Jsc/Voc signs do not identify a safe polarity",
                    details={"Jsc": asdict(jsc), "Voc": asdict(voc)},
                )
            result = PolarityMeasurementResult(state, factor, jsc, voc, snapshot)
            LOG.info("POLARITY_MEASUREMENT %s", result.to_dict())
            return result
        except PolarityMeasurementError as exc:
            exc.details = {**partial_results, **exc.details}
            LOG.warning("POLARITY_MEASUREMENT_FAILED reason=%s details=%s", exc, exc.details)
            raise
        finally:
            if light_shutdown_required:
                check_cancel_safely = True
                try:
                    check_cancel()
                except Exception:
                    check_cancel_safely = False
                status("關閉白光…")
                light_off()
                if not check_cancel_safely:
                    LOG.info("White Light OFF completed after polarity cancellation")

    @staticmethod
    def analyze(
        samples: tuple[float, ...] | list[float],
        aggregation: str,
        minimum_absolute: float,
        maximum_variation_percent: float,
        label: str,
    ) -> SampleStatistics:
        values = tuple(float(value) for value in samples)
        if not values or any(not math.isfinite(value) for value in values):
            raise PolarityMeasurementError(
                f"{label} contains missing or invalid samples",
                details={label: {"samples": values}},
            )
        signs = {1 if value > 0 else -1 if value < 0 else 0 for value in values}
        if 0 in signs or len(signs) != 1:
            raise PolarityMeasurementError(
                f"{label} sample signs are inconsistent",
                details={label: {"samples": values}},
            )
        representative = median(values) if aggregation == "median" else fmean(values)
        value_range = max(values) - min(values)
        deviation = pstdev(values)
        variation = value_range / abs(representative) * 100.0
        statistics = SampleStatistics(
            values,
            representative,
            deviation,
            value_range,
            variation,
            aggregation,
        )
        if abs(representative) < minimum_absolute:
            raise PolarityMeasurementError(
                f"{label} representative is below the configured minimum",
                details={label: asdict(statistics)},
            )
        if variation > maximum_variation_percent:
            raise PolarityMeasurementError(
                f"{label} variation {variation:.3g}% exceeds {maximum_variation_percent:.3g}%",
                details={label: asdict(statistics)},
            )
        return statistics

    @staticmethod
    def _integration_context(
        driver: Any,
        mode: str,
        settings: PolarityMeasurementSettings,
    ) -> ContextManager[Any]:
        if not settings.anti_flicker_enabled:
            return nullcontext()
        factory = getattr(driver, "temporary_measurement_nplc", None)
        if callable(factory):
            return factory(mode, settings.integration_nplc)
        LOG.warning(
            "SMU driver does not support temporary NPLC; polarity sampling continues without changing integration"
        )
        return nullcontext()

    @staticmethod
    def _sample_output(
        driver: Any,
        sample_count: int,
        settle_ms: int,
        measure: Callable[[], float],
        check_cancel: Callable[[], None],
        wait_ms: Callable[[int], None],
    ) -> tuple[float, ...]:
        output_shutdown_required = False
        try:
            check_cancel()
            # An ON command can reach the instrument even if the transport or
            # readback fails immediately afterwards. Always issue OFF once ON
            # has been attempted.
            output_shutdown_required = True
            driver.set_output_enabled(True)
            if driver.query_output_enabled() is not True:
                raise PolarityMeasurementError("Temporary measurement OUTPUT ON was not confirmed")
            wait_ms(settle_ms)
            readings: list[float] = []
            for _index in range(sample_count):
                check_cancel()
                readings.append(float(measure()))
                check_cancel()
            return tuple(readings)
        finally:
            if output_shutdown_required:
                driver.set_output_enabled(False)
                if driver.query_output_enabled() is not False:
                    raise PolarityMeasurementError("Temporary measurement OUTPUT OFF was not confirmed")
