# 0001: Module and slot architecture for the project template

Status: Accepted
Date: 2026-10-15

## Context

The template was copied with `cp -R`, which carried the template's `.git`
history and remote into every new project, and shipped optional domain guidance
(CAD, Graphify, formal verification) and harness-specific files to projects
that did not need them. That guidance was woven into shared files
(`AGENTS.md`, `README.md`, `docs/README.md`, `docs/development.md`,
`docs/plans/next.md`, `.gitignore`), so it could not be left out by deleting a
file.

The committed content must stay harness-agnostic: developers on the same
repository may use different coding harnesses.

## Decision

- `base/` holds the files every project receives. `modules/<name>/` holds
  opt-in content: `files/` (copied verbatim), `slots/<slot>.md` (fragments),
  and `module.json` (`description`, `requires`, `order`).
- Base files, and module files, declare insertion points as marker lines
  `@module-slot: <name>` inside the file's own comment syntax. The installer
  inserts each selected module's fragment for that slot, wrapped in
  `BEGIN/END module:<name>` markers, and leaves the slot marker so that a
  later `--add` is a deterministic patch.
- `install.py` (Python 3 standard library only) assembles a new project,
  creates a fresh `git init` with no remote and no commit, sets a local git
  identity from explicit input, and records `.template-manifest`.
- Harness entry points (such as `CLAUDE.md`) are independent modules.
  Committed content names capabilities and policy, never a private helper or
  skill; binding a capability to a tool is per-developer configuration.
- CAD is split into a tool-neutral `cad` module and tool modules
  (`cad-freecad`, later others) that `require` it.
- `LICENSE` is not copied; each project chooses its own.

## Alternatives considered

- **Strip marked regions from the flat template.** Fragile, and leaves the
  template cluttered with every domain at once.
- **Copier or cookiecutter.** Adds a dependency; the standard library is
  sufficient for this scope.
- **A single "harness" selector.** Mixed-harness teams make a single choice
  wrong; independent modules compose.

## Consequences

- The template repository root is no longer itself a usable project.
- Adding a domain or tool is a new directory; the installer does not change.
- `--add` works only for projects created by the installer.
- Slot names are a public contract between `base/` and modules; renaming one
  is a breaking change.

## Verification

- `tests/` generates each module combination into a scratch directory and
  checks the output tree, git state, identity handling, and neutrality (no
  harness-helper names outside harness modules).

## Amended by 0004

[ADR 0004](0004-harness-files-in-modules.md) and the
[module harness files specification](../specs/module-harness-files.md) amend three clauses, with
effect from 2026-10-19; the rest of this record is unchanged:

- Decision, "Harness entry points (such as `CLAUDE.md`) are independent modules": module-owned
  harness files install under a harness the project records. Entry-point modules keep working until
  the roadmap retires `"harness": true`.
- Alternatives, "A single harness selector" rejected: rejected for committed neutral content only; a
  project records one harness for module-owned harness files.
- Verification, no harness-helper names outside harness modules: the neutrality test exempts
  `harness/` directories.

## Related files and decisions

- `base/`, `modules/`, `install.py`
- `docs/plans/next.md`
