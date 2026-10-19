# 0022: Graphify tooling in the graphify module

Status: Completed
Created: 2026-10-19
Completed: 2026-10-19

## Goal

The `graphify` module ships the Graphify workflow tooling itself: a tool-neutral script in the project
(`tools/graphify/`) that provides the status, doctor, query and refresh commands now implemented in
the global `claude-workflow` helper, and, under `--harness claude`, the `graphify-workflow` skill and
the `graphify-semantic` agent that drive it. Nothing refreshes the graph automatically: there is no
git hook and no post-commit step, and `doctor` reports a stale graph. This is the template side of
roadmap candidate 5 and carries ADR 0004 decision 5; the global-configuration side (dropping the Graphify
commands, the post-commit refresh, the skill and the agent from `claude_global_config`) is a separate
plan in that repository.

## Scope

- A stdlib-only script `tools/graphify/graphify.py` (module `files/`) with the commands `status`, `doctor`,
  `query`, `path`, `explain`, `affected`, `god-nodes`, `diagnose`, `benchmark`, `prepare`, `finalize`,
  `abort` and `validate-chunk`, ported from `claude_global_config/bin/claude-workflow` (its `graph-*`
  commands, about 600 lines) and `skills/graphify-workflow/scripts/` (`prepare.py`, `finalize.py`,
  `ignored_paths.py`; `post_commit.py` is not ported). The helper's plumbing they rely on (the
  repository boundary, the trusted `PATH` lookup for the vendor `graphify` executable, the scrubbed
  subprocess runner, structured JSON output) is carried with them. Sources are recorded by commit in the
  Result.
- Neutral names: the state files `.claude_refresh.json`, `.claude_graph_state.json`,
  `.claude_graph_visualization.json` and `.claude_post_commit.json` under `graphify-out/` become
  `.workflow_*` names (the post-commit marker is dropped), and every `next_action` text names the new
  script. Existing graphs read as `present` (stale) once and are refreshed; `graphify-out/` is rebuildable.
- Helpers beside the script: `tools/graphify/extraction-spec.md` (the chunk contract) and a neutral
  procedure `tools/graphify/refresh.md` that says "dispatch each chunk to the chunk-extractor worker",
  with no harness product named.
- Harness files in `modules/graphify/harness/claude/`: the `graphify-workflow` skill (its commands rewritten
  to `python3 tools/graphify/graphify.py ...`, its "After a commit" section replaced by the explicit
  refresh policy) with a `references/refresh.md` that names the Claude agent, the `graphify-semantic`
  agent, and a `harness.json` mapping the role `graphify-chunk-extractor` to it.
- `module.json`: a hint naming the new script, and the declarations from plan 0020: `helpers`
  (`graphify`), `workers` (`graphify-chunk-extractor` with a one-line contract) and `global_config`
  (see Assumptions).
- Tests: a new `tests/test_graphify_tool.py` ported from the skill's `test_workflow.py` and
  `test_scripts_review.py` and the graph cases of `test_claude_workflow_review.py`, run against the module's
  files with a fake `graphify` executable; install tests for `--with graphify`, with `--harness claude`,
  the declared-dependency report, neutrality and the generic hygiene test.
- README: the Modules row, "Harness files" and a short "Graphify tooling" section, and a note that
  `tools/graphify/` is project code.

## Non-goals

- Anything in `claude_global_config`: removing the `graph-*` commands, `graph-post-commit` and the commit
  helper's Graphify handling, the skill, the agent, the sync manifest, `settings-policy.txt`
  entries, the global `CLAUDE.md` Graphify section and `hooks/review_agent_guard.py`. They are listed in
  the Result for the owner.
- Any automatic refresh, hook or post-commit step, anywhere.
- Changing the Graphify vendor tool, its extraction contract or its graph format.
- The `.graphifyignore` and `.gitignore` slot text, which stay as they are.
- Retiring `"harness": true`, `plan-review`, `codex` and the `claude` module (candidate 6).

## Assumptions and constraints

- ADR 0004 decision 5 fixes the shape (a neutral script shipped by the module, no hook, no automatic
  refresh, `graph-doctor` reporting staleness); this plan does not reopen it. Plans 0018 to 0020 provide
  harness files, declarations and the dependency report.
- The script is project code. Unlike the global helper, a hostile clone could carry a modified copy, so the
  skill and README tell the agent to treat `tools/graphify/` like any other project code, and
  `install.py --update` reports it as kept when it differs from the template.
- The `graphify-semantic` agent's frontmatter runs a guard hook from the global configuration
  (`${CLAUDE_CONFIG_DIR:-$HOME/.claude}/hooks/review_agent_guard.py chunk`) that confines its writes to
  one chunk file. Machine-level hooks stay global (ADR 0004 decision 5), so the module declares
  `global_config: true` and the installer's report says whether the marker is present. Whether a missing
  hook script blocks the agent's tool calls (a nonzero exit 2 from a missing script) or only logs is an
  assumption about Claude Code to verify before approval; if it only logs, Increment E adds an explicit
  instruction for the agent to refuse to write without the guard.
- Choices to confirm in review: the location `tools/graphify/` and the entry name `graphify.py` (the base
  has no `tools/` directory); the neutral state names; dropping `post-commit` and the `--deep` behaviour
  of `prepare` unchanged; and keeping one plan for the script and the harness files (they can be split at
  Increment E if the review finds the plan too large).
- Verified in the sources: the global graph commands wrap the vendor `graphify` executable and the skill's
  scripts and read state under `graphify-out/`; `claude_global_config/skills/graphify-workflow/tests`
  hold about 650 lines of tests; the neutral text of the module (`slots/*.md`) names no tool, and the
  neutrality test forbids `claude-workflow`, `graphify-semantic` and `codex` outside harness files, so the
  neutral docs use the role name, not the agent name.
- No new dependency: Python 3.9+ standard library; the vendor `graphify` executable is the user's, found
  on `PATH`.

Graphify: skipped — no graph exists in this checkout (`graph_missing`), and the affected files are
enumerated: `modules/graphify/` (`module.json`, new `files/tools/graphify/`, new `harness/claude/`),
`tests/test_install.py`, new `tests/test_graphify_tool.py`, and `README.md`; the sources are read from
`claude_global_config` without modifying it.

## Completion criteria

`./install.py <target> --with graphify` installs `tools/graphify/` and nothing under `.claude/`; with
`--harness claude` it also installs the skill and the agent, records them in `harness_files` and prints
the declared-dependency lines (helper `graphify`, worker `graphify-chunk-extractor` implemented, global
configuration). In a project with a fake `graphify` executable and git history the script reports `status`
and `doctor`, runs the query commands through the executable, and completes `prepare`, a valid chunk,
`validate-chunk` and `finalize`; a refresh in progress is refused a second `prepare`; `abort` refuses once
chunks exist; nothing runs a hook or refreshes after a commit. The script and the neutral docs contain
none of the forbidden tool names; the suite passes; an adversarial review of the script has run and its
findings are decided; `git diff --check` is clean.

## Increments

### Increment A — Shared plumbing, `status` and `doctor`

Dependencies: None
Affected areas: `modules/graphify/files/tools/graphify/graphify.py` (new), `tests/test_graphify_tool.py`
(new)

1. Write failing tests, ported and adapted, for: JSON output; the repository boundary and trusted `PATH`
   lookup (a `PATH` directory inside the repository is ignored); the scrubbed subprocess runner; `status`
   for each state (`missing`, `present`, `current`, `stale_code`, `stale_semantic`, `refresh_in_progress`);
   `doctor` for each workflow state with its one next action; a symlinked or non-directory `graphify-out`
   refused; the new state file names and the old names reading as `present`.
2. Port the plumbing, `status` and `doctor`, with the neutral names and next actions.

Completion: the new tests pass; the script mentions no forbidden tool name.

### Increment B — Query commands

Dependencies: Increment A
Affected areas: `graphify.py`, `tests/test_graphify_tool.py`

1. Write failing tests with a fake `graphify` executable that records its arguments: `query` (budget,
   `--dfs`, repeated `--context`), `path`, `explain`, `affected` (depth, repeated `--relation`),
   `god-nodes`, `diagnose`, `benchmark`; a missing graph and a missing executable are clear errors;
   a stale graph prints its warning; hostile node text is passed as one argument, never through a shell.
2. Port the commands.

Completion: the new tests pass.

### Increment C — Refresh commands

Dependencies: Increment B
Affected areas: `graphify.py`, `tools/graphify/prepare.py`, `finalize.py`, `ignored_paths.py`,
`extraction-spec.md` (all new), `tests/test_graphify_tool.py`

1. Write failing tests, ported from the skill's tests, for `prepare` (manifest, chunking, `--deep`, a
   second `prepare` refused while one is prepared), `validate-chunk` (every rejection class the helper
   tests cover, including path, hash and coverage mismatches), `finalize` (state, visualization record,
   atomic write, refresh state removed), `abort` (refused once chunks exist, `--confirm` required), and that
   no command refreshes after a commit and no `post-commit` command exists.
2. Port `prepare.py`, `finalize.py`, `ignored_paths.py`, the chunk contract and the three commands, and
   write the neutral `refresh.md`.

Completion: the new tests pass and a scripted end-to-end refresh completes against the fake executable.

### Increment D — Wire the module

Dependencies: Increment C
Affected areas: `modules/graphify/module.json`, `modules/graphify/files/`, `tests/test_install.py`

1. Write failing install tests: `--with graphify` installs `tools/graphify/*` (executable bits not
   preserved: the README says to run it with `python3`) and no `.claude`; the files are read as text and
   contain no forbidden name; `--update` keeps an edited script with a report.
2. Update the hint to name the new script.

Completion: the new tests pass; the neutrality test passes with and without `--harness`.

### Increment E — Harness files and declarations

Dependencies: Increment D
Affected areas: `modules/graphify/harness/claude/` (new), `modules/graphify/module.json`,
`tests/test_install.py`

1. Verify the missing-hook behaviour assumption (or choose the explicit-refusal instruction) and record
   the result in the plan before continuing.
2. Write failing tests: `--new --with graphify --harness claude` installs the skill (with its
   `references/refresh.md`) and the agent and records them; the unit names are
   `graphify-workflow` and `graphify-semantic`; `harness.json` maps the role; the declarations load and the
   dependency report prints helper, worker `implemented by graphify` and global configuration for present
   and missing helper and marker; the skill contains no `claude-workflow` command and mentions no
   post-commit step; the agent's hook line is present unchanged.
3. Port the skill and the agent with the rewritten commands, add `harness.json` and the declarations.

Completion: the new tests pass.

### Increment F — Documentation

Dependencies: Increment E
Affected areas: `README.md`

1. Update the Modules row, "Harness files" and add "Graphify tooling": the commands, the explicit refresh
   procedure, that nothing refreshes automatically, that `tools/graphify/` is project code, and the
   `--add graphify --harness claude` route for existing projects.

Completion: the README matches the behaviour tested above; `git diff --check` is clean.

### Increment G — Verification and security review

Dependencies: Increment F
Affected areas: none expected beyond fixes

1. Run the full suite and the scratch checks under Verification.
2. Run an adversarial `security-reviewer` pass with the `security-review` skill on the script and its
   subprocess and path handling, with fake executables on `PATH`: hostile repository contents
   (`graphify-out` symlinks, a `PATH` directory inside the repository, hostile node names and chunk
   JSON), a tampered manifest or chunk between commands, `abort` and `finalize` races, and that no
   command runs anything from the repository besides the named helpers. Fix each reachable finding with a
   regression test that failed first and record the rest with a reason.

Completion: the findings are decided and the suite is green.

## Verification

- `python3 -I -m unittest discover -s tests` (482 tests today plus the new ones); each new test is seen to
  fail before its implementation.
- In scratch: install with `--with graphify --harness claude`; with a fake `graphify` executable and a small
  git repository run `status`, `doctor`, each query command, a full `prepare`, chunk, `validate-chunk`,
  `finalize` cycle, then `--update --dry-run`.
- Mutation checks on a scratch copy: trusting a `PATH` directory inside the repository, following a
  symlinked `graphify-out`, skipping chunk path validation and allowing a second `prepare` each fail the
  new tests.
- Compare the ported behaviour with the global helper on the same fixture repository for `status` and
  `doctor` output (apart from the renamed state files and next actions).
- `git diff --check`.

## Risks and sensitive actions

- A project-local script replaces a trusted global helper; a hostile clone could modify it. Mitigations:
  the README and skill say to treat it as project code, `install.py --update` reports a modified copy, and
  Increment G reviews it adversarially.
- The agent's write guard is a global hook. If a missing hook does not block the agent, the guard is not
  enforced in a project on a machine without the global configuration; Increment E decides between the
  declaration alone and an explicit refusal instruction.
- The port is large (about 1,400 lines plus tests) and behaviour-critical; the ported tests and the
  side-by-side comparison are the control.
- Public behaviour grows (`tools/graphify/`, the commands); old `.claude_*` state files are ignored.
- No commit, push, dependency, secret or destructive action without the owner's request.

## Deferred work

- In `claude_global_config`: remove the `graph-*` commands and `graph-post-commit`, the commit helper's
  Graphify result, the skill, the agent, their manifest and permission entries, tests and the `CLAUDE.md`
  Graphify wording; keep `hooks/review_agent_guard.py` and its tests; update `settings-policy.txt` for
  the new command shape if the owner wants it allowed.
- Candidates 6, 8, 9 and 10 of the roadmap.

## Result

Increments A to G are implemented and verified; the plan commit is `03ba2ef` and the work is
`4348bc8`. The suite passes with 610 tests (482 before this plan). `tests/test_graphify_tool.py` is new
(ported from the skill's `test_workflow.py` and `test_scripts_review.py` and the graph cases of the global
helper tests, plus new ones); `tests/test_install.py` gained `GraphifyToolInstallTest` and
`GraphifyHarnessTest`.

Source: the graph commands of `claude_global_config/bin/claude-workflow` and
`skills/graphify-workflow/scripts/` (`prepare.py`, `finalize.py`, `ignored_paths.py`, the extraction spec),
read at the working tree of 2026-10-19; `post_commit.py` was not ported. Delivered: `tools/graphify/`
(`workflow.py`, the three helper scripts, `extraction-spec.md`, `refresh.md`), the `graphify-workflow`
skill with its `references/refresh.md`, the `graphify-semantic` agent unchanged, `harness.json`, the
`helpers`/`workers`/`global_config` declarations, a new hint, and the README sections.

Rulings (deviations from the plan text, made while implementing):
- The entry script is `workflow.py`, not `graphify.py`. A `graphify.py` beside `prepare.py` shadows the
  vendor `graphify` package the helper scripts import (found when the ported tests failed). Commands are
  `status`, `doctor`, `prepare`, `abort`, `finalize`, `refresh-code`, `validate-chunk`, `query`, `path`,
  `explain`, `affected`, `god-nodes`, `diagnose`, `benchmark`, each with `--root`.
- `refresh-code` is new. Without post-commit, `doctor` had no action to offer for a `stale_code` graph. It
  runs the vendor's code-only update and records it (the old `record_code_refresh` semantic-baseline pinning),
  without the commit marker or retry logic, and is never run by a commit.
- State files are `.workflow_*`; a graph with the old `.claude_*` files reads as `present` once.
- The agent file is unchanged, including its hook from the global configuration. Checked against the Claude
  Code documentation: exit code 2 blocks a PreToolUse call and Python exits 2 for a missing script (an
  inference the docs do not state; `onFailure: "block"` would make it explicit), a project agent's
  frontmatter hooks run only after the workspace trust dialog and are skipped in untrusted folders and `-p`
  sessions, and a project agent overrides a same-named user agent. The skill and `refresh.md` therefore
  tell the model to dispatch the agent only in a trusted workspace.
- The tool refuses to run when the repository's own git config defines programs git may run (names, never
  values), unless `--allow-repo-programs`, as the owner's global commit helper does for commits; git is also
  run with `core.fsmonitor`, `core.hooksPath`, the pager and the untracked cache overridden and inherited
  `GIT_*` variables scrubbed. Repositories that legitimately use filter drivers (for example LFS) need the flag.

Verification: `python3 -I -m unittest discover -s tests` passes with 610 tests; `git diff --check` is clean.
Mutation checks on scratch copies (trusting a `PATH` directory in the repository, following a symlinked
output directory, unchecked chunk paths, a second `prepare`, `abort` discarding chunks, blessing an unknown
graph, `refresh-code` during a refresh, an open manifest schema, an optional contract, repository programs
allowed, an inherited runtime variable, a runtime inside the project, unlisted chunk files, no cumulative hash
budget, sources under `.git` or `graphify-out`, invisible marks passing, an in-project symlinked chunk, no
output cap, a size cap, a runtime beside a trusted `graphify` that links into the repository, a grandchild
holding the pipes) each fail the new tests. One mutation, removing the regular-file check in `read_json`,
survives and is an equivalent mutant (the non-blocking open already fails safely on special files); the check
stays as defense in depth. On seven graph states `status` and `doctor` give the same status as the global
helper. The end-to-end refresh tests ran against the real `graphify` executable on this machine.

Adversarial review (`security-reviewer`, scratch copies; no Critical or High finding), two passes:
- Pass 1: Medium: a committed manifest was trusted (source paths, contract, hashing without a cap; the
  refresh procedure passes them to a worker that can read files); a repository `core.fsmonitor` ran code
  (inherited from the global helper). Low: FIFOs hung the readers; deeply nested JSON wedged the workflow;
  the helper scripts re-executed a `python` found without a containment check; option-like text reached the
  vendor; control characters passed through; no timeout kill of a grandchild; `doctor` and `validate-chunk`
  ignored a symlinked output directory. All fixed with tests that failed first.
- Pass 2 (of the fixes): Medium: a clean filter driver still ran during `git status`; an inherited
  `GRAPHIFY_TOOL_PYTHON` was executed. Low: a manifest without a contract and with free-text fields was
  accepted; no cumulative hash cap; invisible and bidirectional marks passed; unbounded vendor runs and
  output; `abort` ignored chunk files the manifest did not list; an in-project symlinked chunk was read. All
  fixed with tests that failed first (a strict manifest schema with a required contract, a refusal on
  repository programs, scrubbed `GRAPHIFY_TOOL_*`, a runtime that must lie outside the project, a 1 GiB total
  hash budget, a query timeout and a 1 MiB output cap).
- Not reviewed again: the pass 2 fixes were verified by tests and mutation checks, not a third review.
- Accepted residuals: a hostile clone carries its own tool, skill and agent text, and nothing in the
  repository can detect that (the guards are the README and skill warnings and `install.py --update`
  reporting an edit as kept, which cannot see a fresh clone); `prepare` and `finalize` are not time-bounded
  because builds are long; the vendor's own behaviour (option parsing, writes through symlinks inside
  `graphify-out`) is outside the tool; `safe.directory`, credential-helper and alias routes were reasoned
  about, not executed.
- Not exercised: the real Claude Code hook and trust behaviour for the agent, a case-insensitive alias of a
  path that does not exist, and a real concurrent swap between a check and a read.

For the owner, in `claude_global_config` (not touched): remove the `graph-*` commands and `graph-post-commit`
from `bin/claude-workflow` and the commit helper's Graphify result; remove `skills/graphify-workflow` and
`agents/graphify-semantic.md`, their `config-manifest.txt` lines and the tests that name them; keep
`hooks/review_agent_guard.py` and its tests (the shipped agent calls it); reword the global `CLAUDE.md`
Graphify section (no automatic refresh; the project's tool and skill); and, if you want the new command
shape allowed, add `python3 tools/graphify/workflow.py` entries to `settings-policy.txt`. Until then both
copies exist, and a project that installs the module uses its own.

Not done (deferred above): the other roadmap candidates (6, 8, 9, 10).

## Codex plan review

- Plan: docs/plans/next.md (key d8b0db9f6a60889d)
- Rounds used: 1 of 3
- Round 1: model gpt-5.6-luna, effort low, 0 finding(s) (0 blocker or major), 119753 input and 1430 output tokens
- Outcome: converged (no blocker or major finding in the last round)
- Decisions: 0 applied, 0 rejected
