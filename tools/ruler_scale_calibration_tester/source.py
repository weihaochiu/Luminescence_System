from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

import numpy as np

from core.i18n import tr


@dataclass(frozen=True)
class AnalysisSource:
    source_type: str
    source_identity: str
    frame_sequence: int | None = None
    filename: str = ""
    display_name: str = ""
    capture_timestamp: str = ""


class FrameCaptureState:
    """Keep the live stream mutable while the captured analysis input stays frozen."""

    def __init__(self) -> None:
        self.latest_frame: np.ndarray | None = None
        self.latest_sequence: int | None = None
        self.captured_frame: np.ndarray | None = None
        self.captured_source: AnalysisSource | None = None

    def update_live(self, frame: np.ndarray, sequence: int) -> None:
        array = np.asarray(frame)
        if array.ndim != 2:
            raise ValueError(f"Expected a scientific HxW frame, got {array.shape}")
        self.latest_frame = array.copy()
        self.latest_sequence = int(sequence)

    def capture_camera(
        self,
        device_name: str,
        *,
        captured_at: str | None = None,
    ) -> tuple[np.ndarray, AnalysisSource]:
        if self.latest_frame is None or self.latest_sequence is None:
            raise ValueError("No camera frame is available")
        timestamp = captured_at or datetime.now().astimezone().isoformat(timespec="milliseconds")
        sequence = self.latest_sequence
        device = device_name or "camera"
        source = AnalysisSource(
            source_type="camera",
            source_identity=f"camera|{device}|frame={sequence}|captured={timestamp}",
            frame_sequence=sequence,
            display_name=tr(
                "calibration.tester.camera_frame_source",
                device=device,
                sequence=sequence,
            ),
            capture_timestamp=timestamp,
        )
        self.captured_frame = self.latest_frame.copy()
        self.captured_source = source
        return self.captured_frame.copy(), source

    def capture_file(self, path: str | Path, frame: np.ndarray) -> tuple[np.ndarray, AnalysisSource]:
        resolved = Path(path).resolve()
        stat = resolved.stat()
        source = AnalysisSource(
            source_type="file",
            source_identity=f"file|{resolved}|mtime_ns={stat.st_mtime_ns}|size={stat.st_size}",
            filename=str(resolved),
            display_name=resolved.name,
        )
        self.captured_frame = np.asarray(frame).copy()
        self.captured_source = source
        return self.captured_frame.copy(), source
