"""Existing-project optional documents through the public CLI and real files."""

import hashlib
from contextlib import contextmanager
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import time
import unittest


ROOT = Path(__file__).resolve().parents[1]
DOCUMENTS = ("architecture", "environment", "progress", "results", "summary")


class ProjectDocumentCompletionTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name)
        self.workspace = self.base / "project"
        self.task_id = "synthetic-planning"
        self.command("start", self.workspace, "--project-id", "synthetic-completion",
                     "--name", "SYNTHETIC_PROJECT_NAME", "--brief", "SYNTHETIC_PROJECT_GOAL",
                     "--task-id", self.task_id, "--mode", "manual-review", "--apply")

    def command(self, *args: object, ok: bool = True, runtime: Path = ROOT) -> dict:
        proc = subprocess.run([sys.executable, "-m", "agent_workflow", *(str(arg) for arg in args)],
                              cwd=runtime, capture_output=True, text=True, check=False, timeout=30)
        self.assertEqual(proc.returncode, 0 if ok else 2, proc.stdout + proc.stderr)
        result = json.loads(proc.stdout)
        self.assertEqual(result["ok"], ok, result)
        return result

    def args(self, *documents: str) -> list[object]:
        args: list[object] = ["project-docs", self.workspace, "--task-id", self.task_id]
        for document in documents:
            args.extend(("--with-docs", document))
        return args

    def hashes(self) -> dict[str, str]:
        return {path.relative_to(self.workspace).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest()
                for path in self.workspace.rglob("*") if path.is_file()}

    def link_fixture(self, path: Path, target: Path) -> None:
        if os.name == "nt":
            # Junctions do not require developer mode/admin, and are reparse points.
            result = subprocess.run(["cmd.exe", "/c", "mklink", "/J", str(path), str(target)],
                                    capture_output=True, text=True, check=False, timeout=15)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        else:
            path.symlink_to(target, target_is_directory=target.is_dir())

    def remove_link_fixture(self, path: Path) -> None:
        if os.name == "nt":
            path.rmdir()  # Removes only the test-owned junction, never its target.
        else:
            path.unlink()

    @contextmanager
    def pause_public_link(self, args: list[object], document: str):
        config, signal, release = self.base / "observe.json", self.base / "reached", self.base / "release"
        signal.unlink(missing_ok=True)
        release.unlink(missing_ok=True)
        config.write_text(json.dumps({
            "watch_root": str(self.workspace), "pause_path": str(self.workspace / f"docs/project/{document}.md"),
            "pause_event": "os.link", "pause_target": 1, "signal": str(signal), "release": str(release),
        }), encoding="utf-8")
        proc = subprocess.Popen([sys.executable, str(ROOT / "tests/support/observe_cli.py"),
                                 "--config", str(config), "--", *(str(arg) for arg in args)],
                                cwd=ROOT, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        try:
            deadline = time.monotonic() + 15
            while not signal.exists() and proc.poll() is None and time.monotonic() < deadline:
                time.sleep(0.01)
            self.assertTrue(signal.exists(), "public document command did not reach exclusive publication")
            yield proc, release
        finally:
            if proc.poll() is None:
                proc.kill()
                proc.communicate()

    def test_preview_then_create_selected_documents_without_touching_facts_or_index(self) -> None:
        before = self.hashes()
        args = self.args("environment", "progress", "environment")
        preview = self.command(*args)
        self.assertFalse(preview["applied"])
        self.assertEqual(preview["progress"], {"created": [], "preserved": [], "pending": ["environment", "progress"]})
        self.assertEqual(self.hashes(), before)
        applied = self.command(*args, "--apply")
        self.assertTrue(applied["applied"])
        self.assertEqual(applied["progress"], {"created": ["environment", "progress"], "preserved": [], "pending": []})
        after = self.hashes()
        self.assertEqual({name: after[name] for name in before}, before)
        self.assertEqual(set(after) - set(before), {"docs/project/environment.md", "docs/project/progress.md"})
        self.assertTrue(self.command("context", self.workspace, "--task-id", self.task_id, "--check")["snapshot_matches"])

    def test_all_five_independent_completions_equal_start_templates_and_preserve_real_content(self) -> None:
        initial = self.base / "initial-with-docs"
        args: list[object] = ["start", initial, "--project-id", "synthetic-initial-docs", "--name", "SYNTHETIC_OTHER_NAME",
                              "--task-id", self.task_id, "--mode", "manual-review"]
        for document in DOCUMENTS:
            args.extend(("--with-docs", document))
        self.command(*args, "--apply")
        before = self.hashes()
        for document in DOCUMENTS:
            with self.subTest(document=document):
                result = self.command(*self.args(document), "--apply")
                self.assertEqual(result["progress"]["created"], [document])
                path = self.workspace / f"docs/project/{document}.md"
                self.assertEqual(path.read_bytes(), (initial / f"docs/project/{document}.md").read_bytes())
                content = path.read_text(encoding="utf-8")
                self.assertNotIn("{{TASK_ID}}", content)
                self.assertNotIn("SYNTHETIC_PROJECT_NAME", content)
                self.assertNotIn("SYNTHETIC_PROJECT_GOAL", content)
                if document != "results":
                    self.assertIn(f"tasks/{self.task_id}", content)
        self.assertEqual({name: self.hashes()[name] for name in before}, before)
        summary = (self.workspace / "docs/project/summary.md").read_text(encoding="utf-8")
        self.assertRegex(summary, r"\A---\nstatus: draft\n---")
        self.assertNotRegex(summary, r"(?im)^completed(?:_at|_on|_date)?\s*:")
        for document in ("summary", "results"):
            content = (self.workspace / f"docs/project/{document}.md").read_text(encoding="utf-8")
            self.assertEqual(len([line for line in content.splitlines() if line.startswith("|")]), 2)
        preserved = self.workspace / "docs/project/environment.md"
        preserved.write_bytes(b"Synthetic user-owned modified document.\x00\xff")
        populated = self.hashes()
        for apply in (False, True):
            args = self.args(*DOCUMENTS, "summary", "environment")
            if apply:
                args.append("--apply")
            result = self.command(*args)
            self.assertEqual(result["progress"], {"created": [], "preserved": list(DOCUMENTS), "pending": []})
            self.assertEqual(self.hashes(), populated)
        self.assertTrue(self.command("context", self.workspace, "--task-id", self.task_id, "--check")["snapshot_matches"])

    def test_middle_failure_reports_partial_progress_and_recovers_only_missing_documents(self) -> None:
        directory = self.workspace / "docs/project"
        directory.mkdir()
        (directory / "progress.md").write_text("Synthetic existing user event.", encoding="utf-8")
        before = self.hashes()
        args = self.args("summary", "environment", "architecture", "progress", "environment")
        preview = self.command(*args)
        self.assertEqual(preview["progress"], {"created": [], "preserved": ["progress"],
                                              "pending": ["architecture", "environment", "summary"]})
        with self.pause_public_link([*args, "--apply"], "environment") as (proc, release):
            blocked = directory / "environment.md"
            blocked.mkdir()  # Real mid-run target conflict after architecture was created.
            release.touch()
            output, errors = proc.communicate(timeout=20)
        self.assertEqual(proc.returncode, 2, output + errors)
        failed = json.loads(output)
        self.assertFalse(failed["ok"])
        self.assertEqual(failed["error"]["code"], "invalid_document_target")
        self.assertEqual(failed["progress"], {"created": ["architecture"], "preserved": ["progress"],
                                             "pending": ["environment", "summary"]})
        partial = self.hashes()
        self.assertEqual({name: partial[name] for name in before}, before)
        self.assertTrue((directory / "architecture.md").is_file())
        self.assertFalse((directory / "summary.md").exists())
        blocked.rmdir()  # Only the empty, test-owned obstruction, not prior documents.
        recovered = self.command(*args, "--apply")
        self.assertEqual(recovered["progress"], {"created": ["environment", "summary"],
                                                "preserved": ["architecture", "progress"], "pending": []})
        self.assertEqual({name: self.hashes()[name] for name in partial}, partial)
        self.assertTrue(self.command("context", self.workspace, "--task-id", self.task_id, "--check")["snapshot_matches"])

    def test_competing_ordinary_file_is_preserved_at_exclusive_publication(self) -> None:
        args = self.args("environment")
        self.command(*args)  # Missing at preview time.
        before = self.hashes()
        with self.pause_public_link([*args, "--apply"], "environment") as (proc, release):
            target = self.workspace / "docs/project/environment.md"
            supplied = b"Synthetic file from another writer.\x00\xff"
            target.write_bytes(supplied)
            release.touch()
            output, errors = proc.communicate(timeout=20)
        self.assertEqual(proc.returncode, 0, output + errors)
        result = json.loads(output)
        self.assertEqual(result["progress"], {"created": [], "preserved": ["environment"], "pending": []})
        self.assertEqual(target.read_bytes(), supplied)
        self.assertEqual({name: self.hashes()[name] for name in before}, before)
        self.assertNotIn("another writer", output)

    def test_invalid_selection_identity_and_legacy_targets_are_rejected_without_writes(self) -> None:
        before = self.hashes()
        for selection in ((), ("",), ("../summary",), ("unknown",)):
            with self.subTest(selection=selection):
                failed = self.command(*self.args(*selection), "--apply", ok=False)
                self.assertEqual(failed["error"]["code"], "invalid_arguments")
                self.assertEqual(self.hashes(), before)
        for task_id in ("../escape", "missing-task", "CON"):
            with self.subTest(task_id=task_id):
                self.command("project-docs", self.workspace, "--task-id", task_id,
                             "--with-docs", "summary", "--apply", ok=False)
                self.assertEqual(self.hashes(), before)
        self.command("project-docs", self.workspace, "--with-docs", "summary", "--apply", ok=False)
        self.assertEqual(self.hashes(), before)
        legacy = self.base / "legacy"
        legacy.mkdir()
        sentinel = legacy / "keep.bin"
        supplied = b"Synthetic legacy project, not framework managed.\x00\xff"
        sentinel.write_bytes(supplied)
        for target in (legacy, self.base / "missing-project", ROOT):
            with self.subTest(target=target):
                self.command("project-docs", target, "--task-id", self.task_id,
                             "--with-docs", "summary", "--apply", ok=False)
                self.assertEqual(sentinel.read_bytes(), supplied)
                self.assertEqual(list(legacy.iterdir()), [sentinel])
                self.assertFalse((self.base / "missing-project").exists())
                self.assertEqual(self.hashes(), before)

    def test_predictable_directory_and_parent_file_conflicts_are_preflighted(self) -> None:
        directory = self.workspace / "docs/project"
        directory.mkdir()
        blocked = directory / "environment.md"
        blocked.mkdir()
        before = self.hashes()
        for apply in (False, True):
            args = self.args("architecture", "environment")
            if apply:
                args.append("--apply")
            failed = self.command(*args, ok=False)
            self.assertEqual(failed["error"]["code"], "invalid_document_target")
            self.assertEqual(failed["progress"], {"created": [], "preserved": [],
                                                 "pending": ["architecture", "environment"]})
            self.assertEqual(self.hashes(), before)
            self.assertFalse((directory / "architecture.md").exists())
        blocked.rmdir()
        directory.rmdir()
        directory.write_bytes(b"Synthetic parent file must not become a directory.")
        before = self.hashes()
        self.command(*self.args("architecture", "environment"), "--apply", ok=False)
        self.assertEqual(self.hashes(), before)

    def test_linked_workspace_parent_and_document_targets_refuse_external_writes(self) -> None:
        outside = self.base / "outside-documents"
        outside.mkdir()
        sentinel = outside / "environment.md"
        supplied = b"Synthetic external sentinel stays untouched.\x00\xff"
        sentinel.write_bytes(supplied)
        before = self.hashes()
        alias = self.base / "linked-workspace"
        self.link_fixture(alias, self.workspace)
        try:
            failed = self.command("project-docs", alias, "--task-id", self.task_id,
                                  "--with-docs", "environment", "--apply", ok=False)
            self.assertEqual(failed["error"]["code"], "unsafe_path")
        finally:
            self.remove_link_fixture(alias)
        directory = self.workspace / "docs/project"
        self.link_fixture(directory, outside)
        try:
            for apply in (False, True):
                args = self.args("architecture", "environment")
                if apply:
                    args.append("--apply")
                failed = self.command(*args, ok=False)
                self.assertEqual(failed["error"]["code"], "unsafe_path")
                self.assertEqual(failed["progress"]["created"], [])
                self.assertEqual(sentinel.read_bytes(), supplied)
                self.assertEqual(list(outside.iterdir()), [sentinel])
        finally:
            self.remove_link_fixture(directory)
        directory.mkdir()
        target = directory / "environment.md"
        self.link_fixture(target, outside if os.name == "nt" else sentinel)
        try:
            failed = self.command(*self.args("architecture", "environment"), "--apply", ok=False)
            self.assertEqual(failed["error"]["code"], "unsafe_path")
            self.assertFalse((directory / "architecture.md").exists())
        finally:
            self.remove_link_fixture(target)
        self.assertEqual(self.hashes(), before)
        self.assertEqual(sentinel.read_bytes(), supplied)

    def test_link_appearing_at_publication_is_not_idempotently_preserved(self) -> None:
        outside = self.base / "outside-race"
        outside.mkdir()
        sentinel = outside / "keep.bin"
        supplied = b"Synthetic race sentinel.\x00\xff"
        sentinel.write_bytes(supplied)
        before = self.hashes()
        with self.pause_public_link([*self.args("environment"), "--apply"], "environment") as (proc, release):
            target = self.workspace / "docs/project/environment.md"
            self.link_fixture(target, outside if os.name == "nt" else sentinel)
            release.touch()
            output, errors = proc.communicate(timeout=20)
        try:
            self.assertEqual(proc.returncode, 2, output + errors)
            result = json.loads(output)
            self.assertEqual(result["error"]["code"], "unsafe_path")
            self.assertEqual(result["progress"], {"created": [], "preserved": [], "pending": ["environment"]})
            self.assertEqual(sentinel.read_bytes(), supplied)
        finally:
            self.remove_link_fixture(target)
        self.assertEqual(self.hashes(), before)

    def test_apply_reloads_templates_and_rejects_bad_templates_before_writing(self) -> None:
        runtime = self.base / "isolated-framework"
        shutil.copytree(ROOT, runtime, ignore=shutil.ignore_patterns(
            ".git", "__pycache__", ".mypy_cache", ".ruff_cache"))
        template = runtime / "templates/project/docs/project/environment.md.tmpl"
        original = template.read_bytes()
        args = self.args("architecture", "environment")
        self.command(*args, runtime=runtime)
        before = self.hashes()
        for content in (b"{{UNSUPPORTED_TEMPLATE_TOKEN}}\n", b"x" * 1_000_001, b"\xff"):
            with self.subTest(content_type=len(content)):
                template.write_bytes(content)
                failed = self.command(*args, "--apply", runtime=runtime, ok=False)
                self.assertEqual(failed["progress"], {"created": [], "preserved": [],
                                                     "pending": ["architecture", "environment"]})
                self.assertEqual(self.hashes(), before)
                self.assertFalse((self.workspace / "docs/project").exists())
        template.unlink()
        template.mkdir()
        self.command(*args, "--apply", runtime=runtime, ok=False)
        self.assertEqual(self.hashes(), before)
        template.rmdir()
        template.write_bytes(original)
        self.command(*args, runtime=runtime)  # Preview the old valid version.
        template.write_bytes(original + b"\nSynthetic template revision for this execution.\n")
        self.command(*args, "--apply", runtime=runtime)
        rendered = (self.workspace / "docs/project/environment.md").read_text(encoding="utf-8")
        self.assertIn("Synthetic template revision for this execution.", rendered)
        self.assertIn(f"tasks/{self.task_id}", rendered)
        self.assertNotIn("{{TASK_ID}}", rendered)
        self.assertEqual({name: self.hashes()[name] for name in before}, before)

    def test_completion_does_not_change_existing_answer_stage_mode_or_evidence(self) -> None:
        task = self.workspace / "tasks" / self.task_id
        payload_path = task / "payload.json"
        payload = json.loads(payload_path.read_text(encoding="utf-8"))
        payload.update({"users": "Synthetic readers", "in_scope": "Local planning only",
                        "out_of_scope": "Any real business operations", "success_criteria": "Verify public CLI behavior"})
        payload_path.write_text(json.dumps(payload), encoding="utf-8")
        self.command("advance", self.workspace, "--task-id", self.task_id, "--apply")
        # A synthetic answer may be recorded while plan content is still incomplete.
        self.command("decision", self.workspace, "--task-id", self.task_id, "--decision-id", "plan-acceptance",
                     "--answer", "accept", "--by", "synthetic-reviewer", "--apply")
        view_before = self.command("status", self.workspace, "--task-id", self.task_id)
        self.assertFalse(view_before["can_advance"])
        self.assertTrue(next(check for check in view_before["checks"] if check["id"] == "plan-acceptance")["passed"])
        before = self.hashes()
        self.command(*self.args("summary", "results"), "--apply")
        self.assertEqual({name: self.hashes()[name] for name in before}, before)
        view_after = self.command("status", self.workspace, "--task-id", self.task_id)
        self.assertEqual(view_after["task"], view_before["task"])
        self.assertEqual(view_after["sources"], view_before["sources"])
        self.assertEqual(view_after["checks"], view_before["checks"])
        self.assertFalse(view_after["completed_locally"])
        self.assertTrue(self.command("context", self.workspace, "--task-id", self.task_id, "--check")["snapshot_matches"])

    def test_io_failure_keeps_top_level_partial_progress_and_does_not_replay_task(self) -> None:
        args = self.args("architecture", "environment", "summary")
        before = self.hashes()
        directory = self.workspace / "docs/project"
        moved = self.workspace / "docs/project-temporary-move"
        with self.pause_public_link([*args, "--apply"], "environment") as (proc, release):
            directory.rename(moved)  # Real I/O failure, not a patched production function.
            directory.write_text("Synthetic temporary parent-file obstruction.", encoding="utf-8")
            release.touch()
            output, errors = proc.communicate(timeout=20)
        self.assertEqual(proc.returncode, 2, output + errors)
        result = json.loads(output)
        self.assertEqual(result["error"]["code"], "project_document_error")
        self.assertEqual(result["progress"], {"created": ["architecture"], "preserved": [],
                                             "pending": ["environment", "summary"]})
        self.assertNotIn("temporary parent-file obstruction", output)
        self.assertTrue((moved / "architecture.md").is_file())
        self.assertEqual({name: self.hashes()[name] for name in before}, before)
        directory.unlink()  # Remove only the test-owned obstruction.
        moved.rename(directory)
        partial = self.hashes()
        recovered = self.command(*args, "--apply")
        self.assertEqual(recovered["progress"], {"created": ["environment", "summary"],
                                                "preserved": ["architecture"], "pending": []})
        self.assertEqual({name: self.hashes()[name] for name in partial}, partial)
        self.assertTrue(self.command("context", self.workspace, "--task-id", self.task_id, "--check")["snapshot_matches"])

    def test_help_and_skill_wrapper_expose_the_same_completion_entry(self) -> None:
        before = self.hashes()
        help_result = subprocess.run([sys.executable, "-m", "agent_workflow", "project-docs", "--help"],
                                     cwd=ROOT, capture_output=True, text=True, check=False, timeout=15)
        self.assertEqual(help_result.returncode, 0, help_result.stderr)
        for option in ("--task-id", "--with-docs", "--apply", *DOCUMENTS):
            self.assertIn(option, help_result.stdout)
        wrapped = subprocess.run([sys.executable, str(ROOT / ".skillshare/skills/project-start/scripts/start_project.py"),
                                  "--framework", str(ROOT), "--", *(str(arg) for arg in self.args("progress"))],
                                 cwd=self.workspace, capture_output=True, text=True, check=False, timeout=20)
        self.assertEqual(wrapped.returncode, 0, wrapped.stdout + wrapped.stderr)
        self.assertEqual(json.loads(wrapped.stdout)["progress"], {"created": [], "preserved": [], "pending": ["progress"]})
        self.assertEqual(self.hashes(), before)


if __name__ == "__main__":
    unittest.main()
