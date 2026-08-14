from __future__ import annotations

import csv
import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

import numpy as np
import tifffile

from gui.el_matrix_runner import ELMatrixRunner
from gui.main_window_measurement import _on_measurement_finished
from gui.measurement_output import sha256_file
from gui.pixel_csv_postprocessor import (
    PixelCSVPostprocessError,
    PixelCSVPostprocessor,
)
from gui.smu_control import SMUOwnership
from tests.test_el_matrix import _FakeHardware, _small_recipe


SAFE = {
    "smu_output_off": True,
    "routing_off": True,
    "white_light_off": True,
    "ownership_released": True,
    "ok": True,
}


def _capture(
    root: Path,
    name: str,
    measurement_type: str,
    value: int | np.ndarray,
    *,
    gain: int = 100,
    exposure: float = 10.0,
    repeat: int = 1,
    size: tuple[int, int] = (2, 1),
) -> Path:
    tiff = root / f"{name}.tiff"
    metadata = root / f"{name}.json"
    array = (
        np.asarray(value, dtype=np.uint16)
        if isinstance(value, np.ndarray)
        else np.full((size[1], size[0]), value, dtype=np.uint16)
    )
    tifffile.imwrite(tiff, array, photometric="minisblack")
    metadata.write_text(json.dumps({
        "MeasurementType": measurement_type,
        "Gain": gain,
        "Exposure": exposure,
        "RepeatIndex": repeat,
        "Resolution": f"{array.shape[1]}x{array.shape[0]}",
        "ScientificShape": list(array.shape),
        "RawTiffPath": str(tiff),
        "RawTiffSha256": sha256_file(tiff),
        "MetadataJsonPath": str(metadata),
        "PixelCsvPaths": {},
    }), encoding="utf-8")
    return metadata


def _snapshot(root: Path, *, raw: bool, corrected: bool, normalized: bool) -> None:
    (root / "measurement_snapshot.json").write_text(json.dumps({
        "output": {
            "export_pixel_csv": True,
            "pixel_csv_raw": raw,
            "pixel_csv_dark_corrected": corrected,
            "pixel_csv_exposure_normalized": normalized,
        }
    }), encoding="utf-8")


def _values(csv_path: Path, column: str) -> list[float]:
    with csv_path.open("r", newline="", encoding="utf-8-sig") as stream:
        return [float(row[column]) for row in csv.DictReader(stream)]


class PixelCSVPostprocessorTests(unittest.TestCase):
    def test_runner_never_calls_pixel_csv_during_hardware_measurement(self) -> None:
        recipe = _small_recipe(1)
        recipe.output.export_pixel_csv = True
        hardware = _FakeHardware()
        with tempfile.TemporaryDirectory() as directory, patch(
            "gui.measurement_output.save_pixel_csv_products"
        ) as save_pixel:
            result = ELMatrixRunner(
                recipe,
                hardware,
                directory,
                report_progress=lambda _item: None,
                is_cancel_requested=lambda: False,
            ).run()
        save_pixel.assert_not_called()
        self.assertTrue(result["hardware_measurement_completed"])
        self.assertEqual("safe_shutdown", hardware.events[-1])

    def test_postprocess_is_blocked_until_every_safe_shutdown_gate_is_verified(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            _snapshot(root, raw=True, corrected=False, normalized=False)
            _capture(root, "dark", "DARK", 1)
            unsafe = dict(SAFE, ownership_released=False)
            with self.assertRaisesRegex(PixelCSVPostprocessError, "blocked"):
                PixelCSVPostprocessor(root, unsafe).run()
            self.assertFalse((root / "postprocess_status.json").exists())
            self.assertFalse(list(root.glob("*.csv")))

    def test_shared_dark_matches_gain_exposure_and_repeat(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            _snapshot(root, raw=False, corrected=True, normalized=True)
            _capture(root, "dark_r1", "DARK", 1, repeat=1)
            _capture(root, "dark_r2", "DARK", 7, repeat=2)
            _capture(root, "el_r2", "EL", 10, repeat=2)
            status = PixelCSVPostprocessor(root, SAFE).run()
            corrected = root / "el_r2_pixels_dark_corrected.csv"
            normalized = root / "el_r2_pixels_exposure_normalized.csv"
            self.assertEqual([3.0, 3.0], _values(corrected, "DarkCorrectedDN"))
            self.assertEqual([0.3, 0.3], _values(normalized, "DN_per_ms"))
            self.assertEqual("completed", status["status"])
            metadata = json.loads((root / "el_r2.json").read_text(encoding="utf-8"))
            source = metadata["PixelCsvSources"]["DarkCorrected"]
            self.assertEqual(str(root / "dark_r2.tiff"), source["SharedDarkTiff"])
            self.assertEqual(sha256_file(root / "dark_r2.tiff"), source["SharedDarkTiffSha256"])
            self.assertEqual(
                sha256_file(corrected), metadata["PixelCsvHashes"]["DarkCorrected"]
            )
            with (root / "pixel_csv_manifest.csv").open(
                "r", newline="", encoding="utf-8-sig"
            ) as stream:
                manifest = list(csv.DictReader(stream))
            corrected_row = next(
                row for row in manifest
                if row["product"] == "DarkCorrected" and row["output_csv"] == str(corrected)
            )
            self.assertEqual(sha256_file(root / "el_r2.tiff"), corrected_row["source_sha256"])
            self.assertEqual(sha256_file(corrected), corrected_row["output_sha256"])

    def test_failure_preserves_raw_tiff_and_hardware_completion_can_remain_successful(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            _snapshot(root, raw=True, corrected=True, normalized=False)
            _capture(root, "dark", "DARK", 1, size=(1, 1))
            el_metadata_path = _capture(root, "el", "EL", 10, size=(2, 1))
            # Simulate corrupt metadata that claims a matching geometry; the
            # TIFF array validation must still catch the real shape mismatch.
            el_metadata = json.loads(el_metadata_path.read_text(encoding="utf-8"))
            el_metadata["Resolution"] = "1x1"
            el_metadata["ScientificShape"] = [1, 1]
            el_metadata_path.write_text(json.dumps(el_metadata), encoding="utf-8")
            before = sha256_file(root / "el.tiff")
            with self.assertRaises(PixelCSVPostprocessError):
                PixelCSVPostprocessor(root, SAFE).run()
            status = json.loads((root / "postprocess_status.json").read_text(encoding="utf-8"))
            self.assertEqual("partial", status["status"])
            self.assertEqual(before, sha256_file(root / "el.tiff"))
            self.assertTrue((root / "el_pixels_raw.csv").is_file())

        control = SimpleNamespace(
            ownership=SMUOwnership.IDLE,
            safe_shutdown=Mock(side_effect=AssertionError("duplicate shutdown")),
        )
        status_label = SimpleNamespace(setText=Mock())
        dialog = SimpleNamespace(
            set_postprocess_failed=Mock(), set_failed=Mock(), show=Mock()
        )
        window = SimpleNamespace(
            smu_manager=SimpleNamespace(control=control),
            emergency_manager=SimpleNamespace(is_active=False),
            status_message=status_label,
            _measurement_progress_dialog=dialog,
        )
        _on_measurement_finished(window, {
            "hardware_measurement_completed": True,
            "safe_shutdown": SAFE,
            "output_directory": "run",
            "captures": 2,
            "postprocess": {"status": "partial", "error": "CSV failed"},
        })
        control.safe_shutdown.assert_not_called()
        dialog.set_postprocess_failed.assert_called_once_with("CSV failed")
        status_label.setText.assert_called_with("硬體量測完成，但 Pixel CSV 後處理失敗")

    def test_resume_skips_hash_verified_csv(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            _snapshot(root, raw=True, corrected=True, normalized=False)
            _capture(root, "dark", "DARK", 2)
            _capture(root, "el", "EL", 9)
            processor = PixelCSVPostprocessor(root, SAFE)
            processor.run()
            paths = sorted(root.glob("*_pixels_*.csv"))
            before = {path: (path.stat().st_mtime_ns, sha256_file(path)) for path in paths}
            with patch("gui.pixel_csv_postprocessor.write_mono_array_csv_atomic") as writer:
                resumed = PixelCSVPostprocessor(root, SAFE).run()
            writer.assert_not_called()
            self.assertEqual("completed", resumed["status"])
            self.assertEqual(
                before,
                {path: (path.stat().st_mtime_ns, sha256_file(path)) for path in paths},
            )

    def test_raw_csv_exactly_preserves_uint16_dn_above_255(self) -> None:
        source = np.array([[0, 1, 255, 256, 1024, 2048, 4095]], dtype=np.uint16)
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            _snapshot(root, raw=True, corrected=False, normalized=False)
            _capture(root, "dark", "DARK", source)
            PixelCSVPostprocessor(root, SAFE).run()
            csv_path = root / "dark_pixels_raw.csv"
            with csv_path.open("r", newline="", encoding="utf-8-sig") as stream:
                reader = csv.DictReader(stream)
                self.assertEqual(["y", "x", "DN"], reader.fieldnames)
                actual = [int(row["DN"]) for row in reader]
            self.assertEqual(source.ravel().tolist(), actual)

    def test_dark_correction_preserves_negative_and_normalization_is_dn_per_ms(self) -> None:
        dark = np.array([[10, 30, 100]], dtype=np.uint16)
        source = np.array([[100, 20, 4095]], dtype=np.uint16)
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            _snapshot(root, raw=False, corrected=True, normalized=True)
            _capture(root, "dark", "DARK", dark, exposure=10.0)
            _capture(root, "el", "EL", source, exposure=10.0)
            PixelCSVPostprocessor(root, SAFE).run()
            self.assertEqual(
                [90.0, -10.0, 3995.0],
                _values(root / "el_pixels_dark_corrected.csv", "DarkCorrectedDN"),
            )
            self.assertEqual(
                [9.0, -1.0, 399.5],
                _values(root / "el_pixels_exposure_normalized.csv", "DN_per_ms"),
            )
            payload = json.loads((root / "el.json").read_text(encoding="utf-8"))
            self.assertEqual(
                "DN/ms", payload["PixelCsvQuantities"]["ExposureNormalized"]["Unit"]
            )

    def test_normal_completion_does_not_repeat_safe_shutdown(self) -> None:
        control = SimpleNamespace(
            ownership=SMUOwnership.IDLE,
            safe_shutdown=Mock(side_effect=AssertionError("duplicate shutdown")),
        )
        dialog = SimpleNamespace(set_complete=Mock(), set_failed=Mock())
        window = SimpleNamespace(
            smu_manager=SimpleNamespace(control=control),
            emergency_manager=SimpleNamespace(is_active=False),
            status_message=SimpleNamespace(setText=Mock()),
            _measurement_progress_dialog=dialog,
        )
        _on_measurement_finished(window, {
            "hardware_measurement_completed": True,
            "safe_shutdown": SAFE,
            "captures": 3,
            "postprocess": {"status": "completed", "total_files": 5},
        })
        control.safe_shutdown.assert_not_called()
        dialog.set_failed.assert_not_called()
        dialog.set_complete.assert_called_once_with(5, "量測與 Pixel CSV 後處理完成")


if __name__ == "__main__":
    unittest.main()
