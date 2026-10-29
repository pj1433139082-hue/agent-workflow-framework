"""Public CLI contract tests for non-destructive project adoption."""

import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]


class ProjectAdoptCliTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name)

    def cli(self, *args: object) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [sys.executable, "-m", "agent_workflow", *(str(arg) for arg in args)],
            cwd=ROOT,
            env=os.environ.copy(),
            capture_output=True,
            text=True,
            check=False,
        )

    def result(self, proc: subprocess.CompletedProcess[str], *, ok: bool) -> dict:
        self.assertEqual(proc.returncode, 0 if ok else 2, proc.stdout + proc.stderr)
        payload = json.loads(proc.stdout)
        self.assertEqual(payload.get("ok"), ok, payload)
        return payload

    def test_adopt_nonexistent_workspace_fails_with_not_found(self) -> None:
        missing = self.base / "does-not-exist"
        proc = self.cli("adopt", missing, "--project-id", "test-adopt")
        res = self.result(proc, ok=False)
        self.assertEqual(res["error"]["code"], "workspace_not_found")

    def test_adopt_preview_does_not_mutate_existing_workspace(self) -> None:
        workspace = self.base / "legacy-repo"
        workspace.mkdir()
        (workspace / "README.md").write_text("# Old Readme\n", encoding="utf-8")
        (workspace / "requirements.txt").write_text("pandas>=2.0\n", encoding="utf-8")
        (workspace / "main.py").write_text("print('hello')\n", encoding="utf-8")

        proc = self.cli("adopt", workspace, "--project-id", "test-adopt", "--name", "Legacy Repo")
        res = self.result(proc, ok=True)
        self.assertTrue(res["adopted"])
        self.assertFalse(res["applied"])
        self.assertIn("README.md", res["preserved_files"])
        self.assertEqual(res["detected_environments"], {"python": ["requirements.txt"]})

        # Ensure no files were written in preview
        self.assertFalse((workspace / "project.json").exists())
        self.assertFalse((workspace / "tasks").exists())
        self.assertFalse((workspace / "docs").exists())

    def test_adopt_detects_broader_environment_families(self) -> None:
        workspace = self.base / "mixed-stack"
        workspace.mkdir()
        (workspace / "App.csproj").write_text("<Project />", encoding="utf-8")
        (workspace / "CMakeLists.txt").write_text("project(synthetic)\n", encoding="utf-8")
        (workspace / "composer.json").write_text("{}", encoding="utf-8")
        res = self.result(self.cli("adopt", workspace, "--project-id", "mixed-stack"), ok=True)
        self.assertEqual(res["detected_environments"]["dotnet"], ["App.csproj"])
        self.assertEqual(res["detected_environments"]["cpp"], ["CMakeLists.txt"])
        self.assertEqual(res["detected_environments"]["php"], ["composer.json"])

    def test_adopt_preserves_code_git_and_readme_and_creates_framework_skeleton(self) -> None:
        workspace = self.base / "legacy-project"
        workspace.mkdir()
        (workspace / "README.md").write_text("# Legacy Project\nOriginal docs.", encoding="utf-8")
        (workspace / "AGENTS.md").write_text("# Legacy Agents\nCustom proxy.", encoding="utf-8")
        (workspace / "package.json").write_text('{"name": "legacy-app"}', encoding="utf-8")
        (workspace / "requirements.txt").write_text("pytest\n", encoding="utf-8")
        (workspace / "src").mkdir()
        (workspace / "src" / "index.js").write_text("console.log(1);\n", encoding="utf-8")

        proc = self.cli("adopt", workspace, "--project-id", "legacy-core", "--apply")
        res = self.result(proc, ok=True)
        self.assertTrue(res["adopted"])
        self.assertTrue(res["applied"])

        # Preserved files unchanged
        self.assertEqual((workspace / "README.md").read_text(encoding="utf-8"), "# Legacy Project\nOriginal docs.")
        self.assertEqual((workspace / "AGENTS.md").read_text(encoding="utf-8"), "# Legacy Agents\nCustom proxy.")
        self.assertEqual((workspace / "src" / "index.js").read_text(encoding="utf-8"), "console.log(1);\n")

        # AGENTS.framework.md generated for reference
        self.assertTrue((workspace / "AGENTS.framework.md").is_file())
        self.assertIn("本项目协作入口", (workspace / "AGENTS.framework.md").read_text(encoding="utf-8"))

        # Framework skeleton created
        self.assertTrue((workspace / "project.json").is_file())
        self.assertTrue((workspace / ".agent-workflow.local.json").is_file())
        self.assertTrue((workspace / "docs/00-入口层/00-项目总览.md").is_file())
        self.assertTrue((workspace / "tasks/kickoff/task.json").is_file())
        self.assertTrue((workspace / "tasks/kickoff/payload.json").is_file())
        self.assertTrue((workspace / "tasks/kickoff/plan.md").is_file())
        self.assertTrue((workspace / "tasks/kickoff/workflow-state.json").is_file())

        # Environment detected
        self.assertIn("node", res["detected_environments"])
        self.assertIn("python", res["detected_environments"])

        # Status and context work immediately
        status_proc = self.cli("status", workspace, "--task-id", "kickoff")
        status_res = self.result(status_proc, ok=True)
        self.assertEqual(status_res["task"]["stage"], "scope")

    def test_adopt_refuses_conflicting_project_identity_without_writing(self) -> None:
        workspace = self.base / "existing-project"
        workspace.mkdir()
        facts = workspace / "project.json"
        facts.write_text('{"schema_version": "1.0", "project_id": "legacy-core"}', encoding="utf-8")
        (workspace / "README.md").write_text("# Existing\n", encoding="utf-8")
        before = {path: path.read_bytes() for path in workspace.rglob("*") if path.is_file()}
        res = self.result(self.cli("adopt", workspace, "--project-id", "other-id", "--apply"), ok=False)
        self.assertEqual(res["error"]["code"], "project_identity_mismatch")
        self.assertIn("legacy-core", res["error"]["message"])
        after = {path: path.read_bytes() for path in workspace.rglob("*") if path.is_file()}
        self.assertEqual(before, after)
        self.assertFalse((workspace / "tasks").exists())
        self.assertFalse((workspace / ".agent-workflow.local.json").exists())

    def test_adopt_keeps_existing_local_marker_and_reports_task_files(self) -> None:
        workspace = self.base / "adopt-marker"
        workspace.mkdir()
        marker = workspace / ".agent-workflow.local.json"
        original = '{"schema_version": "1.0", "framework_root": "C:/existing/framework", "task_id": "legacy-task"}'
        marker.write_text(original, encoding="utf-8")
        res = self.result(self.cli("adopt", workspace, "--project-id", "marker-prj", "--apply"), ok=True)
        self.assertEqual(marker.read_text(encoding="utf-8"), original)
        self.assertIn(".agent-workflow.local.json", res["preserved_files"])
        self.assertNotIn(".agent-workflow.local.json", res["created_files"])
        self.assertEqual(res["local_marker"], {"file": ".agent-workflow.local.json",
                                               "preserved": True, "active_task_id": "legacy-task"})
        for name in ("task.json", "payload.json", "plan.md"):
            self.assertIn(f"tasks/kickoff/{name}", res["created_files"])
        self.assertTrue((workspace / "tasks/kickoff/task.json").is_file())

    def test_adopt_second_task_does_not_retarget_the_pointer(self) -> None:
        workspace = self.base / "two-tasks"
        workspace.mkdir()
        first = self.result(self.cli("adopt", workspace, "--project-id", "two-tasks-prj", "--apply"), ok=True)
        self.assertEqual(first["local_marker"]["active_task_id"], "kickoff")
        second = self.result(self.cli("adopt", workspace, "--project-id", "two-tasks-prj",
                                      "--task-id", "review", "--apply"), ok=True)
        marker = json.loads((workspace / ".agent-workflow.local.json").read_text(encoding="utf-8"))
        self.assertEqual(marker["task_id"], "kickoff")
        self.assertEqual(second["local_marker"], {"file": ".agent-workflow.local.json",
                                                  "preserved": True, "active_task_id": "kickoff"})
        self.assertIn("tasks/review/plan.md", second["created_files"])
        status = self.result(self.cli("status", workspace, "--task-id", "review"), ok=True)
        self.assertEqual(status["task"]["id"], "review")

    def test_context_hook_zero_config_detects_workspace_from_cwd(self) -> None:
        workspace = self.base / "active-project"
        workspace.mkdir()
        proc = self.cli("adopt", workspace, "--project-id", "active-prj", "--apply")
        self.result(proc, ok=True)

        hook_script = ROOT / "scripts/context_hook.py"
        # Run hook directly from inside workspace directory without any env vars
        clean_env = os.environ.copy()
        clean_env.pop("AGENT_WORKFLOW_WORKSPACE", None)
        clean_env.pop("AGENT_WORKFLOW_TASK_ID", None)

        hook_proc = subprocess.run(
            [sys.executable, str(hook_script), "--event", "SessionStart"],
            cwd=workspace,
            env=clean_env,
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(hook_proc.returncode, 0, hook_proc.stdout + hook_proc.stderr)
        output = json.loads(hook_proc.stdout)
        context_str = output["hookSpecificOutput"]["additionalContext"]
        self.assertIn("Read-only task navigation", context_str)
        self.assertIn("project-planning", context_str)
        self.assertIn("kickoff", context_str)


if __name__ == "__main__":
    unittest.main()
