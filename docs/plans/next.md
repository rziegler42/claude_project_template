# Next plan

Status: Approved
Created: 2026-10-18

## Goal

`install.py --update` (alias `--upgrade`) brings an installer-created project up to
date with the modules it already has: built-in modules from this checkout, and
external modules from a store named by registered name or `name=path`. Existing
projects pick up changed slot fragments and newly added module files without a
re-create, and nothing is committed.

## Scope

- New mode `--update [MODULE ...]` / `--upgrade`, run in the project given by `--dir`
  (default `.`). With no names it targets every module in `.template-manifest`; with
  names, only those (each must be installed).
- Slot blocks: for each targeted module, a `BEGIN/END module:<name> slot:<slot>`
  block whose body differs from the module's current fragment is replaced. A fragment
  with a marker but no block yet is inserted as `--add` does. A block whose fragment
  no longer exists is left alone and reported.
- Module files: a file missing from the project is written. A file that exists and
  differs is never overwritten; it is reported as `differs; not overwriting`. Files
  are not compared against a baseline, because the manifest records none.
- External modules: a targeted external module is re-read the same way as for
  `--add` (registered name, or `name=path`), verified read-only, and compared with
  the manifest digest. A changed digest updates its blocks and the recorded digest.
  A recorded external module that is not named and cannot be resolved by registry is
  skipped with a note; a stale or unknown store is never guessed at.
- `--dry-run` previews every block and file change. `--skip-unsafe-entries` and the
  project-scan, symlink, and write-path checks behave as for `--add`.
- Manifest `template_commit` and `template_dirty` are refreshed on a real update.
- Root `README.md` section; roadmap deferred item moved to done.

## Non-goals

- Updating `base/` files (they carry no markers and no baseline exists to detect
  local edits) and three-way merging of edited files or blocks.
- Removing modules, removing orphaned blocks, or migrating renamed slots.
- Recording per-file hashes in the manifest (a possible later schema change).
- Fetching remote stores, or committing and pushing the result.

## Assumptions and constraints

- Governed by ADR 0002 (trust model), the 2026-10-18 addendum, and ADR 0003. The
  update path adds no new read or write boundary: it reuses `load_manifest`,
  `load_externals`, `scan_project`, `apply_slots`, and `write_tree`.
- Marker blocks are treated as installer-managed. An edit made inside a block is
  replaced by `--update`. This is the one data-loss path, so `--dry-run` shows the
  block diff, and the README states that edits belong outside blocks.
- Fragments can contain markers, so a replaced block is re-expanded with
  `apply_slots` until stable, as installation does.
- Name `--update` only; `--upgrade` is an argparse alias for the same flag.
- The owner opted out of design questions; the choices above are the author's
  defaults and are open to change at plan review.

## Discovery and impact evidence

Graphify: skipped — the change is confined to `install.py` (one new command beside
`cmd_add`), `tests/test_install.py`, and `README.md`, and the functions it reuses
were read directly from current source.

Verified in `install.py` at 6f62338: blocks are written by `apply_slots`
(`begin_line`/`end_line`), which skips a module/slot whose BEGIN line already exists
and so cannot refresh one; `cmd_add` never re-reads a recorded external module;
the manifest stores `modules`, `template_commit`, `template_dirty`, and per external
module `{module_format, digest}` only.

## Completion criteria

- `--update` on a project from an older template state replaces a stale block,
  inserts a new fragment, writes a missing module file, and leaves a differing file
  and unrelated text untouched, with the above reported.
- `--update` on an unchanged project reports nothing to update and writes nothing.
- `--dry-run` writes nothing and lists the changes.
- An external module whose descriptor or fragment changed is refreshed and its
  digest updated; an unresolvable recorded store is skipped, not guessed.
- Full suite passes and `git diff --check` is clean.

## Increments

### Increment A — Update built-in modules

Dependencies: None
Affected areas: `install.py`, `tests/test_install.py`

1. Add failing tests: stale block replaced; missing fragment block inserted; missing
   file written; differing file kept and reported; unchanged project is a no-op;
   `--dry-run` writes nothing; named module only; unknown or uninstalled name is an
   error; `--update` conflicts with `--add`, `--with`, `--register`, `--unregister`,
   `--list`.
2. Add `refresh_blocks` (replace an existing block body from the current fragment)
   and `cmd_update`; wire `--update`/`--upgrade` in `build_parser` and `main`.
3. Run the new tests, then the full suite.

Completion: the tests in step 1 fail before step 2 and pass after; full suite green.

### Increment B — Update external modules

Dependencies: Increment A
Affected areas: `install.py`, `tests/test_install.py`

1. Add failing tests: changed fragment refreshes blocks and the manifest digest;
   unchanged digest is a no-op; `name=path` and registered-name resolution; recorded
   store not resolvable is skipped with a note; hostile store (symlink, `.git`)
   refused as for `--add`; a store whose descriptor name now clashes with a built-in
   is refused.
2. Resolve targeted externals through `registered_entries`/`load_externals`, compare
   digests against the manifest, and include them in the block refresh and manifest
   write.
3. Run the new tests, then the full suite.

Completion: step 1 tests fail before and pass after; full suite green.

### Increment C — Documentation

Dependencies: Increment B
Affected areas: `README.md`, `docs/roadmaps/external-modules.md`,
`docs/plans/README.md`

1. Add an "Update a project" README section: command forms, what changes, what never
   changes, the block-edit warning, and external-module resolution.
2. Move "Refreshing an installed external module" out of Deferred in the roadmap and
   record this plan; add the plan to the archive table when archived.

Completion: README commands match `./install.py --help` output; `git diff --check`
clean.

## Verification

- `python3 -I -m unittest discover -s tests` after each increment.
- A scripted scratch run: create a project with `--with claude,graphify`, edit a
  module fragment in a temporary copy of the template or store, run `--update
  --dry-run` and then `--update`, and inspect the diff. Scratch only; nothing in
  this repository.
- `git diff --check`.

## Risks and sensitive actions

- Replacing a block discards edits made inside it. Mitigated by `--dry-run`, the
  README warning, and never touching text outside blocks. Accepted by the owner only
  when this plan is approved.
- Re-reading a store is a new read of an untrusted tree on each update; it must go
  through the existing verified path with no new code reading the store directly.
  A security review pass of `cmd_update` is warranted before archive because it
  changes files in an existing project from a store's content.
- Real-world projects are not touched by tests or verification.

## Deferred work

- Per-file hashes in the manifest so unedited files can be updated safely.
- Updating `base/` files and removing orphaned blocks.
- Updating existing projects such as `game_theory`, under that project's own approval.

## Result

<!-- Complete this only after verification. Archive the plan according to
base/docs/plans/README.md, then reset this file to the empty template. -->
