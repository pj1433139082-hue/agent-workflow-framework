"""Create a project entry and its planning task using the same workflow engine."""

from pathlib import Path
import stat
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


def select_documents(documents: list[str] | None) -> list[str]:
    if documents is not None and (not isinstance(documents, list)
            or any(not isinstance(document, str) or document not in OPTIONAL_DOCUMENTS for document in documents)):
        raise engine.WorkflowError("invalid_project_documents", "Choose only declared optional project documents.")
    return sorted(set(documents or []))


def render_project_files(task_id: str, relatives: list[str]) -> dict[str, str]:
    engine.identifier(task_id)
    directory = engine.local_path(engine.ROOT, "templates/project")
    files = {}
    for relative in relatives:
        path = engine.local_path(directory, relative + ".tmpl")
        info = path.stat()
        if not stat.S_ISREG(info.st_mode) or info.st_size > 1_000_000:
            raise engine.WorkflowError("invalid_project_template", "A declared project template is unavailable or too large.")
        content = path.read_text(encoding="utf-8").replace("{{TASK_ID}}", task_id)
        if len(content.encode("utf-8")) > 1_000_000 or "{{" in content or "}}" in content:
            raise engine.WorkflowError("invalid_project_template", "A project template contains unsupported placeholders or exceeds the size limit.")
        files[relative] = content
    return files


def start(workspace: str | Path, project_id: str, name: str, brief: str = "",
          task_id: str = "kickoff", mode: str = "assisted", *, apply: bool = False,
          with_docs: list[str] | None = None) -> dict[str, Any]:
    engine.identifier(task_id)
    documents = select_documents(with_docs)
    name = engine.plain_text(name, maximum=100)
    if brief:
        brief = engine.plain_text(brief)
    selected = [OPTIONAL_DOCUMENTS[document] for document in documents]
    files = render_project_files(task_id, [*PROJECT_FILES, *selected])
    files[".agent-workflow.local.json"] = engine.encode({
        "schema_version": "1.0", "framework_root": str(engine.ROOT), "task_id": task_id,
    })
    payload = {"project_name": name, "goal": brief, "users": "", "in_scope": "",
               "out_of_scope": "", "success_criteria": ""}
    result = engine.new(workspace, project_id, "project-planning", task_id, mode, apply=apply,
                        root_files=files, template_overrides={"payload.json": engine.encode(payload)})
    return {**result, "entry": "AGENTS.md", "scope": "project planning only; no implementation or external operations"}
