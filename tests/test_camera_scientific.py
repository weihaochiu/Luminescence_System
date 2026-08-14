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
    def __init__(self, *, max_bit_depth: int = 12) -> None:
        self.max_bit_depth = max_bit_depth
        self.max_bit_depth_calls = 0
        self.options: list[tuple[int, int]] = []
        self.pull_bits: list[int] = []

    def get_eSize(self) -> int:
        return 0

    def put_Option(self, option: int, value: int) -> None:
        self.options.append((option, value))

    def MaxBitDepth(self) -> int:
        self.max_bit_depth_calls += 1
        return self.max_bit_depth

    def put_AutoExpoEnable(self, _enabled: int) -> None:
        pass

    def put_Gamma(self, _gamma: int) -> None:
        pass

    def StartPullModeWithCallback(self, _callback, _context) -> None:
        pass

    def PullImageV4(self, _buffer, _still: int, bits: int, _pitch: int, _info) -> None:
        self.pull_bits.append(bits)

    def Close(self) -> None:
        pass


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
        finally:
            controller.close_camera()

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
