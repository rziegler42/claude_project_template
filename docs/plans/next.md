# Ship the verilog-sby-formal skill in formal

Status: In Progress
Created: 2026-10-19

## Goal

The `formal` module ships the `verilog-sby-formal` skill in `harness/claude/`, so
`install.py ... --with formal --harness claude` puts the skill in the project's
`.claude/skills/verilog-sby-formal/` instead of leaving it only in a developer's global configuration.
This is the template side of roadmap candidate 7, repeating the `cad-freecad` pilot (plan 0019); the
global-configuration side is a separate plan in `claude_global_config`.

## Scope

- Copy the skill into `modules/formal/harness/claude/skills/verilog-sby-formal/`: `SKILL.md` (about
  10 KB) and `reference.md` (about 11 KB). The source is `claude_global_config/skills/verilog-sby-formal`
  at its commit `18a3107`, identical to `~/.claude/skills/verilog-sby-formal`; record the commit in the
  Result. No text changes are expected: the files contain no path to the global install, no helper and
  no placeholder, and the skill refers to its reference as "beside this file".
- Tests with the real module: the tree reads clean and is exactly the two files, and `--new`, `--add`,
  `--update` and `--remove` behave as for `cad-freecad`.
- README: the Modules table row, the "Harness files" section (which names `cad-freecad` as the first
  module to ship harness files) and a one-line `hint` on `formal`.

## Non-goals

- Anything in `claude_global_config`: removing the global copy and its `config-manifest.txt` lines,
  and the global `CLAUDE.md` rule that routes SymbiYosys work to `verilog-sby-formal` (line 95 today),
  which assumes the skill is always loaded. Those are the owner's, listed in the Result.
- `verilog-verilator-sim`, which has no module and stays global unless the owner adds a module for it.
- Editing the skill's guidance; its content is the owner's.
- Declarations, a `workers` role or the marker for this module, and the other candidates.

## Assumptions and constraints

- Plans 0018 to 0020 are complete: a built-in `harness/claude/` tree installs under `--harness claude`
  within the specification's limits (two files, 21 KB in all).
- Verified on the source: both files are UTF-8 without NUL or CR; neither contains a placeholder, a slot
  marker, a block marker, a path to `~/.claude`, or a helper or tool name; the frontmatter `name` is
  `verilog-sby-formal`, the unit name; the global copy and the repository copy are identical.
- The module's neutral text (`slots/agents-guidance.md`) stays tool-neutral and unchanged; nothing outside
  `harness/` may name the skill, and the neutrality test keeps checking that, now also with
  `--harness claude`.
- While both copies exist, the project copy takes precedence in a project that installs it (ADR 0004).
- Python standard library only; no dependency, secret or network access.

Graphify: skipped — no graph exists in this checkout (`graph_missing`), and the affected files are
enumerated above: `modules/formal/` (`module.json`, new `harness/claude/skills/verilog-sby-formal/`),
`tests/test_install.py` and `README.md`.

## Completion criteria

`./install.py <target> --with formal --harness claude` installs `SKILL.md` and `reference.md` under
`.claude/skills/verilog-sby-formal/` and records both in `harness_files` with `formal` as supplier;
without `--harness` nothing is installed and the manifest is unchanged; `--update` leaves an unedited
tree alone and keeps an edited file with a conflict report; `--remove formal` deletes the unedited files
and the emptied directories. Every built-in harness tree still passes the reader; the neutrality test
passes with and without `--harness`; the installed bytes equal the source; the suite passes;
`git diff --check` is clean.

## Increments

### Increment A — Ship the skill in the module

Dependencies: None
Affected areas: `modules/formal/harness/claude/skills/verilog-sby-formal/` (new),
`tests/test_install.py` (`HarnessFormalTest`)

1. Write failing tests against the real module: `read_harness_tree` returns exactly the two installed
   paths under `.claude/skills/verilog-sby-formal/`; the unit map is `{".claude/skills/verilog-sby-formal":
   "verilog-sby-formal"}`; no installed file mentions `~/.claude`; `SKILL.md` points at `reference.md`
   beside it.
2. Copy the two files from the source unchanged.
3. Confirm the copy is byte-identical to the source.

Completion: the new tests pass and the copy equals the source.

### Increment B — Behaviour with the real module

Dependencies: Increment A
Affected areas: `tests/test_install.py`

1. Write tests with the real module and the real `base/`: `--new --with formal --harness claude`
   installs and records both files; the same without `--harness` installs none and keeps `schema` 1;
   the `--add` paths: `--add formal --harness claude` to a project with no harness activates it and
   installs the skill for `formal` (added in the same run); `--add formal` without the option installs only
   the neutral part and no `.claude`; `--add formal` to a project that already records `claude` installs
   the skill; and `--add formal --harness claude` where `formal` is already installed and the project has
   no harness activates it and installs the skill. `--update` is a no-op on an unedited tree and keeps an
   edited file with a conflict report; `--remove formal` deletes the unedited files and the emptied
   directories and keeps an edited one.
2. Confirm that the existing neutrality test with `--harness claude` now covers `formal` and still passes,
   and that every built-in harness tree reads clean (the generic hygiene test).

Completion: the new tests pass and no existing test changes. With the skill directory removed from a
scratch copy, the new tests fail.

### Increment C — Documentation and hint

Dependencies: Increment B
Affected areas: `README.md`, `modules/formal/module.json`

1. Add a `hint` to `formal` (one line, at most 200 characters) saying that `--harness claude` also
   installs the SymbiYosys skill.
2. Update the README Modules table row and the "Harness files" section so that `formal` and
   `cad-freecad` are both named as shipping harness files.

Completion: the hint prints under "Next steps" for a new install and `--add`; the README matches the
behaviour tested above.

### Increment D — Verification

Dependencies: Increment C
Affected areas: none expected

1. Run the full suite and the scratch checks under Verification.
2. Record the source commit, the sizes and the follow-up for `claude_global_config` in the Result.

Completion: the Result lists the evidence and the open items for the other repository.

## Verification

- `python3 -I -m unittest discover -s tests` (473 tests today plus the new ones).
- Each Increment A test is seen to fail before the copy; the Increment B tests are shown to fail with the
  skill directory removed from a scratch copy.
- In scratch: install with `--with formal --harness claude`, `cmp` the installed files against the source,
  run `--update --dry-run`, edit one file and rerun `--update`, then `--remove formal`; and on a project
  created without the option, `--add formal --harness claude --dir <project>` installs the skill.
- `git diff --check`.
- Security review: skipped — no code changes; the files are the owner's own skill text, and the installer
  paths they take were reviewed adversarially under plan 0018.

## Risks and sensitive actions

- The skill is loaded automatically by Claude Code in every project that installs it; it is the same text
  the owner already loads globally.
- Duplicate copies (global and project) can drift until the global one is removed; the follow-up in
  `claude_global_config` closes that.
- The global `CLAUDE.md` routing rule assumes the skill is always loaded. Once the global copy is removed,
  a project without the harness copy has no such skill, so that rule needs rewording in the other
  repository at the same time.
- No commit, push, dependency, secret or destructive action without the owner's request.

## Deferred work

- In `claude_global_config`: remove `skills/verilog-sby-formal` and its `config-manifest.txt` lines,
  update the tests and sync that name it, and reword or keep the `CLAUDE.md` routing rule.
- Existing projects that use `formal` can run `install.py --add formal --harness claude --dir <project>`.

## Result

Increments A to D are done and verified; the plan commit is `8c322f0` and the work is uncommitted. The
suite passes with 482 tests (473 before, 9 new in `HarnessFormalTest`).

- Increment A: the skill is in `modules/formal/harness/claude/skills/verilog-sby-formal/` (`SKILL.md`,
  9,950 bytes, and `reference.md`, 11,037 bytes), copied unchanged from
  `claude_global_config/skills/verilog-sby-formal` at its commit `18a3107` (identical to
  `~/.claude/skills/verilog-sby-formal`); `cmp` confirms both files are byte-identical to the source.
  Seven of the nine new tests failed before the copy.
- Increment B: tests with the real module and `base/` for `--new`, the four `--add` paths (activation for
  a module added in the same run, no option installing only the neutral part, a recorded harness, and
  activation for an already-installed module), `--update` (a no-op on an unedited tree, a reported
  conflict on an edit) and `--remove` (unedited files and emptied directories deleted, an edited
  `reference.md` kept). The existing neutrality test with `--harness claude` and the generic hygiene test
  cover `formal` automatically. With the harness directory removed from a scratch copy the new tests fail
  (3 failures, 3 errors); the three that still pass do not depend on the skill.
- Increment C: `formal` has a one-line `hint`; the README Modules row and the "Harness files" section name
  both `formal` and `cad-freecad`, with the `--add <module> --harness claude` route for existing projects.
- Increment D: a scratch install with `--with formal --harness claude` produced both files at mode 0644,
  byte-identical to the source; `--update --dry-run` reported nothing to update; an edit to `reference.md`
  was kept with a conflict report; `--remove formal` kept it and removed the rest; a project created without
  the option received the skill from `--add formal --harness claude`. `git diff --check` is clean.

Choices where the plan was silent: none beyond repeating the pilot; the hint prints on every install of the
module, as the other hints do.

Security review: skipped, as planned (no code changes; owner-authored text; installer paths reviewed under
plan 0018).

For the owner, in `claude_global_config` (not touched): remove `skills/verilog-sby-formal` and its
`config-manifest.txt` lines, update the tests and sync that name it, and reword the global `CLAUDE.md` rule
(line 95 when checked) that routes SymbiYosys work to the skill, since a project without the harness copy
would otherwise name a skill that is not loaded. Until the global copy is removed both exist and the project
copy takes precedence where installed. Existing projects that use `formal` can run
`install.py --add formal --harness claude --dir <project>`.
