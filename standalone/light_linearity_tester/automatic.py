from __future__ import annotations

from dataclasses import asdict, dataclass
import math
import json
import os
import shutil
from time import monotonic

import numpy as np

from tools.camera_linearity_qualification.capture_manifest import atomic_write_json
from tools.camera_linearity_qualification.capture_runner import CaptureProgress
from .analysis import ConditionStatistics, DEFAULT_THRESHOLDS
from .capture import LightCaptureRunner
from .messages import msg


REQUESTED_GAINS = (100, 200, 300, 400, 500, 1000, 2000, 3000, 5000)


@dataclass(frozen=True)
class AutomaticSettings:
    gains: tuple[int, ...] = REQUESTED_GAINS
    minimum_points: int = 5
    minimum_span_ev: float = 2.0
    formal_step_ev: float = .5
    pwm_probe_limit: int = 21
    probe_condition_limit: int = 1500
    ae_iterations: int = 8
    boundary_steps: int = 20
    target_fraction: float = .35
    noise_floor_dn: float = .5
    minimum_exposure_ms: float = .03
    maximum_exposure_ms: float = 15000.

    def validate(self):
        if not self.gains or any(type(g) is not int or g < 1 for g in self.gains) or len(set(self.gains)) != len(self.gains):
            raise ValueError("Invalid automatic Gain list")
        if self.minimum_points < 5 or self.minimum_span_ev <= 0 or not 0 < self.formal_step_ev <= 1:
            raise ValueError("Automatic coverage requires at least 5 points and a positive EV span")
        if not 0 < self.minimum_exposure_ms < self.maximum_exposure_ms <= 15000:
            raise ValueError("Invalid automatic exposure bounds")
        if self.pwm_probe_limit < 5 or self.probe_condition_limit < 1 or self.ae_iterations < 1 or self.boundary_steps < 1:
            raise ValueError("Invalid automatic search budget")
        if not math.isfinite(self.noise_floor_dn) or self.noise_floor_dn <= 0:
            raise ValueError("Invalid effective DN noise floor")


def exposure_points(low: float, high: float, settings: AutomaticSettings) -> tuple[float, ...]:
    """Uniform EV spacing inside measured limits, without forcing narrow-range PASS."""
    if low <= 0 or high <= low:
        return ()
    width = math.log2(high / low)
    if width + 1e-9 < settings.minimum_span_ev:
        return ()
    count = max(settings.minimum_points, math.ceil(width / settings.formal_step_ev - 1e-9) + 1)
    values = tuple(dict.fromkeys(round(low * 2 ** (i * width / (count - 1)), 3) for i in range(count)))
    return values if len(values) >= settings.minimum_points else ()


def next_pwm(observations: dict[int, dict]) -> int | None:
    """Refine widest intervals around usable data; never optimize a regression score."""
    levels = [0, *sorted(observations), 256]
    choices = []
    for left, right in zip(levels, levels[1:]):
        middle = (left + right) // 2
        if not 1 <= middle <= 255 or middle in observations or right - left < 2:
            continue
        a = observations.get(left, {}).get("status", "LOW")
        b = observations.get(right, {}).get("status", "HIGH")
        priority = 4 if a == "VALID" and b == "VALID" else 3 if "VALID" in (a, b) else 2 if a != b else 0
        if priority:
            choices.append((priority * (right - left), middle))
    return max(choices)[1] if choices else None


def selected_pwm(observations: dict[int, dict], minimum: int = 5, span_ev: float = 2.) -> tuple[int, ...]:
    valid = sorted((r["signal_dn"], level) for level, r in observations.items() if r["status"] == "VALID" and r["signal_dn"] > 0)
    if len(valid) < minimum or math.log2(valid[-1][0] / valid[0][0]) < span_ev:
        return ()
    selected = {valid[0][1], valid[-1][1]}
    targets = np.geomspace(valid[0][0], valid[-1][0], minimum)
    for target in targets[1:-1]:
        candidates = [(abs(math.log(signal / target)), level) for signal, level in valid if level not in selected]
        if candidates:
            selected.add(min(candidates)[1])
    for _signal, level in valid:
        if len(selected) >= minimum:
            break
        selected.add(level)
    return tuple(sorted(selected))


class AutomaticCaptureRunner(LightCaptureRunner):
    def __init__(self, *args, settings: AutomaticSettings | None = None, **kwargs):
        super().__init__(*args, **kwargs)
        self.settings = settings or AutomaticSettings(gains=self.plan.gains)
        self.settings.validate()
        if self.settings.gains != self.plan.gains or self.plan.repeats < 5 or self.plan.dark_repeats < 5:
            raise ValueError("Automatic capture requires matching Gain definitions and >=5 Light/Dark repeats")
        self.probes: dict[tuple[int, int, float], dict] = {}
        self.planning = {"settings": asdict(self.settings), "gains": [], "curves": [], "probes": []}
        self.pending_formal_frames = 0

    def snapshot_extra(self):
        return {"capture_strategy": "automatic", "automatic_settings": asdict(self.settings),
                "exposure_anchor_source": "software_ROI_AE_fixed_gain",
                "analysis_thresholds": {**DEFAULT_THRESHOLDS, "minimum_exposure_span_ev": self.settings.minimum_span_ev,
                                        "minimum_signal_span_ev": self.settings.minimum_span_ev}}

    def _time(self, value):
        return round(float(np.clip(value, self.settings.minimum_exposure_ms, self.settings.maximum_exposure_ms)), 3)

    def _flush_planning(self):
        atomic_write_json(self.session / "SUMMARY" / "automatic_planning.json", self.planning)

    def probe(self, level: int, gain: int, exposure: float) -> dict:
        exposure = self._time(exposure)
        key = (level, gain, exposure)
        if key in self.probes:
            return self.probes[key]
        if len(self.probes) >= self.settings.probe_condition_limit:
            raise RuntimeError("Automatic probe budget exhausted; completed data retained")
        self.progress({"message": msg(f"自動預掃描：PWM {level} / Gain {gain}% / {exposure:g} ms",
                                       f"Automatic scouting: PWM {level} / Gain {gain}% / {exposure:g} ms"), "indeterminate": True})
        values = [0] * 4
        values[self.plan.channel - 1] = level
        self.light.enable(values, self.check_cancel)
        self.wait(self.plan.settle_s)
        lights = []
        actual_times = []
        high = False
        for repeat in range(1, 3):
            self.wait(np.random.default_rng().uniform(0, self.plan.jitter_s))
            state = self.verify_light(level)
            frame, region, actual = self.acquire(gain, exposure)
            self.verify_light(level)
            self.save_frame(frame, "PROBE_LIGHT", level, gain, exposure, actual, repeat, state)
            actual_times.append(actual)
            lights.append((region.copy(), frame.metadata["EffectiveDNMax"], frame.sequence))
            if np.any(region >= frame.metadata["EffectiveDNMax"] * .98):
                high = True
                break  # A saturated first frame needs no complete Dark/Light set.
        if high:
            result = {"status": "HIGH", "signal_dn": float(np.mean(lights[0][0])),
                      "actual_exposure_ms": actual_times[0], "effective_dn_max": lights[0][1]}
        else:
            self.light.turn_off()
            self.wait(self.plan.settle_s)
            stats = ConditionStatistics()
            for repeat in range(1, 4):
                state = self.verify_light(None)
                frame, region, actual = self.acquire(gain, exposure)
                self.verify_light(None)
                if any(abs(actual - t) > max(.001, actual * .001) for t in actual_times):
                    raise ValueError("Probe Light/Dark actual exposure mismatch")
                stats.add_dark(region)
                self.save_frame(frame, "PROBE_DARK", level, gain, exposure, actual, repeat, state)
            for region, maximum, sequence in lights:
                stats.add_light(region, maximum, sequence)
            result = stats.result()
            result["snr_noise_floor_dn"] = self.settings.noise_floor_dn
            result["snr"] = result["signal_dn"] / max(self.settings.noise_floor_dn, result["dark_noise_dn"])
            result["actual_exposure_ms"] = actual_times[0]
            result["status"] = "VALID" if result["snr"] >= DEFAULT_THRESHOLDS["minimum_snr"] and result["signal_dn"] > 0 else "LOW"
            if result["status"] == "VALID" and (result["repeat_cv_percent"] > 10 or result["temporal_band_percent"] > 10):
                result["status"] = "UNSTABLE"
        self.probes[key] = result
        self.planning["probes"].append({"pwm_level": level, "gain": gain, "requested_exposure_ms": exposure,
                                         **{k: v for k, v in result.items() if k != "frames"}})
        self._flush_planning()
        return result

    def anchor(self, level: int, gain: int, start: float) -> float:
        time = self._time(start)
        best = None
        seen = set()
        for _ in range(self.settings.ae_iterations):
            if time in seen:
                break
            seen.add(time)
            result = self.probe(level, gain, time)
            if result["status"] == "HIGH":
                time = self._time(time / 2)
            elif result["status"] in ("LOW", "UNSTABLE"):
                time = self._time(time * 2)
            else:
                best = time
                target = self.settings.target_fraction * max(1, result["effective_dn_max"] - result["dark_mean_dn"])
                ratio = target / max(result["signal_dn"], 1e-9)
                if .8 <= ratio <= 1.2:
                    return time
                time = self._time(time * float(np.clip(ratio, .25, 4)))
        return best if best is not None else time

    def pwm_for_gain(self, gain: int, start: float) -> tuple[float, tuple[int, ...]]:
        # Lower illumination can permit longer, more stable PWM integrations at
        # high Gain. Keep every diagnostic scout in the journal/planning file.
        for anchor_level in (128, 32, 8):
            common = self.anchor(anchor_level, gain, start)
            observations = {}
            for level in (1, 32, 64, 128, 255):
                observations[level] = self.probe(level, gain, common)
            for _ in range(self.settings.pwm_probe_limit - len(observations)):
                selected = selected_pwm(observations, self.settings.minimum_points, self.settings.minimum_span_ev)
                if selected:
                    return common, selected
                candidate = next_pwm(observations)
                if candidate is None:
                    break
                observations[candidate] = self.probe(candidate, gain, common)
            selected = selected_pwm(observations, self.settings.minimum_points, self.settings.minimum_span_ev)
            if selected:
                return common, selected
        return common, ()

    def range_for(self, level: int, gain: int, anchor: float) -> tuple[float, float]:
        low = high = anchor
        for direction in (-1, 1):
            valid = anchor
            invalid = None
            for _ in range(self.settings.boundary_steps):
                candidate = self._time(valid * (2 if direction == 1 else .5))
                if candidate == valid:
                    break
                status = self.probe(level, gain, candidate)["status"]
                if status != "VALID":
                    invalid = candidate
                    break
                valid = candidate
            # Refine boundaries, then retain only verified valid values.
            for _ in range(2):
                if invalid is None:
                    break
                candidate = self._time(math.sqrt(valid * invalid))
                if candidate in (valid, invalid):
                    break
                if self.probe(level, gain, candidate)["status"] == "VALID":
                    valid = candidate
                else:
                    invalid = candidate
            if direction == -1:
                low = valid
            else:
                high = valid
        return low, high

    def capture_schedule(self, rows: list[dict]):
        state = self.camera.snapshot_state()
        start = 200.
        for gain in self.settings.gains:
            self.check_cancel()
            minimum, maximum = state.get("GainMin"), state.get("GainMax")
            if minimum is not None and gain < int(minimum) or maximum is not None and gain > int(maximum):
                self.planning["gains"].append({"gain": gain, "status": "UNSUPPORTED_HARDWARE_GAIN"})
                self._flush_planning()
                continue
            common, levels = self.pwm_for_gain(gain, start)
            start = common  # Fixed-Gain AE rechecks this guess; no nominal Gain-ratio assumption.
            self.planning["gains"].append({"gain": gain, "common_exposure_ms": common, "pwm_levels": list(levels),
                                           "status": "PLANNED" if levels else "INSUFFICIENT_PWM_COVERAGE"})
            self._flush_planning()
            for level in levels:
                low, high = self.range_for(level, gain, common)
                times = exposure_points(low, high, self.settings)
                curve = {"gain": gain, "pwm_level": level, "low_ms": low, "high_ms": high,
                         "status": "PLANNED" if times else "INSUFFICIENT_EXPOSURE_COVERAGE"}
                self.planning["curves"].append(curve)
                if not times:
                    # A narrow exposure curve can still provide an independent
                    # valid common-exposure point for intensity linearity.
                    if self.probe(level, gain, common)["status"] == "VALID":
                        self.pending_formal_frames = self.plan.repeats + self.plan.dark_repeats
                        rows.append(self.capture_condition(level, gain, common))
                        atomic_write_json(self.session / "SUMMARY" / "condition_statistics.json", rows)
                        curve["captured_exposures_ms"] = [common]
                    self._flush_planning()
                    continue
                # Common exposures preserve intensity comparisons across PWM.
                times = tuple(sorted(set((*times, common))))
                self.pending_formal_frames = len(times) * (self.plan.repeats + self.plan.dark_repeats)
                accepted = []
                for exposure in times:
                    self.check_cancel()
                    if self.probe(level, gain, exposure)["status"] != "VALID":
                        self.manifest["skipped"].append({"gain": gain, "pwm_level": level, "exposure_ms": exposure, "reason": "PROBE_OUTSIDE_USABLE_RANGE"})
                        self.pending_formal_frames -= self.plan.repeats + self.plan.dark_repeats
                        continue
                    row = self.capture_condition(level, gain, exposure)
                    rows.append(row)
                    accepted.append(exposure)
                    atomic_write_json(self.session / "SUMMARY" / "condition_statistics.json", rows)
                    if row["near_saturation_fraction"] > 0:
                        # Real acquisition takes precedence over an earlier cached scout.
                        curve["saturation_during_formal_capture_ms"] = exposure
                        break
                curve["captured_exposures_ms"] = accepted
                curve["status"] = "CAPTURED" if len(accepted) >= self.settings.minimum_points else "INSUFFICIENT_VALID_POINTS"
                self._flush_planning()
        self.light.turn_off()

    def capture_condition(self, level, gain, exposure):
        result = super().capture_condition(level, gain, exposure)
        result["snr_noise_floor_dn"] = self.settings.noise_floor_dn
        result["snr"] = result["signal_dn"] / max(self.settings.noise_floor_dn, result["dark_noise_dn"])
        return result

    def emit_progress(self, phase, level, gain, exposure, region, maximum):
        self.pending_formal_frames = max(0, self.pending_formal_frames - 1)
        total = self._frame_count + self.pending_formal_frames
        elapsed = monotonic() - self.started
        self.progress(CaptureProgress(phase, f"PWM{level} G{gain}% E{exposure:g}ms", self._frame_count, total,
                                      elapsed, None, float(np.mean(region)), float(np.percentile(region, 99)),
                                      float(np.mean(region >= maximum * .98)), message="Automatic total grows as conditions are planned"))

    def save_frame(self, frame, kind, level, gain, exposure, actual, repeat, light_state):
        # Dynamic plans cannot reserve an exact size up front; check every write.
        needed = frame.scientific.nbytes + 1024 * 1024
        if shutil.disk_usage(self.session).free < needed:
            raise OSError("Insufficient storage; automatic acquisition stopped with data retained")
        super().save_frame(frame, kind, level, gain, exposure, actual, repeat, light_state)

    def checkpoint_frame(self, metadata):
        # Append a durable record per frame, rather than rewriting a growing
        # multi-megabyte manifest for every short-exposure scout.
        journal = self.session / "SUMMARY" / "frame_journal.jsonl"
        with journal.open("a", encoding="utf-8") as stream:
            stream.write(json.dumps(metadata, ensure_ascii=False) + "\n")
            stream.flush()
            os.fsync(stream.fileno())
        self.manifest["frame_journal"] = "SUMMARY/frame_journal.jsonl"
        if self._frame_count == 1 or self._frame_count % 32 == 0:
            atomic_write_json(self.manifest_path, self.manifest)
