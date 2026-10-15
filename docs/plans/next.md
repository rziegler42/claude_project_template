# Next plan

Status: In Progress
Created: 2026-10-15

## Goal

A project created with `install.py --with codex` carries concrete, Codex-bound
guidance for plan review (the helper, the skill, its limits, and where its
state and summary go) on top of the neutral `plan-review` module, and the
module has room for later `ask-codex` uses.

## Scope

1. A new `codex` module, `harness: true`, `requires: ["plan-review"]`, with an
   `agents-guidance` fragment, a `plan-review` slot fragment mapping the
   helper's archive summary onto the Second opinion receipt, and a hint.
2. Tests, README module table and wording for tool-bound modules.
3. Follow-up in `claude_global_config`, under its own approval: its README
   pointer names `--with codex` instead of `--with plan-review`.

## Non-goals

- Changing the neutral `plan-review` module or the base slot markers.
- Any change to `ask-codex`, the `second-opinion` skill, or other global
  configuration behavior; the module only describes them.
- Other review kinds (diff or code review): the module is named for the tool
  so they can be added later, but none is designed here.
- Automatic triggers: review stays on the owner's request only.
- A second vendor; that would be another module requiring `plan-review`.

## Assumptions and constraints

- `harness: true` is the existing mechanism that lets a module name
  Claude-owned helpers and skills; the neutrality test exempts such modules,
  and `plan-review` and every other non-harness module must still name no
  helper, skill, or vendor.
- The module is guidance only. It ships no executable, configuration, or
  settings; the helper comes from `claude_global_config` and the guidance says
  to use it when installed.
- Facts to state, verified against `claude_global_config` (`skills/
  second-opinion/SKILL.md`, ADR 0001, README): requests such as "have Codex
  review the plan" or `/second-opinion`; `ask-codex review-plan`; default
  bound 3 rounds, never more than 5 per request; Claude is the only writer;
  each blocker and major finding is applied or rejected with a recorded
  reason; `extend`, `reset`, `archive`, and `prune` are owner-only; review
  state lives in untracked `.debug/<date>-plan-review/`; everything Codex
  reads is sent to OpenAI.
- Module name `codex`, `order` 16 (after `plan-review`, before `formal`).
- The spike run on 2026-10-15 showed the archive summary maps onto the
  receipt fields except its heading names the vendor and it lists counts, not
  text, for applied findings; the fragment says how to adapt it.

## Discovery and impact evidence

Graphify: skipped — the repository has about 50 tracked files and the
affected paths are fully enumerated: `modules/codex/`, `tests/test_install.py`,
`README.md`. Verified against current source: the `cad` / `cad-freecad`
`requires` pattern, the `harness` flag and neutrality test, the
`plan-review` module and slots, and the helper and skill text listed above.

## Completion criteria

- `python3 -I -m unittest discover -s tests` passes with the new tests;
  `git diff --check` is clean.
- `install.py <dir> --with codex` installs `plan-review` as well, prints both
  hints, and puts both fragments in `AGENTS.md` and the plan.
- Output without `codex` is unchanged.
- Only harness-marked modules name `ask-codex`, `second-opinion`, or
  `codex`.

## Increments

### Increment A — the `codex` module

Dependencies: None
Affected areas: `modules/codex/{module.json,slots/*.md}`,
`tests/test_install.py`, `README.md`

1. Tests first: `--with codex` pulls `plan-review`; the `codex` guidance and
   receipt-mapping fragment appear only with it; `--add codex` on a project
   that already has `plan-review` works and matches a fresh install; `--list`
   shows `codex (harness; requires plan-review)`; the neutrality test still
   passes for all non-harness modules; every fragment has a marker; the hint
   prints once.
2. Add the module.
   - `agents-guidance`: how to request a review, the helper and skill, the
     bound, who writes, how findings are handled, the owner-only commands,
     where state lives, the privacy note, and what to record in the plan.
   - `plan-review` slot: a comment mapping each archive-summary line to a
     receipt field and saying to adapt rather than paste its heading.
3. README: module table row, and reword the neutrality note so tool-bound
   modules are described as harness-marked.

Completion: tests pass; scratch install shows both modules' text.

### Increment B — pointer in `claude_global_config`

Dependencies: Increment A pushed
Affected areas: `claude_global_config/README.md` (separate approval there)

1. Change the template-pointer paragraph to name `--with codex`
   (which requires `plan-review`).

Completion: README reads correctly; no installed file changes.

## Verification

- `python3 -I -m unittest discover -s tests`.
- Scratch installs under the session scratchpad: `--with codex`,
  `--with plan-review` (unchanged), `--with codex,graphify`, and a later
  `--add codex`.
- A diff of the `--with graphify,cad,plan-review` output against the previous
  commit's installer.
- `git diff --check`.

## Risks and sensitive actions

- The generated text states privacy and approval policy; it must not weaken
  the neutral `plan-review` policy, and must say that reviewed content leaves
  the machine.
- The guidance names owner-only commands; it must not suggest running them.
- Commits only on explicit approval; nothing pushed without it; the
  global-config change has its own approval.

## Deferred work

- Other `ask-codex` kinds (diff review) and their guidance.
- A second vendor module.
- `--add` fragment insertion for projects created before a base marker
  existed; the Ghidra module; adopting `cp -R` projects.

## Result

<!-- Complete this only after verification. Archive the plan according to
base/docs/plans/README.md, then reset this file to the empty template. -->
