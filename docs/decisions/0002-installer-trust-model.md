# 0002: Installer trust model and hardening

Status: Accepted
Date: 2026-10-15

## Context

`install.py` writes files and runs `git`. Under `--add` it also reads and
patches an existing project directory that may have come from elsewhere. Two
adversarial review rounds (plan 0003) found that the first implementation
followed symlinks, trusted the caller's git environment and configuration,
installed module files under `.git/`, and did not validate its manifest.

## Decision

Trust model:

- Trusted: the template checkout when run from the owner's own clone, and
  the owner's command line as intent.
- Untrusted data: every command-line value; everything in a project under
  `--add` (files, symlinks, special files, `.template-manifest`); the module
  directories of a fork or locally edited clone; the caller's environment and
  git configuration, as far as `git` subprocesses are concerned.
- Permitted writes: inside the target or project directory and
  `<target>/.git/info/exclude`. Anything else is a defect.
- Out of scope: the owner deliberately installing a malicious module, and
  what a generated project's own tools do later.

Mitigations, each covered by a regression test:

- Files are read only as regular files through `lstat`, `O_NOFOLLOW`, and
  `O_NONBLOCK`, capped at 16 MiB; symlinks, FIFOs, and other special files
  are refused in projects and in module trees (module directory, `files/`,
  `slots/`, `module.json`, and each slot file).
- Writes go through a temporary sibling and a rename, manifest last, so a
  hardlinked or unwritable file is never written through and a failure
  before the rename step leaves the tree unchanged. A path with a symlinked
  or non-directory component, a read-only target, or any `.git` component is
  refused before the first write.
- `git` runs with every `GIT_*` variable dropped except
  `GIT_CONFIG_GLOBAL`, `GIT_CONFIG_SYSTEM`, and `GIT_CONFIG_NOSYSTEM`, with
  `core.fsmonitor`, `core.untrackedCache`, and `core.hooksPath` neutralized,
  and `git init --template=` so no template directory or sample hook is
  copied.
- `.template-manifest` must be an object with `schema` 1 and a list of valid
  module names, and at most 1 MiB.
- Names must be printable single-line text; module file names are compared
  case-insensitively and `.template-manifest` is reserved.
- The template root is resolved with `realpath`, and a target is refused when
  it or any existing ancestor is the template, by identity.

Opt-in relaxation: `--add --skip-unsafe-entries` skips, and lists, symlinks,
special files, and files over the size cap in the project walk instead of
refusing. A skipped entry is never read, patched, or written through; every
write-time check, the symlinked-project-directory check, and manifest
validation are unchanged. A slot marker that exists only in a skipped file
still fails with "fragments with no matching slot marker". The option is
rejected for a new-project install.

## Alternatives considered

- Document that `--add` must not be run on untrusted projects. Rejected: the
  checks are small and the failure is silent file overwrite.
- A general `--force` that bypasses every refusal. Rejected: it would
  reopen the write-through-symlink exposure; the narrow option above covers
  the legitimate case (`.venv`, `node_modules/.bin`).
- Follow symlinks inside the project when they stay inside it. Rejected: it
  needs path resolution at every use and the common legitimate case is rare.
- A sandbox or chroot. Rejected as disproportionate for a stdlib-only CLI.

## Consequences

- `--add` refuses a project that contains any symlink or non-regular file
  outside `.git` (for example a `.venv` or `node_modules/.bin`), and any file
  over 16 MiB, unless `--skip-unsafe-entries` is given. With the option those
  entries are not patched, so a module whose slot marker lives in one of
  them is refused.
- A manifest written before this change is accepted only if it has
  `schema` 1, as the installer always wrote.
- New repositories have no `.git/hooks` directory.

Accepted residuals:

- A concurrent local attacker can still swap a parent directory for a
  symlink between the pre-write check and the rename. The attacker needs
  the owner's local account, and closing it needs directory-descriptor
  relative operations.
- A failure after renaming has begun can leave some files replaced and
  others not; the manifest is replaced last, so a rerun completes the work.
- `.git/info/exclude` is appended with a normal open and `git init` follows
  its own conventions.
- Name aliases on NTFS or HFS+ volumes (short names, Unicode normalization)
  were not exercised; only case folding was.
- Module sources are trusted once they are regular files in the template
  checkout; their content is the owner's responsibility.

## Verification

- `python3 -I -m unittest discover -s tests` passes (76 tests), including
  regression tests that failed before each fix.
- Two independent `security-reviewer` passes with scratch experiments; the
  second tried to bypass the first round's fixes and found five reachable
  issues, all fixed and tested.

## Related files and decisions

- `install.py`, `tests/test_install.py`, `README.md` (security notes).
- ADR 0001; plan 0003 (`docs/plans/0003-installer-security-review.md`).

## Addendum (2026-10-18): standalone stores and the registry

Plans 0006 and 0007 let `install.py` read a standalone project (a "store") and a
machine-local registry. The mechanism is recorded in
[ADR 0003](0003-external-module-mechanism.md); this addendum extends the trust
model above to the two new inputs. The decisions above are unchanged.

Trust model additions:

- Trusted as intent only: a store path the owner types or registers.
- Untrusted data: every byte in a store (`module.json`, fragments, directory
  names), the registry file, and an `external_modules` entry in a project's
  `.template-manifest`. A store's bytes are read, never executed, and no
  subprocess runs in or on a store, so a store's `.git`, hooks, and
  `.gitattributes` are never consulted.
- Out of scope, as for built-in modules: the owner deliberately installing a
  store whose fragment text is hostile guidance. Fragment text is trusted
  guidance, not code; ESC and bidirectional characters in it are allowed.
- Permitted writes gain one location: `registry.json` and its temporary sibling
  in the registry directory (mode 0700, file 0600), nothing else.

Mitigations, each covered by a regression test:

- A store is refused when the given path is a symlink (its final component, with
  trailing separators and `.` components ignored), its real path contains a
  `.git` component, is not printable single-line text, or is, contains, or is
  inside the template or the target (by real path and identity, both
  directions). The real path is resolved physically, so `..` after a symlink
  cannot select a different store than the one checked.
- `module.json`, `slots/`, and each fragment go through the same
  `lstat`/`O_NOFOLLOW`/`O_NONBLOCK` read as module trees; descriptor and
  fragment sizes and the fragment count are capped, and the count is checked
  before any fragment is read. One read feeds both the manifest digest and the
  installed text.
- Reserved marker lines are refused in fragments after placeholder
  substitution, so a module name or path cannot complete a marker.
- Names are lowercase and end at the end of the string (`\Z`), so a trailing
  newline is never accepted; a store's `module_format` is shown in messages only
  when short.
- The same store cannot be installed or registered twice under case or
  normalization aliases (compared by file identity).
- The registry is re-verified through the same checks at every use, loaded only
  when a name needs it, and refused when it is a symlink, a special file, over
  1 MiB, or malformed; `--unregister --dry-run` removes nothing.

Accepted residuals:

- The concurrent local attacker above can also swap a store directory or the
  registry between the check and the read; the read function itself is not
  hardened against a file replaced after `lstat`. The owner's account is
  required.
- A `--with` path containing a comma is split into entries and fails closed,
  unless the second piece is itself a valid module name.
- The registry records the real path in the case the owner typed on a
  case-insensitive filesystem (cosmetic).
- Registry writers are not locked; the last writer wins.
- Unicode-normalization and NTFS aliases were exercised only on macOS (NFC/NFD,
  case); Windows was not.

## Addendum 2026-10-18: module removal

`--remove` adds deletion inside the project. Its inputs are the same untrusted
project, manifest, and command-line names; it reads no store and no registry.

Permitted deletions: regular files whose bytes equal the module's own file after
name substitution, and directories left empty by them. Never `base/` files, `.git`,
edited files, or anything outside the project.

Mitigations, each covered by a regression test:

- Deletion paths go through `check_write_paths` (no symlink component, no `.git`,
  regular and writable), then `delete_files`, which opens the root and each parent
  with `O_DIRECTORY|O_NOFOLLOW` relative to the previous descriptor, checks the
  target with `fstatat` (no follow), and uses `unlink`/`rmdir` with `dir_fd`. A parent
  swapped for a symlink after the check fails to open instead of redirecting the
  delete. Without `dir_fd` support the installer deletes nothing.
- Deletions run after the other writes and before the manifest, so an interrupted run
  leaves a manifest that still lists the module and a rerun completes it.
- A file holding the removed module's blocks that does not round-trip, whose
  built-in block differs from the module's fragment, or that would still hold a
  removed module's marker after the run, stops the run before any write.
- Files that `base/` or a remaining module also ships (compared case-folded) are never
  deleted, and a path shipped by two removed modules is deleted once.

Accepted residuals: the write path's swap window above is unchanged (rename still
follows a swapped parent); the delete path closes it only for deletion. A swap of the
project root itself between `load_manifest` and the delete is bounded by the owner's
account, as above. A file changed between the project scan and the delete is
deleted or overwritten on that basis. An external module's blocks are removed without
a baseline to compare, so text added inside one is lost. With `--skip-unsafe-entries`
a skipped file keeps its blocks and the run says so.

## Addendum 2026-10-18: several values for `--with`

`--with` now accepts several space-separated values as well as commas, matching
`--add`, `--update` and `--remove`. Each value is still split on commas, so the
rule above is unchanged: a `--with` path containing a comma is split and fails
closed. No read or write boundary changes.
