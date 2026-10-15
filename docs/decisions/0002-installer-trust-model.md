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
