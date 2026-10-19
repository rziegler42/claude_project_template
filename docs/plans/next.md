# External stores: harness files under registration review

Status: Complete
Created: 2026-10-19

## Goal

A registered standalone store may ship `template-module/harness/claude/` (skills, agents, commands). The
installer lists those files and their digest when the store is registered, installs them only after the owner
approves that exact digest (`--approve <digest>`), re-checks the digest on every verb that would install or
deliver them, and refuses a changed store until it is approved again. The installer runs no model, no program
from a store and no network call. This implements roadmap candidate 8, ADR 0004 decision 6 and the "External
stores" section of the approved specification (`docs/specs/module-harness-files.md`), which this plan does not
change.

## Scope

- `module_format` 3 for external stores: the declarations `helpers`, `workers` and `global_config`, and the
  `harness/<harness>/` tree. Formats 1 and 2 keep rejecting both; a `harness/` entry of any kind in a format 1
  or 2 store, and a symlinked `harness/` in any format, is refused. `MODULE_FORMATS` becomes `(1, 2, 3)`, so an
  installer from before this plan refuses a project whose manifest records a format 3 store (it already
  validates `module_format` against its own list).
- The store tree reader: the existing built-in checks (allowlist, depth, counts, sizes, UTF-8 without NUL,
  folded uniqueness, slot-marker refusal, reserved `base/` and `files/` paths) plus the store-only rules: ASCII
  path components `[A-Za-z0-9][A-Za-z0-9._-]*`, every file name ending `.md` apart from `harness.json`, the
  three unit shapes with `<n>` `[a-z0-9][a-z0-9-]{0,63}`, the exact frontmatter grammar with `name` equal to
  `<n>`, no C0 or C1 control character other than LF, no `root/CLAUDE.md`, no `remote-runner.toml`, and the
  placeholders `REPLACE_WITH_MODULE_NAME` and `REPLACE_WITH_MODULE_PATH`, with the project-name pattern check
  when a harness file holds a placeholder. The digest covers the bytes as stored, before substitution.
- The digest: SHA-256 framing over `module.json`, each `slots/<slot>.md` by slot name, then every file under
  `harness/` sorted by its UTF-8 relative path (prefix `harness/<harness>/`, `harness.json` included). One read
  feeds the digest and the install. A literal digest for a fixed fixture store is asserted in a test.
- `--register` review output (per-file size and SHA-256, each unit's `name`, `description` and `tools`,
  executable-bit files, advisory phrases from the fixed list, a flag for a unit name equal to one a built-in
  module ships, the digest, any refusal reason), every value ASCII-escaped and capped at 200 characters;
  re-running `--register` for an already registered store changes nothing and prints it again.
- The approvals file `<registry>.approvals` (schema 1, `{path, digest}` per name), `--approve DIGEST --name
  NAME`, `--unapprove NAME`, `--unregister` also removing the approval (approval first, registry second), the
  same hardened read and write as the registry, lazily loaded, and the option matrix (`--approve` and
  `--unapprove` accept only `--name`, `--registry`, `--dry-run` and `--global-config`; `--harness` is refused
  with them; a `--registry` named like an approvals file is refused).
- The verb table: `--new` and `--add` of a name not installed need an approval that matches the real path held
  by the registry and the current digest, including a `name=path` store (which must be registered); `--add` of an
  installed name reads nothing; a full `--update` skips a changed or unapproved store whole with a note; a named
  `--update` refuses before any write; `--remove` reads no store, registry or approvals file; a hostile approvals
  file blocks only the verbs that need it.
- Installing: external suppliers join `prepare_harness`, `plan_harness` and the collision rules (identical unit
  trees install once, differing trees fail one run or conflict across runs); the manifest records the format 3
  entry and the harness files with the store as supplier; `--add --harness` names an external module installed
  earlier without reading it (already implemented); a store whose digest changed but equals its approval is
  delivered by `--update`; declarations of a format 3 store are reported like a built-in's.
- Documentation: README ("Boundaries", "Writing a module", an external-stores harness section), a note in
  `docs/specs/external-modules.md` that its Acceptance items now point to the harness specification (the
  amendment text is already there), ADR 0004's Implementation note, and the roadmap.

## Non-goals

- `files/` and `requires` for external stores (still excluded), a harness other than `claude`, installing
  helpers, hooks or settings, and merging edits into installed harness files.
- Any model call, network access or execution of store content; human sign-off tooling beyond passing the
  digest; verifying that a file implements a declared role.
- Knowledge-base stores (candidate 9) and anything in `claude_global_config` (candidate 10).
- Changing built-in module behaviour, the base harness files, or the manifest of a project that records neither
  a harness nor a format 3 store (it stays byte-identical).

## Assumptions and constraints

- ADR 0004 (`Accepted`) and the specification (`Approved`) are the authority; where this plan is more concrete
  than they are, it names the choice and the owner confirms it by approving the plan.
- Verified in `install.py`: `read_external` reads `module.json` and `slots/*.md` only, with `MODULE_FORMATS =
  (1, 2)`; `prepare_harness` and `check_module_harness_dirs` skip external modules; `report_declarations`
  returns early for them; `validate_external_modules` checks `module_format` against `MODULE_FORMATS` and
  `digest` against `DIGEST_RE`; `load_registry` and `save_registry` implement the hardened registry file the
  approvals file will copy; `cmd_add` already tells the owner that earlier-installed external modules were not
  read on activation; `validate_harness_record` already accepts a supplier listed in `external_modules`.
- Choices to confirm in review: (1) the review output is printed by `--register` and by a repeat
  `--register`, with no separate `--review` verb, as the specification says; (2) a store that fails any store
  rule is refused at registration with the reason, and cannot be approved; (3) `harness/` in a format 1 or 2
  store is a refusal rather than silently ignored (so no store is half-installed by an installer that knows
  format 3); (4) one new module-level table of advisory phrases, kept short, documented as advisory.
- Compatibility accepted: a registry or approvals file written by this plan is read by older installers (the
  registry file is untouched); an older installer refuses a project that records a format 3 store.
- The installer stays standard-library Python with no dependency, secret or network access; the unit tests
  never execute store content, and a test checks that a store's checksum is identical before and after every
  command, including `--dry-run`.

Graphify: skipped — no graph exists in this checkout (`graph_missing`), and the affected code is enumerated in
one file: `install.py` (`MODULE_FORMATS`, `read_external`, `load_externals`, `load_registry`, `save_registry`,
`registered_entries`, `cmd_register`, `cmd_unregister`, `read_harness_tree`, `prepare_harness`,
`plan_harness`, `report_declarations`, `external_record`, `validate_external_modules`, `cmd_new`, `cmd_add`,
`cmd_update`, `load_update_externals`, `cmd_remove`, `build_parser`, `main`), `tests/test_install.py`,
`README.md`, `docs/specs/external-modules.md` and `docs/decisions/0004-harness-files-in-modules.md`.

## Completion criteria

A store with `template-module/harness/claude/skills/<n>/SKILL.md` registered with `--register` prints its file
listing and digest and installs nothing; `--with name` is refused until `--approve <digest> --name name`; after
approval `--with name --harness claude` installs the skill into `.claude/skills/<n>/`, recorded with the store
as supplier; editing any byte of the store (a harness file, a fragment, `module.json`) makes `--add`, `--new`
and a named `--update` refuse and a full `--update` skip it with a note until it is approved again; two stores
shipping the same skill install it once when identical and refuse or conflict when they differ; `--remove`
needs no approval; the acceptance criteria 9 to 13 of the specification (stores, approval, removal, activation,
read-only) pass as tests; the full suite passes and a project with no harness and no format 3 store is
byte-for-byte unchanged; an adversarial review finds no unresolved Critical or High finding.

## Increments

### Increment A — Format 3 stores and the tree reader

Dependencies: None
Affected areas: `install.py` (`MODULE_FORMATS`, `read_external`, `read_harness_tree`, the tree checks, new
store rules), `tests/test_install.py`

1. Write failing tests: formats 1 and 2 reject `helpers`, `workers`, `global_config` and any `harness/` entry; a
   symlinked `harness/` is refused in every format; a format 3 store with each hostile tree form is refused
   before any file is read (count, size, depth, control characters, non-ASCII or non-`.md` name, each
   unit-shape violation, each frontmatter violation, `root/CLAUDE.md`, an allowlist violation, a base/`files/`
   alias, a name equal to another unit's, a `NFC`/case alias); the digest literal for a fixed fixture, and that
   changing, adding or removing any harness file, a fragment or `module.json` changes it while placeholder
   substitution does not.
2. Implement format 3 in `read_external` with one read feeding digest and install; share the built-in checks
   with a `strict` store mode in `read_harness_tree`; return the harness tree and unit names on the module dict.
3. Verify that the read never executes or follows anything (checksum of the store before and after).

Completion: the new tests fail first and then pass; the built-in suite is unchanged.

### Increment B — Registration review

Dependencies: Increment A
Affected areas: `install.py` (`cmd_register`, a review printer, the advisory phrase list), `tests/test_install.py`

1. Write failing tests: `--register` of a format 3 store prints each file with size and SHA-256, unit `name`,
   `description` and `tools`, executables, advisory phrase findings, a flag for a unit named like a built-in
   unit, and the digest; a hostile file cannot inject ANSI or newlines into the output (escape and cap at 200
   characters); nothing is installed or approved; `--register` again for the same name and path prints the
   review and changes nothing; a refused store prints its reason.
2. Implement the review printer and wire it into `cmd_register` (including `--dry-run`).

Completion: the tests pass and the output matches the specification's list item for item.

### Increment C — The approvals file and its commands

Dependencies: Increment A
Affected areas: `install.py` (`approvals_path`, `load_approvals`, `save_approvals`, `cmd_approve`,
`cmd_unapprove`, `cmd_unregister`, `build_parser`, `main`), `tests/test_install.py`

1. Write failing tests: `--approve` with a wrong digest, an unregistered name, a changed store or a moved store
   is refused; a new approval replaces the old one; `--unapprove` removes only the approval; `--unregister`
   removes the approval first; two registries in one directory keep separate approvals; a `--registry` ending in
   `.approvals` is refused; every option outside `--name`, `--registry`, `--dry-run`, `--global-config`, and any
   target, is refused; `--dry-run` writes nothing; each hostile approvals file (symlinked directory or file,
   special file, over 1 MiB, malformed JSON, wrong schema, extra keys, invalid name, non-absolute or multi-line
   path, bad digest, extra entry keys) is refused before any write, never echoes its contents, and does not
   block `--remove`, `--list` or a store without `harness/`.
2. Implement by copying the registry's checks and write path; add the two options and their rows in `main`.

Completion: the tests pass; a mutation that skips the digest comparison, the path binding or a hostile-file
check fails a test.

### Increment D — The verb table

Dependencies: Increments A and C
Affected areas: `install.py` (`load_externals`, `registered_entries`, `cmd_new`, `cmd_add`, `cmd_update`,
`load_update_externals`, `cmd_remove`), `tests/test_install.py`

1. Write failing tests for every row: `--new` and `--add` without, with a stale, with a moved-path, with another
   name's and with the current approval (including `name=path` of an unregistered store and of a store
   registered elsewhere); `--add` of an installed name reads neither store, registry nor approvals; a full
   `--update` skips a changed store whole with a note and keeps its blocks, files and records; a named
   `--update` refuses before any write; a store changed in a fragment or `module.json` only is refused too;
   `--remove` works with a missing store, registry and approvals file; a store with no `harness/` needs no
   approval in any verb.
2. Implement the check in one function used by each verb, before any write.

Completion: the tests pass and no verb path installs unapproved store files.

### Increment E — Installing, collisions, declarations

Dependencies: Increment D
Affected areas: `install.py` (`prepare_harness`, `plan_harness`, `external_record`, `report_declarations`,
`cmd_add`, `cmd_update`, `cmd_remove`), `tests/test_install.py`

1. Write failing tests: an approved store's skill installs under `--harness claude` with substitution of the
   project and module placeholders and the supplier recorded; an unapproved or changed store installs none;
   two stores with the same skill (identical: once, co-supplied; different: the run fails when both are in it,
   a conflict and skip when later); a store unit named like a built-in module's unit is flagged at registration only, and at install the normal
   per-unit rules apply (the run fails only when two differing suppliers are both in it, otherwise the unit is
   reported as a conflict and skipped); a
   changed-but-approved digest is delivered by `--update` and the record updated; `--add --harness` names an
   earlier-installed store without reading it and a later approved `--update NAME` installs its files;
   `--remove` of the store deletes unedited files and keeps edited ones; declarations of a format 3 store are
   reported (helper present or missing, worker implemented or warned, global configuration).
2. Implement by including approved external trees in `prepare_harness` with the supplier name and letting
   `plan_harness` and removal work on supplier names without a built-in lookup.

Completion: the acceptance criteria 7, 11 and 12 of the specification pass for stores.

### Increment F — Documentation

Dependencies: Increment E
Affected areas: `README.md`, `docs/specs/external-modules.md`, `docs/decisions/0004-harness-files-in-modules.md`,
`docs/roadmaps/module-harness-files.md`

1. README: describe store-shipped harness files, `--register` review, `--approve`, `--unapprove`, the approvals
   file, what the digest covers, the verb table and what approval does not guarantee; correct "Boundaries".
2. Update the ADR 0004 Implementation note and the roadmap candidate 8 status (promotion text only; the
   completion mark waits for the archive).

Completion: the README commands run as written in a scratch project.

### Increment G — Verification and adversarial review

Dependencies: Increments A to F
Affected areas: `tests/test_install.py`; no new production code except fixes

1. Run the full suite, `git diff --check`, and an end-to-end scratch run: register a fixture store, read its
   review, approve, install into a new project, edit the store, observe each verb's refusal, approve again, and
   `--update`.
2. Mutation checks on a scratch copy: dropping the digest comparison, the path binding, the registry-name
   check, the `.md`-only rule, the control-character rule, the approval removal on `--unregister`, and reading
   the store on `--remove`, each fail a test.
3. Adversarial review with the `security-reviewer` agent on the diff (store path tricks, a store swapped
   between review and use, hostile registry and approvals files, an escape-sequence listing, frontmatter and
   alias bypasses, a collision with a built-in skill); fix each finding with a failing-first test; a second
   independent bypass attempt on the fixes. Complete the plan's Result.

Completion: no unresolved Critical or High finding, mutation survivors explained, suite green.

## Verification

- `python3 -I -m unittest discover -s tests` (671 tests today plus the new ones); each new test is seen to fail
  before its implementation; the store checksum test covers every command, including `--dry-run`.
- The scratch end-to-end run in Increment G, and a check that an installer from before this plan
  (`git archive 10bdbe1`) refuses the manifest of a project that records a format 3 store, and still reads the
  registry file this plan writes.
- `git diff --check`.

## Risks and sensitive actions

- This is the trust boundary of the template: files from a store become instructions a harness loads
  automatically. The approval is the control; the digest re-check, path binding, fail-closed reads and the
  refusal rules carry it, and Increment G reviews it adversarially before the plan is called complete.
- The approvals file is new state outside the project (beside the registry). It is written only by
  `--approve`, `--unapprove` and `--unregister`, never by project commands.
- A reviewed phrase list is bypassable; the output says so and the owner reads the files. The plan makes no
  claim that approval makes a store safe.
- No commit, push, dependency, secret, network call or destructive action without the owner's request.

## Deferred work

- Knowledge-base stores and the global configuration cleanup (roadmap candidates 9 and 10).
- A second harness, `files/` for stores, signature or sign-off tooling.

## Result

Increments A to G are implemented and verified; nothing is committed beyond the approved plan.

- **Format 3 stores (A):** `MODULE_FORMATS = (1, 2, 3)`; declarations and `harness/claude/` for format 3 only; a
  `harness/` entry in format 1 or 2, a symlinked `harness/`, or an unknown harness directory is refused. The strict
  store tree rules (ASCII components, `.md` files, unit shapes, exact frontmatter grammar with a single-line
  `name`, no control characters or Unicode line separators, no `root/`, no `remote-runner.toml`) run before the
  digest. The digest frames `module.json`, the slots and every harness file by UTF-8 path; a literal for a fixed
  fixture is asserted and was computed outside `install.py`.
- **Review (B):** `--register` (also a repeat and `--dry-run`) prints each file with size and SHA-256, each unit's
  name, description and tools, findings (executable bit, advisory phrases, a line starting with `!`, a unit name
  also shipped by a built-in module, frontmatter keys other than `name`, `description` and `tools`), the digest and
  the `--approve` line; every value is ASCII-escaped and capped.
- **Approvals (C):** `<registry>.approvals` with the registry's hardened read and write; `--approve DIGEST --name`,
  `--unapprove`, `--unregister` removing the approval first; the option matrix; a `--registry` ending in
  `.approvals` is refused after path normalisation.
- **Verb table (D) and install (E):** `require_approvals` gates `--new`, `--add` and a named `--update` before any
  write; a full `--update` skips a changed or unapproved store with a note; `--remove` and `--add` of an installed
  name read no store, registry or approvals file; approved store trees install through `prepare_harness` with the
  supplier recorded, collision rules unchanged, placeholders filled in one pass, a changed-but-approved digest
  delivered by `--update`, and declarations reported.
- **Docs (F):** README "Harness files in a store", ADR 0004 Verification, roadmap candidate 8.
- **Verification (G):** 740 tests pass (`python3 -I -m unittest discover -s tests`), `git diff --check` clean. A
  scratch run registered, approved, installed, edited the store and saw each refusal. An installer from
  `10bdbe1` refuses a format 3 store and a project that records one (`malformed external_modules entry`) and
  leaves the project unchanged. Fifteen mutations on scratch copies: fourteen killed; the survivor (registry
  binding of an approval) got a new test and is now killed. Adversarial review by `security-reviewer`: no
  Critical, High or Medium finding; one Low (a trailing `/` or `/.` bypassed the `.approvals` registry guard) and
  Info items fixed with failing-first tests (name continuation lines, U+2028 and U+2029, flagged extra frontmatter
  keys, a misleading activation note).
- **Choices and interpretations:** the module path placeholder accepts `[A-Za-z0-9._/ -]` (the spec's
  `[A-Za-z0-9._ -]` pattern has no `/`, which a store path needs); a hostile project name is refused only when a
  harness file uses a project placeholder; `--approve` refuses a store with no `harness/` tree.
- **Unchecked or accepted:** `--merge` with stores; a case-sensitive filesystem for the case-alias test (skipped
  here); whether a real harness reads a name continuation or `hooks:` in frontmatter differently from the
  installer's grammar (only the owner's reading of the files guards that); a concurrent local attacker swapping a
  store or the approvals file (accepted residual in the specification).
- **Not done here:** knowledge-base stores and the global configuration cleanup (candidates 9 and 10).
- **Next action:** commit on request, then archive as plan 0024; candidate 9 waits for the knowledge-base skills
  roadmap in `claude_knowledge_base` and `claude_global_config`.
