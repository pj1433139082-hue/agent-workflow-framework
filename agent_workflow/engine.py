"""Declarative local workflows behind one CLI, with no business-system writes."""

from __future__ import annotations

from contextlib import contextmanager
import hashlib
import json
import math
import os
from pathlib import Path, PurePosixPath
import re
import shutil
import stat
import tempfile
from typing import Any, cast

from . import __version__

ROOT = Path(__file__).resolve().parent.parent
PACKS = Path(__file__).resolve().parent / "packs"
MODES = {"full-auto", "assisted", "manual-review"}
IDENTIFIER = re.compile(r"[a-z0-9][a-z0-9_-]{0,63}\Z")
PLACEHOLDER = re.compile(r"\bTODO\b|\bTBD\b|待填写|待补充|\{\{[^{}]+\}\}", re.IGNORECASE)
SENSITIVE = re.compile(
    r"(?i)(?:password|secret|api[_ -]?key|access[_ -]?token)\s*[:=]\s*\S+"
    r"|bearer\s+\S+|gh[pousr]_[A-Za-z0-9]{24,}|sk-[A-Za-z0-9]{24,}"
    r"|https?://[^ /@:]+:[^ /@]+@|-----BEGIN .*PRIVATE KEY-----"
)
BASE_DOCS = ["AGENTS.md", "docs/00-入口层/00-协作总览.md"]


class WorkflowError(ValueError):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code


def identifier(value: Any) -> str:
    if not isinstance(value, str) or not IDENTIFIER.fullmatch(value):
        raise WorkflowError("invalid_identity", "Use a lowercase, filesystem-safe ID, not a path.")
    if value.split(".", 1)[0] in {"con", "prn", "aux", "nul", *(f"com{i}" for i in range(1, 10)), *(f"lpt{i}" for i in range(1, 10))}:
        raise WorkflowError("invalid_identity", "The ID is reserved by the filesystem.")
    return value


def plain_text(value: Any, *, maximum: int = 1000) -> str:
    if not isinstance(value, str) or not value.strip() or len(value) > maximum:
        raise WorkflowError("invalid_text", "A nonempty bounded text value is required.")
    if any(ord(char) < 32 for char in value) or SENSITIVE.search(value):
        raise WorkflowError("sensitive_text", "Task metadata must not contain controls or credentials.")
    return value.strip()


def safe_path(path: Path) -> Path:
    """Refuse links/junctions before resolving; validate every existing ancestor."""
    path = Path(os.path.abspath(path))
    for component in [*reversed(path.parents), path]:
        try:
            info = component.lstat()
        except FileNotFoundError:
            continue
        if stat.S_ISLNK(info.st_mode) or getattr(info, "st_file_attributes", 0) & getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0):
            raise WorkflowError("unsafe_path", "Links and junctions are not accepted in task paths.")
    return path


def local_path(root: Path, relative: Any) -> Path:
    if not isinstance(relative, str) or "\\" in relative or ":" in relative:
        raise WorkflowError("unsafe_path", "Expected a portable relative path.")
    parts = PurePosixPath(relative)
    if parts.is_absolute() or not parts.parts or any(part in {".", ".."} for part in parts.parts):
        raise WorkflowError("unsafe_path", "The path must stay inside its workspace.")
    result = safe_path(root / relative)
    if not result.is_relative_to(safe_path(root)):
        raise WorkflowError("unsafe_path", "The path must stay inside its workspace.")
    return result


def external_workspace(path: str | Path) -> Path:
    result = safe_path(Path(path))
    if result == ROOT or result.is_relative_to(ROOT) or ROOT.is_relative_to(result):
        raise WorkflowError("private_workspace_required", "Choose a dedicated workspace outside the framework checkout.")
    if result == Path(result.anchor):
        raise WorkflowError("unsafe_path", "A drive/root directory cannot be a project workspace.")
    return result


def _object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise WorkflowError("invalid_json", "Duplicate JSON keys are not accepted.")
        result[key] = value
    return result


def read_json(path: Path) -> dict[str, Any]:
    safe_path(path)
    try:
        if path.stat().st_size > 1_000_000:
            raise WorkflowError("invalid_json", "JSON input exceeds the size limit.")
        value = json.loads(path.read_text(encoding="utf-8-sig"), object_pairs_hook=_object,
                           parse_constant=lambda _: (_ for _ in ()).throw(WorkflowError("invalid_json", "Nonfinite JSON values are not accepted.")))
    except (json.JSONDecodeError, UnicodeError) as error:
        raise WorkflowError("invalid_json", "The JSON document cannot be decoded.") from error
    except OSError as error:
        raise WorkflowError("missing_file", "A required local JSON document is unavailable.") from error
    if not isinstance(value, dict):
        raise WorkflowError("invalid_json", "The JSON root must be an object.")
    return value


def encode(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2, allow_nan=False) + "\n"


def atomic_json(path: Path, value: Any) -> None:
    safe_path(path)
    fd, name = tempfile.mkstemp(prefix=".write-", dir=path.parent)
    temporary = Path(name)
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as stream:
            stream.write(encode(value))
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def load_pack(pack_id: str) -> dict[str, Any]:
    identifier(pack_id)
    path = local_path(PACKS, f"{pack_id}/workflow.json")
    if not path.is_file():
        raise WorkflowError("unknown_workflow", "No such installed business workflow.")
    pack = read_json(path)
    if set(pack) != {"schema_version", "id", "name", "version", "description", "templates", "stages"} or pack.get("schema_version") != "1.0" or pack.get("id") != pack_id:
        raise WorkflowError("invalid_workflow", "The business pack has an unsupported schema or identity.")
    for field in ("name", "version", "description"):
        plain_text(pack[field])
    templates = pack["templates"]
    stages = pack["stages"]
    if not isinstance(templates, dict) or not isinstance(stages, list) or not stages:
        raise WorkflowError("invalid_workflow", "Templates and a nonempty stage list are required.")
    for name, content in templates.items():
        local_path(PACKS, name)
        if (PurePosixPath(name).parts[0] in {"task.json", "workflow-state.json", ".task-write-lock"}
                or any(part.startswith(".write-") for part in PurePosixPath(name).parts)
                or not isinstance(content, str)):
            raise WorkflowError("invalid_workflow", "Templates cannot replace task facts or generated state.")
    seen: set[str] = set()
    decisions: set[str] = set()
    check_ids: set[str] = set()
    for stage in stages:
        if not isinstance(stage, dict) or set(stage) != {"id", "documents", "checks"}:
            raise WorkflowError("invalid_workflow", "Each stage needs an ID, documents and checks.")
        stage_id = identifier(stage["id"])
        if stage_id in seen:
            raise WorkflowError("invalid_workflow", "Stage IDs must be unique.")
        seen.add(stage_id)
        if not isinstance(stage["documents"], list) or not isinstance(stage["checks"], list):
            raise WorkflowError("invalid_workflow", "Documents and checks must be lists.")
        for document in stage["documents"]:
            if not local_path(ROOT, document).is_file():
                raise WorkflowError("invalid_workflow", "A business pack documentation pointer is missing.")
        for check in stage["checks"]:
            if not isinstance(check, dict):
                raise WorkflowError("invalid_workflow", "Checks must be objects.")
            check_id = identifier(check.get("id"))
            if check_id in check_ids:
                raise WorkflowError("invalid_workflow", "Check IDs must be unique across the business workflow.")
            check_ids.add(check_id)
            kind = check.get("kind")
            if kind == "json-fields":
                if set(check) != {"id", "kind", "file", "fields"} or not isinstance(check["fields"], dict) or not check["fields"]:
                    raise WorkflowError("invalid_workflow", "json-fields requires explicit field rules.")
                local_path(PACKS, check["file"])
                for key, rule in check["fields"].items():
                    if not isinstance(key, str) or not isinstance(rule, dict) or not set(rule) <= {"type", "nonempty", "enum", "equals", "exclusive_minimum"} or rule.get("type") not in {"string", "number", "boolean"}:
                        raise WorkflowError("invalid_workflow", "Unknown field rule or type.")
                    if "enum" in rule and (not isinstance(rule["enum"], list) or not rule["enum"]):
                        raise WorkflowError("invalid_workflow", "enum must be a nonempty list.")
                    if "exclusive_minimum" in rule and (type(rule["exclusive_minimum"]) not in {int, float} or not math.isfinite(rule["exclusive_minimum"])):
                        raise WorkflowError("invalid_workflow", "The numeric bound must be finite.")
                    if "nonempty" in rule and (type(rule["nonempty"]) is not bool or rule["type"] != "string"):
                        raise WorkflowError("invalid_workflow", "nonempty is a boolean rule for string fields.")
                    if "exclusive_minimum" in rule and rule["type"] != "number":
                        raise WorkflowError("invalid_workflow", "Numeric bounds are only valid for number fields.")
            elif kind == "file-content":
                if (not {"id", "kind", "file", "contains"} <= set(check)
                        or not set(check) <= {"id", "kind", "file", "contains", "sections"}
                        or not isinstance(check["contains"], list)
                        or any(not isinstance(text, str) or not text for text in check["contains"])):
                    raise WorkflowError("invalid_workflow", "file-content requires literal text markers.")
                if "sections" in check:
                    sections = check["sections"]
                    if (not isinstance(sections, list) or not sections
                            or any(not isinstance(title, str) or not title.strip()
                                   or "\n" in title or "\r" in title for title in sections)
                            or len(set(sections)) != len(sections)):
                        raise WorkflowError("invalid_workflow", "sections requires unique nonempty Markdown section titles.")
                local_path(PACKS, check["file"])
            elif kind == "decision":
                if set(check) != {"id", "kind", "question", "recommendation", "answers", "required_answer"} or check_id in decisions:
                    raise WorkflowError("invalid_workflow", "Decisions need unique IDs and complete wording.")
                decisions.add(check_id)
                plain_text(check["question"])
                plain_text(check["recommendation"])
                if not isinstance(check["answers"], list) or len(check["answers"]) < 2 or any(not isinstance(answer, str) for answer in check["answers"]) or check["required_answer"] not in check["answers"]:
                    raise WorkflowError("invalid_workflow", "A decision needs explicit choices and a required answer.")
            else:
                raise WorkflowError("unsupported_check", "This check kind is not implemented; no dynamic code execution is allowed.")
    if stages[-1]["checks"]:
        raise WorkflowError("invalid_workflow", "The terminal stage cannot contain unexecutable transition checks.")
    return pack


def packs() -> list[dict[str, str]]:
    return [{key: pack[key] for key in ("id", "name", "version", "description")}
            for pack in (load_pack(path.name) for path in sorted(PACKS.iterdir()) if path.is_dir())]


def load_task(workspace: str | Path, task_id: str) -> tuple[Path, dict[str, Any], dict[str, Any], dict[str, Any]]:
    root = external_workspace(workspace)
    identifier(task_id)
    project = read_json(root / "project.json")
    if set(project) != {"schema_version", "project_id"} or project.get("schema_version") != "1.0":
        raise WorkflowError("invalid_project", "The project identity is invalid.")
    identifier(project["project_id"])
    task_dir = local_path(root, f"tasks/{task_id}")
    task = read_json(task_dir / "task.json")
    fields = {"schema_version", "id", "project_id", "workflow", "pack_digest", "mode", "stage", "next_action", "decisions"}
    if set(task) != fields or task.get("schema_version") != "1.0" or task.get("id") != task_id or task.get("project_id") != project["project_id"]:
        raise WorkflowError("task_identity_mismatch", "Task and project identities do not match.")
    if task["mode"] not in MODES or not isinstance(task["decisions"], dict):
        raise WorkflowError("invalid_task", "Task execution mode or decisions are invalid.")
    plain_text(task["next_action"])
    pack = load_pack(task["workflow"])
    if task["pack_digest"] != pack_digest(pack["id"]):
        raise WorkflowError("workflow_changed", "The business pack changed; review and migrate the task explicitly instead of silently changing its rules.")
    if task["stage"] not in {stage["id"] for stage in pack["stages"]}:
        raise WorkflowError("invalid_task", "The task stage is not in its business workflow.")
    defined = {check["id"]: check for stage in pack["stages"] for check in stage["checks"] if check["kind"] == "decision"}
    for key, value in task["decisions"].items():
        if key not in defined or not isinstance(value, dict) or set(value) != {"answer", "by", "evidence_digest"} or value.get("answer") not in defined[key]["answers"]:
            raise WorkflowError("invalid_decision", "A stored business decision is invalid.")
        plain_text(value["by"], maximum=100)
        if not isinstance(value["evidence_digest"], str) or not re.fullmatch(r"[0-9a-f]{64}", value["evidence_digest"]):
            raise WorkflowError("invalid_decision", "A decision needs its evidence digest.")
    return task_dir, project, task, pack


def digest(path: Path) -> str:
    hasher = hashlib.sha256()
    with safe_path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            hasher.update(block)
    return hasher.hexdigest()


def pack_digest(pack_id: str) -> str:
    directory = local_path(PACKS, identifier(pack_id))
    files = {path.relative_to(directory).as_posix(): digest(path)
             for path in sorted(directory.rglob("*"))
             if safe_path(path).is_file() and "__pycache__" not in path.parts and path.suffix != ".pyc"}
    return hashlib.sha256(encode(files).encode("utf-8")).hexdigest()


def evidence(task_dir: Path) -> dict[str, str]:
    result: dict[str, str] = {}
    for path in sorted(task_dir.rglob("*")):
        safe_path(path)
        relative = path.relative_to(task_dir).as_posix()
        if (path.is_file() and relative not in {"task.json", "workflow-state.json"}
                and not any(part.startswith(".write-") for part in Path(relative).parts)):
            result[relative] = digest(path)
    return result


def evidence_digest(task_dir: Path) -> str:
    return hashlib.sha256(encode(evidence(task_dir)).encode("utf-8")).hexdigest()


def nonempty_markdown_sections(content: str, required: list[str]) -> bool:
    """Check prose under real level-two headings, not headings in fenced examples."""
    sections: dict[str, bool] = {}
    current: str | None = None
    fence: str | None = None
    content = re.sub(r"<!--.*?(?:-->|$)", "", content, flags=re.DOTALL)
    for line in content.splitlines():
        delimiter = re.match(r"^ {0,3}(`{3,}|~{3,})(.*)$", line)
        if fence is not None:
            if (delimiter and delimiter[1][0] == fence[0]
                    and len(delimiter[1]) >= len(fence) and not delimiter[2].strip()):
                fence = None
            continue
        if delimiter:
            fence = delimiter[1]
            continue
        heading = re.match(r"^ {0,3}(#{1,6})[ \t]+(.+?)[ \t]*$", line)
        if heading:
            title = re.sub(r"[ \t]+#+$", "", heading[2]).strip()
            if len(heading[1]) <= 2:
                current = title if len(heading[1]) == 2 else None
                if current is not None:
                    sections.setdefault(current, False)
        elif current is not None and not line.startswith(("    ", "\t")) and re.search(r"\w", line):
            sections[current] = True
    return all(sections.get(title, False) for title in required)


def evaluate(check: dict[str, Any], task_dir: Path, task: dict[str, Any]) -> dict[str, Any]:
    passed = False
    errors: list[str] = []
    kind = check["kind"]
    if kind == "decision":
        answer = task["decisions"].get(check["id"], {})
        passed = answer.get("answer") == check["required_answer"] and answer.get("evidence_digest") == evidence_digest(task_dir)
        if not passed:
            errors.append("business_answer_required_or_evidence_changed")
    elif kind == "file-content":
        path = local_path(task_dir, check["file"])
        try:
            if path.stat().st_size > 1_000_000:
                raise WorkflowError("invalid_text", "Evidence file exceeds size limit.")
            content = path.read_text(encoding="utf-8-sig")
            passed = bool(content.strip()) and not PLACEHOLDER.search(content) and all(text in content for text in check["contains"])
            if passed and "sections" in check:
                passed = nonempty_markdown_sections(content, check["sections"])
        except (OSError, UnicodeError):
            passed = False
        if not passed:
            errors.append("missing_or_placeholder_evidence")
    else:
        try:
            payload = read_json(local_path(task_dir, check["file"]))
        except WorkflowError as error:
            if error.code == "unsafe_path":
                raise
            payload = {}
            errors.append(error.code)
        for key, rule in check["fields"].items():
            value = payload.get(key)
            valid = ((isinstance(value, str) if rule["type"] == "string" else
                      type(value) in {int, float} and math.isfinite(cast(float, value)) if rule["type"] == "number" else
                      isinstance(value, bool)))
            if rule.get("nonempty") and (not isinstance(value, str) or not value.strip() or PLACEHOLDER.search(value)):
                valid = False
            if "enum" in rule and value not in rule["enum"]:
                valid = False
            if "equals" in rule and (value != rule["equals"] or type(value) is not type(rule["equals"])):
                valid = False
            if "exclusive_minimum" in rule and (type(value) not in {int, float} or value <= rule["exclusive_minimum"]):
                valid = False
            if not valid:
                errors.append(f"invalid_field:{key}")
        passed = not errors
    return {"id": check["id"], "kind": kind, "passed": bool(passed), "errors": errors}


def task_view(workspace: str | Path, task_id: str) -> dict[str, Any]:
    task_dir, project, task, pack = load_task(workspace, task_id)
    index = next(i for i, stage in enumerate(pack["stages"]) if stage["id"] == task["stage"])
    stage = pack["stages"][index]
    # Earlier evidence remains required after advancement; editing it cannot bypass checks.
    checks = [evaluate(check, task_dir, task) for earlier in pack["stages"][:index + 1] for check in earlier["checks"]]
    failed = {check["id"] for check in checks if not check["passed"]}
    pending = [check for earlier in pack["stages"][:index + 1] for check in earlier["checks"]
               if check["kind"] == "decision" and check["id"] in failed]
    next_stage = pack["stages"][index + 1]["id"] if index + 1 < len(pack["stages"]) else None
    documents = list(dict.fromkeys(BASE_DOCS + stage["documents"] + ["docs/00-入口层/02-交互与续接.md"]))
    sources = {"project.json": digest(task_dir.parent.parent / "project.json"),
               f"tasks/{task_id}/task.json": digest(task_dir / "task.json"),
               f"business-packs/{pack['id']}": task["pack_digest"],
               **{f"tasks/{task_id}/{name}": value for name, value in evidence(task_dir).items()}}
    return {"schema_version": "1.0", "framework_version": __version__, "project": {"id": project["project_id"]},
            "task": {key: task[key] for key in ("id", "workflow", "mode", "stage", "next_action")},
            "checks": checks, "pending_decisions": pending, "next_stage": next_stage,
            "can_advance": next_stage is not None and not failed, "evidence_valid": not failed,
            "completed_locally": next_stage is None and not failed, "documents": documents,
            "sources": sources, "business_system_state": "not_queried"}


def context(workspace: str | Path, task_id: str, *, write: bool = False, check: bool = False) -> dict[str, Any]:
    view = task_view(workspace, task_id)
    task_dir, _, _, _ = load_task(workspace, task_id)
    path = safe_path(task_dir / "workflow-state.json")
    matches = False
    if path.is_file():
        try:
            matches = read_json(path) == view
        except WorkflowError as error:
            if error.code == "unsafe_path":
                raise
    if write:
        atomic_json(path, view)
        matches = True
    if check and not matches:
        raise WorkflowError("snapshot_drift", "Generated state is missing or stale; use context --write, not a repeated business operation.")
    return {**view, "snapshot_matches": matches, "framework_root": str(ROOT),
            "documents_absolute": [str(local_path(ROOT, document)) for document in view["documents"]]}


@contextmanager
def task_lock(task_dir: Path):
    lock = safe_path(task_dir / ".task-write-lock")
    try:
        lock.mkdir()
    except FileExistsError as error:
        raise WorkflowError("task_busy", "Another task write is in progress; do not replay an uncertain operation.") from error
    try:
        yield
    finally:
        lock.rmdir()


def save_task(task_dir: Path, task: dict[str, Any]) -> dict[str, Any]:
    atomic_json(task_dir / "task.json", task)
    try:
        context(task_dir.parent.parent, task["id"], write=True)
    except (WorkflowError, OSError):
        return {"operation": "completed", "local_record": "incomplete", "repeat_operation": False,
                "recovery": ["context", str(task_dir.parent.parent), "--task-id", task["id"], "--write"]}
    return {"operation": "completed", "local_record": "complete", "repeat_operation": False}


def new(workspace: str | Path, project_id: str, workflow: str, task_id: str,
        mode: str = "assisted", *, apply: bool = False,
        root_files: dict[str, str] | None = None,
        template_overrides: dict[str, str] | None = None) -> dict[str, Any]:
    root = external_workspace(workspace)
    identifier(project_id)
    identifier(task_id)
    pack = load_pack(workflow)
    root_files = root_files or {}
    template_overrides = template_overrides or {}
    for relative, content in root_files.items():
        local_path(root, relative)
        if (PurePosixPath(relative).parts[0] in {"project.json", "tasks"}
                or any(part.startswith(".write-") for part in PurePosixPath(relative).parts)
                or not isinstance(content, str)):
            raise WorkflowError("invalid_project_template", "Project templates cannot replace project/task facts.")
    if (not set(template_overrides) <= set(pack["templates"])
            or any(not isinstance(content, str) for content in template_overrides.values())):
        raise WorkflowError("invalid_project_template", "Only declared task templates can receive initial inputs.")
    if mode not in MODES:
        raise WorkflowError("invalid_mode", "Unknown interaction mode.")
    if root.exists():
        raise WorkflowError("workspace_exists", "Workspace already exists; no files were overwritten.")
    result = {"project_id": project_id, "task_id": task_id, "workflow": workflow, "mode": mode,
              "workspace": str(root), "applied": apply}
    if root_files:
        result["project_files"] = sorted(root_files)
    if not apply:
        return result
    if not root.parent.is_dir():
        raise WorkflowError("missing_parent", "Create or select the workspace parent directory first.")
    temporary = Path(tempfile.mkdtemp(prefix=".agent-workflow-new-", dir=root.parent))
    try:
        task_dir = temporary / "tasks" / task_id
        task_dir.mkdir(parents=True)
        atomic_json(temporary / "project.json", {"schema_version": "1.0", "project_id": project_id})
        task = {"schema_version": "1.0", "id": task_id, "project_id": project_id, "workflow": workflow,
                "pack_digest": pack_digest(workflow), "mode": mode,
                "stage": pack["stages"][0]["id"], "next_action": "Fill the declared inputs and run status.", "decisions": {}}
        atomic_json(task_dir / "task.json", task)
        for relative, content in {**pack["templates"], **template_overrides}.items():
            destination = local_path(task_dir, relative)
            destination.parent.mkdir(parents=True, exist_ok=True)
            destination.write_text(content, encoding="utf-8", newline="\n")
        for relative, content in root_files.items():
            destination = local_path(temporary, relative)
            destination.parent.mkdir(parents=True, exist_ok=True)
            destination.write_text(content, encoding="utf-8", newline="\n")
        # mkdir is an exclusive reservation on both Windows and POSIX. POSIX rename
        # alone could replace another writer's newly-created empty directory.
        try:
            root.mkdir()
        except FileExistsError as error:
            raise WorkflowError("workspace_exists", "Workspace appeared during creation; nothing was overwritten.") from error
        try:
            for child in temporary.iterdir():
                destination = local_path(root, child.name)
                if destination.exists():
                    raise WorkflowError("workspace_creation_incomplete", "A reserved workspace was changed by another writer; preserve it and inspect before retrying.")
                child.rename(destination)
        except OSError as error:
            raise WorkflowError("workspace_creation_incomplete", "Workspace reservation succeeded but file creation was incomplete; preserve it and inspect before retrying.") from error
    finally:
        # Only this uniquely-created staging directory is ever removed.
        if temporary.exists():
            checked = safe_path(temporary)
            if checked.parent != root.parent or not checked.name.startswith(".agent-workflow-new-"):
                raise WorkflowError("unsafe_path", "The owned staging path changed; no recursive cleanup was attempted.")
            shutil.rmtree(checked)
    try:
        context(root, task_id, write=True)
        result["completion"] = {"operation": "completed", "local_record": "complete", "repeat_operation": False}
    except (WorkflowError, OSError):
        result["completion"] = {"operation": "completed", "local_record": "incomplete", "repeat_operation": False,
                                "recovery": ["context", str(root), "--task-id", task_id, "--write"]}
    return result


def advance(workspace: str | Path, task_id: str, *, apply: bool = False) -> dict[str, Any]:
    task_dir, _, task, _ = load_task(workspace, task_id)
    with task_lock(task_dir) if apply else _no_lock():
        view = task_view(workspace, task_id)
        if not view["can_advance"]:
            raise WorkflowError("transition_blocked", "No next stage or required evidence/business answers are missing; run status.")
        task = load_task(workspace, task_id)[2]
        result = {"from_stage": task["stage"], "to_stage": view["next_stage"], "applied": apply}
        if apply:
            task["stage"] = view["next_stage"]
            task["next_action"] = "Run context/status and follow the current business stage."
            result["completion"] = save_task(task_dir, task)
        return result


@contextmanager
def _no_lock():
    yield


def decision(workspace: str | Path, task_id: str, decision_id: str, answer: str, by: str,
             *, apply: bool = False) -> dict[str, Any]:
    identifier(decision_id)
    plain_text(by, maximum=100)
    task_dir, _, _, _ = load_task(workspace, task_id)
    with task_lock(task_dir) if apply else _no_lock():
        _, _, task, pack = load_task(workspace, task_id)
        stage = next(stage for stage in pack["stages"] if stage["id"] == task["stage"])
        definition = next((check for check in stage["checks"] if check["kind"] == "decision" and check["id"] == decision_id), None)
        if definition is None or answer not in definition["answers"]:
            raise WorkflowError("invalid_decision", "Only a current, defined business question with an explicit choice can be answered.")
        result = {"decision_id": decision_id, "answer": answer, "by": by, "applied": apply}
        if apply:
            task["decisions"][decision_id] = {"answer": answer, "by": by, "evidence_digest": evidence_digest(task_dir)}
            result["completion"] = save_task(task_dir, task)
        return result


def task_plan(workspace: str | Path, task_id: str, *, mode: str | None = None,
              next_action: str | None = None, apply: bool = False) -> dict[str, Any]:
    task_dir, _, task, _ = load_task(workspace, task_id)
    if mode is not None and mode not in MODES:
        raise WorkflowError("invalid_mode", "Unknown interaction mode.")
    if next_action is not None:
        plain_text(next_action)
    with task_lock(task_dir) if apply else _no_lock():
        task = load_task(workspace, task_id)[2]
        if mode is not None:
            task["mode"] = mode
        if next_action is not None:
            task["next_action"] = next_action
        result = {"task": {key: task[key] for key in ("id", "workflow", "mode", "stage", "next_action")}, "applied": apply}
        if apply:
            result["completion"] = save_task(task_dir, task)
        return result
