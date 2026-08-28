from __future__ import annotations

from datetime import datetime
import hashlib
import json
from pathlib import Path
from typing import Any

from .capture_manifest import sha256_file
from .models import QualificationResult, RunMode
from .settings import QualificationCriteria


PROFILE_SCHEMA_VERSION = "1.0.0"


def dataset_hash(paths: list[Path]) -> str:
    digest = hashlib.sha256()
    for path in sorted(paths, key=lambda item: str(item).lower()):
        digest.update(str(path.name).encode("utf-8"))
        digest.update(sha256_file(path).encode("ascii"))
    return digest.hexdigest()


def build_profile(
    summary: dict[str, Any],
    *,
    criteria: QualificationCriteria,
    mode: RunMode,
    synthetic: bool,
    source_paths: list[Path],
    manifest_path: Path | None = None,
) -> dict[str, Any]:
    overall = str(summary.get("overall_qualification", QualificationResult.FAIL.value))
    usable = (
        mode is RunMode.FULL
        and overall == QualificationResult.PASS.value
        and not synthetic
        and bool(summary.get("formal_evidence_complete"))
    )
    identity = dict(summary.get("camera_identity", {}))
    payload = {
        "profile_schema_version": PROFILE_SCHEMA_VERSION,
        "qualification_criteria_version": criteria.version,
        "created_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "software_commit": summary.get("software_commit", "unknown"),
        "camera_model": identity.get("model"),
        "camera_serial": identity.get("serial"),
        "resolution": summary.get("resolution"),
        "pixel_format": summary.get("raw_format"),
        "sensor_bit_depth": summary.get("sensor_bit_depth"),
        "EffectiveDNMax": summary.get("effective_dn_max"),
        "RawValueAlignment": summary.get("raw_value_alignment"),
        "validated_temperature_range": summary.get("temperature_range_c"),
        "ROI": summary.get("roi"),
        "validated_gains": summary.get("validated_gains", []),
        "per_gain_exposure_linearity": summary.get("per_gain_linearity", []),
        "empirical_gain_response": summary.get("empirical_gain_response", []),
        "reliable_dn_low": summary.get("reliable_dn_low"),
        "reliable_dn_high": summary.get("reliable_dn_high"),
        "preferred_dn_low": summary.get("preferred_dn_low"),
        "preferred_dn_high": summary.get("preferred_dn_high"),
        "target_dn": summary.get("target_dn"),
        "compression_onset": summary.get("compression_onset"),
        "saturation_warning": summary.get("saturation_warning"),
        "saturation_reject": summary.get("saturation_reject"),
        "recommended_exposure_limits": summary.get("recommended_exposure_limits", {}),
        "multi_exposure_readiness": summary.get("hdr_readiness"),
        "test_dataset_hash": dataset_hash(source_paths),
        "manifest_hash": sha256_file(manifest_path) if manifest_path and manifest_path.exists() else None,
        "qualification_result": overall,
        "limitations": summary.get("limitations", []),
        "run_mode": mode.value,
        "synthetic_dataset": bool(synthetic),
        "profile_usable_for_production": usable,
    }
    return payload

def load_profile(path: str | Path) -> dict[str, Any]:
    payload = json.loads(Path(path).read_text(encoding="utf-8-sig"))
    if payload.get("profile_schema_version") != PROFILE_SCHEMA_VERSION:
        raise ValueError("Unsupported camera linearity profile schema")
    return payload
