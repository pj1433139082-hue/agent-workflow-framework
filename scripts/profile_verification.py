"""Passive synthetic CLI read-work comparison; no timing or exact-count gate."""

import argparse
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile


ROOT = Path(__file__).resolve().parent.parent


def cli(runtime: Path, *args: object) -> dict:
    result = subprocess.run([sys.executable, "-m", "agent_workflow", *(str(arg) for arg in args)],
                            cwd=runtime, capture_output=True, text=True, check=False)
    if result.returncode:
        raise RuntimeError("Synthetic public CLI preparation failed.")
    return json.loads(result.stdout)


def measure(source: Path, base: Path, decisions: int) -> dict:
    runtime, workspace = base / "runtime", base / "workspace"
    shutil.copytree(source, runtime, ignore=shutil.ignore_patterns(
        ".git", "__pycache__", "*.pyc", ".mypy_cache", ".ruff_cache", ".agents"))
    pack = runtime / "agent_workflow/packs/synthetic-read-profile"
    pack.mkdir()
    checks = [{"id": f"accept-{index}", "kind": "decision", "question": "Accept synthetic evidence?",
               "recommendation": "Inspect synthetic evidence.", "answers": ["accept", "revise"],
               "required_answer": "accept"} for index in range(decisions)]
    declaration = {
        "schema_version": "1.0", "id": "synthetic-read-profile", "name": "Synthetic read workload",
        "version": "0.1.0", "description": "Only synthetic local evidence; no external operations.",
        "templates": {"payload.json": '{"synthetic":true}\n',
                      **{f"evidence-{index}.md": "Synthetic bounded evidence.\n" * 100 for index in range(8)}},
        "stages": [
            {"id": "gather", "documents": ["AGENTS.md"], "checks": [
                {"id": "synthetic-only", "kind": "json-fields", "file": "payload.json",
                 "fields": {"synthetic": {"type": "boolean", "equals": True}}}]},
            {"id": "review", "documents": ["AGENTS.md"], "checks": checks},
            {"id": "complete", "documents": ["AGENTS.md"], "checks": []},
        ],
    }
    (pack / "workflow.json").write_text(json.dumps(declaration), encoding="utf-8")
    cli(runtime, "new", workspace, "--project-id", "synthetic-profile", "--workflow",
        "synthetic-read-profile", "--task-id", "sample", "--apply")
    cli(runtime, "advance", workspace, "--task-id", "sample", "--apply")
    for index in range(decisions):
        cli(runtime, "decision", workspace, "--task-id", "sample", "--decision-id",
            f"accept-{index}", "--answer", "accept", "--by", "synthetic-observer", "--apply")
    results = {}
    for command in ("status", "context"):
        report, config = base / f"{command}.reads.json", base / f"{command}.config.json"
        config.write_text(json.dumps({"watch_root": str(workspace), "watch_roots": [str(workspace), str(pack)],
                                      "report": str(report)}), encoding="utf-8")
        proc = subprocess.run([sys.executable, str(ROOT / "tests/support/observe_cli.py"),
                               "--config", str(config), "--", command, str(workspace), "--task-id", "sample"],
                              cwd=runtime, capture_output=True, text=True, check=False)
        if proc.returncode or not json.loads(proc.stdout).get("evidence_valid"):
            raise RuntimeError("Observed public CLI did not return a valid synthetic view.")
        reads = json.loads(report.read_text(encoding="utf-8"))["reads"]
        task = workspace / "tasks/sample"
        results[command] = {
            "task_evidence_read_opens": sum(count for name, count in reads.items()
                                            if Path(name).is_relative_to(task)
                                            and Path(name).name not in {"task.json", "workflow-state.json"}),
            "identity_read_opens": sum(count for name, count in reads.items()
                                       if Path(name).name in {"project.json", "task.json"}),
            "business_pack_read_opens": sum(count for name, count in reads.items()
                                            if Path(name).is_relative_to(pack)),
        }
    return {"decisions": decisions, "evidence_files": 9, "commands": results}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--baseline-root", type=Path)
    args = parser.parse_args()
    roots = {"current": ROOT}
    if args.baseline_root:
        roots = {"baseline": args.baseline_root.resolve(), **roots}
    with tempfile.TemporaryDirectory(prefix="agent-workflow-read-profile-") as directory:
        base = Path(directory)
        measurements = {label: [measure(source, base / f"{label}-{count}", count) for count in (1, 6)]
                        for label, source in roots.items()}
    print(json.dumps({"ok": True, "measurements": measurements,
                      "scope": "Passive CPython open observations on public CLI synthetic loads, not elapsed-time benchmarks.",
                      "interpretation": "Current reads include capture and necessary content stability review; compare workload trends, not exact counts or production speed."}))


if __name__ == "__main__":
    main()
