"""Create a project entry and its planning task using the same workflow engine."""

import json
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
    return {
        **result,
        "entry": "AGENTS.md",
        "scope": "project planning only; no implementation or external operations",
        "business_environment": {
            "policy": "per_project",
            "requirements_file": f"tasks/{task_id}/plan.md",
            "verification_file": OPTIONAL_DOCUMENTS["environment"] if "environment" in documents else None,
            "configured_by_start": False,
            "verified_by_start": False,
        },
    }


DETECTED_ENV_PATTERNS = {
    "python": ["requirements.txt", "pyproject.toml", "setup.py", "setup.cfg", "Pipfile", "environment.yml"],
    "node": ["package.json", "pnpm-lock.yaml", "package-lock.json", "yarn.lock"],
    "rust": ["Cargo.toml"],
    "golang": ["go.mod"],
    "java": ["pom.xml", "build.gradle", "build.gradle.kts"],
    "dotnet": [],
    "cpp": ["CMakeLists.txt", "meson.build", "conanfile.txt", "vcpkg.json"],
    "php": ["composer.json"],
    "ruby": ["Gemfile", "Rakefile"],
    "dart": ["pubspec.yaml"],
    "swift": ["Package.swift"],
    "elixir": ["mix.exs"],
}

# Solution and project files keep their own names, so match them by suffix.
DETECTED_ENV_SUFFIXES = {".sln": "dotnet", ".csproj": "dotnet", ".fsproj": "dotnet", ".vbproj": "dotnet"}


def detect_environments(root: Path) -> dict[str, list[str]]:
    detected: dict[str, set[str]] = {}
    for env_name, files in sorted(DETECTED_ENV_PATTERNS.items()):
        found = {name for name in files if (root / name).is_file()}
        if found:
            detected.setdefault(env_name, set()).update(found)
    try:
        entries = sorted(root.iterdir())
    except OSError:
        entries = []
    for path in entries:
        env_name = DETECTED_ENV_SUFFIXES.get(path.suffix.lower())
        if env_name and path.is_file():
            detected.setdefault(env_name, set()).add(path.name)
    return {env_name: sorted(names) for env_name, names in sorted(detected.items())}


def adopt(workspace: str | Path, project_id: str, name: str = "", brief: str = "",
          task_id: str = "kickoff", mode: str = "assisted", *, apply: bool = False,
          with_docs: list[str] | None = None) -> dict[str, Any]:
    root = engine.external_workspace(workspace)
    if not root.is_dir():
        raise engine.WorkflowError("workspace_not_found", "Target workspace directory does not exist for adoption.")
    engine.identifier(project_id)
    engine.identifier(task_id)
    if mode not in engine.MODES:
        raise engine.WorkflowError("invalid_mode", "Unknown interaction mode.")
    documents = select_documents(with_docs)
    project_name = engine.plain_text(name, maximum=100) if name else root.name
    if brief:
        brief = engine.plain_text(brief)
    else:
        brief = "历史项目非破坏性纳管与协作规范对齐"

    pack = engine.load_pack("project-planning")
    task_dir = root / "tasks" / task_id
    if task_dir.exists():
        raise engine.WorkflowError("task_exists", f"Task '{task_id}' already exists in workspace; choose another task-id or resume existing task.")

    existing_project_json = root / "project.json"
    if existing_project_json.is_file():
        p_data: dict[str, Any] | None = None
        try:
            p_data = json.loads(existing_project_json.read_text(encoding="utf-8"))
            if not isinstance(p_data, dict) or p_data.get("schema_version") != "1.0":
                raise engine.WorkflowError("invalid_project_facts", "Existing project.json is not a valid 1.0 schema.")
        except (OSError, json.JSONDecodeError) as exc:
            raise engine.WorkflowError("invalid_project_facts", "Existing project.json is corrupted or unreadable.") from exc
        # An adopted workspace already owns one project identity. Adopting it
        # under a second ID would write task facts that every later command
        # rejects, so refuse before touching anything.
        assert p_data is not None
        existing_project_id = p_data.get("project_id")
        if not isinstance(existing_project_id, str) or not engine.IDENTIFIER.fullmatch(existing_project_id):
            raise engine.WorkflowError("invalid_project_facts", "Existing project.json has no usable project_id.")
        if existing_project_id != project_id:
            raise engine.WorkflowError(
                "project_identity_mismatch",
                f"This workspace already belongs to project '{existing_project_id}'; adopt it with "
                f"--project-id {existing_project_id}, or choose a new workspace. Nothing was written.",
            )

    detected = detect_environments(root)
    selected_docs = [OPTIONAL_DOCUMENTS[doc] for doc in documents]
    all_needed_files = render_project_files(task_id, [*PROJECT_FILES, *selected_docs])

    preserved_files: list[str] = []
    created_files: dict[str, str] = {}

    for relative, content in all_needed_files.items():
        target_path = root / relative
        if target_path.exists():
            preserved_files.append(relative)
            if relative == "AGENTS.md":
                framework_ref = "AGENTS.framework.md"
                if not (root / framework_ref).exists():
                    created_files[framework_ref] = content
        else:
            created_files[relative] = content

    if not existing_project_json.is_file():
        created_files["project.json"] = engine.encode({"schema_version": "1.0", "project_id": project_id})
    else:
        preserved_files.append("project.json")

    # The local marker is the zero-config navigation pointer for one task. Keep an
    # existing pointer byte-for-byte: adopting another task must not silently
    # retarget the session that already uses this workspace.
    local_marker = ".agent-workflow.local.json"
    marker_path = root / local_marker
    if marker_path.is_file():
        preserved_files.append(local_marker)
        try:
            marker_data = json.loads(marker_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            marker_data = {}
        pointed = marker_data.get("task_id") if isinstance(marker_data, dict) else None
        marker_outcome = {"file": local_marker, "preserved": True,
                          "active_task_id": pointed if isinstance(pointed, str) else None}
    else:
        created_files[local_marker] = engine.encode({
            "schema_version": "1.0", "framework_root": str(engine.ROOT), "task_id": task_id,
        })
        marker_outcome = {"file": local_marker, "preserved": False, "active_task_id": task_id}

    env_summary_lines = []
    if detected:
        for k, v in detected.items():
            env_summary_lines.append(f"- **{k}**: {', '.join(v)}")
    else:
        env_summary_lines.append("- 未嗅探到标准配置文件；待人工梳理。")
    env_summary_text = "\n".join(env_summary_lines)

    adopted_plan = f"""# 历史项目纳管与改造方案

## 可执行任务
- 梳理老项目既有代码结构与功能模块
- 对齐老项目现有环境与运行配置
- 建立符合通用智能体协作框架的规范文档与任务流

## 技术选择
- 保持既有技术栈与运行时环境不变
{env_summary_text}
- 引入通用智能体协作规范底座与治理机制

## 风险
- 改造过程可能涉及代码冲突或依赖版本差异；坚持非破坏性接入，保留历史提交与配置。

## 验收方法
- 检查原有测试套件全量通过
- 检查框架协作与任务状态机正常就绪
"""

    payload = {
        "project_name": project_name,
        "goal": brief,
        "users": "开发者与协作智能体",
        "in_scope": "代码现状梳理、协作骨架对齐、环境自适应探测",
        "out_of_scope": "破坏性重构、外部未经授权的部署",
        "success_criteria": "原有功能与Git历史逐字节保留，协作框架状态机就绪",
    }

    task_files = [f"tasks/{task_id}/{name}" for name in ("task.json", "payload.json", "plan.md")]

    result: dict[str, Any] = {
        "project_id": project_id,
        "task_id": task_id,
        "workflow": "project-planning",
        "mode": mode,
        "workspace": str(root),
        "applied": apply,
        "adopted": True,
        "detected_environments": detected,
        "preserved_files": sorted(preserved_files),
        "created_files": sorted([*created_files, *task_files]),
        "local_marker": marker_outcome,
        "entry": "AGENTS.md",
        "scope": "project adoption and planning only; no destructive modifications or external operations",
        "business_environment": {
            "policy": "per_project",
            "requirements_file": f"tasks/{task_id}/plan.md",
            "verification_file": OPTIONAL_DOCUMENTS["environment"] if "environment" in documents else None,
            "configured_by_adopt": False,
            "verified_by_adopt": False,
            "detected_environments": detected,
        },
    }

    if not apply:
        return result

    for relative, content in created_files.items():
        if relative.startswith("tasks/"):
            continue
        dest = engine.local_path(root, relative)
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_text(content, encoding="utf-8", newline="\n")

    task_dir.mkdir(parents=True, exist_ok=True)
    task_facts = {
        "schema_version": "1.0",
        "id": task_id,
        "project_id": project_id,
        "workflow": "project-planning",
        "pack_digest": engine.pack_digest("project-planning"),
        "mode": mode,
        "stage": pack["stages"][0]["id"],
        "next_action": "Review preserved files, fill payload.json and plan kickoff.",
        "decisions": {},
    }
    engine.atomic_json(task_dir / "task.json", task_facts)
    (task_dir / "payload.json").write_text(engine.encode(payload), encoding="utf-8", newline="\n")
    (task_dir / "plan.md").write_text(adopted_plan, encoding="utf-8", newline="\n")

    try:
        result["completion"] = engine.context(root, task_id, write=True)["completion"]
    except (engine.WorkflowError, OSError):
        result["completion"] = {
            "operation": "completed",
            "local_record": "incomplete",
            "repeat_operation": False,
            "recovery": ["context", str(root), "--task-id", task_id, "--write"],
        }
    return result
