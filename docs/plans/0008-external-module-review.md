# 0008: External module trust-model review

Status: Completed
Created: 2026-10-18
Completed: 2026-10-18

## Goal

The external-module read boundary (typed store paths, the registry, the
`external_modules` manifest entry, and descriptor text that ends up in a
project) has had an independent adversarial review. Every reachable finding is
fixed with a regression test that failed first, and the mechanism and its trust
model are recorded in an ADR 0002 addendum and a new ADR. This is candidate 3
of [roadmap external-modules](../roadmaps/external-modules.md), covering the
work of plans [0006](0006-external-module-core.md) and
[0007](0007-registry.md) against the approved
[external-modules spec](../specs/external-modules.md).

## Scope

- Review of the external-module and registry code paths in `install.py`:
  `parse_entries`, `descriptor_digest`, `real_directory`, `is_within`,
  `load_external` / `read_external` / `load_externals`, `registry_path`,
  `load_registry`, `save_registry`, `registered_entries`, `cmd_register`,
  `cmd_unregister`, the external parts of `cmd_list`, `cmd_new`, `cmd_add`,
  `assemble`, `validate_external_modules`, `external_record`, `manifest_bytes`,
  and `load_manifest`.
- Fixes for confirmed findings, tests first, in `install.py` and
  `tests/test_install.py`.
- An addendum to ADR 0002 and a new ADR for the external-module mechanism, plus
  the `docs/decisions/README.md` index.

## Non-goals

- Built-in-module paths and anything plan 0003 already settled, except where an
  external path reuses it incorrectly.
- New features, new options, or any change to the descriptor, registry, or
  manifest format. A finding that can only be fixed by a format change is
  recorded as deferred work for the owner to decide.
- The store-side contract in `claude_knowledge_base` (candidate 4) and README
  prose (candidate 5).
- Concurrent-writer protection for the registry (accepted residual in the spec)
  and closing the parent-directory swap race (accepted residual in ADR 0002),
  unless the review shows the external path widens either.

## Assumptions and constraints

- Trust model to confirm in Increment A, from the spec's trust section: the
  owner's command line, the template checkout, and a store the owner names or
  registers are trusted as to intent only. A store's bytes are untrusted data:
  they must be read-only, bounded, validated, and never executed. The registry
  file is untrusted data shaped by the owner's commands. A project under
  `--add`, including its `.template-manifest`, stays untrusted as in ADR 0002.
  The owner deliberately installing a hostile store's fragment text into
  `AGENTS.md` is out of scope; that text is guidance, not code, and the spec
  says so.
- Hypotheses to test, not conclusions (from reading the code and spec):
  1. A store whose final component, `template-module/`, `slots/`, `module.json`,
     or a fragment is a symlink, FIFO, device, or oversized file is refused, and
     a swap between verification and read cannot make the recorded digest differ
     from the bytes installed (one read feeds both).
  2. A store that contains, is contained by, or is the template or the target
     (including through symlinked ancestors and case or Unicode aliases on this
     filesystem) is refused in both directions.
  3. A store with a `.git` directory, hooks, fsmonitor config, or `.gitattributes`
     is never touched by `git`, because no subprocess runs in or on a store.
  4. Fragment text cannot forge or close a slot block: marker lines
     (`@module-slot:`, `BEGIN module:`, `END module:`) are refused anywhere in a
     fragment, including with leading text, CRLF, lone CR, NEL, or Unicode line
     separators; placeholders substitute once and a substituted name or path
     cannot reintroduce a marker or another placeholder.
  5. A hostile `module.json` (duplicate keys, non-string values, huge ints,
     deep nesting, `NaN`, extra keys, a null `hint`, control or bidirectional
     characters in `description`, `hint`, or slot names) either validates or is
     refused with a clean message, never a traceback.
  6. A hostile external name (case-insensitive collision with a built-in or
     another external, Windows-reserved or `.`-leading names, long names) cannot
     shadow a built-in, overwrite another store's block, or reach a path
     component unsanitised.
  7. A tampered registry (symlinked file or directory, FIFO, huge or deeply
     nested JSON, duplicate keys, a path of `/`, `$HOME`, the template, or the
     project, a path with `=`, comma, newline, or NUL, a name that is built-in)
     can only point at a directory that passes the same checks as a typed path,
     and cannot make `--register` or `--unregister` write outside the registry
     directory.
  8. A forged `external_modules` entry in a project's `.template-manifest`
     (built-in name, bad name, bad digest, extra keys, a recorded name with no
     fragments in the files) is refused or harmless under `--add`.
  9. Error messages and `--list` output never print descriptor, fragment, or
     registry content beyond the name and a fixed reason, so terminal control
     sequences in a hostile store cannot reach the owner's terminal.
  10. `--dry-run` and failed runs read no more and write no more than a real run
      and leave the project, store, and registry unchanged.
- `install.py` stays one stdlib-only file, Python 3.9+. The review uses the
  `security-reviewer` agent, which works only in a scratch directory and does not
  touch this tree; a second pass tries to bypass the fixes of the first, as plan
  0003 did.
- Findings that change documented behaviour are reported to the owner before the
  fix, not decided silently. A finding is rated by the effect on a person using
  the installer, not by whether the spec names the input.
- Tests never touch the real `~/.config`; they use `--registry` or a temporary
  `XDG_CONFIG_HOME`.

## Discovery and impact evidence

Graphify: skipped — the affected paths are fully enumerated: `install.py`,
`tests/test_install.py`, and three documents (ADR 0002, the new ADR, the ADR
index). Verified against current source (HEAD `e811b6d`): the functions listed
under Scope exist in `install.py`; external modules reach the filesystem only
through `read_regular`, `real_directory`, and the `assemble` / `write_tree`
path already covered by ADR 0002; no `git` call receives a store path. The
plan-0003 review produced the pattern (hypotheses, scratch experiments, a second
bypass pass, tests that fail first) reused here.

## Completion criteria

- Each hypothesis above is recorded in the new ADR as confirmed (with the fix and
  its test), refuted (with the experiment), or an accepted residual.
- Every confirmed finding has a regression test that fails before its fix and
  passes after; the whole suite passes with
  `python3 -I -W error::ResourceWarning -m unittest discover -s tests`.
- A second reviewer pass, told the first round's fixes, finds nothing reachable
  that is unfixed or unrecorded.
- ADR 0002 has an addendum that extends the trust model to stores and the
  registry; the new ADR records the mechanism (descriptor, names, digest,
  registry, manifest record, read-only verification) and its alternatives; the
  ADR index lists it.
- Built-in-only behaviour is unchanged: a scratch install of
  `graphify,cad,plan-review,claude` differs from `e811b6d`'s installer only in
  project name, runner id, and template commit.
- `git diff --check` is clean; no store fixture is modified by any command, by
  checksum with dotfiles included.

## Increments

### Increment A — adversarial review

Dependencies: None
Affected areas: none in the tree (scratch directory only); findings recorded in
the plan's Result and carried into the ADR

1. Dispatch the read-only `security-reviewer` with the hypotheses, the spec's
   trust section, ADR 0002, and the function list, working only under the
   session scratchpad. It must run real experiments (hostile stores, registries,
   manifests, fake `git`) and report each as confirmed, refuted, or a new
   finding, with the command used.
2. Rate each confirmed finding by effect. Report any that would change
   documented behaviour or need a format change to the owner before fixing.

Completion: every hypothesis has a recorded verdict; the confirmed list is
agreed with the owner where it changes behaviour.

### Increment B — fixes, tests first

Dependencies: Increment A
Affected areas: `install.py`, `tests/test_install.py`

1. For each confirmed finding, write the regression test (in `ExternalModuleTest`
   or `RegistryTest`), run it, and watch it fail for the stated reason.
2. Make the smallest fix; run the new test, then the whole suite.
3. Record each fix and its test name in the Result.

Completion: every confirmed finding has a failing-then-passing test; suite green.
If Increment A confirms nothing, this increment is a no-op and is recorded as
such.

### Increment C — second pass

Dependencies: Increment B
Affected areas: none in the tree

1. Dispatch a second `security-reviewer`, told the first round's findings and
   fixes, to bypass them and to probe what the first round did not.
2. Fix anything reachable by the Increment B method.

Completion: no reachable unfixed finding; residuals listed for the ADR.

### Increment D — ADRs

Dependencies: Increment C
Affected areas: `docs/decisions/0002-installer-trust-model.md`,
`docs/decisions/0003-external-module-mechanism.md`, `docs/decisions/README.md`

1. Append an "Addendum (2026-10-18): standalone stores and the registry" to ADR
   0002: the extended trust model, the read-only store checks, the registry
   rules, the new accepted residuals, and the new test count. Do not rewrite the
   original decision text.
2. Write ADR 0003 in the `base/docs/decisions/README.md` format: context,
   decision (descriptor, names, digest, registry, manifest record, fragments
   only), alternatives considered (a `--add-to` style generator coupling,
   per-project copies of text, `files/` from stores, a remote registry,
   reference-only modules), consequences, residuals, verification.
3. Add the ADR 0003 row to the index; status `Accepted` only after the owner
   accepts it.

Completion: the documents cite real test names and the verdict for each
hypothesis; links resolve.

### Increment E — final checks

Dependencies: Increment D
Affected areas: none beyond the above

1. Run the full suite with `-W error::ResourceWarning`, `git diff --check`, and
   the built-in-only scratch comparison against `e811b6d`.
2. Run the store-checksum check on a fixture store across register, list,
   install, and unregister.
3. Independent read-only `workflow-reviewer` pass on the diff.

Completion: all completion criteria met.

## Verification

- `python3 -I -W error::ResourceWarning -m unittest discover -s tests`.
- Scratch runs under the session scratchpad with `--registry` inside it:
  register, list, `--with`, `--add`, unregister; the built-in-only install
  compared with `e811b6d`.
- Store tree checksums (dotfiles included) before and after each command.
- `git diff --check`.

## Risks and sensitive actions

- The review is the security-sensitive step: hostile stores, symlinks, a fake
  `git`, and tampered registries are built only under the session scratchpad,
  with `--registry` and `XDG_CONFIG_HOME` pointing inside it. The real
  `~/.config` and this tree are not touched by experiments.
- A fix may change documented behaviour (a message, a refusal, a limit). Such a
  fix is reported before it is made and recorded in the ADR.
- ADR 0003 is written as `Proposed` until the owner accepts it; the roadmap and
  README are not updated by this plan.
- Commits only on explicit approval; nothing pushed without it.

## Deferred work

- Store-side contract (candidate 4); end-to-end check and README (candidate 5).
- Anything that needs a descriptor, registry, or manifest format change; locking
  for concurrent registry writers; refresh on digest drift.

## Review Focus

- A store swapped for a symlink or edited between verification and read: the
  digest recorded in the manifest must describe the bytes actually installed
  (Increment A hypothesis 1).
- Fragment text containing a marker split by CR, NEL, or Unicode line
  separators, or produced by placeholder substitution (hypothesis 4).
- A registry entry pointing at the template, the project, `/`, or a home
  directory (hypothesis 7).
- A forged `external_modules` entry in a project manifest under `--add`
  (hypothesis 8).
- Terminal control characters from a hostile store reaching error or `--list`
  output (hypothesis 9).

## Result

All completion criteria met. Implemented in `690f270` (`install.py`,
`tests/test_install.py`, ADR 0002 addendum, ADR 0003, ADR index); the plan was
approved in `399e469`.

- Increment A: a read-only `security-reviewer` ran scratch experiments against the
  ten hypotheses. Refuted: 1 (symlink and swap handling of a store, with a
  race-only residual), 2, 3, 5, 6, 7, 8. Partly confirmed: 4, 9, 10. New findings
  F1 to F7 (all Low, or Low to Medium for F3).
- Increment B: fixed with tests that failed first: F1 placeholder-completed
  reserved marker; F2 one store under case aliases (`same_store`); F3
  non-printable real path; F4 `--unregister --dry-run` deleted the entry; F5 `..`
  through a symlink resolved lexically; F6 `NAME_RE` accepted a trailing newline
  and a huge `module_format` was echoed; F7 fragments were read before the count
  check.
- Increment C: a second reviewer tried to bypass each fix and probed further; no
  bypass and no new traceback. Two cosmetic notes only.
- Increment D: ADR 0002 addendum and ADR 0003 (`Proposed`), plus the index row.
- Increment E: see Verification and review below.

Verification: `python3 -I -W error::ResourceWarning -m unittest discover -s tests`
passed (167 tests, up from 155); `git diff --check` clean. A scratch install of
`graphify,cad,plan-review,claude` differed from `e811b6d`'s installer only in the
recorded template commit and dirty flag (the old copy had no git history), and
`--list` was identical. A fixture store, `.git` included, had the same checksum
across register, list, install, `--unregister --dry-run`, and unregister; the
registry file had mode 600. The real `~/.config` was never touched.

Independent review: a read-only `workflow-reviewer` found one Low regression: the
`..` fix let a symlinked store through when the path ended in `/.`. Fixed with a
test that failed first, plus a guard that `.` still names the current directory.
Two ADR wording fixes were made.

Rulings: the comma in a `--with` path stays as specified (the entry splits and fails
closed) and is recorded as a residual; control and bidirectional characters in
fragment text stay allowed, as the spec treats fragments as trusted guidance;
`NAME_RE` was tightened to end at `\Z` for built-in names as well, because only a
trailing newline is newly refused.

Deferred minors: the registry keeps the case the owner typed on a case-insensitive
filesystem; an integer `module_format` over Python's 4300-digit limit reads as
"not a valid JSON object".

Not done (roadmap candidates 4 and 5): the store-side contract in
`claude_knowledge_base`, and the end-to-end check with README prose. ADR 0003 is
`Proposed` until the owner accepts it.

No Codex plan review was run for this plan: the review for `docs/plans/next.md`
was closed, and the owner approved the plan without it.
