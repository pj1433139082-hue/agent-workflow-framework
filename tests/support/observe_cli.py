"""Test-side public CLI runner: passive observation and file-I/O coordination.

No framework imports, private function patches, or production test switches.
The audit callback runs before an OS open, so a parent can change real fixtures
at a known point rather than relying on sleeps to win a race.
"""

import argparse
import json
import os
from pathlib import Path
import runpy
import sys
import time


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", required=True)
    parser.add_argument("command", nargs=argparse.REMAINDER)
    args = parser.parse_args()
    config = json.loads(Path(args.config).read_text(encoding="utf-8"))
    roots = [Path(root).absolute() for root in config.get("watch_roots", [config["watch_root"]])]
    pause = Path(config["pause_path"]).absolute() if config.get("pause_path") else None
    reads: dict[str, int] = {}
    paused = 0
    in_callback = False

    pause_event = config.get("pause_event", "open")

    def observe(event: str, values: tuple) -> None:
        nonlocal paused, in_callback
        if in_callback or event not in {"open", pause_event}:
            return
        target = config.get("pause_target", 0) if event == pause_event else 0
        if not isinstance(values[target], (str, bytes)):
            return
        if event == "open":
            name, mode, flags = values
            if isinstance(mode, str):
                reading = "r" in mode or "+" in mode
            else:
                reading = flags & (os.O_WRONLY | os.O_RDWR) != os.O_WRONLY
            if not reading:
                return
        in_callback = True
        try:
            path = Path(os.fsdecode(values[target])).absolute()
            if event == "open" and any(path.is_relative_to(root) for root in roots):
                key = str(path)
                reads[key] = reads.get(key, 0) + 1
            matches_pause = pause == path or (
                pause is None and config.get("pause_parent")
                and path.parent == Path(config["pause_parent"]).absolute()
                and path.name.startswith(config.get("pause_name_prefix", ""))) or (
                pause is None and config.get("pause_ancestor")
                and path.parent.parent == Path(config["pause_ancestor"]).absolute()
                and path.parent.name.startswith(config.get("pause_directory_prefix", ""))
                and path.name.startswith(config.get("pause_name_prefix", "")))
            if event == pause_event and matches_pause and (not paused or config.get("pause_each", False)):
                paused += 1
                if config.get("pause_each", False):
                    signal = Path(config["signal"] + f".{paused}")
                    release = Path(config["release"] + f".{paused}")
                else:
                    signal, release = Path(config["signal"]), Path(config["release"])
                signal.write_text(str(path), encoding="utf-8")
                deadline = time.monotonic() + 20
                while not release.exists():
                    if time.monotonic() >= deadline:
                        raise TimeoutError("Test parent did not release the coordinated file read.")
                    time.sleep(0.01)
        finally:
            in_callback = False

    command = args.command[1:] if args.command[:1] == ["--"] else args.command
    sys.dont_write_bytecode = True
    sys.path.insert(0, str(Path.cwd()))
    sys.addaudithook(observe)
    try:
        if config.get("hook"):
            sys.argv = ["scripts/context_hook.py", *command]
            runpy.run_path("scripts/context_hook.py", run_name="__main__")
        else:
            sys.argv = ["agent-workflow", *command]
            runpy.run_module("agent_workflow", run_name="__main__")
    finally:
        if config.get("report"):
            Path(config["report"]).write_text(json.dumps({"reads": reads, "pauses": paused}), encoding="utf-8")


if __name__ == "__main__":
    main()
