# Next plan

Status: In Progress
Created: 2026-10-15

## Goal

`install.py` has had an adversarial security review, every reachable finding
is fixed with a regression test that failed before the fix, and the residual
risks and the trust model are written down.

## Scope

Review and harden `install.py` and the module/slot loading it performs:

1. A threat model for the installer: what it trusts, what it reads from
   outside the template repository, and what it can write.
2. An adversarial review with experiments in a scratch directory (hostile
   inputs, fake `git` executable, symlinked project trees).
3. Fixes for confirmed findings, tests first.
4. An ADR recording the trust model and the accepted residuals.
5. (Added at your request after Increment C.) An opt-in
   `--skip-unsafe-entries` option for `--add`, so a project containing
   symlinks or oversized files can be extended without relaxing any write
   protection.

## Non-goals

- Anything the installer does not do: network access, dependency installs,
  and the contents of generated projects after creation.
- `claude_global_config` helpers (`claude-workflow`, `remote-runner`) beyond
  how the generated stub refers to them.
- New installer features, other than Increment D. Behavior changes are
  limited to refusing or neutralizing unsafe input.

## Assumptions and constraints

- Trust model to confirm in Increment A: the template repository content
  (`base/`, `modules/`) is trusted when the owner runs it from their own
  clone; a forked or locally modified module is *not* automatically trusted;
  everything read from a target project (`--add`) and every command-line value
  is untrusted.
- The installer is a local CLI run by its owner; there is no privilege
  boundary, so impact is bounded to what the owner's account can write.
- Standard library only, Python 3.9+, POSIX paths; fixes keep that.
- Hypotheses to test, not conclusions (from reading the code):
  1. `--add` reads project files with `open()` and writes with `write_tree`,
     both of which follow symlinks, so a symlinked file or directory in the
     project may redirect a read or a write outside the project.
  2. `.template-manifest` is parsed as JSON and its fields used without
     type checks; a non-object or non-list value likely raises a traceback.
  3. `git` subprocesses (`init`, `config`, `rev-parse`, `status`) inherit the
     caller's environment and the template repo's own config, so a global
     `init.templateDir`, `core.hooksPath`, `core.fsmonitor`, or ambient
     `GIT_*` variables may run code or copy hooks into a new project.
  4. `--name`, `--git-name`, and `--git-email` reach files and `git config`;
     control characters, very long values, and values beginning with `-`
     need probing.
  5. `check_target` validates the target before later writes; a path swapped
     or created between check and write (TOCTOU) and case-insensitive
     filesystem collisions are untested.
  6. `files/` entries in a module could escape through `..`, absolute paths,
     or case-colliding names; symlinks are rejected but other special files
     (FIFOs, device nodes) are not.

## Discovery and impact evidence

Graphify: skipped — one source file (`install.py`, about 560 lines) and one
test file; the affected surface is fully enumerated above. Verified against
current source: `collect_tree` rejects symlinks and `..` only for template
sources; `cmd_add` walks the project with `os.walk` and reads each file with
`open()`; `git()` passes no environment override; `template_state` runs
`git` in the template root.

## Completion criteria

- The threat model and each hypothesis above is recorded as confirmed,
  refuted (with the experiment), or accepted residual, in the ADR.
- Every confirmed finding has a regression test that fails before and passes
  after its fix; the full suite passes; `git diff --check` is clean.
- An independent adversarial pass over the fixes found no remaining
  reachable High or Medium issue, or each is recorded as accepted residual
  with the owner's agreement.
- No legitimate installer behavior regressed: the existing install, `--add`,
  dry-run, hint, and prompt tests still pass unchanged.

## Increments

### Increment A — threat model and adversarial review

Dependencies: None
Affected areas: scratch experiments only; no tracked files change except
this plan's Result

1. Write the trust model and entry-point list (command-line values, target
   directory, project tree and manifest under `--add`, module sources, `git`
   environment) and have it reviewed by you.
2. Run the `security-review` skill and an adversarial `security-reviewer`
   pass over `install.py` and `tests/test_install.py` with experiments in a
   scratch directory: hostile names and paths, a fake `git` that records its
   arguments and environment, symlinked files and directories in a project,
   crafted manifests, special files and case collisions in module sources.
3. Record findings by severity with the experiment that shows each, and the
   smallest proposed fix.

Completion: a findings list in this plan's Result; you decide which are
fixed in Increment B and which are accepted.

### Increment B — fixes, tests first

Dependencies: Increment A, and your decision on its findings
Affected areas: `install.py`, `tests/test_install.py`, `README.md`

1. For each accepted finding, add a regression test that fails against the
   current code.
2. Apply the smallest fix. Candidate shapes, to be confirmed by Increment A:
   refuse symlinks (and non-regular files) in the project tree and along
   every written path under `--add`; validate manifest types; run `git` with
   a scrubbed environment and explicit `-c` overrides for hooks, templates,
   and fsmonitor; reject control characters in names; refuse special files
   in module sources.
3. Re-run the whole suite and a scratch install/`--add` end to end.

Completion: every fix has a test that failed first; suite passes.

### Increment C — independent bypass pass and decision record

Dependencies: Increment B
Affected areas: `docs/decisions/0002-installer-trust-model.md`,
`docs/decisions/README.md`, `README.md`

1. Give the fixes to a fresh `security-reviewer` with no prior findings and
   ask it to bypass them; fix anything reachable, tests first.
2. Write ADR 0002: trust model, mitigations, accepted residuals, and the
   assumption that a modified module is the owner's responsibility.
3. Add a short "Security notes" section to `README.md`.

Completion: ADR accepted by you; no unresolved reachable finding.

### Increment D — `--skip-unsafe-entries` for `--add`

Dependencies: Increment C (hardened walk and write checks)
Affected areas: `install.py` (`scan_project`, `cmd_add`, argument parser),
`tests/test_install.py`, `README.md`,
`docs/decisions/0002-installer-trust-model.md`

1. Tests first:
   - with the option, a project containing a symlinked directory
     (`.venv`-like), a symlinked file, a FIFO, and a file over the size cap
     is extended, each skipped entry is listed in the output, and none of
     them is read, patched, or written through;
   - without the option, the same project is still refused (current
     behavior unchanged);
   - with the option, a module file or manifest whose target path is a
     symlink, a hardlinked file, a read-only file, or under `.git` is still
     refused with nothing written;
   - with the option, a slot marker that exists only in a skipped file still
     fails with "fragments with no matching slot marker";
   - a symlinked project directory and a malformed manifest are refused with
     the option; the option is rejected for a new-project install.
2. Implement the option for `--add` only: `scan_project` skips and reports
   symlinks, special files, and oversized files instead of raising; the
   write-time checks are unchanged.
3. Amend ADR 0002 (still Proposed) with the option, what it does and does not
   relax, and the consequence that skipped files are not patched; describe it
   in the README Security notes.

Completion: tests pass; a scratch project with `.venv` links is extended with
the option and refused without it; nothing outside the project changes.

## Verification

- `python3 -I -m unittest discover -s tests`.
- Scratch experiments under the session scratchpad, never in the template
  repository or in a real project; a fake `git` on `PATH` for subprocess
  behavior; a scratch `HOME` and `GIT_CONFIG_GLOBAL`.
- `git diff --check`.

## Risks and sensitive actions

- Experiments write only to scratch directories; no real secrets, no
  network, no external systems. Symlink experiments point only at scratch
  files created for the test.
- Tightening symlink and environment handling could refuse a legitimate
  setup (for example a project directory that is itself a symlink). Fixes
  must be checked against the install and `--add` tests and documented.
- Commits only on explicit approval; nothing pushed without it.

## Deferred work

- A neutral shared workflow helper in place of `claude-workflow`.
- `--add` fragment insertion for already-installed modules; `--remove`.
- Ghidra and Codex second-opinion modules; adopting `cp -R` projects.

## Result

### Increment A — trust model (draft for owner review)

Assets: files outside the new project reachable by the owner's account; the
integrity of generated hooks/config (a new repo must not receive executable
content the owner did not choose); the owner's git identity.

Trusted: the template checkout (`base/`, `modules/`, `install.py`) when run
from the owner's own clone; the owner's command line as an *intent*.

Untrusted inputs:

| Entry point | Used for |
|---|---|
| `<target>`, `--dir` | paths created, written, and walked |
| `--name`, `--git-name`, `--git-email`, `--with`, `--add` | file text, `git config`, module selection |
| target project tree under `--add` | read in full, patched, written back |
| `.template-manifest` in a project | module list, schema |
| `modules/*` of a fork or locally edited clone | module files and slots |
| caller environment and global/system git config | every `git` subprocess |

Writes allowed: inside the target (or project) directory, and
`<target>/.git/info/exclude`. Everything else is a finding.

Out of scope: the owner deliberately installing a malicious module; what a
generated project's own tools do later.

### Increment A — findings (adversarial review, 2026-10-15)

Reviewer experiments ran on a scratch copy under a scratch `HOME` and git
config. Findings 1, 2, 4 and the manifest crash in 5 were reproduced
independently against the tracked `install.py` before recording.

| # | Severity | Finding | Status |
|---|---|---|---|
| 1 | High (hostile project dir) | `--add` follows symlinks: a symlinked `.claude` received `remote-runner.toml` outside the project; a symlinked `AGENTS.md` was read and the outside file rewritten with slot fragments; a symlinked `.template-manifest` is overwritten. | reproduced |
| 2 | Medium | `git()` passes the caller's environment: with `GIT_DIR` set, `git init`, `symbolic-ref` and `config --local user.*` wrote the identity into another repository. | reproduced |
| 3 | Medium/Low | `template_state` runs `git status` in the template root: a configured `core.fsmonitor` program ran, even under `--dry-run`; global `init.templateDir` hooks are copied into the new repo. | reviewer-tested |
| 4 | Medium/Low | Module `files/.git/**` is installed: a forked module's `.git/hooks/pre-commit` landed in the new repo (and via `--add`). | reproduced |
| 5 | Low | `.template-manifest` is not type-checked: `[]`, `null`, wrong `modules` type, empty file, deep nesting give tracebacks; a string or dict `modules` is accepted. | `[]` reproduced |
| 6 | Low | `--add` walk reads FIFOs (hang), dangling symlinks (traceback), unbounded special files. | reviewer-tested |
| 7 | Low | Failure midway leaves a partial write (`--add` after a read-only file; `git init` failure leaves the tree); missing `git` is a traceback. | reviewer-tested |
| 8 | Low | `check_target` prefix test is case-sensitive: on case-insensitive APFS a case-variant path inside the template is accepted. | reviewer-tested |
| 9 | Low | `--name` (in `--add`) and `--git-name` accept control characters and ANSI escapes that are echoed to the terminal. | reviewer-tested |
| 10 | Low | Case-colliding module file names overwrite base files on case-insensitive filesystems; a module file named `.template-manifest` is overwritten silently. | reviewer-tested |

Found sound (tested by reviewer): refusal paths write nothing; target
normalization and symlinked target/ROOT refusal; argv-list subprocess calls
with no shell; `--git-email` newline refusal; hint validation (by reading).
Not exercised: memory cap on `/dev/zero`, a real TOCTOU race, Windows
separators. Reviewer proposed fixes: reject symlinks and non-regular files
along the project walk and each written path (including the manifest);
scrub `GIT_*` and pass `-c core.fsmonitor=false`, `--template=`,
`--no-optional-locks`; reject `.git` (case-insensitively) in module and
written paths; validate manifest types and schema; catch `OSError`; compare
case-normalized paths; reject non-printable names.

### Increment B — fixes (implemented, awaiting commit)

Findings 1–6 fixed, tests first (25 new test failures/errors before the fix,
all passing after; full suite 62 tests):

- 1, 6: `--add` and module sources read only regular files through
  `read_regular` (lstat plus `O_NOFOLLOW`/`O_NONBLOCK`, 16 MiB cap); symlinks,
  FIFOs, and other special files, and a symlinked project directory, are
  refused; every written path is checked for symlinked or non-directory
  components first, and files are opened `O_NOFOLLOW`.
- 2: `git` runs with every `GIT_*` variable dropped except
  `GIT_CONFIG_GLOBAL/SYSTEM/NOSYSTEM`.
- 3: `git` runs with `core.fsmonitor=false`, `core.untrackedCache=false`,
  `core.hooksPath=/dev/null`, and `git init --template=`; new repositories no
  longer receive sample hooks or a global template directory.
- 4: any path component equal to `.git` (case-insensitive) is refused in
  module files and in every write.
- 5: `.template-manifest` must be an object with `schema` 1 and a list of
  valid module names; invalid JSON and deep nesting are clean refusals.

Optional findings, same method (tests failed first, now pass; suite 66):

- 8: `check_target` also compares every existing ancestor of the target to
  the template by identity (`samefile`), so a case variant of the template
  path is refused on case-insensitive filesystems.
- 9: project name (`new` and `--add --name`), git name, and git email must be
  printable single-line text.
- 10: module files are compared case-insensitively against base and earlier
  modules, and `.template-manifest` (any case) is reserved.
- 7 (partial write on a mid-run failure, `OSError` traceback) is accepted as a
  residual: a rerun is idempotent and recoverable.

Behavior changes to note: `--add` refuses projects containing symlinks (no
override); a manifest lacking `schema` is refused; new projects have no
`.git/hooks` directory.

### Increment C — independent bypass pass (implemented, awaiting commit)

A fresh `security-reviewer`, given the trust model and the claimed
protections but not the first-round findings, ran against a `git archive`
copy of `66b492c`. The git subprocess hardening held. It found, and the new
regression tests reproduced (7 failures + 1 error before the fix), five
issues, now fixed (suite 71 tests):

| # | Severity | Issue | Fix |
|---|---|---|---|
| 1 | Medium | A hardlinked project file (or manifest) was written in place, rewriting a file outside the project. | Writes go to a temporary sibling and are renamed; the link target is never written. |
| 2 | Medium | `--add` was not atomic: an unwritable file gave a traceback after the manifest and new files were written, leaving it permanently inconsistent. | Existing targets must be writable (checked first); all temporaries are created before any rename, manifest renamed last; `OSError` is an `InstallError`. |
| 3 | Medium | Module trees followed symlinks (slot files, `files/`, `module.json`, module directories): a forked module could read outside files into a project. | Module directory, `files/`, `slots/`, `module.json`, and slot files are refused when symlinks and read through `read_regular`. |
| 4 | Low/Medium | Running the installer through a symlink to the template bypassed the "target inside template" check (`ROOT` was not resolved). | `ROOT` uses `realpath`. |
| 5 | Low | Write-time TOCTOU: a parent directory swapped for a symlink after the check. | Not fixed; accepted residual in ADR 0002 (needs a concurrent local attacker; dir-fd operations would close it). |
| 6 | Low | Usability: `--add` refuses `.venv`/`node_modules` symlinks and files over 16 MiB. | By design; documented in the README and ADR 0002. |

Verified sound by the reviewer: scrubbed git environment (`GIT_CONFIG_COUNT`,
`GIT_EXEC_PATH`, `GIT_DIR`, and others never reached git), `--template=`
(no hooks directory), `.GIT` casefold, path normalization from `os.walk`,
name injection (slugged id, substitution after slot expansion). Not run: a
real symlink-swap race, non-APFS filesystems.

ADR 0002 (Proposed) records the trust model, mitigations, and residuals;
README has a Security notes section.

<!-- Complete this only after verification. Archive the plan according to
base/docs/plans/README.md, then reset this file to the empty template. -->
