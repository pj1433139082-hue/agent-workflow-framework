"""One command-local capture, shared checks/digests, and bounded stability review.

This is not an OS multi-file snapshot or a cache across CLI calls. Hashes and
directory membership are checked again before returning a view. Changes after
that review, or changes restored between observations, cannot be ruled out.
"""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
from pathlib import Path
from typing import Any

from . import engine


@dataclass(frozen=True)
class _CapturedFile:
    digest: str
    # Large evidence is hashed as a stream; only bounded text is retained.
    content: bytes | None


class VerificationBatch:
    def __init__(self) -> None:
        self._files: dict[Path, _CapturedFile] = {}
        self._missing: set[Path] = set()
        self._json: dict[Path, dict[str, Any]] = {}
        self._file_types: dict[Path, bool] = {}
        self._manifests: dict[tuple[Path, bool], dict[str, str]] = {}

    def _capture(self, path: Path) -> _CapturedFile:
        path = engine.safe_path(path)
        if path in self._missing:
            raise FileNotFoundError("A captured local file is unavailable.")
        if path not in self._files:
            hasher = hashlib.sha256()
            content: bytearray | None = bytearray()
            try:
                with path.open("rb") as stream:
                    for block in iter(lambda: stream.read(1024 * 1024), b""):
                        hasher.update(block)
                        if content is not None:
                            if len(content) + len(block) > 1_000_000:
                                content = None
                            else:
                                content.extend(block)
            except FileNotFoundError:
                self._missing.add(path)
                raise
            self._files[path] = _CapturedFile(hasher.hexdigest(), bytes(content) if content is not None else None)
        return self._files[path]

    def digest(self, path: Path) -> str:
        return self._capture(path).digest

    def text(self, path: Path) -> str:
        content = self._capture(path).content
        if content is None:
            raise engine.WorkflowError("invalid_text", "Evidence file exceeds size limit.")
        # Match Path.read_text's universal-newline semantics for literal checks,
        # while the source/decision hash remains bound to original file bytes.
        return content.decode("utf-8-sig").replace("\r\n", "\n").replace("\r", "\n")

    def json(self, path: Path) -> dict[str, Any]:
        path = engine.safe_path(path)
        if path not in self._json:
            content = self._capture(path).content
            if content is None:
                raise engine.WorkflowError("invalid_json", "JSON input exceeds the size limit.")
            self._json[path] = engine.decode_json(content)
        return self._json[path]

    def is_file(self, path: Path) -> bool:
        path = engine.safe_path(path)
        if path not in self._file_types:
            self._file_types[path] = path.is_file()
        return self._file_types[path]

    def _members(self, directory: Path, *, pack: bool) -> list[Path]:
        members = []
        for path in sorted(directory.rglob("*")):
            engine.safe_path(path)
            relative = path.relative_to(directory)
            included = ("__pycache__" not in path.parts and path.suffix != ".pyc" if pack else
                        relative.as_posix() not in {"task.json", "workflow-state.json"}
                        and not any(part.startswith(".write-") for part in relative.parts))
            if path.is_file() and included:
                members.append(path)
        return members

    def manifest(self, directory: Path, *, pack: bool) -> dict[str, str]:
        directory = engine.safe_path(directory)
        key = (directory, pack)
        if key not in self._manifests:
            # Retain membership before reading: an addition/removal during capture
            # must also invalidate a batch, including a captured read failure.
            files = {path.relative_to(directory).as_posix(): "" for path in self._members(directory, pack=pack)}
            self._manifests[key] = files
            for relative in files:
                files[relative] = self.digest(directory / relative)
        return self._manifests[key]

    def unchanged(self) -> bool:
        def same_members() -> bool:
            return all(list(files) == [path.relative_to(directory).as_posix()
                                      for path in self._members(directory, pack=pack)]
                       for (directory, pack), files in self._manifests.items())

        if not same_members():
            return False
        for path, captured in self._files.items():
            try:
                if engine.digest(path) != captured.digest:
                    return False
            except OSError:
                return False
        if any(engine.safe_path(path).exists() for path in self._missing):
            return False
        if any(engine.safe_path(path).is_file() != expected for path, expected in self._file_types.items()):
            return False
        return same_members()


@dataclass(frozen=True)
class VerifiedTask:
    task_dir: Path
    project: dict[str, Any]
    task: dict[str, Any]
    pack: dict[str, Any]
    evidence_digest: str
    view: dict[str, Any]


def verify_task(workspace: str | Path, task_id: str) -> VerifiedTask:
    # Retry only a newly observed material change, never a business operation.
    for _ in range(3):
        batch = VerificationBatch()
        failure: engine.WorkflowError | OSError | None = None
        verified = None
        try:
            task_dir, project, task, pack = engine.load_task(workspace, task_id, _batch=batch)
            evidence = engine.evidence(task_dir, _batch=batch)
            current_digest = hashlib.sha256(engine.encode(evidence).encode("utf-8")).hexdigest()
            view = engine._verified_view(task_dir, project, task, pack, batch, evidence, current_digest)
            verified = VerifiedTask(task_dir, project, task, pack, current_digest, view)
        except (engine.WorkflowError, OSError) as error:
            failure = error
        if batch.unchanged():
            if failure is not None:
                raise failure
            assert verified is not None
            return verified
    raise engine.WorkflowError("materials_changed", "Local materials changed during verification; no coherent view was returned. Retry the read after editing stops.")
