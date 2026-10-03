"""Create a project entry and its planning task using the same workflow engine."""

from pathlib import Path
from typing import Any

from . import engine


PROJECT_FILES = (
    "AGENTS.md", "README.md", "CONTEXT.md", ".gitignore",
    "docs/00-入口层/00-项目总览.md", "docs/10-流程层/10-项目启动SOP.md",
    "docs/20-规则层/20-项目规则.md", "docs/30-触发层/30-项目验收.md",
)

OPTIONAL_DOCUMENTS = {
    name: f"docs/project/{name}.md"
    for name in ("environment", "architecture", "progress", "summary", "results")
}


def start(workspace: str | Path, project_id: str, name: str, brief: str = "",
          task_id: str = "kickoff", mode: str = "assisted", *, apply: bool = False,
          with_docs: list[str] | None = None) -> dict[str, Any]:
    engine.identifier(task_id)
    if (with_docs is not None and (not isinstance(with_docs, list)
            or any(not isinstance(document, str) or document not in OPTIONAL_DOCUMENTS
                   for document in with_docs))):
        raise engine.WorkflowError("invalid_project_documents", "Choose only declared optional project documents.")
    name = engine.plain_text(name, maximum=100)
    if brief:
        brief = engine.plain_text(brief)
    directory = engine.local_path(engine.ROOT, "templates/project")
    selected = [OPTIONAL_DOCUMENTS[document] for document in sorted(set(with_docs or []))]
    files = {relative: engine.local_path(directory, relative + ".tmpl").read_text(encoding="utf-8")
             .replace("{{TASK_ID}}", task_id) for relative in (*PROJECT_FILES, *selected)}
    files[".agent-workflow.local.json"] = engine.encode({
        "schema_version": "1.0", "framework_root": str(engine.ROOT), "task_id": task_id,
    })
    payload = {"project_name": name, "goal": brief, "users": "", "in_scope": "",
               "out_of_scope": "", "success_criteria": ""}
    result = engine.new(workspace, project_id, "project-planning", task_id, mode, apply=apply,
                        root_files=files, template_overrides={"payload.json": engine.encode(payload)})
    return {**result, "entry": "AGENTS.md", "scope": "project planning only; no implementation or external operations"}
