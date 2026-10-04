"""Task mutation/recovery contracts through public subprocesses and real files."""

import hashlib
from contextlib import contextmanager
import json
import os
from pathlib import Path
import stat
import subprocess
import sys
import tempfile
import time
import unittest


ROOT = Path(__file__).resolve().parents[1]


class TaskWriteCliTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name)
        self.workspace = self.base / "project"
        self.task = self.workspace / "tasks" / "review"
        self.command("new", self.workspace, "--project-id", "synthetic-write",
                     "--workflow", "ecommerce-catalog", "--task-id", "review", "--apply")

    def command(self, *args: object, ok: bool = True) -> dict:
        result = subprocess.run([sys.executable, "-m", "agent_workflow", *(str(arg) for arg in args)],
                                cwd=ROOT, capture_output=True, text=True, check=False, timeout=30)
        self.assertEqual(result.returncode, 0 if ok else 2, result.stdout + result.stderr)
        payload = json.loads(result.stdout)
        self.assertEqual(payload["ok"], ok, payload)
        return payload

    def hashes(self) -> dict[str, str]:
        return {path.relative_to(self.workspace).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest()
                for path in self.workspace.rglob("*") if path.is_file()}

    def write_payload(self, price: int = 3) -> None:
        (self.task / "payload.json").write_text(json.dumps({
            "sku": "SYN-WRITE", "title": "合成写入资料", "price": price,
            "currency": "CNY", "synthetic": True,
        }, ensure_ascii=False), encoding="utf-8")

    def operation(self, kind: str) -> list[object]:
        if kind == "advance":
            self.write_payload()
            return [kind, self.workspace, "--task-id", "review"]
        if kind == "decision":
            self.write_payload()
            self.command("advance", self.workspace, "--task-id", "review", "--apply")
            (self.task / "review.md").write_text("# 合成审核\n\n## 检查结论\n只核验临时资料。\n", encoding="utf-8")
            return [kind, self.workspace, "--task-id", "review", "--decision-id", "review-acceptance",
                    "--answer", "accept", "--by", "synthetic-reviewer"]
        return ["task-plan", self.workspace, "--task-id", "review", "--mode", "full-auto",
                "--next-action", "Inspect synthetic records."]

    def test_precommit_type_conflict_preserves_original_fact_and_reports_not_completed(self) -> None:
        path = self.task / "task.json"
        original = path.read_bytes()
        saved = self.base / "original-fact.json"
        index = (self.task / "workflow-state.json").read_bytes()
        with self.paused_command(*self.operation("task-plan"), "--apply", path=path,
                                 event="os.rename", target=1) as (proc, release):
            path.rename(saved)
            path.mkdir()  # Real destination-type conflict, not a patched writer.
            release.touch()
            output, errors = proc.communicate(timeout=20)
        self.assertEqual(proc.returncode, 2, output + errors)
        result = json.loads(output)
        self.assertFalse(result["ok"])
        self.assertEqual(result["completion"]["operation"], "not_completed")
        self.assertEqual(saved.read_bytes(), original)
        self.assertEqual((self.task / "workflow-state.json").read_bytes(), index)
        self.assertEqual(list(path.iterdir()), [])
        path.rmdir()
        saved.rename(path)
        self.assertEqual(self.command("status", self.workspace, "--task-id", "review")["task"]["mode"], "assisted")
        self.assertFalse((self.task / ".task-write-lock").exists())

    def test_access_denied_before_replace_reports_uncommitted_and_preserves_fact(self) -> None:
        path = self.task / "task.json"
        original = path.read_bytes()
        index = (self.task / "workflow-state.json").read_bytes()
        # Windows read-only destination forbids replacement; POSIX directory
        # permissions forbid rename. Both are genuine OS failures, not mocks.
        restricted = path if os.name == "nt" else self.task
        previous_mode = stat.S_IMODE(restricted.stat().st_mode)
        try:
            with self.paused_command(*self.operation("task-plan"), "--apply", path=path,
                                     event="os.rename", target=1) as (proc, release):
                restricted.chmod(0o444 if os.name == "nt" else 0o500)
                release.touch()
                output, errors = proc.communicate(timeout=20)
        finally:
            restricted.chmod(previous_mode)
        self.assertEqual(proc.returncode, 2, output + errors)
        result = json.loads(output)
        self.assertEqual(result["completion"]["operation"], "not_completed")
        self.assertEqual(path.read_bytes(), original)
        self.assertEqual((self.task / "workflow-state.json").read_bytes(), index)
        lock = self.task / ".task-write-lock"
        if lock.exists():
            self.assertEqual(result["completion"]["lock_cleanup"], "incomplete")
            self.assertEqual(list(lock.iterdir()), [])
            lock.rmdir()  # Test-owned empty lock after the real holder has exited.
        self.assertEqual(self.command("status", self.workspace, "--task-id", "review")["task"]["mode"], "assisted")

    def test_each_change_retains_committed_facts_when_index_fails_and_repairs_without_replay(self) -> None:
        for kind in ("advance", "decision", "task-plan"):
            with self.subTest(operation=kind):
                self.workspace = self.base / kind
                self.task = self.workspace / "tasks" / "review"
                self.command("new", self.workspace, "--project-id", "synthetic-recovery",
                             "--workflow", "ecommerce-catalog", "--task-id", "review", "--apply")
                args = self.operation(kind)
                facts_path = self.task / "task.json"
                before = json.loads(facts_path.read_text(encoding="utf-8"))
                index = self.task / "workflow-state.json"
                with self.paused_command(*args, "--apply", path=index, event="os.rename", target=1) as (proc, release):
                    index.unlink()
                    index.mkdir()  # Blocks only the derived-index replacement.
                    release.touch()
                    output, errors = proc.communicate(timeout=20)
                self.assertEqual(proc.returncode, 0, output + errors)
                result = json.loads(output)
                completion = result["completion"]
                self.assertEqual(completion["operation"], "completed")
                self.assertEqual(completion["local_record"], "incomplete")
                self.assertFalse(completion["repeat_operation"])
                self.assertEqual(completion["recovery"], ["context", str(self.workspace), "--task-id", "review", "--write"])
                status = self.command("status", self.workspace, "--task-id", "review")
                expected = {"advance": ("review", "assisted"), "decision": ("review", "assisted"),
                            "task-plan": ("collect", "full-auto")}[kind]
                self.assertEqual((status["task"]["stage"], status["task"]["mode"]), expected)
                after = json.loads(facts_path.read_text(encoding="utf-8"))
                changed = {"advance": {"stage", "next_action"}, "decision": {"decisions"},
                           "task-plan": {"mode", "next_action"}}[kind]
                self.assertEqual({key: value for key, value in after.items() if key not in changed},
                                 {key: value for key, value in before.items() if key not in changed})
                if kind == "decision":
                    self.assertTrue(next(check for check in status["checks"] if check["id"] == "review-acceptance")["passed"])
                committed_hash = hashlib.sha256(facts_path.read_bytes()).hexdigest()
                self.assertEqual(status["sources"]["tasks/review/task.json"], committed_hash)
                index.rmdir()  # Remove only the empty, test-owned obstruction.
                self.command(*completion["recovery"])
                checked = self.command("context", self.workspace, "--task-id", "review", "--check")
                self.assertTrue(checked["snapshot_matches"])
                self.assertEqual(checked["sources"]["tasks/review/task.json"], committed_hash)
                self.assertEqual(hashlib.sha256(facts_path.read_bytes()).hexdigest(), committed_hash)

    def test_competing_changes_and_index_repair_are_busy_while_holder_commits_once(self) -> None:
        before = (self.task / "task.json").read_bytes()
        with self.paused_command(*self.operation("task-plan"), "--apply", path=self.task / "task.json") as (proc, release):
            for args in (
                ["advance"],
                ["decision", "--decision-id", "review-acceptance", "--answer", "accept", "--by", "synthetic-other"],
                ["task-plan", "--mode", "manual-review"],
                ["context", "--write"],
            ):
                command = [args[0], self.workspace, "--task-id", "review", *args[1:]]
                if args[0] != "context":
                    command.append("--apply")
                result = self.command(*command, ok=False)
                self.assertEqual(result["error"]["code"], "task_busy")
                self.assertEqual((self.task / "task.json").read_bytes(), before)
            release.touch()
            output, errors = proc.communicate(timeout=20)
        self.assertEqual(proc.returncode, 0, output + errors)
        self.assertEqual(json.loads(output)["completion"]["local_record"], "complete")
        checked = self.command("context", self.workspace, "--task-id", "review", "--check")
        self.assertEqual(checked["task"]["stage"], "collect")
        self.assertEqual(checked["task"]["mode"], "full-auto")
        self.assertTrue(checked["snapshot_matches"])

    def test_index_repair_also_holds_lock_until_its_current_view_is_saved(self) -> None:
        self.write_payload()
        before = (self.task / "task.json").read_bytes()
        with self.paused_command("context", self.workspace, "--task-id", "review", "--write",
                                 path=self.task / "task.json") as (proc, release):
            competing = self.command(*self.operation("task-plan"), "--apply", ok=False)
            self.assertEqual(competing["error"]["code"], "task_busy")
            self.assertEqual((self.task / "task.json").read_bytes(), before)
            release.touch()
            output, errors = proc.communicate(timeout=20)
        self.assertEqual(proc.returncode, 0, output + errors)
        self.assertTrue(json.loads(output)["snapshot_matches"])
        # A newer admitted writer owns the final index; the old repair is over.
        self.command(*self.operation("task-plan"), "--apply")
        checked = self.command("context", self.workspace, "--task-id", "review", "--check")
        self.assertTrue(checked["snapshot_matches"])
        self.assertEqual(checked["task"]["mode"], "full-auto")

    def test_preview_is_read_only_and_cannot_authorize_advance_after_evidence_changes(self) -> None:
        args = self.operation("advance")
        before = self.hashes()
        preview = self.command(*args)
        self.assertFalse(preview["applied"])
        self.assertEqual(self.hashes(), before)
        self.write_payload(price=-3)
        changed = self.hashes()
        rejected = self.command(*args, "--apply", ok=False)
        self.assertEqual(rejected["error"]["code"], "transition_blocked")
        self.assertEqual(rejected["completion"]["operation"], "not_completed")
        self.assertEqual(self.hashes(), changed)
        self.assertEqual(self.command("status", self.workspace, "--task-id", "review")["task"]["stage"], "collect")

    def test_each_admission_rechecks_changes_made_before_lock_inner_capture(self) -> None:
        for kind in ("advance", "decision", "task-plan"):
            with self.subTest(operation=kind):
                self.workspace = self.base / f"changed-before-lock-{kind}"
                self.task = self.workspace / "tasks" / "review"
                self.command("new", self.workspace, "--project-id", "synthetic-admission",
                             "--workflow", "ecommerce-catalog", "--task-id", "review", "--apply")
                args = self.operation(kind)
                self.command(*args)  # Earlier preview is explicitly not a permit.
                with self.paused_command(*args, "--apply", path=self.task / ".task-write-lock",
                                         event="os.mkdir") as (proc, release):
                    if kind == "advance":
                        self.write_payload(price=-3)
                        expected = "transition_blocked"
                    elif kind == "decision":
                        path = self.task / "task.json"
                        facts = json.loads(path.read_text(encoding="utf-8"))
                        facts["stage"] = "collect"
                        path.write_text(json.dumps(facts), encoding="utf-8")
                        expected = "invalid_decision"
                    else:
                        path = self.workspace / "project.json"
                        path.write_text(json.dumps({"schema_version": "1.0", "project_id": "synthetic-other"}), encoding="utf-8")
                        expected = "task_identity_mismatch"
                    externally_changed = self.hashes()
                    release.touch()
                    output, errors = proc.communicate(timeout=20)
                self.assertEqual(proc.returncode, 2, output + errors)
                rejected = json.loads(output)
                self.assertEqual(rejected["error"]["code"], expected)
                self.assertEqual(rejected["completion"]["operation"], "not_completed")
                self.assertEqual(self.hashes(), externally_changed)

    def test_decision_uses_reverified_evidence_and_preserves_external_metadata_update(self) -> None:
        args = self.operation("decision")
        with self.paused_command(*args, "--apply", path=self.task / "payload.json") as (proc, release):
            self.write_payload(price=7)
            path = self.task / "task.json"
            facts = json.loads(path.read_text(encoding="utf-8"))
            facts["mode"] = "manual-review"
            facts["next_action"] = "Externally updated synthetic next step."
            path.write_text(json.dumps(facts), encoding="utf-8")
            (self.task / "added.md").write_text("Synthetic evidence supplied during admission.", encoding="utf-8")
            release.touch()
            output, errors = proc.communicate(timeout=20)
        self.assertEqual(proc.returncode, 0, output + errors)
        checked = self.command("context", self.workspace, "--task-id", "review", "--check")
        self.assertEqual(checked["task"]["mode"], "manual-review")
        self.assertEqual(checked["task"]["next_action"], "Externally updated synthetic next step.")
        self.assertTrue(checked["can_advance"])
        self.assertEqual(checked["pending_decisions"], [])
        self.assertIn("tasks/review/added.md", checked["sources"])
        self.assertEqual(checked["sources"]["tasks/review/task.json"], hashlib.sha256(path.read_bytes()).hexdigest())

    def test_valid_decision_and_plan_do_not_require_unrelated_content_checks_to_pass(self) -> None:
        self.write_payload()
        self.command("advance", self.workspace, "--task-id", "review", "--apply")
        # review.md intentionally stays an empty template.
        decision = ["decision", self.workspace, "--task-id", "review", "--decision-id", "review-acceptance",
                    "--answer", "accept", "--by", "synthetic-reviewer"]
        for args in (decision, self.operation("task-plan")):
            before = self.hashes()
            self.assertFalse(self.command(*args)["applied"])
            self.assertEqual(self.hashes(), before)
            self.assertEqual(self.command(*args, "--apply")["completion"]["operation"], "completed")
        checked = self.command("context", self.workspace, "--task-id", "review", "--check")
        self.assertFalse(checked["can_advance"])
        checks = {check["id"]: check["passed"] for check in checked["checks"]}
        self.assertTrue(checks["review-acceptance"])
        self.assertFalse(checks["review-evidence"])
        self.assertEqual(checked["task"]["mode"], "full-auto")

    def test_oversized_content_fails_its_check_without_blocking_valid_answer_or_plan(self) -> None:
        self.write_payload()
        self.command("advance", self.workspace, "--task-id", "review", "--apply")
        (self.task / "review.md").write_bytes(b"Synthetic bounded-input rejection.\n" * 40_000)
        self.command("decision", self.workspace, "--task-id", "review", "--decision-id", "review-acceptance",
                     "--answer", "accept", "--by", "synthetic-reviewer", "--apply")
        self.command(*self.operation("task-plan"), "--apply")
        checked = self.command("context", self.workspace, "--task-id", "review", "--check")
        self.assertFalse(checked["can_advance"])
        self.assertFalse(next(check for check in checked["checks"] if check["id"] == "review-evidence")["passed"])
        self.assertTrue(next(check for check in checked["checks"] if check["id"] == "review-acceptance")["passed"])
        before = self.hashes()
        self.assertEqual(self.command("advance", self.workspace, "--task-id", "review", "--apply", ok=False)["error"]["code"],
                         "transition_blocked")
        self.assertEqual(self.hashes(), before)

    def test_invalid_arguments_or_identity_never_change_facts_or_index(self) -> None:
        cases = (
            ["advance", self.workspace, "--task-id", "wrong-task", "--apply"],
            ["decision", self.workspace, "--task-id", "review", "--decision-id", "review-acceptance",
             "--answer", "undefined", "--by", "synthetic-reviewer", "--apply"],
            ["decision", self.workspace, "--task-id", "review", "--decision-id", "review-acceptance",
             "--answer", "accept", "--by", "", "--apply"],
            ["task-plan", self.workspace, "--task-id", "review", "--mode", "undefined", "--apply"],
            ["task-plan", self.workspace, "--task-id", "review", "--next-action", "", "--apply"],
        )
        before = self.hashes()
        for args in cases:
            with self.subTest(command=args[0]):
                self.command(*args, ok=False)
                self.assertEqual(self.hashes(), before)
                self.assertFalse((self.task / ".task-write-lock").exists())

    @contextmanager
    def paused_command(self, *args: object, path: Path | None, event: str = "open", target: int = 0,
                       parent: Path | None = None, prefix: str = "", ancestor: Path | None = None,
                       directory_prefix: str = ""):
        config, signal, release = self.base / "observe.json", self.base / "reached", self.base / "release"
        signal.unlink(missing_ok=True)
        release.unlink(missing_ok=True)
        config.write_text(json.dumps({
            "watch_root": str(self.workspace), "pause_path": str(path) if path else None,
            "pause_event": event, "pause_target": target, "signal": str(signal), "release": str(release),
            "pause_parent": str(parent) if parent else None, "pause_name_prefix": prefix,
            "pause_ancestor": str(ancestor) if ancestor else None, "pause_directory_prefix": directory_prefix,
        }), encoding="utf-8")
        proc = subprocess.Popen([sys.executable, str(ROOT / "tests/support/observe_cli.py"),
                                 "--config", str(config), "--", *(str(arg) for arg in args)],
                                cwd=ROOT, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        try:
            deadline = time.monotonic() + 15
            while not signal.exists() and proc.poll() is None and time.monotonic() < deadline:
                time.sleep(0.01)
            self.assertTrue(signal.exists(), "public subprocess did not reach the coordinated file operation")
            yield proc, release
        finally:
            if proc.poll() is None:
                proc.kill()
                proc.communicate()

    def test_fact_commit_is_not_reclassified_when_temporary_cleanup_is_obstructed(self) -> None:
        with self.paused_command(*self.operation("task-plan"), "--apply", path=None,
                                 event="os.remove", parent=self.task, prefix=".write-") as (proc, release):
            temporary = Path((self.base / "reached").read_text(encoding="utf-8"))
            self.assertEqual(temporary.parent, self.task)
            self.assertFalse(temporary.exists(), "fact replacement must already have moved the staged file")
            temporary.mkdir()  # Re-occupy the cleanup name with an unknown directory.
            release.touch()
            output, errors = proc.communicate(timeout=20)
        self.assertEqual(proc.returncode, 0, output + errors)
        result = json.loads(output)
        self.assertEqual(result["completion"]["operation"], "completed")
        self.assertFalse(result["completion"]["repeat_operation"])
        self.assertEqual(result["completion"]["file_cleanup"], "incomplete")
        self.assertTrue(temporary.is_dir(), "cleanup must not remove an unknown replacement")
        checked = self.command("context", self.workspace, "--task-id", "review", "--check")
        self.assertEqual(checked["task"]["mode"], "full-auto")
        self.assertTrue(checked["snapshot_matches"])

    def test_postcommit_schema_error_is_incomplete_record_not_uncommitted_operation(self) -> None:
        with self.paused_command(*self.operation("task-plan"), "--apply", path=None,
                                 event="os.remove", parent=self.task, prefix=".write-") as (proc, release):
            path = self.task / "task.json"
            committed = json.loads(path.read_text(encoding="utf-8"))
            self.assertEqual(committed["mode"], "full-auto", "the requested plan must already be committed")
            invalid = {**committed, "mode": []}
            path.write_text(json.dumps(invalid), encoding="utf-8")
            externally_changed = path.read_bytes()
            release.touch()
            output, errors = proc.communicate(timeout=20)
        self.assertEqual(proc.returncode, 0, output + errors)
        result = json.loads(output)
        self.assertEqual(result["completion"]["operation"], "completed")
        self.assertEqual(result["completion"]["local_record"], "incomplete")
        self.assertFalse(result["completion"]["repeat_operation"])
        self.assertEqual(path.read_bytes(), externally_changed)
        # Repair only the test-owned corrupt metadata, then rebuild the index.
        path.write_text(json.dumps(committed), encoding="utf-8")
        self.command(*result["completion"]["recovery"])
        self.assertTrue(self.command("context", self.workspace, "--task-id", "review", "--check")["snapshot_matches"])

    def test_new_preserves_interrupted_staging_without_moving_unknown_cleanup_content(self) -> None:
        workspace = self.base / "new-project"
        with self.paused_command("new", workspace, "--project-id", "synthetic-new-cleanup",
                                 "--workflow", "ecommerce-catalog", "--task-id", "review", "--apply",
                                 path=None, event="os.remove", ancestor=self.base,
                                 directory_prefix=".agent-workflow-new-", prefix=".write-") as (proc, release):
            replaced = Path((self.base / "reached").read_text(encoding="utf-8"))
            self.assertFalse(replaced.exists())
            replaced.mkdir()
            marker = replaced / "unknown-owner.txt"
            marker.write_text("Synthetic unknown staging replacement; preserve for inspection.", encoding="utf-8")
            release.touch()
            output, errors = proc.communicate(timeout=20)
        self.assertEqual(proc.returncode, 2, output + errors)
        result = json.loads(output)
        self.assertEqual(result["error"]["code"], "workspace_creation_incomplete")
        self.assertFalse(workspace.exists(), "do not publish staging whose cleanup is incomplete")
        self.assertTrue(marker.is_file(), "do not recursively delete unknown staging content")

    def test_committed_plan_survives_unlock_failure_without_false_failure_or_replay(self) -> None:
        lock = self.task / ".task-write-lock"
        with self.paused_command("task-plan", self.workspace, "--task-id", "review",
                                 "--mode", "full-auto", "--next-action", "Inspect synthetic records.",
                                 "--apply", path=lock, event="os.rmdir") as (proc, release):
            marker = lock / "unknown-owner.txt"
            marker.write_text("Synthetic external occupation; must survive cleanup.", encoding="utf-8")
            release.touch()
            output, errors = proc.communicate(timeout=20)
        self.assertEqual(proc.returncode, 0, output + errors)
        result = json.loads(output)
        self.assertTrue(result["ok"])
        completion = result["completion"]
        self.assertEqual(completion["operation"], "completed")
        self.assertFalse(completion["repeat_operation"])
        self.assertEqual(completion["lock_cleanup"], "incomplete")
        self.assertEqual(self.command("status", self.workspace, "--task-id", "review")["task"]["mode"], "full-auto")
        self.assertTrue(marker.is_file())

    def test_changed_lock_owner_is_preserved_after_commit(self) -> None:
        lock = self.task / ".task-write-lock"
        relocated = self.base / "old-owned-lock"
        with self.paused_command(*self.operation("task-plan"), "--apply", path=self.task / "workflow-state.json",
                                 event="os.rename", target=1) as (proc, release):
            lock.rename(relocated)
            lock.mkdir()  # Unknown, empty replacement must not be auto-deleted.
            release.touch()
            output, errors = proc.communicate(timeout=20)
        self.assertEqual(proc.returncode, 0, output + errors)
        result = json.loads(output)
        self.assertEqual(result["completion"]["operation"], "completed")
        self.assertEqual(result["completion"]["lock_cleanup"], "incomplete")
        self.assertFalse(result["completion"]["repeat_operation"])
        self.assertTrue(lock.is_dir())
        self.assertTrue(relocated.is_dir())
        self.assertEqual(self.command("status", self.workspace, "--task-id", "review")["task"]["mode"], "full-auto")

    def test_index_repair_completion_survives_unlock_failure_without_changing_facts(self) -> None:
        facts = (self.task / "task.json").read_bytes()
        lock = self.task / ".task-write-lock"
        with self.paused_command("context", self.workspace, "--task-id", "review", "--write",
                                 path=lock, event="os.rmdir") as (proc, release):
            (lock / "unknown-owner.txt").write_text("Synthetic obstruction after index commit.", encoding="utf-8")
            release.touch()
            output, errors = proc.communicate(timeout=20)
        self.assertEqual(proc.returncode, 0, output + errors)
        result = json.loads(output)
        self.assertEqual(result["completion"]["operation"], "completed")
        self.assertEqual(result["completion"]["lock_cleanup"], "incomplete")
        self.assertFalse(result["completion"]["repeat_operation"])
        self.assertEqual((self.task / "task.json").read_bytes(), facts)
        self.assertTrue((self.task / "workflow-state.json").is_file())

    def test_index_repair_is_busy_under_task_lock_but_queries_and_hook_stay_read_only(self) -> None:
        lock = self.task / ".task-write-lock"
        lock.mkdir()
        (lock / "unknown-owner.txt").write_text("Synthetic occupied lock; do not delete.", encoding="utf-8")
        before = self.hashes()
        result = self.command("context", self.workspace, "--task-id", "review", "--write", ok=False)
        self.assertEqual(result["error"]["code"], "task_busy")
        self.command("status", self.workspace, "--task-id", "review")
        self.command("context", self.workspace, "--task-id", "review")
        env = {**os.environ, "AGENT_WORKFLOW_WORKSPACE": str(self.workspace), "AGENT_WORKFLOW_TASK_ID": "review"}
        hook = subprocess.run([sys.executable, "scripts/context_hook.py", "--event", "SessionStart"],
                              cwd=ROOT, env=env, capture_output=True, text=True, check=False)
        self.assertEqual(hook.returncode, 0, hook.stdout + hook.stderr)
        self.assertEqual(self.hashes(), before)
        self.assertTrue(lock.is_dir())


if __name__ == "__main__":
    unittest.main()
