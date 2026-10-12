from __future__ import annotations

from collections import defaultdict
import csv
import json
import math
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw

from tools.camera_linearity_qualification.capture_manifest import atomic_write_json, sha256_file
from tools.camera_linearity_qualification.regression import linear_regression, is_monotonic
from .messages import msg
from .calibration import LightCalibration
from .lux_reference import read_lux, required_levels


class ConditionStatistics:
    """Streaming ROI statistics; keep neither the full matrix nor all Light images."""

    def __init__(self) -> None:
        self.dark_count = 0
        self.dark_mean = None
        self.dark_m2 = None
        self.means: list[float] = []
        self.frame_rows: list[dict] = []
        self.profiles: list[np.ndarray] = []
        self.maximum = None

    def add_dark(self, roi: np.ndarray) -> None:
        data = np.asarray(roi, dtype=np.float64)
        self.dark_count += 1
        if self.dark_mean is None:
            self.dark_mean = data.copy()
            self.dark_m2 = np.zeros_like(data)
        else:
            delta = data - self.dark_mean
            self.dark_mean += delta / self.dark_count
            self.dark_m2 += delta * (data - self.dark_mean)

    def add_light(self, roi: np.ndarray, maximum: int, sequence: int) -> None:
        if self.dark_mean is None:
            raise ValueError("Light 分析需要 matching Dark")
        raw = np.asarray(roi, dtype=np.float64)
        corrected = raw - self.dark_mean
        mean = float(np.mean(corrected))
        self.maximum = maximum
        self.means.append(mean)
        # Remove fixed spatial gradients by comparing normalized profiles across repeats.
        profile = np.concatenate((np.mean(corrected, axis=1), np.mean(corrected, axis=0)))
        self.profiles.append(profile / max(abs(mean), 1.0))
        self.frame_rows.append({"sequence": sequence, "signal_dn": mean,
                                "raw_p99_dn": float(np.percentile(raw, 99)),
                                "near_saturation_fraction": float(np.mean(raw >= maximum * .98)),
                                "negative_fraction": float(np.mean(corrected < 0))})

    def result(self) -> dict:
        if not self.means:
            raise ValueError("沒有 Light frames")
        signal = float(np.mean(self.means))
        std = float(np.std(self.means, ddof=1)) if len(self.means) > 1 else None
        sigma = float(np.sqrt(np.mean(self.dark_m2 / (self.dark_count - 1)))) if self.dark_count > 1 else None
        profiles = np.asarray(self.profiles)
        band = float(np.max(np.std(profiles, axis=0, ddof=1)) * 100) if len(profiles) > 1 else None
        return {"signal_dn": signal, "light_count": len(self.means), "dark_count": self.dark_count,
                "repeat_cv_percent": std / abs(signal) * 100 if std is not None and abs(signal) > 1e-12 else None,
                "dark_noise_dn": sigma, "dark_mean_dn": float(np.mean(self.dark_mean)),
                "snr": signal / max(sigma, 1e-6) if sigma is not None else None,
                "near_saturation_fraction": max(x["near_saturation_fraction"] for x in self.frame_rows),
                "temporal_band_percent": band, "effective_dn_max": self.maximum,
                "frames": self.frame_rows}


def fit_rows(rows: list[dict], x_field: str, thresholds: dict) -> dict:
    included, excluded = [], []
    for row in rows:
        reasons = []
        x = row.get(x_field)
        if x is None or not math.isfinite(x) or x <= 0:
            reasons.append("MISSING_MEASURED_INTENSITY" if x_field == "relative_intensity" else "INVALID_EXPOSURE")
        if row.get("snr") is None or row["snr"] < thresholds["minimum_snr"]:
            reasons.append("LOW_SNR_OR_MISSING_DARK_NOISE")
        if row["near_saturation_fraction"] > 0:
            reasons.append("NEAR_SATURATION")
        if not math.isfinite(row["signal_dn"]) or row["signal_dn"] <= 0:
            reasons.append("NONPOSITIVE_OR_INVALID_SIGNAL")
        if reasons:
            excluded.append({"pwm_level": row["pwm_level"], "exposure_ms": row["exposure_ms"], "reasons": reasons})
        else:
            included.append(row)
    included.sort(key=lambda x: x[x_field])
    result = {"status": "INSUFFICIENT_EVIDENCE", "included_count": len(included), "excluded": excluded,
              "x_field": x_field, "r2": None, "max_residual_percent": None, "slope": None}
    if len({row[x_field] for row in included}) < thresholds["minimum_points"]:
        return result
    fit = linear_regression(np.array([x[x_field] for x in included]), np.array([x["signal_dn"] for x in included]))
    stability = all(x.get("repeat_cv_percent") is not None and x["repeat_cv_percent"] <= thresholds["cv_percent"]
                    and x.get("temporal_band_percent") is not None and x["temporal_band_percent"] <= thresholds["band_percent"]
                    and x["light_count"] >= 5 and x["dark_count"] >= 5 for x in included)
    passed = fit.slope > 0 and fit.r2 >= thresholds["r2"] and fit.max_absolute_residual_percent <= thresholds["residual_percent"] and is_monotonic(np.array([x["signal_dn"] for x in included]), 2)
    result.update({"status": ("PASS" if passed else "FAIL") if stability else "UNSTABLE_OR_INSUFFICIENT_REPEATS",
                   "r2": fit.r2, "max_residual_percent": fit.max_absolute_residual_percent,
                   "slope": fit.slope, "intercept": fit.intercept, "stability_pass": stability})
    exposure_span = math.log2(max(row[x_field] for row in included) / min(row[x_field] for row in included))
    signal_span = math.log2(max(row["signal_dn"] for row in included) / min(row["signal_dn"] for row in included))
    coverage = signal_span + 1e-9 >= thresholds.get("minimum_signal_span_ev", 0)
    if x_field == "actual_exposure_ms":
        coverage &= exposure_span + 1e-9 >= thresholds.get("minimum_exposure_span_ev", 0)
    result.update({"x_span_ev": exposure_span, "signal_span_ev": signal_span, "coverage_pass": bool(coverage)})
    if not coverage:
        result["status"] = "INSUFFICIENT_RANGE_COVERAGE"
    return result


DEFAULT_THRESHOLDS = {"minimum_points": 5, "minimum_snr": 5.0, "r2": .999,
                      "residual_percent": 2.0, "cv_percent": 2.0, "band_percent": 2.0}


def write_report(session: str | Path) -> dict:
    root = Path(session)
    if root.name == "SUMMARY":
        root = root.parent
    summary_dir = root / "SUMMARY"
    manifest = json.loads((summary_dir / "capture_manifest.json").read_text(encoding="utf-8"))
    statistics_path = summary_dir / "condition_statistics.json"
    if not manifest.get("statistics_sha256") or sha256_file(statistics_path) != manifest["statistics_sha256"]:
        raise ValueError("統計資料 SHA-256 不一致或未完成保存")
    missing_images = 0
    for frame in manifest["frames"]:
        path = root / frame["tiff"]
        if not path.exists():
            missing_images += 1
        elif sha256_file(path) != frame["sha256"]:
            raise ValueError(f"原始影像 SHA-256 不一致：{path}")
    snapshot_path = summary_dir / "measurement_snapshot.json"
    if sha256_file(snapshot_path) != manifest["snapshot_sha256"]:
        raise ValueError("測試快照 SHA-256 不一致")
    snapshot = json.loads(snapshot_path.read_text(encoding="utf-8"))
    rows = json.loads(statistics_path.read_text(encoding="utf-8"))
    thresholds = snapshot["analysis_thresholds"]
    deferred = read_lux(summary_dir, manifest)
    if deferred:
        reference = LightCalibration.from_dict(deferred["reference"]["calibration"])
        if reference.snapshot()["sha256"] != deferred["reference"]["sha256"] or reference.channel != snapshot["plan"]["channel"] or reference.unit.strip().lower() != "lux":
            raise ValueError("Deferred LUX calibration hash/channel mismatch")
        reference.require_levels(required_levels(rows))
        for row in rows:
            row["relative_intensity"] = reference.relative(row["pwm_level"])
            row["measured_intensity"] = reference.readings.get(row["pwm_level"])
            row["lux_reference_sha256"] = deferred["record_sha256"]
    exposure_groups, intensity_groups, gain_groups = defaultdict(list), defaultdict(list), defaultdict(list)
    for row in rows:
        exposure_groups[(row["pwm_level"], row["gain"])].append(row)
        intensity_groups[(row["gain"], row["actual_exposure_ms"])].append(row)
        gain_groups[(row["pwm_level"], row["actual_exposure_ms"])].append(row)
    exposure = [{"pwm_level": level, "gain": gain, **fit_rows(group, "actual_exposure_ms", thresholds)}
                for (level, gain), group in sorted(exposure_groups.items())]
    intensity = [{"gain": gain, "exposure_ms": time, **fit_rows(group, "relative_intensity", thresholds)}
                 for (gain, time), group in sorted(intensity_groups.items())]
    gain_response = []
    for (level, time), group in sorted(gain_groups.items()):
        baseline = min(group, key=lambda r: r["gain"])
        for row in group:
            gain_response.append({"pwm_level": level, "exposure_ms": time, "gain": row["gain"],
                                  "baseline_gain": baseline["gain"],
                                  "response_ratio": row["signal_dn"] / baseline["signal_dn"] if baseline["signal_dn"] > 0 and not row["near_saturation_fraction"] and not baseline["near_saturation_fraction"] else None})
    limitations = ["手動光強表是使用者量測參考；不是軟體自行認證的可追溯光學校正。",
                   "PWM 頻率／光學波形與相機相位未由硬體同步驗證；影像分析無法唯一判定不穩定來源。",
                   "temporal_band_percent 只檢查重複影像間的條紋變化，固定條紋仍須人工檢查。",
                   "本工具不產生正式 EMVA 1288 或 production PASS profile。"]
    if snapshot["plan"]["retention"] != "full":
        limitations.append("影像保存不完整；summary-only 無法重算影像，ROI 模式不能重新分析 ROI 外區域。")
    if manifest["phase"] != "COMPLETE":
        limitations.append("測試取消或失敗，結果僅涵蓋已完成條件。")
    if snapshot["synthetic_dataset"]:
        limitations.append("模擬資料不代表硬體已驗收。")
    if missing_images:
        limitations.append(f"{missing_images} 張原始影像已移走或刪除；此報告使用保存的數值統計。")
    summary = {"schema_version": "1.0", "scope": "GSP4H camera/source empirical qualification",
               "run_phase": manifest["phase"], "calibration_sha256": snapshot["light_calibration"]["sha256"],
               "retention": snapshot["plan"]["retention"], "condition_count": len(rows),
               "exposure_linearity": exposure, "measured_intensity_linearity": intensity,
               "profile_usable_for_production": False, "limitations": limitations}
    needed = required_levels(rows)
    waiting = bool(needed and any(row.get("relative_intensity") is None for row in rows if row["pwm_level"] in needed))
    summary.update({"capture_strategy": snapshot.get("capture_strategy", "manual"),
                    "analysis_state": "AWAITING_LUX" if waiting else "ANALYZED",
                    "required_pwm_levels": list(needed), "light_channel": snapshot["plan"]["channel"],
                    "lux_reference_sha256": deferred["record_sha256"] if deferred else None})
    summary["requested_gains"] = snapshot["plan"]["gains"]
    summary["gains_without_usable_exposure_curve"] = [gain for gain in summary["requested_gains"]
        if not any(group["gain"] == gain and group["included_count"] >= thresholds["minimum_points"]
                   and group.get("coverage_pass", True) for group in exposure)]
    gain_overview = []
    for gain in summary["requested_gains"]:
        points = [row for row in rows if row["gain"] == gain]
        curves = [group for group in exposure if group["gain"] == gain]
        gain_overview.append({"gain": gain, "condition_count": len(points),
                              "pass_exposure_curves": sum(group["status"] == "PASS" for group in curves),
                              "failed_exposure_curves": sum(group["status"] == "FAIL" for group in curves),
                              "limited_exposure_curves": sum(group["status"] not in ("PASS", "FAIL") for group in curves),
                              "median_dark_noise_dn": float(np.median([row["dark_noise_dn"] for row in points if row.get("dark_noise_dn") is not None])) if any(row.get("dark_noise_dn") is not None for row in points) else None,
                              "signal_dn_min": min((row["signal_dn"] for row in points), default=None),
                              "signal_dn_max": max((row["signal_dn"] for row in points), default=None)})
    summary["per_gain_overview"] = gain_overview
    planning_path = summary_dir / "automatic_planning.json"
    if planning_path.exists():
        summary["automatic_planning"] = json.loads(planning_path.read_text(encoding="utf-8"))
    if waiting:
        limitations.append("LUX 尚未填入；曝光線性可分析，實測光強線性仍待補齊。")
    out = summary_dir / "ANALYSIS"
    out.mkdir(exist_ok=True)
    atomic_write_json(out / "analysis_summary.json", summary)
    for name, data in (("conditions", [{k: v for k, v in row.items() if k != "frames"} for row in rows]),
                       ("exposure_linearity", exposure), ("measured_intensity_linearity", intensity), ("gain_response", gain_response), ("gain_overview", gain_overview),
                       ("frame_statistics", [{"pwm_level": row["pwm_level"], "gain": row["gain"], "exposure_ms": row["exposure_ms"], **frame} for row in rows for frame in row["frames"]])):
        fields = list(dict.fromkeys(k for row in data for k in row))
        with (out / f"{name}.csv").open("w", encoding="utf-8-sig", newline="") as stream:
            writer = csv.DictWriter(stream, fieldnames=fields)
            writer.writeheader()
            writer.writerows([{k: json.dumps(v, ensure_ascii=False) if isinstance(v, (dict, list)) else v for k, v in row.items()} for row in data])
    report = ["# GSP-4H 光源／相機線性度測試", "", f"測試狀態：{manifest['phase']}；完成條件：{len(rows)}；分析狀態：{summary['analysis_state']}", "",
              "曝光與光強回歸分開分析；Gain 曲線為實測比例。PASS 僅適用於此表中的測試條件。", "",
              "| 分析 | PWM / Gain / 曝光 | 狀態 | R² | 最大殘差 % |", "|---|---|---|---|---|"]
    for group_name, groups in (("曝光", exposure), ("實測相對光強", intensity)):
        for group in groups:
            label = msg(f"PWM {group.get('pwm_level', '多等級')} / G{group['gain']} / {group.get('exposure_ms', '多曝光')} ms",
                        f"PWM {group.get('pwm_level', 'multiple')} / G{group['gain']} / {group.get('exposure_ms', 'multiple')} ms")
            report.append(f"| {group_name} | {label} | {group['status']} | {group['r2']} | {group['max_residual_percent']} |")
    report.extend(["", "## 限制", "", *[f"- {item}" for item in limitations], "", "門檻：", json.dumps(thresholds, ensure_ascii=False)])
    report.extend(["", "## Gain 比較", "", "| Gain % | 條件數 | 曝光曲線 PASS / FAIL / 受限 | Dark noise DN（中位數） |", "|---|---|---|---|"])
    for group in gain_overview:
        report.append(f"| {group['gain']} | {group['condition_count']} | {group['pass_exposure_curves']} / {group['failed_exposure_curves']} / {group['limited_exposure_curves']} | {group['median_dark_noise_dn']} |")
    (out / "LIGHT_LINEARITY_REPORT.md").write_text("\n".join(report), encoding="utf-8")
    for (level, gain), group in exposure_groups.items():
        _plot(out / f"exposure_PWM{level}_G{gain}.png", group, "actual_exposure_ms", f"PWM {level}, G{gain}: signal / exposure ms")
    for (gain, time), group in intensity_groups.items():
        _plot(out / f"intensity_G{gain}_E{time:g}.png", group, "relative_intensity", f"G{gain}, E{time:g}ms: signal / measured relative intensity")
    return summary


def _plot(path: Path, rows: list[dict], x_field: str, title: str) -> None:
    pairs = sorted((row[x_field], row["signal_dn"]) for row in rows if row.get(x_field) is not None)
    image = Image.new("RGB", (900, 550), "white")
    draw = ImageDraw.Draw(image)
    draw.text((35, 15), title, fill="black")
    draw.line((80, 50, 80, 480, 840, 480), fill="black", width=2)
    if pairs:
        xs, ys = zip(*pairs)
        low_x, high_x, low_y, high_y = min(xs), max(xs), min(0, min(ys)), max(ys)
        coords = [(80 + (x - low_x) / max(high_x - low_x, 1e-9) * 760,
                   480 - (y - low_y) / max(high_y - low_y, 1e-9) * 420) for x, y in pairs]
        if len(coords) > 1:
            draw.line(coords, fill="#1769aa", width=2)
        for x, y in coords:
            draw.ellipse((x - 4, y - 4, x + 4, y + 4), fill="#1769aa")
        draw.text((80, 495), f"X {low_x:g} ... {high_x:g}; Y {low_y:g} ... {high_y:g} DN", fill="black")
    image.save(path)
