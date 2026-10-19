# Pilot: freecad-scripts skill in cad-freecad

Status: In Progress
Created: 2026-10-19

## Goal

The `cad-freecad` module ships the `freecad-scripts` skill in `harness/claude/`, so
`install.py ... --with cad-freecad --harness claude` puts the skill in the project's
`.claude/skills/freecad-scripts/` instead of leaving it only in a developer's global configuration. It
proves the harness-file mechanism (plan 0018) on a real module that needs no helper. This is the
template side of roadmap candidate 3; the global-configuration side is a separate plan in
`claude_global_config`.

## Scope

- Copy the skill tree into `modules/cad-freecad/harness/claude/skills/freecad-scripts/`: `SKILL.md`,
  the ten files under `references/` and `scripts/mesh_report.py` (12 files, about 130 KB). The source
  is `claude_global_config/skills/freecad-scripts` as mirrored in `~/.claude/skills/freecad-scripts`;
  record its commit in the Result.
- Rewrite the four references to the global install path (`SKILL.md` line 770 and
  `references/mesh-reverse-engineering.md` lines 10, 15 and 96) so they resolve from a project root,
  for example `.claude/skills/freecad-scripts/scripts/mesh_report.py`. The Curves workbench paths in
  `references/curves-and-curved-shapes.md` are FreeCAD's own and stay. Store `mesh_report.py` without
  the executable bit; the installer never installs one and the skill runs it through `freecadcmd`.
- Tests: a pilot class that reads the real module's tree, installs, adds, updates and removes it, and
  a generic hygiene test that every built-in module's harness trees read clean.
- README: the Modules table and the "Harness files" section stop saying that no module ships harness
  files, and `module.json` gains a one-line `hint`.

## Non-goals

- Anything in `claude_global_config`: removing the global copy, its sync manifest and tests, and the
  mention in its plan 0003. Those are the owner's, listed in the Result.
- Editing the skill's guidance beyond the four path rewrites; its content is the owner's.
- Declarations, a `workers` role or the marker (candidate 4), `formal`'s skill (candidate 7), and the
  `claude` and `codex` conversion (candidate 6).
- A drift check between the template copy and the global one; the global copy is to be removed.

## Assumptions and constraints

- Plan 0018 is complete: a built-in `harness/claude/` tree installs under `--harness claude` with the
  limits of the specification (128 files, 256 KiB each, 2 MiB per module). The skill is 12 files, none
  over 28 KB, so it is well inside them.
- Verified on the source: all files are UTF-8 without NUL or CR; none contains a placeholder, a slot
  marker or a block marker; the frontmatter `name` is `freecad-scripts`, the unit name; there is no
  helper or hook, only the optional `freecad` MCP server and the `freecadcmd` binary that the skill
  names as tools it uses.
- The global and project copies exist side by side until the global one is removed; the project copy
  takes precedence in a project that installs it (a documented consequence of ADR 0004).
- The module's committed neutral text stays tool-neutral: nothing outside `harness/` may name the
  skill, and the neutrality test keeps checking that.
- Python standard library only; no dependency, secret or network access.

Graphify: skipped — no graph exists in this checkout (`graph_missing`), and the affected files are
enumerated above: `modules/cad-freecad/` (`module.json`, new `harness/claude/skills/freecad-scripts/`),
`tests/test_install.py`, and `README.md`.

## Completion criteria

`./install.py <target> --with cad-freecad --harness claude` installs the 12 skill files under
`.claude/skills/freecad-scripts/` and records each in `harness_files` with `cad-freecad` as supplier;
without `--harness` nothing is installed and the manifest is unchanged; `--update` leaves an unedited
tree alone and keeps an edited file; `--remove cad-freecad` deletes the unedited files and the emptied
directories. Every built-in harness tree passes the reader; the neutrality test still passes with
and without `--harness`; the installed skill has no reference to `~/.claude`; the suite passes;
`git diff --check` is clean; the installed bytes equal the source except the four rewritten lines.

## Increments

### Increment A — Ship the skill in the module

Dependencies: None
Affected areas: `modules/cad-freecad/harness/claude/skills/freecad-scripts/` (new),
`tests/test_install.py` (`HarnessPilotTest`)

1. Write failing tests against the real module: `read_harness_tree` returns exactly the 12 installed
   paths under `.claude/skills/freecad-scripts/`; the unit map is `{".claude/skills/freecad-scripts":
   "freecad-scripts"}`; no installed file contains `~/.claude`; the tree is within the per-module
   limits; the installed `scripts/mesh_report.py` path appears in the skill text.
2. Copy the tree from the source, apply the four path rewrites, and remove the executable bit from
   `mesh_report.py`.
3. Compare the copy to the source and confirm that only the four lines differ.

Completion: the new tests pass and the diff against the source shows only the four rewrites.

### Increment B — Behaviour with the real module

Dependencies: Increment A
Affected areas: `tests/test_install.py`

1. Write failing tests with the real module and the real `base/`: `--new --with cad-freecad --harness
   claude` installs and records the files; the same without `--harness` installs none and records no
   harness; `--add cad-freecad --harness claude` to a project that has `cad` only; `--update` is a
   no-op on an unedited tree and keeps an edited file with a conflict report; `--remove cad-freecad`
   deletes the unedited files and the emptied `.claude/skills` directories.
2. Add the generic hygiene test (every built-in module's harness tree reads clean for every harness)
   and extend the neutrality check: a project of every non-harness module installed with `--harness
   claude` mentions tool-specific names only in recorded harness files.

Completion: the new tests pass and no existing test changes except the neutrality additions.

### Increment C — Documentation and hint

Dependencies: Increment B
Affected areas: `README.md`, `modules/cad-freecad/module.json`

1. Add a `hint` to `cad-freecad` (one line, at most 200 characters) saying that
   `--harness claude` also installs the FreeCAD scripting skill.
2. Update the README Modules table row and the "Harness files" section, which currently says that no
   module ships harness files.
3. Check the README's module-authoring text for statements the pilot makes incomplete: "Writing a
   module" step 4 and the Boundaries paragraph say harness-specific content belongs to modules marked
   `"harness": true`; reword them to add `harness/<harness>/` directories as the other place. The
   `"harness": true` flag itself stays documented, because it is retired only by roadmap candidate 6.

Completion: the hint prints under "Next steps" for a new install and `--add`; the README matches the
behaviour tested above, and a grep of the README for `harness": true` finds only text that also
mentions `harness/<harness>/`.

### Increment D — Verification

Dependencies: Increment C
Affected areas: none expected

1. Run the full suite and the scratch checks under Verification.
2. Record the source commit, the sizes, and the open items for the other repository.

Completion: the Result lists the evidence and the follow-up for `claude_global_config`.

## Verification

- `python3 -I -m unittest discover -s tests` (412 tests today plus the new ones).
- Each new test is seen to fail before its implementation.
- In scratch: install with `--with cad-freecad --harness claude`, diff the installed skill against the
  source (only the four rewrites), run `--update --dry-run`, edit one reference and rerun `--update`,
  then `--remove cad-freecad`.
- `git diff --check`.
- Security review: skipped — no code changes; the files are the owner's own skill text, and the
  installer paths they take (limits, allowlist, no executable bit, recorded hashes) were reviewed
  adversarially under plan 0018.

## Risks and sensitive actions

- The skill is loaded automatically by Claude Code in every project that installs it, so its text is
  now part of those projects; it is the same text the owner already loads globally.
- Duplicate copies (global and project) can drift until the global one is removed; the follow-up in
  `claude_global_config` closes that, and the Result names it.
- A mistaken path rewrite would break the mesh script lookup; Increment A checks the paths and the
  scratch run checks that `.claude/skills/freecad-scripts/scripts/mesh_report.py` exists.
- No commit, push, dependency, secret or destructive action without the owner's request.

## Deferred work

- In `claude_global_config`: remove `skills/freecad-scripts` and its `config-manifest.txt` entry,
  update the tests and the sync that mention it, and keep or reword the mention in its plan 0003.
- A way to keep a shipped skill and its source in step (candidate 10 and later).

## Result

Increments A to D are done and verified; the plan commit is `02dc09f` and the work is uncommitted.
The suite passes with 425 tests (412 before, 13 new in `HarnessPilotTest`, `ModuleHygieneTest` and
`InstallerTest`).

- Increment A: the skill is in `modules/cad-freecad/harness/claude/skills/freecad-scripts/` (12 files,
  about 140 KB), copied from `claude_global_config/skills/freecad-scripts` at its commit `b388ec5`
  (identical to `~/.claude/skills/freecad-scripts` when copied). Four lines were rewritten from
  `~/.claude/skills/freecad-scripts/...` to `.claude/skills/freecad-scripts/...` (`SKILL.md` line 770 and
  `references/mesh-reverse-engineering.md` lines 10, 15 and 96); a diff against the source shows
  only those lines. `mesh_report.py` is stored without the executable bit. The four tests failed
  before the copy.
- Increment B: tests with the real module and `base/` for `--new`, `--add`, `--update` (no-op on an
  unedited tree, a reported conflict on an edit) and `--remove` (unedited files and emptied directories
  deleted, an edited reference kept), a generic test that every built-in harness tree reads clean, and
  a neutrality test for a project of every non-harness module installed with `--harness claude`. These
  were written after the copy, so they are coverage tests; with the harness directory removed from a
  scratch copy, they fail (4 failures and 5 errors). The neutrality helper now also skips
  `.template-manifest`, which records the installed harness paths by design.
- Increment C: `cad-freecad` has a one-line `hint`; the README Modules row, the "Harness files"
  section and "Writing a module" step 4 are updated (the `"harness": true` flag stays documented until
  candidate 6).
- Increment D: a scratch install with `--with cad-freecad --harness claude` produced the 12 files, a
  `schema` 2 manifest and mode 0644 for the script; only `SKILL.md` and
  `references/mesh-reverse-engineering.md` differ from the source; `--update --dry-run` reported
  nothing to update; `--remove cad-freecad` removed the tree and `.claude`. `git diff --check` is clean.

Choices where the plan was silent: the hint prints on every install of the module, including one that
already passes `--harness claude`, as other hints do; the shipped skill keeps its content except for
the four paths.

Security review: skipped, as planned (no code changes; owner-authored text; installer paths reviewed
under plan 0018).

For the owner, in `claude_global_config` (not touched): remove `skills/freecad-scripts` and its
`config-manifest.txt` entry, update the tests and sync that name it, and reword the mention in its
plan 0003. Until then both copies exist and the project copy takes precedence in projects that install
it. The follow-on candidates are 4 (declarations) and 7 (`formal`), both unblocked.
