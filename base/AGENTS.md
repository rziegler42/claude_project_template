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
- Commit messages and pull request descriptions describe the change only. Do not
  mention the AI tool, model, or session that helped produce it, and do not add
  `Co-Authored-By`, `Generated with`, or session-link lines for it.
- Treat automated memory and prior conversation recall as potentially stale;
  current repository evidence wins.
- Keep one active implementation plan in `docs/plans/next.md`; archive fully
  verified or explicitly superseded plans according to `docs/plans/README.md`.
- Planning tools and skills may guide plan construction, but repository plans
  belong in `docs/plans/`. Put durable requirements and specifications in
  `docs/specs/`; do not create tool-owned planning or specification directories.
- Keep tracked, non-authoritative multi-plan direction in `docs/roadmaps/`.
  A roadmap does not authorize implementation or change an active plan.

<!-- @module-slot: agents-guidance -->
