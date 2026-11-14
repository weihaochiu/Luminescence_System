"""Release gate: bump the operator version, preserve history, and hash shipped files."""
from __future__ import annotations

import argparse
import ast
import json
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from core.release_info import load_history, version_tuple
from core.software_update import atomic_json, file_hash, managed_path


def source_version(source: str) -> str:
    for node in ast.parse(source).body:
        if isinstance(node, ast.Assign) and any(
            isinstance(target, ast.Name) and target.id == "__version__" for target in node.targets
        ):
            return node.value.value
    raise ValueError("Missing __version__")


def manifest_files() -> dict[str, str]:
    result = subprocess.run(["git", "ls-files", "--cached", "--others", "--exclude-standard", "-z"],
                            cwd=ROOT, capture_output=True, check=True)
    names = set(result.stdout.decode("utf-8").split("\0"))
    return {name: file_hash(ROOT / name) for name in sorted(names)
            if name and name != "release_manifest.json" and managed_path(name) and (ROOT / name).is_file()}


def validate_release(base: str | None = None) -> list[dict]:
    history = load_history()
    current = source_version((ROOT / "gui/__init__.py").read_text("utf-8-sig"))
    if current != history[0]["version"]:
        raise ValueError("GUI version and release history disagree")
    if base:
        # Fail closed when the baseline cannot be resolved.
        old = subprocess.run(["git", "show", f"{base}:gui/__init__.py"], cwd=ROOT,
                             capture_output=True, text=True, check=True)
        if version_tuple(current) <= version_tuple(source_version(old.stdout)):
            raise ValueError("Every delivery must increase the version above the baseline")
        previous = subprocess.run(["git", "show", f"{base}:release_history.json"], cwd=ROOT,
                                  capture_output=True, text=True, encoding="utf-8")
        if previous.returncode == 0:
            old_history = json.loads(previous.stdout)["releases"]
            if history[-len(old_history):] != old_history:
                raise ValueError("Published release notes must not be rewritten")
    return history


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base")
    parser.add_argument("--write-manifest", action="store_true")
    args = parser.parse_args()
    history = validate_release(args.base)
    payload = {"schema_version": 1, "version": history[0]["version"], "files": manifest_files()}
    if args.write_manifest:
        atomic_json(ROOT / "release_manifest.json", payload)
    elif json.loads((ROOT / "release_manifest.json").read_text("utf-8")) != payload:
        raise ValueError("Release manifest is stale; run --write-manifest before testing")
    print(f"Release {history[0]['version']}: version, notes and {len(payload['files'])} file hashes verified")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
