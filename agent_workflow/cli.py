"""Public JSON CLI. All mutations are explicit and local to one workspace."""

import argparse
import json
import sys
from typing import Any, NoReturn

from . import __version__, engine, project_documents, project_start


class _ArgumentParser(argparse.ArgumentParser):
    def error(self, message: str) -> NoReturn:
        # Do not echo raw arguments, which may accidentally contain credentials.
        raise engine.WorkflowError("invalid_arguments", "Invalid arguments; use --help for the public command contract.")


def main(argv: list[str] | None = None) -> int:
    parser = _ArgumentParser(prog="agent-workflow")
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("doctor")
    commands.add_parser("packs")
    new = commands.add_parser("new")
    new.add_argument("workspace")
    new.add_argument("--project-id", required=True)
    new.add_argument("--workflow", required=True)
    new.add_argument("--task-id", required=True)
    new.add_argument("--mode", default="assisted", choices=sorted(engine.MODES))
    new.add_argument("--apply", action="store_true")
    start = commands.add_parser("start")
    start.add_argument("workspace")
    start.add_argument("--project-id", required=True)
    start.add_argument("--name", required=True)
    start.add_argument("--brief", default="")
    start.add_argument("--task-id", default="kickoff")
    start.add_argument("--mode", default="assisted", choices=sorted(engine.MODES))
    start.add_argument("--with-docs", action="append", choices=sorted(project_start.OPTIONAL_DOCUMENTS), default=[])
    start.add_argument("--apply", action="store_true")
    documents = commands.add_parser("project-docs", help="Preview or create only missing optional project documents.",
                                    description="Existing valid workspace/task only. Default is read-only; existing ordinary files are never overwritten. Task facts and index remain unchanged.")
    documents.add_argument("workspace", help="Existing framework-created workspace outside this checkout.")
    documents.add_argument("--task-id", required=True, help="Explicit existing task ID, not a path.")
    documents.add_argument("--with-docs", action="append", required=True, choices=sorted(project_start.OPTIONAL_DOCUMENTS),
                           help="Repeat to select documents; duplicate selections are deduplicated.")
    documents.add_argument("--apply", action="store_true", help="Create only missing documents; report created/preserved/pending progress.")
    for name in ("status", "context", "advance", "decision", "task-plan"):
        command = commands.add_parser(name)
        command.add_argument("workspace")
        command.add_argument("--task-id", required=True)
        if name == "context":
            group = command.add_mutually_exclusive_group()
            group.add_argument("--write", action="store_true")
            group.add_argument("--check", action="store_true")
        if name in {"advance", "decision", "task-plan"}:
            command.add_argument("--apply", action="store_true")
        if name == "decision":
            command.add_argument("--decision-id", required=True)
            command.add_argument("--answer", required=True)
            command.add_argument("--by", required=True)
        if name == "task-plan":
            command.add_argument("--mode", choices=sorted(engine.MODES))
            command.add_argument("--next-action")
    try:
        args = vars(parser.parse_args(argv))
        name = args.pop("command")
        if name == "doctor":
            if sys.version_info < (3, 11):
                raise engine.WorkflowError("python_version", "The collaboration tool requires Python >=3.11; business runtimes are independent.")
            result = {"version": __version__, "python": sys.version.split()[0], "framework_root": str(engine.ROOT),
                      "business_runtime_constraint": None, "packs": engine.packs(), "external_integrations": []}
        elif name == "packs":
            result = {"packs": engine.packs()}
        elif name == "status":
            result = engine.task_view(**args)
        elif name == "start":
            result = project_start.start(**args)
        elif name == "project-docs":
            result = project_documents.complete(**args)
        else:
            result = getattr(engine, name.replace("-", "_"))(**args)
        print(json.dumps({"ok": True, **result}, ensure_ascii=True, allow_nan=False))
        return 0
    except engine.WorkflowError as error:
        failure: dict[str, Any] = {"ok": False, "error": {"code": error.code, "message": str(error)}}
        if error.completion is not None:
            failure["completion"] = error.completion
        if isinstance(error, project_documents.DocumentError):
            failure["progress"] = error.progress
        print(json.dumps(failure, ensure_ascii=True))
        return 2
    except (OSError, KeyError, TypeError, ValueError):
        print(json.dumps({"ok": False, "error": {"code": "local_input_error", "message": "A local path, fact or schema is unavailable/invalid; no external operation was performed."}}))
        return 2
