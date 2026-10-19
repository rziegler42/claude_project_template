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

## Addendum 2026-10-18: files that `--update` and `--add` patch

`--update` and `--add` patch module blocks only in files the template ships: the
`base/` paths and the `files/` of each installed built-in module, compared
case-folded. A file the project created, such as a completed plan copied from
`next.md`, is never patched even when it holds a slot marker or a block. In
`docs/plans/next.md`, `--update` inserts a missing block but keeps the body of one
already present, since that text is filled in per plan. `--remove` is unchanged: it
strips the removed module's blocks from every scanned file, so no orphaned block
remains. No read or write boundary changes.

## Addendum 2026-10-18: reading the template's history

`--update` now rebuilds the template as it was installed, to tell a file the template
changed from one only the project changed. The manifest's `template_commit` is
untrusted input and is used only if it is 40 lowercase hex characters that
`git rev-parse --verify --quiet <sha>^{commit}` resolves to a commit in the installer's
own checkout; anything else (an option, a ref name, a tree or blob id) is reported as
having no base and never reaches `git` again. The history is read with `git ls-tree`
and `git cat-file --batch`, not `git archive`, so export attributes cannot rewrite or
drop files. Only plain blobs (modes 100644 and 100755) under `base/` and `modules/`
are accepted, with normalized paths, no `.git` component, the 16 MiB file cap, and
file-count and total-size caps. They are written with exclusive, no-follow creation
into a private temporary directory that is removed afterwards, and rendered with the
installer's own readers using only the commit's `base/` and `modules/`. The project
contributes only the manifest's module names and the project name. The step is
read-only: nothing in the project changes. The new optional manifest keys
`project_name`, `module_commits` and `file_bases` are validated on load (names,
40-hex commits or null, safe relative paths, at most 10000 entries) and are ignored by
older installers.

## Addendum 2026-10-18: `--update --merge`

`--merge` writes into existing files, still only those the template ships (the owned-file
rule above), and only in `--update`. Each merge reads three versions: the project's file,
the template as installed (rebuilt from the recorded commit as described above) and the
current template. A file equal to its installed version takes the current text. Otherwise
the three are written to a private temporary directory (exclusive, no-follow creation)
and combined with `git merge-file -p` run with the safe git options and no repository.
The result is written only on exit status 0, so a conflict, a binary file or any error
leaves the file byte-identical, and no conflict markers are ever written. Nothing is
merged without a base, into a file with an external module's block, into a project-created
file, or into an edited `docs/plans/next.md`. The merged text then goes through the usual
block refresh and the usual write path, so the existing swap-window and write-boundary
properties are unchanged.

Hardening from the adversarial review of the two addenda above: the recorded commit must
come from the installer's own checkout, and the installer must sit at its top level
(`git rev-parse --show-toplevel`), so a parent repository's history is never a base.
`git` runs with `--no-replace-objects` and `GIT_NO_LAZY_FETCH=1`, with a 60-second
timeout, and object sizes are read with `cat-file --batch-check` before any blob is
read. A recorded commit whose old module definitions are malformed is reported as having
no base, not as a crash. A manifest value that is not a string is treated as not a commit
id. `--update` advances the recorded `template_commit` only after a full run that
compared every shipped file; a run limited to named modules, or one that skipped a
shipped path as unsafe, leaves it where it is, and a differing file that had no usable
base is recorded with a null base so it is never later judged against a commit it did not
come from. `--merge` cannot be limited to named modules, leaves a file alone when taking
the template's text would drop a block of an installed module the template no longer
ships, and does not write a merged text that the block check rejects.

Accepted residual: a project file edited between the scan and the write is overwritten on
that basis, as for every other patched file; the merge widens that window by the time
`git merge-file` takes.

## Addendum: module info in the manifest

The manifest's optional `module_info` key copies a built-in module's `type`, `paths` and
`data` for tools that read the manifest. It is untrusted input like the rest of the
manifest: on load it is limited to the entry count, to modules the manifest lists, and to
the same bounds the installer applies to a module's own `module.json` (a lowercase type
name, at most 16 safe relative paths, and plain JSON data of bounded depth, size and
string length). A hostile value is refused before anything is written. The installer never
acts on these values; consumers must treat them as data, resolve paths against the
project root, confirm with `realpath` that they stay inside, and not follow symlinks (a
role may name any file in the project, including one the manifest's editor chose). The
path check rejects `\`, `:`, and a `.git` component with trailing dots or spaces, so a
consumer on Windows cannot be steered into git metadata or another drive.

External modules join this under `module_format` 2. A format 2 descriptor may declare
the same keys, validated by the same function as a built-in module's, and format 1 still
rejects them. The installer checks `module_format` before the keys. An external module's
entry also carries `store`, the location the user gave: `../` plus one safe component, or
an absolute path, and nothing else (`foo/bar`, `.`, `../a/b` and a `.git` component are
refused). The recorded `store` is a pointer for consumers and never an input to the
installer, which re-verifies a store from the registry or the path named on the command
line. A consumer resolves a relative `store` against the project root, applies the same
`realpath` check, and treats a missing store as unavailable. An absolute `store` is
machine-specific and can expose a home directory name; the sibling form avoids both.
External entries are validated against `external_modules` and the external name pattern,
built-in entries against `modules` and the built-in pattern.

Compatibility with older installers differs from the other optional keys above. An
installer that predates external `module_info` accepts only entries named in `modules`,
and one that predates format 2 refuses format 2 in `external_modules`. Either one refuses
a manifest whose external modules have entries (exit 2, "malformed"), writes nothing, and
cannot `--add`, `--update` or `--remove` in that project until it is upgraded. It fails
closed rather than ignoring the key. The costs were accepted because no project depended
on the earlier `module_info` shape. Built-in-only manifests are unaffected.

## Addendum: harness files (ADR 0004)

Accepted with [ADR 0004](0004-harness-files-in-modules.md) and the approved
[specification](../specs/module-harness-files.md) on 2026-10-19. Nothing here is implemented
yet; each mitigation below is covered by regression tests in the implementation plans. The
decisions above are unchanged.

A module may ship `harness/<harness>/`, installed into the project's harness root (`.claude/`) and,
for a few table-listed entry points, the project root. Claude Code loads installed skills and agents
automatically, so anyone who opens the project runs what they say. The owner's approval of an
external store's files is therefore the control, and the installer's static findings are advisory.

Trust model additions:

- Untrusted data: every byte of an external store's `harness/` tree and `harness.json`, the
  `harness`, `harness_files` and `schema` values in a project's `.template-manifest`, the approvals
  file beside the registry, and the marker file. A store's harness files are read, never executed,
  and no subprocess touches a store. A built-in module's harness tree is trusted as template code,
  like its other files, and gets the same path and allowlist checks so a mistake fails loudly.
- Trusted as intent only: the owner passing a digest to `--approve` after reviewing the listing the
  installer printed for exactly those files.
- Out of scope, as for fragments: the owner approving a store whose files are hostile guidance. A
  review is evidence, not proof, and an approval guards new installs only: files already copied do
  not change when the store does.
- Permitted reads gain one location outside the target, the template, a store and the registry: the
  harness marker file under the user's home directory, read as a regular file of at most 4 KiB.
  `PATH` entries are inspected with `stat` to report whether a helper exists; no helper is run.
- Permitted writes gain the harness root and the table's root-level entry-point files, inside the
  target; and the approvals file beside the registry (`registry.json.approvals`), written like the
  registry (mode 0700 directory, 0600 file, temporary sibling and rename).

Mitigations, each to be covered by a regression test in the implementation plans:

- Harness paths pass the same relative-path checks as other module files and are unique
  case-folded. A symlink, special file, `.git` component or traversal in a tree is refused, with the
  file count and tree size checked before any file is read.
- Only table-listed top-level entries install. For an external store these are skills, agents and
  commands as `.md` files; settings, hooks and MCP configuration are refused, so an approved store
  cannot add a file the harness runs on open. Installed files are never executable and are not
  protected from instructions that ask the model to run something: approval is the control, and
  the owner confirms the harness's behaviour in its documentation.
- Harness files cannot carry slot or block markers, and units whose frontmatter names collide are
  refused, so a store cannot capture another module's fragments, block its own removal, or shadow
  another unit.
- An external store with a harness tree needs an approval bound to its canonical path and the
  digest of the whole tree (including `harness.json`), checked before any write by `--new` and
  `--add` of a new name and by a named `--update`; a full `--update` skips a changed store. A
  `name=path` store carrying a harness tree is refused without one. `--remove` reads no store, no
  registry and no approval.
- A harness file is never overwritten; a differing existing file is reported as a conflict, and
  a unit shipped by two suppliers with different content refuses the later one.
- A manifest that records a harness has `schema` 2, so an installer from before this change refuses
  it instead of ignoring the harness files. A format 3 store is likewise refused by an installer
  that supports only formats 1 and 2. Manifests without a harness are unchanged.
- `harness_files` is validated on load (entry count, safe relative paths, 64-hex digests, valid
  module names), and removal deletes only a regular file whose SHA-256 equals the recorded value,
  through the existing descriptor-relative delete.

Accepted residuals:

- A store changed between review and use is caught only by the digest check at use.
- A concurrent local attacker can swap a store, the registry or the approvals file between the check
  and the read, as for the registry above; approvals are last-writer-wins.
- The installer does not verify that a file implements a declared worker role, and static findings
  do not catch hostile instructions in plain language.
- A project with a harness cannot be changed by an older installer until it is upgraded.
- The marker is machine-local and can be forged by anyone with the owner's account; it only changes
  what the installer reports, never what it installs.
