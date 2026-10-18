# Report unchanged files and merge template updates

Status: In Progress
Created: 2026-10-18

## Goal

`--update` tells the owner every file it left alone and why, so the effect of a
merge can be judged first. A new opt-in `--update --merge` then carries template
changes into those files with a three-way merge, keeping the project's edits.

## Scope

- Increment A: an always-on report of files `--update` did not change, including
  `base/` files, which `--update` neither compares nor mentions today.
- Increment B: reconstruct the template as installed (the file as the recorded
  `template_commit` would have rendered it) from the template's git history,
  read-only, and use it to refine the report: template changed or not since
  install, or why no base is available.
- Increment C: `--update --merge`, with `--dry-run` support. A file unmodified
  since install takes the new template text. A modified file whose edits do not
  overlap the template's changes is merged. A file that would conflict, or that
  has no base, is left untouched and listed.
- README, ADR 0002 addendum, tests.

## Non-goals

- Writing conflict markers into files. A conflicting file stays as it is.
- Merging files the template does not ship (the 0012 rule stands), external
  module store files (the installer never reads them), or `--remove`.
- A true merge of `docs/plans/next.md`. It is per-plan content: only the
  unmodified-since-install case takes the new template text.
- Making `--merge` the default.
- Anything in `ask-codex` or the global configuration.

## Assumptions and constraints

- Verified in `install.py`: `cmd_update` compares only module `files/`
  (`install.py:1398-1409`); `base/` files such as `docs/plans/README.md` are
  never compared or reported. The manifest records `template_commit` and
  `template_dirty` and nothing per file.
- The rendering of a file at an old commit is reproducible by running the
  current `assemble`, `substitute` and `refresh_blocks` code against that
  commit's `base/` and `modules/`. `load_modules` already takes a directory;
  `assemble` and `collect_tree` use the module constants `BASE_DIR` and
  `MODULES_DIR` and need to take them as parameters.
- A base is unavailable when `template_commit` is missing, `template_dirty` is
  true, or the commit is not in the template clone. Those files are reported
  and, under `--merge`, left untouched.
- A renamed project (`--name`, or a changed directory name) can change the
  `REPLACE_WITH_PROJECT_NAME` substitution. A base that no longer matches shows
  up as an extra difference or a conflict, never as a silent overwrite.
- The manifest is untrusted input (ADR 0002). `template_commit` reaches `git`,
  so it must be validated as 40 lowercase hex characters and passed as a full
  object name after `--` where git allows; nothing else from the manifest
  reaches `git`.
- Decided by the owner: the manifest's single `template_commit` advances on
  every write today, which after a partial merge would discard the base for
  files left unmerged. When a differing file is left unmerged, its base is
  recorded in an optional manifest map (`file_bases: {path: commit}`) and
  `template_commit` advances as now; the map is validated on load and ignored
  by older installers. For each path the effective base commit is
  `file_bases[path]` when present, otherwise `template_commit`; classification
  and merging render that commit's base for that file. A file merged cleanly,
  or found identical to the current template, loses its entry; a conflicting
  or otherwise unmerged file keeps its existing entry, or gains one naming the
  effective base it was judged against. (Holding `template_commit` back was rejected: simpler,
  but it makes the recorded commit misleading.)
- Base lifecycle (from Codex review round 3). `cmd_add` does not refresh
  `template_commit`, so a module added later was not installed from the
  recorded commit. Increment B therefore also makes `cmd_new` record the
  effective `project_name` and `cmd_add` record `module_commits:
  {module: commit}` for each module it adds (optional keys, validated on load,
  ignored by older installers). A project is classified `no base` when: an
  installed module's recorded commit differs from the file's effective base;
  or, for a legacy project with no such record, the base render lacks an
  installed built-in module or a `BEGIN module:... slot:...` block the project
  file carries (residual risk: a legacy module added later with no visible
  trace; mitigated by opt-in `--merge` and the dry-run listing).
- A file containing a block of an external module is `no base` and is never
  merged: the manifest holds only the store's current digest, so the
  historical fragment is not recoverable.
- The project name for rendering is the manifest's `project_name` when present.
  For a legacy project without one, `--merge` requires an explicit `--name`
  (the report says "name assumed from directory" otherwise), so a mismatched
  substitution cannot produce a silent clean merge.
- `template_commit` (and each `file_bases`/`module_commits` value) is accepted
  only if it is 40 lowercase hex characters and
  `git rev-parse --verify --quiet <sha>^{commit}` resolves to a commit; a blob
  or tree object id is `no base`.

## Discovery and impact evidence

Graphify: skipped - the graph is missing (the last commit reported
`graph_missing`) and building one is not part of this plan. Discovery was by
reading `install.py` directly: it is a single file, and the touched functions
are `assemble`, `collect_tree`, `cmd_update`, `load_manifest`,
`manifest_bytes`, `template_state` and `write_tree`. Precedents: plans 0009
(`--update`), 0010 (`--remove`) and 0012 (owned files); ADR 0002 and its
addenda.

## Completion criteria

- `--update` prints, for every file it does not change, the path and a reason
  from a fixed set, including `base/` files and project-created files that
  carry markers.
- With a usable base the report distinguishes "template unchanged since
  install" from "template changed" and, under `--merge --dry-run`, "merges
  cleanly" from "conflicts"; without one it says why.
- `--update --merge` writes only clean results, leaves every other file
  byte-identical, and a dry run writes nothing.
- A hostile manifest cannot make the installer run `git` with an
  attacker-chosen argument or read or write outside the project.
- The full suite passes and `git diff --check` is clean.

## Increments

### Increment A — Report every file left alone

Dependencies: None
Affected areas: `install.py` (`cmd_update`), `tests/test_install.py`, `README.md`

1. Write tests that fail first: a `base/` file differing from the template is
   listed; a module file differing is listed (as today); a project-created file
   with a slot marker is listed as not patched; an identical file is not
   listed; the report appears with and without `--dry-run`.
2. Compare `base/` files in `cmd_update` the same way as module files, with
   reasons `differs from the template`, `project-created file with markers,
   not patched`, and `skipped (unsafe entry)` for entries already skipped.
3. Print one line per file after the existing `kept` lines, grouped by reason.
4. Run the suite and `git diff --check`.

Completion: the knowledge-base case (a stale `docs/plans/README.md`) is listed
instead of "Nothing to update"; the report writes no file.

### Increment B — Reconstruct the installed template and classify

Dependencies: Increment A
Affected areas: `install.py` (`assemble`, `collect_tree`, new base-rendering
helper, `load_manifest`, `manifest_bytes`, `cmd_new` and `cmd_add` manifest
records), `tests/test_install.py`, ADR 0002 addendum

1. Write tests that fail first, using a throwaway git repository as the
   template: base rendered at an older commit equals what `--new` wrote; a
   changed template file shows as "template changed"; an untouched one as
   "template unchanged"; a missing commit, a dirty install and an unknown
   commit give the three "no base" reasons; a `template_commit` such as
   `--output=x` or `HEAD~1` is rejected without running `git`, and a valid
   blob or tree object id is `no base`; a project created at one commit with a
   module added at a later commit (`--add`) is `no base` where the module's
   recorded commit differs; a file with an external-module block is `no base`;
   `--name X` in directory Y is recorded and reused by a later update without
   `--name`, while a legacy project without a recorded name needs `--name` to
   merge; and after a
   module file and a slot fragment both change in a later commit, the
   reconstructed base is still byte-identical to the original installation.
2. Parameterize `assemble` and `collect_tree` by template directory
   (defaults unchanged).
3. Materialize the commit read-only: `git archive` of `base` and `modules` to a
   private temporary directory, extracted by the installer accepting only
   regular files and directories, with normalized names, the existing size cap,
   no links and no `.git`. Then load the archived commit's `base/` and
   built-in `modules/` (descriptors, files and slot fragments) through the
   parameterized `load_modules`/`assemble` path and render with the current
   code. From the project, only the manifest's installed module names and the
   project name (for substitution) are used; nothing is read from the current
   checkout's `base/` or `modules/`.
4. Refine the report reasons using the base. Without `--merge` nothing is
   written.
5. Add the ADR 0002 addendum for the git read and the extraction rules.

Completion: classification is correct against a fixture with an older commit;
the hostile-commit tests pass; nothing in the project changes.

### Increment C — `--update --merge`

Dependencies: Increment B
Affected areas: `install.py` (`cmd_update`, `write_tree` use, manifest),
`tests/test_install.py`, `README.md`, ADR 0002 addendum

1. Write tests that fail first: an unmodified-since-install file takes the new
   text; a modified file with non-overlapping edits merges and keeps both;
   overlapping edits leave the file byte-identical and listed as `conflict`; a
   no-base file is left untouched; `docs/plans/next.md` takes new text only
   when unmodified; `--dry-run` writes nothing and prints the same
   classification; a second run is a no-op; the `file_bases` rules above hold
   across two successive updates with a previously unresolved file (its base is
   the recorded per-file commit, not the advanced `template_commit`, and the
   entry is removed once it merges or matches the template); project-created
   files are never merged.
2. Merge with `git merge-file -p` on private temporary copies (base, ours,
   theirs); write the result only on exit status 0; any other status is a
   conflict or an error and leaves the file alone. Run block refresh on the
   merged text as `--update` does today.
3. Add `--merge`, valid only with `--update`/`--upgrade`; reject it elsewhere
   with a clear message.
4. Update the README `--update` documentation and the ADR 0002 addendum
   (writes to existing files, still limited to owned files).
5. Run an adversarial review (security-reviewer) covering hostile manifest
   values, hostile files in a project and in the template history, symlinks,
   large files and temporary-file handling; fix findings with regression
   tests.

Completion: all of the above tests pass; a real dry run against
`claude_knowledge_base` lists its stale README as merging cleanly and changes
nothing.

## Verification

- `python3 -I -m unittest discover -s tests`
- `git diff --check`
- Dry runs of `./install.py --update --merge --dir <project> --dry-run`
  against `claude_knowledge_base` and `othello`, checking nothing changes.

## Risks and sensitive actions

- Increment B runs `git` and extracts an archive using a value from an
  untrusted manifest, and Increment C writes into existing project files. Both
  change trust boundaries recorded in ADR 0002, so each gets an addendum and C
  gets the adversarial review above before archiving.
- A wrong base could merge cleanly into the wrong text. Mitigation: bases are
  rendered, not guessed; conflicts leave files untouched; `--merge` is opt-in;
  the dry run shows every file first.
- Increment C is separately reviewable. Stopping after B still leaves a useful,
  read-only report.

## Deferred work

- Optionally writing conflict markers or a sidecar file for conflicts.
- Merging external-module store content.

## Result

Increment A done (not yet committed): `--update` now compares `base/` files with
the template, ignoring module blocks, and lists `kept` and `skipped` files with
reasons. Six new tests failed first (five failures; the fresh-project guard
exposed an existing false `kept docs/cad.md` caused by the raw comparison, now
fixed by the block-aware one). Suite 237 pass, `git diff --check` clean. A dry
run against `claude_knowledge_base` lists its stale `docs/plans/README.md`
and four project-created files with markers.

<!-- Complete this only after verification. Archive the plan according to
README.md, then reset this file to the empty template. -->
