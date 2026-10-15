# 0002: Runner stub, module hints, and interactive prompt checks

Status: Completed
Created: 2026-10-15
Completed: 2026-10-15

## Outcome

A project created with `install.py --with claude,graphify` starts with a
committed-ready remote-runner contract stub, is told how to start using
Graphify, and the installer's interactive prompts are covered by tests that
have actually run them on a terminal.

## Scope

1. **Runner contract stub (`claude` module).** Ship
   `.claude/remote-runner.toml` containing `[project] id` set from the project
   name and only commented-out `[profiles.<name>]` examples.
2. **Post-install hints.** A module may declare a one-line `hint` in
   `module.json`; the installer prints each selected module's hint after
   `install.py <target>` and after `--add`. `graphify` declares the first one.
3. **Interactive paths.** Exercise the module and git-identity prompts on a
   pseudo-terminal, add tests, and fix what that finds.

## Non-goals

- A `graphify-out/` placeholder: it is rebuildable ignored state and
  `claude-workflow` already treats a missing graph as a normal state.
- `.claude/settings.local.json`: personal, ignored, and created by Claude Code.
- Active example profiles, or profile fragments contributed by other modules
  (`formal`, `graphify`); a slot for that can follow once real profiles exist.
- Ghidra and Codex second-opinion modules, `--add` fragment insertion for
  already-installed modules, adopting `cp -R` projects, `--remove`.
- Any change to `claude_global_config` or to `remote-runner` itself.

## Assumptions and constraints

- `remote-runner` reads `.claude/remote-runner.toml` from the committed
  revision and requires `[project] id` matching
  `[A-Za-z0-9][A-Za-z0-9_-]*` and at least one profile with a string
  `command`. A stub with no active profile therefore fails closed with
  "needs one or more [profiles.<name>] entries" and can never run a command.
- The installer's project-name check today rejects only empty or multi-line
  names, so a name such as `my project` is valid for the project but not as a
  runner id, and a quote or backslash would break TOML. Decision point: the
  installer derives a second substitution, `REPLACE_WITH_PROJECT_ID`, by
  replacing every character outside `[A-Za-z0-9_-]` with `-` and rejecting an
  empty result or one that does not start with an alphanumeric.
- The runner stub is Claude-specific and belongs in the `claude` module,
  which is `harness: true`, so the neutrality test already permits it.
- Module opt-in stays generic: the new `module.json` field is optional, and
  an absent hint changes nothing for existing modules.
- `--add` today copies a module's `files/` but never substitutes
  `REPLACE_WITH_PROJECT_NAME`. Adding `claude` later would leave placeholders
  in the stub. Decision point: `--add` derives the name from the project
  directory (the same default as a new project) and applies both
  substitutions to the files it writes.
- The installer writes only inside the target directory and the new
  repository's `.git/info/exclude`; none of this changes that.

## Discovery and impact evidence

Graphify: skipped — the repository has 40 tracked files, and the affected
paths are fully enumerated here: `install.py`, `tests/test_install.py`,
`modules/claude/`, `modules/graphify/module.json`, `README.md`. Evidence
verified against current source: `install.py` `cmd_new`/`cmd_add` (name
substitution and `--add` file writes), `bin/remote-runner` `project_config`
(contract requirements), `bin/claude-workflow` graph status handling
(`status: missing` is a normal result).

## Completion criteria

- `python3 -I -m unittest discover tests` passes, including new tests for
  each increment, and `git diff --check` is clean.
- A scratch `install.py <dir> --with claude,graphify --git-name … --git-email …`
  produces `.claude/remote-runner.toml` with the project id set, no
  unresolved placeholder, a Graphify hint in the output, and no
  `graphify-out/` or `settings.local.json`.
- In that scratch project `remote-runner` rejects the stub with the
  documented "needs one or more [profiles.<name>]" message and runs nothing.
- The interactive prompts have been run on a pseudo-terminal by a test and
  the observed behavior, including end-of-input, is recorded in the Result.

## Increments

### Increment A — runner contract stub

Dependencies: None
Affected areas: `modules/claude/files/.claude/remote-runner.toml`,
`install.py` (project-id substitution, `--add` name handling),
`tests/test_install.py`, `README.md`

1. Tests first: the stub is installed with `claude`, id equals the slugged
   project name, no unresolved placeholder, TOML parses with `tomllib` and
   has no profiles, names with spaces and TOML-hostile characters are
   slugged or refused, a name that cannot form an id is refused before
   anything is written, and `--add claude` produces the same stub as a fresh
   install.
2. Add the stub with commented examples (command, `requirements`) and a
   header stating that it must be committed before `remote-runner` can use
   it and that profiles are project commands, not host details.
3. Add the `REPLACE_WITH_PROJECT_ID` substitution in `cmd_new` and in
   `cmd_add`; document it in the README module section.

Completion: tests pass and the scratch install matches the criteria above.

### Increment B — post-install hints

Dependencies: None (independent of A)
Affected areas: `install.py` (`load_modules` validation, `cmd_new`,
`cmd_add`), `modules/graphify/module.json`, `tests/test_install.py`,
`README.md`

1. Tests first: a module hint is printed once for each selected module,
   including modules pulled in through `requires`; not printed for
   unselected modules; printed by `--add`; an absent field prints nothing; a
   non-string, multi-line, or oversized hint fails module loading; `--dry-run`
   labels it as a dry run.
2. Implement the optional `hint` field and printing.
3. Graphify hint text: no graph exists yet; run
   `claude-workflow graph-doctor` when discovery is needed. The hint lives in
   the `graphify` module, which already documents the helper, so the neutral
   base names nothing.

Completion: tests pass; scratch install shows the hint only when `graphify`
is selected.

### Increment C — exercise the interactive prompts

Dependencies: None
Affected areas: `install.py` (`cmd_new`, `resolve_identity`),
`tests/test_install.py`

1. Run `install.py` in a pseudo-terminal using the standard-library `pty`
   module under a scratch `HOME` and `GIT_CONFIG_GLOBAL`/`GIT_CONFIG_SYSTEM`
   sentinels: module prompt answered, identity prompts answered, blank module
   answer, invalid identity, unknown module name, and end-of-input at each
   prompt.
2. Record findings. Suspects to confirm rather than assume: prompts are
   asked before the target is validated, so a bad target is reported only
   after the user has typed answers; `input()` end-of-input is not caught and
   would print a traceback.
3. Tests first for each confirmed defect, then fix. Keep the pty tests
   POSIX-only and skipped elsewhere.

Completion: the pty tests pass; each confirmed defect has a regression test
that failed before its fix.

## Verification

- `python3 -I -m unittest discover tests` (full suite; stdlib only, no
  network).
- Scratch installs under the session scratchpad, never inside the template
  repository: `--with claude,graphify`, `--with claude`, no modules, and a
  later `--add claude`.
- `remote-runner recommend --profile example` in the scratch project to show
  the stub's fail-closed message; read-only.
- `git diff --check`.

## Risks and sensitive actions

- A stub contract that someone commits unchanged yields a clear refusal, not
  a run. No active profile ships, so no command can execute on a remote.
- Project-id derivation is an input-handling change: it must fail closed on
  names that cannot form an id, and the id must never be interpolated into
  TOML unescaped.
- Commits are made only on explicit approval; nothing is pushed without it.
- No dependency, network, or secret use.

## Deferred work

- Commented example profiles contributed by `formal` and other modules
  through a slot.
- `--add` fragment insertion for already-installed modules.
- Ghidra and Codex second-opinion modules; neutral shared workflow helper;
  adopting `cp -R` projects; `--remove`.

## Result

All completion criteria met. Implemented in this repository:

- Increment A, `27f7123`: `.claude/remote-runner.toml` stub in the `claude`
  module with a derived project id; `--add` fills name placeholders.
- Increment B, `5822068`: optional `hint` in `module.json`, printed under
  "Next steps"; `graphify` declares the first hint.
- Increment C, `3393fec`: prompts run last, end of input is a clean refusal,
  Ctrl-C exits 130; pseudo-terminal tests added.

Verification: `python3 -I -m unittest discover -s tests` passed (51 tests);
`git diff --check` clean; a scratch `--with claude,graphify` install produced
the stub and the hint, and `remote-runner` rejected the stub with "needs one
or more [profiles.<name>] entries".

Observed during Increment C and left unchanged:

- `--dry-run` never prompts for modules, so an interactive dry run without
  `--with` previews the no-module tree.
- An invalid name or email is reported after both identity prompts, not after
  the offending one.
- Ctrl-C handling is covered by a unit test, not a terminal signal.
