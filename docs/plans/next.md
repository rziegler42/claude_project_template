# Declarations and reporting

Status: In Progress
Created: 2026-10-19

## Goal

A built-in module can declare in `module.json` the helpers, worker roles and global configuration its
harness files depend on, and `install.py` reports each one as present or missing at `--new`, `--add`
and `--update`, without ever installing, running or failing on one. This is roadmap candidate 4,
implementing the "Declarations in `module.json`" section of the approved
[specification](../specs/module-harness-files.md) for built-in modules.

## Scope

All of it follows `docs/specs/module-harness-files.md`; section names are that document's.

- `module.json` keys `helpers` (at most 16 unique names matching `[A-Za-z0-9][A-Za-z0-9._-]{0,63}\Z`),
  `workers` (at most 16 entries of role id, `[a-z][a-z0-9-]{0,63}\Z`, to a printable one-line contract of
  1 to 200 characters) and `global_config` (a boolean), validated when the module loads.
- Helper detection: a file of that name in an absolute `PATH` directory that is a regular file after
  `stat` and executable by the user; never run. Reported with or without a harness.
- The marker file: one fixed name per harness in the table (`claude`: `~/.claude/global-config.json`),
  found through the account's home directory from the password database, never `HOME`; a new
  `--global-config DIR` option makes the marker `DIR/global-config.json`; an empty or relative home or
  `DIR` reports it missing. It is read with the hardened regular-file read (a symlinked final component is
  refused, a symlinked parent is fine), at most 4 KiB read with a limit of one byte more, valid UTF-8, a
  JSON object whose `schema` is the integer 1 (not a boolean or float); any other state, including a
  recursion error, is `missing (unreadable or invalid marker)` and its contents are never echoed.
- Worker roles: the module's `harness.json` `roles` map is read for the project's harness; a role is
  reported implemented only when the module declared it, `harness.json` maps it, and the mapped file is
  recorded for that module in `harness_files` after the run (a file skipped as a conflict does not count).
- Reporting: one line per item for the modules in the run, printed after the other output of `--new`,
  `--add` and `--update` (including `--dry-run`), with no effect on the exit status. For `--add` the
  modules in the run are the ones it adds, plus every installed built-in module when it activates a
  harness; an `--add` that finds everything already installed and activates nothing prints "Nothing to
  add" and no declaration lines, because it did no work, and `--update` is how an installed module is
  checked again.
- README documents the keys, the report and `--global-config`.

## Non-goals

- No module is converted and none declares anything yet; tests use fixture module trees. The `graphify`,
  `plan-review`, `codex` and `formal` declarations come with their own candidates.
- External stores: `module_format` 3 declarations, the harness-tree digest and approval (candidate 8).
- Writing the marker file, which is the global configuration's job (candidate 10), and anything in
  `claude_global_config`.
- Installing, locating by any means other than `PATH`, or running a helper; verifying that a file
  implements a role; a change to `--list` output.

## Assumptions and constraints

- ADR 0004 is Accepted and the specification Approved; plan 0018 delivered the harness record,
  `harness.json` validation and `plan_harness` this plan reads. Where the specification is silent, the
  installer's idiom applies and the choice is recorded in the Result.
- The marker is the one new read outside the target, the template and the registry (ADR 0002
  addendum); anyone with the owner's account can forge it and it only changes what is reported. `PATH`
  entries are inspected with `stat` and `access`, never executed.
- Choices to confirm in review, because the specification is silent: with no harness recorded, a
  `global_config` module reports "no harness selected" (the marker is per harness); `--global-config`
  is accepted with `--new`, `--add` and `--update` and refused with the other actions; a module's lines
  are prefixed with its name.
- Verified in `install.py`: `load_modules` validates `hint` and `module_info` keys at load and accepts
  unknown keys; `read_regular` already reads at most its limit; `prepare_harness` and `plan_harness`
  give the final `harness_files` record for each run.
- No new dependency; `pwd` and `os.access` are standard library, and a missing `pwd` (non-POSIX)
  reports the marker missing.

Graphify: skipped — no graph exists in this checkout (`graph_missing`), and the affected code is
enumerated: `load_modules`, `HARNESSES`, `build_parser`, `main`, `cmd_new`, `cmd_add`, `cmd_update`,
`prepare_harness`, `plan_harness`, `report_harness`, and `tests/test_install.py`.

## Completion criteria

A fixture module declaring two helpers, a worker role and `global_config` reports each as present or
missing for `--new`, `--add` and `--update` with and without a harness, with the exit status unchanged
for a missing item; every bound of the three keys, every marker state in the specification (present,
absent, symlink, directory, oversized, not JSON, not UTF-8, deeply nested, `schema` `true` or `1.0`, a
relative or empty home) and every helper state (executable, not executable, directory, relative `PATH`
entry, empty entry) has a test that failed before the change; the marker is found through the password
database although `HOME` points elsewhere; a fake executable on `PATH` is never run; the suite passes; an
adversarial review of the new reads has run and its findings are decided; `git diff --check` is clean.

## Increments

### Increment A — Declarations in `module.json`

Dependencies: None
Affected areas: `install.py` (`load_modules`, a `declarations_problem` helper),
`tests/test_install.py` (`DeclarationTest`)

1. Write failing tests: a valid module loads with `helpers`, `workers` and `global_config` kept on its
   record; each bound is refused with the module named: `helpers` not a list, a non-string, a bad name
   (leading dot, space, slash, over 64 characters, a trailing newline), a duplicate, 17 entries;
   `workers` not an object, a bad role id, an empty, over-200, multi-line or non-printable contract, a
   non-string contract, 17 entries; `global_config` not a boolean (including `1`, `"true"`); exact-limit
   values accepted; a module with none of the keys is unchanged.
2. Implement `declarations_problem(meta)` next to `module_info_problem` and call it in `load_modules`.

Completion: the new tests pass and no existing test changes.

### Increment B — Marker, helpers and `--global-config`

Dependencies: Increment A
Affected areas: `install.py` (`HARNESSES` marker name, `home_directory`, `read_marker`, `find_helper`,
`build_parser`, `main`), `tests/test_install.py` (`MarkerTest`, `HelperTest`)

1. Write failing tests for every marker state in the Completion criteria, each asserting the report
   state and that the file's contents never appear; the password-database lookup (patch `pwd.getpwuid`
   with a home holding a marker while `HOME` points at an empty directory); a missing `pwd` module; an
   empty or relative home; `--global-config DIR` redirecting the marker; `--global-config` refused with
   `--list`, `--register`, `--unregister` and `--remove`. For helpers: an executable file, a file
   without the execute bit, a directory of that name, a symlink to an executable, a relative `PATH`
   entry, an empty entry, an unset `PATH`, and a fake executable that records a run, asserted never run.
2. Add the marker name to the table, `read_marker(harness, global_config_dir)` returning `"present"`,
   `"missing"` or `"missing (unreadable or invalid marker)"`, `find_helper(name)`, and the option.

Completion: the new tests pass and existing tests are unchanged.

### Increment C — Reporting for new, add and update

Dependencies: Increment B
Affected areas: `install.py` (`read_harness_roles`, `report_declarations`, `cmd_new`, `cmd_add`,
`cmd_update`), `tests/test_install.py` (`DeclarationReportTest`)

1. Write failing tests with fixture modules for: one line per helper, worker and global configuration
   for `--new`, `--add` and `--update`, each also with `--dry-run`; a role implemented (declared,
   mapped, recorded); a role the module declared but `harness.json` does not map, a module with no
   directory for the harness, and a mapped file skipped as a conflict, each a warning with the
   contract; a role in `harness.json` that the module did not declare printing nothing; a project
   with no harness printing "no harness selected" for workers and `global_config` while helpers are
   still checked; a missing helper and a missing marker leaving the exit status 0; activation by
   `--add --harness` reporting every installed built-in module; modules without declarations printing
   nothing; and the narrowed `--add` path: naming an already-installed declaring module with and
   without a recorded harness prints "Nothing to add" and no declaration lines, while `--update`
   reports that module.
2. Implement `read_harness_roles(module, harness)` (the validated `harness.json` roles as installed
   paths) and `report_declarations(...)`, and call it after the harness report in the three commands.

Completion: the new tests pass and existing tests are unchanged.

### Increment D — Documentation

Dependencies: Increment C
Affected areas: `README.md`

1. Document the three keys, the report lines, `--global-config` and the marker location in the README
   ("Writing a module", "Harness files"), without describing external stores or approval, and update
   the sentence that says declarations are not implemented.

Completion: the README matches the behaviour tested above and `git diff --check` is clean.

### Increment E — Verification and security review

Dependencies: Increment D
Affected areas: none expected beyond fixes

1. Run the full suite and the scratch checks under Verification.
2. Run an adversarial `security-reviewer` pass with the `security-review` skill on the new reads: the
   marker (symlink, FIFO, huge, hostile JSON, a symlinked parent, `--global-config` values, an empty or
   relative home, a missing password entry) and `PATH` inspection (relative, empty and symlinked
   entries, loops, a helper that is a FIFO or socket, names that cannot be validated), and that nothing
   is run, echoed or written. Fix each reachable finding with a regression test that failed first and
   record the rest with a reason.

Completion: the findings are decided and the suite is green.

## Verification

- `python3 -I -m unittest discover -s tests` (425 tests today plus the new ones).
- Each new test is seen to fail before its implementation.
- In scratch: a fixture module declaring `ask-codex`-like helpers, two roles and `global_config`,
  installed with and without `--harness claude`, with a fake executable on `PATH` that records a run
  and a marker under `--global-config`; check the report lines, the exit status and that the fake is not
  run.
- Mutation checks on a scratch copy: using `HOME`, accepting `schema` `true`, following a symlinked
  marker, accepting a non-executable file, and counting a conflict-skipped file as implemented each
  fail the new tests.
- `git diff --check`.

## Risks and sensitive actions

- A new read outside the target and a `PATH` walk. Both are read-only and bounded; Increment E tests
  hostile inputs.
- Output could mislead if a marker or helper were forged; the lines say only present or missing and
  never change what is installed.
- Public behaviour grows (`module.json` keys, `--global-config`, report lines); the specification is
  approved.
- No commit, push, dependency, secret or destructive action without the owner's request.

## Deferred work

- Converting the first real module to declare dependencies (candidates 5, 6 and 7).
- The marker's writer in `claude_global_config` (candidate 10).
- External-store declarations (candidate 8).

## Result

Increments A to E are done and verified; the plan commit is `d6558a7` and the work is uncommitted. The
suite passes with 473 tests (425 before, 48 new in `DeclarationTest`, `MarkerTest`, `HelperTest` and
`DeclarationReportTest`).

- Increment A: `declarations_problem` validates `helpers`, `workers` and `global_config` when a module
  loads; a module without them has empty declarations.
- Increment B: `read_marker`, `marker_path`, `home_directory` (password database, never `$HOME`),
  `find_helper` (absolute `PATH` entries, regular and executable, never run), the marker name in the
  harness table, and `--global-config DIR`, refused with `--list`, `--register`, `--unregister` and
  `--remove`.
- Increment C: `report_declarations` (through `report_safely`), `read_harness_roles`; one line per item
  for the modules in the run after the other output of `--new`, `--add` and `--update`, with no effect
  on the exit status. A role counts as implemented only when its file is recorded for the module after
  the run.
- Increment D: README "Declared dependencies" section and the module layout text.
- Choices where the specification was silent: with no harness a `global_config` module reports "no
  harness selected"; `--global-config` is refused with the other actions; lines are prefixed with the
  module name; `--dry-run` words a role as `would be implemented`; a failing report prints one note and
  never fails the run (the report runs after the writes in `--new` and `--add`).

Verification: `python3 -I -m unittest discover -s tests` passes with 473 tests; `git diff --check` is
clean. Mutation checks on scratch copies (no report, `$HOME` instead of the password database, accepting
`schema: true`, accepting a non-executable helper, accepting a relative `PATH` entry, counting a
conflict-skipped file as implemented, accepting a relative marker directory) each fail the new tests; a
mutation that followed a symlinked marker hung on a FIFO, which the real code refuses before opening.
The first draft of the report tests ran with `PATH` limited to the fixture directory, which broke `git`,
so they failed for the wrong reason; they now keep the real `PATH` and the mutation checks confirm they
fail for the right ones.

Adversarial review (`security-reviewer`, scratch copies, one pass): no Critical, High or Medium finding.
The marker, `PATH` and `module.json` reads held against every case tried (symlinked or FIFO or device
marker, 4096 and 4097 bytes, a file that grew after `lstat`, hostile JSON, a hostile `$HOME`, odd
`pwd` values, `--global-config` values with NUL, newline or 70 KB, relative and empty `PATH` entries,
loops, a fake executable on `PATH` that was never run, hostile declarations, and dry-run snapshots).
- Low, applied: the report was documented as never failing but had no guard; `report_safely` now
  catches any exception and prints one note, with a test that a failing report leaves a complete install.
- Low, applied: a dry run said "implemented" although nothing is installed yet; it now says "would be
  implemented".
- Low, not applied: `isprintable()` accepts Unicode lookalikes in a contract (a Cyrillic letter prints as
  itself). Control, bidi and line-separator characters are refused; `module.json` is trusted template
  code under ADR 0002, so the effect is cosmetic and restricting contracts to ASCII would only cost
  legitimate text.
- Test gaps the review listed, now covered: the 4096 and 4097 boundary was already tested; added a size
  that grew after `lstat`, a symlink to `/dev/zero`, NUL, newline and very long `--global-config`
  values, a `PATH` symlink loop, `--global-config` leaving the tree and manifest unchanged, dry runs of
  `--add` and `--update` with a declaring module, and a failing report; the vacuous "real modules
  declare nothing" test is now "every real module passes the declaration rules".
- Not exercised: executability by another uid or a setuid `PATH` directory, real `getpwuid` anomalies
  (patched only), a genuine concurrent file-growth race (simulated by patching `lstat`), and a user-edited
  harness file conflicting during `--update` as it affects the "implemented" label.

Residual: the "implemented" label follows the planned record, not the disk, so a file the user deleted
still reads as implemented until `--update` restores it.

Not done (deferred above): converting a real module to declare dependencies (candidates 5, 6, 7), the
marker's writer in `claude_global_config`, and external-store declarations.
