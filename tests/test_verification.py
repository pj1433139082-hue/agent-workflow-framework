"""Public task-read behavior with real files and test-only I/O observation."""

import hashlib
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


class VerificationCliTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name)
        self.workspace = self.base / "project"
        self.task = self.workspace / "tasks" / "review"
        self.cli("new", self.workspace, "--project-id", "synthetic-read",
                 "--workflow", "ecommerce-catalog", "--task-id", "review", "--apply")
        self.write_payload(price=3)
        self.cli("advance", self.workspace, "--task-id", "review", "--apply")
        (self.task / "review.md").write_text("# 合成审核\n\n## 检查结论\n只核验临时资料。\n", encoding="utf-8")
        self.cli("decision", self.workspace, "--task-id", "review", "--decision-id",
                 "review-acceptance", "--answer", "accept", "--by", "synthetic-reviewer", "--apply")

    def cli(self, *args: object) -> dict:
        result = subprocess.run([sys.executable, "-m", "agent_workflow", *(str(arg) for arg in args)],
                                cwd=ROOT, capture_output=True, text=True, check=False)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        return json.loads(result.stdout)

    def write_payload(self, *, price: int) -> None:
        (self.task / "payload.json").write_text(json.dumps({
            "sku": "SYN-READ", "title": "合成资料", "price": price,
            "currency": "CNY", "synthetic": True,
        }, ensure_ascii=False), encoding="utf-8")

    def hashes(self) -> dict[str, str]:
        return {path.relative_to(self.workspace).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest()
                for path in self.workspace.rglob("*") if path.is_file()}

    def test_mid_read_edit_never_combines_old_checks_with_new_sources(self) -> None:
        # Coordination observes file I/O only; it does not patch framework functions.
        observer = ROOT / "tests" / "support" / "observe_cli.py"
        config = self.base / "observe.json"
        signal = self.base / "reached"
        release = self.base / "release"
        config.write_text(json.dumps({
            "watch_root": str(self.workspace),
            "pause_path": str(self.task / "review.md"),
            "signal": str(signal), "release": str(release),
        }), encoding="utf-8")
        proc = subprocess.Popen([sys.executable, str(observer), "--config", str(config), "--",
                                 "status", str(self.workspace), "--task-id", "review"],
                                cwd=ROOT, env=os.environ.copy(), stdout=subprocess.PIPE,
                                stderr=subprocess.PIPE, text=True)
        try:
            deadline = time.monotonic() + 15
            while not signal.exists() and proc.poll() is None and time.monotonic() < deadline:
                time.sleep(0.01)
            self.assertTrue(signal.exists(), "public subprocess did not reach the coordinated read")
            self.write_payload(price=-3)
            release.touch()
            output, errors = proc.communicate(timeout=20)
        finally:
            if proc.poll() is None:
                proc.kill()
                proc.communicate()
        self.assertEqual(proc.returncode, 0, output + errors)
        view = json.loads(output)
        checks = {check["id"]: check for check in view["checks"]}
        self.assertFalse(checks["catalog-fields"]["passed"], "edited payload cannot keep the old pass")
        self.assertFalse(view["evidence_valid"])
        self.assertFalse(view["can_advance"])
        self.assertEqual(view["sources"]["tasks/review/payload.json"],
                         hashlib.sha256((self.task / "payload.json").read_bytes()).hexdigest())

    def test_context_rechecks_changed_identity_and_new_evidence_membership(self) -> None:
        config, signal, release = self.base / "identity.json", self.base / "reached", self.base / "release"
        config.write_text(json.dumps({
            "watch_root": str(self.workspace), "pause_path": str(self.task / "review.md"),
            "signal": str(signal), "release": str(release),
        }), encoding="utf-8")
        proc = subprocess.Popen([sys.executable, str(ROOT / "tests/support/observe_cli.py"),
                                 "--config", str(config), "--", "context", str(self.workspace),
                                 "--task-id", "review"], cwd=ROOT,
                                stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        try:
            deadline = time.monotonic() + 15
            while not signal.exists() and proc.poll() is None and time.monotonic() < deadline:
                time.sleep(0.01)
            self.assertTrue(signal.exists())
            facts_path = self.task / "task.json"
            facts = json.loads(facts_path.read_text(encoding="utf-8"))
            facts["mode"] = "manual-review"
            facts["next_action"] = "Inspect synthetic new evidence."
            facts_path.write_text(json.dumps(facts), encoding="utf-8")
            (self.task / "added.md").write_text("Synthetic added evidence.", encoding="utf-8")
            release.touch()
            output, errors = proc.communicate(timeout=20)
        finally:
            if proc.poll() is None:
                proc.kill()
                proc.communicate()
        self.assertEqual(proc.returncode, 0, output + errors)
        view = json.loads(output)
        self.assertEqual(view["task"]["mode"], "manual-review")
        self.assertEqual(view["task"]["next_action"], "Inspect synthetic new evidence.")
        self.assertEqual(view["sources"]["tasks/review/task.json"], hashlib.sha256(facts_path.read_bytes()).hexdigest())
        self.assertIn("tasks/review/added.md", view["sources"])
        self.assertFalse(view["can_advance"], "new evidence invalidates the old accepted decision")
        self.assertFalse(view["snapshot_matches"])

    def test_continuous_edits_stop_structurally_without_writing_or_replaying(self) -> None:
        config = self.base / "continuous.json"
        signal, release = self.base / "reached", self.base / "release"
        config.write_text(json.dumps({
            "watch_root": str(self.workspace), "pause_path": str(self.task / "review.md"),
            "signal": str(signal), "release": str(release), "pause_each": True,
        }), encoding="utf-8")
        proc = subprocess.Popen([sys.executable, str(ROOT / "tests/support/observe_cli.py"),
                                 "--config", str(config), "--", "context", str(self.workspace),
                                 "--task-id", "review", "--write"], cwd=ROOT,
                                stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        unchanged = {name: digest for name, digest in self.hashes().items() if name != "tasks/review/payload.json"}
        try:
            deadline = time.monotonic() + 20
            sequence = 1
            while proc.poll() is None and time.monotonic() < deadline:
                if Path(str(signal) + f".{sequence}").exists():
                    self.write_payload(price=sequence + 100)
                    Path(str(release) + f".{sequence}").touch()
                    sequence += 1
                else:
                    time.sleep(0.01)
            output, errors = proc.communicate(timeout=5)
        finally:
            if proc.poll() is None:
                proc.kill()
                proc.communicate()
        self.assertEqual(proc.returncode, 2, output + errors)
        result = json.loads(output)
        self.assertFalse(result["ok"])
        self.assertEqual(result["error"]["code"], "materials_changed")
        self.assertNotIn("sources", result, "a stopped read cannot return a mixed success view")
        self.assertEqual({name: digest for name, digest in self.hashes().items()
                          if name != "tasks/review/payload.json"}, unchanged)

    def test_stable_views_hook_and_index_repair_use_facts_without_expanding_evidence(self) -> None:
        self.cli("context", self.workspace, "--task-id", "review", "--write")
        status = self.cli("status", self.workspace, "--task-id", "review")
        context = self.cli("context", self.workspace, "--task-id", "review", "--check")
        self.assertEqual({key: context[key] for key in status}, status)
        self.assertTrue(status["can_advance"])
        auxiliary = self.workspace / "docs/project"
        auxiliary.mkdir(parents=True)
        (auxiliary / "progress.md").write_text("Synthetic auxiliary event, not task evidence.", encoding="utf-8")
        self.assertEqual(self.cli("status", self.workspace, "--task-id", "review"), status)

        before = self.hashes()
        env = {**os.environ, "AGENT_WORKFLOW_WORKSPACE": str(self.workspace), "AGENT_WORKFLOW_TASK_ID": "review"}
        hook = subprocess.run([sys.executable, "scripts/context_hook.py", "--event", "UserPromptSubmit"],
                              cwd=ROOT, env=env, input="untrusted user prompt", capture_output=True, text=True)
        self.assertEqual(hook.returncode, 0, hook.stdout + hook.stderr)
        text = json.loads(hook.stdout)["hookSpecificOutput"]["additionalContext"]
        self.assertIn('"can_advance": true', text)
        for raw in ("合成资料", "synthetic-reviewer", "untrusted user prompt", '"answer"'):
            self.assertNotIn(raw, text)
        self.assertEqual(self.hashes(), before)

        snapshot = self.task / "workflow-state.json"
        for corruption in (None, "{broken", '{"tampered":true}'):
            with self.subTest(index=corruption):
                if corruption is None:
                    snapshot.unlink()
                else:
                    snapshot.write_text(corruption, encoding="utf-8")
                facts = {name: value for name, value in self.hashes().items()
                         if name != "tasks/review/workflow-state.json"}
                self.assertFalse(self.cli("context", self.workspace, "--task-id", "review")["snapshot_matches"])
                self.cli("context", self.workspace, "--task-id", "review", "--write")
                self.assertTrue(self.cli("context", self.workspace, "--task-id", "review", "--check")["snapshot_matches"])
                self.assertEqual({name: value for name, value in self.hashes().items()
                                  if name != "tasks/review/workflow-state.json"}, facts)

        (self.task / "new-evidence.md").write_text("Synthetic new task evidence.", encoding="utf-8")
        changed = self.cli("status", self.workspace, "--task-id", "review")
        self.assertFalse(changed["can_advance"])
        self.assertEqual([item["id"] for item in changed["pending_decisions"]], ["review-acceptance"])

    def test_pack_binding_includes_sop_and_ignores_only_existing_cache_rules(self) -> None:
        runtime = self.base / "runtime"
        shutil.copytree(ROOT, runtime, ignore=shutil.ignore_patterns(
            ".git", "__pycache__", "*.pyc", ".mypy_cache", ".ruff_cache"))
        pack = runtime / "agent_workflow/packs/ecommerce-catalog"
        (pack / "__pycache__").mkdir()
        (pack / "__pycache__/ignored.bin").write_bytes(b"synthetic cache")
        (pack / "ignored.pyc").write_bytes(b"synthetic bytecode")
        stable = subprocess.run([sys.executable, "-m", "agent_workflow", "status", str(self.workspace),
                                 "--task-id", "review"], cwd=runtime, capture_output=True, text=True)
        self.assertEqual(stable.returncode, 0, stable.stdout + stable.stderr)
        (pack / "SOP.md").write_text("Synthetic changed SOP", encoding="utf-8")
        for command in ("status", "context"):
            changed = subprocess.run([sys.executable, "-m", "agent_workflow", command, str(self.workspace),
                                      "--task-id", "review"], cwd=runtime, capture_output=True, text=True)
            self.assertEqual(changed.returncode, 2, changed.stdout + changed.stderr)
            self.assertEqual(json.loads(changed.stdout)["error"]["code"], "workflow_changed")

    def test_crlf_text_evidence_keeps_existing_literal_check_semantics(self) -> None:
        runtime = self.base / "crlf-runtime"
        shutil.copytree(ROOT, runtime, ignore=shutil.ignore_patterns(
            ".git", "__pycache__", "*.pyc", ".mypy_cache", ".ruff_cache"))
        pack_path = runtime / "agent_workflow/packs/synthetic-crlf"
        pack_path.mkdir()
        pack = {
            "schema_version": "1.0", "id": "synthetic-crlf", "name": "Synthetic text compatibility",
            "version": "0.1.0", "description": "Synthetic Windows newline evidence only.",
            "templates": {"note.md": "synthetic-one\r\nsynthetic-two\r\n"},
            "stages": [
                {"id": "read", "documents": ["AGENTS.md"], "checks": [
                    {"id": "literal", "kind": "file-content", "file": "note.md",
                     "contains": ["synthetic-one\nsynthetic-two"]}]},
                {"id": "complete", "documents": ["AGENTS.md"], "checks": []},
            ],
        }
        (pack_path / "workflow.json").write_text(json.dumps(pack), encoding="utf-8")
        workspace = self.base / "crlf-workspace"
        for args in (("new", str(workspace), "--project-id", "synthetic-crlf", "--workflow", "synthetic-crlf",
                      "--task-id", "read", "--apply"),
                     ("status", str(workspace), "--task-id", "read")):
            proc = subprocess.run([sys.executable, "-m", "agent_workflow", *args], cwd=runtime,
                                  capture_output=True, text=True, check=False)
            self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
        view = json.loads(proc.stdout)
        self.assertTrue(view["checks"][0]["passed"], "Windows newlines must retain prior text-read semantics")
        raw = (workspace / "tasks/read/note.md").read_bytes()
        self.assertIn(b"\r\n", raw)
        self.assertEqual(view["sources"]["tasks/read/note.md"], hashlib.sha256(raw).hexdigest())


if __name__ == "__main__":
    unittest.main()
