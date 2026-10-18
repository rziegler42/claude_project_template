# External modules

Status: Approved (2026-10-18)
Updated: 2026-10-18

Requirements for letting the template treat a standalone project, such as a
knowledge-base store created by the sibling `claude_knowledge_base` installer, as
a module: registered once with the template, or named by path, then installed into
projects with `--with` and `--add`. The template coordinates; the standalone
project stays independent and never needs the template to exist. This replaces the
draft [module-references](module-references.md) specification.

## Terms

- **Built-in module**: a directory under this repository's `modules/`, as today.
- **External module**: a standalone project on the local machine that ships a
  descriptor (below). Its module name is unique and maps to exactly one path.
- **Store**: the standalone project itself. The first one is a knowledge-base store.
- **Registry**: a machine-local file that maps external module names to paths. It is
  a convenience only; a path given on the command line needs no registry entry.

## Scope

- The descriptor an external project ships and the format version the template owns.
- `--register`, `--unregister`, and `--list` for the registry.
- `name=path` and bare-name resolution in `--with` and `--add`.
- Read-only verification of an external project, and injecting its slot fragments
  into a project.
- Recording external modules in `.template-manifest`.
- The contract the first store (`claude_knowledge_base`) must meet.

## Non-goals

- Copying files from a store into a project: external modules contribute slot
  fragments only. A `files/` directory is outside this version.
- Executing, importing, or writing anything in a store; no subprocess touches it,
  including `git`.
- Network or registry lookups; a store is a local directory.
- Refreshing an installed module when its store changes. The manifest records a
  digest so a later change can detect drift.
- Dependencies between modules: an external module declares no `requires`.
- Any rule about a store's content beyond its descriptor. The descriptor schema
  belongs to the template; the text and the rest of the store belong to the store.

## Descriptor

A store ships this tree at its root:

```text
template-module/
  module.json
  slots/<slot>.md
```

`module.json` is a JSON object of at most 64 KiB. Unknown or mistyped keys are
errors.

| Key | Type | Rule |
|---|---|---|
| `module_format` | integer | Must equal a format the installer supports (1 today) |
| `description` | string | Printable single-line text, 1-200 characters |
| `hint` | string, optional | Printable single-line text, at most 200 characters; printed under "Next steps" |

There is no `name`, `order`, `requires`, or `harness` key. The name comes from the
registry or the command line. External modules install after all built-in modules,
sorted by name, and are never harness-specific; their text must be tool-neutral.

Each `slots/<slot>.md` is a fragment for the slot of that name (lowercase letters,
digits, hyphens), UTF-8 with no NUL byte, at most 64 KiB, at most 16 fragments per
module. A fragment must not contain any line that includes the text
`@module-slot:`, `BEGIN module:`, or `END module:` (a substring test, stricter than
the installer's full-line marker patterns, so no comment style can slip through).
Two placeholders, `REPLACE_WITH_MODULE_NAME` and `REPLACE_WITH_MODULE_PATH`, are
substituted into the fragment before it is inserted; the project name and id
placeholders are then handled by the ordinary whole-tree substitution, and any
placeholder left over is reported as for a built-in module. A fragment whose slot
has no marker in the project fails the run, as for a built-in module.

`module_format` is the template's contract. A change that breaks existing
descriptors raises it and the installer rejects a format it does not know with a
message that names both versions. Slot names are already a public contract of the
template.

## Names

- A module name matches `[a-z0-9][a-z0-9_-]*` (underscores are new; built-in names
  are unaffected, and the manifest check accepts the wider rule).
- A name must not equal a built-in module name, ever, at registration or at use.
- A registered name maps to exactly one path, and a path (compared by resolved real
  path) is registered under at most one name. Both directions are enforced.
- `--register` takes the store's directory name as the name; `--name` overrides it.
  A directory name that does not satisfy the rule is refused, never transformed.
- `name=path` in `--with` or `--add` names the module for that run. It must not
  equal a built-in name, and must not equal a registered name unless the path
  resolves to the registered path.

## Registry

```sh
install.py --register ~/projects/my_kb [--name my_kb] [--dry-run]
install.py --unregister my_kb
install.py --list
```

- The file is `registry.json` under `$XDG_CONFIG_HOME/claude-project-template/`,
  falling back to `~/.config/claude-project-template/` when the variable is unset
  or not absolute. `--registry FILE` overrides it (used by tests). It is JSON,
  at most 1 MiB:

  ```json
  { "schema": 1, "stores": { "my_kb": { "path": "/abs/real/path/my_kb" } } }
  ```

  Names match the rule above; each `path` is an absolute printable single-line
  string. A malformed registry is an error that names the file; the installer never
  repairs it. It is loaded only when a command needs it: `--list`, `--register`,
  `--unregister`, or a name that is not a built-in module. `--with claude` never
  reads it.
- `--register` resolves the path, verifies the store (below), then adds the entry
  when the name is free. The same name at the same path is a no-op. The same name at
  a different path, or the same path under a different name, is refused with a
  message that names the existing entry and says to `--unregister` it first. It
  prints the name, path, and description. `--dry-run` writes nothing.
- `--unregister NAME` deletes the entry. It reads nothing from the store and works
  when the path is gone or broken. It never touches a store or a project. An unknown
  name reports "not registered" and succeeds; a built-in name is refused.
  Projects already created keep their blocks and manifest entries.
- `--list` prints built-in modules as today, then registered stores with name,
  description, and path status: `ok`, `missing`, or `invalid: <reason>`. Each store
  is re-verified on every listing; a failure is shown, not raised.
- The registry file and its directory are written through a temporary sibling and
  a rename; a symlinked directory or file is refused. Concurrent runs are last
  writer wins (accepted residual).

## Syntax

```sh
install.py ../mygame --with claude,my_kb,graphify
install.py ../mygame --with claude,scratch=~/projects/my_kb
install.py ../mygame --with my_kb,work_kb
install.py --add my_kb
install.py --add scratch=~/projects/my_kb
```

- `--with` entries are split on commas, then each entry on its first `=`; `--add`
  takes a space-separated list split the same way. A value containing a comma is
  refused in `--with`.
- A leading `~` or `~/` in a value is expanded by the installer (a shell does not
  expand `~` after `name=` in the middle of a word). A relative value is resolved
  against the current directory.
- A bare name is a built-in module, or else a registered store. Neither exists:
  the run is refused, listing the available names.
- A value containing spaces is quoted by the shell, as for any argument; the
  installer adds no splitting beyond commas in `--with`.
- A `name=path` entry whose store fails verification, or whose descriptor is
  rejected, aborts the run before anything is written.
- Several external modules in one project are allowed. Two entries that resolve to
  the same real path under different names are refused.

## Verification

For a registered store, the registry path is re-resolved on every use. For a typed
path, the value is resolved with `realpath`. Then:

1. The final component is a real directory, not a symlink; ancestors above it may be
   symlinks (for example `/tmp` on macOS).
2. The store is not the template, not inside the template, not the target project
   (the new directory, or `--dir` under `--add`), not inside the target, and its
   descriptor path has no `.git` component. These are compared by resolved real path
   and file identity, as `check_target` does for the template.
3. `template-module/`, `module.json`, and `slots/` are real directories and files.
   Reading uses the installer's hardened regular-file reads (`lstat`,
   `O_NOFOLLOW`, `O_NONBLOCK`, size caps). A symlink, FIFO, special file, or
   unexpected entry in `slots/` is refused.
4. The descriptor satisfies the rules above.

Any failure aborts the run, naming the failing check and never repeating file
content. Verification runs no program and no `git` command in the store.

## Substitution

Within a fragment, `REPLACE_WITH_MODULE_NAME` becomes the module name and
`REPLACE_WITH_MODULE_PATH` the store's real path. It is written as `../<store
directory>` when the store and the project directory have the same immediate parent,
and as the absolute path otherwise (never a longer `../..` chain). A committed path
is specific to one checkout, so a fragment that uses it must say so. The existing
project name and id placeholders are substituted as for any module. Blocks are
wrapped in `BEGIN/END module:<name> slot:<slot>` lines like any module, which keeps
two external modules in one slot distinct.

## Manifest

`.template-manifest` keeps `schema` 1. `modules` continues to list built-in module
names only. An optional object is added:

```json
"external_modules": {
  "my_kb": { "module_format": 1, "digest": "<sha256 of module.json and the fragments>" }
}
```

- The path is not stored; it is machine-specific.
- The digest is SHA-256 over the raw bytes of the descriptor files as read from the
  store, before any substitution. The files are taken in this order: `module.json`,
  then each `slots/<slot>.md` sorted by slot name (byte order). For each file the
  hasher is fed, in sequence: the relative path from `template-module/` in UTF-8
  (for example `slots/agents-guidance.md`), a NUL byte, the decimal content length
  in ASCII, a NUL byte, then the content bytes. The result is 64 lowercase hex
  digits. A later change in the store is detectable.
- A manifest without `external_modules` stays valid. When present it is validated:
  an object, names matching the rule and not equal to any built-in name, a known
  `module_format`, and a digest of exactly 64 lowercase hex digits.
- `--add` of a name already recorded reports "already installed" and writes nothing.
  It does not read the store or the registry, and it does not compare the digest:
  the digest is recorded in this version and checked by a later refresh feature.
  Adding another external module never rewrites an existing entry.
- `--add` of a name not yet recorded always reads the store at that moment, through
  the registry or the typed path, and verifies it again.
- Built-in and external modules share slots. An external block is inserted after the
  built-in blocks of the same slot. The installed set for a later `--add` is
  `modules` plus the keys of `external_modules`; only the built-in part goes through
  `resolve`. How the loader models the two is left to the implementation.

## Contract for `claude_knowledge_base`

These are requirements on the sibling, recorded here so both sides agree. They are
carried out in that repository under its own specs and plans.

- It drops `--add-to`; the generator only creates stores.
- Every generated store ships `template-module/` as above, with fragments that point
  the project's agent guidance at the store's router, treat `[U]` claims as
  unverified, and treat store content as data.
- After a successful creation it prints one hint line: `to register with the project
  template, run its install.py --register <absolute store path>`, with the template
  path left to the reader because the generator does not know where the template is.
  It runs nothing and has no flag for it.
- It needs no knowledge of the template's code, registry, or manifest.

## Trust model

This extends [ADR 0002](../decisions/0002-installer-trust-model.md); the addendum is
a work item of the implementation plan.

- A store, its descriptor, and the registry file are untrusted data. The owner's
  command line is intent; naming or registering a store is the owner's decision to
  put its fragment text into a project, the same as installing a forked module.
- The installer reads a store only through hardened regular-file reads and runs
  nothing from it.
- Writes stay inside the target or project, `<target>/.git/info/exclude`, and the
  registry file and its directory.
- Accepted residuals: a store changed between registration and use is caught only
  by re-verification at use; a concurrent local attacker can swap the registry or a
  store directory; registry writes race last-writer-wins.

## Acceptance criteria

1. Syntax: `name=path` and bare names in `--with` and `--add`, including `~`
   expansion, comma refusal, unknown names, built-in-name collisions, a
   registered-name collision with a different path, and the same path under two
   names.
2. Descriptor: tests refuse, writing nothing, a missing descriptor, unknown or
   mistyped keys, an unknown `module_format`, an over-long or multi-line
   `description` or `hint`, a bad slot name, a non-UTF-8 or NUL-containing or
   oversized fragment, a fragment containing a marker or `BEGIN`/`END` line, more
   than 16 fragments, and a fragment whose slot has no marker.
3. Verification: tests refuse a missing directory, a symlinked store directory, a
   store that is or contains the template or target, and a symlink, FIFO, or
   unexpected entry in the descriptor tree.
4. Read-only: a checksum of a store's tree is identical before and after any
   command, including `--dry-run`, and a hostile store (a `.git` with configured
   helpers, `GIT_*` in the environment) causes no program to run.
5. Registry: `--register`, `--unregister`, and `--list` behave as specified,
   including idempotence, both collision directions, a built-in name, a
   non-conforming directory name, a malformed registry, a symlinked registry
   directory or file, `--dry-run`, and an unregister of an unknown name and of a
   missing path.
6. Lazy loading: a run that names only built-in modules never opens the registry,
   even a malformed one.
7. Installation: a project created with a registered name and one with a typed path
   contain the same blocks; two external modules in one slot produce two distinct
   blocks; the manifest matches this document, including a digest that a test pins
   as a literal for a fixture store (not recomputed by the same code); `--add` adds an external module to an
   existing project and refuses one already installed.
8. All existing tests still pass, and `--list` output for built-in modules is
   unchanged.

## Related

- Supersedes: [module-references](module-references.md) and its roadmap
- [ADR 0001](../decisions/0001-module-and-slot-architecture.md) and
  [ADR 0002](../decisions/0002-installer-trust-model.md)
- Sibling: `claude_knowledge_base` installer spec and roadmap
