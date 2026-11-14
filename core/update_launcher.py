"""Stable stdlib bootstrap used by run.bat; recover before importing GUI code."""
from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import sys


def main() -> int:
    root = Path(__file__).resolve().parents[1]
    pending = root / ".luminescence-update-pending.json"
    environment = os.environ.copy()
    if pending.exists():
        record = json.loads(pending.read_text("utf-8"))
        job = Path(record["job"]).resolve()
        result = subprocess.run([sys.executable, "-m", "core.update_runner", "--job", str(job), "--recover"],
                                cwd=job.parent / "helper", check=False)
        if result.returncode:
            print(f"Update recovery failed. Preserve files and see: {job.parent}")
            return result.returncode
        environment["LUMINESCENCE_SKIP_AUTOCONNECT"] = "1"
        environment["LUMINESCENCE_UPDATE_RESULT"] = str(job.parent / "result.json")
    interpreter = sys.executable
    runtime = root / ".luminescence-runtime.json"
    if runtime.exists():
        interpreter = json.loads(runtime.read_text("utf-8"))["python"]
        if not Path(interpreter).is_file():
            print("The selected Python environment is missing. Restore the previous installation.")
            return 1
    return subprocess.call([interpreter, "-m", "gui.app"], cwd=root, env=environment)


if __name__ == "__main__":
    raise SystemExit(main())
