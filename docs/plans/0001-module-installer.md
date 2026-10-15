# 0001: Modular project installer

Status: Completed
Created: 2026-10-15
Completed: 2026-10-15

## Outcome

New projects are created with `install.py` instead of `cp -R`. The installer
assembles a project from `base/` plus opt-in modules, starts a fresh git
repository with no remote and no commits, sets an explicit local git
identity, and can add modules later. Governing decision: ADR 0001.

## Scope

- Restructure into `base/` and `modules/` (`claude`, `cad`, `cad-freecad`,
  `graphify`, `formal`); `LICENSE` stays at the repository root and is never
  copied.
- `install.py`: new project, `--with`, `--name`, `--dry-run`, `--list`,
  `--add`, git identity flags and prompt, `.template-manifest`, placeholder
  summary.
- Tests, README, and the template-source mentions in `claude_global_config`.

## Non-goals

- Ghidra and Codex second-opinion modules.
- Adopting pre-existing `cp -R` projects; `--remove`; splitting planning docs
  into a module; extracting `claude-workflow` into a neutral helper.
- Pre-commit identity guards or `includeIf` configuration for existing repos.

## Assumptions

- Python 3.9+ standard library only; macOS primary, Linux secondary.
- `docs/plans/` and `docs/roadmaps/` base paths are frozen because external
  tooling reads them.
- No default-on modules; harness shims are independent modules.
- Committed content names capabilities and policy, never a private helper or
  skill.

## Completion criteria

- Module matrix passes under `python3 -I -m unittest discover -s tests`.
- Installer output for `--with cad-freecad,graphify,formal,claude` is
  content-equivalent to the pre-change template.
- A new project has a fresh `.git` with no remote, no commits, and a local
  identity that never came from global configuration unless explicitly
  bypassed.

## Constraints

- No dependency additions, no network access, no commits or pushes without
  approval.

## Increments

### Increment A — restructure, then ADR; no behavior change

Dependencies: None
Affected areas: whole repository layout, `docs/`

1. Move shipped files into `base/` and `modules/` with `git mv`.
2. Extract Graphify, formal, CAD, CAD-FreeCAD, and Claude content into module
   slots; convert the docs index to a list.
3. Write ADR 0001 and the repository's own `docs/plans/`, `docs/decisions/`.
4. Root `README.md` describes the template and installer.

Completion: assembled output is content-equivalent to the pre-change
template. Met: diff against the `3895ebc` export differed only by slot
markers, the missing `LICENSE`, the docs-index list conversion, neutralised
harness wording, and the FreeCAD text moved into `cad-freecad`.

### Increment B — installer core (new project)

Dependencies: Increment A
Affected areas: `install.py`, `tests/`

1. Tests first, then `install.py`.

Completion: tests pass and a manual run produces the expected tree with an
empty `git log`. Met.

### Increment C — `--add`, `--list`, idempotency

Dependencies: Increment B
Affected areas: `install.py`, `tests/`

1. Tests, then implementation.

Completion: `--add` changes only the module's files and marked fragments.
Met: tests assert equality with a fresh install, idempotency, conflict
refusal, and preservation of user edits.

### Increment D — documentation and global-config mentions

Dependencies: Increment C
Affected areas: root `README.md`; `claude_global_config` `CLAUDE.md`,
`README.md`

1. Document usage, module authoring, and the harness boundary.
2. Update the template-source mentions in `claude_global_config` and mirror
   into `~/.claude`.

Completion: README walkthrough reproduced from a clean scratch directory.
Met: `--list`, `--dry-run`, install, and `--add` were run from a scratch
directory; the manifest recorded the template commit and `template_dirty:
false`.

## Verification

- `python3 -I -m unittest discover -s tests`: 30 tests, all passing, on the
  committed tree (`e575e4d`).
- Golden comparison against the pre-change export, reviewed by the owner.
- `git diff --check` clean in both repositories.
- `claude_global_config`: `CLAUDE.md` mirror matches; `install.sh --check`
  reports only the intentional local `settings.json` preferences.

## Deferred work

- Interactive prompts (module list, git name and email) are implemented but
  were not exercised by an automated test or a TTY run.
- `--add` inserts fragments only for newly added modules.
- Ghidra and Codex second-opinion modules; `claude_global_config` helper and
  skill counterparts; trigger design still undecided.
- Adopting pre-existing `cp -R` projects; `--remove`; splitting planning
  docs into a module.
- A neutral shared workflow helper in place of `claude-workflow`.
- `claude_global_config` has no merge for local-only `settings.json` keys.

## Result

Implemented in commits `66e70cd` (restructure) and `e575e4d` (installer) in
this repository and `7730192` in `claude_global_config`. All completion
criteria met; none pushed at archive time.
