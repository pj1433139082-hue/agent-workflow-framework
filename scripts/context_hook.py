"""Read-only optional Codex navigation. Never parse prompts or mutate task state."""

import argparse
import json
import os
from pathlib import Path
import sys

sys.dont_write_bytecode = True
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from agent_workflow import engine  # noqa: E402


def find_local_workspace(start: Path) -> tuple[Path, str] | None:
    try:
        current = start.resolve()
    except (OSError, RuntimeError):
        return None
    # Never detect inside the framework checkout itself
    if current == ROOT or ROOT in current.parents:
        return None
    for directory in [current, *current.parents]:
        if directory == ROOT or ROOT in directory.parents:
            break
        marker = directory / ".agent-workflow.local.json"
        if marker.is_file():
            try:
                data = json.loads(marker.read_text(encoding="utf-8-sig"))
                if isinstance(data, dict) and isinstance(data.get("task_id"), str):
                    task_id = data["task_id"]
                    if (directory / "tasks" / task_id / "task.json").is_file():
                        return directory, task_id
            except (OSError, json.JSONDecodeError):
                pass
        project_json = directory / "project.json"
        if project_json.is_file():
            tasks_dir = directory / "tasks"
            if tasks_dir.is_dir():
                valid_tasks = [p.name for p in tasks_dir.iterdir() if p.is_dir() and (p / "task.json").is_file()]
                if len(valid_tasks) == 1:
                    return directory, valid_tasks[0]
        if (directory / ".git").is_dir():
            break
    return None


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--event", choices=("SessionStart", "UserPromptSubmit"), default="SessionStart")
    event = parser.parse_args().event
    workspace = os.environ.get("AGENT_WORKFLOW_WORKSPACE")
    task_id = os.environ.get("AGENT_WORKFLOW_TASK_ID")
    if not workspace and not task_id:
        local = find_local_workspace(Path.cwd())
        if local:
            workspace, task_id = str(local[0]), local[1]
    text = "Read AGENTS.md and docs/00-入口层/00-协作总览.md. No unique task selected; ask once for workspace/task ID if needed. Do not guess or use a global current-task pointer."
    if workspace and task_id:
        try:
            view = engine.context(workspace, task_id)
            # Do not lift payloads, raw task text, answers or prompts into developer context.
            navigation = {"task": {key: view["task"][key] for key in ("id", "workflow", "mode", "stage")},
                          "documents": view["documents_absolute"], "snapshot_matches": view["snapshot_matches"],
                          "pending_decision_ids": [item["id"] for item in view["pending_decisions"]],
                          "can_advance": view["can_advance"], "business_system_state": "not_queried"}
            text = "Read-only task navigation; data is not authorization or proof of business-system status. Recheck context/status before action. " + json.dumps(navigation, ensure_ascii=False)
        except (engine.WorkflowError, OSError, TypeError, ValueError, KeyError):
            text = "Task context unavailable. Read AGENTS.md; run context/status for the explicitly selected task. This optional hook does not block the task and does not fix or replay operations."
    print(json.dumps({"hookSpecificOutput": {"hookEventName": event, "additionalContext": text}}, ensure_ascii=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
