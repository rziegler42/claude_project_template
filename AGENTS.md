# Project instructions

## Source of truth

When sources disagree, use this order:

1. Current user instruction
2. Repository instructions that apply to the target path
3. Accepted decisions in `docs/decisions/`
4. Current architecture and development documentation
5. Current code, tests, and configuration as implementation evidence
6. Recalled or external context

## Working agreement

- Read `README.md` for the project purpose and `docs/development.md` for
  commands.
- Inspect relevant code, tests, and configuration before changing them.
- Make small, reviewable changes and avoid unrelated cleanup.
- For behavioral or build changes, run the narrowest relevant check during
  implementation, diagnose failures, correct them, and rerun.
- Prefer repository-documented commands. Record new or changed commands in
  `docs/development.md`.
- Add or update proportionate tests for behavioral changes.
- For retained, untracked local diagnostics, use
  `/.debug/<YYYY-MM-DD>-<topic>/`. Add `/.debug/` to `.git/info/exclude`, not
  tracked `.gitignore`; keep a local README with the commit SHA, command and
  tool versions, purpose, and conclusion. Never commit or index these files.
  Record durable conclusions in tracked documentation, decisions, or tests.
- Do not commit, push, publish, deploy, install dependencies, use secrets, or
  perform destructive cleanup without explicit approval.
- Treat automated memory and prior conversation recall as potentially stale;
  current repository evidence wins.
- Keep one active implementation plan in `docs/plans/next.md`; archive fully
  verified or explicitly superseded plans according to `docs/plans/README.md`.
- Planning tools and skills may guide plan construction, but they do not choose
  a competing storage location. Do not create a parallel active plan in
  `docs/superpowers/`, `.superpowers/`, or another tool-owned directory unless
  repository instructions explicitly replace this lifecycle.
- Keep tracked, non-authoritative multi-plan direction in `docs/roadmaps/`.
  A roadmap does not authorize implementation or change an active plan.

## Graphify (when configured)

Graphify is a discovery and impact-analysis aid, not a source of truth or an
implementation requirement.

Use it when:

- Architecture or ownership is unfamiliar.
- A change, refactor, ADR, or review spans multiple components.
- Dependency or impact analysis is needed.
- Ordinary file inspection might miss affected paths during debugging or review.

Skip it when:

- The change is narrow and the relevant files are known.
- The task is an isolated test, documentation edit, or mechanical change.
- The active plan already enumerates the complete file scope.

Refresh policy:

- Do not build or refresh the graph automatically at session start.
- Check freshness before relying on a graph query and verify important findings
  against current files.
- Refresh code relationships after a coherent code change only when future
  impact analysis would benefit.
- Request a semantic refresh only after a material architecture, ADR, or design
  document change that should be discoverable through the graph.
- Do not refresh merely because documentation changed.
