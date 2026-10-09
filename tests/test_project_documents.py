"""Public CLI contract tests for optional project documents."""

import json
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_PROJECT_FILES = {
    "AGENTS.md",
    "README.md",
    "CONTEXT.md",
    ".gitignore",
    ".agent-workflow.local.json",
    "docs/00-入口层/00-项目总览.md",
    "docs/10-流程层/10-项目启动SOP.md",
    "docs/20-规则层/20-项目规则.md",
    "docs/30-触发层/30-项目验收.md",
    "docs/agents/triage-labels.md",
    "docs/agents/domain.md",
}
TASK_FILES = {"task.json", "payload.json", "plan.md", "workflow-state.json"}
OPTIONAL_DOCUMENTS = {"environment", "architecture", "progress", "summary", "results"}
TRACKER_FILE = "docs/agents/issue-tracker.md"


class ProjectDocumentCliTests(unittest.TestCase):
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
        try:
            payload = json.loads(proc.stdout)
        except json.JSONDecodeError as exc:
            self.fail(f"CLI stdout was not JSON: {exc}: {proc.stdout!r}")
        self.assertIsInstance(payload, dict)
        self.assertEqual(payload.get("ok"), ok, payload)
        if not ok:
            self.assertIsInstance(payload.get("error"), dict)
        return payload

    def start_args(self, workspace: Path, *, task_id: str = "kickoff",
                   name: str = "SYNTHETIC_PROJECT_NAME",
                   brief: str = "SYNTHETIC_PROJECT_BRIEF",
                   mode: str = "manual-review",
                   with_docs: tuple[str, ...] = ()) -> list[object]:
        args: list[object] = [
            "start", workspace,
            "--project-id", "synthetic-project",
            "--name", name,
            "--brief", brief,
            "--task-id", task_id,
            "--mode", mode,
        ]
        for document in with_docs:
            args.extend(("--with-docs", document))
        return args

    def assert_project_files(self, payload: dict, expected: set[str]) -> None:
        project_files = payload.get("project_files")
        self.assertIsInstance(project_files, list)
        self.assertEqual(len(project_files), len(set(project_files)), "project_files must be deduplicated")
        self.assertEqual(set(project_files), expected)

    def assert_task_and_snapshot(self, workspace: Path, task_id: str, mode: str) -> None:
        status = self.result(self.cli("status", workspace, "--task-id", task_id), ok=True)
        task = status["task"]
        self.assertEqual(task["id"], task_id)
        self.assertEqual(task["workflow"], "project-planning")
        self.assertEqual(task["stage"], "scope")
        self.assertEqual(task["mode"], mode)

        snapshot = json.loads(
            (workspace / "tasks" / task_id / "workflow-state.json").read_text(encoding="utf-8")
        )
        self.assertEqual(snapshot["task"]["id"], task["id"])
        self.assertEqual(snapshot["task"]["workflow"], task["workflow"])
        self.assertEqual(snapshot["task"]["stage"], task["stage"])
        checked = self.result(
            self.cli("context", workspace, "--task-id", task_id, "--check"), ok=True
        )
        self.assertTrue(checked["snapshot_matches"])

    def test_default_start_keeps_the_minimal_sixteen_file_workspace(self) -> None:
        workspace = self.base / "minimal-project"
        args = self.start_args(workspace)

        preview = self.result(self.cli(*args), ok=True)
        self.assertFalse(preview["applied"])
        self.assert_project_files(preview, DEFAULT_PROJECT_FILES)
        self.assertFalse(workspace.exists(), "preview must not create the target directory")

        created = self.result(self.cli(*args, "--apply"), ok=True)
        self.assertTrue(created["applied"])
        self.assert_project_files(created, DEFAULT_PROJECT_FILES)
        expected_files = DEFAULT_PROJECT_FILES | {"project.json"}
        expected_files |= {f"tasks/kickoff/{name}" for name in TASK_FILES}
        actual_files = {
            path.relative_to(workspace).as_posix()
            for path in workspace.rglob("*")
            if path.is_file()
        }
        self.assertEqual(actual_files, expected_files)
        self.assertEqual(len(actual_files), 16)
        self.assertFalse((workspace / "docs/project").exists())
        self.assert_task_and_snapshot(workspace, "kickoff", "manual-review")

    def test_each_optional_document_can_be_previewed_and_applied_alone(self) -> None:
        self.assertEqual(OPTIONAL_DOCUMENTS, {
            "environment", "architecture", "progress", "summary", "results",
        })
        for document in sorted(OPTIONAL_DOCUMENTS):
            with self.subTest(document=document):
                workspace = self.base / f"only-{document}"
                task_id = "selected-task"
                args = self.start_args(workspace, task_id=task_id, with_docs=(document,))
                selected_path = f"docs/project/{document}.md"

                preview = self.result(self.cli(*args), ok=True)
                self.assertFalse(preview["applied"])
                self.assert_project_files(preview, DEFAULT_PROJECT_FILES | {selected_path})
                self.assertFalse(workspace.exists(), "document preview must not write files")

                created = self.result(self.cli(*args, "--apply"), ok=True)
                self.assertTrue(created["applied"])
                self.assert_project_files(created, DEFAULT_PROJECT_FILES | {selected_path})
                self.assertTrue((workspace / selected_path).is_file())
                for other in OPTIONAL_DOCUMENTS - {document}:
                    self.assertFalse((workspace / f"docs/project/{other}.md").exists())
                self.assert_task_and_snapshot(workspace, task_id, "manual-review")

    def test_repeated_mixed_selection_deduplicates_and_leaves_summary_and_results_unfilled(self) -> None:
        workspace = self.base / "mixed-project"
        task_id = "mixed-task"
        name = "SYNTHETIC_NAME_MIXED_DOCS_73"
        brief = "SYNTHETIC_BRIEF_MIXED_DOCS_73"
        selected = ("environment", "architecture", "summary", "results",
                    "environment", "summary", "results")
        selected_paths = {
            f"docs/project/{document}.md"
            for document in {"environment", "architecture", "summary", "results"}
        }
        args = self.start_args(
            workspace, task_id=task_id, name=name, brief=brief, with_docs=selected
        )

        preview = self.result(self.cli(*args), ok=True)
        self.assertFalse(preview["applied"])
        self.assert_project_files(preview, DEFAULT_PROJECT_FILES | selected_paths)
        self.assertFalse(workspace.exists(), "preview must not create optional documents")

        created = self.result(self.cli(*args, "--apply"), ok=True)
        self.assertTrue(created["applied"])
        self.assert_project_files(created, DEFAULT_PROJECT_FILES | selected_paths)
        self.assertFalse((workspace / "docs/project/progress.md").exists())
        self.assert_task_and_snapshot(workspace, task_id, "manual-review")

        payload_path = workspace / "tasks" / task_id / "payload.json"
        payload = json.loads(payload_path.read_text(encoding="utf-8"))
        self.assertEqual(payload["project_name"], name)
        self.assertEqual(payload["goal"], brief)
        for path in workspace.rglob("*"):
            if not path.is_file() or path == payload_path:
                continue
            content = path.read_text(encoding="utf-8")
            self.assertNotIn(name, content, f"project name leaked into {path}")
            self.assertNotIn(brief, content, f"project brief leaked into {path}")

        summary = (workspace / "docs/project/summary.md").read_text(encoding="utf-8")
        frontmatter = re.match(r"\A---\r?\n(?P<yaml>.*?)\r?\n---(?:\r?\n|\Z)", summary, re.DOTALL)
        self.assertIsNotNone(frontmatter, "summary must have YAML frontmatter")
        fields = {}
        for line in frontmatter.group("yaml").splitlines():
            if ":" in line:
                key, value = line.split(":", 1)
                fields[key.strip()] = value.strip().strip("\"'")
        self.assertEqual(fields.get("status"), "draft")
        self.assertNotRegex(frontmatter.group("yaml"), r"(?im)^\s*completed(?:_at|_on|_date)?\s*:")
        self.assert_markdown_tables_have_headers_only(summary)

        results = (workspace / "docs/project/results.md").read_text(encoding="utf-8")
        for prohibited in ("test_MAE", "厂站", "业务参数"):
            self.assertNotIn(prohibited, results)
        self.assert_markdown_tables_have_headers_only(results)

    def assert_markdown_tables_have_headers_only(self, document: str) -> None:
        table_lines = [line for line in document.splitlines() if line.lstrip().startswith("|")]
        self.assertTrue(table_lines, "document should expose an empty table template")
        self.assertEqual(len(table_lines), 2, "template tables must not contain prefilled data rows")

    def test_project_docs_creates_a_missing_tracker_and_preserves_an_existing_one(self) -> None:
        workspace = self.base / "tracker-project"
        task_id = "tracker-task"
        self.result(self.cli(*self.start_args(workspace, task_id=task_id), "--apply"), ok=True)
        tracker = workspace / TRACKER_FILE
        self.assertFalse(tracker.exists(), "start without --tracker leaves the tracker undecided")

        args = ["project-docs", workspace, "--task-id", task_id, "--tracker", "local"]
        preview = self.result(self.cli(*args), ok=True)
        self.assertFalse(preview["applied"])
        self.assertEqual(preview["issue_tracker"], {"selected": "local", "file": TRACKER_FILE})
        self.assertEqual(preview["progress"],
                         {"created": [], "preserved": [], "pending": ["issue-tracker"]})
        self.assertFalse(tracker.exists(), "tracker preview must not write files")

        created = self.result(self.cli(*args, "--apply"), ok=True)
        self.assertEqual(created["progress"],
                         {"created": ["issue-tracker"], "preserved": [], "pending": []})
        self.assertIn(".scratch/", tracker.read_text(encoding="utf-8"))

        again = self.result(self.cli(*args, "--apply"), ok=True)
        self.assertEqual(again["progress"],
                         {"created": [], "preserved": ["issue-tracker"], "pending": []})

        before = tracker.read_bytes()
        switched = self.result(self.cli("project-docs", workspace, "--task-id", task_id,
                                        "--tracker", "github", "--apply"), ok=True)
        self.assertEqual(switched["progress"],
                         {"created": [], "preserved": ["issue-tracker"], "pending": []})
        self.assertEqual(tracker.read_bytes(), before, "an existing tracker is never rewritten")

        with_optional = self.result(self.cli(
            "project-docs", workspace, "--task-id", task_id, "--with-docs", "summary",
            "--tracker", "github", "--apply"), ok=True)
        self.assertEqual(with_optional["progress"],
                         {"created": ["summary"], "preserved": ["issue-tracker"], "pending": []})
        self.assertEqual(with_optional["document_files"], {"summary": "docs/project/summary.md"})

    def test_project_docs_requires_a_document_or_tracker_selection(self) -> None:
        workspace = self.base / "empty-selection"
        self.result(self.cli(*self.start_args(workspace), "--apply"), ok=True)
        # An empty selection stays an argument error at the CLI boundary, not a local fact problem.
        failure = self.result(self.cli("project-docs", workspace, "--task-id", "kickoff", "--apply"),
                              ok=False)
        self.assertEqual(failure["error"]["code"], "invalid_arguments")

    def test_invalid_option_and_existing_target_preserve_local_files(self) -> None:
        invalid_workspace = self.base / "invalid-option-project"
        invalid = self.result(
            self.cli(
                "start", invalid_workspace,
                "--project-id", "synthetic-invalid",
                "--name", "SYNTHETIC_INVALID_PROJECT",
                "--with-docs", "not-a-document",
                "--apply",
            ),
            ok=False,
        )
        self.assertEqual(invalid["error"]["code"], "invalid_arguments")
        self.assertFalse(invalid_workspace.exists())

        existing = self.base / "existing-project"
        existing.mkdir()
        sentinel = existing / "keep.bin"
        sentinel.write_bytes(b"synthetic-existing-content\x00\x01")
        before = {
            path.relative_to(existing).as_posix(): path.read_bytes()
            for path in existing.rglob("*")
            if path.is_file()
        }
        failure = self.result(
            self.cli(*self.start_args(existing, with_docs=("architecture",)), "--apply"),
            ok=False,
        )
        self.assertEqual(failure["error"]["code"], "workspace_exists")
        after = {
            path.relative_to(existing).as_posix(): path.read_bytes()
            for path in existing.rglob("*")
            if path.is_file()
        }
        self.assertEqual(after, before)


if __name__ == "__main__":
    unittest.main()
