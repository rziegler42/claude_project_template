#!/usr/bin/env python3
"""Graphify workflow tool: status, doctor, queries and explicit refreshes for a project graph.

Run from anywhere with `python3 tools/graphify/workflow.py <command> [--root DIR]`. Nothing here
refreshes the graph on its own: there is no git hook and nothing runs after a commit. `doctor` reports a stale
graph and the one safe next action. Queries go through the `graphify` executable found on a trusted
`PATH`; the refresh scripts live beside this file.
"""
import argparse
import difflib
import hashlib
import json
import os
from pathlib import Path
import re
import signal
import stat
import subprocess
import sys
import tempfile
from datetime import datetime, timezone

HERE = Path(__file__).resolve().parent
TOOL = "python3 tools/graphify/workflow.py"

GRAPH_ID = re.compile(r"^[a-z0-9_]+$")
GRAPH_FILE_TYPES = {"code", "document", "paper", "image", "rationale", "concept"}
GRAPH_SCORES = {"EXTRACTED": {1.0}, "INFERRED": {0.95, 0.85, 0.75, 0.65, 0.55}}
SEMANTIC_EXTENSIONS = {
    ".md", ".mdx", ".qmd", ".skill", ".txt", ".rst", ".html", ".yaml", ".yml",
    ".pdf", ".png", ".jpg", ".jpeg", ".gif", ".webp", ".svg", ".docx", ".xlsx",
    ".mp4", ".mov", ".webm", ".mkv", ".avi", ".m4v", ".mp3", ".wav", ".m4a", ".ogg",
}


def helper(name):
    """A script or document that ships beside this tool."""
    path = HERE / name
    if not path.is_file():
        raise RuntimeError(f"Graphify tool file missing: {path}")
    return path


READ_LIMIT = 64 * 1024 * 1024
MAX_SOURCE_BYTES = 256 * 1024 * 1024
MAX_MANIFEST_CHUNKS = 10000
MAX_TOTAL_HASH_BYTES = 1024 * 1024 * 1024
OUTPUT_LIMIT = 1024 * 1024
HEX64 = re.compile(r"[0-9a-f]{64}")
MANIFEST_KEYS = {"graphify_version", "project_root", "spec", "contract", "chunks"}
CHUNK_KEYS = {"number", "total", "files", "sources", "size_bytes", "output", "deep"}
SOURCE_KEYS = {"source_file", "size_bytes", "sha256"}
# Repository settings shaped like "a program or command git may run" (the owner's global helper
# refuses the same shapes before a commit). Names are reported, never values.
EXEC_KEY = re.compile(
    r".*\.(program|command|driver|cmd|clean|smudge|process|textconv|external|defaultkeycommand|helper)"
    r"|core\.(hookspath|fsmonitor|sshcommand|gitproxy|askpass)|diff\.external|include\.path|includeif\..*\.path")
CHUNK_OUTPUT = re.compile(r"graphify-out/\.graphify_chunk_[0-9]+\.json")
CONTROL = re.compile("[\x00-\x08\x0b-\x1f\x7f-\x9f\u200b-\u200f\u2028-\u202e\u2060-\u2069\u061c"
                     "\ufeff\ufff9-\ufffb\U000e0000-\U000e007f]")
GIT_SAFE = ["-c", "core.fsmonitor=false", "-c", "core.untrackedCache=false", "-c", "core.pager=cat",
            "-c", "core.hooksPath=" + os.devnull]
GIT_KEEP = ("GIT_CONFIG_GLOBAL", "GIT_CONFIG_SYSTEM", "GIT_CONFIG_NOSYSTEM")


def emit(status, **details):
    print(json.dumps({"status": status, **details}))


def clean(text):
    """Replace control, bidirectional and line-separator characters other than newline and tab."""
    return CONTROL.sub("?", text)


def read_json(path, limit=READ_LIMIT):
    """JSON from a regular, non-symlink file of bounded size; anything else is a ValueError."""
    path = Path(path)
    try:
        info = os.lstat(path)
        if not stat.S_ISREG(info.st_mode):
            raise ValueError(f"{path.name} is not a regular file")
        if info.st_size > limit:
            raise ValueError(f"{path.name} is larger than {limit} bytes")
        fd = os.open(path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_NONBLOCK", 0))
        with os.fdopen(fd, "rb") as stream:
            data = stream.read(limit + 1)
        if len(data) > limit:
            raise ValueError(f"{path.name} is larger than {limit} bytes")
        return json.loads(data.decode("utf-8"))
    except json.JSONDecodeError as exc:
        raise ValueError(f"invalid JSON in {path.name} at line {exc.lineno}, column {exc.colno}: {exc.msg}") from exc
    except (OSError, UnicodeDecodeError, RecursionError, MemoryError) as exc:
        raise ValueError(f"cannot read {path.name}: {exc.__class__.__name__}") from exc


def plain_argument(value, what):
    """User text goes to the vendor executable as one argument; it must not look like an option."""
    if not isinstance(value, str) or not value or value.startswith("-") or "\0" in value:
        raise ValueError(f"{what} must not start with '-' (and must not be empty)")
    return value


def is_inside(path, boundary):
    """True when `path` is `boundary` or below it, robust to symlinks and case."""
    try:
        current = os.path.realpath(path)
        while True:
            if os.path.samefile(current, boundary):
                return True
            parent = os.path.dirname(current)
            if parent == current:
                return False
            current = parent
    except OSError:
        return False


def repository_boundary(start):
    """The nearest ancestor of `start` holding a .git entry (without running git)."""
    current = os.path.realpath(start)
    while True:
        if os.path.lexists(os.path.join(current, ".git")):
            return current
        parent = os.path.dirname(current)
        if parent == current:
            return os.path.realpath(start)
        current = parent


def trusted_path_entries(boundary):
    """PATH entries that are absolute and outside the repository (never "", ".", or relative)."""
    entries = []
    for entry in os.environ.get("PATH", "").split(os.pathsep):
        if entry and os.path.isabs(entry) and not is_inside(entry, boundary):
            entries.append(entry)
    return entries


def trusted_which(name, boundary):
    for entry in trusted_path_entries(boundary):
        candidate = os.path.join(entry, name)
        if (os.path.isfile(candidate) and os.access(candidate, os.X_OK)
                and not is_inside(candidate, boundary)):
            return candidate
    return None


def run(argv, cwd, check=True, input_text=None, timeout=None, env_extra=None):
    boundary = repository_boundary(cwd)
    env = {k: v for k, v in os.environ.items()
           if (not k.startswith("GIT_") or k in GIT_KEEP) and not k.startswith("GRAPHIFY_TOOL_")}
    entries = trusted_path_entries(boundary) or ["/usr/bin", "/bin"]
    env["PATH"] = os.pathsep.join(entries)
    env.update(env_extra or {})
    if argv and argv[0] == "git":
        # A repository can rewrite objects with refs/replace; never let it do that to a commit.
        env["GIT_NO_REPLACE_OBJECTS"] = "1"
        env["GIT_OPTIONAL_LOCKS"] = "0"
        found = trusted_which("git", boundary)
        if found is None:
            raise RuntimeError("git was not found in an absolute PATH entry outside the repository")
        # A repository's own config must not make a git subprocess run code.
        argv = [found, *GIT_SAFE, *argv[1:]]
    if timeout is None:
        result = subprocess.run(argv, cwd=cwd, text=True, capture_output=True, check=False, env=env,
                                input=input_text)
    else:
        result = run_bounded(argv, cwd, env, input_text, timeout)
    if check and result.returncode:
        detail = (result.stderr or result.stdout or "command failed").strip()[-1000:]
        raise RuntimeError(f"{argv[0]} failed ({result.returncode}): {detail}")
    return result


def run_bounded(argv, cwd, env, input_text, timeout):
    """Run in its own session and kill the whole group on timeout, so a grandchild cannot hold the pipes."""
    process = subprocess.Popen(argv, cwd=cwd, text=True, env=env, start_new_session=True,
                               stdin=subprocess.PIPE if input_text is not None else None,
                               stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    try:
        out, err = process.communicate(input_text, timeout=timeout)
    except BaseException:  # a timeout, Ctrl-C or any error: never leave the group running
        try:
            os.killpg(process.pid, signal.SIGKILL)
        except (OSError, AttributeError):
            process.kill()
        try:
            process.communicate(timeout=5)
        except (subprocess.TimeoutExpired, OSError):
            pass
        raise
    return subprocess.CompletedProcess(argv, process.returncode, out, err)


def runtime_env(root):
    """Where the helper scripts may find Graphify's Python: beside a trusted `graphify`, never in the repository."""
    boundary = repository_boundary(root)
    executable = trusted_which("graphify", boundary)
    if executable:
        python = Path(executable).resolve().parent / "python"
        if python.is_file() and not is_inside(python, boundary):
            return {"GRAPHIFY_TOOL_PYTHON": str(python)}
    return {}


def repo_program_findings(root):
    """Names (never values) of repository-controlled settings that make git run a program."""
    result = run(["git", "config", "--local", "--list", "-z"], root, check=False)
    if result.returncode:
        return ["config:unreadable"]
    found = []
    for entry in result.stdout.split("\0"):
        key = entry.split("\n", 1)[0].lower()
        if key and EXEC_KEY.fullmatch(key) and key not in found:
            found.append(key)
    return sorted(found)


def refuse_repo_programs(root, allowed):
    findings = repo_program_findings(root)
    if findings and not allowed:
        raise RuntimeError(
            "this repository's own git config defines settings that make git run programs ("
            + ", ".join(clean(name)[:80] for name in findings[:10])
            + "); review them, or pass --allow-repo-programs after reviewing")


def git_root(path):
    path = Path(path).resolve()
    result = run(["git", "rev-parse", "--show-toplevel"], path)
    top = Path(result.stdout.strip()).resolve()
    holder = Path(repository_boundary(path))
    try:
        same = os.path.samefile(top, holder)
    except OSError:
        same = False
    if not same:
        raise RuntimeError(
            "git reports a work tree that is not the repository holding its metadata "
            "(a core.worktree redirect?); refusing to act")
    marker = top / ".git"
    if marker.is_dir():
        gitdir = run(["git", "rev-parse", "--absolute-git-dir"], path).stdout.strip()
        if os.path.realpath(gitdir) != os.path.realpath(marker):
            raise RuntimeError("git is using a git directory that is not the repository's own .git "
                               "(an embedded or bare repository?); refusing to act")
    try:
        path.relative_to(top)
    except ValueError as exc:
        raise RuntimeError(
            "the working directory is outside the repository root git reports "
            "(a core.worktree redirect?); refusing to act") from exc
    return top


def head(root):
    return run(["git", "rev-parse", "HEAD"], root).stdout.strip()


def changed_paths(root, base):
    """Return paths changed between base and HEAD, or None when base cannot be resolved."""
    if not isinstance(base, str) or not re.fullmatch(r"[0-9a-f]{40}|[0-9a-f]{64}", base):
        return None
    result = run(["git", "diff", "--name-only", "-z", base, "HEAD", "--"], root, check=False)
    return {item for item in result.stdout.split("\0") if item} if result.returncode == 0 else None


def dirty_paths(root):
    result = run(["git", "status", "--porcelain=v1", "-z", "--untracked-files=all"], root, check=False)
    paths = set()
    if result.returncode == 0:
        tokens = result.stdout.split("\0")
        index = 0
        while index < len(tokens):
            item = tokens[index]
            index += 1
            if not item:
                continue
            paths.add(item[3:] if len(item) > 3 else item)
            # A rename or copy entry is followed by its original path, which has
            # no status prefix.
            if len(item) > 3 and (item[0] in "RC" or item[1] in "RC") and index < len(tokens):
                original = tokens[index]
                index += 1
                if original:
                    paths.add(original)
    return {path for path in paths if not path.startswith("graphify-out/")}


def graph_ignored_paths(root, paths):
    """Return the paths Graphify's ignore rules exclude, or none when that cannot be determined."""
    if not paths:
        return set()
    try:
        result = run([sys.executable, str(helper("ignored_paths.py")), str(root)], root,
                     check=False, input_text=json.dumps(sorted(paths)), timeout=60,
                     env_extra=runtime_env(root))
        if result.returncode != 0:
            return set()
        listed = json.loads(result.stdout.strip().splitlines()[-1])
    except (RuntimeError, OSError, ValueError, IndexError, subprocess.SubprocessError):
        return set()
    return {item for item in listed if item in paths}


def graph_status_details(root):
    require_graph_output(root)
    graph = root / "graphify-out" / "graph.json"
    if not graph.is_file():
        return {"status": "missing", "graph": str(graph)}
    refresh = root / "graphify-out" / ".workflow_refresh.json"
    if refresh.is_file():
        try:
            state = read_json(refresh)
            if isinstance(state, dict) and state.get("status") == "prepared":
                return {"status": "refresh_in_progress", "graph": str(graph)}
        except (OSError, ValueError):
            pass
    metadata = root / "graphify-out" / ".workflow_graph_state.json"
    if not metadata.is_file():
        return {"status": "present", "graph": str(graph), "warning": "freshness metadata missing"}
    try:
        state = read_json(metadata)
    except (OSError, ValueError):
        return {"status": "present", "graph": str(graph), "warning": "freshness metadata invalid"}
    if not isinstance(state, dict):
        return {"status": "present", "graph": str(graph), "warning": "freshness metadata invalid"}
    paths = dirty_paths(root)
    recorded_head = state.get("head")
    current_head = head(root)
    # Code freshness is measured from the last code refresh (head); semantic
    # freshness from the last full semantic refresh (semantic_head, falling back
    # to head for state files written before it existed). A code-only commit
    # advances head but must not hide earlier un-ingested semantic changes.
    if "semantic_head" in state:
        # A present key is used verbatim: null or a malformed value is never
        # "ingested", and must not fall back to head.
        semantic_base = state["semantic_head"]
        if not (isinstance(semantic_base, str) and re.fullmatch(r"[0-9a-f]{40}|[0-9a-f]{64}", semantic_base)):
            return {"status": "stale_semantic", "graph": str(graph), "changed": [],
                    "warning": "graph has no valid semantic baseline; run a full refresh"}
    else:
        semantic_base = recorded_head
    code_paths = set(paths)
    semantic_paths = set(paths)
    for base, target in ((recorded_head, code_paths), (semantic_base, semantic_paths)):
        if base and base != current_head:
            changed = changed_paths(root, base)
            if changed is None:
                # An unresolvable baseline is unknown freshness, never current.
                return {"status": "present", "graph": str(graph),
                        "warning": f"freshness baseline commit is not resolvable: {base}"}
            target.update(changed)
    # Files the graph never ingests (.graphifyignore, .gitignore, skip files) cannot make it stale.
    ignored = graph_ignored_paths(root, code_paths | semantic_paths)
    code_paths -= ignored
    semantic_paths -= ignored
    semantic = sorted(path for path in semantic_paths if Path(path).suffix.lower() in SEMANTIC_EXTENSIONS)
    if semantic:
        return {"status": "stale_semantic", "graph": str(graph), "changed": semantic[:20]}
    if code_paths or recorded_head != current_head:
        return {"status": "stale_code", "graph": str(graph), "changed": sorted(code_paths)[:20]}
    return {"status": "current", "graph": str(graph), "head": recorded_head,
            "generated_at": state.get("generated_at"), "graphify_version": state.get("graphify_version")}


def graph_status(root):
    details = graph_status_details(root)
    status = details.pop("status")
    emit(status, **details)


def graph_warning(root):
    details = graph_status_details(root)
    if details["status"] != "current":
        print(json.dumps({"graph_warning": details}))


def require_graph_output(root):
    out = root / "graphify-out"
    if out.is_symlink():
        raise RuntimeError("graphify-out is a symlink; refusing to read or write graph state through it")
    if out.exists() and (not out.is_dir() or out.resolve() != Path(root).resolve() / "graphify-out"):
        raise RuntimeError("graphify-out must be a real directory inside the repository")


def load_manifest(root):
    """The prepared manifest in exactly the shape prepare.py writes, or ValueError.

    A committed manifest is untrusted: its shape, contract, project, sources and counters are all checked,
    because the refresh procedure passes them to a worker that can read files.
    """
    manifest = read_json(root / "graphify-out" / ".graphify_chunks.json")
    if not isinstance(manifest, dict) or set(manifest) != MANIFEST_KEYS:
        raise ValueError("manifest has missing or unexpected keys")
    resolved_root = root.resolve()
    spec = helper("extraction-spec.md").resolve()
    version = manifest["graphify_version"]
    if not (isinstance(version, str) and 0 < len(version) <= 64 and version.isprintable()):
        raise ValueError("manifest graphify_version is not short text")
    if manifest["project_root"] != str(resolved_root):
        raise ValueError("manifest names another project; abort and prepare again")
    if manifest["spec"] != str(spec) or manifest["contract"] != spec.read_text(encoding="utf-8"):
        raise ValueError("manifest contract is not the shipped extraction-spec.md; abort and prepare again")
    chunks = manifest["chunks"]
    if not isinstance(chunks, list) or len(chunks) > MAX_MANIFEST_CHUNKS:
        raise ValueError("manifest has no usable chunk list")

    def number(value, what):
        if isinstance(value, bool) or not isinstance(value, int) or not 0 <= value < 10 ** 12:
            raise ValueError(f"manifest {what} is not a whole number")
        return value

    for chunk in chunks:
        if not isinstance(chunk, dict) or set(chunk) != CHUNK_KEYS:
            raise ValueError("manifest chunk has missing or unexpected keys")
        number(chunk["number"], "chunk number")
        number(chunk["total"], "chunk total")
        if not isinstance(chunk["deep"], bool):
            raise ValueError("manifest deep flag is not a boolean")
        if not isinstance(chunk["output"], str) or not CHUNK_OUTPUT.fullmatch(chunk["output"]):
            raise ValueError("manifest has an unsafe chunk output path")
        files, sources = chunk["files"], chunk["sources"]
        if not isinstance(files, list) or not isinstance(sources, list):
            raise ValueError("manifest chunk has malformed source lists")
        total = 0
        for item in sources:
            if not isinstance(item, dict) or set(item) != SOURCE_KEYS:
                raise ValueError("manifest source record has missing or unexpected keys")
            if not (isinstance(item["source_file"], str) and isinstance(item["sha256"], str)
                    and HEX64.fullmatch(item["sha256"])):
                raise ValueError("manifest source record is malformed")
            total += number(item["size_bytes"], "source size")
        if files != [item["source_file"] for item in sources] or number(chunk["size_bytes"], "chunk size") != total:
            raise ValueError("manifest chunk files, sources and sizes disagree")
        for name in files:
            source = Path(name)
            if not source.is_absolute() or source.is_symlink():
                raise ValueError(f"manifest source is outside the project: {clean(name[:200])}")
            resolved = source.resolve()
            if resolved_root not in resolved.parents or resolved.relative_to(resolved_root).parts[0] in (
                    ".git", "graphify-out"):
                raise ValueError(f"manifest source is outside the project: {clean(name[:200])}")
    return manifest


def graph_prepare(root, deep=False):
    require_graph_output(root)
    refresh = root / "graphify-out" / ".workflow_refresh.json"
    if refresh.is_file():
        try:
            in_progress = read_json(refresh).get("status") == "prepared"
        except (OSError, ValueError):
            in_progress = True
        if in_progress:
            # A second prepare would overwrite the manifest and delete chunks that
            # workers already wrote.
            raise RuntimeError(
                "a prepared refresh is already in progress; run doctor and resume or "
                "finalize it, or cancel it with abort --confirm (refused once chunks exist)")
    spec = helper("extraction-spec.md").resolve()
    command = [sys.executable, str(helper("prepare.py")), str(root), "--spec", str(spec)]
    if deep:
        command.append("--deep")
    result = run(command, root, env_extra=runtime_env(root))
    print(clean(result.stdout.rstrip()))


def graph_abort(root, confirm):
    """Cancel a prepared refresh only when no semantic chunk was written."""
    if not confirm:
        raise ValueError("abort requires --confirm")
    require_graph_output(root)
    out = root / "graphify-out"
    refresh = out / ".workflow_refresh.json"
    manifest_path = out / ".graphify_chunks.json"
    if not refresh.is_file():
        emit("nothing_to_abort", graph=str(out / "graph.json"))
        return
    try:
        refresh_state = read_json(refresh)
    except (OSError, ValueError) as exc:
        raise RuntimeError(f"refresh marker is unreadable: {exc}")
    if refresh_state.get("status") != "prepared":
        raise RuntimeError("refusing to abort a refresh that is not prepared")
    if not os.path.lexists(manifest_path):
        # A prepare that failed before writing its manifest wrote no chunks, so
        # nothing can be lost by clearing its marker.
        if any(out.glob(".graphify_chunk_*.json")):
            raise RuntimeError("refusing to abort: chunk files exist but the manifest is missing")
        refresh.unlink()
        emit("aborted", graph=str(out / "graph.json"), discarded_chunks=0, note="prepared manifest was missing")
        return
    try:
        manifest = read_json(manifest_path)
    except (OSError, ValueError) as exc:
        raise RuntimeError(f"refresh manifest is unreadable: {exc}")
    chunks = manifest.get("chunks")
    if not isinstance(chunks, list):
        raise RuntimeError("refresh manifest has no chunk list")
    outputs = []
    for chunk in chunks:
        output = chunk.get("output") if isinstance(chunk, dict) else None
        if not isinstance(output, str) or not re.fullmatch(r"graphify-out/\.graphify_chunk_[0-9]+\.json", output):
            raise RuntimeError("refresh manifest has an unsafe chunk output path")
        outputs.append(root / output)
    written = [str(path.relative_to(root)) for path in outputs if path.is_file()]
    if written:
        raise RuntimeError("refusing to abort: semantic chunks exist; resume or finalize the refresh first")
    if any(out.glob(".graphify_chunk_*.json")):
        raise RuntimeError("refusing to abort: chunk files exist that the manifest does not list")
    refresh.unlink()
    manifest_path.unlink()
    emit("aborted", graph=str(out / "graph.json"), discarded_chunks=len(outputs))


def graph_doctor(root):
    """Report Graphify workflow health and one safe next action without mutation."""
    require_graph_output(root)
    out = root / "graphify-out"
    graph = out / "graph.json"
    refresh = out / ".workflow_refresh.json"
    manifest_path = out / ".graphify_chunks.json"
    viewer = out / "graph.html"
    if refresh.is_file():
        try:
            refresh_state = read_json(refresh)
        except (OSError, ValueError) as exc:
            emit("refresh_marker_invalid", graph=str(graph), viewer_present=viewer.is_file(),
                 next_action="inspect the refresh marker; do not remove it manually", error=str(exc))
            return
        if refresh_state.get("status") != "prepared":
            emit("refresh_marker_unexpected", graph=str(graph), viewer_present=viewer.is_file(),
                 next_action="inspect the refresh marker; do not remove it manually",
                 marker_status=refresh_state.get("status"))
            return
        if not os.path.lexists(manifest_path):
            emit("prepared_manifest_missing", graph=str(graph), viewer_present=viewer.is_file(),
                 next_action=f"{TOOL} abort --confirm (no chunks can exist without a manifest), then prepare again if a refresh is still wanted")
            return
        try:
            manifest = load_manifest(root)
            outputs = [root / chunk["output"] for chunk in manifest["chunks"]]
        except (OSError, ValueError) as exc:
            emit("prepared_manifest_invalid", graph=str(graph), viewer_present=viewer.is_file(),
                 next_action=f"inspect the prepared refresh; if you did not just run prepare, treat the manifest as "
                             f"untrusted and run {TOOL} abort --confirm (allowed while no chunk exists)",
                 error=clean(str(exc)))
            return
        written = [str(path.relative_to(root)) for path in outputs if path.is_file()]
        if not written:
            emit("prepared_no_chunks", graph=str(graph), viewer_present=viewer.is_file(),
                 chunks_total=len(outputs), next_action=f"{TOOL} abort --confirm")
            return
        if len(written) == len(outputs):
            emit("prepared_all_chunks_written", graph=str(graph), viewer_present=viewer.is_file(),
                 chunks_total=len(outputs), next_action=f"validate every assigned chunk, then run {TOOL} finalize")
            return
        emit("prepared_partial_chunks", graph=str(graph), viewer_present=viewer.is_file(),
             chunks_total=len(outputs), chunks_written=len(written),
             next_action="resume the missing semantic workers; do not use abort")
        return
    if not graph.is_file():
        emit("graph_missing", graph=str(graph), viewer_present=viewer.is_file(),
             next_action=f"{TOOL} prepare")
        return
    details = graph_status_details(root)
    status = details.pop("status")
    if status == "current":
        action = "none"
    elif status == "stale_semantic":
        action = "use current source for the immediate task; prepare a semantic refresh only if the changed material should be discoverable"
    elif status == "stale_code":
        action = f"refresh code relationships with {TOOL} refresh-code (a code-only update; changed documents need a prepare and finalize refresh)"
    else:
        action = "inspect graph freshness metadata before relying on graph results"
    emit(status, **details, viewer_present=viewer.is_file(), next_action=action)


def graph_finalize(root):
    require_graph_output(root)
    spec = helper("extraction-spec.md").resolve()
    result = run([sys.executable, str(helper("finalize.py")), str(root), "--spec", str(spec)], root,
                 env_extra=runtime_env(root))
    print(clean(result.stdout.rstrip()))


def graph_file(root):
    require_graph_output(root)
    graph = root / "graphify-out" / "graph.json"
    if not graph.is_file():
        raise RuntimeError(f"Graphify graph missing: {graph}")
    return graph


def graphify_read(root, arguments, timeout=300):
    graph_warning(root)
    executable = trusted_which("graphify", repository_boundary(root))
    if not executable:
        raise RuntimeError("Graphify executable not found")
    try:
        result = run([executable, *arguments], root, timeout=timeout)
    except subprocess.TimeoutExpired:
        raise RuntimeError(f"graphify timed out after {timeout} seconds")
    text = result.stdout.rstrip()
    if len(text) > OUTPUT_LIMIT:
        text = text[:OUTPUT_LIMIT] + "\n... (output truncated at 1 MiB)"
    print(clean(text))


def graph_query(root, args):
    command = ["query", plain_argument(args.question, "question"), "--graph", str(graph_file(root)),
               "--budget", str(args.budget)]
    if args.dfs:
        command.append("--dfs")
    for context in args.context:
        command.extend(["--context", plain_argument(context, "context")])
    graphify_read(root, command, args.timeout)


def graph_path(root, args):
    graphify_read(root, ["path", plain_argument(args.source, "source"), plain_argument(args.target, "target"),
                         "--graph", str(graph_file(root))], args.timeout)


def graph_explain(root, args):
    graphify_read(root, ["explain", plain_argument(args.node, "node"), "--graph", str(graph_file(root))],
                  args.timeout)


def graph_affected(root, args):
    command = ["affected", plain_argument(args.node, "node"), "--graph", str(graph_file(root)),
               "--depth", str(args.depth)]
    for relation in args.relation:
        command.extend(["--relation", plain_argument(relation, "relation")])
    graphify_read(root, command, args.timeout)


def graph_god_nodes(root, args):
    command = ["god-nodes", "--graph", str(graph_file(root)), "--top", str(args.top)]
    if args.json:
        command.append("--json")
    graphify_read(root, command, args.timeout)


def graph_diagnose(root, args):
    command = [
        "diagnose", "multigraph", "--graph", str(graph_file(root)),
        "--max-examples", str(args.max_examples),
    ]
    if args.json:
        command.append("--json")
    graphify_read(root, command, args.timeout)


def graph_benchmark(root, timeout=300):
    graphify_read(root, ["benchmark", str(graph_file(root))], timeout)


def graph_validate_chunk(root, raw_path):
    require_graph_output(root)
    if not isinstance(raw_path, str) or not CHUNK_OUTPUT.fullmatch(raw_path):
        raise ValueError("chunk must be an exact project-relative graphify-out/.graphify_chunk_NN.json path")
    path = (root / raw_path).resolve()
    try:
        path.relative_to(root)
    except ValueError as exc:
        raise ValueError("chunk path escapes repository") from exc
    if not path.is_file():
        raise ValueError(f"chunk file missing: {raw_path}")
    data = read_json(root / raw_path)  # the unresolved path: an in-project symlink is refused
    if not isinstance(data, dict):
        raise ValueError("chunk root must be a JSON object")
    for key in ("nodes", "edges", "hyperedges"):
        if not isinstance(data.get(key), list):
            raise ValueError(f"chunk field {key!r} must be an array")

    manifest = load_manifest(root)
    assigned = next(
        (chunk for chunk in manifest.get("chunks", []) if chunk.get("output") == raw_path),
        None,
    )
    if assigned is None:
        raise ValueError("chunk is not assigned by the current prepared manifest")
    allowed_sources = set(assigned.get("files", []))
    expected_sources = {
        item.get("source_file"): item
        for item in assigned.get("sources", [])
        if isinstance(item, dict) and isinstance(item.get("source_file"), str)
    }
    if set(expected_sources) != allowed_sources:
        raise ValueError("prepared chunk is missing exact source metadata; rerun prepare")

    coverage = data.get("coverage")
    if not isinstance(coverage, list) or len(coverage) != len(expected_sources):
        raise ValueError(
            f"coverage must contain exactly {len(expected_sources)} prepared source receipts"
        )
    receipts = {}
    for index, item in enumerate(coverage):
        if not isinstance(item, dict):
            raise ValueError(f"coverage entry {index} must be an object")
        source = item.get("source_file")
        if source not in expected_sources:
            raise ValueError(f"coverage entry {index} is outside the assigned source scope")
        if source in receipts:
            raise ValueError(f"coverage contains duplicate source: {source}")
        if item.get("status") != "read_complete":
            raise ValueError(f"coverage entry {index} is not marked read_complete")
        expected_digest = expected_sources[source].get("sha256")
        if item.get("sha256") != expected_digest:
            raise ValueError(f"coverage entry {index} has the wrong prepared digest")
        receipts[source] = item
    missing_receipts = sorted(allowed_sources - set(receipts))
    if missing_receipts:
        raise ValueError(f"coverage is missing assigned sources: {missing_receipts}")

    if sum(record.get("size_bytes", 0) for record in expected_sources.values()) > MAX_TOTAL_HASH_BYTES:
        raise ValueError("assigned sources are too much to verify at once")
    for source, record in expected_sources.items():
        source_path = Path(source)
        if not source_path.is_file():
            raise ValueError(f"assigned source is missing after preparation: {source}")
        if source_path.stat().st_size > MAX_SOURCE_BYTES:
            raise ValueError(f"assigned source too large to verify ({source_path.stat().st_size} bytes): {source}")
        if source_path.stat().st_size != record.get("size_bytes"):
            raise ValueError(f"assigned source size changed after preparation: {source}")
        digest = hashlib.sha256()
        with source_path.open("rb") as stream:
            for block in iter(lambda: stream.read(1024 * 1024), b""):
                digest.update(block)
        if digest.hexdigest() != record.get("sha256"):
            raise ValueError(f"assigned source content changed after preparation: {source}")

    node_ids = set()
    for index, node in enumerate(data["nodes"]):
        if not isinstance(node, dict):
            raise ValueError(f"node {index} must be an object")
        node_id = str(node.get("id", ""))
        if not GRAPH_ID.fullmatch(node_id):
            raise ValueError(f"node {index} has invalid id: {node_id!r}")
        if not str(node.get("label", "")).strip():
            raise ValueError(f"node {node_id!r} has an empty label")
        if node.get("file_type") not in GRAPH_FILE_TYPES:
            raise ValueError(f"node {node_id!r} has invalid file_type")
        if node.get("source_file") not in allowed_sources:
            raise ValueError(f"node {node_id!r} is outside the assigned source scope")
        node_ids.add(node_id)

    for index, edge in enumerate(data["edges"]):
        if not isinstance(edge, dict):
            raise ValueError(f"edge {index} must be an object")
        confidence, score = edge.get("confidence"), edge.get("confidence_score")
        if edge.get("source_file") not in allowed_sources:
            raise ValueError(f"edge {index} is outside the assigned source scope")
        if not str(edge.get("relation", "")).strip() or not edge.get("source") or not edge.get("target"):
            raise ValueError(f"edge {index} is missing source, target, or relation")
        if confidence not in {"EXTRACTED", "INFERRED", "AMBIGUOUS"}:
            raise ValueError(f"edge {index} has invalid confidence")
        if not isinstance(score, (int, float)):
            raise ValueError(f"edge {index} has invalid confidence_score")
        if confidence in GRAPH_SCORES and score not in GRAPH_SCORES[confidence]:
            raise ValueError(f"edge {index} has unsupported {confidence} confidence_score")
        if confidence == "AMBIGUOUS" and not 0.1 <= score <= 0.3:
            raise ValueError(f"edge {index} has unsupported AMBIGUOUS confidence_score")

    for index, hyperedge in enumerate(data["hyperedges"]):
        if not isinstance(hyperedge, dict):
            raise ValueError(f"hyperedge {index} must be an object")
        if hyperedge.get("source_file") not in allowed_sources:
            raise ValueError(f"hyperedge {index} is outside the assigned source scope")
        if not str(hyperedge.get("relation", "")).strip() or len(hyperedge.get("nodes", [])) < 3:
            raise ValueError(f"hyperedge {index} requires a relation and at least three nodes")

    ast = read_json(root / "graphify-out" / ".graphify_ast.json")
    cached = read_json(root / "graphify-out" / ".graphify_cached.json")
    external_ids = {
        node["id"]
        for source in (ast, cached)
        for node in source.get("nodes", [])
        if isinstance(node, dict) and "id" in node
    }
    known_ids = node_ids | external_ids
    cached_ids = external_ids
    dangling_cached_edges = [
        edge for edge in cached.get("edges", [])
        if edge.get("source") not in cached_ids or edge.get("target") not in cached_ids
    ]
    dangling_cached_hyperedges = [
        edge for edge in cached.get("hyperedges", [])
        if any(node not in cached_ids for node in edge.get("nodes", []))
    ]
    if dangling_cached_edges or dangling_cached_hyperedges:
        raise ValueError(
            "prepared semantic cache has dangling endpoints; rerun prepare with the current workflow: "
            f"{len(dangling_cached_edges)} edges, {len(dangling_cached_hyperedges)} hyperedges"
        )
    dangling_edges = [
        edge for edge in data["edges"]
        if edge.get("source") not in known_ids or edge.get("target") not in known_ids
    ]
    dangling_hyperedges = [
        edge for edge in data["hyperedges"]
        if any(node not in known_ids for node in edge.get("nodes", []))
    ]
    if dangling_edges or dangling_hyperedges:
        unknown = sorted({
            endpoint
            for edge in dangling_edges
            for endpoint in (edge.get("source"), edge.get("target"))
            if endpoint not in known_ids
        } | {
            endpoint
            for edge in dangling_hyperedges
            for endpoint in edge.get("nodes", [])
            if endpoint not in known_ids
        })
        examples = unknown[:8]
        suggestions = {
            endpoint: difflib.get_close_matches(endpoint, known_ids, n=3, cutoff=0.6)
            for endpoint in examples
        }
        raise ValueError(
            "dangling semantic endpoints: "
            f"{len(dangling_edges)} edges, {len(dangling_hyperedges)} hyperedges; "
            f"unknown={examples!r}; suggestions={suggestions!r}; "
            f"edge_examples={dangling_edges[:3]!r}; hyperedge_examples={dangling_hyperedges[:2]!r}"
        )
    emit(
        "valid",
        chunk=raw_path,
        nodes=len(data["nodes"]),
        edges=len(data["edges"]),
        hyperedges=len(data["hyperedges"]),
    )


def atomic_write(path, text):
    """Write text through a temporary file and os.replace, never through a symlink."""
    path = Path(path)
    descriptor, temporary = tempfile.mkstemp(dir=str(path.parent), prefix=".tmp-")
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
            stream.write(text)
        os.replace(temporary, path)
    except BaseException:
        try:
            os.unlink(temporary)
        except OSError:
            pass
        raise


def graph_counts(path):
    """Portable graph totals, or None when no readable graph exists."""
    try:
        data = read_json(path)
    except (OSError, ValueError):
        return None
    if not isinstance(data, dict):
        return None
    nodes = data.get("nodes", [])
    edges = data.get("edges", data.get("links", []))
    hyperedges = data.get("hyperedges", [])
    if not all(isinstance(item, list) for item in (nodes, edges, hyperedges)):
        return None
    communities = {
        node.get("community") for node in nodes
        if isinstance(node, dict) and node.get("community") is not None
    }
    return {"nodes": len(nodes), "edges": len(edges), "hyperedges": len(hyperedges),
            "communities": len(communities)}


def graph_delta(before, after):
    if before is None or after is None:
        return None
    return {"before": before, "after": after,
            "delta": {key: after[key] - before.get(key, 0) for key in after}}


def record_code_refresh(root):
    """Advance the code head without hiding un-ingested semantic changes.

    semantic_head is the last commit whose documents were semantically ingested. Pin it to the previous
    head before advancing head, so a code-only refresh cannot make a graph with pending semantic changes
    look current.
    """
    state_path = root / "graphify-out" / ".workflow_graph_state.json"
    state = {}
    if state_path.is_file():
        try:
            state = read_json(state_path)
        except (OSError, ValueError):
            state = {}
        if not isinstance(state, dict):
            state = {}
    # A graph this tool never built has no known semantic baseline.
    if "semantic_head" not in state and not state.get("head"):
        state["semantic_head"] = None
    elif state.get("head") and not state.get("semantic_head") and "semantic_head" not in state:
        state["semantic_head"] = state["head"]
    state.update({"head": head(root), "generated_at": datetime.now(timezone.utc).isoformat()})
    atomic_write(state_path, json.dumps(state, indent=2))


def graph_refresh_code(root, timeout=300):
    """Run the vendor code-only update, then record it. An explicit step, never run by a commit."""
    require_graph_output(root)
    out = root / "graphify-out"
    graph = out / "graph.json"
    if not graph.is_file():
        raise RuntimeError(f"no graph to refresh: {graph}; run prepare to build one")
    marker = out / ".workflow_refresh.json"
    if marker.is_file():
        raise RuntimeError("a prepared refresh is in progress; run doctor and resume, finalize or abort it first")
    executable = trusted_which("graphify", repository_boundary(root))
    if not executable:
        raise RuntimeError("Graphify executable not found")
    before = graph_counts(graph)
    try:
        result = run([executable, "update", "."], root, check=False, timeout=timeout)
    except subprocess.TimeoutExpired:
        raise RuntimeError(f"graphify update timed out after {timeout} seconds")
    if result.returncode != 0:
        detail = (result.stderr or result.stdout or "unknown error").strip()[-500:]
        raise RuntimeError(f"graphify update failed ({result.returncode}): {detail}")
    record_code_refresh(root)
    details = graph_status_details(root)
    status = details.pop("status")
    emit("updated", graph_delta=graph_delta(before, graph_counts(graph)), graph_status=status,
         next_action=("none" if status == "current" else
                      f"changed documents need a semantic refresh: {TOOL} prepare, when worthwhile"))


def build_parser():
    parser = argparse.ArgumentParser(description="Graphify workflow tool for this project.")
    sub = parser.add_subparsers(dest="command", required=True)

    def command(name, help_text, reads_graph=False):
        item = sub.add_parser(name, help=help_text)
        item.add_argument("--root", default=".", help="project directory (default: .)")
        item.add_argument("--allow-repo-programs", action="store_true",
                          help="proceed although the repository's own git config defines programs git may run")
        if reads_graph:
            item.add_argument("--timeout", type=int, default=300, help="seconds before a vendor call is stopped")
        return item

    command("status", "report graph freshness")
    command("doctor", "report workflow health and one safe next action (read-only)")
    prepare_p = command("prepare", "prepare a semantic refresh (manifest and chunks to extract)")
    prepare_p.add_argument("--deep", action="store_true")
    abort_p = command("abort", "cancel a prepared refresh that has no chunks yet")
    abort_p.add_argument("--confirm", action="store_true")
    command("finalize", "merge validated chunks into the graph")
    refresh_p = command("refresh-code", "update code relationships only (an explicit, never automatic step)")
    refresh_p.add_argument("--timeout", type=int, default=300)
    validate_p = command("validate-chunk", "validate one written chunk against the prepared manifest")
    validate_p.add_argument("chunk")
    query_p = command("query", "ask one broad question", reads_graph=True)
    query_p.add_argument("question")
    query_p.add_argument("--budget", type=int, default=2000)
    query_p.add_argument("--context", action="append", default=[])
    query_p.add_argument("--dfs", action="store_true")
    path_p = command("path", "shortest relationship path between two nodes", reads_graph=True)
    path_p.add_argument("source")
    path_p.add_argument("target")
    explain_p = command("explain", "explain one node", reads_graph=True)
    explain_p.add_argument("node")
    affected_p = command("affected", "what depends on one node", reads_graph=True)
    affected_p.add_argument("node")
    affected_p.add_argument("--relation", action="append", default=[])
    affected_p.add_argument("--depth", type=int, default=2)
    god_p = command("god-nodes", "most connected nodes", reads_graph=True)
    god_p.add_argument("--top", type=int, default=10)
    god_p.add_argument("--json", action="store_true")
    diagnose_p = command("diagnose", "structural graph analysis", reads_graph=True)
    diagnose_p.add_argument("--max-examples", type=int, default=5)
    diagnose_p.add_argument("--json", action="store_true")
    command("benchmark", "graph benchmark", reads_graph=True)
    return parser


def main():
    args = build_parser().parse_args()
    root = git_root(Path(args.root))
    refuse_repo_programs(root, args.allow_repo_programs)
    if args.command == "status": graph_status(root)
    elif args.command == "doctor": graph_doctor(root)
    elif args.command == "prepare": graph_prepare(root, args.deep)
    elif args.command == "abort": graph_abort(root, args.confirm)
    elif args.command == "finalize": graph_finalize(root)
    elif args.command == "refresh-code": graph_refresh_code(root, args.timeout)
    elif args.command == "validate-chunk": graph_validate_chunk(root, args.chunk)
    elif args.command == "query": graph_query(root, args)
    elif args.command == "path": graph_path(root, args)
    elif args.command == "explain": graph_explain(root, args)
    elif args.command == "affected": graph_affected(root, args)
    elif args.command == "god-nodes": graph_god_nodes(root, args)
    elif args.command == "diagnose": graph_diagnose(root, args)
    else: graph_benchmark(root, args.timeout)


if __name__ == "__main__":
    try:
        main()
    except (OSError, RuntimeError, ValueError) as exc:
        emit("failed", error=str(exc))
        raise SystemExit(1)
    except Exception as exc:  # noqa: BLE001 - a tool must never end in a traceback
        emit("failed", error=f"internal error: {exc.__class__.__name__}: {exc}")
        raise SystemExit(1)
