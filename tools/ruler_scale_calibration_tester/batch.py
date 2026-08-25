from __future__ import annotations

import argparse
from collections import Counter
import json
import logging
from pathlib import Path
import statistics
import sys

from core.calibration import CalibrationService

from .image_loader import iter_images, load_image
from .repeatability import repeatability_summary


LOG = logging.getLogger(__name__)


def run_batch(
    input_path: str | Path,
    *,
    save_debug_failures: bool = False,
    debug_root: str | Path = Path("local") / "generated" / "debug" / "batch",
) -> dict[str, object]:
    paths = iter_images(input_path)
    service = CalibrationService()
    records: list[dict[str, object]] = []
    values: list[float] = []
    failure_reasons: Counter[str] = Counter()
    ruler_detected = 0
    ocr_usable = 0
    successful = 0
    for index, path in enumerate(paths, start=1):
        LOG.info("Batch ruler calibration image=%s index=%s total=%s", path, index, len(paths))
        try:
            image = load_image(path)
            result = service.analyze(image, input_source=str(path))
        except Exception as exc:
            failure_reasons["image_load_or_analysis_exception"] += 1
            records.append({"path": str(path), "success": False, "error": str(exc)})
            continue
        if result.ruler_detection is not None and result.ruler_detection.success:
            ruler_detected += 1
        if result.ocr_usable:
            ocr_usable += 1
        if result.success and result.pixels_per_mm is not None:
            successful += 1
            values.append(result.pixels_per_mm)
        else:
            failure_reasons.update(result.failure_reasons or ["unspecified_failure"])
            if save_debug_failures:
                service.save_debug_package(result, debug_root)
        records.append({"path": str(path), **result.to_dict()})
    repeatability = repeatability_summary(values)
    return {
        "images": len(paths),
        "ruler_detected": ruler_detected,
        "ocr_usable": ocr_usable,
        "calibration_successful": successful,
        "mean_pixels_per_mm": statistics.fmean(values) if values else None,
        "sd_pixels_per_mm": statistics.stdev(values) if len(values) > 1 else (0.0 if values else None),
        "cv_percent": repeatability["cv_percent"],
        "failure_reasons": dict(sorted(failure_reasons.items())),
        "records": records,
    }


def _print_summary(summary: dict[str, object]) -> None:
    print(f"Images                 {summary['images']:>6}")
    print(f"Ruler detected         {summary['ruler_detected']:>6}")
    print(f"OCR usable             {summary['ocr_usable']:>6}")
    print(f"Calibration successful {summary['calibration_successful']:>6}")
    print()
    print(f"Mean px/mm             {summary['mean_pixels_per_mm']}")
    print(f"SD                     {summary['sd_pixels_per_mm']}")
    print(f"CV %                   {summary['cv_percent']}")
    print()
    print("Failure reasons:")
    reasons = summary["failure_reasons"]
    if isinstance(reasons, dict) and reasons:
        for reason, count in reasons.items():
            print(f"- {reason}: {count}")
    else:
        print("- none")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Batch ruler scale calibration regression")
    parser.add_argument("input", help="Image file or directory")
    parser.add_argument("--json", dest="json_path", help="Write full JSON results")
    parser.add_argument("--save-debug-failures", action="store_true")
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    summary = run_batch(args.input, save_debug_failures=args.save_debug_failures)
    _print_summary(summary)
    if args.json_path:
        output = Path(args.json_path)
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    return 0 if int(summary["calibration_successful"]) == int(summary["images"]) else 1


if __name__ == "__main__":
    sys.exit(main())
