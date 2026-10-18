# Module type and locations in the manifest

Status: In Progress
Created: 2026-10-18

## Goal

A project's `.template-manifest` says, for each installed module that declares
it, what type of module it is and where its files or stores live, so a skill or
another module can discover them from one file instead of guessing paths.

## Scope

- Three optional keys in a built-in module's `module.json`:
  - `type`: a short name for the kind of module (`claude`, `knowledge-base`).
  - `paths`: an object of role to project-relative POSIX path
    (`{"store": "docs/kb"}`), for the locations other tools need.
  - `data`: a small JSON object of other module-specific values.
- The installer validates the keys when it loads modules and copies them into a
  new optional manifest key, `module_info`: `{module: {type, paths, data}}`,
  one entry per installed module that declares any of the three. Modules that
  declare none have no entry.
- `--new` and `--add` record entries, `--remove` drops them, and a full
  `--update` refreshes them from the current template. A run limited to named
  modules leaves them alone.
- `module_info` is validated on load and ignored by older installers, as the
  other optional keys are.
- README documents the keys and the consumer contract.

## Non-goals

- Per-install values. `paths` and `data` come from the template and are the
  same in every project; a store whose location the user chooses at install
  time (for example `--with knowledge-base=../kb`) needs its own plan.
- External modules. Their descriptor format rejects unknown keys, so allowing
  these keys there means a new `module_format` and is deferred.
- Declaring `type` on the existing built-in modules. No current module needs
  it; fixtures cover the feature, and the knowledge module declares its own.
- A query command. Consumers read the JSON file.
- Any schema bump: `schema` stays 1.

## Assumptions and constraints

- The manifest is untrusted input (ADR 0002): validation is bounded (entry
  count, string length, nesting depth, total size), every `paths` value must
  pass `safe_relpath`, and consumers are told to treat the contents as data.
- `module_info` is derived data. The installed files stay the source of truth;
  a mismatch is not an error.
- An existing project has no `module_info` until its next full `--update`;
  consumers must treat an absent entry as "not declared".
- Two modules may declare the same `type` (two knowledge bases); consumers
  select by module name or by type.
- Decision point for the owner: `paths` as a top-level key (proposed) versus a
  convention inside `data`. A top-level key lets the installer validate every
  location; I recommend it.

Graphify: skipped — the affected code (`load_modules`, `manifest_bytes`,
`cmd_new`, `cmd_add`, `cmd_remove`, `cmd_update`, `load_manifest`) is already
enumerated below.

## Completion criteria

A fixture module declaring all three keys is recorded in the manifest by
`--new` and `--add`, refreshed by a full `--update`, dropped by `--remove`;
malformed or hostile values are refused before anything is written; a module
declaring none leaves the manifest byte-identical to today's; the full suite
passes and `git diff --check` is clean.

## Increments

### Increment A — Validate the optional module keys

Dependencies: None
Affected areas: `install.py` (`load_modules`), `tests/test_install.py`

1. Write failing tests: valid keys load; `type` not matching the name pattern,
   non-object `paths` or `data`, an unsafe or absolute path, an oversized or
   too deeply nested `data`, and a non-JSON-native value are each refused with
   a message naming the module.
2. Validate `type`, `paths`, `data` in `load_modules` and keep them on the
   module record; modules without them are unchanged.

Completion: new tests pass and the existing suite is unchanged.

### Increment B — Record module_info in the manifest

Dependencies: Increment A
Affected areas: `install.py` (`manifest_bytes`, `validate_optional_keys`,
`cmd_new`, `cmd_add`, `cmd_remove`, `cmd_update`), `tests/test_install.py`

1. Write failing tests for: `--new` and `--add` write `module_info` for
   declaring modules only; no declaring module means no key; `--remove` drops
   the entry; a full `--update` refreshes it; a named-module `--update` leaves
   it; a hostile `module_info` in an existing manifest is refused on load;
   an older manifest without it still loads; and a metadata-only full
   `--update` (a module's `type`, `paths` or `data` changed, no file or
   external descriptor changed) writes the refreshed manifest instead of
   reporting "Nothing to update", while a named-module `--update` leaves the
   existing `module_info` unchanged.
2. Implement. `module_info` is rebuilt from the installed built-in modules
   rather than patched, so it cannot drift. In `cmd_update`, a full run counts
   a rebuilt `module_info` that differs from the manifest's as a change, so the
   early "Nothing to update" return (`if not writes and not changed`) does not
   skip the manifest write; `--dry-run` reports it without writing.

Completion: new tests pass; manifests of projects whose modules declare
nothing are byte-identical to today's.

### Increment C — Document the contract

Dependencies: Increment B
Affected areas: `README.md`, `docs/decisions/0002-installer-trust-model.md`,
`docs/plans/README.md` (archive row)

1. README: the three keys, the `module_info` shape, and the consumer rules
   (absent means undeclared; treat as untrusted data; paths are
   project-relative).
2. ADR 0002 addendum: `module_info` is untrusted input with the bounds above.

Completion: documents match the behavior; suite green.

## Verification

`python3 -I -m unittest discover -s tests`, `git diff --check`, and a manual
`--new --dry-run` and `--new` with a scratch fixture module.

## Risks and sensitive actions

None identified beyond the untrusted-input handling above. No push, no change
to existing projects, no change to the global config.

## Deferred work

- Per-install values (user-chosen store locations).
- External modules declaring type, paths and data (`module_format` 2).
- Declaring `type` on the existing built-in modules.
- A command that prints the module info.

## Result

<!-- Complete this only after verification. Archive the plan according to
README.md, then reset this file to the empty template. -->
