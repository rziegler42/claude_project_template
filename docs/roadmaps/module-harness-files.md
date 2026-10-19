# Roadmap: module harness files

Status: Active
Updated: 2026-10-19

This roadmap is direction only. It does not authorize work, change
`docs/plans/next.md`, or commit the project to any item below.

## Purpose

Let a module carry the harness-specific files that serve it (skills, agents, scripts), installed
into a project's own harness directory instead of a developer's global configuration, with one
mechanism for built-in and external modules. The decision is
[ADR 0004](../decisions/0004-harness-files-in-modules.md), `Accepted` 2026-10-19 with the
approved [specification](../specs/module-harness-files.md). Candidate 1 is done; each later
candidate still needs its own plan and the owner's promotion.

## Current state

- Modules ship `slots/` and `files/`. `"harness": true` marks the `claude` and `codex` modules, the
  only way a module may be harness-specific. No module carries a skill or an agent.
- Skills and agents that serve a module live in `claude_global_config`: `freecad-scripts`
  (`cad-freecad`), `verilog-sby-formal` (`formal`), `graphify-workflow` and `graphify-semantic`
  (`graphify`), `second-opinion` (`plan-review`, `codex`). `verilog-verilator-sim`,
  `security-review`, `architecture-decisions`, the knowledge-base skills and four agents have no
  module.
- External stores ship slot fragments only (ADR 0003). The knowledge-base skills are global
  wrappers (that repository's ADR 0008).
- `claude-workflow` in the global configuration mixes a generic core (`commit`, `amend-message`,
  `remove`) with about 170 lines of Graphify tooling and a post-commit refresh.
- Owner decisions (2026-10-19), recorded in the ADR: a harness directory per module; one harness per
  project, chosen at install or added once to a project with none and never overridden; no `generic`
  directory; helpers, worker roles (free-form id and one-line contract) and a global-configuration
  dependency declared in `module.json` and reported by the installer; Graphify tooling ships with its
  module and the automatic refresh is dropped; external stores may ship harness files, trusted at
  registration through a digest-pinned approval.

## Ordered plan candidates

### 1. Specification and trust-model addendum (done 2026-10-19)

**Outcome:** an approved specification (`docs/specs/module-harness-files.md`) that fixes what the
ADR leaves open (see its Verification), and the ADR 0002 addendum for harness files, the marker read
and the approval. ADR 0004 is accepted with it.
**Dependencies:** none.
**Boundary:** documents only; no installer change.
**Promotion trigger:** the owner accepts the direction of ADR 0004. Met.

### 2. Harness directories and `--harness` (done 2026-10-19, plan 0018)

**Outcome:** the installer copies `harness/<name>/` into the harness root, records `harness` in the
manifest, refuses a different value and never overwrites an existing file; `--update` and `--remove`
cover the harness files like other module files. Built-in modules only.
**Dependencies:** 1.
**Boundary:** no declarations and no external stores yet. The plan also carries the specification's
`write_tree` mode change (every harness write `0644 & ~umask`), the `schema` 2 manifest and the
`harness_files` record, which every later candidate builds on.
**Promotion trigger:** candidate 1 complete. Met. Promoted 2026-10-19: the plan is drafted in
`docs/plans/next.md` and waits for the owner's approval.

### 3. Pilot: `cad-freecad` and `freecad-scripts` (template side done 2026-10-19, plan 0019)

**Outcome:** `cad-freecad/harness/claude/` carries the `freecad-scripts` skill; the global
configuration drops it. It needs no helper, so it proves the mechanism alone. Spans both
repositories as two plans.
**Dependencies:** 2.
**Boundary:** one module and one skill.
**Promotion trigger:** candidate 2 complete. Met. The template side is done (plan 0019); removing
the global copy is a separate plan in `claude_global_config`, still open.

### 4. Declarations and reporting (done 2026-10-19, plan 0020)

**Outcome:** `module.json` accepts `helpers`, `workers` and the global-configuration dependency; the
installer reports each as present or missing at install, `--add` and `--update`, and installs none.
The marker file is read as untrusted data. The global configuration writes the marker.
**Dependencies:** 2.
**Boundary:** reporting only; no module is converted yet.
**Promotion trigger:** candidate 3 shows the layout works. Met. Done in plan 0020; no real module
declares anything yet.

### 5. Graphify split and the `graphify` module

**Outcome:** the Graphify commands move into a script the `graphify` module ships, with
`graphify-workflow` and `graphify-semantic` in its harness directory; `claude-workflow` keeps its
generic core and no longer refreshes after a commit.
**Dependencies:** 4.
**Boundary:** two repositories; no hook and no automatic refresh.
**Promotion trigger:** candidate 4 complete.

### 6. `plan-review`, `codex` and the `claude` module

**Outcome:** `second-opinion` moves into the harness directory, `codex` becomes a neutral tool
module, `"harness": true` is retired, and the `claude` module's files become the base harness
directory.
**Dependencies:** 4. Migration for existing projects is decided in the plan.
**Boundary:** no change to `ask-codex`.
**Promotion trigger:** candidate 4 complete.

### 7. `formal`

**Outcome:** `verilog-sby-formal` moves into the `formal` harness directory.
**Dependencies:** 3.
**Boundary:** one skill. `verilog-verilator-sim` has no module and stays global unless the owner adds
a module for it.
**Promotion trigger:** candidate 3 complete.

### 8. External stores: registration review

**Outcome:** a store may ship `template-module/harness/<name>/`; `--register` lists the files, the
digest and static findings; `--approve <digest>` records approval; only matching files install; a
changed store is refused until approved again; identical skills install once and differing ones are
refused. Security-reviewed adversarially.
**Dependencies:** 2, 4.
**Boundary:** no model call and no network access by the installer.
**Promotion trigger:** candidate 4 complete and the owner asks for store-shipped harness files.

### 9. Knowledge-base stores

**Outcome:** the starter ships the consuming `knowledge-base` skill in its harness directory;
`knowledge-base-authoring` stays global. The starter's tool-neutral stance and the global
configuration's ADR 0008 are superseded for harness directories.
**Dependencies:** 8.
**Boundary:** coordinated with `claude_knowledge_base` and `claude_global_config`; the in-progress
knowledge-base skills roadmap there is reviewed first.
**Promotion trigger:** candidate 8 complete.

### 10. Global configuration cleanup

**Outcome:** the moved skills and agents are gone from the global configuration, its sync and tests
are updated, and the marker file is written.
**Dependencies:** 3, 5, 6, 7, 9 as each lands.
**Boundary:** `claude_global_config` only.
**Promotion trigger:** each removal follows its conversion.

## Deferred

- A harness other than `claude`; the table supports it, but no module has files for one.
- A module for `verilog-verilator-sim`.
- Human sign-off tooling for reviewed approvals beyond the owner passing the digest.
- Switching harness in place (the answer is a new project).

## Related decisions

- [ADR 0004](../decisions/0004-harness-files-in-modules.md) (`Accepted`), the
  [specification](../specs/module-harness-files.md) (`Approved`), ADRs 0001 to 0003, and the
  [external-modules roadmap](external-modules.md).
