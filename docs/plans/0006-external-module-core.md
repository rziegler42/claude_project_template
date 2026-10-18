# 0006: External module core

Status: Completed
Created: 2026-10-18
Completed: 2026-10-18

## Goal

`install.py` accepts `name=path` entries in `--with` (new project) and `--add`
(existing project), verifies the named standalone project read-only, and installs
its slot fragments beside the built-in modules, recording it in
`.template-manifest`. This is candidate 1 of
[roadmap external-modules](../roadmaps/external-modules.md), implementing the
approved [external-modules spec](../specs/external-modules.md) for typed paths.

## Scope

- The descriptor (`template-module/module.json`, `template-module/slots/*.md`)
  parsing, validation, and digest.
- `name=path` parsing in `--with` and `--add`, with `~` expansion.
- Read-only verification of a store, name rules, and the collision rules that
  apply without a registry.
- Fragment substitution (`REPLACE_WITH_MODULE_NAME`, `REPLACE_WITH_MODULE_PATH`),
  installation beside built-in blocks, hints, and dry run.
- The optional `external_modules` manifest object, its validation, and `--add`
  behavior for recorded and new external modules.
- Tests in `tests/test_install.py`, and the `--with`/`--add` help text.

## Non-goals

- The registry, `--register`, `--unregister`, `--list` changes, and bare registered
  names (candidate 2). A bare name that is not built-in stays "unknown module".
- ADR 0002 addendum, the mechanism ADR, and the adversarial review (candidate 3).
- Any change in `claude_knowledge_base` (candidate 4).
- README prose for registering and writing an external module (candidate 5); this
  plan changes only the argparse help text.
- Files from a store, `requires`, refresh on drift, a digest check.

## Assumptions and constraints

- Spec rules are copied, not re-decided; where this plan says "the spec's rule" the
  spec governs. Spec sections: Descriptor, Names, Syntax, Verification,
  Substitution, Manifest, Acceptance criteria 1-4, 7, 8.
- `install.py` stays one stdlib-only file, Python 3.9+, and external code never
  runs: no subprocess touches a store.
- Implementation choice (the spec leaves it open): an external module is a
  `load_modules`-shaped dict with extra keys `external: True`, `digest`,
  `module_format`, `requires: []`, `order: EXTERNAL_ORDER` (1000000, so it sorts
  after every built-in then by name), `harness: False`, merged into the `modules`
  mapping passed to `resolve` and `assemble`; `assemble` skips the `files/` walk
  for entries with `external` (a store's own `files/` directory is never read).
- Built-in behavior and `--list` output are unchanged. The manifest key `modules`
  keeps listing built-ins only; `NAME_RE` is untouched, and external names use a
  new `EXT_NAME_RE` (`^[a-z0-9][a-z0-9_-]*$`).
- Fixture digest (spec acceptance 7), pinned as a literal in tests: a store whose
  `module.json` is the bytes `{"module_format": 1, "description": "Fixture store"}\n`
  and whose only fragment `slots/agents-guidance.md` is
  `## Fixture guidance\n\nRead REPLACE_WITH_MODULE_PATH/router.md.\n` has digest
  `cf9d227a545469fbe589ff4e65d3a4b4878bd32bd1a3f14341acee82fe7da26d`
  (computed independently of `install.py` with the spec's algorithm).

## Discovery and impact evidence

Graphify: skipped — the affected paths are fully enumerated: `install.py` and
`tests/test_install.py` (the README is untouched). Verified against current source:
`load_modules`, `resolve`, `assemble`, `apply_slots`, `emit_hints`, `parse_with`,
`cmd_new`, `cmd_add`, `load_manifest`, `manifest_bytes`, `check_target`,
`read_regular`, and `ModuleHygieneTest`. `apply_slots` already wraps blocks with
`BEGIN/END module:<name> slot:<slot>`, so two external modules in one slot stay
distinct without a change to it.

## Completion criteria

- `python3 -I -m unittest discover -s tests` passes with the new tests, and
  `git diff --check` is clean.
- Spec acceptance criteria 1-4, 7 and 8 hold for typed paths (criteria 5 and 6 are
  candidate 2).
- A checksum of a fixture store tree is identical before and after a run, including
  `--dry-run`; a hostile store runs no program.
- Output for runs that name only built-in modules is byte-identical to the previous
  commit's installer.

## Increments

### Increment A — descriptor loading and verification

Dependencies: None
Affected areas: `install.py`, `tests/test_install.py`

Interfaces produced (all in `install.py`):

- `EXT_NAME_RE`, `EXTERNAL_ORDER = 1000000`, `MODULE_FORMATS = (1,)`,
  `DESCRIPTOR_DIR = "template-module"`.
- `parse_entries(parts: list) -> list` of `(name, value_or_None)`: each part split on
  its first `=`; an empty name or an empty value after `=` is an `InstallError`.
- `descriptor_digest(files: list) -> str`: `files` is `[(relpath, bytes)]` already in
  the spec's order; returns the spec's SHA-256 hex.
- `load_external(name: str, value: str, target: str, builtin: set) -> dict`: expands
  `~`, resolves relative to the cwd, verifies, and returns the module dict described
  above plus `slots` (fragment text with `REPLACE_WITH_MODULE_NAME` and
  `REPLACE_WITH_MODULE_PATH` substituted), `hint`, `description`, `path` (the real
  store path), and `target`-relative path text per the spec's `../<store>` rule.

Steps:

1. Tests first, using a helper `make_store(parent, slots, module=None)` that writes
   a valid descriptor and returns the path:
   - `test_parse_entries`: `["claude", "kb=~/x", "a=b=c"]` →
     `[("claude", None), ("kb", "~/x"), ("a", "b=c")]`; `"=x"`, `"kb="` raise.
   - `test_digest_matches_pinned_literal`: the fixture store above gives the pinned
     digest; changing one byte of a fragment changes it.
   - `test_load_external_valid`: returns description, hint, fragments with both
     placeholders substituted, and `../<store>` when the store and the target share
     a parent, the absolute path when they do not.
   - Refusals (one test each, asserting nothing is written and no content echoed):
     missing store; store symlink; store equal to or inside the template; equal to or
     inside the target; no `template-module/`; `module.json` or a slot that is a
     symlink or FIFO; an unexpected entry in `slots/`; a bad slot name; unknown or
     mistyped `module.json` key; `module_format` 2; `description` empty, over 200
     characters, or multi-line; `hint` over 200; a fragment that is non-UTF-8, has a
     NUL, exceeds 64 KiB, or contains `@module-slot:`, `BEGIN module:`, or
     `END module:` anywhere in a line; 17 fragments; `name` equal to a built-in;
     `name` failing `EXT_NAME_RE`; a `.git` component in the real store path.
2. Implement the four interfaces with the existing `read_regular` for every read and
   `os.lstat` for directory checks; list `slots/` with `os.listdir` and refuse
   anything not a regular `*.md`. Compare template/target containment by real path
   and `os.path.samefile`, as `check_target` does.
3. Run the new tests, then the whole suite.

Completion: new tests pass and fail before the code; whole suite passes.

### Increment B — install into a new project

Dependencies: Increment A
Affected areas: `install.py`, `tests/test_install.py`

Interfaces consumed: `parse_entries`, `load_external`. Produced: `assemble(names,
modules)` unchanged in signature but skips the `files/` walk when
`modules[name].get("external")`; `manifest_bytes(module_names, commit, dirty,
externals=None)` where `externals` maps name → `{"module_format", "digest"}`.

Steps:

1. Tests first (use `run([...])` and a scratch project directory):
   - `test_with_name_path_installs_fragment`: `--with claude,kb=<store>` writes the
     fragment inside `BEGIN module:kb slot:agents-guidance` / `END` lines in
     `AGENTS.md`, after any built-in block of the same slot, with the path text per
     the spec, and prints the store's hint under "Next steps".
   - `test_two_external_modules_make_two_blocks`: `a=<s1>,b=<s2>` in one slot give
     two distinct blocks.
   - `test_manifest_records_external`: `external_modules` holds the name,
     `module_format` 1, and the digest; `modules` lists only built-ins; no path
     appears anywhere in the manifest.
   - `test_dry_run_with_external_writes_nothing`: lists would-write paths, prints
     hints, and leaves the store's tree checksum unchanged.
   - Refusals, each writing nothing: a duplicate name in one run; the same real path
     under two names; a fragment whose slot has no marker in the project; a bare
     unknown name (still "unknown module").
   - `test_store_files_dir_is_never_copied`: a store with a top-level `files/` and
     `template-module/files/` yields none of those files in the project.
   - `test_builtin_only_output_unchanged`: a built-in-only install equals the tree
     from a fixed expected set already covered by existing tests (the old tests
     pass unmodified).
   - `test_hostile_store_runs_nothing`: a store `.git` with a configured
     `core.fsmonitor` helper and `GIT_*` in the environment cause no program to run.
2. Implement in `cmd_new`: split the `--with` parts with `parse_entries`; entries
   with a value become externals through `load_external` (after `check_target`, so
   the target path is known), merged into `modules` with duplicate-name and
   duplicate-real-path refusals; entries without a value go through `resolve` as
   today; `emit_hints` and the "Modules:" line include externals; the manifest
   gains `external_modules` only when non-empty.
3. Run the whole suite.

Completion: new tests pass; every pre-existing test passes unmodified.

### Increment C — `--add` and manifest validation

Dependencies: Increment B
Affected areas: `install.py`, `tests/test_install.py`

Interfaces consumed: all of the above. Produced: `load_manifest` also validates and
returns `external_modules` (default `{}`).

Steps:

1. Tests first:
   - `test_add_name_path_to_existing_project`: adds the block and the manifest
     entry, leaves text outside blocks unchanged, and refuses (writing nothing) a
     fragment whose slot marker is missing from an older project.
   - `test_add_recorded_external_is_already_installed`: `--add kb` (bare) and
     `--add kb=<path>` on a project recording `kb` report "already installed", do
     not read the store (a missing path is not an error), and write nothing.
   - `test_add_second_external_keeps_first_entry`.
   - `test_add_builtin_after_external_works`: the recorded external is not
     re-resolved.
   - Manifest validation, each refused: `external_modules` not an object; a name
     failing `EXT_NAME_RE` or equal to a built-in; an unknown `module_format`; a
     digest that is not 64 lowercase hex digits. A manifest without the key stays
     valid.
   - `--skip-unsafe-entries` semantics are unchanged with an external block.
2. Implement in `cmd_add`: build `modules` plus any new external entries; the
   already-installed set is `manifest["modules"]` plus the keys of
   `external_modules`; only new externals are loaded; `wanted` for `resolve` is the
   built-in part, with new externals appended in name order; write `modules` as the
   built-in names only and merge new external entries into `external_modules`
   without rewriting existing ones.
3. Run the whole suite.

Completion: new tests pass; every pre-existing test passes unmodified.

### Increment D — help text and final checks

Dependencies: Increment C
Affected areas: `install.py` (argparse help and module docstring), `tests/test_install.py`

1. Update the `--with` and `--add` help text and the usage docstring for
   `name=path`; add `test_help_mentions_name_path` only if an existing help test
   pattern makes it cheap.
2. Run the full suite, `git diff --check`, and the scratch installs listed under
   Verification.

Completion: all completion criteria met.

## Verification

- `python3 -I -m unittest discover -s tests`.
- Scratch installs under the session scratchpad: `--with claude,kb=<fixture store>`,
  two stores in one slot, `--dry-run` with a store, a later
  `--add scratch=<store>`, and a `--with graphify,cad,plan-review` diff against the
  previous commit's installer showing no change.
- A tree checksum of the fixture store before and after each scratch run.
- `git diff --check`.

## Risks and sensitive actions

- The installer now reads a directory outside the target and template and places its
  text in `AGENTS.md`; the read path must stay on `read_regular` and `lstat`, and no
  subprocess may touch the store. The adversarial review is candidate 3, so this
  plan's tests cover the listed hostile cases only, and the feature should not be
  announced in the README before that review.
- Widening name rules (underscores) must not change built-in validation; the
  existing hygiene test guards this.
- Commits only on explicit approval; nothing pushed without it.

## Deferred work

- Registry and bare names (candidate 2); trust-model review and ADRs (candidate 3);
  store-side contract (candidate 4); end-to-end check and README (candidate 5).
- Refresh on drift using the recorded digest.

## Review Focus

Inputs the spec implies but no listed test exercises are covered by tests named in
the increments above where noted:

- An empty name or empty value (`=x`, `kb=`): refused (Increment A).
- A path containing `=`: the first `=` splits (Increment A).
- The same name given twice in one run: refused (Increment B).
- A store path under a symlinked ancestor such as `/tmp` on macOS: accepted
  (Increment A refusal tests include the accepting counterpart).
- A fragment lacking a trailing newline or using CRLF: inserted without breaking the
  block's `END` line (Increment B; add a case to `test_with_name_path_installs_fragment`).

## Result

All completion criteria met. Implemented in `4076a80` (`install.py`,
`tests/test_install.py`); the plan was approved in `dd978ae`.

- Increment A: `parse_entries`, `descriptor_digest`, `is_within`,
  `load_external` (wrapping `read_external`), `load_externals`, and the
  descriptor, name, and containment rules.
- Increment B: `name=path` in `--with`; external fragments install after the
  built-in blocks of a slot; hints, dry run, and the `external_modules`
  manifest entry (format and digest, no path); `assemble` skips a store's
  files.
- Increment C: `--add` with `name=path`; a recorded external module is never
  re-read; `external_modules` validation in `load_manifest`.
- Increment D: usage text and `--with`/`--add` help.

Verification: `python3 -I -W error::ResourceWarning -m unittest discover -s
tests` passed (122 tests, up from 85; the new tests failed before the code);
`git diff --check` clean. A scratch install of `graphify,cad,plan-review,claude`
differed from the previous commit's installer only in the project name and the
template commit. A scratch install with a descriptor store left every store file
unchanged (checksums) and a `--dry-run` wrote nothing. The pinned fixture digests
were computed independently of `install.py`.

Independent review: a read-only reviewer found no critical or high issues.
Fixed with tests that failed first: containment by real path and identity in
both directions (symlinked ancestor, a store containing the template or target,
case variant); a fragment-symlink test that passed for the wrong reason; an
untested slot-name digest ordering; the format message now names both versions;
a trailing newline accepted by the name and digest patterns; a `null` hint
accepted; an unreadable store directory raised a traceback; and the hostile-store
test now spies on subprocess calls and checks every file in the store.

Rulings: a comma in a `--with` path cannot be detected (commas separate
entries), so a directory named `a,b` fails in `--with` and works in `--add`, as
a test pins; external names use `EXT_NAME_RE` and the built-in name rule is
unchanged.

Deferred minors: slot names use the built-in rule, slightly stricter than the
spec; the plan's `test_builtin_only_output_unchanged` is covered by the
unmodified existing tests and a scratch diff rather than a separate test.

Not done (roadmap candidates 2 to 5): the registry and bare registered names,
the adversarial trust-model review with the ADR 0002 addendum and mechanism
ADR, the store-side contract in `claude_knowledge_base`, and README prose. The
README does not mention `name=path` yet.

## Codex plan review

- Plan: docs/plans/next.md (key f82302b7335cd421)
- Rounds used: 1 of 3
- Round 1: model gpt-5.6-luna, effort low, 0 finding(s) (0 blocker or major), 127014 input and 1478 output tokens
- Outcome: converged (no blocker or major finding in the last round)
- Decisions: 0 applied, 0 rejected
