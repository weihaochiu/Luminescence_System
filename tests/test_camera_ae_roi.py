from __future__ import annotations

import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import numpy as np

from gui.camera_controller import CameraController, SDKAutoExposureMode
from gui.camera_ae_calibration import AECalibrationIdentity, AECalibrationRun
from gui.sdk import nncam
from tests.qt_test_utils import ensure_qapplication
from tests.test_camera_exposure import (
    FakeModeCamera,
    configured_controller,
    resolution_controller,
)
from tests.test_camera_scientific import _FakeMonoCamera, _install_frame, _open


class FaultAERectCamera(FakeModeCamera):
    def __init__(
        self,
        *,
        put_error: Exception | None = None,
        get_error: Exception | None = None,
        readback: tuple[int, int, int, int] | None = None,
    ) -> None:
        super().__init__()
        self.put_error = put_error
        self.get_error = get_error
        self.forced_readback = readback
        self.closed = False

    def put_AEAuxRect(self, x: int, y: int, width: int, height: int) -> None:
        if self.closed:
            raise RuntimeError("AEAuxRect write after Close")
        self.calls.append(("ae_roi", x, y, width, height))
        if self.put_error is not None:
            raise self.put_error
        self.ae_aux_rect = (x, y, width, height)

    def get_AEAuxRect(self) -> tuple[int, int, int, int]:
        if self.closed:
            raise RuntimeError("AEAuxRect read after Close")
        self.calls.append(("read_ae_roi",))
        if self.get_error is not None:
            raise self.get_error
        return self.forced_readback or self.ae_aux_rect

    def Close(self) -> None:
        self.calls.append(("close",))
        self.closed = True


class CameraAEROITests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.app = ensure_qapplication()

    def test_set_roi_writes_exact_image_coordinates_and_verifies_readback(self) -> None:
        camera = FakeModeCamera()
        controller = configured_controller(camera)
        controller._width, controller._height = 640, 480

        self.assertTrue(controller.set_auto_exposure_roi(10, 20, 100, 80))

        self.assertIn(("ae_roi", 10, 20, 100, 80), camera.calls)
        self.assertIn(("read_ae_roi",), camera.calls)
        self.assertEqual((10, 20, 100, 80), controller.auto_exposure_roi)
        self.assertEqual((10, 20, 100, 80), controller.auto_exposure_roi_readback)
        self.assertTrue(controller.auto_exposure_roi_verified)
        self.assertEqual("CustomROI", controller.auto_exposure_roi_status()["mode"])

    def test_readback_mismatch_is_not_verified(self) -> None:
        camera = FaultAERectCamera(readback=(10, 20, 99, 80))
        controller = configured_controller(camera)
        controller._width, controller._height = 640, 480

        self.assertFalse(controller.set_auto_exposure_roi(10, 20, 100, 80))

        self.assertEqual((10, 20, 99, 80), controller.auto_exposure_roi_readback)
        self.assertFalse(controller.auto_exposure_roi_verified)
        self.assertEqual(
            "ReadbackMismatch",
            controller.auto_exposure_roi_status()["verification_status"],
        )

    def test_put_failure_is_reported_without_readback(self) -> None:
        camera = FaultAERectCamera(put_error=RuntimeError("put failed"))
        controller = configured_controller(camera)
        controller._width, controller._height = 640, 480

        self.assertFalse(controller.set_auto_exposure_roi(10, 20, 100, 80))

        self.assertNotIn(("read_ae_roi",), camera.calls)
        self.assertFalse(controller.auto_exposure_roi_verified)
        self.assertEqual(
            "WriteFailed",
            controller.auto_exposure_roi_status()["verification_status"],
        )

    def test_get_failure_is_reported(self) -> None:
        camera = FaultAERectCamera(get_error=RuntimeError("get failed"))
        controller = configured_controller(camera)
        controller._width, controller._height = 640, 480

        self.assertFalse(controller.set_auto_exposure_roi(10, 20, 100, 80))

        self.assertFalse(controller.auto_exposure_roi_verified)
        self.assertEqual(
            "ReadbackFailed",
            controller.auto_exposure_roi_status()["verification_status"],
        )

    def test_clear_roi_resets_explicit_full_current_image_rectangle(self) -> None:
        camera = FakeModeCamera()
        controller = configured_controller(camera)
        controller._width, controller._height = 640, 480
        controller.set_auto_exposure_roi(10, 20, 100, 80)
        camera.calls.clear()

        self.assertTrue(controller.reset_auto_exposure_roi())

        self.assertEqual(("ae_roi", 0, 0, 640, 480), camera.calls[0])
        self.assertEqual(("read_ae_roi",), camera.calls[1])
        self.assertEqual("FullImage", controller.auto_exposure_roi_status()["mode"])

    def test_resolution_change_replaces_old_roi_with_new_full_image(self) -> None:
        camera = FakeModeCamera()
        controller = resolution_controller(camera)
        self.assertTrue(controller.set_auto_exposure_roi(1, 1, 2, 2))
        camera.calls.clear()

        controller.set_resolution(0)

        self.assertIn(("ae_roi", 0, 0, 5, 4), camera.calls)
        self.assertEqual((0, 0, 5, 4), controller.auto_exposure_roi_readback)
        self.assertEqual("FullImage", controller.auto_exposure_roi_status()["mode"])

    def test_open_initializes_full_image_roi_before_continuous_ae(self) -> None:
        camera = _FakeMonoCamera()
        controller, errors = _open(camera)
        try:
            self.assertTrue(controller.is_open, errors)
            calls = camera.auto_exposure_calls
            self.assertLess(
                calls.index(("ae_roi", 0, 0, 3, 2)),
                calls.index(("ae_roi_readback",)),
            )
            self.assertLess(
                calls.index(("ae_roi_readback",)), calls.index(("enable", 1))
            )
            self.assertTrue(controller.auto_exposure_roi_verified)
        finally:
            controller.close_camera()

    def test_open_readback_mismatch_keeps_live_view_open_and_ae_off(self) -> None:
        class _MismatchMonoCamera(_FakeMonoCamera):
            def get_AEAuxRect(self) -> tuple[int, int, int, int]:
                self.auto_exposure_calls.append(("ae_roi_readback",))
                return 0, 0, 1, 1

        camera = _MismatchMonoCamera()
        controller, errors = _open(camera)
        try:
            self.assertTrue(controller.is_open, errors)
            self.assertFalse(controller.auto_exposure_roi_verified)
            self.assertEqual(SDKAutoExposureMode.MANUAL, controller.sdk_auto_exposure_mode)
            self.assertNotIn(("enable", 1), camera.auto_exposure_calls)
        finally:
            controller.close_camera()

    def test_disconnect_clears_local_state_without_post_close_sdk_call(self) -> None:
        camera = FaultAERectCamera()
        controller = configured_controller(camera)
        controller.close_camera()

        self.assertEqual(("close",), camera.calls[-1])
        self.assertIsNone(controller.auto_exposure_roi)
        self.assertIsNone(controller.auto_exposure_roi_readback)
        self.assertFalse(controller.auto_exposure_roi_verified)

    def test_manual_continuous_manual_continuous_and_once_reuse_roi(self) -> None:
        camera = FakeModeCamera()
        controller = configured_controller(camera)
        controller._width, controller._height = 640, 480
        self.assertTrue(controller.set_auto_exposure_roi(10, 20, 100, 80))
        roi_write_count = sum(call[0] == "ae_roi" for call in camera.calls)

        self.assertTrue(controller.enable_continuous_auto_exposure())
        self.assertTrue(controller.switch_to_manual_exposure())
        self.assertTrue(controller.enable_continuous_auto_exposure())
        controller.start_auto_exposure_once()

        self.assertEqual(
            roi_write_count, sum(call[0] == "ae_roi" for call in camera.calls)
        )
        self.assertEqual((10, 20, 100, 80), controller.auto_exposure_roi_readback)
        self.assertEqual(SDKAutoExposureMode.ONCE, controller.sdk_auto_exposure_mode)

    def test_roi_failure_while_continuous_leaves_sdk_ae_off(self) -> None:
        camera = FaultAERectCamera(readback=(0, 0, 1, 1))
        controller = configured_controller(camera)
        controller._width, controller._height = 640, 480
        controller._sdk_auto_exposure_mode = SDKAutoExposureMode.CONTINUOUS
        camera.auto_exposure_enable = 1

        self.assertFalse(controller.set_auto_exposure_roi(10, 20, 100, 80))

        self.assertEqual(0, camera.auto_exposure_enable)
        self.assertEqual(SDKAutoExposureMode.MANUAL, controller.sdk_auto_exposure_mode)

    def test_metering_mean_matches_whole_frame_or_verified_custom_roi(self) -> None:
        camera = _FakeMonoCamera(max_bit_depth=12)
        controller, errors = _open(camera)
        try:
            self.assertTrue(controller.is_open, errors)
            controller._alignment_verifier = None
            controller._raw_value_alignment = "right"
            controller._raw_value_alignment_source = "Test"
            values = np.array([[0, 100, 200], [300, 400, 500]], dtype=np.uint16)
            statuses: list[dict] = []
            controller.effective_dn_status_changed.connect(statuses.append)

            _install_frame(controller, values)
            controller._pull_live_frame()
            self.assertEqual(250.0, statuses[-1]["MeanEffectiveDN"])
            self.assertEqual(250.0, statuses[-1]["MeteringMeanEffectiveDN"])

            self.assertTrue(controller.set_auto_exposure_roi(1, 0, 2, 2))
            _install_frame(controller, values)
            controller._pull_live_frame()
            self.assertEqual(250.0, statuses[-1]["MeanEffectiveDN"])
            self.assertEqual(300.0, statuses[-1]["MeteringMeanEffectiveDN"])
        finally:
            controller.close_camera()

    def test_calibration_timeout_records_metering_mean_not_whole_frame_mean(self) -> None:
        camera = FakeModeCamera()
        controller = configured_controller(camera)
        controller._width, controller._height = 640, 480
        controller._device = SimpleNamespace(
            id="SERIAL-A",
            displayname="IUA8300KMB",
            model=SimpleNamespace(name="IUA8300KMB"),
        )
        controller._auto_exposure_roi_requested = (10, 20, 100, 80)
        controller._auto_exposure_roi_readback = (10, 20, 100, 80)
        controller._auto_exposure_roi_mode = "CustomROI"
        identity = AECalibrationIdentity(
            camera_model="IUA8300KMB",
            camera_serial="SERIAL-A",
            width=640,
            height=480,
            sensor_bit_depth=12,
            raw_value_alignment="right",
            ae_roi=(10, 20, 100, 80),
        )
        run = AECalibrationRun(identity, (40,), 16, 220)
        run.next_candidate()
        run.start_point(40)
        controller._ae_calibration_run = run
        controller._latest_mean_effective_dn = 100.0
        controller._latest_effective_dn_fraction = 100.0 / 4095
        controller._latest_metering_mean_effective_dn = 300.0
        controller._latest_metering_effective_dn_fraction = 300.0 / 4095

        with patch("gui.camera_controller.QTimer.singleShot"):
            controller._on_ae_calibration_timeout()

        self.assertEqual(300.0, run.points[0].mean_effective_dn)
        self.assertAlmostEqual(300.0 / 4095 * 100.0, run.points[0].mean_effective_dn_percent)

    def test_autoexposure_percent_remains_full_active_roi_average(self) -> None:
        self.assertEqual(0x4A, nncam.NNCAM_OPTION_AUTOEXPOSURE_PERCENT)
        source = Path(nncam.__file__).read_text(encoding="utf-8")
        self.assertIn('0 or 100: full roi average', source)
        camera = FakeModeCamera()
        controller = configured_controller(camera)
        controller._configure_sdk_auto_exposure_parameters(camera)
        self.assertIn(
            ("option", nncam.NNCAM_OPTION_AUTOEXPOSURE_PERCENT, 100),
            camera.calls,
        )


if __name__ == "__main__":
    unittest.main()
