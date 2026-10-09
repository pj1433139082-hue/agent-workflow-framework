"""Non-overwriting optional-document completion for an existing valid task."""

import os
from pathlib import Path
import stat
import tempfile
from typing import Any

from . import engine, project_start
from .verification import verify_task


# Progress name for the tracker document, which is not one of OPTIONAL_DOCUMENTS.
TRACKER_DOCUMENT = "issue-tracker"


class DocumentError(engine.WorkflowError):
    def __init__(self, code: str, message: str, progress: dict[str, list[str]]):
        super().__init__(code, message)
        self.progress = progress


def _ordinary_document(path: Path) -> bool:
    path = engine.safe_path(path)
    try:
        info = path.lstat()
    except FileNotFoundError:
        return False
    if not stat.S_ISREG(info.st_mode):
        raise engine.WorkflowError("invalid_document_target", "A selected document target is not an ordinary file; preserve it and inspect.")
    return True


def _record(progress: dict[str, list[str]], document: str, outcome: str) -> None:
    progress["pending"].remove(document)
    progress[outcome].append(document)
    progress[outcome].sort()


def _publish(path: Path, content: str, document: str, progress: dict[str, list[str]]) -> None:
    if _ordinary_document(path):
        _record(progress, document, "preserved")
        return
    engine.safe_path(path.parent).mkdir(parents=True, exist_ok=True)
    engine.safe_path(path)
    fd, name = tempfile.mkstemp(prefix=".write-project-doc-", dir=path.parent)
    temporary = Path(name)
    owned = os.fstat(fd)
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as stream:
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())
        current = engine.safe_path(temporary).lstat()
        if not stat.S_ISREG(current.st_mode) or (current.st_dev, current.st_ino) != (owned.st_dev, owned.st_ino):
            raise engine.WorkflowError("unsafe_path", "The staged document changed; unknown content was not published.")
        engine.safe_path(path)
        try:
            # Publish a complete file exclusively: link cannot replace a target.
            # No overwrite fallback on filesystems that do not support this.
            os.link(temporary, path)
        except FileExistsError:
            if not _ordinary_document(path):
                raise engine.WorkflowError("document_target_changed", "A competing target changed; inspect before completing missing documents.")
            _record(progress, document, "preserved")
        else:
            _record(progress, document, "created")
    finally:
        remaining: os.stat_result | None
        try:
            remaining = engine.safe_path(temporary).lstat()
        except FileNotFoundError:
            remaining = None
        if remaining is not None:
            if not stat.S_ISREG(remaining.st_mode) or (remaining.st_dev, remaining.st_ino) != (owned.st_dev, owned.st_ino):
                raise engine.WorkflowError("document_cleanup_incomplete", "The staging path changed; preserve unknown content and inspect.")
            temporary.unlink()


def complete(workspace: str | Path, task_id: str, with_docs: list[str], *, apply: bool = False,
             tracker: str | None = None) -> dict[str, Any]:
    progress: dict[str, list[str]] = {"created": [], "preserved": [], "pending": []}
    try:
        selected = project_start.select_documents(with_docs)
        chosen_tracker = project_start.select_tracker(tracker)
        if not selected and not chosen_tracker:
            raise engine.WorkflowError("invalid_project_documents", "Select at least one declared optional document or issue tracker.")
        # Progress names stay the declared document names; the tracker is one more missing document.
        targets = {document: project_start.OPTIONAL_DOCUMENTS[document] for document in selected}
        template_for: dict[str, str] = {}
        if chosen_tracker:
            targets[TRACKER_DOCUMENT] = project_start.TRACKER_FILE
            template_for[project_start.TRACKER_FILE] = project_start.TRACKER_TEMPLATES[chosen_tracker]
        progress["pending"] = sorted(targets)
        verified = verify_task(workspace, task_id)
        root = verified.task_dir.parent.parent
        paths = {name: engine.local_path(root, relative) for name, relative in targets.items()}
        # Check ALL predictable conflicts before creating any document/directory.
        for name, path in paths.items():
            if _ordinary_document(path):
                _record(progress, name, "preserved")
        rendered = project_start.render_project_files(task_id, sorted(set(targets.values())), template_for)
        if apply:
            for name in progress["pending"].copy():
                _publish(paths[name], rendered[targets[name]], name, progress)
        return {"task_id": task_id, "applied": apply,
                "document_files": {document: project_start.OPTIONAL_DOCUMENTS[document] for document in selected},
                # Describes this request only; whether anything was written is in progress.
                "issue_tracker": {"selected": chosen_tracker,
                                  "file": project_start.TRACKER_FILE if chosen_tracker else None},
                "progress": progress, "scope": "optional documents only; task facts and index unchanged"}
    except engine.WorkflowError as error:
        raise DocumentError(error.code, str(error), progress) from error
    except (OSError, KeyError, TypeError, ValueError) as error:
        raise DocumentError("project_document_error", "Local document completion failed; preserve files and inspect before completing only missing documents.", progress) from error
