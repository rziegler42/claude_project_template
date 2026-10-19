#!/usr/bin/env python3
"""Create or extend a project from base/ plus opt-in modules.

Usage:
  install.py <target> [--with a,b,name=PATH] [--name N] [--dry-run] [--harness H]
             [--git-name N --git-email E | --use-global-git-identity]
  install.py --list
  install.py --add <module|name=PATH>... [--dir DIR] [--harness H]
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
import math
import os
import re
import stat
import subprocess
import sys
import tempfile
import unicodedata

ROOT =os.path.dirname(os.path.realpath(__file__))
BASE_DIR = os.path.join(ROOT, "base")
MODULES_DIR = os.path.join(ROOT, "modules")
MANIFEST = ".template-manifest"
PLAN_FILE = "docs/plans/next.md"
SCHEMA = 1
HARNESS_SCHEMA = 2
HARNESS_FILES_MAX = 4000
HARNESS_KEY_MAX = 256
HARNESS_RECORD_MAX_BYTES = 512 * 1024

NAME_RE = re.compile(r"^[a-z0-9][a-z0-9-]*\Z")
EXT_NAME_RE = re.compile(r"^[a-z0-9][a-z0-9_-]*\Z")
DIGEST_RE = re.compile(r"^[0-9a-f]{64}\Z")
DESCRIPTOR_DIR = "template-module"
MODULE_FORMATS = (1, 2)
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
SHA_RE = re.compile(r"^[0-9a-f]{40}\Z")
OBJECT_RE = re.compile(rb"^[0-9a-f]{40,64}\Z")
BASE_MAX_FILES = 4096
BASE_MAX_BYTES = 64 * 1024 * 1024
MANIFEST_MAP_MAX = 10000
GIT_TIMEOUT = 60
INFO_KEYS = ("type", "paths", "data")
INFO_NAME_MAX = 64
INFO_PATHS_MAX = 16
INFO_DATA_DEPTH = 4
INFO_DATA_NODES = 256
INFO_DATA_BYTES = 4096


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
        problem = module_info_problem({k: meta[k] for k in INFO_KEYS if k in meta})
        if problem:
            raise InstallError("module %s: %s" % (name, problem))
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


def info_name_ok(text):
    return isinstance(text, str) and len(text) <= INFO_NAME_MAX and bool(EXT_NAME_RE.match(text))


def info_text_ok(text, limit):
    return isinstance(text, str) and 0 < len(text) <= limit and text.isprintable()


def module_info_problem(info):
    """Describe what is wrong with a module's type, paths and data, or return None.

    The values are copied into the project manifest and read by other tools,
    so they are bounded and limited to plain JSON.
    """
    if "type" in info and not info_name_ok(info["type"]):
        return "type must be a lowercase name of 1-%d characters" % INFO_NAME_MAX
    if "paths" in info:
        paths = info["paths"]
        if not (isinstance(paths, dict) and len(paths) <= INFO_PATHS_MAX
                and all(info_name_ok(role) and safe_relpath(rel) for role, rel in paths.items())):
            return ("paths must map up to %d lowercase role names to safe relative paths"
                    % INFO_PATHS_MAX)
    if "data" in info:
        data = info["data"]
        if not isinstance(data, dict) or not plain_json(data):
            return ("data must be an object of plain JSON no deeper than %d levels, with at "
                    "most %d values and %d bytes" % (INFO_DATA_DEPTH, INFO_DATA_NODES,
                                                      INFO_DATA_BYTES))
    return None


def plain_json(data):
    """True for a bounded tree of dicts, lists, short printable strings, numbers, bools, null."""
    nodes, stack = 0, [(data, 1)]
    while stack:
        value, depth = stack.pop()
        nodes += 1
        if nodes > INFO_DATA_NODES or depth > INFO_DATA_DEPTH:
            return False
        if isinstance(value, dict):
            if any(not info_text_ok(key, INFO_NAME_MAX) for key in value):
                return False
            stack.extend((item, depth + 1) for item in value.values())
        elif isinstance(value, list):
            stack.extend((item, depth + 1) for item in value)
        elif isinstance(value, str):
            if not info_text_ok(value, DESCRIPTION_MAX):
                return False
        elif isinstance(value, float):
            if not math.isfinite(value):
                return False
        elif not (value is None or isinstance(value, (bool, int))):
            return False
    return len(json.dumps(data)) <= INFO_DATA_BYTES


def store_ok(value):
    """True for the two forms recorded as an external module's `store`.

    Sibling: `../` plus one safe component. Absolute: `/` plus safe components.
    Anything else, such as `foo/bar` or `.`, is refused so a consumer never
    resolves a surprise path against the project root.
    """
    if not (isinstance(value, str) and len(value) <= 512):
        return False
    if value.startswith("../"):
        part = value[3:]
        return "/" not in part and safe_relpath(part)
    return value.startswith("/") and safe_relpath(value[1:])


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
    fmt = meta.get("module_format")
    if isinstance(fmt, bool) or not isinstance(fmt, int) or fmt not in MODULE_FORMATS:
        raise InstallError(
            "module %s: module_format %s is not supported (this installer supports %s)"
            % (name, shown_format(fmt), ", ".join(str(f) for f in MODULE_FORMATS))
        )
    allowed = {"module_format", "description", "hint"}
    if fmt >= 2:
        allowed |= set(INFO_KEYS)
    unknown = set(meta) - allowed
    if unknown:
        raise InstallError("module %s: unknown module.json keys: %s" % (name, len(unknown)))
    problem = module_info_problem({k: meta[k] for k in INFO_KEYS if k in meta})
    if problem:
        raise InstallError("module %s: %s" % (name, problem))
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
    if not store_ok(where):
        raise InstallError("module %s: store path cannot be recorded in %s" % (name, MANIFEST))
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
    module = {
        "name": name, "path": store, "external": True, "description": meta["description"],
        "hint": meta.get("hint"), "module_format": fmt, "digest": digest, "requires": [],
        "order": EXTERNAL_ORDER, "harness": False, "slots": slots,
    }
    module.update({k: meta[k] for k in INFO_KEYS if k in meta})
    module["store"] = where
    return module


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
        data = handle.read(limit + 1)
    if len(data) > limit:
        raise InstallError("file too large (over %d bytes): %s" % (limit, path))
    return data


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


# --------------------------------------------------------------------------
# Harness files (docs/specs/module-harness-files.md)

HARNESS_NAME_RE = re.compile(r"^[a-z][a-z0-9-]{0,31}\Z")
ROLE_RE = re.compile(r"^[a-z][a-z0-9-]{0,63}\Z")
HARNESS_JSON = "harness.json"
HARNESS_ROOT_DIR = "root"
HARNESS_MAX_FILES = 128
HARNESS_MAX_DIR_ENTRIES = 128
HARNESS_MAX_FILE_BYTES = 256 * 1024
HARNESS_MAX_TREE_BYTES = 2 * 1024 * 1024
HARNESS_MAX_DEPTH = 8
HARNESS_JSON_MAX = 16 * 1024
HARNESS_ROLES_MAX = 16
HARNESS_RUN_FILES = 512
HARNESS_RUN_BYTES = 8 * 1024 * 1024
HARNESS_PROJECT_NAME_RE = re.compile(r"[A-Za-z0-9._ -]{1,200}\Z")
# The installer owns this table. `entries` are the top-level names a built-in
# module may ship under the harness root; `root_files` are the project-root
# entry points a harness directory carries in `root/`.
HARNESSES = {
    "claude": {
        "root": ".claude",
        "root_files": ("CLAUDE.md",),
        "entries": ("skills", "agents", "commands", "remote-runner.toml"),
    },
}


def fold(text):
    """Case- and Unicode-fold exactly as the specification says: NFC(casefold(NFC(x)))."""
    return unicodedata.normalize("NFC", unicodedata.normalize("NFC", text).casefold())


def check_unique(paths):
    seen = {}
    for path in paths:
        key = fold(path)
        if key in seen:
            raise InstallError(
                "harness paths %s and %s are the same after case and Unicode folding"
                % (shown_text(seen[key]), shown_text(path))
            )
        seen[key] = path


def shown_text(text, limit=80):
    """A name for a message, only when it is short, printable text."""
    if isinstance(text, str) and len(text) <= limit and text.isprintable():
        return repr(text)
    return "(long or unprintable name)"


def harness_spec(harness):
    if not (isinstance(harness, str) and HARNESS_NAME_RE.match(harness) and harness in HARNESSES):
        raise InstallError("unknown harness %s (known: %s)"
                           % (shown_text(harness, 32), ", ".join(sorted(HARNESSES))))
    return HARNESSES[harness]


def check_harness_dirs(module):
    """Every `harness/<name>/` of a module must be a real directory of a known harness."""
    top = os.path.join(module["path"], "harness")
    if not os.path.lexists(top):
        return
    if os.path.islink(top) or not os.path.isdir(top):
        raise InstallError("module %s: harness is a symlink or not a directory" % module["name"])
    for entry in sorted(os.listdir(top)):
        full = os.path.join(top, entry)
        if os.path.islink(full):
            raise InstallError("module %s: symlink not allowed in harness: %s"
                               % (module["name"], shown_text(entry)))
        if not (os.path.isdir(full) and HARNESS_NAME_RE.match(entry) and entry in HARNESSES):
            raise InstallError("module %s: harness directory %s is not a known harness (known: %s)"
                               % (module["name"], shown_text(entry, 32), ", ".join(sorted(HARNESSES))))


def harness_source_ok(rel, is_dir, spec, name):
    """The position rules of "Layout": which source entries a harness directory may hold."""
    parts = rel.split("/")
    if not safe_relpath(rel):
        raise InstallError("module %s: unsafe harness path %s" % (name, shown_text(rel)))
    if len(parts) > HARNESS_MAX_DEPTH:
        raise InstallError("module %s: harness path deeper than %d components: %s"
                           % (name, HARNESS_MAX_DEPTH, shown_text(rel)))
    top = parts[0]
    if top == HARNESS_JSON:
        ok = len(parts) == 1 and not is_dir
    elif top == HARNESS_ROOT_DIR:
        ok = (len(parts) == 1 and is_dir) or (
            len(parts) == 2 and not is_dir and parts[1] in spec["root_files"])
    elif top in spec["entries"]:
        ok = (len(parts) > 1 or is_dir == (not top.endswith(".toml")))
    else:
        ok = False
    if not ok:
        raise InstallError("module %s: harness entry %s is not allowed" % (name, shown_text(rel)))


def installed_harness_path(rel, spec):
    parts = rel.split("/")
    if parts[0] == HARNESS_ROOT_DIR:
        return "/".join(parts[1:])
    return spec["root"] + "/" + rel


def frontmatter_name(text):
    lines = text.split("\n")
    if not lines or lines[0] != "---":
        return None
    for line in lines[1:]:
        if line == "---":
            return None
        if line.startswith("name:"):
            return line[5:].strip() or None
    return None


def harness_unit(installed, spec):
    """(unit path, primary file path or None, default name) for an installed harness path, or None."""
    prefix = spec["root"] + "/"
    if not installed.startswith(prefix):
        return None
    parts = installed[len(prefix):].split("/")
    kind = parts[0]
    if kind == "skills" and len(parts) >= 2:
        if len(parts) == 2:  # a loose file in skills/
            return prefix + "/".join(parts), prefix + "/".join(parts), parts[1].rsplit(".", 1)[0]
        unit = prefix + "skills/" + parts[1]
        return unit, unit + "/SKILL.md", parts[1]
    if kind in ("agents", "commands") and len(parts) >= 2:
        return installed, installed, parts[-1].rsplit(".", 1)[0]
    return None


def read_harness_tree(module, harness, reserved=frozenset(), budget=None):
    """Read and check a built-in module's `harness/<harness>/` tree.

    Returns ({installed path: bytes}, {unit path: name}). The walk counts and
    stats first and reads no file until every count, depth, shape and size
    limit has passed. `reserved` holds folded installed paths that `base/` and
    module `files/` ship; `budget` counts the files and bytes of a whole run.
    """
    spec = harness_spec(harness)
    check_harness_dirs(module)
    name = module["name"]
    source = os.path.join(module["path"], "harness", harness)
    if not os.path.lexists(source):
        return {}, {}
    found = []  # (source rel, full path)
    total = 0
    stack = [("", source)]
    while stack:
        rel_dir, full_dir = stack.pop()
        with os.scandir(full_dir) as scan:
            names = []
            for entry in scan:
                names.append(entry.name)
                if len(names) > HARNESS_MAX_DIR_ENTRIES:
                    raise InstallError("module %s: more than %d entries in a harness directory"
                                       % (name, HARNESS_MAX_DIR_ENTRIES))
        for entry_name in sorted(names):
            rel = rel_dir + "/" + entry_name if rel_dir else entry_name
            full = os.path.join(full_dir, entry_name)
            info = os.lstat(full)
            if stat.S_ISLNK(info.st_mode):
                raise InstallError("module %s: symlink not allowed in harness: %s"
                                   % (name, shown_text(rel)))
            if stat.S_ISDIR(info.st_mode):
                harness_source_ok(rel, True, spec, name)
                stack.append((rel, full))
            elif stat.S_ISREG(info.st_mode):
                harness_source_ok(rel, False, spec, name)
                if len(found) >= HARNESS_MAX_FILES:
                    raise InstallError("module %s: more than %d harness files"
                                       % (name, HARNESS_MAX_FILES))
                if info.st_size > HARNESS_MAX_FILE_BYTES:
                    raise InstallError("module %s: harness file over %d KiB: %s"
                                       % (name, HARNESS_MAX_FILE_BYTES // 1024, shown_text(rel)))
                total += info.st_size
                if budget is not None:
                    budget.add(info.st_size)
                if total > HARNESS_MAX_TREE_BYTES:
                    raise InstallError("module %s: harness tree over %d MiB"
                                       % (name, HARNESS_MAX_TREE_BYTES // (1024 * 1024)))
                found.append((rel, full))
            else:
                raise InstallError("module %s: not a regular file in harness: %s"
                                   % (name, shown_text(rel)))
    contents = {}
    for rel, full in found:
        data = read_regular(full, HARNESS_MAX_FILE_BYTES)
        if not is_text(data):
            raise InstallError("module %s: harness file is not UTF-8 text without NUL: %s"
                               % (name, shown_text(rel)))
        text = data.decode("utf-8")
        if any(marker in text for marker in FRAGMENT_FORBIDDEN):
            raise InstallError("module %s: harness file holds a slot or block marker: %s"
                               % (name, shown_text(rel)))
        contents[rel] = data
    if HARNESS_JSON in contents:
        check_harness_json(contents[HARNESS_JSON], contents, name)
    installed = {}
    for rel, data in contents.items():
        if rel != HARNESS_JSON:
            installed[installed_harness_path(rel, spec)] = data
    for path in installed:
        if len(path) > HARNESS_KEY_MAX:
            raise InstallError("module %s: installed harness path over %d characters: %s"
                               % (name, HARNESS_KEY_MAX, shown_text(path)))
    check_unique(installed)
    for path in installed:
        if fold(path) in reserved:
            raise InstallError("module %s: harness file %s is also shipped by base/ or a module's "
                               "files/" % (name, shown_text(path)))
    units = {}
    names = {}
    for path in sorted(installed):
        unit = harness_unit(path, spec)
        if unit is None or unit[0] in units:
            continue
        unit_path, primary, default = unit
        value = default
        if primary in installed:
            value = frontmatter_name(installed[primary].decode("utf-8")) or default
        if fold(value) in names:
            raise InstallError("module %s: two harness units are named %s"
                               % (name, shown_text(value)))
        names[fold(value)] = unit_path
        units[unit_path] = value
    return installed, units


class RunBudget:
    """Files and bytes of harness trees read in one run, across modules."""

    def __init__(self):
        self.files = 0
        self.size = 0

    def add(self, size):
        self.files += 1
        self.size += size
        if self.files > HARNESS_RUN_FILES:
            raise InstallError("more than %d harness files in one run" % HARNESS_RUN_FILES)
        if self.size > HARNESS_RUN_BYTES:
            raise InstallError("more than %d MiB of harness files in one run"
                               % (HARNESS_RUN_BYTES // (1024 * 1024)))


def reserved_paths(modules, names):
    """Folded installed paths that `base/` and the `files/` of built-in `names` ship."""
    reserved = {fold(rel) for rel in collect_tree(BASE_DIR)}
    for name in names:
        if name in modules and not modules[name].get("external"):
            reserved |= {fold(rel) for rel in
                         collect_tree(os.path.join(modules[name]["path"], "files"))}
    return reserved


def harness_sha(data):
    return hashlib.sha256(data).hexdigest()


def substitute_harness(files, project_name):
    """The ordinary placeholders, but only for a name conservative enough for an approved file."""
    uses = any(NAME_PLACEHOLDER in data or ID_PLACEHOLDER in data for data in files.values())
    if uses and not HARNESS_PROJECT_NAME_RE.match(project_name):
        raise InstallError("project name %s cannot be written into harness files; "
                           "use letters, digits, '.', '_', '-' and spaces (pass --name)"
                           % shown_text(project_name))
    substitute(files, project_name)


def check_module_harness_dirs(names, modules):
    """A module's `harness/` entries must be sound whenever the module is used, with or without a harness."""
    for name in names:
        if name in modules and not modules[name].get("external"):
            check_harness_dirs(modules[name])


def prepare_harness(names, modules, harness, project_name, installed=()):
    """Read, check and substitute the harness tree of each built-in module in `names`.

    `installed` are the project's other modules; their `files/` are reserved too.
    """
    builtin = [n for n in names if not modules[n].get("external")]
    reserved = reserved_paths(modules, set(builtin) | set(installed))
    budget = RunBudget()
    trees = {}
    for name in builtin:
        files, units = read_harness_tree(modules[name], harness, reserved, budget)
        substitute_harness(files, project_name)
        for path, data in files.items():
            if any(marker.encode() in data for marker in FRAGMENT_FORBIDDEN):
                raise InstallError("module %s: harness file holds a slot or block marker after "
                                   "substitution: %s" % (name, shown_text(path)))
        trees[name] = (files, units)
    return trees


class HarnessPlan:
    def __init__(self, record):
        self.writes = {}
        self.record = record
        self.conflicts = []
        self.adopted = []


def plan_harness(trees, harness, existing, record, project=None):
    """Decide what the run writes and records (specification, "Collisions").

    `trees` maps each module in the run to (files, units); `existing` is the
    project scan; `record` the manifest's `harness_files`. Nothing is written
    here. Two suppliers in this run that disagree fail the run.
    """
    spec = HARNESSES[harness]
    plan = HarnessPlan({path: dict(entry) for path, entry in record.items()})
    supply = {}
    unit_trees = {}
    run_names = {}
    for module in sorted(trees):
        files, units = trees[module]
        for path, data in files.items():
            supply.setdefault(path, {})[module] = data
            unit = harness_unit(path, spec)
            if unit:
                unit_trees.setdefault(unit[0], {}).setdefault(module, {})[path] = data
        for unit, value in units.items():
            run_names.setdefault(fold(value), set()).add(unit)
    check_unique(sorted(supply))
    for path, by in sorted(supply.items()):
        if len(set(by.values())) > 1:
            raise InstallError("%s is supplied with different content by %s"
                               % (path, ", ".join(sorted(by))))
    for unit, by in sorted(unit_trees.items()):
        shapes = list(by.values())
        if any(shape != shapes[0] for shape in shapes):
            raise InstallError("%s is supplied as different trees by %s"
                               % (unit, ", ".join(sorted(by))))
    for key, units in sorted(run_names.items()):
        if len(units) > 1:
            raise InstallError("two harness units are named %s: %s"
                               % (shown_text(key), ", ".join(sorted(units))))
    taken = {}
    for path, data in existing.items():
        unit = harness_unit(path, spec)
        if unit and path == unit[1]:
            value = frontmatter_name(data.decode("utf-8", "replace")) or unit[2]
            taken[fold(value)] = unit[0]
    folded = {}
    for path in existing:
        folded.setdefault(fold(path), path)
    recorded_fold = {fold(key): key for key in plan.record}
    action = {}
    for path, by in sorted(supply.items()):
        data = next(iter(by.values()))
        suppliers = sorted(by)
        entry = plan.record.get(path)
        real = folded.get(fold(path))
        stale = recorded_fold.get(fold(path))
        if real is not None and real != path:
            action[path] = ("conflict", "same as %s after case and Unicode folding" % shown_text(real))
        elif stale is not None and stale != path:
            action[path] = ("conflict", "same as the recorded path %s after case and Unicode "
                                        "folding" % shown_text(stale))
        elif path in existing:
            if existing[path] == data:
                action[path] = ("adopt", None)
            elif (entry and harness_sha(existing[path]) == entry["sha256"]
                  and set(entry["modules"]) <= set(by)):
                action[path] = ("replace", None)
            else:
                action[path] = ("conflict", "differs from the module's file; not overwriting")
        elif project is not None and os.path.lexists(os.path.join(project, *path.split("/"))):
            action[path] = ("conflict", "exists and is not a regular file")
        else:
            action[path] = ("write", None)
    bad = set()
    for module in trees:
        for unit, value in trees[module][1].items():
            other = taken.get(fold(value))
            if other is not None and other != unit:
                bad.add(unit)
                plan.conflicts.append((unit, "name %s is already used by %s" % (shown_text(value), other)))
    for path, (kind, why) in action.items():
        if kind == "conflict":
            unit = harness_unit(path, spec)
            bad.add(unit[0] if unit else path)
            plan.conflicts.append((path, why))
    for path, (kind, _) in sorted(action.items()):
        unit = harness_unit(path, spec)
        if kind == "conflict" or (unit and unit[0] in bad):
            continue
        data = next(iter(supply[path].values()))
        suppliers = sorted(supply[path])
        entry = plan.record.get(path)
        if kind == "adopt":
            plan.adopted.append(path)
        else:
            plan.writes[path] = data
        plan.record[path] = {
            "sha256": harness_sha(data),
            "modules": sorted(set(entry["modules"] if entry else ()) | set(suppliers)),
        }
    return plan


def report_harness(out, plan, harness, trees):
    for module in sorted(trees):
        if not trees[module][0]:
            out("  %s: no %s files" % (module, harness))
    for path, why in plan.conflicts:
        out("  conflict %s (%s)" % (path, why))
    if plan.conflicts:
        out("  harness: %d conflict(s); those files were not written or recorded" % len(plan.conflicts))


def check_harness_json(data, contents, name):
    def bad(why):
        return InstallError("module %s: %s %s" % (name, HARNESS_JSON, why))

    if len(data) > HARNESS_JSON_MAX:
        raise bad("is over %d KiB" % (HARNESS_JSON_MAX // 1024))
    try:
        value = json.loads(data.decode("utf-8"))
    except (ValueError, RecursionError):
        raise bad("is not valid JSON")
    if not isinstance(value, dict) or not set(value) <= {"roles"}:
        raise bad("must be an object with only a roles key")
    roles = value.get("roles", {})
    if not isinstance(roles, dict) or len(roles) > HARNESS_ROLES_MAX:
        raise bad("roles must be an object of at most %d entries" % HARNESS_ROLES_MAX)
    for role, target in roles.items():
        if not ROLE_RE.match(role):
            raise bad("has an invalid role id")
        if not (isinstance(target, str) and safe_relpath(target) and target in contents
                and target != HARNESS_JSON):
            raise bad("maps a role to a file that is not in the harness directory")


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


def assemble(module_names, modules, base_dir=None):
    """Build the output tree {relpath: bytes} for base plus the given modules."""
    tree = collect_tree(base_dir or BASE_DIR)
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


BLOCK_RE = re.compile(
    r"^(?P<open><!-- |# )(?P<kind>BEGIN|END) module:(?P<module>[a-z0-9][a-z0-9_-]*) "
    r"slot:(?P<slot>[a-z0-9-]+)(?P<close> -->)?\Z"
)


def strip_blocks(text):
    """Remove every module block; return (text, {(module, slot): body}).

    The inverse of `apply_slots`: the blank line that may follow a block goes
    with it, whether or not the body still starts with a heading. Raises ValueError on unbalanced, mismatched, or
    duplicate blocks.
    """
    out = []
    stack = []
    blocks = {}
    drop_blank = False
    for line in text.split("\n"):
        match = BLOCK_RE.match(line)
        if match and (match.group("open") == "<!-- ") != (match.group("close") is not None):
            match = None
        if not match:
            if not (drop_blank and not line.strip()):
                out.append(line)
            drop_blank = False
            continue
        key = (match.group("module"), match.group("slot"))
        drop_blank = False
        if match.group("kind") == "BEGIN":
            stack.append((key, len(out)))
            continue
        if not stack or stack[-1][0] != key or key in blocks:
            raise ValueError("malformed block markers: unbalanced or duplicate %s:%s" % key)
        _, start = stack.pop()
        body = out[start:]
        del out[start:]
        blocks[key] = "\n".join(body)
        drop_blank = True
    if stack:
        raise ValueError("malformed block markers: %s:%s has no END line" % stack[-1][0])
    return "\n".join(out), blocks


def _content(text):
    return [line for line in text.split("\n") if line.strip()]


def refresh_blocks(text, order, fresh, relpath, drop=(), expect=None, keep=False):
    """Return (text, blocks, used) with module blocks re-rendered from `fresh`.

    `fresh` maps module -> {slot: fragment}; other blocks keep their recorded
    body, and modules in `drop` lose theirs. With `keep`, a block already in the
    text keeps its body and `fresh` only fills the ones that are missing. Refuses (ValueError) a layout that
    does not render back to itself, a kept block with no place left, or a
    dropped block whose body differs from `expect[module][slot]` when given.
    """
    stripped, blocks = strip_blocks(text)
    recorded = {}
    for (module, slot), body in blocks.items():
        recorded.setdefault(module, {})[slot] = body

    def render(fragments):
        names = list(order) + sorted(m for m in fragments if m not in order)
        return apply_slots(stripped, names, fragments, relpath)

    same, used, _ = render(recorded)
    if _content(same) != _content(text) or set(blocks) - used:
        raise ValueError("block layout differs from the installer's")
    for (module, slot), body in sorted(blocks.items()):
        wanted = (expect or {}).get(module, {}).get(slot)
        if module in drop and wanted is not None and _content(body) != _content(wanted):
            raise ValueError(
                "%s:%s differs from the module's fragment (edited, or the template "
                "changed: run --update first)" % (module, slot)
            )
    merged = {module: dict(slots) for module, slots in recorded.items()}
    for module, slots in fresh.items():
        have = merged.setdefault(module, {})
        for slot, fragment in slots.items():
            if not keep or slot not in have:
                have[slot] = fragment
    for module in drop:
        merged.pop(module, None)
    new_text, used, _ = render(merged)
    if drop:
        lost = {key for key in blocks if key[0] not in drop} - used
        if lost:
            raise ValueError("%s:%s would lose its slot marker" % min(lost))
    return new_text, blocks, used


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


class NoBase(Exception):
    """The template as installed cannot be rebuilt; the message says why."""


def git_bytes(args, data=None):
    env = dict(git_env(), GIT_NO_LAZY_FETCH="1")
    try:
        result = subprocess.run(
            ["git", "--no-replace-objects"] + GIT_SAFE + args, cwd=ROOT, env=env, input=data,
            capture_output=True, check=False, timeout=GIT_TIMEOUT,
        )
    except subprocess.TimeoutExpired:
        raise NoBase("git did not finish in %d seconds" % GIT_TIMEOUT)
    except OSError as exc:
        raise NoBase("git cannot run: %s" % exc)
    if result.returncode:
        raise NoBase("git %s failed" % args[0])
    return result.stdout


def verified_commit(sha):
    """Return `sha` if it names a commit in the template checkout, else raise NoBase."""
    if not isinstance(sha, str) or not SHA_RE.match(sha):
        raise NoBase("the recorded commit is not a commit id")
    try:
        top = git_bytes(["rev-parse", "--show-toplevel"]).strip().decode("utf-8", "replace")
    except NoBase:
        top = ""
    if not top or os.path.realpath(top) != os.path.realpath(ROOT):
        raise NoBase("the installer is not at the top of a git checkout")
    try:
        found = git_bytes(["rev-parse", "--verify", "--quiet", sha + "^{commit}"])
    except NoBase:
        found = b""
    if found.strip().decode("ascii", "replace") != sha:
        raise NoBase("commit %s is not a commit in this template checkout" % sha)
    return sha


def read_template_at(sha):
    """Map path -> bytes of `base/` and `modules/` at a commit; regular files only.

    Read with `ls-tree` and `cat-file`, never `archive`, so export attributes in
    the history cannot rewrite or drop files.
    """
    listing = git_bytes(["ls-tree", "-r", "-z", sha, "--", "base", "modules"])
    wanted = []
    for entry in listing.split(b"\0"):
        if not entry:
            continue
        meta, _, raw = entry.partition(b"\t")
        try:
            mode, kind, obj = meta.split(b" ")
            rel = raw.decode("utf-8")
        except ValueError:
            raise NoBase("the template tree has an entry that cannot be read")
        parts = rel.split("/")
        if (kind != b"blob" or mode not in (b"100644", b"100755") or not OBJECT_RE.match(obj)
                or parts[0] not in ("base", "modules") or "" in parts or ".." in parts
                or "." in parts or any(part.casefold() == ".git" for part in parts)):
            raise NoBase("the template tree has an entry that is not a plain file: %s" % rel)
        wanted.append((rel, obj))
    if len(wanted) > BASE_MAX_FILES:
        raise NoBase("the template tree has too many files")
    request = b"".join(obj + b"\n" for _, obj in wanted)
    sizes = git_bytes(["cat-file", "--batch-check"], request).split(b"\n")
    total = 0
    for (rel, obj), line in zip(wanted, sizes):
        fields = line.split(b" ")
        if len(fields) != 3 or fields[0] != obj or fields[1] != b"blob" or not fields[2].isdigit():
            raise NoBase("the template tree has an object that cannot be read: %s" % rel)
        if int(fields[2]) > MAX_FILE_BYTES:
            raise NoBase("the template tree has a file that is too large: %s" % rel)
        total += int(fields[2])
    if len(sizes) < len(wanted) or total > BASE_MAX_BYTES:
        raise NoBase("the template tree is too large")
    blobs = git_bytes(["cat-file", "--batch"], request)
    if len(blobs) > BASE_MAX_BYTES:
        raise NoBase("the template tree is too large")
    files = {}
    at = 0
    for rel, obj in wanted:
        end = blobs.find(b"\n", at)
        header = blobs[at:end].split(b" ") if end >= 0 else []
        if len(header) != 3 or header[0] != obj or header[1] != b"blob" or not header[2].isdigit():
            raise NoBase("the template tree has an object that cannot be read: %s" % rel)
        size = int(header[2])
        if size > MAX_FILE_BYTES or end + 1 + size > len(blobs):
            raise NoBase("the template tree has a file that is too large: %s" % rel)
        files[rel] = blobs[end + 1:end + 1 + size]
        at = end + 1 + size + 1
    return files


def render_template_at(commit, module_names, name):
    """Rebuild the tree `--new` would have written at `commit` for these modules.

    Only the commit's own `base/` and `modules/` are used; from the project only
    the module names and the project name come in.
    """
    files = read_template_at(verified_commit(commit))
    with tempfile.TemporaryDirectory(prefix="template-base-") as tmp:
        try:
            for rel, data in files.items():
                dest = os.path.join(tmp, *rel.split("/"))
                os.makedirs(os.path.dirname(dest), exist_ok=True)
                fd = os.open(dest, os.O_WRONLY | os.O_CREAT | os.O_EXCL
                             | getattr(os, "O_NOFOLLOW", 0), 0o600)
                with os.fdopen(fd, "wb") as handle:
                    handle.write(data)
        except OSError as exc:
            raise NoBase("the template cannot be unpacked: %s" % (exc.strerror or exc))
        try:
            modules = load_modules(os.path.join(tmp, "modules"))
            for module in module_names:
                if module not in modules:
                    raise NoBase("module %s is not in commit %s" % (module, commit[:7]))
            tree = assemble(resolve(module_names, modules), modules, os.path.join(tmp, "base"))
            substitute(tree, name)
        except (InstallError, ValueError, TypeError, KeyError, AttributeError) as exc:
            raise NoBase("it cannot be rebuilt: %s" % exc)
    return tree


def block_problem(current, base_text, externals):
    """Why a project file's module blocks rule out using `base_text` as its base, or None."""
    try:
        _, have = strip_blocks(current)
        _, then = strip_blocks(base_text)
    except ValueError:
        return "its block markers are malformed"
    for module, slot in sorted(have):
        if module in externals:
            return "it holds a block of the external module %s" % module
        if (module, slot) not in then:
            return "block %s:%s is not in the installed template" % (module, slot)
    return None


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


def parse_with(values):
    """Names from --with values or a prompt answer: spaces and commas both separate."""
    names = []
    for value in values:
        names += [part.strip() for part in value.split(",") if part.strip()]
    return names


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


def can_delete_safely():
    return (
        os.unlink in os.supports_dir_fd and os.rmdir in os.supports_dir_fd
        and os.stat in os.supports_dir_fd and os.stat in os.supports_follow_symlinks
        and hasattr(os, "O_NOFOLLOW") and hasattr(os, "O_DIRECTORY")
    )


def delete_files(root, rels):
    """Unlink regular files below `root`, then rmdir parents left empty.

    Every directory is opened relative to its parent's descriptor without
    following symlinks, so a parent swapped for a symlink after the path check
    fails to open instead of redirecting the delete.
    """
    flags = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW
    for rel in rels:
        parts = rel.split("/")
        fds = []
        try:
            fds.append(os.open(root, flags))
            for part in parts[:-1]:
                fds.append(os.open(part, flags, dir_fd=fds[-1]))
            info = os.stat(parts[-1], dir_fd=fds[-1], follow_symlinks=False)
            if not stat.S_ISREG(info.st_mode):
                raise InstallError("not a regular file: %s" % rel)
            os.unlink(parts[-1], dir_fd=fds[-1])
            for depth in range(len(parts) - 1, 0, -1):
                try:
                    os.rmdir(parts[depth - 1], dir_fd=fds[depth - 1])
                except OSError:
                    break
        except OSError as exc:
            raise InstallError("cannot delete %s: %s" % (rel, exc.strerror or exc))
        finally:
            for fd in fds:
                os.close(fd)


def write_tree(target, tree, delete=(), private=()):
    """Write every file via a temporary sibling and rename, manifest last.

    A rename replaces the directory entry, so a hardlinked file's other names
    are never written through; if any temporary file cannot be created
    nothing has been replaced yet. Files in `delete` are removed after the
    other writes and before the manifest, so an interrupted run leaves a
    manifest that still lists what a rerun must finish.
    """
    check_write_paths(target, list(tree) + list(delete))
    if delete and not can_delete_safely():
        raise InstallError("this platform cannot delete files safely")
    order = sorted(tree, key=lambda rel: (rel == MANIFEST, rel))
    staged = []
    try:
        for rel in order:
            dest = os.path.join(target, *rel.split("/"))
            os.makedirs(os.path.dirname(dest), exist_ok=True)
            temp = "%s.install-%d.tmp" % (dest, os.getpid())
            flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0)
            fd = os.open(temp, flags, 0o644 if rel in private else 0o666)
            staged.append((temp, dest))
            with os.fdopen(fd, "wb") as handle:
                handle.write(tree[rel])
            if rel not in private and os.path.exists(dest):
                os.chmod(temp, stat.S_IMODE(os.lstat(dest).st_mode))
        manifest_dest = os.path.join(target, MANIFEST)
        pending = list(delete)
        for temp, dest in staged:
            if pending and dest == manifest_dest:
                delete_files(target, pending)
                pending = []
            os.replace(temp, dest)
        staged = []
        if pending:
            delete_files(target, pending)
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


def safe_relpath(rel):
    if not isinstance(rel, str) or not rel or len(rel) > 512 or not rel.isprintable():
        return False
    parts = rel.split("/")
    # Windows ignores trailing dots and spaces and reads `\` and `:` as separators or
    # drive letters, so a path a consumer joins later cannot slip through.
    return not (rel.startswith("/") or "\\" in rel or ":" in rel
                or "" in parts or "." in parts or ".." in parts
                or any(part.rstrip(" .").casefold() == ".git" for part in parts))


def info_entry_ok(name, entry, manifest):
    """One `module_info` entry: a built-in module's, or an external one that has a `store`."""
    if not (isinstance(name, str) and isinstance(entry, dict) and entry):
        return False
    if NAME_RE.match(name) and name in manifest["modules"]:
        allowed = set(INFO_KEYS)
    elif EXT_NAME_RE.match(name) and name in manifest.get("external_modules", {}):
        allowed = set(INFO_KEYS) | {"store"}
        if not store_ok(entry.get("store")):
            return False
    else:
        return False
    declared = {k: v for k, v in entry.items() if k in INFO_KEYS}
    return set(entry) <= allowed and module_info_problem(declared) is None


def validate_optional_keys(manifest, builtin):
    """Check the keys older manifests lack: project_name, module_commits, file_bases, module_info."""
    name = manifest.get("project_name")
    commits = manifest.get("module_commits")
    bases = manifest.get("file_bases")
    ok = "project_name" not in manifest or (isinstance(name, str) and 0 < len(name) <= 200
                                            and name.isprintable())
    if "module_commits" in manifest:
        ok = ok and isinstance(commits, dict) and len(commits) <= MANIFEST_MAP_MAX and all(
            isinstance(k, str) and NAME_RE.match(k) and (v is None or (
                isinstance(v, str) and SHA_RE.match(v)))
            for k, v in commits.items())
    if "file_bases" in manifest:
        ok = ok and isinstance(bases, dict) and len(bases) <= MANIFEST_MAP_MAX and all(
            safe_relpath(k) and (v is None or (isinstance(v, str) and SHA_RE.match(v)))
            for k, v in bases.items())
    if "module_info" in manifest:
        info = manifest["module_info"]
        ok = ok and isinstance(info, dict) and len(info) <= MANIFEST_MAP_MAX and all(
            info_entry_ok(k, v, manifest) for k, v in info.items())
    if not ok:
        raise InstallError("%s has a malformed project_name, module_commits, file_bases or "
                           "module_info entry" % MANIFEST)


def harness_destination_ok(key, spec):
    """Is `key` a path the recorded harness can install to (specification, "Manifest")?"""
    if key in spec["root_files"]:
        return True
    prefix = spec["root"] + "/"
    if not key.startswith(prefix):
        return False
    parts = key[len(prefix):].split("/")
    if parts[0] not in spec["entries"]:
        return False
    return len(parts) == 1 if parts[0].endswith(".toml") else len(parts) >= 2


def validate_harness_record(manifest):
    """`harness` and `harness_files` go with schema 2 and with nothing else."""
    schema = manifest.get("schema")
    has = [key in manifest for key in ("harness", "harness_files")]
    if schema == SCHEMA and any(has):
        raise InstallError("%s has a harness record but schema %d" % (MANIFEST, SCHEMA))
    if schema == HARNESS_SCHEMA and not all(has):
        raise InstallError("%s has schema %d but no harness record" % (MANIFEST, HARNESS_SCHEMA))
    if schema == SCHEMA:
        return
    harness, record = manifest["harness"], manifest["harness_files"]
    if not (isinstance(harness, str) and harness in HARNESSES):
        raise InstallError("%s has an unknown harness" % MANIFEST)
    spec = HARNESSES[harness]
    ok = isinstance(record, dict) and len(record) <= HARNESS_FILES_MAX
    known = set(manifest.get("modules", [])) | set(manifest.get("external_modules", {}))
    seen = set()
    for key, entry in (record.items() if ok else ()):
        modules = entry.get("modules") if isinstance(entry, dict) else None
        sha = entry.get("sha256") if isinstance(entry, dict) else None
        ok = (
            ok
            and isinstance(key, str) and len(key) <= HARNESS_KEY_MAX and safe_relpath(key)
            and key.casefold() != MANIFEST.casefold()
            and harness_destination_ok(key, spec) and fold(key) not in seen
            and isinstance(entry, dict) and set(entry) == {"sha256", "modules"}
            and isinstance(sha, str) and DIGEST_RE.match(sha)
            and isinstance(modules, list) and modules and modules == sorted(set(
                m for m in modules if isinstance(m, str)))
            and all(EXT_NAME_RE.match(m) and m in known for m in modules)
        )
        seen.add(fold(key) if isinstance(key, str) else key)
    if ok and len(json.dumps(record)) > HARNESS_RECORD_MAX_BYTES:
        ok = False
    if not ok:
        raise InstallError("%s has a malformed harness or harness_files entry" % MANIFEST)


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
        or isinstance(schema, bool) or not isinstance(schema, int)
        or schema not in (SCHEMA, HARNESS_SCHEMA)
        or not isinstance(modules, list)
        or not all(isinstance(m, str) and NAME_RE.match(m) for m in modules)
    ):
        raise InstallError(
            "%s is malformed (expected an object with schema %d and a list of module names)"
            % (MANIFEST, SCHEMA)
        )
    if "external_modules" in manifest:
        validate_external_modules(manifest["external_modules"], builtin)
    validate_optional_keys(manifest, builtin)
    validate_harness_record(manifest)
    return manifest


def external_record(meta):
    return {"module_format": meta["module_format"], "digest": meta["digest"]}


def module_info_for(modules, names):
    """The type, paths and data each named module declares, if any.

    An external module always has an entry, because it carries the `store`
    location the user gave.
    """
    info = {}
    for name in sorted(names):
        meta = modules[name]
        declared = {k: meta[k] for k in INFO_KEYS if k in meta}
        if meta.get("external"):
            declared["store"] = meta["store"]
        if declared:
            info[name] = declared
    return info


def check_record_limits(record):
    """The load-time limits on `harness_files`, enforced when writing too."""
    if (len(record) > HARNESS_FILES_MAX
            or any(len(key) > HARNESS_KEY_MAX for key in record)
            or len(json.dumps(record)) > HARNESS_RECORD_MAX_BYTES):
        raise InstallError("the harness record would exceed its limits (%d entries, %d-character "
                           "paths, %d KiB); nothing was written"
                           % (HARNESS_FILES_MAX, HARNESS_KEY_MAX, HARNESS_RECORD_MAX_BYTES // 1024))


def encode_manifest(manifest):
    """Serialize a manifest, refusing one the next run could not read back."""
    if isinstance(manifest.get("harness_files"), dict):
        check_record_limits(manifest["harness_files"])
    if "harness" in manifest or "harness_files" in manifest:
        validate_harness_record(manifest)
    data = (json.dumps(manifest, indent=2, sort_keys=True) + "\n").encode("utf-8")
    if len(data) > MAX_MANIFEST_BYTES:
        raise InstallError("%s would exceed %d bytes; nothing was written"
                           % (MANIFEST, MAX_MANIFEST_BYTES))
    return data


def manifest_bytes(module_names, commit, dirty, externals=None, project_name=None,
                   module_info=None, harness=None, harness_files=None):
    payload = {
        "schema": HARNESS_SCHEMA if harness else SCHEMA,
        "template_commit": commit,
        "template_dirty": dirty,
        "modules": sorted(module_names),
    }
    if externals:
        payload["external_modules"] = externals
    if project_name:
        payload["project_name"] = project_name
    if module_info:
        payload["module_info"] = module_info
    if harness:
        payload["harness"] = harness
        payload["harness_files"] = harness_files or {}
    return encode_manifest(payload)


def choose_harness(option, recorded, introduce):
    """The project's harness for this run, from `--harness` and the manifest (specification, "Selection")."""
    if option is not None:
        harness_spec(option)
        if recorded is not None and option != recorded:
            raise InstallError("this project's harness is %s; it cannot be changed (create a "
                               "new project)" % recorded)
        if recorded is None and not introduce:
            raise InstallError("--update never introduces a harness; use --add --harness %s "
                               "once" % option)
    return recorded or option


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
            "Modules (space or comma separated, blank for none; available: %s): "
            % ", ".join(sorted(modules))
        )
        selected = parse_with(answer.split())
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
    harness_plan, trees = None, {}
    check_module_harness_dirs(names, modules)
    if args.harness is not None:
        trees = prepare_harness(names, modules, args.harness, name)
        harness_plan = plan_harness(trees, args.harness, {}, {})
        tree.update(harness_plan.writes)
    identity = None
    if not args.dry_run:
        identity = resolve_identity(args, interactive)
    commit, dirty = template_state()
    tree[MANIFEST] = manifest_bytes(
        [n for n in names if n in builtin], commit, dirty,
        {n: external_record(modules[n]) for n in names if n in externals},
        project_name=name,
        module_info=module_info_for(modules, names),
        harness=args.harness,
        harness_files=harness_plan.record if harness_plan else None,
    )

    out("Project: %s" % name)
    out("Target:  %s" % target)
    out("Modules: %s" % (", ".join(names) or "none"))
    pulled = sorted(set(names) - set(selected))
    if pulled:
        out("Required modules added: %s" % ", ".join(pulled))
    if harness_plan:
        report_harness(out, harness_plan, args.harness, trees)
    if args.dry_run:
        for rel in sorted(tree):
            out("  would write %s" % rel)
        emit_hints(out, names, modules, True)
        out("Dry run: nothing written.")
        return 0

    os.makedirs(target, exist_ok=True)
    write_tree(target, tree, private=set(harness_plan.writes) if harness_plan else ())
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


def owned_paths(modules, names):
    """Casefolded paths the template ships: the base plus the files of `names`."""
    owned = {rel.casefold() for rel in collect_tree(BASE_DIR)}
    for name in names:
        if name in modules:
            owned |= {rel.casefold() for rel in
                      collect_tree(os.path.join(modules[name]["path"], "files"))}
    return owned


def cmd_add(args, out):
    modules = load_modules()
    project = os.path.abspath(args.dir)
    builtin = set(modules)
    manifest = load_manifest(project, builtin)
    installed = list(manifest["modules"])
    recorded = dict(manifest.get("external_modules", {}))
    harness = choose_harness(args.harness, manifest.get("harness"), introduce=True)
    activating = harness is not None and "harness" not in manifest
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
    if not new and not activating:
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
    harness_plan, trees = None, {}
    check_module_harness_dirs(new, modules)
    if harness:
        wanted_here = [n for n in wanted if n in modules and (activating or n in new)]
        trees = prepare_harness(wanted_here, modules, harness, project_name, installed=wanted)
        harness_plan = plan_harness(trees, harness, existing,
                                    manifest.get("harness_files", {}), project)
    existing.update(writes)
    owned = owned_paths(modules, [n for n in wanted if n not in externals])
    fragments = {name: modules[name]["slots"] for name in wanted}
    patched = dict()
    used = set()
    for rel, data in existing.items():
        if rel.casefold() not in owned:
            continue
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
    if harness_plan:
        writes.update(harness_plan.writes)
        manifest["schema"] = HARNESS_SCHEMA
        manifest["harness"] = harness
        manifest["harness_files"] = harness_plan.record
    commit, dirty = template_state()
    added = dict(manifest.get("module_commits", {}))
    for name in new:
        if name not in externals:
            added[name] = commit if commit and not dirty else None
    if added:
        manifest["module_commits"] = added
    manifest["modules"] = sorted(n for n in wanted if n not in externals)
    info = dict(manifest.get("module_info", {}))
    info.update(module_info_for(modules, new))
    if info:
        manifest["module_info"] = info
    for name in externals:
        recorded[name] = external_record(externals[name])
    if recorded:
        manifest["external_modules"] = recorded
    writes[MANIFEST] = encode_manifest(manifest)

    out("Adding modules: %s" % (", ".join(new) or "none"))
    if harness_plan:
        report_harness(out, harness_plan, harness, trees)
        if activating and recorded:
            out("  note: the harness files of external modules already installed (%s) were "
                "not read, so none were installed" % ", ".join(sorted(recorded)))
    private = set(harness_plan.writes) if harness_plan else ()
    if args.dry_run:
        for rel in sorted(writes):
            out("  would write %s" % rel)
        emit_hints(out, new, modules, True)
        out("Dry run: nothing written.")
        return 0
    write_tree(project, writes, private=private)
    for rel in sorted(writes):
        out("  wrote %s" % rel)
    emit_hints(out, new, modules, False)
    return 0


def load_update_externals(args, entries, recorded, project, builtin, notes):
    """Load the recorded external modules that `--update` should compare.

    Named modules (registered name or name=path) must load. Without names,
    every recorded module is looked up in the registry only, and one that is
    unregistered or fails verification is skipped with a note.
    """
    if entries:
        named = [(n, v) for n, v in entries if n in recorded]
        named, registered = registered_entries(args, named, builtin)
        return load_externals(named, project, builtin, registered)
    if not recorded:
        return {}
    try:
        stores = load_registry(registry_path(args.registry))
    except InstallError as exc:
        notes.append("external modules skipped: %s" % exc)
        return {}
    loaded = {}
    for name in sorted(recorded):
        if name not in stores:
            notes.append("%s skipped: not registered; name it as %s=PATH to update it" % (name, name))
            continue
        try:
            loaded.update(load_externals([(name, stores[name])], project, builtin, {name}))
        except InstallError as exc:
            notes.append("%s skipped: %s" % (name, exc))
    return loaded


def differs_from_template(current, shipped):
    """True when a project file differs from the template's file, ignoring module blocks."""
    if current == shipped:
        return False
    if not (is_text(current) and is_text(shipped)):
        return True
    try:
        stripped, _ = strip_blocks(current.decode("utf-8"))
    except ValueError:
        return True
    return _content(stripped) != _content(shipped.decode("utf-8"))


class BaseFinder:
    """Classify a differing file against the template as it was installed."""

    def __init__(self, manifest, project_name, externals):
        self.manifest = manifest
        self.names = list(manifest["modules"])
        self.project_name = project_name
        self.externals = externals
        self.trees = {}
        self.used = False

    def tree(self, commit):
        if commit not in self.trees:
            try:
                self.trees[commit] = render_template_at(commit, self.names, self.project_name)
            except NoBase as exc:
                self.trees[commit] = exc
        found = self.trees[commit]
        if isinstance(found, NoBase):
            raise found
        return found

    def classify(self, rel, current, shipped):
        """Return ("changed" | "unchanged", commit) or ("nobase", reason)."""
        bases = self.manifest.get("file_bases", {})
        commit = bases[rel] if rel in bases else self.manifest.get("template_commit")
        try:
            if rel in bases and commit is None:
                raise NoBase("no merge base was kept for it at the last update")
            if commit is None:
                raise NoBase("no template commit was recorded")
            if not isinstance(commit, str):
                raise NoBase("the recorded commit is not a commit id")
            if rel not in bases:
                if self.manifest.get("template_dirty"):
                    raise NoBase("it was installed from a modified template")
                for module, at in sorted(self.manifest.get("module_commits", {}).items()):
                    if at != commit:
                        raise NoBase("module %s was added at a different commit" % module)
            tree = self.tree(commit)
            self.used = True
            if rel not in tree:
                raise NoBase("the file did not exist at commit %s" % commit[:7])
            if current is not None and is_text(current) and is_text(tree[rel]):
                problem = block_problem(current.decode("utf-8"), tree[rel].decode("utf-8"),
                                        self.externals)
                if problem:
                    raise NoBase(problem)
            return ("changed" if differs_from_template(tree[rel], shipped) else "unchanged", commit)
        except NoBase as exc:
            return ("nobase", str(exc))


def merge_text(ours, base, theirs):
    """Three-way merge of text; the merged bytes, or None on a conflict or an error."""
    with tempfile.TemporaryDirectory(prefix="template-merge-") as tmp:
        paths = []
        for label, data in (("ours", ours), ("base", base), ("theirs", theirs)):
            path = os.path.join(tmp, label)
            fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL
                         | getattr(os, "O_NOFOLLOW", 0), 0o600)
            with os.fdopen(fd, "wb") as handle:
                handle.write(data)
            paths.append(path)
        try:
            result = subprocess.run(
                ["git"] + GIT_SAFE + ["merge-file", "-p", "-L", "ours", "-L", "base",
                                      "-L", "theirs"] + paths,
                cwd=tmp, env=git_env(), capture_output=True, check=False, timeout=GIT_TIMEOUT,
            )
        except (OSError, subprocess.TimeoutExpired):
            return None
    return result.stdout if result.returncode == 0 else None


def lost_block(ours, theirs):
    """(module, slot) of a block in `ours` that `theirs` lacks, or None."""
    try:
        _, have = strip_blocks(ours.decode("utf-8"))
        _, want = strip_blocks(theirs.decode("utf-8"))
    except (ValueError, UnicodeDecodeError):
        return None
    missing = sorted(set(have) - set(want))
    return missing[0] if missing else None


def merge_files(kept, outcome, bases, existing, writes, modules, present, project_name,
                name_recorded):
    """Merge the template's changes into the differing files `--update` kept.

    A file unmodified since install takes the new template text; a modified one
    is merged three-way when the edits do not overlap. A conflict, a file with
    no base, a non-text file, and a changed `docs/plans/next.md` that was edited
    are left byte-identical. Results are added to `writes`.
    """
    theirs_tree = None
    merged_now = {}
    for entry in kept:
        verb, rel = entry[0], entry[1]
        state = outcome.get(rel)
        if verb != "kept" or state is None or state[0] != "changed" or rel not in existing:
            continue
        if not name_recorded:
            raise InstallError(
                "--merge needs the project name, which %s does not record: pass --name" % MANIFEST
            )
        if theirs_tree is None:
            theirs_tree = assemble(resolve(present, modules), modules)
            substitute(theirs_tree, project_name)
        if rel not in theirs_tree:
            continue
        ours, base, theirs = existing[rel], bases.tree(state[1])[rel], theirs_tree[rel]
        lost = lost_block(ours, theirs)
        if lost:
            entry[2] += "; would drop the block %s:%s, left unchanged" % lost
            continue
        if ours == base:
            merged, verb, why = theirs, "updated", "unmodified since install; took the template's changes"
        elif rel == PLAN_FILE:
            continue
        elif is_text(ours) and is_text(base) and is_text(theirs):
            merged = merge_text(ours, base, theirs)
            if merged is None:
                entry[0], entry[2] = "conflict", ("your edits and the template's changes overlap; "
                                                   "left unchanged")
                continue
            verb, why = "merged", "template changes merged with yours"
        else:
            continue
        if merged != ours:
            writes[rel] = merged
        else:
            verb, why = "current", "already contains the template's changes"
        entry[0], entry[2] = verb, why
        merged_now[rel] = (entry, state)
        outcome[rel] = ("merged", state[1])
    return merged_now


def describe_base(result):
    status, value = result
    if status == "nobase":
        return "no merge base: %s" % value
    return "template %s since %s" % (status, value[:7])


def cmd_update(args, out):
    modules = load_modules()
    project = os.path.abspath(args.dir)
    builtin = set(modules)
    manifest = load_manifest(project, builtin)
    installed = list(manifest["modules"])
    recorded = dict(manifest.get("external_modules", {}))
    harness = choose_harness(args.harness, manifest.get("harness"), introduce=False)
    entries = parse_entries(args.update)
    for name, value in entries:
        if name in recorded:
            continue
        if name not in installed:
            raise InstallError("module %r is not installed in this project" % name)
        if value is not None:
            raise InstallError("%s is a built-in module; name=PATH is for external modules" % name)
        if name not in modules:
            raise InstallError("module %r is no longer provided by the template" % name)
    present = [n for n in installed if n in modules]
    notes = []
    if entries:
        targets = [n for n, _ in entries if n not in recorded]
    else:
        targets = present
        for name in installed:
            if name not in modules:
                notes.append("%s is no longer provided by the template; left as is" % name)
    externals = load_update_externals(args, entries, recorded, project, builtin, notes)
    changed = {
        name: meta for name, meta in externals.items()
        if external_record(meta) != recorded[name]
    }
    order = sorted(present, key=lambda n: (modules[n]["order"], n))
    name_recorded = bool(args.name or manifest.get("project_name"))
    project_name = require_printable(
        args.name or manifest.get("project_name") or os.path.basename(project.rstrip(os.sep)),
        "project name",
    )
    skipped = [] if args.skip_unsafe_entries else None
    existing = scan_project(project, skipped)
    if skipped:
        out("Skipped (not read, patched, or written through):")
        for rel, reason in sorted(skipped):
            out("  %s (%s)" % (rel, reason))

    writes = {}
    kept = []
    compared = set()
    for name in targets:
        files = collect_tree(os.path.join(modules[name]["path"], "files"))
        substitute(files, project_name)
        compared.update(files)
        for rel, data in sorted(files.items()):
            if rel in existing:
                if differs_from_template(existing[rel], data):
                    kept.append(["kept", rel, "differs from the module's file; not overwriting",
                                 existing[rel], data])
            elif os.path.lexists(os.path.join(project, *rel.split("/"))):
                kept.append(["kept", rel, "differs from the module's file; not overwriting",
                             None, data])
            else:
                writes[rel] = data
    base_files = collect_tree(BASE_DIR)
    substitute(base_files, project_name)
    compared.update(base_files)
    compared.difference_update(rel for rel, _ in skipped or ())
    for rel, data in sorted(base_files.items()):
        if rel in existing and differs_from_template(existing[rel], data):
            if rel == PLAN_FILE:
                kept.append(["kept", rel, "per-plan file; differs from the template, only an "
                                          "unmodified copy is updated", existing[rel], data])
            else:
                kept.append(["kept", rel, "differs from the template; not overwriting",
                             existing[rel], data])

    harness_plan, trees = None, {}
    check_module_harness_dirs(targets, modules)
    if harness:
        trees = prepare_harness(targets, modules, harness, project_name, installed=present)
        harness_plan = plan_harness(trees, harness, existing, manifest["harness_files"], project)
        writes.update(harness_plan.writes)

    bases = BaseFinder(manifest, project_name, set(recorded))
    outcome = {}
    for entry in kept:
        if entry[4] is not None:
            outcome[entry[1]] = bases.classify(entry[1], entry[3], entry[4])
            entry[2] += "; " + describe_base(outcome[entry[1]])
    if bases.used and not name_recorded:
        notes.append("project name assumed from the directory (not recorded in %s); "
                     "pass --name if it differs" % MANIFEST)
    merged_now = {}
    if args.merge:
        merged_now = merge_files(kept, outcome, bases, existing, writes, modules, present,
                                 project_name, name_recorded)

    files = dict(existing, **writes)
    fresh = {name: modules[name]["slots"] for name in targets}
    fresh.update({name: meta["slots"] for name, meta in changed.items()})
    wanted = {(n, s) for n in fresh for s in fresh[n]}
    owned = owned_paths(modules, present)
    placed = set()
    seen = set()
    for rel in sorted(files):
        data = files[rel]
        if not is_text(data) or not (b"@module-slot:" in data or b"BEGIN module:" in data):
            continue
        if rel.casefold() not in owned:
            kept.append(["skipped", rel, "project-created file with markers; not patched",
                         None, None])
            continue
        text = data.decode("utf-8")
        try:
            new_text, blocks, used = refresh_blocks(
                text, order, fresh, rel, keep=rel == PLAN_FILE
            )
        except (ValueError, InstallError) as exc:
            notes.append("%s: not updated (%s)" % (rel, exc))
            if rel in merged_now:
                entry, state = merged_now[rel]
                writes.pop(rel, None)
                outcome[rel] = state
                entry[0], entry[2] = "kept", "the merged text was rejected by the block check; left unchanged"
            continue
        placed |= used
        seen |= set(blocks)
        if new_text != text:
            writes[rel] = new_text.encode("utf-8")
    for module, slot in sorted(wanted - placed):
        notes.append("%s:%s has no slot marker in this project; add the marker line by hand"
                     % (module, slot))
    for module, slot in sorted(seen):
        if module in fresh and slot not in fresh[module]:
            notes.append("%s:%s is no longer a fragment of the module; block left in place"
                         % (module, slot))

    out("Updating modules: %s" % (", ".join(targets + sorted(changed)) or "none"))
    for verb, rel, why, _, _ in kept:
        out("  %s %s (%s)" % (verb, rel, why))
    for note in notes:
        out("  note: %s" % note)
    if harness_plan:
        report_harness(out, harness_plan, harness, trees)
    record_changed = bool(harness_plan) and harness_plan.record != manifest["harness_files"]
    info = dict(manifest.get("module_info", {}))
    if not entries:
        # Declared by the template, so a full run rebuilds it; a module the
        # template no longer provides, or an external it could not verify,
        # keeps what the manifest recorded.
        info = {n: v for n, v in info.items()
                if (n not in modules and n in installed) or (n in recorded and n not in externals)}
        info.update(module_info_for(modules, present))
    # Every external that verified gets a fresh entry, whether or not its digest moved.
    info.update(module_info_for(externals, sorted(externals)))
    info_changed = info != manifest.get("module_info", {})
    if not writes and not changed and not info_changed and not record_changed:
        out("Nothing to update.")
        return 0
    if record_changed:
        manifest["harness_files"] = harness_plan.record
    if info_changed:
        if info:
            manifest["module_info"] = info
        else:
            manifest.pop("module_info", None)
    unread = [r.casefold() for r, _ in skipped or ()]
    partial = bool(entries) or any(
        path == r or path.startswith(r + "/") for path in owned for r in unread
    )
    if partial:
        out("  note: partial update; the recorded template commit was not advanced")
    old_bases = manifest.get("file_bases", {})
    if partial:
        # Files this run did not all compare still need their old base, so the
        # recorded commit stays put; only files merged now no longer need one.
        kept_bases = {rel: base for rel, base in old_bases.items()
                      if outcome.get(rel, ("",))[0] != "merged"}
    else:
        commit, dirty = template_state()
        manifest["template_commit"], manifest["template_dirty"] = commit, dirty
        manifest.pop("module_commits", None)
        kept_bases = {rel: base for rel, base in old_bases.items() if rel not in compared}
        for rel, (status, value) in outcome.items():
            if rel == PLAN_FILE:
                continue
            if status == "changed":
                kept_bases[rel] = value
            elif status == "nobase":
                # Without a stored base the file would be judged against the commit
                # just recorded, which it never came from: remember that it has none.
                kept_bases[rel] = old_bases.get(rel)
    if kept_bases:
        manifest["file_bases"] = kept_bases
    else:
        manifest.pop("file_bases", None)
    for name, meta in changed.items():
        recorded[name] = external_record(meta)
    if recorded:
        manifest["external_modules"] = recorded
    writes[MANIFEST] = encode_manifest(manifest)
    if args.dry_run:
        for rel in sorted(writes):
            out("  would write %s" % rel)
        out("Dry run: nothing written.")
        return 0
    write_tree(project, writes, private=set(harness_plan.writes) if harness_plan else ())
    for rel in sorted(writes):
        out("  wrote %s" % rel)
    return 0


def cmd_remove(args, out):
    modules = load_modules()
    project = os.path.abspath(args.dir)
    builtin = set(modules)
    manifest = load_manifest(project, builtin)
    installed = list(manifest["modules"])
    recorded = dict(manifest.get("external_modules", {}))
    names = list(dict.fromkeys(args.remove))
    for name in names:
        if name not in installed and name not in recorded:
            raise InstallError("module %r is not installed in this project" % name)
    for other in installed:
        if other in names or other not in modules:
            continue
        for name in modules[other]["requires"]:
            if name in names:
                raise InstallError(
                    "%s requires %s; name %s too to remove both" % (other, name, other)
                )
    present = [n for n in installed if n in modules]
    order = sorted(present, key=lambda n: (modules[n]["order"], n))
    project_name = require_printable(
        args.name or os.path.basename(project.rstrip(os.sep)), "project name"
    )
    skipped = [] if args.skip_unsafe_entries else None
    existing = scan_project(project, skipped)
    if skipped:
        out("Skipped (not read, patched, or written through):")
        for rel, reason in sorted(skipped):
            out("  %s (%s)" % (rel, reason))

    notes = []
    writes = {}
    harness_paths = set(manifest.get("harness_files", {}))
    for rel in sorted(existing):
        data = existing[rel]
        if rel in harness_paths or not is_text(data) or b"BEGIN module:" not in data:
            continue
        text = data.decode("utf-8")
        try:
            new_text, _, _ = refresh_blocks(
                text, order, {}, rel, drop=set(names),
                expect={n: modules[n]["slots"] for n in names if n in modules},
            )
        except (ValueError, InstallError) as exc:
            if any(("module:%s slot:" % name).encode() in data for name in names):
                raise InstallError("%s: cannot remove its blocks (%s); nothing was written" % (rel, exc))
            notes.append("%s: not updated (%s)" % (rel, exc))
            continue
        if new_text != text:
            writes[rel] = new_text.encode("utf-8")

    keep = {rel.casefold() for rel in collect_tree(BASE_DIR)}
    for name in installed:
        if name not in names and name in modules:
            keep |= {rel.casefold() for rel in
                     collect_tree(os.path.join(modules[name]["path"], "files"))}
    deletes = []
    kept = []
    safe = can_delete_safely()
    for name in names:
        if name in recorded:
            continue
        if name not in modules:
            notes.append("%s is no longer provided by the template; its files are left" % name)
            continue
        files = collect_tree(os.path.join(modules[name]["path"], "files"))
        substitute(files, project_name)
        for rel, data in sorted(files.items()):
            if rel not in existing or rel.casefold() in keep:
                continue
            if writes.get(rel, existing[rel]) == data and safe:
                writes.pop(rel, None)
                if rel not in deletes:
                    deletes.append(rel)
            else:
                kept.append(rel)

    record = dict(manifest["harness_files"]) if "harness" in manifest else None
    for path in sorted(record or ()):
        entry = record[path]
        left = [m for m in entry["modules"] if m not in names]
        if len(left) == len(entry["modules"]):
            continue
        if left:
            record[path] = {"sha256": entry["sha256"], "modules": left}
            continue
        del record[path]
        data = existing.get(path)
        if data is None:
            notes.append("%s is not a regular file in the project; its record was dropped" % path)
        elif path.casefold() in keep:
            notes.append("%s is also shipped by the template or a remaining module; left" % path)
        elif path in deletes or path in kept:
            pass  # a `files/` entry of the same module already decided this path
        elif harness_sha(data) == entry["sha256"] and safe:
            writes.pop(path, None)
            deletes.append(path)
        else:
            kept.append(path)

    for rel in sorted(existing):
        if rel in deletes or rel in harness_paths:
            continue
        data = writes.get(rel, existing[rel])
        for name in names:
            if ("module:%s slot:" % name).encode() in data:
                raise InstallError(
                    "%s still holds blocks of %s after removal (CRLF, binary, or "
                    "rearranged markers); nothing was written" % (rel, name)
                )
    if skipped:
        notes.append("skipped entries may still hold blocks of the removed modules")
    out("Removing modules: %s" % ", ".join(names))
    for rel in kept:
        out("  kept %s (differs from the module's file or cannot be deleted safely; not deleting)" % rel)
    for note in notes:
        out("  note: %s" % note)
    commit, dirty = template_state()
    manifest["template_commit"], manifest["template_dirty"] = commit, dirty
    manifest["modules"] = [n for n in installed if n not in names]
    info = {n: v for n, v in manifest.get("module_info", {}).items() if n not in names}
    if info:
        manifest["module_info"] = info
    else:
        manifest.pop("module_info", None)
    for name in names:
        recorded.pop(name, None)
    if recorded:
        manifest["external_modules"] = recorded
    else:
        manifest.pop("external_modules", None)
    if record is not None:
        manifest["harness_files"] = record
    writes[MANIFEST] = encode_manifest(manifest)
    if args.dry_run:
        for rel in sorted(writes):
            out("  would write %s" % rel)
        for rel in sorted(deletes):
            out("  would delete %s" % rel)
        out("Dry run: nothing written.")
        return 0
    write_tree(project, writes, deletes)
    for rel in sorted(writes):
        out("  wrote %s" % rel)
    for rel in sorted(deletes):
        out("  deleted %s" % rel)
    return 0


def build_parser():
    parser = argparse.ArgumentParser(description="Create or extend a project from the template.")
    parser.add_argument("target", nargs="?", help="directory for the new project")
    parser.add_argument(
        "--with", dest="with_", nargs="+", default=[], metavar="MODULE",
        help="modules for a new project, space- or comma-separated (put the target first); "
             "name=PATH installs a standalone project as module 'name'",
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
    parser.add_argument(
        "--harness", metavar="NAME",
        help="harness whose module files (harness/<NAME>/) are installed, recorded in the "
             "manifest; known: %s" % ", ".join(sorted(HARNESSES)),
    )
    parser.add_argument("--list", action="store_true", help="list available modules")
    parser.add_argument(
        "--add", nargs="+", metavar="MODULE",
        help="add modules (or name=PATH standalone projects) to an existing project",
    )
    parser.add_argument(
        "--update", "--upgrade", dest="update", nargs="*", metavar="MODULE",
        help="refresh installed modules (all, or those named) from this template",
    )
    parser.add_argument(
        "--remove", nargs="+", metavar="MODULE",
        help="remove installed modules (blocks, unedited files, manifest entries)",
    )
    parser.add_argument(
        "--merge", action="store_true",
        help="with --update: merge the template's changes into files you edited "
             "(three-way, against the template as installed); conflicts are left unchanged",
    )
    parser.add_argument("--dir", default=".",
                        help="project directory for --add, --update and --remove (default: .)")
    parser.add_argument(
        "--skip-unsafe-entries", action="store_true",
        help="with --add, --update or --remove: skip (and list) symlinks, special files, and oversized files "
             "instead of refusing; skipped entries are never read, patched, or written through",
    )
    return parser


def main(argv=None, out=print):
    args = build_parser().parse_args(argv)
    try:
        updating = args.update is not None
        removing = args.remove is not None
        if args.skip_unsafe_entries and not (args.add or updating or removing):
            raise InstallError("--skip-unsafe-entries applies to --add, --update and --remove only")
        if args.merge and not updating:
            raise InstallError("--merge applies to --update only")
        if args.merge and args.update:
            raise InstallError("--merge cannot be limited to named modules: "
                               "it brings every installed module up to date")
        registry_modes = (args.register is not None) + (args.unregister is not None)
        if args.harness is not None and (args.list or registry_modes or removing):
            raise InstallError("--harness applies to a new project, --add and --update only")
        if removing and (
            registry_modes or args.list or args.add or updating or args.target or args.with_
        ):
            raise InstallError(
                "--remove cannot be combined with --add, --update, --with, --list, "
                "--register, --unregister, or a target directory"
            )
        if updating and (registry_modes or args.list or args.add or args.target or args.with_):
            raise InstallError(
                "--update cannot be combined with --add, --with, --list, --register, "
                "--unregister, or a target directory"
            )
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
        if removing:
            return cmd_remove(args, out)
        if updating:
            return cmd_update(args, out)
        if args.add:
            return cmd_add(args, out)
        if not args.target:
            build_parser().error(
                "a target directory is required"
                + ("; --with takes every following value as a module, so put the target "
                   "before --with or end the list with --" if args.with_ else "")
            )
        return cmd_new(args, out)
    except InstallError as exc:
        print("error: %s" % exc, file=sys.stderr)
        return 2
    except KeyboardInterrupt:
        print("\ninterrupted; nothing was written", file=sys.stderr)
        return 130


if __name__ == "__main__":
    sys.exit(main())
