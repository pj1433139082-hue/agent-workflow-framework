"""Locate a local framework checkout and forward arguments without a shell."""

import argparse
import json
import os
from pathlib import Path
import subprocess
import sys
from typing import NoReturn


class LocateError(ValueError):
    pass


class Parser(argparse.ArgumentParser):
    def error(self, message: str) -> NoReturn:
        raise LocateError("Invalid helper arguments; use --help.")


def read_location(path: Path) -> str:
    if path.stat().st_size > 100_000:
        raise LocateError("Framework location metadata exceeds the size limit.")
    data = json.loads(path.read_text(encoding="utf-8-sig"))
    if not isinstance(data, dict) or not isinstance(data.get("framework_root"), str):
        raise LocateError("Framework location metadata is invalid.")
    return data["framework_root"]


def verified(path: str | Path) -> Path:
    root = Path(path).expanduser().resolve()
    if not all((root / relative).is_file() for relative in (
        "AGENTS.md", "agent_workflow/cli.py", "agent_workflow/project_start.py",
        "agent_workflow/packs/project-planning/workflow.json",
        "docs/00-入口层/03-一键启动新项目.md",
    )):
        raise LocateError("No usable local framework at the selected location; specify --framework once.")
    return root


def locate(explicit: str | None) -> Path:
    if explicit:
        return verified(explicit)
    configured = os.environ.get("AGENT_WORKFLOW_FRAMEWORK")
    if configured:
        return verified(configured)
    marker = Path.cwd() / ".agent-workflow.local.json"
    if marker.is_file():
        return verified(read_location(marker))
    parents = Path(__file__).resolve().parents
    if len(parents) > 4 and (parents[4] / "agent_workflow/project_start.py").is_file():
        return verified(parents[4])
    if os.name == "nt" and os.environ.get("LOCALAPPDATA"):
        base = Path(os.environ["LOCALAPPDATA"])
    else:
        base = Path(os.environ.get("XDG_CONFIG_HOME", str(Path.home() / ".config")))
    registration = base / "agent-workflow/framework.json"
    if registration.is_file():
        return verified(read_location(registration))
    raise LocateError("Framework not located; ask once for its checkout path and use --framework.")


def main() -> int:
    parser = Parser()
    parser.add_argument("--framework")
    parser.add_argument("--locate", action="store_true")
    parser.add_argument("command", nargs=argparse.REMAINDER)
    try:
        options = parser.parse_args()
        if sys.version_info < (3, 11):
            raise LocateError("This helper requires Python >=3.11; business runtimes are independent.")
        root = locate(options.framework)
        command = options.command
        if command[:1] == ["--"]:
            command = command[1:]
        if options.locate or not command:
            print(json.dumps({"ok": True, "framework_root": str(root)}, ensure_ascii=True))
            return 0
        return subprocess.run([sys.executable, "-m", "agent_workflow", *command], cwd=root, check=False).returncode
    except (LocateError, OSError, ValueError, TypeError):
        # Do not print caller arguments or metadata, which may contain credentials.
        print(json.dumps({"ok": False, "error": {"code": "framework_location_error",
                                                   "message": "Local framework unavailable or arguments invalid; specify its checkout with --framework. No project was created."}}))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
