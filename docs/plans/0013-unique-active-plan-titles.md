# 0013: Give active plans a unique title

Status: Completed
Created: 2026-10-18
Completed: 2026-10-18

## Goal

An active plan started from the template carries a unique, descriptive title,
so a tool that identifies a plan by its heading and `Created:` line (the
`ask-codex` review helper) can never mistake a new plan for one it already
reviewed.

## Scope

- `base/docs/plans/next.md`: replace the shared `# Next plan` heading with the
  placeholder `# REPLACE_WITH_PLAN_TITLE`, following the file's existing
  `REPLACE_WITH_` convention, and add a comment saying to fill in the title and
  the `Created:` date.
- `base/docs/plans/README.md`: state that an active plan replaces the heading
  with a short unique title (no number, since the number is only known at
  archive time) and fills in `Created:`; that archiving renames the heading to
  `# NNNN: Plan title`; and why (tools identify a plan by title and date).
- `docs/plans/next.md` in this repository: reset to the new empty template
  after archiving, like every plan.
- One test pinning the new template heading and the README rule.

## Non-goals

- The `ask-codex` guard that refuses a placeholder title or `YYYY-MM-DD`
  `Created:` date. The global configuration owner applies that separately, in
  `claude_global_config` and `~/.claude/bin/ask-codex`.
- Changing the installer. `--update` keeps differing files, so existing
  projects keep their `# Next plan` empty template; they gain the rule through
  the updated `README.md` only where the file is unmodified.
- Renaming or editing archived plans.

## Assumptions and constraints

- Verified: `ask-codex` keys a plan by `sha256(heading + "\n" + Created)`
  (`resolve_plan`, `~/.claude/bin/ask-codex`). In othello, three of eight
  reviews are keyed to the bare title `Next plan`.
- Verified: nothing in the installer or tests depends on the text `Next plan`;
  tests reference `docs/plans/next.md` by path only.
- The helper still sees `Status: Empty` and refuses the empty template, so the
  placeholder heading is never reviewed.
- Coordination: the helper owner should refuse both `Next plan` (existing
  projects) and `REPLACE_WITH_*` titles.

## Discovery and impact evidence

Graphify: skipped - scope is enumerated (two template files, this repository's
own copy, one test) and the helper's identity rule was read directly.

## Completion criteria

- `base/docs/plans/next.md` heading is `# REPLACE_WITH_PLAN_TITLE`.
- `base/docs/plans/README.md` states the title rule and the archive rename.
- The new test passes and the full suite passes.
- `git diff --check` is clean.

## Increments

### Increment A — Template heading, README rule and test

Dependencies: None
Affected areas: `base/docs/plans/next.md`, `base/docs/plans/README.md`,
`docs/plans/next.md`, `tests/test_install.py`

1. Add a test that fails first: the installed `docs/plans/next.md` does not
   start with `# Next plan`, and `docs/plans/README.md` mentions retitling the
   active plan.
2. Change the heading and comment in `base/docs/plans/next.md`; add the rule to
   `base/docs/plans/README.md`.
3. Run `python3 -I -m unittest discover -s tests` and `git diff --check`.
4. After archiving, reset this repository's `docs/plans/next.md` to the new
   template.

Completion: the test failed before the change and passes after; the suite
passes.

## Verification

- `python3 -I -m unittest discover -s tests`
- `git diff --check`

## Risks and sensitive actions

None identified. Existing projects are unaffected until they choose to adopt
the new template text; until the helper owner ships the guard, they remain
exposed to the collision.

## Result

Implemented as planned.

- `base/docs/plans/next.md` now starts with `# REPLACE_WITH_PLAN_TITLE` and a
  comment telling the author to set a unique title and the `Created:` date.
- `base/docs/plans/README.md` states the title rule, why it matters, and that
  archiving renames the heading to `# NNNN: Plan title`.
- New test `test_empty_plan_heading_is_a_placeholder_not_a_shared_title`
  failed before the change (heading was `# Next plan`) and passes after.
- Full suite: 231 tests pass (230 before plus the new one). `git diff --check`
  is clean.

Remaining risk: projects installed earlier keep `# Next plan` until their
owners retitle it, so they stay exposed to the collision until the `ask-codex`
guard (owned by the global configuration project) ships.
