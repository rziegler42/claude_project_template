# 0017: Harness file specification and trust addendum

Status: Completed
Created: 2026-10-19
Completed: 2026-10-19

## Goal

An approved specification, `docs/specs/module-harness-files.md`, and an ADR 0002 addendum fix
everything [ADR 0004](../decisions/0004-harness-files-in-modules.md) leaves open, so the installer
plans that follow (roadmap candidates 2 to 10) can be written without further design decisions.
This is roadmap candidate 1.

## Scope

- Write the specification. It settles, as names, shapes, numbers and rules:
  - the harness root table (`claude` to `.claude/`, others later), the `root/` convention for
    root-level entry points (`harness/<h>/root/` to the project root), and the refusal of an unknown
    harness name;
  - the `--harness` option and the manifest shape for the recorded harness, per-path suppliers and
    co-suppliers, helpers, and approvals;
  - the `module.json` syntax for `helpers`, `workers` and the global-configuration dependency, the
    one declaration file inside a harness directory that maps role ids to files, and the marker
    file's location, format and size limit;
  - the module format number for harness-bearing external stores, the digest rule that covers the
    `harness/` tree, and the manifest change that makes an installer from before ADR 0004 refuse a
    project that records a harness;
  - `--register` output, `--approve <digest>`, where the approval is stored, and the verb-by-verb
    digest re-check, including `--add` of an already-installed name and `--update`;
  - the refusal of a `name=path` store that carries `harness/` without a registered approval;
  - how removal recognises an unedited harness file and handles a file with several suppliers;
  - the exact clauses of ADRs 0001 and 0003 and of `docs/specs/external-modules.md` that ADR 0004
    amends, and the "Amended by 0004" note for each.
- Write the ADR 0002 addendum: new read inputs (the `harness/` tree, the marker file, the approval
  record), the new write locations (the harness root and root-level entry points), mitigations to be
  covered by regression tests in the later plans, and accepted residuals.
- Review the specification with Codex (`review-spec`) and with an adversarial `security-reviewer`
  pass, and apply or reject each finding with a reason.
- Record the owner's acceptance of ADR 0004 and approval of the specification (Increment D).

## Non-goals

- Any change to `install.py`, `modules/`, `base/`, tests or the README's behaviour text.
- Moving any skill or agent, and anything in `claude_global_config` (its ADR 0008, the Graphify
  split of `claude-workflow`, the marker file's writer). Findings that concern that repository are
  listed for the owner, not acted on.
- Choosing which skills move first; the roadmap orders that.
- Migration of existing projects for candidate 6; that plan decides it.

## Assumptions and constraints

- ADR 0004 is `Proposed` and stays so until the owner accepts it together with the approved
  specification. Nothing is implemented before then.
- The Codex review of ADR 0004 (four rounds) did not re-review its last two fixes, the `root/`
  convention and the refusal of path-only stores. The specification reviews must test both.
- Verified against `install.py` and the specs on disk: an external descriptor rejects unknown keys
  and unsupported `module_format` values before writing, while a built-in module's unknown
  `module.json` keys and a `harness/` directory are ignored. The external digest covers
  `module.json` and `slots/*.md` only. A `name=path` store needs no registry entry, and `--add` of
  an already-installed name reads neither the store nor the registry. The specification must change
  or except each of these explicitly.
- The security pass cannot exercise behaviour that is not implemented. It runs the real installer in
  a scratch directory to confirm the current behaviour the specification builds on (a store with a
  `harness/` directory, a planted file, a symlink, a changed store and a `name=path` store, each
  against today's installer) and attacks the specification's rules by reading. The implementation
  plans repeat the hostile cases as regression tests.
- Documentation only: no dependency, secret or destructive action is involved.

Graphify: skipped — the work is documentation, the affected documents are enumerated above, and the
graph does not exist in this checkout (`graph_missing`); the code facts above were checked directly
in `install.py`.

## Completion criteria

`docs/specs/module-harness-files.md` exists with `Status: Approved`, and every point ADR 0004's
Verification section lists as left to the specification has a rule in it; the ADR 0002 addendum is
present; the specification's `## Review record` shows the Codex review converged or lists its remaining
findings for the owner, and shows the security pass with each finding applied or rejected with a
reason and the cases not exercised; ADR 0004
is `Accepted` and its index row updated, with the "Amended by 0004" notes on ADRs 0001 and 0003 and
the external-modules specification; `python3 -I -m unittest discover -s tests` still passes
unchanged; `git diff --check` is clean.

## Increments

### Increment A — Write the specification

Dependencies: None
Affected areas: `docs/specs/module-harness-files.md` (new), `docs/specs/README.md` if it indexes specs

1. Draft the specification from ADR 0004 and the Scope list, following the shape of
   `docs/specs/external-modules.md` (terms, descriptor, syntax, verification, manifest, trust
   model, acceptance criteria). Where the ADR fixes a rule, quote it; do not reopen it.
2. For each external-modules rule the ADR relaxes (no `files/`, no `harness` key, never
   harness-specific, optional registration, `--add` not reading an installed store), state the
   narrow replacement and leave the rest in force.
3. Give every rule an acceptance criterion a later plan can turn into a test, including the hostile
   cases: unknown harness name, `root/` traversal, a symlink or special file in `harness/`, a
   `.git` component, case aliases, an oversized tree, a changed digest, a `name=path` store, an
   older installer reading the project, and a half-installed project after an interrupted run.
4. Set `Status: Draft`.

Completion: every open point from ADR 0004 maps to a section of the draft, listed in a short
table at its end.

### Increment B — ADR 0002 addendum

Dependencies: Increment A
Affected areas: `docs/decisions/0002-installer-trust-model.md`

1. Append an addendum in the form of the existing ones: trust model additions, mitigations to be
   covered by regression tests, accepted residuals. Cover the `harness/` tree and the approval
   record as untrusted input, the marker file as the one read outside the target, and the new write
   locations.
2. State that Claude Code loads the installed skills and agents automatically, so the digest-pinned
   approval is the control and the installer's static findings are advisory.

Completion: the addendum names each new boundary of the specification and states that nothing is
implemented yet.

### Increment C — Reviews

Dependencies: Increments A and B
Affected areas: `docs/specs/module-harness-files.md`, `docs/decisions/0002-installer-trust-model.md`

1. Run `ask-codex review-spec --spec docs/specs/module-harness-files.md` (the helper's bound
   applies; further rounds need the owner's `extend`); decide each blocker and major finding with
   `ask-codex decide --spec ... <ID> applied|rejected`, giving a concrete reason for a rejection.
2. Run an adversarial pass by delegating to the `security-reviewer` agent, briefed with the
   `security-review` skill's method, the specification, and the scratch cases from the assumptions.
   Its experiments run in a scratch directory outside the repository. Apply or reject each finding
   with a reason and rerun the cases a fix touches.
3. Record both reviews in a `## Review record` section at the end of the specification, since the
   helper's ledger under `.debug/` is untracked. For the Codex review: rounds used of the bound,
   model and effort, and every blocker and major finding with its ID, disposition and reason. For
   the security pass: the cases run and their observed results, each finding with severity,
   disposition and reason, the rerun results after any fix, and the cases not exercised.
4. Keep findings about other documents or about `claude_global_config` in a separate list in the
   report to the owner, not in the specification.

Completion: the specification's Review record lists every finding with a disposition, none is
undecided, and the unexercised cases are named.

### Increment D — Acceptance

Dependencies: Increment C and the owner's explicit acceptance of ADR 0004 and approval of the
specification
Affected areas: `docs/decisions/0004-harness-files-in-modules.md`, `docs/decisions/README.md`,
`docs/decisions/0001-module-and-slot-architecture.md`,
`docs/decisions/0003-external-module-mechanism.md`, `docs/specs/external-modules.md`,
`docs/specs/module-harness-files.md`, `docs/roadmaps/module-harness-files.md`

1. Do nothing in this increment until the owner says so in terms. Then set ADR 0004 to `Accepted`,
   its index row to match, and the specification to `Approved`.
2. Add the "Amended by 0004" notes the specification names to ADRs 0001 and 0003 and the
   external-modules specification, without changing their other text.
3. Update the roadmap's current state and promotion triggers for candidate 2.

Completion: the documents agree on status and on the amended clauses; `git diff --check` is clean.

## Verification

- `python3 -I -m unittest discover -s tests` (unchanged suite passes; no code changes).
- `git diff --check`, and a check that every relative link in the new and changed documents
  resolves.
- The `## Review record` in the specification (Increment C).

## Risks and sensitive actions

- The specification fixes a trust boundary that loads instruction files automatically; a gap here
  carries into every later plan. Mitigated by two independent reviews before approval.
- Increment D changes the status of accepted decisions. It waits for the owner's explicit
  acceptance and is never inferred from review results.
- No commit, push or installer change without the owner's request.

## Deferred work

- Installer implementation (roadmap candidates 2, 4 and 8), pilots (3, 7), the Graphify split (5),
  the `claude` module conversion (6), knowledge-base stores (9) and the global configuration cleanup
  (10).
- The ADR 0008 note in `claude_global_config`.

## Result

Completed in documents only; no installer, module, test or README behaviour text changed.

- Plan commit `7e17ac5`; Increments A to D in `90ff9cb`.
- Increment A: `docs/specs/module-harness-files.md` fixes every open point of ADR 0004 (harness
  table, `root/` convention, declarations, `harness.json`, manifest shape with `schema` 2 and
  `harness_files`, `module_format` 3 and its digest, approval files and verb table, collisions,
  removal, amended clauses, acceptance criteria). Status `Approved (2026-10-19)`.
- Increment B: ADR 0002 gained the "Addendum: harness files (ADR 0004)".
- Increment C: the specification's `## Review record` lists every finding with its disposition.
  Codex `review-spec` ran 3 of 3 rounds at high effort and did not converge (12 findings, all applied;
  the round 3 fixes were not shown again). Two adversarial `security-reviewer` passes ran in scratch
  against the unmodified installer: 0 Critical, 9 Medium and 12 Low in the first (applied or applied
  in part), and 0 Critical, 2 High, 8 Medium and 7 Low in the second (all applied; L6 in part). The
  text revised after the second pass was not reviewed again. Not exercised: Claude Code's own
  frontmatter parsing and name precedence (assumptions), a real home-directory marker, concurrent
  swaps, Windows aliases.
- Increment D, on the owner's explicit acceptance: ADR 0004 `Accepted` with three wording
  amendments (the approval is recorded beside the registry, a full `--update` skips a changed
  store, symlinks and size limits are refusals); "Amended by 0004" notes on ADRs 0001 and 0003 and
  on `docs/specs/external-modules.md`; the roadmap marks candidate 1 done and candidate 2's trigger met.

Verification: `python3 -I -m unittest discover -s tests` passes with 307 tests; `git diff --check`
is clean; every relative link in the new and changed documents resolves. One scratch run of the
installer confirmed that a `schema` 2 manifest makes `--update` exit 2 ("malformed") and write nothing.

Not done (deferred above): the installer implementation and every later roadmap candidate, and
anything in `claude_global_config`.

## Codex plan review

- Plan: docs/plans/next.md (key 2afd5ce4f5269eb0)
- Rounds used: 2 of 3
- Round 1: model gpt-5.6-luna, effort low, 1 finding(s) (1 blocker or major), 86948 input and 1495 output tokens
- Round 2: model gpt-5.6-luna, effort low, 0 finding(s) (0 blocker or major), 90128 input and 1172 output tokens
- Outcome: converged (no blocker or major finding in the last round)
- Decisions: 1 applied, 0 rejected
