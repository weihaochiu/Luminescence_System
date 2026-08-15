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


class _FakeHRESULT(Exception):
    def __init__(self, hr: int) -> None:
        super().__init__(f"HRESULT 0x{hr:08X}")
        self.hr = hr


class _FakeMonoCamera:
    """Compatibility fake: SDK readbacks intentionally need not echo writes."""

    def __init__(
        self,
        *,
        max_bit_depth: int | Exception = 12,
        unsupported_options: set[int] | None = None,
        readback_overrides: dict[int, int] | None = None,
        gamma_unsupported: bool = False,
        start_error: Exception | None = None,
        pull_error: Exception | None = None,
    ) -> None:
        self.max_bit_depth = max_bit_depth
        self.max_bit_depth_calls = 0
        self.options: list[tuple[int, int]] = []
        self.option_values = {
            nncam.NNCAM_OPTION_BYTEORDER: 1,
            nncam.NNCAM_OPTION_BITDEPTH: 0,
            nncam.NNCAM_OPTION_LINEAR: 1,
            nncam.NNCAM_OPTION_CURVE: 2,
            nncam.NNCAM_OPTION_RGB: 0,
            nncam.NNCAM_OPTION_RAW: 0,
            nncam.NNCAM_OPTION_ISP: 0,
            nncam.NNCAM_OPTION_PIXEL_FORMAT: nncam.NNCAM_PIXELFORMAT_RAW12,
        }
        self.unsupported_options = set(unsupported_options or ())
        self.readback_overrides = dict(readback_overrides or {})
        self.gamma_unsupported = gamma_unsupported
        self.gamma = 100
        self.start_error = start_error
        self.pull_error = pull_error
        self.pull_bits: list[int] = []
        self.auto_exposure_calls: list[tuple[str, int] | tuple[str]] = []
        self.auto_exposure_target = 99
        self.exposure_us = 1000
        self.gain_percent = 100
        self.exposure_writes: list[int] = []
        self.gain_writes: list[int] = []

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
        return self.readback_overrides.get(option, self.option_values.get(option, 0))

    def MaxBitDepth(self) -> int:
        self.max_bit_depth_calls += 1
        if isinstance(self.max_bit_depth, Exception):
            raise self.max_bit_depth
        return self.max_bit_depth

    def put_AutoExpoTarget(self, target: int) -> None:
        self.auto_exposure_calls.append(("target", target))
        self.auto_exposure_target = target

    def get_AutoExpoTarget(self) -> int:
        self.auto_exposure_calls.append(("target_readback",))
        return self.auto_exposure_target

    def put_AutoExpoEnable(self, enabled: int) -> None:
        self.auto_exposure_calls.append(("enable", enabled))

    def get_ExpTimeRange(self):
        return 100, 10_000, 100

    def get_ExpoAGainRange(self):
        return 100, 800, 100

    def get_ExpoTime(self) -> int:
        return self.exposure_us

    def get_ExpoAGain(self) -> int:
        return self.gain_percent

    def put_ExpoTime(self, value: int) -> None:
        self.exposure_writes.append(value)
        self.exposure_us = value

    def put_ExpoAGain(self, value: int) -> None:
        self.gain_writes.append(value)
        self.gain_percent = value

    def put_Gamma(self, gamma: int) -> None:
        if self.gamma_unsupported:
            raise _FakeHRESULT(nncam.E_INVALIDARG)
        self.gamma = gamma

    def get_Gamma(self) -> int:
        if self.gamma_unsupported:
            raise _FakeHRESULT(nncam.E_INVALIDARG)
        return self.gamma

    def StartPullModeWithCallback(self, _callback, _context) -> None:
        if self.start_error is not None:
            raise self.start_error

    def PullImageV4(self, _buffer, _still: int, bits: int, _pitch: int, _info) -> None:
        self.pull_bits.append(bits)
        if self.pull_error is not None:
            raise self.pull_error

    def Close(self) -> None:
        pass


def _mono_device(
    flags: int = nncam.NNCAM_FLAG_MONO | nncam.NNCAM_FLAG_RAW12,
) -> SimpleNamespace:
    resolution = SimpleNamespace(width=3, height=2)
    model = SimpleNamespace(
        name="IUA8300KMB",
        flag=flags,
        res=[resolution],
        preview=1,
    )
    return SimpleNamespace(id="FAKE-MONO", displayname="IUA8300KMB", model=model)


def _open(camera: _FakeMonoCamera, device: SimpleNamespace | None = None):
    controller = CameraController()
    errors: list[str] = []
    controller.error_occurred.connect(errors.append)
    with patch("gui.camera_controller.nncam.Nncam.Open", return_value=camera):
        controller.open_device(device or _mono_device())
    return controller, errors


def _install_frame(controller: CameraController, values: np.ndarray | None = None) -> np.ndarray:
    expected = (
        np.asarray(values, dtype="<u2")
        if values is not None
        else np.arange(6, dtype="<u2").reshape(2, 3)
    )
    padded = np.zeros((2, controller._pitch // 2), dtype="<u2")
    padded[:, :3] = expected
    controller._buffer = padded.tobytes()
    return expected


class MonoScientificCameraTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.app = ensure_qapplication()

    def test_byteorder_bgr_readback_is_ignored_for_mono_connection(self) -> None:
        camera = _FakeMonoCamera(
            readback_overrides={nncam.NNCAM_OPTION_BYTEORDER: 1}
        )
        controller, errors = _open(camera)
        try:
            self.assertTrue(controller.is_open, errors)
            self.assertEqual([("enable", 0)], camera.auto_exposure_calls)
            self.assertNotIn((nncam.NNCAM_OPTION_BYTEORDER, 0), camera.options)
            metadata = controller.capture_metadata()
            self.assertEqual(1, metadata["ByteOrderReadback"])
            self.assertTrue(metadata["ByteOrderIgnoredForMono"])
            self.assertTrue(metadata["CameraConnected"])
            self.assertFalse(metadata["ScientificMeasurementReady"])

            _install_frame(controller)
            controller._pull_live_frame()
            self.assertTrue(controller.capture_metadata()["ScientificMeasurementReady"])
        finally:
            controller.close_camera()

    def test_preferred_rgb4_path_pulls_uint16_hxw_frame(self) -> None:
        camera = _FakeMonoCamera(max_bit_depth=12)
        controller, errors = _open(camera)
        try:
            self.assertTrue(controller.is_open, errors)
            self.assertIn((nncam.NNCAM_OPTION_BITDEPTH, 1), camera.options)
            self.assertIn((nncam.NNCAM_OPTION_RGB, 4), camera.options)
            self.assertEqual(nncam.TDIBWIDTHBYTES(3 * 16), controller._pitch)

            expected = _install_frame(
                controller,
                np.array([[0, 1, 4095], [256, 1024, 2048]], dtype="<u2"),
            )
            frames: list[tuple[np.ndarray, QImage, int]] = []
            controller.scientific_frame_ready.connect(
                lambda array, image, sequence: frames.append((array, image, sequence))
            )
            controller._pull_live_frame()

            scientific, preview, sequence = frames[-1]
            self.assertEqual([16], camera.pull_bits)
            self.assertEqual(np.uint16, scientific.dtype)
            self.assertEqual(2, scientific.ndim)
            self.assertEqual((2, 3), scientific.shape)
            np.testing.assert_array_equal(expected, scientific)
            self.assertEqual(QImage.Format.Format_Grayscale8, preview.format())
            self.assertEqual(1, sequence)

            metadata = controller.capture_metadata()
            self.assertEqual(12, metadata["SensorBitDepth"])
            self.assertEqual("MaxBitDepth", metadata["BitDepthSource"])
            self.assertEqual(16, metadata["BitDepth"])
            self.assertEqual(16, metadata["ContainerBitDepth"])
            self.assertEqual("unknown", metadata["RawValueAlignment"])
            self.assertEqual(
                "SDKDoesNotReportGrey16Alignment",
                metadata["RawValueAlignmentSource"],
            )
            self.assertIsNone(metadata["MeanEffectiveDN"])
            self.assertEqual("uint16", metadata["ContainerDtype"])
            self.assertEqual("RGBOption4", metadata["ScientificFormatNegotiation"])
            self.assertTrue(metadata["ScientificFrameValidated"])
            self.assertTrue(metadata["ScientificMeasurementReady"])
        finally:
            controller.close_camera()

    def test_rgb4_invalidarg_uses_valid_pull_bits_16_fallback(self) -> None:
        camera = _FakeMonoCamera(unsupported_options={nncam.NNCAM_OPTION_RGB})
        controller, errors = _open(camera)
        try:
            self.assertTrue(controller.is_open, errors)
            expected = _install_frame(controller)
            frames: list[np.ndarray] = []
            controller.scientific_frame_ready.connect(
                lambda array, _image, _sequence: frames.append(array)
            )
            controller._pull_live_frame()

            metadata = controller.capture_metadata()
            self.assertEqual("PullBits16Fallback", metadata["ScientificFormatNegotiation"])
            self.assertFalse(metadata["RGBOption4Supported"])
            self.assertEqual([16], camera.pull_bits)
            np.testing.assert_array_equal(expected, frames[-1])
            self.assertTrue(metadata["ScientificMeasurementReady"])
        finally:
            controller.close_camera()

    def test_rgb4_readback_mismatch_uses_valid_pull_bits_16_fallback(self) -> None:
        camera = _FakeMonoCamera(
            readback_overrides={nncam.NNCAM_OPTION_RGB: 0}
        )
        controller, errors = _open(camera)
        try:
            self.assertTrue(controller.is_open, errors)
            _install_frame(controller)
            controller._pull_live_frame()

            metadata = controller.capture_metadata()
            self.assertEqual(0, metadata["RGBOptionReadback"])
            self.assertFalse(metadata["RGBOption4Supported"])
            self.assertEqual("PullBits16Fallback", metadata["ScientificFormatNegotiation"])
            self.assertTrue(metadata["ScientificMeasurementReady"])
        finally:
            controller.close_camera()

    def test_optional_isp_failures_do_not_override_valid_frame_authority(self) -> None:
        camera = _FakeMonoCamera(
            unsupported_options={
                nncam.NNCAM_OPTION_LINEAR,
                nncam.NNCAM_OPTION_CURVE,
            },
            gamma_unsupported=True,
        )
        controller, errors = _open(camera)
        try:
            self.assertTrue(controller.is_open, errors)
            _install_frame(controller)
            controller._pull_live_frame()

            metadata = controller.capture_metadata()
            self.assertFalse(metadata["LINEAROptionSupported"])
            self.assertFalse(metadata["CURVEOptionSupported"])
            self.assertFalse(metadata["GammaOptionSupported"])
            self.assertTrue(metadata["ScientificFrameValidated"])
            self.assertTrue(metadata["ScientificMeasurementReady"])
        finally:
            controller.close_camera()

    def test_max_bit_depth_failure_uses_raw12_capability(self) -> None:
        camera = _FakeMonoCamera(max_bit_depth=RuntimeError("readback failed"))
        with self.assertLogs("gui.camera_controller", level="WARNING") as captured:
            depth, source = CameraController._read_sensor_bit_depth(
                camera, nncam.NNCAM_FLAG_RAW12
            )
        self.assertEqual((12, "CapabilityFlagFallback"), (depth, source))
        self.assertIn("MaxBitDepth() failed", "\n".join(captured.output))

    def test_unknown_sensor_depth_is_not_assumed_to_be_16(self) -> None:
        camera = _FakeMonoCamera(max_bit_depth=RuntimeError("readback failed"))
        depth, source = CameraController._read_sensor_bit_depth(
            camera, nncam.NNCAM_FLAG_MONO
        )
        self.assertIsNone(depth)
        self.assertEqual("Unknown", source)

        controller, errors = _open(camera, _mono_device(nncam.NNCAM_FLAG_MONO))
        try:
            self.assertTrue(controller.is_open, errors)
            _install_frame(controller)
            controller._pull_live_frame()
            metadata = controller.capture_metadata()
            self.assertIsNone(metadata["SensorBitDepth"])
            self.assertEqual("Unknown", metadata["BitDepthSource"])
            self.assertEqual(16, metadata["ContainerBitDepth"])
            self.assertTrue(metadata["ScientificMeasurementReady"])
        finally:
            controller.close_camera()

    def test_pull_failure_marks_not_ready_and_emits_error_only_once(self) -> None:
        camera = _FakeMonoCamera(pull_error=_FakeHRESULT(nncam.E_FAIL))
        controller, errors = _open(camera)
        try:
            self.assertTrue(controller.is_open, errors)
            controller._pull_live_frame()
            controller._pull_live_frame()

            self.assertTrue(controller.is_open)
            self.assertFalse(controller.capture_metadata()["ScientificFrameValidated"])
            self.assertFalse(controller.capture_metadata()["ScientificMeasurementReady"])
            self.assertEqual(1, len(errors))
            self.assertIn("Stage: PullImageV4(bits=16)", errors[0])
            self.assertIn("SDK HRESULT: 0x80004005", errors[0])
        finally:
            controller.close_camera()

    def test_bitdepth_readback_mismatch_is_the_required_option_failure(self) -> None:
        camera = _FakeMonoCamera(
            readback_overrides={nncam.NNCAM_OPTION_BITDEPTH: 0}
        )
        controller, errors = _open(camera)
        self.assertFalse(controller.is_open)
        self.assertEqual(1, len(errors))
        self.assertIn("Stage: NNCAM_OPTION_BITDEPTH readback", errors[0])

    def test_start_pull_failure_reports_exact_stage_and_hresult(self) -> None:
        camera = _FakeMonoCamera(start_error=_FakeHRESULT(nncam.E_INVALIDARG))
        controller, errors = _open(camera)
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

    def test_known_alignment_frame_drives_mean_and_software_ae(self) -> None:
        camera = _FakeMonoCamera(max_bit_depth=12)
        controller, errors = _open(camera)
        try:
            self.assertTrue(controller.is_open, errors)
            controller._raw_value_alignment = "right"
            controller._raw_value_alignment_source = "TestAuthoritative"
            controller._software_auto_exposure.start_continuous()
            expected = _install_frame(
                controller, np.full((2, 3), 500, dtype=np.uint16)
            )
            statuses = []
            frames = []
            controller.effective_dn_status_changed.connect(statuses.append)
            controller.scientific_frame_ready.connect(
                lambda scientific, _image, _sequence: frames.append(scientific)
            )

            controller._pull_live_frame()

            self.assertEqual([2000], camera.exposure_writes)
            self.assertEqual([], camera.gain_writes)
            self.assertEqual(500.0, statuses[-1]["MeanEffectiveDN"])
            self.assertEqual(4095, statuses[-1]["EffectiveDNMax"])
            np.testing.assert_array_equal(expected, frames[-1])
            self.assertEqual(500, int(frames[-1][0, 0]))
        finally:
            controller.close_camera()


if __name__ == "__main__":
    unittest.main()
