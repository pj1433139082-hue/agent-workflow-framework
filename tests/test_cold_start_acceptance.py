"""Joint public-path acceptance: planning, handoff and distinct recoveries."""

from contextlib import contextmanager
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time
import unittest


ROOT = Path(__file__).resolve().parents[1]


class ColdStartAcceptanceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name)
        self.workspace = self.base / "synthetic-project"
        self.task_id = "launch-not-kickoff"

    def command(self, *args: object, ok: bool = True) -> dict:
        result = subprocess.run([sys.executable, "-m", "agent_workflow", *(str(arg) for arg in args)],
                                cwd=ROOT, capture_output=True, text=True, check=False, timeout=30)
        return self.assert_cli_response(result.returncode, result.stdout, result.stderr, ok=ok)

    def assert_cli_response(self, code: int, output: str, errors: str, *, ok: bool) -> dict:
        self.assertEqual(code, 0 if ok else 2, output + errors)
        value = json.loads(output)
        self.assertEqual(value["ok"], ok, value)
        return value

    def task_cli_args(self, name: str) -> list[object]:
        return [name, self.workspace, "--task-id", self.task_id]

    def hashes(self) -> dict[str, str]:
        return {path.relative_to(self.workspace).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest()
                for path in self.workspace.rglob("*") if path.is_file()}

    @contextmanager
    def coordinate_public_io(self, args: list[object], path: Path, event: str):
        config, signal, release = self.base / "observe.json", self.base / "reached", self.base / "release"
        signal.unlink(missing_ok=True)
        release.unlink(missing_ok=True)
        config.write_text(json.dumps({"watch_root": str(self.workspace), "pause_path": str(path),
                                      "pause_event": event, "pause_target": 1,
                                      "signal": str(signal), "release": str(release)}), encoding="utf-8")
        proc = subprocess.Popen([sys.executable, str(ROOT / "tests/support/observe_cli.py"),
                                 "--config", str(config), "--", *(str(arg) for arg in args)],
                                cwd=ROOT, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        try:
            deadline = time.monotonic() + 15
            while not signal.exists() and proc.poll() is None and time.monotonic() < deadline:
                time.sleep(0.01)
            self.assertTrue(signal.exists(), "public command did not reach coordinated file I/O")
            yield proc, release
        finally:
            if proc.poll() is None:
                proc.kill()
                proc.communicate()

    def test_one_project_resumes_through_index_and_document_recovery_without_recreating_facts(self) -> None:
        start = ["start", self.workspace, "--project-id", "synthetic-joint-acceptance",
                 "--name", "SYNTHETIC LOCAL PLANNING", "--brief", "Plan a fictitious local checklist",
                 "--task-id", self.task_id, "--mode", "assisted"]
        self.command(*start)
        self.assertFalse(self.workspace.exists())
        self.command(*start, "--apply")
        self.assertEqual(len(self.hashes()), 16)
        self.assertFalse((self.workspace / "docs/project").exists())
        task = self.workspace / "tasks" / self.task_id
        snapshot = task / "workflow-state.json"
        task_fact = task / "task.json"
        self.assertEqual(self.command(*self.task_cli_args("status"))["task"]["mode"], "assisted")
        self.command(*self.task_cli_args("advance"), "--apply", ok=False)
        payload_path = task / "payload.json"
        payload = json.loads(payload_path.read_text(encoding="utf-8"))
        payload.update({"users": "Synthetic readers", "in_scope": "Local checklist planning",
                        "out_of_scope": "Real business systems and external operations",
                        "success_criteria": "Resume the project through its explicit public task"})
        payload_path.write_text(json.dumps(payload), encoding="utf-8")
        self.command(*self.task_cli_args("context"), "--write")
        self.command(*self.task_cli_args("advance"), "--apply")

        # The fixture supplies an actual synthetic answer, not an inferred one.
        decision = [*self.task_cli_args("decision"), "--decision-id", "plan-acceptance",
                    "--answer", "accept", "--by", "synthetic-fixture-user", "--apply"]
        with self.coordinate_public_io(decision, task_fact, "os.rename") as (proc, release):
            snapshot.unlink()
            snapshot.mkdir()  # A real postcommit index-publication obstruction.
            release.touch()
            output, errors = proc.communicate(timeout=20)
        committed_result = self.assert_cli_response(proc.returncode, output, errors, ok=True)
        completion = committed_result["completion"]
        self.assertEqual(completion["operation"], "completed")
        self.assertEqual(completion["local_record"], "incomplete")
        self.assertFalse(completion["repeat_operation"])
        self.assertEqual(completion["recovery"], ["context", str(self.workspace), "--task-id", self.task_id, "--write"])
        committed = task_fact.read_bytes()
        view = self.command(*self.task_cli_args("status"))
        self.assertEqual(view["task"]["stage"], "plan")
        self.assertFalse(view["can_advance"])
        self.assertTrue(next(item for item in view["checks"] if item["id"] == "plan-acceptance")["passed"])
        self.command(*self.task_cli_args("advance"), "--apply", ok=False)
        snapshot.rmdir()  # Only the empty, test-owned index obstruction.
        self.command(*completion["recovery"])
        self.assertEqual(task_fact.read_bytes(), committed, "repair must not replay decision or advance")
        self.assertTrue(self.command(*self.task_cli_args("context"), "--check")["snapshot_matches"])

        documents = self.workspace / "docs/project"
        documents.mkdir()
        (documents / "progress.md").write_bytes(b"Synthetic existing user handoff.\x00\xff")
        before = self.hashes()
        supplement = [*self.task_cli_args("project-docs"), "--with-docs", "architecture", "--with-docs", "environment",
                      "--with-docs", "progress", "--with-docs", "summary"]
        self.command(*supplement)
        self.assertEqual(self.hashes(), before)
        blocked = documents / "environment.md"
        with self.coordinate_public_io([*supplement, "--apply"], blocked, "os.link") as (proc, release):
            blocked.mkdir()
            release.touch()
            output, errors = proc.communicate(timeout=20)
        partial = self.assert_cli_response(proc.returncode, output, errors, ok=False)
        self.assertEqual(partial["progress"], {"created": ["architecture"], "preserved": ["progress"],
                                               "pending": ["environment", "summary"]})
        self.assertNotIn("completion", partial, "document progress is not a fact-write completion receipt")
        self.assertEqual({name: self.hashes()[name] for name in before}, before)
        self.assertTrue(self.command(*self.task_cli_args("context"), "--check")["snapshot_matches"])
        blocked.rmdir()  # Only the empty, test-owned document obstruction.
        before_retry = self.hashes()
        supplemented = self.command(*supplement, "--apply")
        self.assertEqual(supplemented["progress"], {"created": ["environment", "summary"],
                                                   "preserved": ["architecture", "progress"], "pending": []})
        self.assertEqual({name: self.hashes()[name] for name in before_retry}, before_retry)

        # Read-only handoff discovers drift/corruption; only context --write repairs.
        stable_facts = task_fact.read_bytes()
        state = json.loads(snapshot.read_text(encoding="utf-8"))
        state["task"]["stage"] = "synthetic-stale-index"
        for damaged in (json.dumps(state).encode("utf-8"), b"{synthetic damaged index"):
            snapshot.write_bytes(damaged)
            self.assertEqual(self.command(*self.task_cli_args("status"))["task"]["stage"], "plan")
            self.command(*self.task_cli_args("context"))
            self.command(*self.task_cli_args("context"), "--check", ok=False)
            self.assertEqual(snapshot.read_bytes(), damaged)
            self.command(*self.task_cli_args("context"), "--write")
            self.assertEqual(task_fact.read_bytes(), stable_facts)
            self.assertTrue(self.command(*self.task_cli_args("context"), "--check")["snapshot_matches"])
        for mode in ("full-auto", "manual-review"):
            self.command(*self.task_cli_args("task-plan"), "--mode", mode, "--apply")
            self.assertEqual(self.command(*self.task_cli_args("status"))["task"]["mode"], mode)
            self.assertEqual(self.command(*self.task_cli_args("context"))["task"]["mode"], mode)
            self.command(*self.task_cli_args("advance"), "--apply", ok=False)

        # The now-complete fixture plan requires its own supplied revised answer.
        (task / "plan.md").write_text("# 合成启动方案\n\n## 可执行任务\n核对虚构清单。\n\n"
                                      "## 技术选择\n仅本地文档与公开 CLI。\n\n## 风险\n不连接真实系统。\n\n"
                                      "## 验收方法\n依据明确任务检查方案与事实。\n", encoding="utf-8")
        self.assertFalse(self.command(*self.task_cli_args("status"))["can_advance"])
        self.command(*decision)
        self.command(*self.task_cli_args("advance"), "--apply")
        ready = self.command(*self.task_cli_args("status"))
        self.assertEqual(ready["task"]["stage"], "ready")
        self.assertTrue(ready["completed_locally"])
        self.assertEqual(ready["business_system_state"], "not_queried")
        self.assertTrue((documents / "summary.md").read_text(encoding="utf-8").startswith("---\nstatus: draft\n"))
        self.assertEqual(len(json.loads(task_fact.read_text(encoding="utf-8"))["decisions"]), 1)
        before_hook = self.hashes()
        env = os.environ.copy()
        env.pop("AGENT_WORKFLOW_WORKSPACE", None)
        env.pop("AGENT_WORKFLOW_TASK_ID", None)
        hook = subprocess.run([sys.executable, "scripts/context_hook.py", "--event", "SessionStart"],
                              cwd=ROOT, env=env, capture_output=True, text=True, check=False, timeout=20)
        self.assertEqual(hook.returncode, 0, hook.stdout + hook.stderr)
        self.assertIn("AGENTS.md", json.loads(hook.stdout)["hookSpecificOutput"]["additionalContext"])
        self.assertEqual(self.hashes(), before_hook)


if __name__ == "__main__":
    unittest.main()
