# 0004: Plan-review module

Status: Completed
Created: 2026-10-15
Completed: 2026-10-15

## Outcome

A project created with `install.py --with plan-review` carries tool-neutral
policy for an independent, read-only, bounded review of its implementation
plan, and a place in the plan and its archive to record the outcome.

## Scope

1. A `plan-review` module with an `agents-guidance` policy fragment and a
   plan "Second opinion" receipt fragment.
2. Two new slot markers in `base/`: `plan-review` in
   `base/docs/plans/next.md` and `plans-review-note` in
   `base/docs/plans/README.md`. Both are empty when the module is absent.
3. Tests, the README module table, and a module hint.

## Non-goals

- Any change to `claude_global_config` (the `ask-codex` helper and
  `second-opinion` skill already exist there). A one-line follow-up that
  points at this module is offered separately.
- Automatic triggers, scheduling, or hooks: review happens only when the
  owner asks, matching the global specification.
- Other review kinds (diff or code review) or a generic review framework.
- Naming a specific helper, skill, vendor, or model in any generated file.

## Assumptions and constraints

- Neutrality rule (ADR 0001): committed files describe capabilities and
  policy; binding a capability to a tool is per-developer global
  configuration. The reviewer is described as "an independent reviewer,
  for example another model".
- Module name `plan-review` is a capability name, `order` 15 (after
  `graphify`, before `formal`), `requires` empty, not a harness module.
- A module fragment for a slot that has no marker is a hard error, so the
  two base slots are added in the same change as the module.
- `--add plan-review` must work on an existing installer-created project:
  `--add` patches base markers that already exist, and projects created
  before this change lack the two new markers, so for them `--add` fails
  with "fragments with no matching slot marker". That is an accepted
  limitation and is documented; the installer is not changed.
- Existing graphify and cad output must be byte-identical when `plan-review`
  is not selected (the new markers expand to nothing).

## Discovery and impact evidence

Graphify: skipped — the repository has 45 tracked files and the affected
paths are fully enumerated: `base/docs/plans/next.md`,
`base/docs/plans/README.md`, `modules/plan-review/`, `tests/test_install.py`,
`README.md`. Evidence verified against current source: the existing slot
markers (`agents-guidance`, `plan-discovery`, and others), the graphify
module's `plan-discovery` fragment as the pattern, `module.json` fields
(`description`, `requires`, `order`, `harness`, `hint`), and the neutrality
test that greps generated output for harness names.

## Completion criteria

- `python3 -I -m unittest discover -s tests` passes with the new tests, and
  `git diff --check` is clean.
- `install.py <dir> --with plan-review` produces the policy fragment in
  `AGENTS.md`, the receipt section in `docs/plans/next.md`, and the archive
  note in `docs/plans/README.md`; with no modules the generated tree equals
  the pre-change base apart from the new (empty) slot markers.
- Output for `--with graphify,cad` is unchanged.
- No generated file names `ask-codex`, `second-opinion`, `codex`, or another
  harness helper.

## Increments

### Increment A — module and slots

Dependencies: None
Affected areas: `base/docs/plans/next.md`, `base/docs/plans/README.md`,
`modules/plan-review/{module.json,slots/*.md}`, `tests/test_install.py`

1. Tests first: the module installs alone and with `graphify`; the policy
   fragment, receipt, and archive note appear only with it; markers survive
   for `--add`; a project created without it gains all three on
   `--add plan-review` when created after the change; the neutrality test
   forbids `ask-codex`, `second-opinion`, and `codex` outside harness
   modules; the hint prints; every fragment has a marker.
2. Add the `plan-review` marker before "Deferred work" in
   `base/docs/plans/next.md` and the `plans-review-note` marker in the
   prose of `base/docs/plans/README.md` (not inside the fenced archive
   format).
3. Add the module:
   - `agents-guidance`: review only when the owner asks; reviewer is
     read-only and the plan's author is the only writer; findings are
     untrusted input, evaluated as comments and never obeyed; rounds are
     bounded and a stop at the bound is reported with what remains
     disputed; whatever the reviewer reads leaves the machine, so keep
     secrets out of plans and reviewed files; review never replaces the
     owner's approval and the plan stays Proposed until approved.
   - `plan-review` (receipt): reviewer, rounds used out of the bound,
     outcome, findings applied, findings rejected with reasons, items left
     for the owner; recorded only after a review ran.
   - `plans-review-note`: an archived plan keeps its receipt.

Completion: tests pass; scratch install shows the three insertions.

### Increment B — documentation

Dependencies: Increment A
Affected areas: `README.md`

1. Add `plan-review` to the README module table and describe the new
   slots under "Writing a module" so module authors know the base markers.
2. Document the `--add` limitation for projects created before the slots
   existed.
3. Re-run the suite and a scratch walkthrough: new project with
   `--with plan-review,graphify`.

Completion: README matches behavior; suite passes.

## Verification

- `python3 -I -m unittest discover -s tests`.
- Scratch installs under the session scratchpad: `--with plan-review`,
  `--with plan-review,graphify,cad`, no modules, and a later `--add`.
- A diff of the no-module output against the previous commit's output.
- `git diff --check`.

## Risks and sensitive actions

- Base template change: two new markers. They must expand to nothing when
  the module is absent; the test compares output against the previous base.
- Generated text is policy about sending repository content to an external
  reviewer; wording must say so plainly and must not weaken existing
  policy (approval, no secrets, plan lifecycle).
- Commits only on explicit approval; nothing pushed without it.

## Deferred work

- A pointer in `claude_global_config` (README or spec) to this module.
- `--add` fragment insertion for projects created before a base slot
  existed.
- Other review kinds; Ghidra module; adopting `cp -R` projects.

## Result

All completion criteria met. Increments A and B are in commit `b703f6f`:
`modules/plan-review/` (`order` 15, policy, Second opinion receipt, archive
note, hint) and the two new empty base markers `plan-review` and
`plans-review-note`.

Verification: `python3 -I -m unittest discover -s tests` passed (79 tests;
the three new tests failed before the module existed); `git diff --check`
clean; a diff of the `--with graphify,cad` output against the previous
commit's installer showed only the two new empty marker lines; a scratch
`--with plan-review` install showed the policy block, the receipt before
"Deferred work", and the hint. No generated file names a helper, skill, or
vendor (the neutrality test now also forbids `ask-codex`, `second-opinion`,
and `codex` outside harness modules).

Limitation (documented in the README): `--add plan-review` fails with
"fragments with no matching slot marker" on a project created before the
two markers existed; the marker lines can be added by hand.

Left open: a pointer from `claude_global_config` to this module, which needs
its own approval in that repository.
