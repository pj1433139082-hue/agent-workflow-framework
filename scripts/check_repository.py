"""Lightweight publication guard for framework files; not a DLP guarantee."""

import json
from pathlib import Path
import re
import subprocess

ROOT = Path(__file__).resolve().parent.parent
ALLOWED = {"AGENTS.md", "CONTEXT.md", "README.md", "LICENSE", "CONTRIBUTING.md", "CODE_OF_CONDUCT.md", "SECURITY.md",
           ".gitignore", ".gitattributes", "pyproject.toml",
           "agent_workflow", "scripts", "tests", "docs", "templates", ".github", ".codex", ".skillshare"}
FORBIDDEN_SUFFIXES = {".zip", ".pkl", ".pickle", ".parquet", ".csv", ".xlsx", ".xls", ".onnx", ".pth", ".pt", ".pem", ".key", ".ipynb"}
PATTERNS = {
    "credential": re.compile(r"gh[pousr]_[A-Za-z0-9]{24,}|sk-[A-Za-z0-9]{24,}|-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----"),
    "specific-model": re.compile(r"MLModel-\d{3,}"),
    "plant-point": re.compile(r"[A-Z]{2,}\d{3,}-BE_[A-Z0-9_]+"),
}


def main() -> int:
    result = subprocess.run(["git", "ls-files", "-z", "--cached", "--others", "--exclude-standard"],
                            cwd=ROOT, check=True, capture_output=True)
    names = sorted({name.decode("utf-8") for name in result.stdout.split(b"\0") if name})
    issues = []
    for name in names:
        path = ROOT / name
        if Path(name).parts[0] not in ALLOWED or path.suffix.lower() in FORBIDDEN_SUFFIXES or path.name.startswith(".env"):
            issues.append({"file": name, "code": "unexpected_framework_asset"})
            continue
        if path.is_symlink() or not path.is_file() or path.stat().st_size > 1_000_000:
            issues.append({"file": name, "code": "unsafe_or_large_file"})
            continue
        try:
            content = path.read_text(encoding="utf-8")
        except UnicodeError:
            issues.append({"file": name, "code": "binary_asset"})
            continue
        for label, pattern in PATTERNS.items():
            if pattern.search(content):
                issues.append({"file": name, "code": label})
        if path.suffix == ".json":
            try:
                json.loads(content)
            except json.JSONDecodeError:
                issues.append({"file": name, "code": "invalid_json"})
    print(json.dumps({"ok": not issues, "files_checked": len(names), "issues": issues,
                      "scope": "framework filenames and obvious leaked identifiers; manual review remains required"}))
    return 1 if issues else 0


if __name__ == "__main__":
    raise SystemExit(main())
