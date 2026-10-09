"""Behavioral contract tests for the public CLI and read-only context hook."""

import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
from concurrent.futures import ThreadPoolExecutor
import unittest


ROOT = Path(__file__).resolve().parents[1]


class CliContractTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name)
        self.workspace = self.base / "workspace"

    def cli(self, *args: object, env: dict[str, str] | None = None) -> subprocess.CompletedProcess[str]:
        return self.cli_at(ROOT, *args, env=env)

    def cli_at(self, runtime: Path, *args: object, env: dict[str, str] | None = None) -> subprocess.CompletedProcess[str]:
        child_env = os.environ.copy()
        if env:
            child_env.update(env)
        return subprocess.run(
            [sys.executable, "-m", "agent_workflow", *(str(arg) for arg in args)],
            cwd=runtime,
            env=child_env,
            capture_output=True,
            text=True,
            check=False,
        )

    def runtime_copy(self) -> Path:
        runtime = self.base / "runtime-copy"
        shutil.copytree(ROOT, runtime, ignore=shutil.ignore_patterns(
            ".git", "__pycache__", "*.pyc", "*.egg-info", "build", "dist"
        ))
        return runtime

    def install_pack(self, runtime: Path, pack: dict) -> None:
        directory = runtime / "agent_workflow" / "packs" / pack["id"]
        directory.mkdir(parents=True)
        (directory / "workflow.json").write_text(json.dumps(pack, ensure_ascii=False), encoding="utf-8")

    def hook(self, env: dict[str, str] | None = None) -> subprocess.CompletedProcess[str]:
        child_env = os.environ.copy()
        child_env.pop("AGENT_WORKFLOW_WORKSPACE", None)
        child_env.pop("AGENT_WORKFLOW_TASK_ID", None)
        if env:
            child_env.update(env)
        return subprocess.run(
            [sys.executable, "scripts/context_hook.py", "--event", "SessionStart"],
            cwd=ROOT,
            env=child_env,
            capture_output=True,
            text=True,
            stdin=subprocess.DEVNULL,
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
            error = payload.get("error")
            self.assertIsInstance(error, dict)
            self.assertIsInstance(error.get("code"), str)
            self.assertIsInstance(error.get("message"), str)
        return payload

    def create(self, workflow: str, *, workspace: Path | None = None, task_id: str = "task",
               project_id: str = "synthetic-project", mode: str | None = None, apply: bool = True) -> dict:
        target = workspace or self.workspace
        args: list[object] = [
            "new", target, "--project-id", project_id, "--workflow", workflow,
            "--task-id", task_id,
        ]
        if mode is not None:
            args += ["--mode", mode]
        if apply:
            args.append("--apply")
        return self.result(self.cli(*args), ok=True)

    def status(self, *, workspace: Path | None = None, task_id: str = "task") -> dict:
        return self.result(self.cli("status", workspace or self.workspace, "--task-id", task_id), ok=True)

    def task_file(self, name: str, *, workspace: Path | None = None, task_id: str = "task") -> Path:
        return (workspace or self.workspace) / "tasks" / task_id / name

    def read_task(self, *, workspace: Path | None = None, task_id: str = "task") -> dict:
        return json.loads(self.task_file("task.json", workspace=workspace, task_id=task_id).read_text(encoding="utf-8"))

    def write_json(self, path: Path, value: object) -> None:
        path.write_text(json.dumps(value, ensure_ascii=False, allow_nan=True, indent=2), encoding="utf-8")

    def advance(self, *, workspace: Path | None = None, task_id: str = "task", apply: bool = True):
        args: list[object] = ["advance", workspace or self.workspace, "--task-id", task_id]
        if apply:
            args.append("--apply")
        return self.cli(*args)

    def valid_catalog(self, *, workspace: Path | None = None, task_id: str = "task") -> None:
        self.write_json(self.task_file("payload.json", workspace=workspace, task_id=task_id), {
            "sku": "SYN-001", "title": "合成商品", "price": 12.5,
            "currency": "CNY", "synthetic": True,
        })

    def decision(self, answer: str, *, workspace: Path | None = None, task_id: str = "task", apply: bool = True):
        args: list[object] = [
            "decision", workspace or self.workspace, "--task-id", task_id,
            "--decision-id", "review-acceptance", "--answer", answer, "--by", "synthetic-reviewer",
        ]
        if apply:
            args.append("--apply")
        return self.cli(*args)

    def test_doctor_checks_framework_tools_not_the_business_runtime(self) -> None:
        diagnostics = self.result(self.cli("doctor"), ok=True)
        self.assertEqual(diagnostics["runtime_scope"], "framework_tools_only")
        self.assertIsNone(diagnostics["business_runtime_constraint"])
        self.assertFalse(diagnostics["business_runtime_checked"])

    def test_preview_and_pack_discovery_do_not_require_real_business_data(self) -> None:
        self.result(self.cli("doctor"), ok=True)
        packs = self.result(self.cli("packs"), ok=True)
        self.assertIn("ecommerce-catalog", json.dumps(packs, ensure_ascii=False))
        self.assertIn("document-delivery", json.dumps(packs, ensure_ascii=False))
        self.create("ecommerce-catalog", apply=False)
        self.assertFalse(self.workspace.exists())
        self.create("ecommerce-catalog")
        facts = self.task_file("task.json")
        before = facts.read_bytes()
        token = "sk" + "-" + "A" * 24
        failure = self.result(self.cli("task-plan", self.workspace, "--task-id", "task",
                                       "--next-action", token, "--apply"), ok=False)
        self.assertNotIn(token, json.dumps(failure))
        self.assertEqual(facts.read_bytes(), before)
    def test_catalog_and_document_delivery_complete_independent_local_flows(self) -> None:
        self.create("ecommerce-catalog")
        self.valid_catalog()
        facts_path = self.task_file("task.json")
        before = facts_path.read_bytes()
        self.result(self.decision("accept", apply=False), ok=False)
        self.assertEqual(facts_path.read_bytes(), before)
        self.result(self.advance(apply=False), ok=True)
        self.assertEqual(self.status()["task"]["stage"], "collect")
        self.result(self.advance(), ok=True)
        state = self.status()
        self.assertEqual(state["task"]["stage"], "review")
        facts = self.read_task()
        self.assertEqual(facts["schema_version"], "1.0")
        self.assertEqual(facts["project_id"], "synthetic-project")
        self.assertEqual(facts["workflow"], "ecommerce-catalog")
        self.assertIn("decisions", facts)
        self.assertTrue(any("SOP.md" in str(doc) for doc in state["documents"]))
        self.task_file("review.md").write_text(
            "# 商品资料审核\n\n## 检查结论\n合成字段相互一致。\n", encoding="utf-8"
        )
        before = facts_path.read_bytes()
        self.result(self.decision("accept", apply=False), ok=True)
        self.assertEqual(facts_path.read_bytes(), before)
        self.result(self.decision("accept"), ok=True)
        self.assertTrue(self.status()["can_advance"])
        review = self.task_file("review.md")
        review.write_text("# 审核\n\n## 检查结论\n重新核对合成字段。\n", encoding="utf-8")
        self.assertFalse(self.status()["can_advance"])
        self.result(self.decision("accept"), ok=True)
        self.result(self.advance(), ok=True)
        final = self.status()
        self.assertEqual(final["task"]["stage"], "ready")
        self.assertTrue(final["completed_locally"])
        self.assertIsNone(final["next_stage"])
        self.assertFalse(final["can_advance"])
        self.assertEqual(final["business_system_state"], "not_queried")
        review.write_text("# 审核\n\n## 检查结论\n完成后证据又被修改。\n", encoding="utf-8")
        self.assertFalse(self.status()["evidence_valid"])
        self.assertFalse(self.status()["completed_locally"])

        docs = self.base / "docs-workspace"
        self.create("document-delivery", workspace=docs, task_id="memo", project_id="synthetic-docs")
        self.write_json(docs / "tasks" / "memo" / "payload.json", {
            "audience": "合成读者", "purpose": "验证本地流程", "synthetic": True,
        })
        (docs / "tasks" / "memo" / "draft.md").write_text("# 合成草稿\n正文。\n", encoding="utf-8")
        self.result(self.advance(workspace=docs, task_id="memo"), ok=True)
        (docs / "tasks" / "memo" / "final.md").write_text("# 合成定稿\n正文。\n", encoding="utf-8")
        self.result(self.decision("accept", workspace=docs, task_id="memo"), ok=True)
        self.result(self.advance(workspace=docs, task_id="memo"), ok=True)
        complete = self.status(workspace=docs, task_id="memo")
        self.assertEqual(complete["task"]["stage"], "complete")
        self.assertIsNone(complete["next_stage"])
        self.assertFalse(complete["can_advance"])
    def test_arbitrary_third_pack_uses_its_own_stage_ids(self) -> None:
        runtime = self.runtime_copy()
        pack_id = "synthetic-arbitrary"
        pack = {
            "schema_version": "1.0", "id": pack_id, "name": "合成流程",
            "version": "0.1.0", "description": "仅用于验证通用流程状态。",
            "templates": {"payload.json": "{\"synthetic\": true}\n"},
            "stages": [
                {"id": "gather-local", "documents": ["agent_workflow/packs/document-delivery/SOP.md"], "checks": []},
                {"id": "handoff-local", "documents": ["agent_workflow/packs/document-delivery/SOP.md"], "checks": []},
                {"id": "archived-local", "documents": ["agent_workflow/packs/document-delivery/SOP.md"], "checks": []},
            ],
        }
        self.install_pack(runtime, pack)
        workspace = self.base / "third-pack-workspace"
        self.result(self.cli_at(runtime, "new", workspace, "--project-id", "synthetic-third",
                                "--workflow", pack_id, "--task-id", "case", "--apply"), ok=True)
        self.assertEqual(self.read_task(workspace=workspace, task_id="case")["stage"], "gather-local")
        self.result(self.cli_at(runtime, "advance", workspace, "--task-id", "case", "--apply"), ok=True)
        state = self.result(self.cli_at(runtime, "status", workspace, "--task-id", "case"), ok=True)
        self.assertEqual(state["task"]["stage"], "handoff-local")
        self.assertEqual(state["next_stage"], "archived-local")
        legacy = self.base / "old-pack-workspace"
        self.result(self.cli_at(runtime, "new", legacy, "--project-id", "synthetic-old",
                                "--workflow", "ecommerce-catalog", "--task-id", "old", "--apply"), ok=True)
        sop = runtime / "agent_workflow" / "packs" / "ecommerce-catalog" / "SOP.md"
        sop.write_text(sop.read_text(encoding="utf-8") + "\n合成流程规则变更。\n", encoding="utf-8")
        stale = self.result(self.cli_at(runtime, "status", legacy, "--task-id", "old"), ok=False)
        self.assertEqual(stale["error"]["code"], "workflow_changed")
    def test_unsupported_check_and_pack_path_traversal_fail_closed(self) -> None:
        runtime = self.runtime_copy()
        base_pack = {
            "schema_version": "1.0", "name": "合成恶意规则", "version": "0.1.0",
            "description": "验证业务包规则拒绝不受支持的动作。",
            "templates": {"payload.json": "{}\n"},
        }
        documents = ["agent_workflow/packs/document-delivery/SOP.md"]
        malformed = (
            ("unsupported-kind", [[{"id": "call-out", "kind": "external-side-effect"}], []]),
            ("escape-reference", [[{"id": "read-outside", "kind": "file-content", "file": "../../outside.md", "contains": ["synthetic"]}], []]),
            ("duplicate-cross-stage", [[{"id": "shared", "kind": "file-content", "file": "review.md", "contains": ["synthetic"]}],
                                        [{"id": "shared", "kind": "decision", "question": "Accept?", "recommendation": "Inspect evidence.", "answers": ["accept", "revise"], "required_answer": "accept"}], []]),
        )
        for pack_id, check_stages in malformed:
            with self.subTest(pack=pack_id):
                stages = [{"id": f"stage-{i}", "documents": documents, "checks": checks}
                          for i, checks in enumerate(check_stages)]
                pack = {**base_pack, "id": pack_id, "stages": stages}
                self.install_pack(runtime, pack)
                workspace = self.base / f"rejected-{pack_id}"
                failure = self.result(self.cli_at(runtime, "new", workspace, "--project-id", "synthetic-negative",
                                                  "--workflow", pack_id, "--task-id", "case", "--apply"), ok=False)
                if pack_id == "duplicate-cross-stage":
                    self.assertEqual(failure["error"]["code"], "invalid_workflow")
                self.assertFalse(workspace.exists())
    def test_modes_persist_across_cli_calls_and_never_infer_acceptance(self) -> None:
        for index, mode in enumerate((None, "assisted", "full-auto", "manual-review")):
            with self.subTest(mode=mode):
                workspace = self.base / f"mode-{index}"
                selected = mode or "assisted"
                self.create("ecommerce-catalog", workspace=workspace, task_id="t", mode=mode)
                task = workspace / "tasks" / "t"
                self.write_json(task / "payload.json", {
                    "sku": "SYN-002", "title": "合成商品", "price": 1, "currency": "CNY", "synthetic": True,
                })
                self.result(self.advance(workspace=workspace, task_id="t"), ok=True)
                state = self.status(workspace=workspace, task_id="t")
                self.assertEqual(state["task"]["mode"], selected)
                self.assertEqual(state["task"]["stage"], "review")
                (task / "review.md").write_text("# 审核\n\n## 检查结论\n合成证据通过。\n", encoding="utf-8")
                self.assertFalse(state["can_advance"])
                self.result(self.advance(workspace=workspace, task_id="t"), ok=False)
                plan = ["task-plan", workspace, "--task-id", "t", "--mode", "full-auto",
                        "--next-action", "复核合成审核正文"]
                before_plan = (task / "task.json").read_bytes()
                self.result(self.cli(*plan), ok=True)
                self.assertEqual((task / "task.json").read_bytes(), before_plan)
                self.result(self.cli(*plan, "--apply"), ok=True)
                self.assertEqual(self.read_task(workspace=workspace, task_id="t")["mode"], "full-auto")
                self.assertEqual(self.read_task(workspace=workspace, task_id="t")["stage"], "review")
                self.result(self.advance(workspace=workspace, task_id="t"), ok=False)
                self.result(self.decision("accept", workspace=workspace, task_id="t"), ok=True)
                self.result(self.advance(workspace=workspace, task_id="t"), ok=True)
                self.assertEqual(self.status(workspace=workspace, task_id="t")["task"]["stage"], "ready")
    def test_unknown_mode_workflow_path_escape_wrong_task_and_project_reuse_are_rejected(self) -> None:
        self.result(self.cli("new", self.workspace, "--project-id", "p", "--workflow", "missing-pack",
                             "--task-id", "t", "--apply"), ok=False)
        self.result(self.cli("new", self.workspace, "--project-id", "p", "--workflow", "ecommerce-catalog",
                             "--task-id", "t", "--mode", "not-a-mode", "--apply"), ok=False)
        self.result(self.cli("new", self.workspace, "--project-id", "p", "--workflow", "ecommerce-catalog",
                             "--task-id", "../../escaped", "--apply"), ok=False)
        self.assertFalse((self.base / "escaped").exists())
        self.assertFalse((self.workspace / "escaped").exists())
        self.create("ecommerce-catalog", project_id="original-project")
        self.result(self.cli("new", self.workspace, "--project-id", "different-project",
                             "--workflow", "document-delivery", "--task-id", "other", "--apply"), ok=False)
        self.result(self.cli("new", self.workspace, "--project-id", "original-project",
                             "--workflow", "document-delivery", "--task-id", "another", "--apply"), ok=False)
        self.result(self.cli("status", self.workspace, "--task-id", "not-this-task"), ok=False)
        self.assertEqual(json.loads((self.workspace / "project.json").read_text(encoding="utf-8"))["project_id"],
                         "original-project")
    def test_invalid_catalog_values_block_advance(self) -> None:
        bad_payloads = (
            {"sku": "SYN", "title": "商品", "currency": "CNY", "synthetic": True},
            {"sku": "SYN", "title": "商品", "price": "3.2", "currency": "CNY", "synthetic": True},
            {"sku": "SYN", "title": "商品", "price": float("nan"), "currency": "CNY", "synthetic": True},
            {"sku": "SYN", "title": "商品", "price": -1, "currency": "CNY", "synthetic": True},
        )
        for index, payload in enumerate(bad_payloads):
            with self.subTest(payload=payload):
                workspace = self.base / f"invalid-{index}"
                self.create("ecommerce-catalog", workspace=workspace, task_id="t")
                self.write_json(workspace / "tasks" / "t" / "payload.json", payload)
                status = self.status(workspace=workspace, task_id="t")
                self.assertFalse(status["can_advance"])
                self.result(self.advance(workspace=workspace, task_id="t"), ok=False)
                self.assertEqual(self.status(workspace=workspace, task_id="t")["task"]["stage"], "collect")
    def test_template_todo_and_revision_are_not_accepted_as_evidence(self) -> None:
        self.create("ecommerce-catalog")
        self.valid_catalog()
        self.result(self.advance(), ok=True)
        status = self.status()
        self.assertFalse(status["can_advance"])
        self.result(self.advance(), ok=False)
        self.task_file("review.md").write_text("# 审核\n\n## 检查结论\n已核对合成记录。\n", encoding="utf-8")
        self.result(self.decision("revise"), ok=True)
        self.assertFalse(self.status()["can_advance"])
        self.result(self.advance(), ok=False)

        docs = self.base / "todo-docs"
        self.create("document-delivery", workspace=docs, task_id="d")
        self.write_json(docs / "tasks" / "d" / "payload.json", {
            "audience": "合成读者", "purpose": "合成目的", "synthetic": True,
        })
        self.assertFalse(self.status(workspace=docs, task_id="d")["can_advance"])
        self.result(self.advance(workspace=docs, task_id="d"), ok=False)
    def test_concurrent_new_has_one_winner_and_preserves_workspace(self) -> None:
        def create(task_id: str):
            return self.cli("new", self.workspace, "--project-id", "race-project", "--workflow",
                            "ecommerce-catalog", "--task-id", task_id, "--apply")
        with ThreadPoolExecutor(max_workers=2) as pool:
            responses = list(pool.map(create, ("race-a", "race-b")))
        parsed = [self.result(proc, ok=proc.returncode == 0) for proc in responses]
        winners = [payload for payload in parsed if payload["ok"]]
        losers = [payload for payload in parsed if not payload["ok"]]
        self.assertEqual(len(winners), 1)
        self.assertEqual(losers[0]["error"]["code"], "workspace_exists")
        task_id = winners[0]["task_id"]
        self.assertEqual([path.name for path in (self.workspace / "tasks").iterdir()], [task_id])
        self.assertEqual(self.status(task_id=task_id)["project"]["id"], "race-project")
    def test_snapshot_check_detects_tampering_and_fact_edits_read_only(self) -> None:
        self.create("ecommerce-catalog")
        self.result(self.cli("context", self.workspace, "--task-id", "task", "--write"), ok=True)
        snapshot = self.workspace / "tasks" / "task" / "workflow-state.json"
        state = json.loads(snapshot.read_text(encoding="utf-8"))

        state["task"]["stage"] = "tampered-snapshot"
        snapshot.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")
        damaged = snapshot.read_bytes()
        self.cli("context", self.workspace, "--task-id", "task")
        self.assertEqual(snapshot.read_bytes(), damaged, "read-only context must not repair the snapshot")
        self.result(self.cli("context", self.workspace, "--task-id", "task", "--write"), ok=True)
        self.result(self.cli("context", self.workspace, "--task-id", "task", "--check"), ok=True)

        self.valid_catalog()
        changed = snapshot.read_bytes()
        self.result(self.cli("context", self.workspace, "--task-id", "task", "--check"), ok=False)
        self.assertEqual(snapshot.read_bytes(), changed)
        snapshot.write_text("{invalid JSON", encoding="utf-8")
        self.result(self.cli("context", self.workspace, "--task-id", "task", "--check"), ok=False)
        damaged = snapshot.read_bytes()
        self.cli("context", self.workspace, "--task-id", "task")
        self.assertEqual(snapshot.read_bytes(), damaged)
        self.result(self.cli("context", self.workspace, "--task-id", "task", "--write"), ok=True)
        self.result(self.cli("context", self.workspace, "--task-id", "task", "--check"), ok=True)
    def test_hook_without_unique_selection_only_routes_and_never_writes(self) -> None:
        self.create("ecommerce-catalog", task_id="synthetic-hook-target-8f3a")
        before = {p.relative_to(self.workspace): p.read_bytes() for p in self.workspace.rglob("*") if p.is_file()}
        no_env = self.hook()
        self.assertEqual(no_env.returncode, 0, no_env.stdout + no_env.stderr)
        self.assertIn("AGENTS", json.loads(no_env.stdout)["hookSpecificOutput"]["additionalContext"])
        incomplete = self.hook({"AGENT_WORKFLOW_WORKSPACE": str(self.workspace)})
        self.assertEqual(incomplete.returncode, 0, incomplete.stdout + incomplete.stderr)
        context = json.loads(incomplete.stdout)["hookSpecificOutput"]["additionalContext"]
        self.assertIn("AGENTS", context)
        self.assertNotIn("tasks/synthetic-hook-target-8f3a", context)
        after = {p.relative_to(self.workspace): p.read_bytes() for p in self.workspace.rglob("*") if p.is_file()}
        self.assertEqual(after, before)
    def test_hook_with_explicit_task_is_read_only(self) -> None:
        self.create("ecommerce-catalog")
        before = {p.relative_to(self.workspace): p.read_bytes() for p in self.workspace.rglob("*") if p.is_file()}
        proc = self.hook({
            "AGENT_WORKFLOW_WORKSPACE": str(self.workspace),
            "AGENT_WORKFLOW_TASK_ID": "task",
        })
        self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
        self.assertIn("task", json.loads(proc.stdout)["hookSpecificOutput"]["additionalContext"])
        after = {p.relative_to(self.workspace): p.read_bytes() for p in self.workspace.rglob("*") if p.is_file()}
        self.assertEqual(after, before)

if __name__ == "__main__":
    unittest.main()
