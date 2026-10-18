#!/usr/bin/env python3
"""Create or extend a project from base/ plus opt-in modules.

Usage:
  install.py <target> [--with a,b,name=PATH] [--name N] [--dry-run]
             [--git-name N --git-email E | --use-global-git-identity]
  install.py --list
  install.py --add <module|name=PATH>... [--dir DIR]
  install.py --register PATH [--name N] [--dry-run]
  install.py --unregister NAME [--dry-run]
  (--registry FILE overrides the registry location for any of the above)

`name=PATH` installs the slot fragments of a standalone project that ships a
`template-module/` descriptor; see docs/specs/external-modules.md.

Standard library only (Python 3.9+). See docs/decisions/0001-*.md.
"""
import argparse
import hashlib
import json
import os
import re
import stat
import subprocess
import sys

ROOT = os.path.dirname(os.path.realpath(__file__))
BASE_DIR = os.path.join(ROOT, "base")
MODULES_DIR = os.path.join(ROOT, "modules")
MANIFEST = ".template-manifest"
SCHEMA = 1

NAME_RE = re.compile(r"^[a-z0-9][a-z0-9-]*\Z")
EXT_NAME_RE = re.compile(r"^[a-z0-9][a-z0-9_-]*\Z")
DIGEST_RE = re.compile(r"^[0-9a-f]{64}\Z")
DESCRIPTOR_DIR = "template-module"
MODULE_FORMATS = (1,)
EXTERNAL_ORDER = 1000000
DESCRIPTION_MAX = 200
FRAGMENT_MAX_BYTES = 64 * 1024
FRAGMENT_MAX_COUNT = 16
REGISTRY_SCHEMA = 1
MAX_REGISTRY_BYTES = 1024 * 1024
FRAGMENT_FORBIDDEN = ("@module-slot:", "BEGIN module:", "END module:")
SLOT_RE = re.compile(
    r"^(?P<open><!--|#)\s*@module-slot:\s*(?P<slot>[a-z0-9-]+)\s*(?P<close>-->)?\s*$"
)
PLACEHOLDER = "REPLACE_WITH_"
NAME_PLACEHOLDER = b"REPLACE_WITH_PROJECT_NAME"
ID_PLACEHOLDER = b"REPLACE_WITH_PROJECT_ID"
HINT_MAX = 200
MAX_FILE_BYTES = 16 * 1024 * 1024
MAX_MANIFEST_BYTES = 1024 * 1024
ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]*$")


class InstallError(Exception):
    """A user-facing failure; nothing partial is left behind where avoidable."""


# --------------------------------------------------------------------------
# Modules


def refuse_symlink(path, what):
    if os.path.islink(path):
        raise InstallError("symlink not allowed in %s: %s" % (what, path))


def load_modules(modules_dir=None):
    modules_dir = modules_dir or MODULES_DIR
    modules = {}
    if not os.path.isdir(modules_dir):
        return modules
    for name in sorted(os.listdir(modules_dir)):
        path = os.path.join(modules_dir, name)
        if os.path.islink(path):
            raise InstallError("symlink not allowed in modules: %s" % path)
        if not os.path.isdir(path):
            continue
        if not NAME_RE.match(name):
            raise InstallError("invalid module name: %r" % name)
        meta = {"description": "", "requires": [], "order": 100, "harness": False,
                "hint": None}
        meta_path = os.path.join(path, "module.json")
        if os.path.lexists(meta_path):
            try:
                meta.update(json.loads(read_regular(meta_path, MAX_MANIFEST_BYTES).decode("utf-8")))
            except (ValueError, RecursionError, TypeError):
                raise InstallError("module %s: module.json is not a valid JSON object" % name)
        for req in meta["requires"]:
            if not NAME_RE.match(req):
                raise InstallError("module %s: invalid requirement %r" % (name, req))
        hint = meta["hint"]
        if hint is not None and not (
            isinstance(hint, str)
            and 0 < len(hint) <= HINT_MAX
            and hint.isprintable()
        ):
            raise InstallError(
                "module %s: hint must be a single printable line of 1-%d characters"
                % (name, HINT_MAX)
            )
        slots = {}
        slot_dir = os.path.join(path, "slots")
        refuse_symlink(os.path.join(path, "files"), "module %s" % name)
        refuse_symlink(slot_dir, "module %s" % name)
        if os.path.isdir(slot_dir):
            for entry in sorted(os.listdir(slot_dir)):
                if not entry.endswith(".md"):
                    raise InstallError("module %s: unexpected slot file %s" % (name, entry))
                slot = entry[:-3]
                if not NAME_RE.match(slot):
                    raise InstallError("module %s: invalid slot name %r" % (name, slot))
                slots[slot] = read_regular(os.path.join(slot_dir, entry)).decode("utf-8")
        meta.update(name=name, path=path, slots=slots)
        modules[name] = meta
    return modules


def parse_entries(parts):
    """Split `--with`/`--add` parts into (name, value or None) on the first `=`."""
    entries = []
    for part in parts:
        name, sep, value = part.partition("=")
        if sep and (not name or not value):
            raise InstallError("invalid module entry %r (expected name=path)" % part)
        entries.append((name, value if sep else None))
    return entries


def descriptor_digest(files):
    """SHA-256 over (relative path, NUL, decimal length, NUL, content) per file."""
    digest = hashlib.sha256()
    for rel, data in files:
        digest.update(rel.encode("utf-8") + b"\0" + str(len(data)).encode("ascii") + b"\0" + data)
    return digest.hexdigest()


def real_directory(path, what):
    if os.path.islink(path) or not os.path.isdir(path):
        raise InstallError("%s is not a directory (symlinks are not allowed): %s" % (what, path))


def is_within(child, parent):
    """True when `child` is `parent` or inside it, by real path and file identity."""
    child, parent = os.path.realpath(child), os.path.realpath(parent)
    if child == parent or child.startswith(parent + os.sep):
        return True
    if not os.path.exists(parent):
        return False
    probe = child
    while True:
        if os.path.exists(probe) and os.path.samefile(probe, parent):
            return True
        up = os.path.dirname(probe)
        if up == probe:
            return False
        probe = up


def shown_format(fmt):
    """The store's module_format for a message, bounded so a hostile value cannot flood it."""
    if isinstance(fmt, bool) or not isinstance(fmt, int):
        return "of the wrong type"
    return str(fmt) if len(str(fmt)) <= 12 else "out of range"


def same_store(first, second):
    """True when two store paths are the same directory, including case aliases."""
    if first == second:
        return True
    try:
        return os.path.samefile(first, second)
    except OSError:
        return False


def load_external(name, value, target, builtin):
    """Wrap `read_external` so an OS error on the store is a user-facing error."""
    try:
        return read_external(name, value, target, builtin)
    except OSError as exc:
        raise InstallError(
            "module %s: cannot read store: %s" % (name, exc.strerror or exc.__class__.__name__)
        )


def read_external(name, value, target, builtin):
    """Verify a standalone project read-only and return a module dict for it.

    Reads only `template-module/module.json` and `template-module/slots/*.md`
    through `read_regular`; nothing in the store is executed and no
    subprocess touches it.
    """
    if not EXT_NAME_RE.match(name):
        raise InstallError("invalid module name %r" % name)
    if name in builtin:
        raise InstallError("%r is a built-in module name and cannot name a store" % name)
    require_printable(value, "module path")
    path = os.path.expanduser(value)
    while True:  # drop trailing separators and "." so a symlink there is still seen as one
        trimmed = path.rstrip(os.sep)
        if trimmed.endswith(os.sep + "."):
            trimmed = trimmed[:-1]
        if trimmed == path:
            break
        path = trimmed
    path = path or os.sep
    if os.path.islink(path):
        raise InstallError("module %s: store is a symlink: %s" % (name, path))
    store = os.path.realpath(path)
    require_printable(store, "module path")
    if is_within(store, ROOT) or is_within(ROOT, store):
        raise InstallError(
            "module %s: store must not be, contain, or be inside the template repository" % name
        )
    if target is not None and (is_within(store, target) or is_within(target, store)):
        raise InstallError(
            "module %s: store must not be, contain, or be inside the target project" % name
        )
    if any(part.casefold() == ".git" for part in store.split(os.sep)):
        raise InstallError("module %s: store path may not touch git metadata" % name)
    real_directory(store, "module %s: store" % name)
    descriptor = os.path.join(store, DESCRIPTOR_DIR)
    slot_dir = os.path.join(descriptor, "slots")
    real_directory(descriptor, "module %s: %s" % (name, DESCRIPTOR_DIR))
    real_directory(slot_dir, "module %s: %s/slots" % (name, DESCRIPTOR_DIR))
    raw = read_regular(os.path.join(descriptor, "module.json"), MAX_MANIFEST_BYTES // 16)
    try:
        meta = json.loads(raw.decode("utf-8"))
    except (ValueError, RecursionError):
        raise InstallError("module %s: module.json is not a valid JSON object" % name)
    if not isinstance(meta, dict):
        raise InstallError("module %s: module.json is not a valid JSON object" % name)
    unknown = set(meta) - {"module_format", "description", "hint"}
    if unknown:
        raise InstallError("module %s: unknown module.json keys: %s" % (name, len(unknown)))
    fmt = meta.get("module_format")
    if isinstance(fmt, bool) or not isinstance(fmt, int) or fmt not in MODULE_FORMATS:
        raise InstallError(
            "module %s: module_format %s is not supported (this installer supports %s)"
            % (name, shown_format(fmt), ", ".join(str(f) for f in MODULE_FORMATS))
        )
    for key, required in (("description", True), ("hint", False)):
        if key not in meta and not required:
            continue
        text = meta.get(key)
        if not (isinstance(text, str) and 0 < len(text) <= DESCRIPTION_MAX and text.isprintable()):
            raise InstallError(
                "module %s: %s must be a single printable line of 1-%d characters"
                % (name, key, DESCRIPTION_MAX)
            )
    entries = os.listdir(slot_dir)
    if len(entries) > FRAGMENT_MAX_COUNT:
        raise InstallError("module %s: more than %d fragments" % (name, FRAGMENT_MAX_COUNT))
    raw_slots = {}
    for entry in entries:
        slot = entry[:-3]
        if not entry.endswith(".md") or not NAME_RE.match(slot):
            raise InstallError("module %s: unexpected entry in %s/slots" % (name, DESCRIPTOR_DIR))
        raw_slots[slot] = read_regular(os.path.join(slot_dir, entry), FRAGMENT_MAX_BYTES)
    where = store
    if target is not None:
        parent = os.path.realpath(os.path.dirname(os.path.abspath(target)))
        if os.path.dirname(store) == parent:
            where = "../" + os.path.basename(store)
    slots = {}
    for slot in sorted(raw_slots):
        if not is_text(raw_slots[slot]):
            raise InstallError("module %s: fragment %s is not UTF-8 text" % (name, slot))
        text = raw_slots[slot].decode("utf-8").replace("REPLACE_WITH_MODULE_NAME", name).replace(
            "REPLACE_WITH_MODULE_PATH", where
        )
        if any(mark in text for mark in FRAGMENT_FORBIDDEN):
            raise InstallError("module %s: fragment %s contains a reserved marker" % (name, slot))
        slots[slot] = text
    digest = descriptor_digest(
        [("module.json", raw)] + [("slots/%s.md" % s, raw_slots[s]) for s in sorted(raw_slots)]
    )
    return {
        "name": name, "path": store, "external": True, "description": meta["description"],
        "hint": meta.get("hint"), "module_format": fmt, "digest": digest, "requires": [],
        "order": EXTERNAL_ORDER, "harness": False, "slots": slots,
    }


def load_externals(entries, target, builtin, registered=()):
    """Load every `name=path` entry; names and real paths must be unique."""
    loaded, paths = {}, {}
    for name, value in entries:
        if name in loaded:
            raise InstallError("module %s given more than once" % name)
        try:
            meta = load_external(name, value, target, builtin)
        except InstallError as exc:
            if name in registered:
                raise InstallError(
                    "%s (registered store %s: if it moved or changed, unregister it and "
                    "register it again)" % (exc, name)
                )
            raise
        for seen, other in paths.items():
            if same_store(seen, meta["path"]):
                raise InstallError("modules %s and %s name the same store" % (other, name))
        paths[meta["path"]] = name
        loaded[name] = meta
    return loaded


def registry_path(override=None):
    """The registry file: the override, else under $XDG_CONFIG_HOME (absolute) or ~/.config."""
    if override is not None:
        if not override:
            raise InstallError("--registry needs a file name")
        return os.path.abspath(os.path.expanduser(override))
    base = os.environ.get("XDG_CONFIG_HOME", "")
    if not (base and os.path.isabs(base)):
        base = os.path.join(os.path.expanduser("~"), ".config")
    return os.path.join(base, "claude-project-template", "registry.json")


def malformed_registry(path, why):
    return InstallError("registry %s is malformed (%s)" % (path, why))


def load_registry(path):
    """Return {name: absolute path}; a missing file is an empty registry."""
    parent = os.path.dirname(path)
    if os.path.islink(parent):
        raise InstallError("registry directory is a symlink: %s" % parent)
    if not os.path.lexists(path):
        return {}
    raw = read_regular(path, MAX_REGISTRY_BYTES)
    try:
        data = json.loads(raw.decode("utf-8"))
    except (ValueError, RecursionError):
        raise malformed_registry(path, "not valid JSON")
    if not isinstance(data, dict) or set(data) != {"schema", "stores"}:
        raise malformed_registry(path, "expected an object with schema and stores")
    if isinstance(data["schema"], bool) or data["schema"] != REGISTRY_SCHEMA:
        raise malformed_registry(path, "unknown schema")
    if not isinstance(data["stores"], dict):
        raise malformed_registry(path, "stores is not an object")
    stores = {}
    for name, entry in data["stores"].items():
        if not EXT_NAME_RE.match(name):
            raise malformed_registry(path, "invalid store name")
        if not isinstance(entry, dict) or set(entry) != {"path"}:
            raise malformed_registry(path, "invalid store entry")
        where = entry["path"]
        if not (isinstance(where, str) and os.path.isabs(where) and where.isprintable()):
            raise malformed_registry(path, "store path must be an absolute single line")
        stores[name] = where
    return stores


def save_registry(path, stores):
    parent = os.path.dirname(path)
    if os.path.islink(parent):
        raise InstallError("registry directory is a symlink: %s" % parent)
    if os.path.lexists(path) and not stat.S_ISREG(os.lstat(path).st_mode):
        raise InstallError("registry is not a regular file: %s" % path)
    payload = {
        "schema": REGISTRY_SCHEMA,
        "stores": {name: {"path": stores[name]} for name in sorted(stores)},
    }
    data = (json.dumps(payload, indent=2) + "\n").encode("utf-8")
    temp = "%s.tmp-%d" % (path, os.getpid())
    try:
        os.makedirs(parent, mode=0o700, exist_ok=True)
        flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0)
        with os.fdopen(os.open(temp, flags, 0o600), "wb") as handle:
            handle.write(data)
        os.replace(temp, path)
    except OSError as exc:
        raise InstallError("cannot write registry %s: %s" % (path, exc.strerror or exc))
    finally:
        try:
            os.unlink(temp)
        except OSError:
            pass


def registered_entries(args, entries, builtin):
    """Fill in registered paths for bare names and check typed names against the registry.

    Returns (entries, registered names). The registry is opened only when some
    name is not a built-in module.
    """
    if all(name in builtin for name, _ in entries):
        return entries, set()
    stores = load_registry(registry_path(args.registry))
    resolved, registered = [], set()
    for name, value in entries:
        if name in builtin:
            resolved.append((name, value))
        elif value is None:
            if name not in stores:
                raise InstallError(
                    "unknown module %r (available: %s)"
                    % (name, ", ".join(sorted(builtin | set(stores))))
                )
            resolved.append((name, stores[name]))
            registered.add(name)
        else:
            if name in stores and not same_store(
                os.path.realpath(os.path.expanduser(value)), stores[name]
            ):
                raise InstallError(
                    "module %s is registered at %s, not at the given path; use that path "
                    "or unregister it first" % (name, stores[name])
                )
            resolved.append((name, value))
    return resolved, registered


def resolve(selected, modules):
    """Return the transitive closure of `selected`, sorted by (order, name)."""
    seen = set()
    stack = list(selected)
    while stack:
        name = stack.pop()
        if name in seen:
            continue
        if name not in modules:
            raise InstallError(
                "unknown module %r (available: %s)" % (name, ", ".join(sorted(modules)) or "none")
            )
        seen.add(name)
        stack.extend(modules[name]["requires"])
    return sorted(seen, key=lambda n: (modules[n]["order"], n))


# --------------------------------------------------------------------------
# Files


def is_text(data):
    try:
        data.decode("utf-8")
    except UnicodeDecodeError:
        return False
    return b"\0" not in data


def read_regular(path, limit=MAX_FILE_BYTES):
    """Read a regular file that is not, and does not go through, a symlink."""
    try:
        info = os.lstat(path)
    except OSError as exc:
        raise InstallError("cannot read %s: %s" % (path, exc.strerror or exc))
    if stat.S_ISLNK(info.st_mode):
        raise InstallError("symlink not allowed: %s" % path)
    if not stat.S_ISREG(info.st_mode):
        raise InstallError("not a regular file: %s" % path)
    if info.st_size > limit:
        raise InstallError("file too large (%d bytes, limit %d): %s" % (info.st_size, limit, path))
    flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_NONBLOCK", 0)
    try:
        fd = os.open(path, flags)
    except OSError as exc:
        raise InstallError("cannot read %s: %s" % (path, exc.strerror or exc))
    with os.fdopen(fd, "rb") as handle:
        return handle.read()


def reject_git_metadata(rel):
    if any(part.casefold() == ".git" for part in rel.split("/")):
        raise InstallError("path may not touch git metadata: %s" % rel)


def collect_tree(source_dir):
    """Map relative POSIX path -> bytes; regular files only, no symlinks,
    no traversal, no git metadata."""
    files = {}
    if os.path.islink(source_dir):
        raise InstallError("symlink not allowed in template source: %s" % source_dir)
    if not os.path.isdir(source_dir):
        return files
    for dirpath, dirnames, filenames in os.walk(source_dir):
        for entry in list(dirnames) + filenames:
            if os.path.islink(os.path.join(dirpath, entry)):
                raise InstallError("symlink not allowed in template source: %s" % os.path.join(dirpath, entry))
        for filename in filenames:
            full = os.path.join(dirpath, filename)
            rel = os.path.relpath(full, source_dir).replace(os.sep, "/")
            if rel.startswith("../") or rel.startswith("/"):
                raise InstallError("unsafe template path: %s" % rel)
            reject_git_metadata(rel)
            if rel.casefold() == MANIFEST.casefold():
                raise InstallError("path is reserved for the installer: %s" % rel)
            files[rel] = read_regular(full)
    return files


def scan_project(project, skipped=None):
    """Map relative POSIX path -> bytes for an existing project.

    Refuses symlinks, special files, and oversized files anywhere outside
    `.git`. When `skipped` is a list they are instead recorded there as
    (relative path, reason) and left unread; a skipped entry is never patched
    or written through, because it is not in the returned map.
    """
    files = {}

    def unsafe(full, reason):
        rel = os.path.relpath(full, project).replace(os.sep, "/")
        if skipped is None:
            raise InstallError(
                "%s in project: %s (use --skip-unsafe-entries to skip such entries)" % (reason, full)
            )
        skipped.append((rel, reason))

    for dirpath, dirnames, filenames in os.walk(project):
        dirnames[:] = [d for d in dirnames if d != ".git"]
        for entry in list(dirnames):
            full = os.path.join(dirpath, entry)
            if os.path.islink(full):
                dirnames.remove(entry)
                unsafe(full, "symlink not allowed")
        for filename in filenames:
            full = os.path.join(dirpath, filename)
            rel = os.path.relpath(full, project).replace(os.sep, "/")
            try:
                info = os.lstat(full)
            except OSError as exc:
                raise InstallError("cannot read %s: %s" % (full, exc.strerror or exc))
            if stat.S_ISLNK(info.st_mode):
                unsafe(full, "symlink not allowed")
            elif not stat.S_ISREG(info.st_mode):
                unsafe(full, "not a regular file")
            elif info.st_size > MAX_FILE_BYTES:
                unsafe(full, "file too large (limit %d bytes)" % MAX_FILE_BYTES)
            else:
                files[rel] = read_regular(full)
    return files


def begin_line(style, module, slot):
    text = "BEGIN module:%s slot:%s" % (module, slot)
    return "<!-- %s -->" % text if style == "<!--" else "# %s" % text


def end_line(style, module, slot):
    text = "END module:%s slot:%s" % (module, slot)
    return "<!-- %s -->" % text if style == "<!--" else "# %s" % text


def apply_slots(text, order, fragments, relpath="<file>"):
    """Insert module fragments before each slot marker; return (text, used, markers).

    `order` lists module names in insertion order; `fragments` maps
    module -> {slot: fragment text}. Inserting is idempotent: a block whose
    BEGIN line is already present is skipped. Fragments may themselves contain
    markers, so insertion repeats until nothing changes.
    """
    used = set()
    markers = {}
    for _ in range(50):
        lines = text.split("\n")
        out = []
        changed = False
        markers = {}
        for line in lines:
            match = SLOT_RE.match(line)
            if not match:
                out.append(line)
                continue
            slot, style = match.group("slot"), match.group("open")
            if slot in markers:
                raise InstallError("%s: duplicate slot marker %r" % (relpath, slot))
            markers[slot] = True
            for module in order:
                fragment = fragments.get(module, {}).get(slot)
                if fragment is None:
                    continue
                begin = begin_line(style, module, slot)
                if begin in text:
                    used.add((module, slot))
                    continue
                body = fragment.rstrip("\n").split("\n")
                heading = body[0].startswith("#") if body else False
                if heading and out and out[-1].strip():
                    out.append("")
                out.append(begin)
                out.extend(body)
                out.append(end_line(style, module, slot))
                if heading:
                    out.append("")
                used.add((module, slot))
                changed = True
            out.append(line)
        text = "\n".join(out)
        if not changed:
            break
    else:
        raise InstallError("%s: slot expansion did not converge" % relpath)
    return text, used, set(markers)


def assemble(module_names, modules):
    """Build the output tree {relpath: bytes} for base plus the given modules."""
    tree = collect_tree(BASE_DIR)
    owners = {path: "base" for path in tree}
    folded = {path.casefold(): path for path in tree}
    for name in module_names:
        if modules[name].get("external"):
            continue  # a store contributes fragments only; its files are never read
        for path, data in collect_tree(os.path.join(modules[name]["path"], "files")).items():
            if path.casefold() in folded:
                other = folded[path.casefold()]
                raise InstallError(
                    "%s: file also provided by %s (as %s; names are compared "
                    "case-insensitively)" % (path, owners[other], other)
                )
            tree[path] = data
            owners[path] = name
            folded[path.casefold()] = path
    fragments = {name: modules[name]["slots"] for name in module_names}
    wanted = {(name, slot) for name in module_names for slot in fragments[name]}
    used = set()
    for path in sorted(tree):
        data = tree[path]
        if not is_text(data):
            continue
        text = data.decode("utf-8")
        if "@module-slot:" not in text:
            continue
        new_text, file_used, _ = apply_slots(text, module_names, fragments, path)
        used |= file_used
        tree[path] = new_text.encode("utf-8")
    missing = wanted - used
    if missing:
        raise InstallError(
            "fragments with no matching slot marker: "
            + ", ".join("%s:%s" % pair for pair in sorted(missing))
        )
    return tree


# --------------------------------------------------------------------------
# Git


GIT_KEEP = ("GIT_CONFIG_GLOBAL", "GIT_CONFIG_SYSTEM", "GIT_CONFIG_NOSYSTEM")
# Never run a configured helper program or inherit hooks/templates implicitly.
GIT_SAFE = ["-c", "core.fsmonitor=false", "-c", "core.untrackedCache=false",
            "-c", "core.hooksPath=/dev/null"]


def git_env():
    """The caller's environment without ambient GIT_* repository selection."""
    env = {k: v for k, v in os.environ.items() if not k.startswith("GIT_") or k in GIT_KEEP}
    env["GIT_OPTIONAL_LOCKS"] = "0"
    env["GIT_TERMINAL_PROMPT"] = "0"
    return env


def git(args, cwd=None, check=True):
    try:
        result = subprocess.run(
            ["git"] + GIT_SAFE + args, cwd=cwd, env=git_env(), text=True,
            capture_output=True, check=False,
        )
    except OSError as exc:
        raise InstallError("cannot run git: %s" % exc)
    if check and result.returncode:
        raise InstallError("git %s failed: %s" % (" ".join(args), (result.stderr or result.stdout).strip()))
    return result


def template_state():
    commit = git(["rev-parse", "HEAD"], cwd=ROOT, check=False)
    if commit.returncode:
        return None, None
    dirty = bool(git(["status", "--porcelain"], cwd=ROOT, check=False).stdout.strip())
    return commit.stdout.strip(), dirty


def require_printable(value, what):
    if not isinstance(value, str) or not value.isprintable():
        raise InstallError("%s must be a single line of printable characters" % what)
    return value


def validate_identity(name, email):
    name = require_printable((name or "").strip(), "git user name")
    email = require_printable((email or "").strip(), "git user email")
    if not name:
        raise InstallError("git user name must not be empty")
    if not re.match(r"^[^@\s]+@[^@\s]+$", email):
        raise InstallError("git user email must look like name@host")
    return name, email


def ask(prompt):
    try:
        return input(prompt)
    except EOFError:
        raise InstallError("input ended before the prompt was answered: %s" % prompt.strip())


def resolve_identity(args, interactive):
    if args.use_global_git_identity:
        return None
    name, email = args.git_name, args.git_email
    if (name is None or email is None) and interactive:
        if name is None:
            name = ask("Git user.name for this project: ")
        if email is None:
            email = ask(
                "Git user.email for this project (a noreply address is recommended): "
            )
    if name is None or email is None:
        raise InstallError(
            "git identity required: pass --git-name and --git-email "
            "(or --use-global-git-identity to inherit the global identity)"
        )
    return validate_identity(name, email)


# --------------------------------------------------------------------------
# Commands


def project_id(name):
    """A runner-safe id derived from the project name, or an error."""
    slug = re.sub(r"[^A-Za-z0-9_-]", "-", name)
    if not ID_RE.match(slug):
        raise InstallError(
            "project id cannot be derived from name %r: it must start with a "
            "letter or digit after replacing other characters with '-'; "
            "pass --name" % name
        )
    return slug


def substitute(tree, name):
    """Replace the name and id placeholders in text files, in place.

    The id is derived only when some file uses it, so a name that cannot form
    an id is accepted for projects without such a file.
    """
    for rel, data in list(tree.items()):
        if not is_text(data):
            continue
        if NAME_PLACEHOLDER in data:
            data = data.replace(NAME_PLACEHOLDER, name.encode("utf-8"))
        if ID_PLACEHOLDER in data:
            data = data.replace(ID_PLACEHOLDER, project_id(name).encode("utf-8"))
        tree[rel] = data


def placeholder_summary(tree):
    counts = {}
    for path, data in sorted(tree.items()):
        if is_text(data):
            count = data.decode("utf-8").count(PLACEHOLDER)
            if count:
                counts[path] = count
    return counts


def emit_hints(out, names, modules, dry_run):
    hints = [(n, modules[n]["hint"]) for n in names if modules[n]["hint"]]
    if not hints:
        return
    out("Next steps (dry run, nothing written):" if dry_run else "Next steps:")
    for name, hint in hints:
        out("  %s: %s" % (name, hint))


def parse_with(value):
    if not value:
        return []
    return [part.strip() for part in value.split(",") if part.strip()]


def check_target(target):
    target = os.path.abspath(target)
    if os.path.islink(target):
        raise InstallError("target is a symlink: %s" % target)
    real = os.path.realpath(target)
    if real == ROOT or real.startswith(ROOT + os.sep):
        raise InstallError("target must not be inside the template repository")
    # A case variant of the template path resolves to it on a case-insensitive
    # filesystem; compare every existing ancestor by identity.
    probe = target
    while True:
        if os.path.exists(probe) and os.path.samefile(probe, ROOT):
            raise InstallError("target must not be inside the template repository")
        parent = os.path.dirname(probe)
        if parent == probe:
            break
        probe = parent
    if os.path.exists(target):
        if not os.path.isdir(target) or os.listdir(target):
            raise InstallError("target exists and is not an empty directory: %s" % target)
    return target


def check_write_paths(root, rels):
    """Refuse a write whose path goes through a symlink, onto a non-file, or
    onto a file the owner has made read-only."""
    for rel in rels:
        reject_git_metadata(rel)
        parts = rel.split("/")
        current = root
        for part in parts[:-1]:
            current = os.path.join(current, part)
            if os.path.lexists(current) and (os.path.islink(current) or not os.path.isdir(current)):
                raise InstallError("refusing to write through %s (symlink or not a directory)" % current)
        final = os.path.join(current, parts[-1])
        if os.path.lexists(final):
            info = os.lstat(final)
            if stat.S_ISLNK(info.st_mode):
                raise InstallError("symlink not allowed: %s" % final)
            if not stat.S_ISREG(info.st_mode):
                raise InstallError("not a regular file: %s" % final)
            if not os.access(final, os.W_OK):
                raise InstallError("not writable: %s" % final)


def write_tree(target, tree):
    """Write every file via a temporary sibling and rename, manifest last.

    A rename replaces the directory entry, so a hardlinked file's other names
    are never written through; if any temporary file cannot be created
    nothing has been replaced yet.
    """
    check_write_paths(target, list(tree))
    order = sorted(tree, key=lambda rel: (rel == MANIFEST, rel))
    staged = []
    try:
        for rel in order:
            dest = os.path.join(target, *rel.split("/"))
            os.makedirs(os.path.dirname(dest), exist_ok=True)
            temp = "%s.install-%d.tmp" % (dest, os.getpid())
            flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0)
            fd = os.open(temp, flags, 0o666)
            staged.append((temp, dest))
            with os.fdopen(fd, "wb") as handle:
                handle.write(tree[rel])
            if os.path.exists(dest):
                os.chmod(temp, stat.S_IMODE(os.lstat(dest).st_mode))
        for temp, dest in staged:
            os.replace(temp, dest)
        staged = []
    except OSError as exc:
        raise InstallError("cannot write %s: %s" % (exc.filename or target, exc.strerror or exc))
    finally:
        for temp, _ in staged:
            try:
                os.unlink(temp)
            except OSError:
                pass


def validate_external_modules(value, builtin):
    ok = isinstance(value, dict)
    for name, entry in (value.items() if ok else ()):
        fmt = entry.get("module_format") if isinstance(entry, dict) else None
        digest = entry.get("digest") if isinstance(entry, dict) else None
        ok = (
            ok and EXT_NAME_RE.match(name) and name not in builtin
            and isinstance(entry, dict)
            and not isinstance(fmt, bool) and fmt in MODULE_FORMATS
            and isinstance(digest, str) and DIGEST_RE.match(digest)
        )
    if not ok:
        raise InstallError("%s has a malformed external_modules entry" % MANIFEST)


def load_manifest(project, builtin=()):
    if os.path.islink(project):
        raise InstallError("project directory is a symlink: %s" % project)
    path = os.path.join(project, MANIFEST)
    if not os.path.lexists(path):
        raise InstallError(
            "%s not found: --add works only on projects created by this installer" % MANIFEST
        )
    raw = read_regular(path, MAX_MANIFEST_BYTES)
    try:
        manifest = json.loads(raw.decode("utf-8"))
    except (ValueError, RecursionError):
        raise InstallError("%s is not valid JSON" % MANIFEST)
    modules = manifest.get("modules") if isinstance(manifest, dict) else None
    schema = manifest.get("schema") if isinstance(manifest, dict) else None
    if (
        not isinstance(manifest, dict)
        or isinstance(schema, bool) or schema != SCHEMA
        or not isinstance(modules, list)
        or not all(isinstance(m, str) and NAME_RE.match(m) for m in modules)
    ):
        raise InstallError(
            "%s is malformed (expected an object with schema %d and a list of module names)"
            % (MANIFEST, SCHEMA)
        )
    if "external_modules" in manifest:
        validate_external_modules(manifest["external_modules"], builtin)
    return manifest


def external_record(meta):
    return {"module_format": meta["module_format"], "digest": meta["digest"]}


def manifest_bytes(module_names, commit, dirty, externals=None):
    payload = {
        "schema": SCHEMA,
        "template_commit": commit,
        "template_dirty": dirty,
        "modules": sorted(module_names),
    }
    if externals:
        payload["external_modules"] = externals
    return (json.dumps(payload, indent=2, sort_keys=True) + "\n").encode("utf-8")


def cmd_new(args, out):
    modules = load_modules()
    selected = parse_with(args.with_)
    interactive = sys.stdin.isatty()
    # Everything that can fail without user input comes before any prompt.
    target = check_target(args.target)
    name = args.name or os.path.basename(target.rstrip(os.sep))
    if not name:
        raise InstallError("invalid project name")
    require_printable(name, "project name")
    if not args.with_ and interactive and not args.dry_run:
        answer = ask(
            "Modules (comma separated, blank for none; available: %s): "
            % ", ".join(sorted(modules))
        )
        selected = parse_with(answer)
    entries = parse_entries(selected)
    builtin = set(modules)
    entries, registered = registered_entries(args, entries, builtin)
    externals = load_externals(
        [(n, v) for n, v in entries if v is not None], target, builtin, registered
    )
    modules = dict(modules, **externals)
    selected = [n for n, _ in entries]
    names = resolve(selected, modules)
    tree = assemble(names, modules)
    substitute(tree, name)
    identity = None
    if not args.dry_run:
        identity = resolve_identity(args, interactive)
    commit, dirty = template_state()
    tree[MANIFEST] = manifest_bytes(
        [n for n in names if n in builtin], commit, dirty,
        {n: external_record(modules[n]) for n in names if n in externals},
    )

    out("Project: %s" % name)
    out("Target:  %s" % target)
    out("Modules: %s" % (", ".join(names) or "none"))
    pulled = sorted(set(names) - set(selected))
    if pulled:
        out("Required modules added: %s" % ", ".join(pulled))
    if args.dry_run:
        for rel in sorted(tree):
            out("  would write %s" % rel)
        emit_hints(out, names, modules, True)
        out("Dry run: nothing written.")
        return 0

    os.makedirs(target, exist_ok=True)
    write_tree(target, tree)
    git(["init", "-q", "--template="], cwd=target)
    git(["symbolic-ref", "HEAD", "refs/heads/main"], cwd=target)
    exclude = os.path.join(target, ".git", "info", "exclude")
    os.makedirs(os.path.dirname(exclude), exist_ok=True)
    with open(exclude, "a", encoding="utf-8") as handle:
        handle.write("/.debug/\n")
    if identity is not None:
        git(["config", "--local", "user.name", identity[0]], cwd=target)
        git(["config", "--local", "user.email", identity[1]], cwd=target)
        out("Git identity (local): %s <%s>" % identity)
        if "noreply" not in identity[1]:
            out("  warning: email is not a noreply address; it will appear in every commit.")
    else:
        out("Git identity: INHERITED from global config (--use-global-git-identity).")
    out("Initialized an empty git repository on branch main (no remote, no commits).")
    counts = placeholder_summary(tree)
    if counts:
        out("Unresolved placeholders:")
        for rel, count in counts.items():
            out("  %s: %d" % (rel, count))
    emit_hints(out, names, modules, False)
    return 0


def cmd_list(args, out):
    modules = load_modules()
    for name in sorted(modules):
        meta = modules[name]
        flags = []
        if meta["harness"]:
            flags.append("harness")
        if meta["requires"]:
            flags.append("requires " + ",".join(meta["requires"]))
        suffix = " (%s)" % "; ".join(flags) if flags else ""
        out("%s%s: %s" % (name, suffix, meta["description"]))
    stores = load_registry(registry_path(args.registry))  # after the built-ins, so they always show
    if stores:
        out("")
        out("Registered stores:")
        for name in sorted(stores):
            path, text = stores[name], stores[name]
            if name in modules:
                status = "invalid: shadowed by a built-in module"
            elif not os.path.lexists(path):
                status = "missing"
            else:
                try:
                    text = load_external(name, path, None, set(modules))["description"]
                    status = "ok"
                except InstallError as exc:
                    status = "invalid: %s" % exc
            out("  %s [%s]: %s" % (name, status, text))
    return 0


def cmd_register(args, out):
    if not args.register:
        raise InstallError("--register needs the path of a standalone project")
    builtin = set(load_modules())
    path = os.path.abspath(os.path.expanduser(args.register))
    name = args.name or os.path.basename(path.rstrip(os.sep))
    if not EXT_NAME_RE.match(name):
        raise InstallError("%r is not a valid module name; pass --name" % name)
    meta = load_external(name, args.register, None, builtin)
    location = registry_path(args.registry)
    stores = load_registry(location)
    if name in stores and same_store(stores[name], meta["path"]):
        out("%s is already registered at %s." % (name, meta["path"]))
        return 0
    if name in stores:
        raise InstallError(
            "%s is already registered at %s; unregister it first" % (name, stores[name])
        )
    for other, where in stores.items():
        if same_store(where, meta["path"]):
            raise InstallError(
                "%s is already registered as %s; unregister it first" % (where, other)
            )
    if args.dry_run:
        out("Would register %s -> %s (%s)" % (name, meta["path"], meta["description"]))
        out("Dry run: nothing written.")
        return 0
    stores[name] = meta["path"]
    save_registry(location, stores)
    out("Registered %s -> %s" % (name, meta["path"]))
    out("  %s" % meta["description"])
    return 0


def cmd_unregister(args, out):
    name = args.unregister
    if not name or not EXT_NAME_RE.match(name):
        raise InstallError("invalid module name %r" % name)
    if name in load_modules():
        raise InstallError("%s is a built-in module, not a registered store" % name)
    location = registry_path(args.registry)
    stores = load_registry(location)
    if name not in stores:
        out("%s is not registered." % name)
        return 0
    if args.dry_run:
        out("Would unregister %s (%s)" % (name, stores[name]))
        out("Dry run: nothing written.")
        return 0
    del stores[name]
    save_registry(location, stores)
    out("Unregistered %s." % name)
    return 0


def cmd_add(args, out):
    modules = load_modules()
    project = os.path.abspath(args.dir)
    builtin = set(modules)
    manifest = load_manifest(project, builtin)
    installed = list(manifest["modules"])
    recorded = dict(manifest.get("external_modules", {}))
    entries = parse_entries(args.add)
    # A recorded external module is never re-read: its store may have moved.
    fresh = [(n, v) for n, v in entries if n not in recorded]
    fresh, registered = registered_entries(args, fresh, builtin)
    externals = load_externals(
        [(n, v) for n, v in fresh if v is not None], project, builtin, registered
    )
    modules = dict(modules, **externals)
    wanted = resolve(list(installed) + [n for n, _ in fresh], modules)
    new = [name for name in wanted if name not in installed]
    if not new:
        out("Nothing to add: %s already installed." % ", ".join(n for n, _ in entries))
        return 0

    # Module files: refuse to overwrite anything that differs.
    project_name = require_printable(
        args.name or os.path.basename(project.rstrip(os.sep)), "project name"
    )
    writes = {}
    for name in new:
        if name in externals:
            continue
        files = collect_tree(os.path.join(modules[name]["path"], "files"))
        substitute(files, project_name)
        for rel, data in files.items():
            dest = os.path.join(project, *rel.split("/"))
            if os.path.lexists(dest):
                if read_regular(dest) != data:
                    raise InstallError("%s exists and differs; not overwriting" % rel)
                continue
            writes[rel] = data

    # Fragments: patch every project text file, including newly written ones.
    skipped = [] if args.skip_unsafe_entries else None
    existing = scan_project(project, skipped)
    if skipped:
        out("Skipped (not read, patched, or written through):")
        for rel, reason in sorted(skipped):
            out("  %s (%s)" % (rel, reason))
    existing.update(writes)
    fragments = {name: modules[name]["slots"] for name in wanted}
    patched = dict()
    used = set()
    for rel, data in existing.items():
        if not is_text(data) or b"@module-slot:" not in data:
            continue
        text = data.decode("utf-8")
        new_text, file_used, _ = apply_slots(text, new, fragments, rel)
        used |= file_used
        if new_text != text:
            patched[rel] = new_text.encode("utf-8")
    missing = {(n, s) for n in new for s in fragments[n]} - used
    if missing:
        raise InstallError(
            "fragments with no matching slot marker: "
            + ", ".join("%s:%s" % pair for pair in sorted(missing))
        )
    writes.update(patched)
    manifest["modules"] = sorted(n for n in wanted if n not in externals)
    for name in externals:
        recorded[name] = external_record(externals[name])
    if recorded:
        manifest["external_modules"] = recorded
    writes[MANIFEST] = (json.dumps(manifest, indent=2, sort_keys=True) + "\n").encode("utf-8")

    out("Adding modules: %s" % ", ".join(new))
    if args.dry_run:
        for rel in sorted(writes):
            out("  would write %s" % rel)
        emit_hints(out, new, modules, True)
        out("Dry run: nothing written.")
        return 0
    write_tree(project, writes)
    for rel in sorted(writes):
        out("  wrote %s" % rel)
    emit_hints(out, new, modules, False)
    return 0


def build_parser():
    parser = argparse.ArgumentParser(description="Create or extend a project from the template.")
    parser.add_argument("target", nargs="?", help="directory for the new project")
    parser.add_argument(
        "--with", dest="with_", default="",
        help="comma-separated modules; name=PATH installs a standalone project as module 'name'",
    )
    parser.add_argument(
        "--name",
        help="project name (default: target directory name); with --register, the registered "
             "name (default: the store's directory name)",
    )
    parser.add_argument("--register", metavar="PATH",
                        help="register a standalone project so its name works in --with and --add")
    parser.add_argument("--unregister", metavar="NAME", help="remove a registered name")
    parser.add_argument("--registry", metavar="FILE",
                        help="registry file (default: ~/.config/claude-project-template/registry.json)")
    parser.add_argument("--dry-run", action="store_true", help="show what would be written")
    parser.add_argument("--git-name", help="local git user.name for the new repository")
    parser.add_argument("--git-email", help="local git user.email for the new repository")
    parser.add_argument(
        "--use-global-git-identity",
        action="store_true",
        help="inherit the global git identity instead of setting a local one",
    )
    parser.add_argument("--list", action="store_true", help="list available modules")
    parser.add_argument(
        "--add", nargs="+", metavar="MODULE",
        help="add modules (or name=PATH standalone projects) to an existing project",
    )
    parser.add_argument("--dir", default=".", help="project directory for --add (default: .)")
    parser.add_argument(
        "--skip-unsafe-entries", action="store_true",
        help="with --add: skip (and list) symlinks, special files, and oversized files "
             "instead of refusing; skipped entries are never read, patched, or written through",
    )
    return parser


def main(argv=None, out=print):
    args = build_parser().parse_args(argv)
    try:
        if args.skip_unsafe_entries and not args.add:
            raise InstallError("--skip-unsafe-entries applies to --add only")
        registry_modes = (args.register is not None) + (args.unregister is not None)
        if registry_modes and (
            registry_modes > 1 or args.list or args.add or args.target or args.with_
        ):
            raise InstallError(
                "--register and --unregister cannot be combined with each other, a target "
                "directory, --list, --add, or --with"
            )
        if args.list:
            return cmd_list(args, out)
        if args.register is not None:
            return cmd_register(args, out)
        if args.unregister is not None:
            return cmd_unregister(args, out)
        if args.add:
            return cmd_add(args, out)
        if not args.target:
            build_parser().error("a target directory is required")
        return cmd_new(args, out)
    except InstallError as exc:
        print("error: %s" % exc, file=sys.stderr)
        return 2
    except KeyboardInterrupt:
        print("\ninterrupted; nothing was written", file=sys.stderr)
        return 130


if __name__ == "__main__":
    sys.exit(main())
