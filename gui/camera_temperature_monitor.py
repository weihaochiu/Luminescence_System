from __future__ import annotations

"""Camera-temperature polling, session history, CSV logging, and snapshots."""

import csv
import logging
import math
from collections import deque
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from threading import RLock
from typing import Callable, TextIO

from PySide6.QtCore import QObject, QTimer, Signal, Slot


LOG = logging.getLogger(__name__)

SAMPLING_INTERVAL_MS = 1000
CHART_HISTORY_SECONDS = 30 * 60
MAX_CHART_SAMPLES = CHART_HISTORY_SECONDS * 1000 // SAMPLING_INTERVAL_MS
STALE_AFTER_SECONDS = 3.0


class CameraTemperatureUnsupportedError(RuntimeError):
    """Raised when the connected camera does not advertise temperature readout."""


@dataclass(frozen=True)
class TemperatureSample:
    value_c: float
    timestamp: datetime

    def timestamp_text(self) -> str:
        return self.timestamp.isoformat(timespec="milliseconds")


def format_temperature_c(value_c: float | None) -> str:
    return "N/A" if value_c is None else f"{value_c:.1f} °C"


class CameraTemperatureMonitor(QObject):
    """Poll one controller-owned temperature source from the Qt owner thread."""

    sample_received = Signal(object)
    availability_changed = Signal(bool)
    session_started = Signal(str)
    session_stopped = Signal(str)

    def __init__(
        self,
        read_temperature_c: Callable[[], float | None],
        is_connected: Callable[[], bool],
        log_directory: str | Path,
        parent: QObject | None = None,
        interval_ms: int = SAMPLING_INTERVAL_MS,
        history_limit: int = MAX_CHART_SAMPLES,
    ) -> None:
        super().__init__(parent)
        self._read_temperature_c = read_temperature_c
        self._is_connected = is_connected
        self._log_directory = Path(log_directory)
        self._history: deque[TemperatureSample] = deque(maxlen=max(1, history_limit))
        self._lock = RLock()
        self._latest_sample: TemperatureSample | None = None
        self._session_min_c: float | None = None
        self._session_max_c: float | None = None
        self._session_active = False
        self._unsupported = False
        self._csv_path: Path | None = None
        self._csv_stream: TextIO | None = None
        self._csv_writer: csv.DictWriter | None = None
        self._last_error_message = ""
        self._last_error_log_at: datetime | None = None

        self._timer = QTimer(self)
        self._timer.setInterval(interval_ms)
        self._timer.timeout.connect(self.poll_now)

    @property
    def interval_ms(self) -> int:
        return self._timer.interval()

    @property
    def is_running(self) -> bool:
        return self._timer.isActive()

    @property
    def session_active(self) -> bool:
        return self._session_active

    @property
    def unsupported(self) -> bool:
        return self._unsupported

    @property
    def csv_path(self) -> Path | None:
        return self._csv_path

    @property
    def history(self) -> tuple[TemperatureSample, ...]:
        with self._lock:
            return tuple(self._history)

    @property
    def session_min_c(self) -> float | None:
        return self._session_min_c

    @property
    def session_max_c(self) -> float | None:
        return self._session_max_c

    def start(
        self,
        *,
        supported: bool = True,
        camera_model: str = "",
        camera_identifier: str = "",
    ) -> None:
        if self._session_active:
            return
        self._session_active = True
        self._unsupported = False
        self._last_error_message = ""
        self._last_error_log_at = None
        with self._lock:
            self._latest_sample = None
            self._history.clear()
        self._session_min_c = None
        self._session_max_c = None
        self._open_csv()
        LOG.info(
            "Camera temperature monitor started path=%s model=%s identifier=%s interval_ms=%d",
            self._csv_path,
            camera_model or "unknown",
            camera_identifier or "unknown",
            self.interval_ms,
        )
        self.session_started.emit(str(self._csv_path or ""))
        self.availability_changed.emit(False)
        if not supported:
            self._mark_unsupported("Connected camera does not advertise sensor temperature readout")
            return
        self._timer.start()
        self.poll_now()

    def stop(self) -> None:
        self._timer.stop()
        was_active = self._session_active
        self._session_active = False
        with self._lock:
            self._latest_sample = None
        self.availability_changed.emit(False)
        self._close_csv()
        if was_active:
            LOG.info("Camera temperature monitor stopped path=%s", self._csv_path)
            self.session_stopped.emit(str(self._csv_path or ""))

    shutdown = stop

    @Slot()
    def poll_now(self) -> None:
        if not self._session_active or self._unsupported or not self._is_connected():
            return
        try:
            value = self._read_temperature_c()
            if value is None:
                raise ValueError("camera temperature is unavailable")
            value_c = float(value)
            if not math.isfinite(value_c) or not -273.15 <= value_c <= 1000.0:
                raise ValueError(f"invalid camera temperature value: {value!r}")
        except CameraTemperatureUnsupportedError as exc:
            self._mark_unsupported(str(exc))
            return
        except Exception as exc:  # noqa: BLE001 - telemetry failures are non-fatal
            self._log_read_failure(exc)
            self.availability_changed.emit(False)
            return

        sample = TemperatureSample(value_c=value_c, timestamp=datetime.now().astimezone())
        with self._lock:
            self._latest_sample = sample
            self._history.append(sample)
        self._session_min_c = (
            value_c if self._session_min_c is None else min(self._session_min_c, value_c)
        )
        self._session_max_c = (
            value_c if self._session_max_c is None else max(self._session_max_c, value_c)
        )
        self._write_sample(sample)
        self.availability_changed.emit(True)
        self.sample_received.emit(sample)

    def latest_snapshot(
        self,
        *,
        max_age_s: float = STALE_AFTER_SECONDS,
        reference_time: datetime | None = None,
    ) -> TemperatureSample | None:
        with self._lock:
            sample = self._latest_sample
        if sample is None:
            return None
        now = reference_time or datetime.now().astimezone()
        if now.tzinfo is None:
            now = now.astimezone()
        age_s = (now - sample.timestamp).total_seconds()
        if age_s < 0 or age_s > max_age_s:
            return None
        return sample

    def metadata_fields(
        self,
        *,
        max_age_s: float = STALE_AFTER_SECONDS,
        reference_time: datetime | None = None,
    ) -> dict[str, float | str]:
        sample = self.latest_snapshot(max_age_s=max_age_s, reference_time=reference_time)
        if sample is None:
            return {}
        return {
            "CameraTemperature_C": round(sample.value_c, 2),
            "CameraTemperatureTimestamp": sample.timestamp_text(),
        }

    def _open_csv(self) -> None:
        self._log_directory.mkdir(parents=True, exist_ok=True)
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        candidate = self._log_directory / f"camera_temperature_{timestamp}.csv"
        suffix = 1
        while candidate.exists():
            candidate = self._log_directory / f"camera_temperature_{timestamp}_{suffix:03d}.csv"
            suffix += 1
        self._csv_path = candidate
        self._csv_stream = candidate.open("w", newline="", encoding="utf-8-sig")
        self._csv_writer = csv.DictWriter(
            self._csv_stream, fieldnames=("timestamp", "temperature_c")
        )
        self._csv_writer.writeheader()
        self._csv_stream.flush()

    def _write_sample(self, sample: TemperatureSample) -> None:
        if self._csv_writer is None or self._csv_stream is None:
            return
        self._csv_writer.writerow(
            {
                "timestamp": sample.timestamp_text(),
                "temperature_c": f"{sample.value_c:.2f}",
            }
        )
        self._csv_stream.flush()

    def _close_csv(self) -> None:
        if self._csv_stream is not None:
            self._csv_stream.flush()
            self._csv_stream.close()
        self._csv_stream = None
        self._csv_writer = None

    def _mark_unsupported(self, message: str) -> None:
        self._unsupported = True
        self._timer.stop()
        self.availability_changed.emit(False)
        LOG.warning("Camera temperature API unsupported: %s", message)

    def _log_read_failure(self, exc: Exception) -> None:
        now = datetime.now().astimezone()
        message = f"{type(exc).__name__}: {exc}"
        should_log = (
            message != self._last_error_message
            or self._last_error_log_at is None
            or (now - self._last_error_log_at).total_seconds() >= 60.0
        )
        if should_log:
            LOG.warning("Camera temperature read unavailable; polling will continue: %s", message)
            self._last_error_message = message
            self._last_error_log_at = now
