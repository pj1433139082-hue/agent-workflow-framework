#!/bin/sh
set -eu
framework_root=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
exec python3 "$framework_root/scripts/context_hook.py" --event "${1:-SessionStart}"
