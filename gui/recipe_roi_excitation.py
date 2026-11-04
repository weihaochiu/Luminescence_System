from __future__ import annotations

"""EL illumination for interactive ROIs, after per-channel polarity checks."""

from copy import deepcopy
import logging
import math
from queue import Empty, Queue
from threading import Event, Thread
from time import monotonic

from PySide6.QtCore import QEventLoop, QObject, Qt, Signal, QTimer
from PySide6.QtWidgets import QDialog

from core.i18n import tr


LOG = logging.getLogger(__name__)


def wait_for_restored_preview(owner):
    """Restart invalidates readiness; wait for an actual new scientific pull."""
    controller = owner.controller
    loop, failure = QEventLoop(), []
    timer = QTimer()
    timer.setSingleShot(True)
    def frame(_image):
        if controller._scientific_frame_validated:
            loop.quit()
    def failed(*_args):
        failure.append(tr("recipe.roi_frame_timeout"))
        loop.quit()
    controller.frame_ready.connect(frame)
    controller.camera_closed.connect(failed)
    controller.error_occurred.connect(failed)
    owner.emergency_manager.triggered.connect(failed)
    timer.timeout.connect(failed)
    try:
        timer.start(max(3000, round(controller.current_exposure()[0] / 1000) + 3000))
        if not controller._scientific_frame_validated:
            loop.exec()
        if failure or not controller._scientific_frame_validated:
            raise RuntimeError(tr("recipe.roi_frame_timeout"))
    finally:
        timer.stop()
        controller.frame_ready.disconnect(frame)
        controller.camera_closed.disconnect(failed)
        controller.error_occurred.disconnect(failed)
        owner.emergency_manager.triggered.disconnect(failed)


def validate_roi_excitation(recipe, safety=None):
    matrix = recipe.el_matrix
    if matrix.output_mode not in {"current_density", "voltage"}:
        return []  # The normal matrix validator reports this.
    value = (matrix.roi_voltage_v if matrix.output_mode == "voltage"
             else matrix.roi_current_density_ma_cm2)
    if (isinstance(value, bool) or not isinstance(value, (int, float))
            or not math.isfinite(value) or value <= 0
            or recipe.geometry.forward_polarity not in {"positive", "negative"}):
        return [tr("recipe.roi_invalid_excitation")]
    max_current = float(getattr(safety, "maximum_current_a", 0.05))
    max_voltage = float(getattr(safety, "maximum_voltage_v", 5.0))
    max_power = float(getattr(safety, "maximum_power_w", 0.15))
    if matrix.output_mode == "voltage":
        power = value * matrix.current_compliance_ma / 1000
        invalid = value > max_voltage
        if recipe.geometry.forward_polarity == "negative":
            invalid |= -value < float(getattr(safety, "minimum_voltage_v", -max_voltage))
    else:
        currents = [recipe.matrix_source_current_ma(ch, value) / 1000
                    for ch in recipe.enabled_channels() if math.isfinite(ch.area_cm2) and ch.area_cm2 > 0]
        invalid = any(current <= 0 or current > max_current for current in currents)
        power = max(currents, default=0) * matrix.voltage_compliance_v
    return [tr("recipe.roi_excitation_safety")] if invalid or power > max_power else []


class ELROISession(QObject):
    """Only hardware I/O runs in the thread; camera and widgets stay on Qt."""

    ready = Signal(str, object)
    status = Signal(str)
    finished = Signal(object)

    def __init__(self, recipe, hardware, *, max_output_time_s=600, max_recipe_time_s=1800):
        super().__init__()
        self.recipe, self.hardware = recipe, hardware
        self.channels = {ch.channel: ch for ch in recipe.enabled_channels()}
        self.commands = Queue()
        self.cancelled = Event()
        self.result = {"polarity": {}, "channels": {}, "error": ""}
        self.max_output_time_s = float(max_output_time_s)
        self.max_recipe_time_s = float(max_recipe_time_s)
        self._started = monotonic()
        self._output_started = None
        self._active_channel = None
        self.thread = Thread(target=self.run, name="Recipe EL ROI", daemon=False)

    def request_channel(self, channel):
        if not self.cancelled.is_set():
            self.commands.put(channel)

    def cancel(self, *_args):
        self.cancelled.set()

    def check_cancel(self):
        from .measurement_worker import MeasurementCancelled
        if self.cancelled.is_set():
            raise MeasurementCancelled()
        if monotonic() - self._started > self.max_recipe_time_s:
            raise TimeoutError(tr("recipe.roi_session_timeout"))
        if self._output_started is not None and monotonic() - self._output_started > self.max_output_time_s:
            raise TimeoutError(tr("recipe.roi_output_timeout"))

    def verify_dark(self):
        if not self.hardware.relay.verify_white_light_off():
            raise RuntimeError(tr("recipe.roi_light_off_failed"))
        self.hardware._verify_gsp4h_dark()

    def prepare(self, name):
        from .el_matrix_runner import interruptible_wait
        from .el_matrix_hardware import relay_channel_id
        channel = self.channels[name]
        self.check_cancel()
        self.hardware.output_off()
        self._output_started = None
        self.hardware.clear_routing()
        self.hardware.route_channel(name, self.check_cancel)
        self.hardware.relay.set_white_light_inhibited("recipe_roi", False)
        if self.recipe.polarity.enabled:
            self.status.emit(tr("recipe.roi_checking_polarity", channel=name))
            result = self.hardware.run_polarity(channel, self.check_cancel)
            factor = result.get("polarity_factor")
            if result.get("polarity_check_status") != "COMPLETED" or type(factor) is not int or factor not in (-1, 1):
                raise RuntimeError(tr("recipe.roi_polarity_failed", channel=name))
            self.result["polarity"][name] = deepcopy(result)
        else:
            factor = 1 if self.recipe.geometry.forward_polarity == "positive" else -1
        self.hardware.output_off()
        self.hardware.relay.set_white_light_inhibited("recipe_roi", True)
        if not self.hardware.relay.safe_white_light_off("recipe_roi_el"):
            raise RuntimeError(tr("recipe.roi_light_off_failed"))
        self.verify_dark()
        self.hardware.apply_polarity_factor(factor)
        self.check_cancel()
        matrix = self.recipe.el_matrix
        limits = self.hardware.control.safety.limits
        if matrix.output_mode == "voltage":
            physical_request = factor * matrix.roi_voltage_v
            allowed = limits.minimum_voltage_v <= physical_request <= limits.maximum_voltage_v
        else:
            physical_request = factor * self.recipe.matrix_source_current_ma(channel, matrix.roi_current_density_ma_cm2) / 1000
            allowed = limits.minimum_current_a <= physical_request <= limits.maximum_current_a
        if not allowed:
            raise ValueError(tr("recipe.roi_excitation_safety"))
        self._output_started = monotonic()
        if matrix.output_mode == "voltage":
            physical = self.hardware.set_voltage(matrix.roi_voltage_v, matrix.current_compliance_ma)
            condition = f"{matrix.roi_voltage_v:g} V"
        else:
            current = self.recipe.matrix_source_current_ma(channel, matrix.roi_current_density_ma_cm2) / 1000
            physical = self.hardware.set_current(current, matrix.voltage_compliance_v)
            condition = f"{matrix.roi_current_density_ma_cm2:g} mA/cm²"
        interruptible_wait(matrix.stabilization_ms / 1000, self.check_cancel)
        self.check_cancel()
        self.verify_dark()
        self.hardware.relay.verify_smu_output_channel_state(relay_channel_id(name), "recipe_roi_el")
        reading = self.hardware.readback()
        self.check_cancel()
        record = {"condition": condition, "output_mode": matrix.output_mode,
                  "commanded_physical": physical, "polarity_factor": factor,
                  "measured_current_a": reading.current_a, "measured_voltage_v": reading.voltage_v,
                  "white_light_off_verified": True, "area_cm2": channel.area_cm2}
        self.result["channels"][name] = record
        self._active_channel = name
        LOG.info("RECIPE_EL_ROI_READY channel=%s details=%s", name, record)
        self.ready.emit(name, record)

    def run(self):
        from .measurement_worker import MeasurementCancelled
        try:
            errors = self.recipe.validate(self.hardware.control.safety.limits)
            if errors:
                raise ValueError("; ".join(errors))
            while not self.cancelled.is_set():
                self.check_cancel()
                try:
                    name = self.commands.get(timeout=0.2)
                except Empty:
                    if self._active_channel is not None:
                        self.verify_dark()
                        self.hardware.readback()  # Includes compliance and OUTPUT ON checks.
                    continue
                self.prepare(name)
        except MeasurementCancelled:
            pass
        except Exception as exc:
            LOG.exception("RECIPE_EL_ROI_FAILED")
            self.result["error"] = str(exc)
        finally:
            try:
                self.result["safe_shutdown"] = self.hardware.safe_shutdown()
                required = ("ok", "smu_output_off", "routing_off", "white_light_off", "ownership_released")
                if not all(self.result["safe_shutdown"].get(key) is True for key in required):
                    raise RuntimeError(tr("measurement.safe_shutdown_failed"))
            except Exception as exc:
                self.result["error"] = "; ".join(filter(None, (self.result["error"], str(exc))))
            finally:
                try:
                    self.hardware.relay.set_white_light_inhibited("recipe_roi", False)
                except Exception as exc:
                    self.result["error"] = "; ".join(filter(None, (self.result["error"], str(exc))))
            self.finished.emit(deepcopy(self.result))


def run_el_roi_selection(owner, recipe):
    from .camera_controller import SDKAutoExposureMode
    from .camera_recipe_ae import begin_recipe_ae, restore_recipe_ae
    from .el_matrix_hardware import ELMatrixHardwareAdapter
    from .polarity_settings import PolarityMeasurementSettings
    from .recipe_roi_dialog import RecipeROIDialog

    hardware = ELMatrixHardwareAdapter(owner.smu_manager.control, owner.relay_service, None,
        PolarityMeasurementSettings.from_dict(owner.polarity_settings_store.settings.to_dict()),
        light_service=getattr(owner, "light_service", None))
    session = ELROISession(recipe, hardware, max_output_time_s=owner.max_output_time_s,
                           max_recipe_time_s=owner.max_recipe_time_s)
    dialog = RecipeROIDialog(owner.controller, list(session.channels), parent=owner, excitation_required=True)
    loop, completed, preview = QEventLoop(), {}, {}
    owner._recipe_roi_preparation = {}

    def channel_ready(name, record):
        if dialog._closed or session.cancelled.is_set():
            return
        try:
            if preview:
                restore_recipe_ae(owner.controller, preview)
                preview.clear()
            maximum = min(5000000, owner.controller._exposure_range[1]) / 1000
            settings = {"auto_gain_mode": "auto", "auto_target_percent": 20,
                        "auto_max_exposure_ms": maximum, "auto_exposure_stops": [0]}
            begin_recipe_ae(owner.controller, settings, preview, mode=SDKAutoExposureMode.CONTINUOUS)
            dialog.channel_ready(name, record["condition"])
        except Exception as exc:
            dialog._fail(str(exc))

    def finished(result):
        completed.update(result)
        if result["error"] and not dialog._closed:
            dialog._fail(result["error"])
        elif not dialog._closed:
            dialog.reject()
        loop.quit()

    session.ready.connect(channel_ready, Qt.ConnectionType.QueuedConnection)
    session.status.connect(dialog.coordinates.setText)
    session.finished.connect(finished, Qt.ConnectionType.QueuedConnection)
    dialog.channel_requested.connect(session.request_channel)
    dialog.finished.connect(session.cancel)
    emergency = lambda *_args: dialog.reject()
    owner.emergency_manager.triggered.connect(emergency)
    session.request_channel(dialog.channels[0])
    session.thread.start()
    accepted = False
    try:
        accepted = dialog.exec() == QDialog.DialogCode.Accepted
        session.cancel()
        if not completed:
            loop.exec()
        session.thread.join()
        if completed.get("error"):
            raise RuntimeError(completed["error"])
        if dialog.error:
            raise RuntimeError(dialog.error)
        owner._recipe_roi_preparation = deepcopy(completed)
        return dialog.rois if accepted and not owner.emergency_manager.is_active else None
    finally:
        session.cancel()
        if session.thread.is_alive():
            if not completed:
                loop.exec()
            session.thread.join()
        owner.emergency_manager.triggered.disconnect(emergency)
        try:
            if preview and owner.controller.is_open and not owner.emergency_manager.is_active:
                restore_recipe_ae(owner.controller, preview)
                if accepted and not completed.get("error") and not dialog.error:
                    wait_for_restored_preview(owner)
        finally:
            dialog.deleteLater()
            session.deleteLater()
