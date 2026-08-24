from __future__ import annotations

"""Shared, flicker-resistant Jsc/Voc sampling used by Manual and Recipe flows."""

from contextlib import nullcontext
from dataclasses import asdict, dataclass
import logging
import math
from statistics import fmean, median, pstdev
from typing import Any, Callable, ContextManager

from core.i18n import tr

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
            "validity_result": "VALID" if self.factor is not None else "INVALID",
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
            status(tr("polarity.status.white_light_on"))
            # The relay may switch before its transport reports an error, so an
            # attempted ON always requires a best-effort OFF in ``finally``.
            light_shutdown_required = True
            light_on()
            wait_ms(settings.white_light_stabilization_ms)

            status(tr("polarity.status.measuring_jsc"))
            current_compliance_a = settings.jsc_compliance_ma_cm2 * area_cm2 / 1000.0
            with self._measurement_configuration(
                driver,
                source_mode="VOLT",
                measurement_mode="CURR",
                compliance=current_compliance_a,
                settings=settings,
            ):
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
                enforce_minimum=False,
            )
            partial_results["Jsc"] = asdict(jsc)
            LOG.info(
                "POLARITY_JSC raw_current_a=%s sample_area_cm2=%g "
                "current_density_ma_cm2=%+.9g compliance_a=%g",
                jsc_a,
                area_cm2,
                jsc.representative,
                current_compliance_a,
            )

            status(tr("polarity.status.measuring_voc"))
            with self._measurement_configuration(
                driver,
                source_mode="CURR",
                measurement_mode="VOLT",
                compliance=settings.voc_compliance_v,
                settings=settings,
            ):
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
                enforce_minimum=False,
            )
            partial_results["Voc"] = asdict(voc)
            LOG.info(
                "POLARITY_VOC samples_v=%s representative_v=%+.9g compliance_v=%g",
                voc_samples,
                voc.representative,
                settings.voc_compliance_v,
            )

            status(tr("polarity.status.determining"))
            invalid_reasons: list[str] = []
            if abs(jsc.representative) < settings.jsc_minimum_valid_ma_cm2:
                invalid_reasons.append(
                    "Jsc representative is below the configured minimum "
                    f"({abs(jsc.representative):g} < {settings.jsc_minimum_valid_ma_cm2:g} mA/cm²)"
                )
            if abs(voc.representative) < settings.voc_minimum_valid_v:
                invalid_reasons.append(
                    "Voc representative is below the configured minimum "
                    f"({abs(voc.representative):g} < {settings.voc_minimum_valid_v:g} V)"
                )
            if invalid_reasons:
                state, factor = "INVALID", None
                failure_reason = "; ".join(invalid_reasons)
            elif voc.representative > 0 and jsc.representative < 0:
                state, factor = "NORMAL", 1
                failure_reason = ""
            elif voc.representative < 0 and jsc.representative > 0:
                state, factor = "REVERSED", -1
                failure_reason = ""
            else:
                state, factor = "INVALID", None
                failure_reason = "Jsc/Voc signs do not identify a safe polarity"
            result = PolarityMeasurementResult(
                state,
                factor,
                jsc,
                voc,
                snapshot,
                failure_reason,
            )
            log = LOG.info if factor is not None else LOG.warning
            log("POLARITY_MEASUREMENT %s", result.to_dict())
            return result
        except PolarityMeasurementError as exc:
            exc.details = {**partial_results, **exc.details}
            LOG.warning("POLARITY_MEASUREMENT_FAILED reason=%s details=%s", exc, exc.details)
            raise
        except Exception:
            LOG.exception("POLARITY_MEASUREMENT_EXCEPTION partial_results=%s", partial_results)
            raise
        finally:
            if light_shutdown_required:
                check_cancel_safely = True
                try:
                    check_cancel()
                except Exception:
                    check_cancel_safely = False
                status(tr("polarity.status.white_light_off"))
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
        *,
        enforce_minimum: bool = True,
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
        if enforce_minimum and abs(representative) < minimum_absolute:
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

    @classmethod
    def _measurement_configuration(
        cls,
        driver: Any,
        *,
        source_mode: str,
        measurement_mode: str,
        compliance: float,
        settings: PolarityMeasurementSettings,
    ) -> ContextManager[Any]:
        configure = getattr(driver, "configure_zero_level_measurement", None)
        if callable(configure):
            configure(
                source_mode,
                measurement_mode,
                compliance,
                settings.integration_nplc,
            )
            return nullcontext()

        if source_mode == "VOLT":
            driver.configure_voltage_source(0.0, compliance)
        else:
            driver.configure_current_source(0.0, compliance)
        LOG.info(
            "POLARITY_MEASUREMENT_CONFIG source_mode=%s measurement_mode=%s "
            "nplc=%g nplc_auto=OFF range=AUTO driver_specific=false",
            source_mode,
            measurement_mode,
            settings.integration_nplc,
        )
        return cls._integration_context(driver, measurement_mode, settings)

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
