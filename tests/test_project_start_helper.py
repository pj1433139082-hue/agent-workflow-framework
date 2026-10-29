"""Project-start diagnostics through the public helper process boundary."""

import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]
HELPER = ROOT / ".skillshare/skills/project-start/scripts/start_project.py"


class ProjectStartHelperTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.workspace = Path(self.temp.name) / "project"
        self.env = os.environ.copy()
        self.env.pop("AGENT_WORKFLOW_FRAMEWORK", None)

    def helper(self, *args: object, python: str = sys.executable) -> subprocess.CompletedProcess[str]:
        return subprocess.run([python, str(HELPER), *(str(arg) for arg in args)],
                              cwd=self.temp.name, env=self.env, capture_output=True,
                              text=True, check=False, timeout=30)

    def test_incompatible_tool_interpreter_does_not_report_missing_framework(self) -> None:
        python = os.environ.get("AGENT_WORKFLOW_TEST_PYTHON310")
        if not python:
            self.skipTest("No explicitly selected existing Python 3.10; not installed by this test.")
        version = subprocess.run([python, "--version"], capture_output=True, text=True,
                                 check=False, timeout=15)
        self.assertEqual(version.returncode, 0, version.stdout + version.stderr)
        self.assertIn("Python 3.10.", version.stdout + version.stderr)
        result = self.helper("--framework", ROOT, "--", "start", self.workspace,
                             "--project-id", "synthetic", "--name", "Synthetic", "--apply", python=python)
        self.assertEqual(result.returncode, 2, result.stdout + result.stderr)
        error = json.loads(result.stdout)["error"]
        self.assertEqual(error["code"], "python_version")
        self.assertIn("business runtimes are independent", error["message"])
        self.assertFalse(self.workspace.exists())

    def test_helper_argument_errors_are_safe_and_not_location_errors(self) -> None:
        sensitive = "synthetic-sensitive-argument"
        result = self.helper("--framework", ROOT, "--unknown-" + sensitive)
        self.assertEqual(result.returncode, 2, result.stdout + result.stderr)
        error = json.loads(result.stdout)["error"]
        self.assertEqual(error["code"], "helper_arguments_error")
        self.assertIn("--help", error["message"])
        self.assertNotIn(sensitive, result.stdout + result.stderr)
        self.assertFalse(self.workspace.exists())

    def test_unusable_locations_and_broken_metadata_do_not_echo_input(self) -> None:
        sensitive = "synthetic-sensitive-location"
        missing = self.helper("--framework", Path(self.temp.name) / sensitive, "--locate")
        marker = Path(self.temp.name) / ".agent-workflow.local.json"
        marker.write_text('{"framework_root":"' + sensitive, encoding="utf-8")
        malformed = self.helper("--locate")
        for result in (missing, malformed):
            with self.subTest(output=result.stdout):
                self.assertEqual(result.returncode, 2, result.stdout + result.stderr)
                error = json.loads(result.stdout)["error"]
                self.assertEqual(error["code"], "framework_location_error")
                self.assertIn("--framework", error["message"])
                self.assertNotIn(sensitive, result.stdout + result.stderr)
        self.assertFalse(self.workspace.exists())

    def test_location_help_and_cli_failures_keep_their_public_behavior(self) -> None:
        located = self.helper("--framework", ROOT, "--locate")
        self.assertEqual(located.returncode, 0, located.stdout + located.stderr)
        self.assertEqual(json.loads(located.stdout), {"ok": True, "framework_root": str(ROOT)})
        help_result = self.helper("--help")
        self.assertEqual(help_result.returncode, 0, help_result.stdout + help_result.stderr)
        self.assertIn("--framework", help_result.stdout)
        args = ["status", str(self.workspace), "--task-id", "absent"]
        direct = subprocess.run([sys.executable, "-m", "agent_workflow", *args], cwd=ROOT,
                                env=self.env, capture_output=True, text=True, check=False, timeout=30)
        wrapped = self.helper("--framework", ROOT, "--", *args)
        self.assertEqual(wrapped.returncode, direct.returncode)
        self.assertEqual(json.loads(wrapped.stdout), json.loads(direct.stdout))
        self.assertFalse(self.workspace.exists())

    @unittest.skipUnless(os.name == "posix" and shutil.which("bash"), "Requires POSIX executable alias launch.")
    def test_unavailable_launch_executable_is_not_a_framework_location_error(self) -> None:
        # A real OS argv[0] alias, not a patched Python global or private writer.
        env = self.env.copy()
        env["PYTHONHOME"] = sys.base_prefix
        missing_executable = Path(self.temp.name) / "synthetic-absent-python"
        result = subprocess.run(
            ["bash", "-c", 'exec -a "$1" "$2" "$3" --framework "$4" -- doctor',
             "synthetic-helper-launch", str(missing_executable), sys.executable, str(HELPER), str(ROOT)],
            cwd=self.temp.name, env=env, capture_output=True, text=True, check=False, timeout=30,
        )
        self.assertEqual(result.returncode, 2, result.stdout + result.stderr)
        error = json.loads(result.stdout)["error"]
        self.assertEqual(error["code"], "framework_invocation_error")
        self.assertNotIn("No project was created", error["message"])
        self.assertFalse(self.workspace.exists())

    def test_locate_walks_up_from_a_project_subdirectory(self) -> None:
        workspace = Path(self.temp.name) / "adopted"
        (workspace / "src" / "deep").mkdir(parents=True)
        (workspace / ".agent-workflow.local.json").write_text(
            json.dumps({"schema_version": "1.0", "framework_root": str(ROOT), "task_id": "kickoff"}),
            encoding="utf-8")
        env = self.env.copy()
        env["LOCALAPPDATA"] = str(Path(self.temp.name) / "empty-local")
        env["XDG_CONFIG_HOME"] = str(Path(self.temp.name) / "empty-config")
        result = subprocess.run([sys.executable, str(HELPER), "--locate"], cwd=workspace / "src" / "deep",
                                env=env, capture_output=True, text=True, check=False, timeout=30)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(json.loads(result.stdout), {"ok": True, "framework_root": str(ROOT)})

    def test_forwarded_partial_completion_is_not_rewritten_or_replayed(self) -> None:
        created = self.helper("--framework", ROOT, "--", "new", self.workspace,
                              "--project-id", "synthetic-recovery", "--workflow", "ecommerce-catalog",
                              "--task-id", "review", "--apply")
        self.assertEqual(created.returncode, 0, created.stdout + created.stderr)
        task = self.workspace / "tasks/review"
        index = task / "workflow-state.json"
        index.unlink()  # Only the generated index in this test-owned workspace.
        index.mkdir()
        result = self.helper("--framework", ROOT, "--", "task-plan", self.workspace,
                             "--task-id", "review", "--mode", "full-auto", "--apply")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        completion = json.loads(result.stdout)["completion"]
        self.assertEqual(completion["operation"], "completed")
        self.assertEqual(completion["local_record"], "incomplete")
        self.assertFalse(completion["repeat_operation"])
        self.assertEqual(completion["recovery"], ["context", str(self.workspace), "--task-id", "review", "--write"])
        status = self.helper("--framework", ROOT, "--", "status", self.workspace, "--task-id", "review")
        self.assertEqual(json.loads(status.stdout)["task"]["mode"], "full-auto")


if __name__ == "__main__":
    unittest.main()
