# 0016: External modules in the manifest

Status: Completed
Created: 2026-10-18
Completed: 2026-10-18

## Goal

An external module (a standalone project registered or passed as `name=path`)
can declare a type, project-relative paths and data, and its `.template-manifest`
entry also records where its store lives, so a skill can find every kb store
from one file.

## Scope

- `module_format` 2 for external stores. A format 2 `template-module/module.json`
  may carry the same optional `type`, `paths` and `data` keys a built-in module
  may, validated by the existing `module_info_problem`. Format 1 is unchanged:
  it still rejects every key but `module_format`, `description` and `hint`.
- `MODULE_FORMATS` becomes `(1, 2)`. An already-deployed installer refuses a
  format 2 store that uses the new keys, with its "unknown module.json keys"
  error, because it checks keys before the format; a format 2 store with none of
  them gets "module_format 2 is not supported". Either way nothing is written.
  The new installer checks `module_format` before the keys, so a format 3 store
  reports the format, not the keys.
- `module_info` gains one key, `store`, valid only on entries for modules named
  in `external_modules`. It is the store location the user gave, in the form the
  slot text already uses: `../name` for a sibling of the project, otherwise the
  absolute path. A consumer resolves a relative value against the project root.
- Every external module gets a `module_info` entry, format 1 included: a format 1
  entry holds only `store`, a format 2 entry holds `store` plus whatever it
  declares. That is how every external store is discoverable from one file.
- `--new`, `--add` and `--update` (full or named) record the entry for an
  external module from its verified descriptor, and `--remove` drops it. Every
  external that verifies successfully produces a fresh entry on every
  `--update`, and `info_changed` compares entries independently of the digest, so
  a legacy manifest with no `store`, or a project whose sibling or absolute form
  changed, is corrected even when the descriptor is unchanged. Only an external
  that cannot be verified keeps its existing entry.
- `module_info` validation has two branches. A built-in key uses `NAME_RE`, must
  be in `modules`, and may hold only `type`, `paths`, `data`. An external key uses
  `EXT_NAME_RE` (so `my_kb` loads), must be in `external_modules`, and may hold
  `type`, `paths`, `data` and `store`. `store` is refused on a built-in entry and
  required on an external one.
- Compatibility cost, accepted: an installer from plan 0015 requires every
  `module_info` key to be in `modules`, so it refuses a manifest whose external
  modules have entries. Plan 0015 was committed today and no project depends on
  it, so no shim is added.
- The external digest already covers `module.json`, so a changed declaration is
  detected as a changed store; no new digest is needed.
- README ("Module info", "Writing an external module"), the ADR 0002 addendum,
  `docs/specs/external-modules.md` and ADR 0003 document format 2, `store`,
  compatibility, and the consumer rule, and no longer say that external
  descriptors reject every unknown key.

## Non-goals

- Store-relative paths (a second map resolved inside the store). `paths` stay
  project-relative; the store location is the only pointer outside the project.
- Per-install `data` values; `data` comes from the store's descriptor.
- Migrating existing format 1 stores or changing the registry format.
- A query command.
- A `schema` bump: `schema` stays 1.

## Assumptions and constraints

- The manifest and the store descriptor are untrusted input (ADR 0002). Every
  existing bound applies to format 2 values; `store` is a printable string of at
  most 512 characters, and exactly one of two forms. Sibling: `../` plus one
  component that passes `safe_relpath` (so no `/`, `.` or `..`). Absolute: a
  leading `/`, then components that pass `safe_relpath` when joined without the
  leading slash. Every other form is refused: empty, `.`, `./name`, `foo/bar`,
  `../a/b`, `../..`, `..`, a trailing slash, a `.git` component, `\` and `:`.
- Absolute store paths are machine-specific and make the manifest non-portable
  across checkouts. The sibling form is preferred; consumers treat a missing
  store as "not available", never an error.
- Decision recorded by the owner: record the store location (not project-relative
  only, not a second path map), and use `module_format` 2 rather than allowing the
  keys in format 1.
- `store` is derived data. The registry and the installed slot text stay the
  source of truth; a mismatch is not an error.

Graphify: skipped — the affected code (`read_external`, `external_record`,
`module_info_for`, `validate_external_modules`, `validate_optional_keys`,
`cmd_new`, `cmd_add`, `cmd_remove`, `cmd_update`) is enumerated below.

## Completion criteria

A format 2 fixture store declaring type, paths and data is recorded with its
`store` by `--new` and `--add`, refreshed by `--update`, and dropped by
`--remove`; a format 1 store with those keys is still refused; hostile `store`,
`type`, `paths` and `data` values are refused before anything is written; a
project with no external modules and no declaring built-in module has a
byte-identical manifest to today's; a project with a format 1 external gains only
its `store` entry; an unchanged-descriptor `--update` adds a missing `store` and
corrects a stale one; a `my_kb` store round-trips through `--add`, `--update` and
`--remove`; the full suite passes and `git diff --check` is clean.

## Increments

### Increment A — Accept and validate format 2 descriptors

Dependencies: None
Affected areas: `install.py` (`MODULE_FORMATS`, `read_external`,
`validate_external_modules`), `tests/test_install.py`

1. Write failing tests: a format 2 store with valid keys loads; the same keys in
   format 1 are refused; invalid `type`, `paths`, `data` in format 2 are refused
   with the module named; format 3 is refused with the format message even when
   the new keys are present; an older-format manifest entry still validates.
2. Check `module_format` before the keys in `read_external`, extend the allowed
   keys by format, call `module_info_problem`, and keep the declared keys on the
   module record.

Completion: new tests pass and the existing suite is unchanged.

### Increment B — Record store and declared info

Dependencies: Increment A
Affected areas: `install.py` (`module_info_for`, `validate_optional_keys`,
`cmd_new`, `cmd_add`, `cmd_remove`, `cmd_update`), `tests/test_install.py`

1. Write failing tests: `--new`, `--add`, full and named `--update` and
   `--remove` with an external fixture; an unverifiable external keeps its entry
   on full `--update`; `--dry-run` writes nothing; hostile `store` values
   (each rejected form listed under the constraints, plus overlong and
   non-string), a `store` on a built-in entry, and an external entry without
   `store` are refused on load; a valid sibling value and a valid absolute value
   load; a `my_kb` external loads and round-trips; an unchanged descriptor with a
   missing or stale `store` is corrected by `--update` (full and named) and
   reported by `--dry-run` without writing.
2. Add a `store_ok` predicate implementing the two accepted forms, compute
   `store` from the loaded store path in the same form `read_external` already
   builds for slot text, add the entry for externals, split the `module_info`
   validation by built-in and external branch, and make `cmd_update` recompute
   every verified external's entry.

Completion: new tests pass, suite green, older manifests load unchanged.

### Increment C — Documentation

Dependencies: Increment B
Affected areas: `README.md`, `docs/decisions/0002-installer-trust-model.md`,
`docs/decisions/0003-external-module-mechanism.md`,
`docs/specs/external-modules.md`

1. Document format 2, `store`, the portability caveat, the compatibility
   behavior of deployed installers and the consumer rule, and remove the
   statements that external descriptors reject all unknown keys.

Completion: documents match behavior; `git diff --check` clean.

## Verification

- `python3 -I -m unittest discover -s tests` (287 tests today plus the new ones).
- An adversarial pass over the new `store` and format 2 inputs, using the
  `security-review` skill, before archiving.

## Risks and sensitive actions

- A new manifest field derived from an untrusted descriptor and a user-supplied
  path; mitigated by the existing bounds and `safe_relpath`-style checks.
- Absolute paths in a committed manifest can expose a home directory name; the
  sibling form avoids this in the common case.

## Deferred work

- Store-relative paths, per-install `data`, and a query command.

## Result

Completed in four commits after the plan commit (`224e5d3`).

- Increment A (`1b91d55`): `MODULE_FORMATS` is `(1, 2)`; `read_external` checks the
  format before the keys and lets a format 2 descriptor declare `type`, `paths` and
  `data`, validated by `module_info_problem`. Format 1 still refuses them. 5 new tests.
- Increment B (`ceb3d72`): every external module gets a `module_info` entry with
  `store` (`../name` or an absolute path, checked by the new `store_ok`) plus whatever it
  declares. `--new`, `--add`, `--update` and `--remove` maintain it; every externally
  verified `--update` rewrites the entry even when the digest is unchanged, and a store
  that cannot be verified keeps its entry. Validation has separate built-in and external
  branches, so `my_kb` loads. A store path that cannot be recorded is refused before
  anything is written. 15 new tests; `test_manifest_records_external` now asserts the
  store name is absent from `external_modules` rather than from the whole manifest.
- Increment C (`ba4ec08`): README, ADR 0002 addendum, ADR 0003 and
  `docs/specs/external-modules.md` document format 2, `store`, compatibility and the
  consumer rule.
- Follow-up (`d36912a`): README and ADR 0002 state that an installer from before external
  entries refuses a manifest that has them.

Verification: `python3 -I -m unittest discover -s tests` passes with 307 tests;
`git diff --check` is clean. Guard mutation on a scratch copy: removing the `store_ok`
rules (32 failures), allowing the keys in format 1 (3), refreshing an external's entry
only when its digest changed (1 failure, 1 error) and dropping the external `store`
check in manifest validation (10) each fail the new tests. An installer from the commit
before this plan, run with `--update --dry-run` against a manifest this plan wrote with
an external module, exited 2 ("malformed … module_info entry") and wrote nothing.

Codex plan review (did not converge; all six findings applied):

## Codex plan review

- Plan: docs/plans/next.md (key 313100c9b64c95c7)
- Rounds used: 3 of 3
- Round 1: model gpt-5.6-luna, effort low, 2 finding(s) (2 blocker or major), 89483 input and 1571 output tokens
- Round 2: model gpt-5.6-luna, effort low, 1 finding(s) (1 blocker or major), 168529 input and 1880 output tokens
- Round 3: model gpt-5.6-luna, effort high, 3 finding(s) (3 blocker or major), 825824 input and 15564 output tokens
- Outcome: not converged (3 blocker or major finding(s) in the last round)
- Effort raised to high for round 3: round 3 reached (round 3 of this review window)
- Decisions: 6 applied, 0 rejected

The round 3 revisions were not shown to Codex again. Codex also reviewed ADR 0002 and
ADR 0003 after the documentation changes: both converged in one round. The only finding,
a stale "76 tests" count in ADR 0002's Verification section, predates this plan and was
left alone.

Adversarial security review (a partial pass; no Critical, High or Medium findings):
about 55 hostile `store_ok` values and hostile format 2 descriptors (non-integer and
boolean formats, `NaN`, huge integers, deep nesting, 17 paths, `.git` in a path, control
and bidi characters) were refused with a bounded message, and store names containing `:`
or `\` were refused. Two Low findings, both documented rather than changed: an installer
from before this plan fails closed on a manifest with external entries, and a registry
that points a name at a different valid store changes the recorded store on the next full
`--update`, which ADR 0002 already treats as owner-controlled.
Not exercised: symlinked parents, case aliases and a store swapped between verification
and write; a registry entry pointing elsewhere; the manifest output for boundary store
names (those runs stopped at the git-identity check); a 512-character store through the
CLI; and Windows or case-insensitive filesystems.

Not done (deferred above): store-relative paths, per-install `data` values and a query
command. The knowledge-base project's own descriptor was not changed.
