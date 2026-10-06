"""One lock domain for existing-task changes and generated-index repair.

Facts and the index are separate files, not a cross-file transaction. A receipt
tracks the fact commit before derived work or lock cleanup can fail.
"""

from __future__ import annotations

from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
import stat
from typing import Any

from . import engine
from .verification import VerifiedTask, verify_task


# Match the public CLI's sanitized local-input errors at both commit phases.
_LOCAL_ERRORS = (OSError, KeyError, TypeError, ValueError)


@dataclass
class _LockStatus:
    cleanup_incomplete: bool = False


@contextmanager
def _task_lock(task_dir: Path) -> Iterator[_LockStatus]:
    path = engine.safe_path(task_dir / ".task-write-lock")
    try:
        path.mkdir()
    except FileExistsError as error:
        raise engine.WorkflowError("task_busy", "Another task write is in progress; do not replay an uncertain operation.") from error
    owned = path.lstat()
    status = _LockStatus()
    try:
        yield status
    finally:
        try:
            current = engine.safe_path(path).lstat()
            if not stat.S_ISDIR(current.st_mode) or (current.st_dev, current.st_ino) != (owned.st_dev, owned.st_ino):
                raise engine.WorkflowError("lock_changed", "The task lock changed; inspect without deleting unknown content.")
            path.rmdir()  # Empty, owned directory only; never recursive cleanup.
        except (OSError, engine.WorkflowError):
            status.cleanup_incomplete = True


def _task_directory(workspace: str | Path, task_id: str) -> Path:
    # Locate only. Facts and business checks must be captured AFTER admission.
    return engine.local_path(engine.external_workspace(workspace), f"tasks/{engine.identifier(task_id)}")


def _receipt(task_dir: Path, task_id: str, *, completed: bool, indexed: bool = False) -> dict[str, Any]:
    result: dict[str, Any] = {
        "operation": "completed" if completed else "not_completed",
        "local_record": "complete" if indexed else "incomplete" if completed else "unchanged",
        "repeat_operation": False,
    }
    if completed and not indexed:
        result["recovery"] = ["context", str(task_dir.parent.parent), "--task-id", task_id, "--write"]
    return result


def _report_cleanup(completion: dict[str, Any], status: _LockStatus | None, task_dir: Path, task_id: str) -> None:
    if status is not None and status.cleanup_incomplete:
        completion.update(lock_cleanup="incomplete", lock_inspection_required=True,
                          next_action=["status", str(task_dir.parent.parent), "--task-id", task_id])
        if completion["operation"] == "completed":
            completion["local_record"] = "incomplete"
            completion["recovery"] = ["context", str(task_dir.parent.parent), "--task-id", task_id, "--write"]


def _report_file_cleanup(completion: dict[str, Any], task_dir: Path, task_id: str) -> None:
    completion.update(file_cleanup="incomplete", file_inspection_required=True, local_record="incomplete",
                      recovery=["context", str(task_dir.parent.parent), "--task-id", task_id, "--write"])


def _uncommitted(error: Exception, task_dir: Path, task_id: str,
                 status: _LockStatus | None) -> engine.WorkflowError:
    completion = _receipt(task_dir, task_id, completed=False)
    _report_cleanup(completion, status, task_dir, task_id)
    if isinstance(error, engine.WorkflowError):
        return engine.WorkflowError(error.code, str(error), completion=completion)
    return engine.WorkflowError("local_write_error", "The local write did not commit; inspect current facts before retrying.",
                                completion=completion)


def change_task(workspace: str | Path, task_id: str,
                prepare: Callable[[VerifiedTask], tuple[dict[str, Any], dict[str, Any]]],
                *, apply: bool) -> dict[str, Any]:
    if not apply:
        result, _ = prepare(verify_task(workspace, task_id))
        return {**result, "applied": False}
    task_dir = _task_directory(workspace, task_id)
    status = None
    try:
        with _task_lock(task_dir) as status:
            verified = verify_task(workspace, task_id)
            result, changes = prepare(verified)
            cleanup_complete = engine.atomic_json(task_dir / "task.json", {**verified.task, **changes})
            completion = _receipt(task_dir, task_id, completed=True)
            try:
                # Fresh batch: the new task digest cannot come from admission.
                indexed = engine._context_view(verify_task(workspace, task_id), write=True)
                completion["local_record"] = "complete"
                completion.pop("recovery", None)
                cleanup_complete = cleanup_complete and "file_cleanup" not in indexed
            except _LOCAL_ERRORS:
                pass  # Facts committed. Only the generated record needs repair.
            if not cleanup_complete:
                _report_file_cleanup(completion, task_dir, task_id)
    except _LOCAL_ERRORS as error:
        raise _uncommitted(error, task_dir, task_id, status) from error
    _report_cleanup(completion, status, task_dir, task_id)
    return {**result, "applied": True, "completion": completion}


def repair_index(workspace: str | Path, task_id: str) -> dict[str, Any]:
    task_dir = _task_directory(workspace, task_id)
    status = None
    try:
        with _task_lock(task_dir) as status:
            result = engine._context_view(verify_task(workspace, task_id), write=True)
            completion = _receipt(task_dir, task_id, completed=True, indexed=True)
            if "file_cleanup" in result:
                _report_file_cleanup(completion, task_dir, task_id)
    except _LOCAL_ERRORS as error:
        raise _uncommitted(error, task_dir, task_id, status) from error
    _report_cleanup(completion, status, task_dir, task_id)
    return {**result, "completion": completion}
