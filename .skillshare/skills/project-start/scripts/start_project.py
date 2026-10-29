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


class ArgumentsError(ValueError):
    pass


class Parser(argparse.ArgumentParser):
    def error(self, message: str) -> NoReturn:
        raise ArgumentsError("Invalid helper arguments; use --help.")


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


def project_marker(start: Path) -> Path | None:
    """Walk up from the working directory the way the read-only hook does.

    Agents routinely work in a subdirectory of an adopted project. Looking only
    at the current directory would lose a marker that is two levels up and send
    the operator looking for a framework path that is already recorded.
    """
    try:
        current = start.resolve()
    except (OSError, RuntimeError):
        return None
    for directory in [current, *current.parents]:
        marker = directory / ".agent-workflow.local.json"
        if marker.is_file():
            return marker
        if (directory / ".git").is_dir():
            return None
    return None


def locate(explicit: str | None) -> Path:
    if explicit:
        return verified(explicit)
    configured = os.environ.get("AGENT_WORKFLOW_FRAMEWORK")
    if configured:
        return verified(configured)
    marker = project_marker(Path.cwd())
    if marker is not None:
        return verified(read_location(marker))
    # A source checkout keeps this skill under .skillshare/skills/<name>; find the
    # framework by its own module file instead of assuming a fixed depth.
    for ancestor in Path(__file__).resolve().parents:
        if (ancestor / "agent_workflow/project_start.py").is_file():
            return verified(ancestor)
    if os.name == "nt" and os.environ.get("LOCALAPPDATA"):
        base = Path(os.environ["LOCALAPPDATA"])
    else:
        base = Path(os.environ.get("XDG_CONFIG_HOME", str(Path.home() / ".config")))
    registration = base / "agent-workflow/framework.json"
    if registration.is_file():
        return verified(read_location(registration))
    raise LocateError("Framework not located; ask once for its checkout path and use --framework.")


def fail(code: str, message: str) -> int:
    print(json.dumps({"ok": False, "error": {"code": code, "message": message}}))
    return 2


def main() -> int:
    parser = Parser()
    parser.add_argument("--framework")
    parser.add_argument("--locate", action="store_true")
    parser.add_argument("command", nargs=argparse.REMAINDER)
    try:
        options = parser.parse_args()
        if sys.version_info < (3, 11):
            return fail("python_version", "This helper requires Python >=3.11; business runtimes are independent. No project was created.")
        root = locate(options.framework)
        command = options.command
        if command[:1] == ["--"]:
            command = command[1:]
        if options.locate or not command:
            print(json.dumps({"ok": True, "framework_root": str(root)}, ensure_ascii=True))
            return 0
    except ArgumentsError:
        return fail("helper_arguments_error", "Invalid helper arguments; use --help. No project was created.")
    except (LocateError, OSError, ValueError, TypeError):
        # Do not print caller arguments or metadata, which may contain credentials.
        return fail("framework_location_error", "Local framework unavailable; check its location or metadata and specify --framework. No project was created.")
    try:
        return subprocess.run([sys.executable, "-m", "agent_workflow", *command], cwd=root, check=False).returncode
    except OSError:
        return fail("framework_invocation_error", "Could not run the located framework command. Check the tool executable and access; inspect task status before retrying an operation.")


if __name__ == "__main__":
    raise SystemExit(main())
