# Retire the harness flag: claude as base harness files, codex as a tool module

Status: Approved
Created: 2026-10-19

## Goal

The `"harness": true` flag is gone. The `claude` entry-point files (`CLAUDE.md`, the runner contract stub
and the local-settings ignore line) are installed by `--harness claude` as the template's own base harness
files, so no project needs a `claude` module. The `codex` module keeps its name but becomes a module that
names only its tool and helper; its Claude packaging, the `second-opinion` skill, is a harness directory
beside it. Existing projects that list `claude` migrate on `--update`. This is roadmap candidate 6; ADR 0004
decision 3 fixes the direction.

## Scope

- Specification amendment (Increment A): the harness files document gains the base harness directory
  (`base/harness/<harness>/`, supplied by the reserved name `base`), the harness's own ignore block, the
  retired-module mechanism and the retirement of `"harness"` in `module.json`. The owner's approval of this
  plan is the approval of that amendment to the approved specification; it changes no accepted ADR text.
- Installer: `base` as a harness supplier (reading the tree, the record, collision and reserved-path rules,
  `--update` refreshing it, `--remove` never touching it); a `gitignore` entry in the harness table written
  as a fenced block (`BEGIN harness:claude` / `END harness:claude`) in the project's `.gitignore` when a
  harness is recorded; `RETIRED_MODULES = {"claude": ...}` so `--with claude` and `--add claude` mean
  `--harness claude` with a printed note, `--remove claude` explains, and `--update` migrates a project
  whose manifest lists `claude`; refusal of a `"harness"` key in a built-in `module.json`; `--list` loses the
  `(harness)` mark.
- Content: `base/harness/claude/` gets `root/CLAUDE.md` and `remote-runner.toml` (moved from
  `modules/claude/files/`); `modules/claude/` is deleted; `modules/codex/harness/claude/skills/second-opinion/`
  gets the skill from `claude_global_config/skills/second-opinion` (record its commit); the `codex` slots
  (`agents-guidance.md`, `plan-review.md`) are rewritten to name Codex and `ask-codex` but no skill, slash
  command or harness; `codex` declares `helpers: ["ask-codex"]`.
- Neutrality: the neutrality test no longer keys on a flag. It scans every module except those named for
  their own tool (`codex`), and `--harness claude` output ignores recorded harness files as before.
- Tests: the migration, the base supplier, the ignore block, the alias and retirement behaviour, the codex
  harness files and declarations; the roughly 40 existing tests that use `claude` as a generic fixture module
  move to a neutral fixture or to `--harness claude`.
- README and ADR notes: usage, "Writing a module" (the flag rule becomes the tool-named-module rule), the
  migration for existing projects.

## Non-goals

- Any change to `ask-codex` or anything in `claude_global_config`: removing the global `second-opinion` skill,
  its manifest lines and tests. Listed in the Result for the owner.
- External stores, approvals, a harness other than `claude`, and the global-configuration cleanup (candidate 10).
- Renaming or removing the `codex` or `plan-review` modules; `plan-review` is unchanged.
- Changing the content of the `second-opinion` skill beyond what the move requires.

## Assumptions and constraints

- ADR 0004 and the approved specification are the authority; the amendment in Increment A fills the one gap
  they leave (the base case) and is part of this plan's approval. Plans 0018 to 0022 provide harness files,
  declarations and the dependency report this plan builds on.
- Verified in the sources: `harness` is read in `install.py` only as a default (`False`) and by `cmd_list`; the
  `claude` module is `files/CLAUDE.md`, `files/.claude/remote-runner.toml` and `slots/gitignore.md` (the
  `/.claude/settings.local.json` line); `codex` has two slots that name `second-opinion`, `ask-codex` and
  Claude; `second-opinion` is one 7.7 KB file with no path to the global configuration.
- Compatibility accepted: a project created before this change lists `claude` in `modules`. The new installer
  migrates it on `--update`; an installer from before this change fails closed on the new `schema` 2 manifest
  that migration writes, as it already does for any recorded harness.
- Choices to confirm in review (the specification is silent or the trade-off is the owner's): (1) the
  reserved supplier `base` versus keeping a `claude` module as the carrier; (2) the ignore line as a fenced
  block the installer writes, versus an ignore file in the harness tree or `.git/info/exclude`; (3) `--with
  claude` as a deprecated alias that works with a note, versus an error; (4) automatic migration on `--update`
  versus a documented manual `--add <module> --harness claude`; (5) exempting only tool-named modules
  (`codex`) from the neutrality scan, versus keeping a flag-like marker in `module.json`.
- The test churn is real: about 40 tests use `claude` as a convenient module (`ALL`, the `--with` parsing
  cases, the runner stub, the manifest cases). They are adapted, not deleted, and the plan counts them.
- Python standard library only; no dependency, secret or network access.

Graphify: skipped — no graph exists in this checkout (`graph_missing`), and the affected code and files are
enumerated: `install.py` (`load_modules`, `cmd_list`, `read_harness_tree` callers, `prepare_harness`,
`plan_harness`, `validate_harness_record`, `cmd_new`, `cmd_add`, `cmd_update`, `cmd_remove`, `parse_entries`),
`base/`, `modules/claude/`, `modules/codex/`, `tests/test_install.py`, `README.md`, and
`docs/specs/module-harness-files.md`.

## Completion criteria

`./install.py <target> --with codex,plan-review --harness claude` installs `CLAUDE.md`,
`.claude/remote-runner.toml`, the `.gitignore` block and the `second-opinion` skill, recorded with suppliers
`base` and `codex`; without `--harness` none of them; `--with claude` works as `--harness claude` with a note;
a project created by the previous commit's installer with `--with claude,codex` is migrated by `--update`
(modules, record, ignore block, files adopted or reported) and a second `--update` is a no-op; `--remove`
never deletes a `base` file; a `"harness"` key in a built-in `module.json` is refused; the neutrality test
passes with and without `--harness`; the specification, README and roadmap match; the suite passes; an
adversarial review of the installer changes has run and its findings are decided; `git diff --check` is clean.

## Increments

### Increment A — Amend the specification

Dependencies: None
Affected areas: `docs/specs/module-harness-files.md`

1. Add the base harness directory (the reserved supplier `base`, its record entries, update and removal
   rules, the collision rule against `base/` files), the harness ignore block, the retired-module mechanism
   with its migration rule, and the refusal of the retired `"harness"` key; update the amended-clauses table
   and the open-points table. Link ADR 0004 decision 3.

Completion: every behaviour in Increments B to E is stated in the specification with acceptance criteria.

### Increment B — Base harness files

Dependencies: Increment A
Affected areas: `install.py` (`read_harness_tree` callers, `prepare_harness`, `validate_harness_record`,
`plan_harness`, `cmd_new`, `cmd_add`, `cmd_update`, `cmd_remove`), `base/harness/claude/` (new),
`tests/test_install.py` (`BaseHarnessTest`)

1. Write failing tests: `--new --harness claude` installs `CLAUDE.md` and `.claude/remote-runner.toml` from
   `base/harness/claude/` with the project id substituted, recorded with supplier `base`; no `--harness`
   installs none; activation by `--add --harness` installs them once; `--update` replaces an unedited file and
   keeps an edited one; `--remove` of any module never deletes or unrecords a `base` path; a manifest record
   naming `base` loads and one naming another unknown supplier is refused; a `base` path equal to a `base/`
   or `files/` path is refused; the hostile-tree cases of plan 0018 hold for `base/harness`.
2. Move `modules/claude/files/CLAUDE.md` and `.claude/remote-runner.toml` to `base/harness/claude/root/` and
   `remote-runner.toml`; supply `base` in the three commands and the record validator.

Completion: the new tests pass.

### Increment C — The harness ignore block

Dependencies: Increment B
Affected areas: `install.py` (the harness table, a block writer used by `cmd_new`, `cmd_add`, `cmd_update`),
`tests/test_install.py`

1. Write failing tests: a recorded harness adds one fenced `harness:claude` block with
   `/.claude/settings.local.json` to `.gitignore`; activation adds it once and a rerun is a no-op; `--update`
   restores an edited block and leaves text outside it alone; a project without a harness has none; a missing
   or symlinked `.gitignore` is handled as the other base files are; the block never touches `.git`.
2. Add `gitignore` to the table and the block writer.

Completion: the new tests pass.

### Increment D — Retire the `claude` module and the flag

Dependencies: Increment C
Affected areas: `install.py` (`RETIRED_MODULES`, `parse_entries`, `cmd_new`, `cmd_add`, `cmd_update`,
`cmd_remove`, `cmd_list`, `load_modules`), `modules/claude/` (deleted), `tests/test_install.py`

1. Write failing tests: `--with claude` and `--add claude` behave as `--harness claude` and print the note
   (also when `--harness` is given, and refused beside a different harness); `--list` shows no `claude` and no
   `(harness)` mark; `--remove claude` explains and writes nothing; `--update` of a manifest listing `claude`
   migrates (drops it from `modules` and `module_info`, records the harness, adopts identical files and
   reports conflicts, converts the old `BEGIN module:claude` block into the new block, refreshes
   `template_commit`) and a second `--update` is a no-op; a hostile manifest cannot use the migration to touch
   another path; a `"harness"` key in a built-in `module.json` is refused with a message naming the new way.
2. Implement the above and delete `modules/claude/`.

Completion: the new tests pass.

### Increment E — The `codex` module and the `second-opinion` skill

Dependencies: Increment D
Affected areas: `modules/codex/` (`module.json`, `slots/*.md`, new `harness/claude/skills/second-opinion/`),
`tests/test_install.py` (`CodexHarnessTest`)

1. Write failing tests: the codex slots contain no skill name, slash command or harness product; the module
   declares `helpers: ["ask-codex"]`; `--with codex,plan-review --harness claude` installs the skill, records
   it with supplier `codex`, and prints the helper line; without the harness only the neutral text installs;
   the skill text names no path under the global configuration.
2. Rewrite the slots, copy the skill unchanged, and add the declaration and the harness hint.

Completion: the new tests pass.

### Increment F — Adapt the existing tests, neutrality and documentation

Dependencies: Increment E
Affected areas: `tests/test_install.py`, `README.md`, `docs/roadmaps/module-harness-files.md`

1. Change the neutrality test to scan every module except tool-named ones and to ignore recorded harness
   files; move the `claude`-as-fixture tests to a neutral fixture module or to `--harness claude`, keeping one
   alias test each for `--with` parsing and `--add`.
2. Update the README (usage, "Writing a module", migration for existing projects, the Modules table) and the
   roadmap.

Completion: the suite is green with no test deleted without a replacement, and the README matches.

### Increment G — Verification and security review

Dependencies: Increment F
Affected areas: none expected beyond fixes

1. Run the full suite and the scratch checks under Verification.
2. Run an adversarial `security-reviewer` pass with the `security-review` skill on the installer changes: the
   migration (a forged manifest listing `claude`, a `.gitignore` that is a symlink or holds a hostile block,
   conflicting files), the `base` supplier (a forged record, a project file at a base path), the ignore block
   writer, the alias, and the earlier-installer interaction. Fix each reachable finding with a regression test
   that failed first and record the rest with a reason.

Completion: the findings are decided and the suite is green.

## Verification

- `python3 -I -m unittest discover -s tests` (610 tests today plus the new ones); each new test is seen to fail
  before its implementation.
- In scratch: build a project with the previous commit's installer (`b1af3e9`) with `--with claude,codex,graphify`,
  run the new installer's `--update` twice, and compare the tree and manifest with a fresh `--with codex,graphify
  --harness claude` project; confirm an installer from before this change refuses the migrated manifest.
- Mutation checks on a scratch copy: letting `--remove` delete a `base` path, accepting an unknown supplier, a
  migration that follows a symlinked `.gitignore`, and the alias bypassing the harness check each fail the tests.
- `git diff --check`.

## Risks and sensitive actions

- The migration rewrites a manifest and `.gitignore` in existing projects. It never commits, runs only on an
  explicit `--update`, reports every conflict and keeps edited files; Increment G reviews it adversarially.
- Removing the `claude` module changes a name users type; the alias keeps `--with claude` working for now.
- A large test migration can hide a lost case; each moved test is replaced one for one and the count is recorded.
- The specification amendment is approved with this plan; it adds the base case only.
- No commit, push, dependency, secret or destructive action without the owner's request.

## Deferred work

- In `claude_global_config`: remove `skills/second-opinion`, its `config-manifest.txt` lines and tests; no change
  to `ask-codex`. The global `CLAUDE.md` does not name the skill today.
- Removing the deprecated `--with claude` alias in a later release; candidates 8, 9 and 10 of the roadmap.

## Result

<!-- Complete this only after verification. Archive the plan according to
docs/plans/README.md, then reset this file to the empty template. -->
