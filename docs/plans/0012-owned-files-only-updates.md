# Limit install.py block edits to template-owned files

Status: Completed
Created: 2026-10-18

## Goal

`--update` (and `--add`, which shares the flaw) only edits files that the template
itself ships. A file the project created, such as a completed plan, is never patched,
even when it contains a slot marker or a module block.

## Problem

Observed upgrading `othello`: `--update` inserted `BEGIN module:graphify
slot:plan-discovery` blocks into `docs/plans/0005-external-training-data.md` and
`0006-larger-supervised-evaluators.md`. Those plans were copied from `next.md`, so
they still carry the `@module-slot:` marker. `cmd_update` runs `refresh_blocks` over
every text file in the project, and `cmd_add` runs `apply_slots` over every text file.
Neither asks whether the template owns the file.

A second defect, seen in the owner's change log: in the active `docs/plans/next.md`
(a template-owned file) `--update` replaced existing blocks with the template
placeholder, discarding the owner's filled-in "Discovery and impact evidence" and
"Second opinion" text. The plan-content blocks (`plan-discovery`, `plan-review`)
are placeholders the owner fills in per plan, so a re-render destroys real content.
Owned-file scoping alone does not prevent this.

## Scope

- Define the owned set: every relative path in `base/` plus every path in the `files/`
  tree of each installed built-in module (all of them, not only the ones being
  updated or added, because a block can land in a file another module ships).
  Compare with `casefold()`, as `--remove` already does.
- `cmd_update`: run `refresh_blocks` only on owned paths. A non-owned file with a
  marker or block is left untouched. Nothing is reported for it unless a wanted
  `module:slot` finds no marker in an owned file, which already produces the existing
  "has no slot marker in this project" note.
- `cmd_update`: never rewrite the body of a block that already exists in
  `docs/plans/next.md`; a missing block is still inserted. Other owned files
  (`AGENTS.md`, the READMEs, `.gitignore`) hold policy text and keep re-rendering.
- `cmd_add`: run `apply_slots` only on owned paths (including newly written module
  files). The existing "fragments with no matching slot marker" error is unchanged,
  so it still fires when the only marker is in a non-owned file.
- README and ADR 0002 addendum stating the rule.

## Non-goals

- `--remove`. It must strip every block of the removed module wherever it sits, and
  refuses to finish if one remains. Narrowing it would leave orphaned blocks,
  including the ones this defect already created.
- Repairing `othello`. The two edited plans there are uncommitted; the owner reverts
  or keeps them with git.
- Changing which files are written when missing, or the keep-if-differs rule.

## Assumptions and constraints

- "Part of the module" is read as template-owned: `AGENTS.md` and `docs/plans/next.md`
  are base files that receive module fragments, so they stay in scope. Treating only
  a module's own `files/` as in scope would make fragment slots in base files
  unreachable.
- External modules ship fragments only, so their blocks also land in owned files.
- Governed by ADR 0002: read and write boundaries are unchanged; this only narrows
  which already-scanned files are patched.

## Discovery and impact evidence

Graphify: skipped — the change is confined to the file loops in `cmd_update`
(`install.py` 1399-1412) and `cmd_add` (`install.py` ~1281-1290), plus tests and docs,
all read directly from current source. `collect_tree` and the `keep` casefold set in
`cmd_remove` are the precedents for the owned set.

## Completion criteria

- `--update` leaves a project-created file containing `@module-slot:` or a module
  block byte-identical, while still refreshing the same block in `AGENTS.md` and
  `docs/plans/next.md`.
- `--update` leaves an existing, filled-in block in `docs/plans/next.md` unchanged
  and still inserts a missing one.
- `--add` does not insert fragments into such a file.
- Existing update, add and remove tests pass unchanged.
- Full suite passes and `git diff --check` is clean.

## Increments

### Increment A — Owned-file scope

Dependencies: None
Affected areas: `install.py`, `tests/test_install.py`

1. Add failing tests: create a project, add `docs/plans/0001-old.md` containing a
   slot marker; `--update` and `--add graphify` leave it identical while
   `AGENTS.md` and `docs/plans/next.md` change as before; a project file holding a
   stale block of an installed module is not rewritten by `--update`;
   `--add` of a module whose only marker is in a non-owned file still fails with the
   no-matching-marker error; a filled-in `plan-discovery` block in `next.md` survives
   `--update` byte-identical, and a missing one is inserted.
2. Add `owned_paths(modules, installed)` returning the casefolded set, and use it as
   a filter in the two loops; give `refresh_blocks` a way to keep existing block
   bodies (insert-only) and use it for `docs/plans/next.md`.
3. Run the new tests, then the full suite.

Completion: step 1 tests fail before step 2 and pass after; suite green.

### Increment B — Documentation

Dependencies: Increment A
Affected areas: `README.md`, `docs/decisions/0002-installer-trust-model.md`,
`docs/plans/README.md`

1. README: state that `--update` and `--add` edit only template-shipped files.
2. ADR 0002 addendum with the rule and the `--remove` exception.
3. Add the plan to the archive table when archived.

Completion: `git diff --check` clean.

## Verification

- `python3 -I -m unittest discover -s tests` after each increment.
- A scratch project with a copied plan holding a marker: `--update --dry-run` and
  `--add --dry-run` list no write for it.
- `git diff --check`.

## Risks and sensitive actions

- Behavior change: a project that relied on `--update` filling a slot in a file the
  owner added by hand (a custom file with a marker) no longer gets it. The run
  stays silent about such files, so the owner would have to copy the block manually.
  Accepted when this plan is approved.
- A stale policy block in `next.md` is no longer refreshed by `--update`; the owner
  edits it by hand. Accepted: losing filled-in plan text is the worse failure.
- A user who renames or moves a shipped file (for example relocates `next.md`) loses
  refreshes for it; the existing "no slot marker" note covers the case.
- No new read or write boundary; a security review is not warranted.

## Deferred work

- A note listing non-owned files that carry markers, if silence proves confusing.
- Narrowing `--remove` once orphaned-block handling is decided separately.

## Result

Completed 2026-10-18; not yet committed when archived.

- `--update` and `--add` patch module blocks only in files the template ships
  (`owned_paths`: `base/` plus the `files/` of installed built-in modules, compared
  case-folded). Project-created files such as completed plans are never patched.
  In `docs/plans/next.md`, `refresh_blocks(..., keep=True)` keeps the body of an
  existing block and still inserts a missing one. `--remove` is unchanged.
- Verification: `python3 -I -m unittest discover -s tests` passed (230 tests, 6 new);
  five of the six failed before the change, and the sixth (`--add` fails when only a
  project-created file has the marker) is a guard. `git diff --check` clean. A
  `--update --skip-unsafe-entries --dry-run` against the affected project reported
  "Nothing to update" and did not list its patched archived plans.
- README and ADR 0002 (addendum 2026-10-18) state the rule.
- Not done: no Codex plan review and no security review (the plan recorded none as
  warranted).
- Known behavior: a stale policy block in `next.md` is not refreshed by `--update`;
  a hand-made file with a slot marker gets no blocks; re-rendering a block whose body
  no longer starts with a heading can move a blank line.
