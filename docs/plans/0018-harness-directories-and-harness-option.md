# 0018: Harness directories and --harness

Status: Completed
Created: 2026-10-19
Completed: 2026-10-19

## Goal

A built-in module can ship `harness/<harness>/`, and `install.py` installs those files into a
project's harness root under a harness the project records. `--new`, `--add`, `--update` and
`--remove` all cover the files, and a project without a harness is unchanged byte for byte. This is
roadmap candidate 2, implementing the approved
[specification](../specs/module-harness-files.md) for built-in modules only.

## Scope

All of it follows `docs/specs/module-harness-files.md`; section names below are that document's.

- The harness table (`claude` only) and harness-name validation; `--harness NAME` with the command
  matrix in "Selection", including its refusals with `--list`, `--register`, `--unregister` and
  `--remove`.
- A built-in harness tree reader: the "Layout" rules (source entries, `root/`, `harness.json` read
  for shape and otherwise ignored, path and depth rules, case and NFC uniqueness through
  `NFC(casefold(NFC(x)))`, limits, UTF-8 without NUL, forbidden marker strings, installed-path
  collision with `base/` and `files/`), the built-in column of the allowlist, and the frontmatter
  `name` rule for built-in modules. The reader runs only for modules a command selects, installs or
  updates, so `--list` and `--remove` never read a harness tree.
- The manifest record: `schema` 2 exactly when `harness` is recorded, `harness` and
  `harness_files` with every validation rule in "Manifest", the refusal of a schema 1 manifest that
  has either key and of schema 2 without `harness`, the 4000-entry, 256-character-key and 512 KiB
  caps, and the pre-write check against the 1 MiB manifest limit.
- Install and refresh: the four "Collisions" rules and the update rules (the record as baseline,
  adoption of identical bytes, co-supplier updates, never deleting on `--update`, "exists" as
  `lexists` after folding), activation by `--add --harness` for built-in modules, placeholder
  substitution for harness files restricted to names matching `[A-Za-z0-9._ -]{1,200}`, and every
  harness write created `0644 & ~umask` without copying the mode of a file it replaces
  (`write_tree` change).
- `--remove`: the delete list from the record, the unedited test by recorded SHA-256, co-supplier
  handling, the `harness` key staying.
- Documentation of the user-visible behaviour in `README.md` ("Writing a module", Boundaries) and
  the neutrality test exemption ADR 0001 now allows for `harness/` directories.

## Non-goals

- No built-in module is converted and none ships a harness directory; the pilot is candidate 3. Tests
  use fixture module trees the way existing tests replace `MODULES_DIR`.
- `helpers`, `workers`, `global_config`, their reporting and the marker file (candidate 4);
  `harness.json` role matching and the worker report.
- External stores: `module_format` 3, the harness-tree digest, `--register` review, `--approve`,
  `--unapprove`, the approvals file and the verb table's store rows (candidate 8). External modules
  contribute nothing here, and `--update` behaves for them as today.
- Retiring `"harness": true`, the `claude` and `codex` module conversion (candidate 6) and any
  change to `claude_global_config`.
- `--update --merge` for harness files, and any change to `--merge`.

## Assumptions and constraints

- ADR 0004 is Accepted and the specification is Approved (2026-10-19); this plan does not reopen
  either. Where the specification is silent, the existing installer idiom applies and the choice is
  recorded in the Result.
- The manifest and every project file are untrusted (ADR 0002). A forged `harness_files` record is
  the main new capability, and removal of a recorded path is bounded by the destination check, the
  matching hash and `delete_files`.
- Verified in `install.py`: `assemble` slot-expands only files from `base/` and `files/`, so harness
  files must be added to the tree after expansion and never be slot-expanded; `write_tree`
  creates files `0666 & ~umask` and copies the mode of a replaced file; `load_manifest` enforces
  `schema == 1` and ignores unknown keys; `--update` and `--remove` read projects through
  `scan_project`; `cmd_list` and `cmd_remove` call only `load_modules`.
- An installer from before this work refuses a `schema` 2 manifest (exit 2, nothing written); this
  was confirmed against the real installer in scratch for plan 0017 and is re-checked here.
- No new dependency. Python standard library only (`unicodedata` for NFC, `hashlib` for SHA-256).
- Compatibility accepted by the specification: a project that records a harness cannot be changed by
  an older installer until it is upgraded. No project records one yet.

Graphify: skipped — no graph exists in this checkout (`graph_missing`), and the affected code is
enumerated directly from `install.py`: `build_parser`, `main`, `load_modules`, `collect_tree`,
`assemble`, `substitute`, `write_tree`, `delete_files`, `load_manifest`, `validate_optional_keys`,
`manifest_bytes`, `cmd_new`, `cmd_add`, `cmd_update`, `cmd_remove`, and `tests/test_install.py`.

## Completion criteria

A fixture built-in module with `harness/claude/` (a skill, an agent, a command and `root/CLAUDE.md`)
installs with `--new --harness claude`, appears in `harness_files` with its SHA-256, is added by
`--add --harness claude` to a project that had none, is refreshed by `--update` when unedited and
kept when edited, and is removed by `--remove` when unedited. Every acceptance criterion of the
specification that concerns built-in modules (1 to 7, 11, 12, 14, and the parts of 3, 6 and 10 that
need no store) has a test that failed before the change; a project without a harness has a
byte-identical manifest and tree; the full suite passes; an installer built from `30f08e5` refuses
the schema 2 project; an adversarial security review of the change has run and its findings are
decided; `git diff --check` is clean.

## Increments

### Increment A — Harness table and built-in tree reader

Dependencies: None
Affected areas: `install.py` (new `HARNESSES` table, `fold`, `read_harness_tree`, helpers),
`tests/test_install.py` (new `HarnessTreeTest`)

1. Write failing tests for: unknown harness name; a `harness/` directory name over 32 characters not
   echoed; each disallowed source entry (`settings.json`, `hooks/`, `.mcp.json`, a top-level file
   outside the list, `root/AGENTS.md`); every `harness.json` rule: a directory of that name,
   malformed JSON, a non-object, 16 KiB + 1, an unknown key, `roles` not an object, 17 roles, a
   role id outside `[a-z][a-z0-9-]{0,63}`, a target that is not a string, unsafe (`..`, `.git`, `\`,
   `:`), outside the directory, missing, or not a regular file, and a valid file accepted and
   otherwise ignored; path rules (`..`, `.git`, `\`, `:`, depth 9, case and NFC aliases including a
   code point whose fold order matters); a symlink or FIFO in the tree; limits (129 files, a
   directory with 129 entries, 256 KiB + 1, 2 MiB + 1) aborting at the first; NUL or invalid UTF-8;
   the three forbidden marker strings; an installed path equal to a `base/` or `files/` path (with
   `root/CLAUDE.md` compared as `CLAUDE.md`); frontmatter `name` read for a built-in unit and the
   unit name used without one; two units with the same name.
2. Implement the table (`claude`: root `.claude`, root-level `CLAUDE.md` for built-in modules,
   allowed entries, marker unused here), `fold(x) = NFC(casefold(NFC(x)))`, and
   `read_harness_tree(module, harness) -> {installed_relpath: bytes}` with an early-abort `scandir`
   walk, returning installed paths. A module with no directory for the harness returns `{}`.

Completion: the new tests pass, each `harness.json` and per-directory limit rule above has a test
that failed first, and no existing test changes.

### Increment B — Manifest record and validation

Dependencies: Increment A
Affected areas: `install.py` (`SCHEMA` handling in `load_manifest`, `validate_optional_keys`,
`manifest_bytes`, a shared manifest serializer with the size check), `tests/test_install.py`
(`HarnessManifestTest`)

1. Write failing tests for: schema 2 with a valid record loads; schema 2 without `harness`, schema 1
   with `harness` or `harness_files`, and `schema` `true` are refused; hostile keys (`README.md`,
   `.claude/settings.json`, `src/main.py`, `.template-manifest`, `/abs`, `..`, a key over 256
   characters, case-folded duplicates, a directory-shaped key), bad `sha256`, an unsorted,
   duplicated, empty or unknown supplier, more than 4000 entries and over 512 KiB; and that a
   manifest that would exceed 1 MiB is refused before any write.
2. Accept `schema` 1 or 2 by the rule in the specification, validate the record on load, write
   `schema` 2 with the record only when a harness is recorded, and route the three manifest writers
   (`cmd_new`, `cmd_add`, `cmd_update`/`cmd_remove`) through one function that enforces the size.

Completion: new tests pass; every existing manifest test still passes unchanged.

### Increment C — `--harness` and new projects

Dependencies: Increment B
Affected areas: `install.py` (`build_parser`, `main`, `write_tree`, `cmd_new`, install helpers for
collisions, substitution and the record), `tests/test_install.py` (`HarnessNewProjectTest`)

1. Write failing tests for: `--new --harness claude` installs the fixture's units under `.claude/`
   and `root/CLAUDE.md` as `CLAUDE.md`, records `harness` and `harness_files` with the SHA-256 of
   the installed bytes, and sets `schema` 2; no `--harness` installs no harness file and writes a
   manifest byte-identical to today's; an unknown name is refused before any write; `--harness`
   with `--list`, `--register`, `--unregister` or `--remove` is refused; two modules supplying the
   same path with different bytes fail the run before any write, identical bytes install once with
   both suppliers recorded; a path or unit equal to a `base/` file is refused; a project name
   outside `[A-Za-z0-9._ -]{1,200}` is refused when a harness file has a placeholder and fine
   otherwise; a module with no directory for the harness installs its neutral part and prints
   `<module>: no claude files`; the per-run limits across all selected modules, each module within
   its own limits, 513 harness files and 8 MiB + 1 in total, refused before any write with the walk
   aborting at the first; files are created `0644 & ~umask` (tested with umask 0, and a
   replaced 0755 or 4755 file in the `write_tree` unit test); `--dry-run` lists the files and writes
   nothing.
2. Add `--harness`, the option checks in `main`, and a `private` argument to `write_tree` that
   creates those paths `0644 & ~umask` and does not copy an existing mode. Build the harness part of
   the tree after slot expansion in `cmd_new`, apply the collision rule 1, and record suppliers. Count the per-run file and byte totals as modules are
read, and share that counter with `cmd_add` and `cmd_update`.

Completion: new tests pass, including both per-run limit cases; the existing `write_tree` and `--new` tests are unchanged.

### Increment D — `--add` and `--update`

Dependencies: Increment C
Affected areas: `install.py` (`cmd_add`, `cmd_update`, the collision and record helpers),
`tests/test_install.py` (`HarnessAddUpdateTest`)

1. Write failing tests for the command matrix (every cell of "Selection"); activation by
   `--add --harness` installing for every installed built-in module and recording the harness once;
   an external module installed earlier being named and not read; rules 2 to 4 against existing
   files (new path written, identical bytes adopted with the module added as supplier, differing
   bytes reported as a conflict with a summary count and not recorded, a `skills/<n>/` unit skipped
   whole, a symlink, directory or case alias at a destination a conflict); extra files in a skill
   directory left alone; `--update` replacing an unedited recorded path and updating its hash,
   leaving an edited one and reporting it, replacing a co-supplied path only when every supplier
   agrees, adopting identical bytes after a simulated interruption (new bytes, old hash), writing a
   file the module newly ships, and never deleting a dropped one; `--update` introducing no harness
   into a project that has none; `--dry-run` for both.
2. Implement the shared install-plan function used by `cmd_new`, `cmd_add` and `cmd_update`
   (existing paths from the project scan plus `lexists` after folding), the activation path, the
   record maintenance, and conflict and summary output. Leave the `--merge` code untouched.

Completion: new tests pass; the existing `--add` and `--update` tests are unchanged.

### Increment E — `--remove`

Dependencies: Increment D
Affected areas: `install.py` (`cmd_remove`), `tests/test_install.py` (`HarnessRemoveTest`)

1. Write failing tests for: a sole-supplier unedited file deleted with its emptied directories; an
   edited file kept, its record dropped and the run saying so; a missing file; a co-supplier
   removed from the record with the file kept until the last supplier goes; a path `base/` or a
   remaining module also ships never deleted; a forged key naming a file the module does not ship
   deleted only when the matching hash and the destination rules hold, and a directory-valued or
   non-regular record dropped without blocking the run; `harness` and `schema` 2 staying; removal
   reading no harness tree, store or registry (a corrupt harness tree in a still-installed module
   does not block it); `--dry-run`.
2. Build the delete list from the record limited to regular files in the project scan with a
   matching hash, pass it through the existing `delete_files` path, and update the record.

Completion: new tests pass; the existing `--remove` tests are unchanged.

### Increment F — Documentation and neutrality

Dependencies: Increment E
Affected areas: `README.md`, `docs/specs/module-harness-files.md` (status line only if needed),
`tests/test_install.py` (the neutrality test)

1. Write the failing test that the neutrality check ignores `harness/` directories and still
   covers `base/`, `slots/` and `files/`.
2. Document `harness/<harness>/`, `--harness`, the manifest keys and the older-installer refusal in
   the README sections the specification names ("Writing a module", Boundaries, usage), without
   describing declarations, stores or approval, which are not implemented.

Completion: `git diff --check` is clean and the README matches the behaviour tested above.

### Increment G — Verification and security review

Dependencies: Increment F
Affected areas: none expected beyond fixes

1. Run the full suite and the scratch checks under Verification.
2. Run an adversarial `security-reviewer` pass with the `security-review` skill on the diff and the
   real installer in scratch: a forged `harness_files` record, a symlink or directory at a
   destination, a case or NFC alias, a hardlinked destination, a tampered manifest edited between
   runs, a hostile project name, an interrupted run, and the older installer. Fix each reachable
   finding with a regression test that failed first, and record the rest with a reason.

Completion: the findings are decided and the suite is green.

## Verification

- `python3 -I -m unittest discover -s tests` (307 tests today plus the new ones; no existing test
  changes except the neutrality test in Increment F).
- Each new test is seen to fail before its implementation.
- In scratch: `git show 30f08e5:install.py` run with `--update --dry-run` against a project this
  work wrote with a harness exits 2 and writes nothing; a fixture project with and without
  `--harness` produces the manifest and tree the specification describes.
- Mutation checks on a scratch copy: removing the destination check on `harness_files` keys, the
  matching-hash test on removal, the case and NFC folding, and the private-mode argument each fail
  the new tests.
- `git diff --check`.

## Risks and sensitive actions

- Removal and replacement now act on paths named by an unauthenticated manifest record. The
  specification names this capability and its bounds; Increment E and G test them.
- Installed harness files are loaded automatically by the harness. No built-in module ships one in
  this plan, so nothing reaches a user's project until candidate 3.
- `write_tree` changes the mode behaviour for the new `private` paths only; existing callers keep
  today's behaviour.
- Public behaviour grows (`--harness`, `schema` 2). The specification is approved; no other public
  behaviour changes.
- No commit, push, dependency, secret or destructive action without the owner's request.

## Deferred work

- Declarations and the marker (candidate 4), the pilot (3), external stores and approval (8), the
  `claude` and `codex` conversion (6), and the rest of the roadmap.
- Frontmatter-key refusal for stores, pending confirmation of how the harness reads them.

## Result

Increments A to G are implemented and verified. Plan commit `652bc6f`; implementation `1049375`;
the specification erratum `cddf68f`. 105 tests are new (`HarnessTreeTest`, `HarnessManifestTest`, `HarnessNewProjectTest`,
`HarnessAddUpdateTest`, `HarnessRemoveTest`, `HarnessFindingsTest`, `HarnessSecondPassTest`) and the
suite passes with 412 tests. Each new test was seen to fail first, except the coverage tests added
after the second review for behaviour the code already had.

What changed in `install.py`: the harness table (`claude`), `fold`, the built-in tree reader
(`read_harness_tree`, `check_harness_json`, the per-module and per-run limits), the manifest record
(`schema` 2, `harness`, `harness_files`, `validate_harness_record`, `encode_manifest` with the size
and record checks the loader applies), `--harness` and `choose_harness`, `plan_harness` and
`report_harness` (collision rules, update baseline, co-suppliers, unit skipping), `write_tree(private=)`
for `0644 & ~umask`, and the harness parts of `cmd_new`, `cmd_add`, `cmd_update` and `cmd_remove`.
`read_regular` now reads at most its limit. README documents the behaviour ("Harness files", Layout,
Writing a module, Boundaries) and the neutrality test ignores installed harness files.

Choices where the specification was silent, all following the installer's existing idiom:
`harness.json` is validated and otherwise ignored until candidate 4; a module's `harness/` entries
are checked whenever the module is selected, installed or updated, with or without `--harness`;
`--add` and `--update` print `<module>: no <harness> files` for each module without a directory; a
conflict is reported with a summary count and does not change the exit status, as for files
`--update` keeps today; the reserved-path set covers every installed built-in module; the writer
validates the whole harness record before writing; a path written again keeps its other recorded
suppliers; and a stale record key that aliases a newly shipped path is a conflict.

Specification erratum (committed separately from the approved text): acceptance criterion 6 said a
forged key naming a file the module does not ship is refused on load. Load cannot tell it from a real
one, so it loads and `--remove` deletes it only when the hash matches, as the Trust model residual says.

Verification: `python3 -I -m unittest discover -s tests` passes with 412 tests; `git diff --check` is
clean. Mutation checks on scratch copies (destination check on record keys, matching-hash test on
removal, fold order, private create mode, private mode copy, unit-tree comparison, co-supplier rule)
each fail the new tests. An installer built from `30f08e5` refuses a schema 2 project for
`--update --dry-run`, `--update`, `--add` and `--remove` with exit 2 and "malformed", writing nothing
(also a test, skipped when that commit is not in the checkout). A scratch end-to-end run produced the
manifest and tree the specification describes.

Adversarial review (`security-reviewer`, scratch copies, two passes; no Critical or High finding):
- Pass 1: Medium: `--remove` deleted one path twice and failed mid-write; the writer accepted a record
  the loader refused (long keys, over 4000 entries); aliases between two modules in one run were not
  detected. Low: reserved paths covered only modules in the run; unknown or symlinked `harness/`
  entries were checked only with `--harness`; harness files were not excluded from `--remove`'s block
  scan and markers were checked before substitution; a rewritten path dropped co-suppliers; reads were
  unbounded after the stat check. All fixed with regression tests.
- Pass 2 (of the fixes): Medium: a stale record key could alias a newly written path and wedge the
  project; Low: a forged record could delete a user-edited file that `files/` had kept. Both fixed with
  tests, the first also by validating the record in `encode_manifest`. The pass confirmed the earlier
  fixes against bypass and ran the items pass 1 skipped (dry-run snapshots for each verb, hostile
  project names, schema 1 with harness keys, the older installer, hostile trees, huge or non-UTF-8
  existing files); it listed coverage gaps (interrupted runs, `--list` with a bad tree, an `--update`
  replace of a setuid file under umask 0, a role mapped to `root/CLAUDE.md`), which now have tests.
- Not reviewed again: the pass 2 fixes were verified by tests and the pass's own reproductions, not by
  a third review.
- Accepted residuals: a forged record naming a regular file with a known hash lets `--remove` or
  `--update` act on it (the specification's stated capability); the walk caps files and entries per
  directory but not the total directory count, and the top-level `harness/` listing is unbounded
  (both read only trusted module sources); `makedirs` creates directories with the process umask, as
  before.
- Not exercised: a case-sensitive filesystem (alias behaviour was checked in-process), real concurrent
  swaps between the walk and the read, and how Claude Code loads the installed files.

Not done (deferred above): declarations and the marker, the pilot, external stores and approval, and
the rest of the roadmap.

## Codex plan review

- Plan: docs/plans/next.md (key 155f342a3d4dfa56)
- Rounds used: 2 of 3
- Round 1: model gpt-5.6-luna, effort low, 2 finding(s) (2 blocker or major), 183646 input and 2182 output tokens
- Round 2: model gpt-5.6-luna, effort low, 0 finding(s) (0 blocker or major), 221030 input and 1979 output tokens
- Outcome: converged (no blocker or major finding in the last round)
- Decisions: 2 applied, 0 rejected
