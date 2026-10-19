#!/usr/bin/env python3
"""Print which repository-relative paths (JSON list on stdin) Graphify's ignore rules exclude.

Uses Graphify's own predicate, so .graphifyignore, .gitignore, skip files, and noise
directories are judged exactly as `detect()` judges them. Exits non-zero when the
Graphify runtime is unavailable; callers then filter nothing.
"""
import importlib.util
import json
import os
from pathlib import Path
import shutil
import sys


def ensure_graphify_runtime():
    """Re-exec with the Graphify Python that workflow.py resolved on a trusted PATH.

    The path comes only from GRAPHIFY_TOOL_PYTHON (set by workflow.py after checking that it is
    outside the repository); nothing is searched for on PATH here, so a repository file is never run.
    """
    if importlib.util.find_spec("graphify") is not None:
        return
    python = os.environ.get("GRAPHIFY_TOOL_PYTHON")
    project = os.path.realpath(sys.argv[1]) if len(sys.argv) > 1 else os.getcwd()
    real = os.path.realpath(python) if python else ""
    inside = real == project or real.startswith(project.rstrip(os.sep) + os.sep)
    if (python and os.path.isabs(python) and os.path.isfile(python) and not inside
            and os.environ.get("GRAPHIFY_TOOL_REEXEC") != "1"):
        os.environ["GRAPHIFY_TOOL_REEXEC"] = "1"
        os.execv(python, [python, str(Path(__file__).resolve()), *sys.argv[1:]])
    raise SystemExit("Graphify runtime not found")


ensure_graphify_runtime()

from graphify.detect import ignored_predicate


def main():
    root = Path(sys.argv[1]).resolve()
    paths = json.load(sys.stdin)
    ignored = ignored_predicate(root)
    print(json.dumps(sorted(path for path in paths if ignored(root / path))))


if __name__ == "__main__":
    main()
