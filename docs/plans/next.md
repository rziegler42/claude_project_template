# Next plan

Status: In Progress (Increment A)
Created: 2026-10-15

## Goal

Replace `cp -R` project creation with a modular, tested installer
(`install.py`) that builds a new project from `base/` plus opt-in modules,
runs a fresh `git init` with an explicit local identity, and supports
`--add <module>` later. Governing decision: ADR 0001.

## Scope

- Restructure into `base/` and `modules/` (claude, cad, cad-freecad, graphify,
  formal); `LICENSE` stays at the repository root and is never copied.
- `install.py`: new project, `--with`, `--name`, `--dry-run`, `--list`, `--add`,
  git identity flags/prompt, `.template-manifest`, placeholder summary.
- Tests, README, and the two template-source mentions in `claude_global_config`
  (separate approval).

## Non-goals

- Ghidra and Codex second-opinion modules (separate plans).
- Adopting pre-existing `cp -R` projects; `--remove`; splitting planning docs
  into a module; extracting `claude-workflow` into a neutral helper.
- Pre-commit identity guards or `includeIf` configuration for existing repos.

## Assumptions and constraints

- Python 3.9+ standard library only; macOS primary, Linux secondary.
- Base paths under `docs/plans/`, `docs/roadmaps/` are frozen: external tooling
  reads `docs/plans/next.md` and `docs/plans/README.md`.
- No default-on modules; harness shims are independent modules.
- Committed content names capabilities, never a private helper or skill.

## Discovery and impact evidence

Graphify: skipped — small repository, scope fully enumerated by the approved
harness plan.

## Completion criteria

- `python3 -I -m unittest discover tests` passes for the module matrix.
- Installer output for `--with cad-freecad,graphify,formal` is
  content-equivalent to the pre-change template (reviewed diff).
- A new project has a fresh `.git` with no remote, no commits, and a local
  identity that never came from global config unless explicitly bypassed.

## Increments

### Increment A — restructure, then ADR; no behavior change

Dependencies: None
Affected areas: whole repository layout, `docs/`

1. `git mv` shipped files into `base/` and `modules/`. (Done.)
2. Extract Graphify, formal, CAD, CAD-FreeCAD, and Claude content into module
   slots; convert the docs index to a list.
3. Write ADR 0001 and this repository's own `docs/plans/`, `docs/decisions/`.
4. Root `README.md` describes the template and installer.

Completion: assembled output is content-equivalent to the pre-change template.

### Increment B — installer core (new project)

Dependencies: Increment A
Affected areas: `install.py`, `tests/`

1. Tests first (tree per combination, git state, identity, refusals, dry-run,
   manifest, neutrality).
2. Implement `install.py`.

Completion: tests pass; manual run produces the expected tree with an empty
`git log`.

### Increment C — `--add`, `--list`, idempotency

Dependencies: Increment B
Affected areas: `install.py`, `tests/`

1. Tests: add, add twice, edited-file conflict, unknown module, legacy
   directory without manifest.
2. Implement.

Completion: tests pass; `--add` changes only the module's files and marked
fragments.

### Increment D — documentation and global-config mentions

Dependencies: Increment C
Affected areas: root `README.md`; `claude_global_config` `CLAUDE.md`, `README.md`

1. Document usage, authoring a module, and the harness boundary.
2. Update the two template-source mentions in `claude_global_config` and mirror
   into `~/.claude` (separate approval).

Completion: README walkthrough reproduced from a clean scratch directory.

## Verification

`python3 -I -m unittest discover tests`; golden comparison against the
pre-change template; `git diff --check`.

## Risks and sensitive actions

- Restructure moves every file (`git mv`, history preserved); commit and push
  only on explicit approval.
- The installer writes only inside the target directory.

## Deferred work

See Non-goals.

## Result

<!-- Complete after verification; archive per base/docs/plans/README.md. -->
