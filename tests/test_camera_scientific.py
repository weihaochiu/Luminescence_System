from __future__ import annotations

import unittest
from types import SimpleNamespace
from unittest.mock import patch

import numpy as np
from PySide6.QtGui import QImage

from gui.camera_controller import CameraController
from gui.measurement_output import scientific_to_visualization
from gui.sdk import nncam
from tests.qt_test_utils import ensure_qapplication


class _FakeMonoCamera:
    def __init__(
        self,
        *,
        max_bit_depth: int = 12,
        unsupported_options: set[int] | None = None,
        gamma_unsupported: bool = False,
        start_error: Exception | None = None,
    ) -> None:
        self.max_bit_depth = max_bit_depth
        self.max_bit_depth_calls = 0
        self.options: list[tuple[int, int]] = []
        self.option_values = {
            nncam.NNCAM_OPTION_RAW: 0,
            nncam.NNCAM_OPTION_ISP: 0,
        }
        self.unsupported_options = set(unsupported_options or ())
        self.gamma_unsupported = gamma_unsupported
        self.start_error = start_error
        self.pull_bits: list[int] = []

    def get_eSize(self) -> int:
        return 0

    def put_Option(self, option: int, value: int) -> None:
        if option in self.unsupported_options:
            raise _FakeHRESULT(nncam.E_INVALIDARG)
        self.options.append((option, value))
        self.option_values[option] = value

    def get_Option(self, option: int) -> int:
        if option in self.unsupported_options:
            raise _FakeHRESULT(nncam.E_INVALIDARG)
        return self.option_values.get(option, 0)

    def MaxBitDepth(self) -> int:
        self.max_bit_depth_calls += 1
        return self.max_bit_depth

    def put_AutoExpoEnable(self, _enabled: int) -> None:
        pass

    def put_Gamma(self, _gamma: int) -> None:
        if self.gamma_unsupported:
            raise _FakeHRESULT(nncam.E_INVALIDARG)
        self.gamma = _gamma

    def get_Gamma(self) -> int:
        if self.gamma_unsupported:
            raise _FakeHRESULT(nncam.E_INVALIDARG)
        return self.gamma

    def StartPullModeWithCallback(self, _callback, _context) -> None:
        if self.start_error is not None:
            raise self.start_error

    def PullImageV4(self, _buffer, _still: int, bits: int, _pitch: int, _info) -> None:
        self.pull_bits.append(bits)

    def Close(self) -> None:
        pass


class _FakeHRESULT(Exception):
    def __init__(self, hr: int) -> None:
        super().__init__(f"HRESULT 0x{hr:08X}")
        self.hr = hr


def _mono_device() -> SimpleNamespace:
    resolution = SimpleNamespace(width=3, height=2)
    model = SimpleNamespace(
        name="IUA8300KMB",
        flag=nncam.NNCAM_FLAG_MONO | nncam.NNCAM_FLAG_RAW12,
        res=[resolution],
        preview=1,
    )
    return SimpleNamespace(id="FAKE-MONO", displayname="IUA8300KMB", model=model)


class MonoScientificCameraTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.app = ensure_qapplication()

    def test_mono_scientific_branch_uses_uint16_grayscale(self) -> None:
        camera = _FakeMonoCamera(max_bit_depth=12)
        controller = CameraController()
        errors: list[str] = []
        controller.error_occurred.connect(errors.append)
        with patch("gui.camera_controller.nncam.Nncam.Open", return_value=camera):
            controller.open_device(_mono_device())
        try:
            self.assertTrue(controller.is_open, errors)
            self.assertEqual(1, camera.max_bit_depth_calls)
            self.assertIn((nncam.NNCAM_OPTION_BITDEPTH, 1), camera.options)
            self.assertIn((nncam.NNCAM_OPTION_RGB, 4), camera.options)
            self.assertIn((nncam.NNCAM_OPTION_LINEAR, 0), camera.options)
            self.assertIn((nncam.NNCAM_OPTION_CURVE, 0), camera.options)
            self.assertEqual(nncam.TDIBWIDTHBYTES(3 * 16), controller._pitch)

            metadata = controller.capture_metadata()
            self.assertEqual(12, metadata["SensorBitDepth"])
            self.assertEqual("MaxBitDepth", metadata["BitDepthSource"])
            self.assertEqual("MONO16", metadata["PixelFormat"])
            self.assertEqual(1, metadata["Channels"])
            self.assertEqual(16, metadata["ContainerBitDepth"])
            self.assertEqual("uint16", metadata["ContainerDtype"])
            self.assertEqual("unknown", metadata["RawValueAlignment"])
            self.assertEqual("RGBOption4", metadata["ScientificFormatNegotiation"])
            self.assertTrue(metadata["RGBOption4Supported"])

            expected = np.array([[0, 1, 4095], [256, 1024, 2048]], dtype="<u2")
            padded = np.zeros((2, controller._pitch // 2), dtype="<u2")
            padded[:, :3] = expected
            controller._buffer = padded.tobytes()
            controller._raw_value_alignment = "right"
            frames: list[tuple[np.ndarray, QImage, int]] = []
            controller.scientific_frame_ready.connect(
                lambda array, image, sequence: frames.append((array, image, sequence))
            )
            controller._pull_live_frame()

            self.assertEqual([16], camera.pull_bits)
            self.assertNotIn(48, camera.pull_bits)
            scientific, preview, sequence = frames[-1]
            self.assertEqual(np.uint16, scientific.dtype)
            self.assertEqual(2, scientific.ndim)
            self.assertEqual((2, 3), scientific.shape)
            np.testing.assert_array_equal(expected, scientific)
            self.assertEqual(QImage.Format.Format_Grayscale8, preview.format())
            self.assertEqual(1, sequence)
            self.assertTrue(controller.capture_metadata()["ScientificFrameValidated"])
            self.assertTrue(controller.capture_metadata()["ScientificMeasurementReady"])
        finally:
            controller.close_camera()

    def test_rgb4_invalidarg_uses_pull_bits_16_fallback(self) -> None:
        camera = _FakeMonoCamera(
            unsupported_options={nncam.NNCAM_OPTION_RGB}
        )
        controller = CameraController()
        errors: list[str] = []
        controller.error_occurred.connect(errors.append)
        with patch("gui.camera_controller.nncam.Nncam.Open", return_value=camera):
            controller.open_device(_mono_device())
        try:
            self.assertTrue(controller.is_open, errors)
            metadata = controller.capture_metadata()
            self.assertEqual("MONO16", metadata["ScientificPixelFormat"])
            self.assertEqual(
                "PullBits16Fallback", metadata["ScientificFormatNegotiation"]
            )
            self.assertFalse(metadata["RGBOption4Supported"])

            expected = np.arange(6, dtype="<u2").reshape(2, 3)
            padded = np.zeros((2, controller._pitch // 2), dtype="<u2")
            padded[:, :3] = expected
            controller._buffer = padded.tobytes()
            frames: list[np.ndarray] = []
            controller.scientific_frame_ready.connect(
                lambda array, _image, _sequence: frames.append(array)
            )
            controller._pull_live_frame()

            self.assertEqual([16], camera.pull_bits)
            self.assertEqual(np.uint16, frames[-1].dtype)
            self.assertEqual((2, 3), frames[-1].shape)
            np.testing.assert_array_equal(expected, frames[-1])
            self.assertTrue(controller.capture_metadata()["ScientificMeasurementReady"])
        finally:
            controller.close_camera()

    def test_linear_unsupported_keeps_connection_but_blocks_scientific_ready(self) -> None:
        camera = _FakeMonoCamera(
            unsupported_options={nncam.NNCAM_OPTION_LINEAR}
        )
        controller = CameraController()
        errors: list[str] = []
        controller.error_occurred.connect(errors.append)
        with patch("gui.camera_controller.nncam.Nncam.Open", return_value=camera):
            controller.open_device(_mono_device())
        try:
            self.assertTrue(controller.is_open, errors)
            metadata = controller.capture_metadata()
            self.assertFalse(metadata["LINEAROptionSupported"])
            self.assertFalse(metadata["ScientificISPBypassed"])
            self.assertFalse(metadata["ScientificMeasurementReady"])
        finally:
            controller.close_camera()

    def test_curve_unsupported_keeps_connection_but_blocks_scientific_ready(self) -> None:
        camera = _FakeMonoCamera(
            unsupported_options={nncam.NNCAM_OPTION_CURVE}
        )
        controller = CameraController()
        errors: list[str] = []
        controller.error_occurred.connect(errors.append)
        with patch("gui.camera_controller.nncam.Nncam.Open", return_value=camera):
            controller.open_device(_mono_device())
        try:
            self.assertTrue(controller.is_open, errors)
            metadata = controller.capture_metadata()
            self.assertFalse(metadata["CURVEOptionSupported"])
            self.assertFalse(metadata["ScientificISPBypassed"])
            self.assertFalse(metadata["ScientificMeasurementReady"])
        finally:
            controller.close_camera()

    def test_gamma_unsupported_keeps_connection_but_blocks_scientific_ready(self) -> None:
        camera = _FakeMonoCamera(gamma_unsupported=True)
        controller = CameraController()
        errors: list[str] = []
        controller.error_occurred.connect(errors.append)
        with patch("gui.camera_controller.nncam.Nncam.Open", return_value=camera):
            controller.open_device(_mono_device())
        try:
            self.assertTrue(controller.is_open, errors)
            metadata = controller.capture_metadata()
            self.assertFalse(metadata["GammaOptionSupported"])
            self.assertFalse(metadata["ScientificISPBypassed"])
            self.assertFalse(metadata["ScientificMeasurementReady"])
        finally:
            controller.close_camera()

    def test_start_pull_failure_reports_exact_stage_and_hresult(self) -> None:
        camera = _FakeMonoCamera(start_error=_FakeHRESULT(nncam.E_INVALIDARG))
        controller = CameraController()
        errors: list[str] = []
        controller.error_occurred.connect(errors.append)
        with patch("gui.camera_controller.nncam.Nncam.Open", return_value=camera):
            controller.open_device(_mono_device())

        self.assertFalse(controller.is_open)
        self.assertEqual(1, len(errors))
        self.assertIn("Stage: StartPullModeWithCallback", errors[0])
        self.assertIn("SDK HRESULT: 0x80070057", errors[0])

    def test_preview_is_uint8_and_does_not_modify_scientific_source(self) -> None:
        source = np.array([[0, 1, 255, 256, 1024, 2048, 4095]], dtype=np.uint16)
        before = source.copy()
        preview = scientific_to_visualization(source, 12, "right")
        display = np.asarray(preview)
        self.assertEqual(np.uint8, display.dtype)
        np.testing.assert_array_equal(before, source)
        self.assertEqual(255, int(display[0, -1]))

    def test_max_bit_depth_failure_logs_and_uses_capability_fallback(self) -> None:
        camera = _FakeMonoCamera()
        camera.MaxBitDepth = lambda: (_ for _ in ()).throw(RuntimeError("readback failed"))
        with self.assertLogs("gui.camera_controller", level="WARNING") as captured:
            depth, source = CameraController._read_sensor_bit_depth(
                camera, nncam.NNCAM_FLAG_RAW12
            )
        self.assertEqual((12, "CapabilityFlagFallback"), (depth, source))
        self.assertIn("MaxBitDepth() failed", "\n".join(captured.output))


if __name__ == "__main__":
    unittest.main()
