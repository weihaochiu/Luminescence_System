"""External update transaction. Copied outside the running application before use."""
from __future__ import annotations

import argparse
import ctypes
import json
import logging
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import time

from core.software_update import (
    INSTALL_RECORD, PENDING_RECORD, RUNTIME_RECORD, UpdateError, atomic_json,
    file_hash, install_conflicts, read_json, target_file,
)

LOG = logging.getLogger(__name__)


def process_alive(pid: int) -> bool:
    if os.name == "nt":
        kernel = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel.OpenProcess.restype = ctypes.c_void_p
        kernel.OpenProcess.argtypes = [ctypes.c_uint32, ctypes.c_int, ctypes.c_uint32]
        kernel.WaitForSingleObject.argtypes = [ctypes.c_void_p, ctypes.c_uint32]
        kernel.CloseHandle.argtypes = [ctypes.c_void_p]
        handle = kernel.OpenProcess(0x100000, False, pid)
        if not handle:
            if ctypes.get_last_error() == 87:  # ERROR_INVALID_PARAMETER: process has exited.
                return False
            raise OSError(ctypes.get_last_error(), "Cannot verify parent process exit")
        try:
            return kernel.WaitForSingleObject(handle, 0) == 258
        finally:
            kernel.CloseHandle(handle)
    try:
        os.kill(pid, 0)
        return True
    except ProcessLookupError:
        return False


def replace_file(source: Path, destination: Path) -> None:
    if destination.is_file() and file_hash(source) == file_hash(destination):
        return
    destination.parent.mkdir(parents=True, exist_ok=True)
    descriptor, name = tempfile.mkstemp(prefix=".luminescence-", dir=destination.parent)
    os.close(descriptor)
    temporary = Path(name)
    try:
        shutil.copy2(source, temporary)
        os.replace(temporary, destination)
    finally:
        temporary.unlink(missing_ok=True)


def snapshot(work: Path, job: dict) -> dict:
    root = Path(job["root"])
    previous = read_json(root / INSTALL_RECORD).get("files", {}) if (root / INSTALL_RECORD).exists() else {}
    names = sorted(set(previous) | set(job["files"]) | {INSTALL_RECORD, RUNTIME_RECORD})
    originals = {}
    for name in names:
        source = target_file(root, name)
        originals[name] = source.is_file()
        if source.is_file():
            copy = work / "previous" / name
            copy.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, copy)
    # Back up persisted application JSON; exclude logs and the updates workspace.
    config = work / "configuration"
    config.mkdir()
    for path in Path(job["data"]).glob("*.json"):
        if path.is_file() and not path.is_symlink():
            shutil.copy2(path, config / path.name)
    state = {"phase": "backed_up", "originals": originals}
    atomic_json(work / "state.json", state)
    return state


def restore_settings(work: Path, job: dict) -> None:
    configuration = work / "configuration"
    if configuration.exists():
        for path in configuration.glob("*.json"):
            replace_file(path, Path(job["data"]) / path.name)
    settings = work / "settings.ini"
    if settings.is_file():
        script = (
            "import sys; from PySide6.QtCore import QSettings; "
            "s=QSettings(sys.argv[1], QSettings.IniFormat); "
            "d=QSettings('EL Measurement Lab','EL Measurement Equipment Control'); "
            "d.clear(); [(d.setValue(k,s.value(k))) for k in s.allKeys() if k!='__update_backup_format__']; d.sync(); "
            "sys.exit(0 if d.status()==QSettings.NoError else 1)"
        )
        subprocess.run([job["old_python"], "-c", script, str(settings)], check=True,
                       timeout=30, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))


def rollback(work: Path, job: dict) -> None:
    state_path = work / "state.json"
    if not state_path.exists():
        return  # The installer had not touched the application yet.
    state = read_json(state_path)
    if state["phase"] in {"backed_up", "applying", "starting", "recovery_failed"}:
        # Keep the journal until every restoration succeeds; retries are idempotent.
        for name, existed in state["originals"].items():
            destination = target_file(Path(job["root"]), name)
            if existed:
                replace_file(work / "previous" / name, destination)
            else:
                destination.unlink(missing_ok=True)
        restore_settings(work, job)
        state["phase"] = "rolled_back"
        atomic_json(state_path, state)


def apply_files(work: Path, job: dict) -> None:
    root = Path(job["root"])
    # Recheck after the GUI and any background settings writes have stopped.
    conflicts = install_conflicts(root, job["files"])
    if conflicts:
        raise UpdateError("local_changes", "\n".join(conflicts[:20]))
    for name, expected in job["files"].items():
        if file_hash(work / "package" / name) != expected:
            raise UpdateError("invalid_package", name)
    state = snapshot(work, job)
    state["phase"] = "applying"
    atomic_json(work / "state.json", state)
    old_record = root / INSTALL_RECORD
    previous = read_json(old_record).get("files", {}) if old_record.exists() else {}
    for name in sorted(set(previous) - set(job["files"])):
        target_file(root, name).unlink(missing_ok=True)
    for name in sorted(job["files"]):
        replace_file(work / "package" / name, target_file(root, name))
    atomic_json(root / INSTALL_RECORD, {"schema_version": 1, "sha": job["sha"],
                                       "version": job["version"], "files": job["files"]})
    atomic_json(root / RUNTIME_RECORD, {"python": job["python"]})
    state["phase"] = "starting"
    atomic_json(work / "state.json", state)


def start_application(work: Path, job: dict, *, previous: bool = False):
    environment = os.environ.copy()
    environment["LUMINESCENCE_SKIP_AUTOCONNECT"] = "1"
    environment["LUMINESCENCE_UPDATE_RESULT"] = str(work / "result.json")
    if not previous:
        environment["LUMINESCENCE_UPDATE_JOB"] = str(work / "job.json")
        environment["LUMINESCENCE_UPDATE_TOKEN"] = job["token"]
    else:
        environment.pop("LUMINESCENCE_UPDATE_JOB", None)
        environment.pop("LUMINESCENCE_UPDATE_TOKEN", None)
    # pythonw avoids leaving a terminal window after installation.
    interpreter = Path(job["old_python"] if previous else job["python"])
    pythonw = interpreter.with_name("pythonw.exe")
    if os.name == "nt" and pythonw.is_file():
        interpreter = pythonw
    log = (work / "startup.log").open("ab")
    try:
        return subprocess.Popen([str(interpreter), "-m", "gui.app"],
                                cwd=job["root"], env=environment, stdout=log, stderr=log,
                                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    finally:
        log.close()


def finish_update(work: Path, job: dict, *, health_timeout: float = 60) -> None:
    process = None
    try:
        apply_files(work, job)
        process = start_application(work, job)
        deadline = time.monotonic() + health_timeout
        while time.monotonic() < deadline:
            health = work / "health.json"
            if health.exists() and read_json(health).get("token") == job["token"]:
                state = read_json(work / "state.json")
                state["phase"] = "success"
                atomic_json(work / "state.json", state)
                atomic_json(work / "result.json", {"status": "success", "version": job["version"]})
                (Path(job["root"]) / PENDING_RECORD).unlink(missing_ok=True)
                return
            if process.poll() is not None:
                raise UpdateError("startup_failed", str(work / "startup.log"))
            time.sleep(0.2)
        raise UpdateError("startup_failed", "Startup confirmation timed out")
    except Exception as exc:
        LOG.exception("Installation failed; restoring previous files")
        if process is not None and process.poll() is None:
            process.terminate()  # Only our new process; automatic hardware connections were disabled.
            process.wait(timeout=15)
        try:
            rollback(work, job)
        except Exception:
            atomic_json(work / "result.json", {"status": "recovery_failed", "detail": str(exc)})
            raise
        atomic_json(work / "result.json", {"status": "rolled_back", "detail": str(exc)})
        (Path(job["root"]) / PENDING_RECORD).unlink(missing_ok=True)
        start_application(work, job, previous=True)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--job", type=Path, required=True)
    parser.add_argument("--recover", action="store_true")
    args = parser.parse_args()
    work = args.job.resolve().parent
    logging.basicConfig(filename=work / "installer.log", level=logging.INFO)
    job = read_json(args.job)
    root = Path(job["root"]).resolve()
    if (root / ".git").exists() or work.is_relative_to(root):
        raise UpdateError("development_checkout")
    pending = read_json(root / PENDING_RECORD)
    if pending.get("job") != str(args.job.resolve()) or pending.get("token") != job["token"]:
        raise UpdateError("invalid_package", "Missing safe-shutdown handoff")
    if args.recover:
        if (process_alive(job["parent_pid"])
                or (pending.get("installer_pid") and process_alive(pending["installer_pid"]))):
            raise UpdateError("installer_running")
        state = work / "state.json"
        if state.exists() and read_json(state).get("phase") == "success":
            atomic_json(work / "result.json", {"status": "success", "version": job["version"]})
            (root / PENDING_RECORD).unlink(missing_ok=True)
            return 0
        rollback(work, job)
        atomic_json(work / "result.json", {"status": "rolled_back", "detail": "Interrupted installation"})
        (root / PENDING_RECORD).unlink(missing_ok=True)
        return 0
    deadline = time.monotonic() + 120
    while process_alive(job["parent_pid"]):
        if time.monotonic() > deadline:
            raise UpdateError("parent_running")
        time.sleep(0.2)
    handoff = read_json(root / PENDING_RECORD)
    if handoff.get("token") != job["token"] or handoff.get("authorized") is not True:
        raise UpdateError("invalid_package", "Installation was not authorized after safe shutdown")
    finish_update(work, job)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
