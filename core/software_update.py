"""Pinned GitHub downloads and conservative file plans for equipment installations."""
from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import shutil
import stat
import subprocess
import sys
from typing import Callable
from urllib.request import Request, urlopen
import uuid
import zipfile

from core.release_info import validate_history, version_tuple

REPOSITORY = "weihaochiu/Luminescence_System"
INSTALL_RECORD = ".luminescence-install.json"
RUNTIME_RECORD = ".luminescence-runtime.json"
PENDING_RECORD = ".luminescence-update-pending.json"
MAX_ARCHIVE = 512 * 1024 * 1024
MAX_EXPANDED = 2 * 1024 * 1024 * 1024
CODE_DIRECTORIES = {"core", "gui", "drivers", "resources", "scripts", "standalone", "tools", "docs", "tests"}
ROOT_FILES = {"main.py", "requirements.txt", "release_history.json", "release_manifest.json", "README.md", "AGENTS.md",
              "REQUIREMENTS_LOG.md", "THIRD_PARTY_NOTICE.txt", ".gitattributes", ".gitignore",
              "relay_hardware_diagnostic.py", "run.bat", "setup_and_run.bat", "run_tests.bat",
              "run_hdr_viewer.bat", "run_camera_linearity_qualification.bat",
              "run_light_linearity_qualification.bat", "run_ruler_scale_calibration_tester.bat"}
PROTECTED_PARTS = {".git", ".venv", "venv", "backup", "local", "private", "paper", "ruler",
                   "__pycache__", ".pytest_cache", "logs", "output", "outputs", "data"}
REQUIRED_FILES = {"main.py", "gui/__init__.py", "gui/app.py", "requirements.txt",
                  "release_history.json", "release_manifest.json", "run.bat", "core/update_launcher.py"}


class UpdateError(RuntimeError):
    def __init__(self, reason: str, detail: str = "") -> None:
        super().__init__(f"{reason}: {detail}" if detail else reason)
        self.reason = reason
        self.detail = detail


@dataclass(frozen=True)
class UpdateOffer:
    sha: str
    releases: list[dict]

    @property
    def version(self) -> str:
        return self.releases[0]["version"]


def atomic_json(path: Path, value: object) -> None:
    temporary = path.with_name(path.name + ".tmp")
    with temporary.open("w", encoding="utf-8") as stream:
        json.dump(value, stream, ensure_ascii=False, indent=2)
        stream.flush()
        os.fsync(stream.fileno())
    os.replace(temporary, path)


def read_json(path: Path) -> dict:
    payload = json.loads(path.read_text("utf-8"))
    if not isinstance(payload, dict):
        raise UpdateError("invalid_package", str(path))
    return payload


def file_hash(path: Path) -> str:
    # Git may normalize CRLF when publishing Windows working files. Compare text
    # contents consistently in Git archives and BAT-installed equipment copies.
    if path.suffix.lower() in {".py", ".json", ".md", ".txt", ".bat", ".ps1", ".yml",
                               ".yaml", ".toml", ".mmd", ".csv", ".tsv", ".svg", ".xml", ".ui"} or path.name in {".gitignore", ".gitattributes"}:
        return hashlib.sha256(path.read_bytes().replace(b"\r\n", b"\n")).hexdigest()
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def safe_relative(name: str) -> PurePosixPath:
    path = PurePosixPath(name)
    if (not name or not path.parts or "\\" in name or ":" in name or path.is_absolute()
            or ".." in path.parts or any(part.endswith((".", " ")) for part in path.parts)
            or any(re.fullmatch(r"(?i)(con|prn|aux|nul|com[0-9]|lpt[0-9])(\..*)?", part)
                   for part in path.parts)):
        raise UpdateError("invalid_package", name)
    return path


def managed_path(name: str) -> bool:
    parts = safe_relative(name).parts
    if any(part.casefold() in PROTECTED_PARTS for part in parts):
        return False
    return (len(parts) == 1 and name in ROOT_FILES) or (len(parts) > 1 and parts[0] in CODE_DIRECTORIES)


def target_file(root: Path, name: str) -> Path:
    relative = safe_relative(name)
    candidate = root.joinpath(*relative.parts)
    if not candidate.resolve().is_relative_to(root.resolve()):
        raise UpdateError("local_changes", name)
    # Never traverse even an in-root symlink/junction in an installed tree.
    for path in (candidate, *candidate.parents):
        if path == root:
            break
        if path.is_symlink() or (hasattr(path, "is_junction") and path.is_junction()):
            raise UpdateError("local_changes", name)
    return candidate


def _request(url: str):
    return urlopen(Request(url, headers={"User-Agent": "Luminescence-System-Updater",
                                        "Accept": "application/vnd.github+json"}), timeout=30)


def _json_url(url: str) -> dict:
    with _request(url) as response:
        raw = response.read(2 * 1024 * 1024 + 1)
    if len(raw) > 2 * 1024 * 1024:
        raise UpdateError("invalid_package", "Oversized metadata")
    payload = json.loads(raw)
    if not isinstance(payload, dict):
        raise UpdateError("invalid_package", "Invalid metadata")
    return payload


def check_latest() -> UpdateOffer:
    commit = _json_url(f"https://api.github.com/repos/{REPOSITORY}/commits/main")
    sha = commit.get("sha", "")
    if not isinstance(sha, str) or not re.fullmatch(r"[0-9a-f]{40}", sha):
        raise UpdateError("invalid_package", "Invalid commit SHA")
    history = _json_url(f"https://raw.githubusercontent.com/{REPOSITORY}/{sha}/release_history.json")
    return UpdateOffer(sha, validate_history(history))


def download_archive(offer: UpdateOffer, destination: Path,
                     progress: Callable[[int], None] = lambda _value: None) -> None:
    if not re.fullmatch(r"[0-9a-f]{40}", offer.sha):
        raise UpdateError("invalid_package", "Invalid commit SHA")
    url = f"https://github.com/{REPOSITORY}/archive/{offer.sha}.zip"
    try:
        with _request(url) as response, destination.open("wb") as output:
            total = int(response.headers.get("Content-Length", 0))
            if total > MAX_ARCHIVE:
                raise UpdateError("invalid_package", "Archive too large")
            downloaded = 0
            while chunk := response.read(1024 * 1024):
                downloaded += len(chunk)
                if downloaded > MAX_ARCHIVE:
                    raise UpdateError("invalid_package", "Archive too large")
                output.write(chunk)
                progress(min(99, int(downloaded * 100 / total)) if total else -1)
            if total and downloaded != total:
                raise UpdateError("invalid_package", "Incomplete download")
    except Exception:
        destination.unlink(missing_ok=True)
        raise
    progress(100)


def extract_package(archive: Path, destination: Path, offer: UpdateOffer) -> dict[str, str]:
    hashes: dict[str, str] = {}
    with zipfile.ZipFile(archive) as source:
        entries = source.infolist()
        if len(entries) > 30000 or sum(entry.file_size for entry in entries) > MAX_EXPANDED:
            raise UpdateError("invalid_package", "Expanded archive too large")
        prefix = f"Luminescence_System-{offer.sha}"
        seen: set[str] = set()
        for entry in entries:
            relative = safe_relative(entry.filename)
            if relative.parts[0] != prefix:
                raise UpdateError("invalid_package", "Unexpected archive root")
            if stat.S_ISLNK(entry.external_attr >> 16):
                raise UpdateError("invalid_package", "Symbolic link in archive")
            if entry.is_dir() or len(relative.parts) < 2:
                continue
            name = PurePosixPath(*relative.parts[1:]).as_posix()
            if name.casefold() in seen:
                raise UpdateError("invalid_package", "Duplicate archive path")
            seen.add(name.casefold())
            if not managed_path(name):
                continue
            target = target_file(destination, name)
            target.parent.mkdir(parents=True, exist_ok=True)
            with source.open(entry) as incoming, target.open("wb") as output:
                shutil.copyfileobj(incoming, output)
            hashes[name] = file_hash(target)
    if not REQUIRED_FILES <= hashes.keys():
        raise UpdateError("invalid_package", "Missing application files")
    releases = validate_history(read_json(destination / "release_history.json"))
    if releases != offer.releases:
        raise UpdateError("invalid_package", "Release history differs from checked commit")
    import ast
    tree = ast.parse((destination / "gui/__init__.py").read_text("utf-8-sig"))
    versions = [node.value.value for node in tree.body if isinstance(node, ast.Assign)
                and any(isinstance(t, ast.Name) and t.id == "__version__" for t in node.targets)
                and isinstance(node.value, ast.Constant)]
    if versions != [offer.version]:
        raise UpdateError("invalid_package", "Version and release notes disagree")
    manifest = read_json(destination / "release_manifest.json")
    expected = {name: digest for name, digest in hashes.items() if name != "release_manifest.json"}
    if manifest.get("version") != offer.version or manifest.get("files") != expected:
        raise UpdateError("invalid_package", "Release file hashes disagree")
    for name in hashes:
        if name.endswith(".py") and (name.startswith(("core/", "gui/")) or name == "main.py"):
            compile((destination / name).read_bytes(), name, "exec")
    return hashes


def install_conflicts(root: Path, incoming: dict[str, str]) -> list[str]:
    record = root / INSTALL_RECORD
    baseline = read_json(record) if record.exists() else read_json(root / "release_manifest.json")
    previous = baseline.get("files", {})
    if not isinstance(previous, dict) or not previous:
        raise UpdateError("unverified_install")
    previous = dict(previous)
    if not record.exists():
        previous["release_manifest.json"] = file_hash(root / "release_manifest.json")
    conflicts = []
    for name in set(previous) | set(incoming):
        if not managed_path(name):
            raise UpdateError("invalid_package", name)
        target = target_file(root, name)
        if target.exists() and not target.is_file():
            conflicts.append(name)
        elif name in previous and (not target.exists() or file_hash(target) != previous[name]):
            conflicts.append(name)
        elif name not in previous and target.exists():
            # A new upstream file must not overwrite an unrelated local file.
            if file_hash(target) != incoming.get(name):
                conflicts.append(name)
    return sorted(conflicts)


def prepare_update(root: Path, data: Path, offer: UpdateOffer,
                   progress: Callable[[str, int], None] = lambda _phase, _value: None) -> Path:
    root = root.resolve()
    if (root / ".git").exists():
        raise UpdateError("development_checkout")
    if (root / PENDING_RECORD).exists():
        raise UpdateError("pending_update")
    if not (root / INSTALL_RECORD).exists() and not (root / "release_manifest.json").exists():
        raise UpdateError("unverified_install")
    work = data.resolve() / "updates" / uuid.uuid4().hex
    work.mkdir(parents=True)
    if work.is_relative_to(root):
        raise UpdateError("invalid_package", "Update workspace must be outside application")
    if shutil.disk_usage(root).free < MAX_ARCHIVE or shutil.disk_usage(work).free < MAX_ARCHIVE:
        raise UpdateError("disk_space")
    progress("download", 0)
    download_archive(offer, work / "source.zip", lambda value: progress("download", value))
    progress("verify", -1)
    files = extract_package(work / "source.zip", work / "package", offer)
    conflicts = install_conflicts(root, files)
    if conflicts:
        raise UpdateError("local_changes", "\n".join(conflicts[:20]))
    # Check practical space after reading the actual archive, including rollback copies.
    required = sum((work / "package" / name).stat().st_size for name in files)
    if shutil.disk_usage(root).free < required * 2 + 128 * 1024 * 1024:
        raise UpdateError("disk_space")
    old_python = Path(sys.executable).resolve()
    python = old_python
    if file_hash(root / "requirements.txt") != files["requirements.txt"]:
        progress("dependencies", -1)
        environment = data.resolve() / "updates" / "environments" / work.name
        result = subprocess.run([str(old_python), "-m", "venv", str(environment)],
                                capture_output=True, timeout=180, creationflags=_hidden_flags())
        (work / "environment.log").write_bytes(result.stdout + result.stderr)
        if result.returncode:
            raise UpdateError("dependencies", str(work / "environment.log"))
        python = environment / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
        result = subprocess.run([str(python), "-m", "pip", "install", "--disable-pip-version-check",
                                 "-r", str(work / "package/requirements.txt")],
                                capture_output=True, timeout=1200, creationflags=_hidden_flags())
        with (work / "environment.log").open("ab") as log:
            log.write(result.stdout + result.stderr)
        if result.returncode:
            raise UpdateError("dependencies", str(work / "environment.log"))
    progress("verify", -1)
    # Import checks take place in a separate interpreter and never create a GUI or open hardware.
    result = subprocess.run([str(python), "-c",
                             "import PySide6.QtWidgets, numpy, PIL, tifffile, cv2, pyvisa, usb, hid"],
                            capture_output=True, timeout=60, creationflags=_hidden_flags())
    if result.returncode:
        raise UpdateError("dependencies", result.stderr.decode("utf-8", "replace")[-2000:])
    helper = work / "helper/core"
    helper.mkdir(parents=True)
    (helper / "__init__.py").write_text("", "utf-8")
    for name in ("software_update.py", "release_info.py", "update_runner.py"):
        shutil.copy2(Path(__file__).parent / name, helper / name)
    job = {"root": str(root), "data": str(data.resolve()), "sha": offer.sha,
           "version": offer.version, "files": files, "python": str(python),
           "old_python": str(old_python), "parent_pid": os.getpid(), "token": uuid.uuid4().hex}
    atomic_json(work / "job.json", job)
    return work / "job.json"


def _hidden_flags() -> int:
    return getattr(subprocess, "CREATE_NO_WINDOW", 0)


def installed_sha(root: Path) -> str | None:
    try:
        value = read_json(root / INSTALL_RECORD).get("sha")
        return value if isinstance(value, str) and re.fullmatch(r"[a-f0-9]{40}", value) else None
    except (OSError, ValueError, UpdateError):
        return None
