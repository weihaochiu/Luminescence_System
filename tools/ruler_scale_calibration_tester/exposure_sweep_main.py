from __future__ import annotations

import argparse
from pathlib import Path
import sys
from threading import Event

from PySide6.QtCore import QObject, QCoreApplication, QThread, Signal, Slot
from PySide6.QtWidgets import QApplication

from core.calibration import CalibrationService
from core.i18n import configure_i18n
from gui.app import _configure_logging
from gui.camera_capture_bridge import CameraCaptureBridge
from gui.camera_controller import CameraController

from .exposure_sweep import ControlledExposureSweepRunner, DEFAULT_SWEEP_ROOT
from .ruler_auto_exposure import CameraCaptureBridgeRulerAdapter


class SweepWorker(QObject):
    finished = Signal(object, object)

    def __init__(self, runner, adapter, device_name: str) -> None:
        super().__init__()
        self.runner = runner
        self.adapter = adapter
        self.device_name = device_name

    @Slot()
    def run(self) -> None:
        try:
            self.finished.emit(self.runner.run(self.adapter, self.device_name, Event()), None)
        except Exception as exc:
            self.finished.emit(None, exc)


def parser() -> argparse.ArgumentParser:
    value = argparse.ArgumentParser(description="Collect a local-only controlled ruler exposure sweep")
    value.add_argument("--camera-index", type=int, default=0)
    value.add_argument("--output-root", type=Path, default=DEFAULT_SWEEP_ROOT)
    return value


def main(argv: list[str] | None = None) -> int:
    args = parser().parse_args(argv)
    QCoreApplication.setOrganizationName("EL Measurement Lab")
    QCoreApplication.setApplicationName("Ruler Exposure Sweep")
    app = QApplication(sys.argv[:1])
    _configure_logging()
    configure_i18n()
    controller = CameraController()
    bridge = CameraCaptureBridge(controller)
    devices = controller.enumerate_devices()
    if not devices or args.camera_index < 0 or args.camera_index >= len(devices):
        print("ERROR: requested RisingCam camera is unavailable", file=sys.stderr)
        return 2
    thread: QThread | None = None
    worker: SweepWorker | None = None
    exit_code = 1

    def opened(_info: object) -> None:
        nonlocal thread, worker
        state = dict(controller.capture_metadata())
        try:
            state["CameraTemperatureC"] = controller.read_temperature_c()
        except Exception:
            state["CameraTemperatureC"] = None
        runner = ControlledExposureSweepRunner(
            CalibrationService(),
            output_root=args.output_root,
        )
        adapter = CameraCaptureBridgeRulerAdapter(bridge, state)
        thread = QThread()
        worker = SweepWorker(runner, adapter, controller.device_name)
        worker.moveToThread(thread)
        thread.started.connect(worker.run)
        worker.finished.connect(done)
        thread.start()

    def done(output: object, error: object) -> None:
        nonlocal exit_code
        if error is None:
            print(f"Controlled exposure sweep completed: {output}")
            exit_code = 0
        else:
            print(f"ERROR: controlled exposure sweep failed: {error}", file=sys.stderr)
            exit_code = 1
        controller.close_camera()
        if thread is not None:
            thread.quit()
        app.quit()

    controller.camera_opened.connect(opened)
    controller.error_occurred.connect(lambda message: print(f"Camera error: {message}", file=sys.stderr))
    controller.open_device(devices[args.camera_index])
    app.exec()
    if thread is not None:
        thread.wait(5000)
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
