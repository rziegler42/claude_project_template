# Installer module removal

Status: Approved
Created: 2026-10-18

## Goal

`install.py --remove MODULE [MODULE ...]` takes installed modules out of an
installer-created project: their slot blocks are stripped from shared files, their
unedited module files are deleted, and they are dropped from `.template-manifest`.
Built-in and external modules both work, an external module without its store being
present. Nothing is committed.

## Scope

- New mode `--remove NAME [NAME ...]`, run in the project given by `--dir` (default
  `.`). Every name must be installed (built-in or in `external_modules`).
- Dependencies: removal is refused while a module that stays installed lists a named
  module in `requires`, unless that dependent is named too (`--remove cad-freecad,cad`
  style, order-independent).
- Slot blocks: every `BEGIN/END module:<name> slot:<slot>` block of a removed module
  is stripped from every text file. The file is re-rendered from the remaining
  blocks' recorded bodies with `apply_slots`, as `--update` does, so surrounding text
  and `@module-slot:` marker lines are untouched. Nested blocks of removed modules
  go with them.
- Module files (built-in modules only): a file is deleted only when the project's copy
  is byte-identical to the module's current file after name substitution. A file that
  differs, or that carries other modules' blocks, is kept and reported. A directory
  left empty by a deletion is removed; `base/` files are never deleted.
- Manifest: the names leave `modules` and `external_modules`; `template_commit` and
  `template_dirty` are refreshed.
- All-or-nothing: if any file that holds a removed module's blocks has malformed or
  rearranged markers (the round-trip guard `--update` uses), nothing is written and
  the command fails naming the file. This differs from `--update`, which skips such a
  file, because a skipped file here would leave orphan blocks in a project that no
  longer lists the module.
- `--dry-run` lists each block strip, deletion, kept file, and the manifest write.
  `--skip-unsafe-entries`, the project scan, symlink, and path checks behave as for
  `--add` and `--update`.
- A module the template no longer provides can still be removed: its blocks are
  stripped, its files are left, with a note.
- Root `README.md` section, roadmap current-state bullet, ADR 0002 addendum for the
  new delete boundary.

## Non-goals

- Deleting edited files, or any `base/` file; recording per-file hashes in the
  manifest.
- Reversing edits made inside a block (they go with the block, as `--update`
  overwrites them) or restoring content a module replaced.
- Removing an external store, or touching the registry (`--unregister` stays
  separate).
- An interactive confirmation prompt: `--dry-run` is the preview, matching the other
  modes.
- Committing, pushing, or touching real projects such as `game_theory`.

## Assumptions and constraints

- Governed by ADR 0002 (trust model), its 2026-10-18 addendum, and ADR 0003. Removal
  reads no store and adds no read boundary; its new boundary is deletion inside the
  project, which must go through the same symlink, `.git`, non-regular-file, and
  writability checks as writes, and may never remove a directory that is not empty.
- Race mitigation (Codex R1-F1): deletion is descriptor-relative. The project root is
  opened with `O_DIRECTORY|O_NOFOLLOW`, each parent component is opened the same way
  relative to its parent's descriptor, the target is checked with `fstatat`
  (`follow_symlinks=False`, regular file), and `os.unlink`/`os.rmdir` use `dir_fd`.
  A parent swapped for a symlink after the pre-check then fails the open instead of
  redirecting the delete. The platform is POSIX per the README; where `dir_fd` is
  unavailable the command refuses to delete (blocks are still stripped and the files
  are reported as kept). This is stronger than the write path, whose swap residual
  ADR 0002 already accepts; the addendum records that the delete path closes it and
  the write path still does not.
- Recommended defaults, open to change at review: delete-only-if-pristine for files
  (the safer alternative is blocks only); refusal on dependents rather than cascading;
  all-or-nothing on malformed markers; no confirmation prompt.
- Deletions run after content replacements and before the manifest, which stays last,
  so an interrupted run leaves a manifest that still lists the module and a re-run
  finishes the job (removal is idempotent over already-stripped blocks and
  already-deleted files).
- Flag name is `--remove` only; no alias.

## Discovery and impact evidence

Graphify: skipped — the change is confined to `install.py` (a new command beside
`cmd_update`, and a deletion path beside `write_tree`), `tests/test_install.py`,
`README.md`, the roadmap, and ADR 0002, and every function it reuses was read in
current source.

Verified in `install.py` at 14fa79d: `strip_blocks` and `refresh_blocks` already
invert and re-render blocks with a round-trip guard; `write_tree` only creates or
replaces files (no deletion), and `check_write_paths` is the shared path guard to
extend; the manifest holds `modules` and `external_modules` and is written last;
`load_manifest` validates both. Module `requires` is available from `load_modules`
for built-in modules; external modules have no `requires` and no files.

## Completion criteria

- `--remove graphify` on a project created with `--with claude,graphify` leaves a
  project whose files equal one created with `--with claude` (blocks gone, module
  files gone, manifest updated), except `template_commit`/`template_dirty`.
- Adding a module with `--add` and then removing it restores the project's bytes.
- Removing a module another installed module requires is refused; naming both works.
- An edited module file is kept and reported; a malformed-marker file stops the run
  with nothing written.
- An external module is removed with its store absent or unregistered.
- `--dry-run` writes and deletes nothing.
- Full suite passes, `git diff --check` is clean, and the adversarial security review
  of the deletion path has run with findings fixed.

## Increments

### Increment A — Remove built-in modules

Dependencies: None
Affected areas: `install.py`, `tests/test_install.py`

1. Add failing tests: block stripped and file restored to the never-installed bytes;
   add-then-remove roundtrip; pristine module file deleted and its empty directory
   pruned; edited file kept and reported; file with another module's block kept;
   dependent refused, and both named accepted; not-installed name is an error;
   malformed markers stop the run with nothing written; `--dry-run` writes and
   deletes nothing; `--remove` conflicts with `--add`, `--update`, `--with`, `--list`,
   `--register`, `--unregister`, and a target; symlink in the project refused.
2. Add a `delete` list to `write_tree` (checked with `check_write_paths`, then
   removed descriptor-relative as in Assumptions, after replacements and before the
   manifest, empty parents pruned with `rmdir`, never `.git`), with a test that a
   parent replaced by a symlink between check and delete (patched hook) is refused
   and nothing outside the project is touched,
   a `remove_blocks` helper beside `refresh_blocks`, and `cmd_remove`; wire
   `--remove` in `build_parser` and `main`.
3. Run the new tests, then the full suite.

Completion: the step 1 tests fail before step 2 and pass after; full suite green.

### Increment B — Remove external modules and edge cases

Dependencies: Increment A
Affected areas: `install.py`, `tests/test_install.py`

1. Add failing tests: external module blocks stripped with the store absent; with
   the registry entry removed; digest entry dropped from the manifest and
   `external_modules` omitted when empty; built-in and external removed together;
   a module no longer provided by the template: blocks stripped, files left, note;
   hostile `--remove` names (path-like, `name=path`) rejected before any read.
2. Extend `cmd_remove` for recorded external modules and unprovided modules.
3. Run the new tests, then the full suite.

Completion: step 1 tests fail before and pass after; full suite green.

### Increment C — Security review and documentation

Dependencies: Increment B
Affected areas: `README.md`, `docs/roadmaps/external-modules.md`,
`docs/decisions/0002-installer-trust-model.md`, `docs/plans/README.md`

1. Run an adversarial review of the deletion path (symlinked parent or file,
   hardlink, swapped path between check and unlink, `.git` component, non-empty
   directory prune, read-only file) with a scratch directory; fix findings with
   regression tests.
2. Add an "Remove a module" README section (forms, what is deleted and kept, the
   block-edit warning, dependencies, all-or-nothing), a roadmap current-state bullet,
   and a short ADR 0002 addendum for the delete boundary.
3. Add the plan to the archive table when archived.

Completion: review findings fixed or recorded; README commands match
`./install.py --help`; `git diff --check` clean.

## Verification

- `python3 -I -m unittest discover -s tests` after each increment.
- A scripted scratch run of the real CLI in a scratch directory: create a project
  with `--with claude,graphify`, `--remove graphify --dry-run`, then `--remove`, and
  compare with a project created without it. Nothing in this repository.
- `git diff --check`.

## Risks and sensitive actions

- This adds file deletion to an installer whose boundary until now was create or
  replace. Mitigations: pristine-only deletion, the shared path guard, no directory
  removal unless empty, `--dry-run`, and the Increment C security review, which is
  required here (the earlier update plan skipped it).
- A block's contents are lost on removal, including edits inside it. Stated in the
  README and visible in `--dry-run`.
- Real-world projects are not touched by tests or verification.

## Deferred work

- Per-file hashes in the manifest so edited files can be diffed instead of kept.
- Removing orphaned blocks of modules not listed in the manifest.
- A confirmation prompt, if usage shows one is wanted.

## Result

<!-- Complete this only after verification. Archive the plan according to
base/docs/plans/README.md, then reset this file to the empty template. -->
