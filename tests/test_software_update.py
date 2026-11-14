from __future__ import annotations

import copy
import io
import json
import os
from pathlib import Path
import shutil
import stat
import tempfile
import subprocess
import sys
import time
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch
import zipfile

from core.release_info import format_changes, load_history, validate_history, version_tuple
from core import software_update as update
from core import update_runner as runner
from gui import __version__


class UpdateFixture(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.base = Path(self.temporary.name)
        self.root = self.base / "equipment"
        self.work = self.base / "updates/job"
        self.data = self.base / "appdata"
        self.root.mkdir()
        self.work.mkdir(parents=True)
        self.data.mkdir()
        self.history = {"schema_version": 1, "releases": [
            {"version": "1.11.0", "date": "2026-11-14", "changes": {
                "zh-TW": ["新版修改"], "en-US": ["New changes"]}},
            {"version": "1.10.0", "date": "2026-11-13", "changes": {
                "zh-TW": ["前版修改"], "en-US": ["Previous changes"]}},
        ]}
        self.offer = update.UpdateOffer("a" * 40, self.history["releases"])

    def write(self, root, name, content):
        path = root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
        return path

    def archive(self, extra=None, transform=None):
        files = {name: "# fixture\n" for name in update.REQUIRED_FILES}
        files["gui/__init__.py"] = '__version__ = "1.11.0"\n'
        files["release_history.json"] = json.dumps(self.history)
        files["main.py"] = "print('new')\n"
        files["requirements.txt"] = "PySide6>=6.8,<7\n"
        files.update(extra or {})
        if transform:
            transform(files)
        import hashlib
        manifest = {"schema_version": 1, "version": "1.11.0", "files": {
            name: hashlib.sha256(content.encode()).hexdigest() for name, content in files.items()
            if name != "release_manifest.json" and update.managed_path(name)}}
        files["release_manifest.json"] = json.dumps(manifest)
        path = self.work / "source.zip"
        with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as archive:
            for name, content in files.items():
                archive.writestr(f"Luminescence_System-{self.offer.sha}/{name}", content)
        return path

    def installation(self, *, record=True):
        self.write(self.root, "main.py", "print('old')\n")
        self.write(self.root, "gui/obsolete.py", "# obsolete\n")
        self.write(self.root, "requirements.txt", "PySide6>=6.8,<7\n")
        previous = {name: update.file_hash(self.root / name)
                    for name in ("main.py", "gui/obsolete.py", "requirements.txt")}
        payload = {"version": "1.10.0", "files": previous}
        update.atomic_json(self.root / (update.INSTALL_RECORD if record else "release_manifest.json"), payload)
        self.write(self.root, "local/operator.txt", "keep me")
        self.write(self.root, "measurements/sample.tiff", "original measurement")
        self.write(self.data, "recipes.json", '{"recipes": ["old"]}')
        return previous

    def job(self, extra=None):
        files = update.extract_package(self.archive(extra), self.work / "package", self.offer)
        job = {"root": str(self.root), "data": str(self.data), "sha": self.offer.sha,
               "version": self.offer.version, "files": files, "token": "test-token",
               "python": "new-python", "old_python": "old-python", "parent_pid": os.getpid()}
        update.atomic_json(self.work / "job.json", job)
        update.atomic_json(self.root / update.PENDING_RECORD,
                           {"job": str(self.work / "job.json"), "token": job["token"], "authorized": True})
        return job


class ReleaseTests(unittest.TestCase):
    def test_current_version_has_bilingual_changes(self):
        releases = load_history()
        self.assertEqual(__version__, releases[0]["version"])
        for language in ("zh-TW", "en-US"):
            self.assertIn(__version__, format_changes(releases[:1], language))

    def test_numeric_version_order(self):
        self.assertGreater(version_tuple("1.10.0"), version_tuple("1.9.99"))
        for invalid in ("v1.2.3", "1.2", None, "1.2.3-rc1"):
            with self.assertRaises(ValueError):
                version_tuple(invalid)

    def test_changes_include_all_newer_releases_in_selected_language(self):
        history = {"schema_version": 1, "releases": [
            {"version": "2.0.0", "date": "2026-11-14", "changes": {"zh-TW": ["新"], "en-US": ["New"]}},
            {"version": "1.9.1", "date": "2026-11-13", "changes": {"zh-TW": ["舊"], "en-US": ["Old"]}},
        ]}
        releases = validate_history(history)
        text = format_changes(releases, "en-US", after="1.8.0")
        self.assertIn("New", text)
        self.assertIn("Old", text)
        self.assertNotIn("新", text)
        self.assertNotIn("Old", format_changes(releases, "en-US", after="1.9.1"))

    def test_missing_notes_and_reordered_history_are_rejected(self):
        payload = {"schema_version": 1, "releases": copy.deepcopy(load_history())}
        payload["releases"][0]["changes"]["en-US"] = []
        with self.assertRaises(ValueError):
            validate_history(payload)
        payload["releases"] = [load_history()[0], load_history()[0]]
        with self.assertRaises(ValueError):
            validate_history(payload)

    def test_release_gate_rejects_same_version_and_rewritten_history(self):
        from tools.check_release import validate_release
        old_version = SimpleNamespace(stdout=f'__version__ = "{__version__}"', returncode=0)
        with patch("tools.check_release.subprocess.run", return_value=old_version):
            with self.assertRaisesRegex(ValueError, "increase"):
                validate_release("origin/main")
        old_version = SimpleNamespace(stdout='__version__ = "1.9.1"', returncode=0)
        old_history = SimpleNamespace(stdout=json.dumps({"releases": [{"version": "1.9.1"}]}), returncode=0)
        with patch("tools.check_release.subprocess.run", side_effect=[old_version, old_history]):
            with self.assertRaisesRegex(ValueError, "rewritten"):
                validate_release("origin/main")


class PackageTests(UpdateFixture):
    def test_windows_and_git_newlines_have_identical_text_hashes(self):
        first = self.root / "first.py"
        second = self.root / "second.py"
        first.write_bytes(b"a\r\nb\r\n")
        second.write_bytes(b"a\nb\n")
        self.assertEqual(update.file_hash(first), update.file_hash(second))

    def test_metadata_uses_pinned_commit(self):
        with patch.object(update, "_json_url", side_effect=[{"sha": self.offer.sha}, self.history]) as fetch:
            offer = update.check_latest()
        self.assertEqual(self.offer, offer)
        self.assertIn(f"/{self.offer.sha}/release_history.json", fetch.call_args_list[1].args[0])

    def test_invalid_commit_is_never_used_in_url(self):
        with patch.object(update, "_json_url", return_value={"sha": "../../oops"}) as fetch:
            with self.assertRaises(update.UpdateError):
                update.check_latest()
            self.assertEqual(1, fetch.call_count)

    def test_download_incomplete_body_removes_partial_zip(self):
        response = io.BytesIO(b"short")
        response.headers = {"Content-Length": "100"}
        destination = self.work / "partial.zip"
        with patch.object(update, "_request", return_value=response):
            with self.assertRaises(update.UpdateError):
                update.download_archive(self.offer, destination)
        self.assertFalse(destination.exists())

    def test_extract_verifies_hashes_and_preserves_protected_paths(self):
        archive = self.archive({"local/operator.txt": "overwrite", "backup/backup_1.zip": "bad"})
        files = update.extract_package(archive, self.work / "package", self.offer)
        self.assertIn("main.py", files)
        self.assertNotIn("local/operator.txt", files)
        self.assertFalse((self.work / "package/local").exists())

    def test_zip_traversal_absolute_paths_and_windows_aliases_are_rejected(self):
        for name in ("../escape", "/absolute", "C:/escape", "gui/../../escape", "gui/CON.txt", "gui/file. ", "gui\\escape"):
            with self.subTest(name=name), self.assertRaises(update.UpdateError):
                update.safe_relative(name)

    def test_zip_symlink_is_rejected(self):
        archive = self.archive()
        with zipfile.ZipFile(archive, "a") as output:
            info = zipfile.ZipInfo(f"Luminescence_System-{self.offer.sha}/gui/link")
            info.external_attr = (stat.S_IFLNK | 0o777) << 16
            output.writestr(info, "../../escape")
        with self.assertRaises(update.UpdateError):
            update.extract_package(archive, self.work / "package", self.offer)

    def test_version_disagreement_and_missing_files_are_rejected(self):
        for mutation in (lambda files: files.pop("main.py"),
                         lambda files: files.update({"gui/__init__.py": '__version__="1.12.0"'})):
            with self.subTest(mutation=mutation), self.assertRaises(update.UpdateError):
                update.extract_package(self.archive(transform=mutation), self.work / "package", self.offer)

    def test_archive_hash_tampering_is_rejected(self):
        archive = self.archive()
        with zipfile.ZipFile(archive) as source:
            entries = {name: source.read(name) for name in source.namelist()}
        entries[f"Luminescence_System-{self.offer.sha}/main.py"] = b"print('tampered')"
        with zipfile.ZipFile(archive, "w") as output:
            for name, content in entries.items():
                output.writestr(name, content)
        with self.assertRaisesRegex(update.UpdateError, "hashes"):
            update.extract_package(archive, self.work / "package", self.offer)

    def test_development_checkout_and_pending_update_are_blocked_before_network(self):
        (self.root / ".git").mkdir()
        with patch.object(update, "download_archive") as download:
            with self.assertRaisesRegex(update.UpdateError, "development_checkout"):
                update.prepare_update(self.root, self.data, self.offer)
            download.assert_not_called()
        (self.root / ".git").rmdir()
        self.write(self.root, update.PENDING_RECORD, "{}")
        with self.assertRaisesRegex(update.UpdateError, "pending_update"):
            update.prepare_update(self.root, self.data, self.offer)

    def test_local_changes_and_new_file_collision_are_preserved(self):
        self.installation()
        job = self.job()
        self.write(self.root, "main.py", "operator change")
        self.write(self.root, "gui/app.py", "local tool")
        conflicts = update.install_conflicts(self.root, job["files"])
        self.assertIn("main.py", conflicts)
        self.assertIn("gui/app.py", conflicts)
        self.assertEqual("operator change", (self.root / "main.py").read_text())

    def test_legacy_bat_deployment_bootstraps_from_release_manifest(self):
        self.installation(record=False)
        job = self.job()
        self.assertEqual([], update.install_conflicts(self.root, job["files"]))

    def test_prepare_failure_does_not_change_existing_runtime(self):
        self.installation()
        source = self.archive()
        def download(_offer, destination, _progress):
            shutil.copyfile(source, destination)
        # Force environment creation, then fail pip installation.
        self.write(self.root, "requirements.txt", "old dependency\n")
        record = update.read_json(self.root / update.INSTALL_RECORD)
        record["files"]["requirements.txt"] = update.file_hash(self.root / "requirements.txt")
        update.atomic_json(self.root / update.INSTALL_RECORD, record)
        with patch.object(update, "download_archive", side_effect=download), patch.object(
            update.subprocess, "run", side_effect=[SimpleNamespace(returncode=0, stdout=b"", stderr=b""),
                                                   SimpleNamespace(returncode=1, stdout=b"", stderr=b"pip failed")]
        ):
            with self.assertRaisesRegex(update.UpdateError, "dependencies"):
                update.prepare_update(self.root, self.data, self.offer)
        self.assertFalse((self.root / update.RUNTIME_RECORD).exists())
        self.assertEqual("print('old')\n", (self.root / "main.py").read_text())

    def test_preparation_pins_job_and_copies_standalone_helper_without_touching_program(self):
        self.installation()
        source = self.archive()
        def download(_offer, destination, _progress):
            shutil.copyfile(source, destination)
        with patch.object(update, "download_archive", side_effect=download), patch.object(
            update.subprocess, "run", return_value=SimpleNamespace(returncode=0)
        ):
            path = update.prepare_update(self.root, self.data, self.offer)
        prepared = update.read_json(path)
        self.assertEqual(self.offer.sha, prepared["sha"])
        self.assertEqual(str(self.root), prepared["root"])
        self.assertTrue((path.parent / "helper/core/update_runner.py").is_file())
        self.assertFalse((self.root / update.PENDING_RECORD).exists())
        self.assertEqual("print('old')\n", (self.root / "main.py").read_text())


class TransactionTests(UpdateFixture):
    def helper(self, job):
        helper = self.work / "helper/core"
        helper.mkdir(parents=True)
        (helper / "__init__.py").write_text("")
        for name in ("software_update.py", "release_info.py", "update_runner.py"):
            shutil.copy2(Path(update.__file__).parent / name, helper / name)
        job.update(python=sys.executable, old_python=sys.executable, parent_pid=1073741824)
        update.atomic_json(self.work / "job.json", job)
        return helper.parent

    def test_real_external_installer_runs_pinned_package_and_receives_startup_acknowledgement(self):
        self.installation()
        app = """import json, os, time
from pathlib import Path
job = Path(os.environ['LUMINESCENCE_UPDATE_JOB'])
token = os.environ['LUMINESCENCE_UPDATE_TOKEN']
assert os.environ['LUMINESCENCE_SKIP_AUTOCONNECT'] == '1'
health = job.parent/'health.json'
temporary = job.parent/'health.tmp'
temporary.write_text(json.dumps({'token':token, 'pid':os.getpid()}))
temporary.replace(health)
while not (job.parent/'result.json').exists():
    time.sleep(0.05)
"""
        job = self.job({"gui/app.py": app})
        helper = self.helper(job)
        result = subprocess.run([sys.executable, "-m", "core.update_runner", "--job",
                                 str(self.work / "job.json")], cwd=helper, capture_output=True,
                                timeout=30, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        self.assertEqual(0, result.returncode, result.stderr.decode("utf-8", "replace"))
        self.assertEqual("success", update.read_json(self.work / "result.json")["status"])
        pid = update.read_json(self.work / "health.json")["pid"]
        deadline = time.monotonic() + 5
        while runner.process_alive(pid) and time.monotonic() < deadline:
            time.sleep(0.05)
        self.assertFalse(runner.process_alive(pid))

    def test_real_recovery_bootstrap_restores_interrupted_transaction(self):
        self.installation()
        job = self.job()
        helper = self.helper(job)
        runner.apply_files(self.work, job)
        result = subprocess.run([sys.executable, "-m", "core.update_runner", "--job",
                                 str(self.work / "job.json"), "--recover"], cwd=helper,
                                capture_output=True, timeout=30,
                                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        self.assertEqual(0, result.returncode, result.stderr.decode("utf-8", "replace"))
        self.assertEqual("print('old')\n", (self.root / "main.py").read_text())
        self.assertFalse((self.root / update.PENDING_RECORD).exists())

    def test_recovery_will_not_undo_live_installer(self):
        self.installation()
        job = self.job()
        helper = self.helper(job)
        pending = update.read_json(self.root / update.PENDING_RECORD)
        pending["installer_pid"] = os.getpid()
        update.atomic_json(self.root / update.PENDING_RECORD, pending)
        result = subprocess.run([sys.executable, "-m", "core.update_runner", "--job",
                                 str(self.work / "job.json"), "--recover"], cwd=helper,
                                capture_output=True, timeout=30,
                                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        self.assertNotEqual(0, result.returncode)
        self.assertTrue((self.root / update.PENDING_RECORD).exists())

    def test_external_installer_requires_completed_safe_exit_handoff(self):
        self.installation()
        job = self.job()
        helper = self.helper(job)
        pending = update.read_json(self.root / update.PENDING_RECORD)
        pending.pop("authorized")
        update.atomic_json(self.root / update.PENDING_RECORD, pending)
        result = subprocess.run([sys.executable, "-m", "core.update_runner", "--job",
                                 str(self.work / "job.json")], cwd=helper,
                                capture_output=True, timeout=30,
                                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        self.assertNotEqual(0, result.returncode)
        self.assertEqual("print('old')\n", (self.root / "main.py").read_text())
        self.assertFalse((self.work / "state.json").exists())

    def test_install_removes_only_managed_obsolete_files_and_rollback_restores_them(self):
        self.installation()
        job = self.job()
        before = {name: (self.root / name).read_bytes() for name in ("main.py", "gui/obsolete.py", update.INSTALL_RECORD)}
        runner.apply_files(self.work, job)
        self.assertFalse((self.root / "gui/obsolete.py").exists())
        self.assertEqual("print('new')\n", (self.root / "main.py").read_text())
        self.assertEqual("keep me", (self.root / "local/operator.txt").read_text())
        self.assertEqual("original measurement", (self.root / "measurements/sample.tiff").read_text())
        self.assertEqual(self.offer.sha, update.installed_sha(self.root))
        runner.rollback(self.work, job)
        for name, content in before.items():
            self.assertEqual(content, (self.root / name).read_bytes(), name)
        self.assertFalse((self.root / "gui/app.py").exists())
        self.assertFalse((self.root / update.RUNTIME_RECORD).exists())
        runner.rollback(self.work, job)  # Recovery can be repeated safely.

    def test_write_failure_restores_every_replaced_file(self):
        self.installation()
        job = self.job()
        replace = runner.replace_file
        def fail_once(source, destination):
            if source == self.work / "package/main.py":
                raise PermissionError("locked application file")
            replace(source, destination)
        with patch.object(runner, "replace_file", side_effect=fail_once):
            with self.assertRaises(PermissionError):
                runner.apply_files(self.work, job)
        runner.rollback(self.work, job)
        self.assertEqual("print('old')\n", (self.root / "main.py").read_text())
        self.assertTrue((self.root / "gui/obsolete.py").exists())
        self.assertFalse((self.root / "gui/app.py").exists())

    def test_startup_health_commits_update(self):
        self.installation()
        job = self.job()
        def start(work, _job):
            update.atomic_json(work / "health.json", {"token": job["token"]})
            return Mock(poll=Mock(return_value=None))
        with patch.object(runner, "start_application", side_effect=start):
            runner.finish_update(self.work, job)
        self.assertEqual("success", update.read_json(self.work / "result.json")["status"])
        self.assertFalse((self.root / update.PENDING_RECORD).exists())

    def test_failed_startup_restores_program_and_configuration(self):
        self.installation()
        job = self.job()
        def start(_work, _job, **kwargs):
            if not kwargs.get("previous"):
                self.write(self.data, "recipes.json", '{"schema": "incompatible"}')
            return Mock(poll=Mock(return_value=1))
        with patch.object(runner, "start_application", side_effect=start) as start_mock:
            with self.assertLogs("core.update_runner", level="ERROR"):
                runner.finish_update(self.work, job)
        self.assertEqual("print('old')\n", (self.root / "main.py").read_text())
        self.assertEqual('{"recipes": ["old"]}', (self.data / "recipes.json").read_text())
        self.assertEqual("rolled_back", update.read_json(self.work / "result.json")["status"])
        self.assertTrue(start_mock.call_args.kwargs["previous"])

    def test_new_process_uses_new_environment_and_disables_automatic_connections(self):
        self.installation()
        job = self.job()
        with patch.object(runner.subprocess, "Popen") as popen:
            runner.start_application(self.work, job)
        self.assertEqual("new-python", popen.call_args.args[0][0])
        self.assertEqual("1", popen.call_args.kwargs["env"]["LUMINESCENCE_SKIP_AUTOCONNECT"])
        self.assertEqual(job["token"], popen.call_args.kwargs["env"]["LUMINESCENCE_UPDATE_TOKEN"])

    def test_tampered_prepared_files_never_start_transaction(self):
        self.installation()
        job = self.job()
        self.write(self.work / "package", "main.py", "tampered")
        with self.assertRaises(update.UpdateError):
            runner.apply_files(self.work, job)
        self.assertFalse((self.work / "state.json").exists())
        self.assertEqual("print('old')\n", (self.root / "main.py").read_text())


if __name__ == "__main__":
    unittest.main()
