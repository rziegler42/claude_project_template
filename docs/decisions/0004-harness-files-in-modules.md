# 0004: Harness files in modules

Status: Accepted
Date: 2026-10-19
Accepted: 2026-10-19, with the [specification](../specs/module-harness-files.md)

## Context

The template is harness-agnostic: committed content names capabilities and policy, never a
specific helper or skill (README, "Boundaries"). Harness-specific skills, agents and helpers
therefore live in each developer's global configuration. For Claude Code that is the
`claude_global_config` repository, which mirrors them into `~/.claude`.

Several of those skills and agents exist only to serve one template module:
`freecad-scripts` (`cad-freecad`), `verilog-sby-formal` (`formal`), `graphify-workflow` and
`graphify-semantic` (`graphify`), and `second-opinion` (`plan-review` and `codex`). They are
maintained apart from the module, can drift from its text, and are loaded in every repository
whether or not it uses the module. The template already has an escape hatch, `"harness": true`,
used by the `claude` and `codex` modules, but it makes a harness a separate module. A module's
`files/` are copied verbatim, so a module could ship a skill file only as an ordinary file at a
project path it chooses. The mechanism has no per-module harness namespace, no harness selection
and no record of which harness a project uses, and policy confines harness-specific content to
harness-marked modules.

[ADR 0003](0003-external-module-mechanism.md) limits an external store to slot fragments and
defers `files/`, because files enlarge the read boundary. The knowledge-base skills that consume
and author stores are in the global configuration for the same reason, under that repository's
ADR 0008, which keeps the starter tool-neutral.

## Decision

1. **Layout.** Any module may contain `harness/<harness>/`. The directory name matches
   `[a-z][a-z0-9-]{0,31}`. Its files are copied into the project under the harness's own root
   (`claude` maps to `.claude/`, `opencode` to `.opencode/`; the template owns the table), for
   example `harness/claude/skills/x/SKILL.md` becomes `.claude/skills/x/SKILL.md`. The table also
   names, per harness, the few entry-point files that belong at the project root rather than under
   the root (for `claude`, `CLAUDE.md`), so a harness directory holds them in a `root/` subdirectory
   (`harness/claude/root/CLAUDE.md` becomes `CLAUDE.md`). Tool-neutral
   scripts stay in `files/`. There is no `generic` harness directory: neutral content already
   lives in `slots/` and `files/`.
2. **Selection.** A project has at most one harness, chosen with `--harness <name>` at creation,
   or on `--add` for a project that has none, and recorded in `.template-manifest`. A different
   value for a project that has one is refused before anything is written; the same value changes
   nothing; an absent option uses the recorded one. With no harness, a project gets only the
   neutral content. Changing harness means creating a new project. A module with no directory
   for the project's harness installs its neutral part and says so. One collision rule covers every
   harness file path, whatever supplies it: a path that does not exist is written and recorded
   with its supplying module; an existing path with identical bytes is left alone and the module is
   recorded as a co-supplier; an existing path with different bytes is never overwritten and is
   reported as a conflict. Removing a module deletes only unedited files it alone supplies, and a
   shared file stays until its last supplier is removed.
3. **One mechanism.** `"harness": true` is retired. The `claude` module's entry-point files become
   the base harness directory, and the `codex` module becomes a neutral tool module whose Claude
   packaging (the `second-opinion` skill) is a harness directory beside it. The details are
   fixed by the specification.
4. **Declarations.** `module.json`, for built-in and external modules alike, may declare what the
   harness files depend on, and the installer reports each item as present or missing and never
   installs one:
   - `helpers`: names of machine-level helpers (for example `ask-codex`, `claude-workflow`),
     found by looking for an executable on `PATH`, never run.
   - `workers`: roles the module wants a harness to supply, each a free-form id with a one-line
     contract of what it reads and writes (for example a bounded chunk extractor that reads the
     listed files and writes one named output). The harness directory implements a role in its
     own format and states which roles it implements in one declaration inside the directory
     (role id to the file that implements it; the file syntax is the specification's). The
     installer matches role ids exactly. A wanted role with no matching declaration, or no harness
     directory for the project's harness, is a warning at install time. The declaration is the
     module author's claim and the installer does not verify that the file does the job.
   - a dependency on the harness's global configuration, detected through one fixed marker file
     per harness that the global configuration writes. The installer reads it as untrusted data:
     a regular file, size-limited, not a symlink.
5. **Machine-level helpers stay global** (`ask-codex`, `remote-runner`, the commit approver, hooks)
   because they hold credentials, machine state or approval policy. Graphify tooling ships with
   the `graphify` module as a tool-neutral script, and `claude-workflow` keeps its generic core
   (`commit`, `amend-message`, `remove`). There is no automatic post-commit Graphify refresh and
   no git hook; the refresh is an explicit step, and `graph-doctor` reports a stale graph.
6. **External modules.** A store may ship `template-module/harness/<harness>/`, and a store that
   does must declare a `module_format` newer than any installer from before this ADR accepts, so
   that installer refuses it before writing rather than installing the neutral fragments and
   omitting the harness files. The `harness/` tree is part of the digest recorded for the store.
   Registration is the trust step, so a store with a `harness/` directory must be registered and
   approved before use: selecting it by `name=path` without an approval is refused before anything
   is written, and no other approval record exists. `--register` lists the harness files with sizes, a digest over
   the whole set and the installer's static findings (executable files and instruction-like
   phrases; symlinks, special files and size limits are refusals), and installs nothing. The owner
   reviews exactly those files, with a security review, and approves by passing the digest back
   (`--approve <digest>`). The approval is recorded in a file beside the registry (so an installer
   from before this ADR keeps reading the registry), bound to the store's canonical path and the
   digest, and only files that match it are ever installed; `--add` and `--new` re-check the digest
   and refuse a changed store until it is approved again, a named `--update` refuses it, and a full
   `--update` skips it and says so. `--remove` needs no approval. The same skill name with
   identical content installs once (the collision rule of decision 2); with different content it is
   refused. The installer runs no model and makes no network call.
7. **The global configuration keeps what is cross-cutting:** skills and agents with no module
   (`security-review`, `architecture-decisions`, the knowledge-base authoring skill, which creates a
   store before any project exists, and the generic agents), the helpers and hooks, settings, and the
   marker file.

## Alternatives considered

- Keep every harness file global. Rejected: skills drift from the module that documents them and
  load in unrelated repositories.
- A separate harness module per tool, the `codex` pattern. Rejected: it names harness products in
  module text and makes modules inconsistent.
- A `generic` harness directory. Rejected: it duplicates `slots/` and `files/`.
- Several harnesses per project, or switching in place. Rejected: switching means a new project, which
  is simpler and avoids overwriting one harness with another.
- A harness chosen by whichever directories exist in the project. Rejected: implicit and easy to get
  wrong; the manifest records an explicit choice.
- Shipping helpers from modules. Rejected: machine-level helpers hold secrets and approval policy and
  must not be copied into every project.
- The commit helper running a project-local Graphify script after each commit. Rejected: a privileged
  global helper would execute code from a repository that may have just been cloned.
- Harness files for external stores keyed by the store's `type` and owned by the template, so a store
  never supplies instruction files. Rejected by the owner in favour of registration-time trust and a
  digest-pinned approval.
- A fixed vocabulary of worker roles. Rejected: a role such as the Graphify chunk extractor is too
  specific for a shared list.
- Installer-run model review at registration. Rejected: the installer is a standard-library script that
  makes no network call.

## Consequences

- The installer copies instruction files (skills and agents) that Claude Code loads automatically, so
  anyone who opens a project runs what it contains. The trust model (ADR 0002) needs an addendum for
  harness files, the one marker read outside the target and the digest-pinned approval.
- `module_format` and `module.json` change. An installer from before this ADR does not refuse a
  built-in module's `harness/` directory or unknown `module.json` keys: it would install the module
  and silently omit the harness files. An external store's unknown keys are refused. The specification
  must therefore give a project that records a harness something an existing installer validates and
  refuses (a manifest change it rejects), so an older installer fails closed rather than omitting files.
- A review is evidence, not proof. The approval is the owner's act. It guards new installs only: files
  already copied into a project do not change when the store does.
- A skill moved out of the global configuration exists only in projects that installed its module. A
  migration leaves global and project copies side by side until the global one is removed.
- Supersession, effective when this ADR is Accepted and not before:
  - ADR 0001 rejected "a single harness selector" because mixed-harness teams make one choice wrong.
    This ADR supersedes only that rejection and the clause that harness entry points are independent
    modules, for module-owned harness files. It keeps that ADR's rule that committed neutral content
    (`base/`, `slots/`, `files/`) names capabilities and policy, never a tool. The cost: one repository
    cannot carry two harnesses' module files through the installer; a team mixing harnesses shares the
    neutral content and each developer supplies the rest through their global configuration.
  - ADR 0003 and `docs/specs/external-modules.md` limit an external store to slot fragments. This ADR
    supersedes only that file exclusion, and only for `template-module/harness/<harness>/` under
    decision 6. `files/` stays excluded for external stores. Where they conflict, this ADR governs
    those directories and ADR 0003 governs everything else.
  - The global configuration's ADR 0008 (a different repository) is the owner's to update. This ADR
    does not change it.
  Both template records get an "Amended by 0004" note on Acceptance; the specification names the
  exact clauses.
- The knowledge-base consuming skill can move into the starter's harness directory. Two registered stores
  shipping the same skill are handled by the digest rule.

## Verification

Not implemented; the specification is approved and fixes the points below. The roadmap [module-harness-files](../roadmaps/module-harness-files.md) orders the
plans; each records its own evidence. The ADR fixes the contract's rules (selection, collision,
approval binding and re-checking, fail-closed refusal by older installers, untrusted reads). The
specification fixes names, shapes and numbers only: the harness root table and the refusal of an
unknown harness name, the marker file's location and format, the syntax of the helper, worker and
role declarations, the manifest shape for the harness, co-suppliers, helpers and approvals, the
module format number and the manifest change older installers reject, how removal recognises an
unedited harness file, and the exact clauses of ADRs 0001 and 0003 that this ADR amends.

## Related files and decisions

- ADR 0001 (modules and slots), ADR 0002 (trust model), ADR 0003 (external modules).
- `README.md` (Boundaries, Writing a module), `docs/specs/external-modules.md`.
- In `claude_global_config`: ADR 0008 (knowledge-base skills are thin wrappers) and the
  `knowledge-base-skills` roadmap.
