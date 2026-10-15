#!/usr/bin/env python3
"""Create or extend a project from base/ plus opt-in modules.

Usage:
  install.py <target> [--with a,b] [--name N] [--dry-run]
             [--git-name N --git-email E | --use-global-git-identity]
  install.py --list
  install.py --add <module>... [--dir DIR]

Standard library only (Python 3.9+). See docs/decisions/0001-*.md.
"""
import argparse
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

NAME_RE = re.compile(r"^[a-z0-9][a-z0-9-]*$")
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


def scan_project(project):
    """Map relative POSIX path -> bytes for an existing project.

    Refuses symlinks and non-regular files anywhere outside `.git`.
    """
    files = {}
    for dirpath, dirnames, filenames in os.walk(project):
        dirnames[:] = [d for d in dirnames if d != ".git"]
        for entry in dirnames:
            if os.path.islink(os.path.join(dirpath, entry)):
                raise InstallError("symlink not allowed in project: %s" % os.path.join(dirpath, entry))
        for filename in filenames:
            full = os.path.join(dirpath, filename)
            rel = os.path.relpath(full, project).replace(os.sep, "/")
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


def load_manifest(project):
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
    return manifest


def manifest_bytes(module_names, commit, dirty):
    payload = {
        "schema": SCHEMA,
        "template_commit": commit,
        "template_dirty": dirty,
        "modules": sorted(module_names),
    }
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
    names = resolve(selected, modules)
    tree = assemble(names, modules)
    substitute(tree, name)
    identity = None
    if not args.dry_run:
        identity = resolve_identity(args, interactive)
    commit, dirty = template_state()
    tree[MANIFEST] = manifest_bytes(names, commit, dirty)

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
    return 0


def cmd_add(args, out):
    modules = load_modules()
    project = os.path.abspath(args.dir)
    manifest = load_manifest(project)
    installed = list(manifest["modules"])
    wanted = resolve(list(installed) + list(args.add), modules)
    new = [name for name in wanted if name not in installed]
    if not new:
        out("Nothing to add: %s already installed." % ", ".join(args.add))
        return 0

    # Module files: refuse to overwrite anything that differs.
    project_name = require_printable(
        args.name or os.path.basename(project.rstrip(os.sep)), "project name"
    )
    writes = {}
    for name in new:
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
    existing = scan_project(project)
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
    manifest["modules"] = sorted(wanted)
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
    parser.add_argument("--with", dest="with_", default="", help="comma-separated modules")
    parser.add_argument("--name", help="project name (default: target directory name)")
    parser.add_argument("--dry-run", action="store_true", help="show what would be written")
    parser.add_argument("--git-name", help="local git user.name for the new repository")
    parser.add_argument("--git-email", help="local git user.email for the new repository")
    parser.add_argument(
        "--use-global-git-identity",
        action="store_true",
        help="inherit the global git identity instead of setting a local one",
    )
    parser.add_argument("--list", action="store_true", help="list available modules")
    parser.add_argument("--add", nargs="+", metavar="MODULE", help="add modules to an existing project")
    parser.add_argument("--dir", default=".", help="project directory for --add (default: .)")
    return parser


def main(argv=None, out=print):
    args = build_parser().parse_args(argv)
    try:
        if args.list:
            return cmd_list(args, out)
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
