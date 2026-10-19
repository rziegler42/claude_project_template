# Module harness files

Status: Approved (2026-10-19)
Updated: 2026-10-19 (amended by plan 0023: base harness files, the harness ignore block, retired modules)

Requirements for letting a module, built-in or external, carry the harness-specific files that
serve it (skills, agents, commands), installed into the project's own harness directory. The
decision is [ADR 0004](../decisions/0004-harness-files-in-modules.md) (`Accepted`). This document
fixes what that ADR leaves open: names, shapes, numbers and the exact clauses it amends. Where the
ADR fixes a rule, this document restates it and does not reopen it. Nothing here is implemented
yet; the roadmap orders the plans that do.

## Terms

- **Harness**: a coding tool whose project-level files the template can install. The installer owns
  the table below; the only entry in this version is `claude`.
- **Harness directory**: `harness/<harness>/` inside a module (`modules/<m>/harness/<h>/` for a
  built-in, `template-module/harness/<h>/` for an external store).
- **Harness root**: the project directory the table maps a harness to (`.claude/` for `claude`).
- **Supplier**: a module whose harness file is installed at a path, or the reserved name `base` for the
  template's own base harness files. A path may have several.
- **Unit**: the collision unit of a harness path: `skills/<name>/` (the whole directory), or one
  file for every other path.
- **Approval**: the owner's recorded pin of an external store's harness tree to a digest.

## Scope

- Harness directories for built-in and external modules, the harness table, `--harness`, and the
  manifest record of the harness and of every installed harness file.
- The `module.json` declarations `helpers`, `workers` and `global_config`, their reporting, and the
  marker file.
- `module_format` 3, the digest of a harness tree, registration review (`--register` output),
  `--approve`, and the verb-by-verb approval check.
- The change that makes an installer from before this specification refuse a project that records a
  harness.
- Removal of harness files, and the clauses of earlier records this specification amends.

## Non-goals

- Installing helpers, hooks, settings, MCP configuration or anything outside the table's allowlist.
- Changing harness in place (a new project), or more than one harness per project.
- Merging edits into installed harness files (`--update --merge` does not touch them).
- Running a model, a program from a store, or any network call in the installer.
- Anything in `claude_global_config`, including who writes the marker file and ADR 0008.
- Migration of existing projects for the `claude` and `codex` modules (roadmap candidate 6).

## The harness table

The installer holds this table in code. A change to it is a template change, not a module's choice.

| Harness | Root | Root-level files (built-in / external) | Allowed top-level entries (built-in modules) | Allowed top-level entries (external stores) | Marker file |
|---|---|---|---|---|---|
| `claude` | `.claude` | `CLAUDE.md` / none | `skills/`, `agents/`, `commands/`, `remote-runner.toml` | `skills/`, `agents/`, `commands/` | `~/.claude/global-config.json` |

- A harness name matches `[a-z][a-z0-9-]{0,31}\Z`. `--harness` with a name not in the table is
  refused, listing the known names. A `harness/<name>/` directory whose name is not in the table is
  an error when the module is selected, installed or updated and when an external store is
  verified, naming the module and not echoing the directory name if it is longer than 32
  characters. Built-in harness trees are validated lazily, only for modules a command selects,
  installs or updates; `--list` and `--remove` never read them, so a bad tree cannot block them.
- The allowlist applies to installable destinations. A harness directory's source entries are the
  allowed top-level entries, `root/` (restricted to the root-level files in the table; an external
  store has none, because `CLAUDE.md` can import any file into every session) and `harness.json`;
  anything else is refused. The allowlist keeps settings, hooks and MCP configuration out:
  `settings.json`, `settings.local.json`, `hooks/`, `.mcp.json` and anything else not listed are
  refused, when a built-in module is selected and when a store is verified.
- The allowlist is not a guarantee that an installed file cannot cause a command to run. Skills,
  agents and commands are instructions the harness loads automatically, and their frontmatter or
  text can ask for tool use or, in some harnesses, declare hooks or tool permissions. Approval is
  the control; the allowlist only removes the files that run without being invoked. That reading of
  the harness's behaviour is an assumption the owner should confirm against its current
  documentation before approving a store.
- Built-in modules are trusted as template code (ADR 0002: module sources are trusted once they
  are regular files in the checkout). The allowlist and the path rules apply to their harness
  trees so a mistake fails loudly, not because a fork is defended against; a built-in module's
  `files/` is outside this specification and is unchanged.
- The marker path is under the account's home directory from the password database
  (`pwd.getpwuid(os.getuid()).pw_dir`), never from `HOME` or any other environment variable. Where
  that lookup is unavailable, or the directory it returns (or `--global-config DIR`) is empty or
  not absolute, the marker is reported missing. `--global-config DIR` makes the
  marker `DIR/global-config.json` instead of `~/.claude/global-config.json`, as `--registry`
  replaces the registry path, and exists for tests.

## Layout

```text
harness/<harness>/
  harness.json               (declaration file; never installed)
  skills/<name>/SKILL.md     -> <root>/skills/<name>/SKILL.md
  agents/<name>.md           -> <root>/agents/<name>.md
  root/CLAUDE.md             -> CLAUDE.md
```

- `root/` files map to the project root and only to the names in the table's root-level column.
  Everything else maps under the harness root. `harness.json` is a regular file at the top of the
  directory, read and never copied; a directory of that name is refused.
- Each relative path passes `safe_relpath` (no `..`, `.`, empty parts, `\`, `:`, or a `.git`
  component), has at most 8 components, and is unique after case folding and NFC normalisation
  within the tree. For an external store every component also matches `[A-Za-z0-9][A-Za-z0-9._-]*`
  (ASCII), so no alias by Unicode form is possible there. A symlink, special file or unreadable
  entry anywhere in the tree is an error, as for `files/`.
- Limits per harness directory: 128 files, at most 128 entries in any one directory, 256 KiB per
  file, 2 MiB in all; per run, 512 harness files and 8 MiB across all modules. Every file is UTF-8
  text without NUL, and for an external store every file name ends in `.md` apart from
  `harness.json` (no scripts, no binary files). The walk counts as it goes and aborts at the first
  limit, before reading any file, as the fragment count is today. `harness.json` and `root/` count
  toward the limits. The walk uses `scandir` with a counter and does not descend past depth 8, so
  it never lists a whole hostile directory first.
- A store's harness files contain no C0 or C1 control character other than LF (no tab, CR, ESC or
  BEL), so nothing in them can overwrite or hide the review output.
- Every harness write, new or replacing, creates the file `0644 & ~umask` and never copies the
  mode of a file it replaces, so a harness file is never executable, setuid or world-writable by
  the installer's doing. A script a skill needs ships in the module's `files/` or stays in a skill
  as text; "never executable" is not a protection against a skill that tells the model to run text
  it carries.
- Key function. Wherever this document says "casefold and NFC", it means exactly
  `NFC(casefold(NFC(x)))`, because the two orders disagree for some code points.
- Harness files must not contain `@module-slot:`, `BEGIN module:` or `END module:`, as for a
  fragment (a substring test, built-in modules included, checked after placeholder substitution).
  They are excluded from slot expansion and from `--remove`'s block scan, so their text can neither
  capture another module's fragments nor stop a module from being removed.
- A harness path whose installed form equals the installed path of a file `base/` or any module's
  `files/` ships (so `root/CLAUDE.md` is compared as `CLAUDE.md`), compared after case folding and
  NFC normalisation, is an error when the module is selected or the store is verified.
- Unit shapes. An external store has exactly these units, with `<n>` matching
  `[a-z0-9][a-z0-9-]{0,63}`: `skills/<n>/` holding `SKILL.md` directly in it (other files in it may
  be nested to the depth limit), `agents/<n>.md` and `commands/<n>.md`, each directly in its
  directory. Any other shape (a loose `skills/x.md`, `skills/x/y/SKILL.md`, a nested agent) is
  refused. A built-in module may use the same shapes; they are not required of it.
- Units are identified by their frontmatter `name`, which can shadow another module's or a global
  one. For an external store the primary file of each unit (`SKILL.md`, the agent file, the command
  file) must have frontmatter in this exact grammar, and is refused otherwise: line 1 is exactly
  `---` with no BOM; a later line is exactly `---`; there is no CR or tab; each line between is
  either `key: value` at column 0 with `key` matching `[a-z][a-z-]*`, or a continuation indented by
  at least one space; no key appears twice; exactly one `name` key, its value unquoted, equal to
  `<n>`, with none of `{ [ & * ! | > # " '`. For a built-in module the installer reads a `name:`
  line if there is one and otherwise uses `<n>`. The installer compares the names of all harness
  units installed or in this run by `NFC(casefold(NFC(x)))`; a name two different units supply is a
  conflict (Collisions). The installer cannot see the global configuration, so registration prints
  each unit's `name` for the owner to compare with it, and flags a store unit whose name equals that
  of a unit any built-in module ships.
- Placeholder substitution is the ordinary whole-tree one: `REPLACE_WITH_PROJECT_NAME` and
  `REPLACE_WITH_PROJECT_ID`; for an external store also `REPLACE_WITH_MODULE_NAME` and
  `REPLACE_WITH_MODULE_PATH`. A placeholder left over is reported as for a built-in module. The
  digest and the approval cover the bytes as stored, before substitution. A harness file that
  contains a placeholder is installed only when the substituted value matches
  `[A-Za-z0-9._ -]{1,200}`; otherwise the run is refused before any write, so a project name taken
  from a manifest cannot inject text into an approved file.

### `harness.json`

```json
{ "roles": { "chunk-extractor": "agents/graphify-semantic.md" } }
```

- A JSON object of at most 16 KiB with exactly one optional key, `roles`: an object of at most 16
  entries mapping a role id (`[a-z][a-z0-9-]{0,63}\Z`) to a path inside the same harness directory
  that is a regular file in the tree. Unknown keys and missing target files are errors.
- It is the module author's claim that the file implements the role. The installer matches ids and
  never inspects the file.

## Declarations in `module.json`

Optional keys, valid for built-in modules and for external `module_format` 3. Formats 1 and 2 still
reject them as unknown keys.

| Key | Type | Rule |
|---|---|---|
| `helpers` | list of strings | At most 16 names, each `[A-Za-z0-9][A-Za-z0-9._-]{0,63}\Z`, unique |
| `workers` | object | At most 16 entries: role id (as in `harness.json`) to a printable one-line contract of 1-200 characters |
| `global_config` | boolean | `true` when the harness files need the harness's global configuration |

At `--new`, `--add` and `--update` the installer prints one line per item and never installs,
fails or changes the exit status for a missing one:

- `helper <name>: present` when a file with that name exists in an absolute directory of `PATH`, is a
  regular file (after `stat`) and executable by the user; otherwise `missing`. It is never run.
  Reported with or without a harness.
- `worker <role>: implemented by <module>` when the role is one the module itself declares in
  `workers`, its `harness.json` maps the id, and the mapped file is recorded for that module in
  `harness_files` after this run (a file skipped as a conflict does not count); otherwise `warning: <harness> does not implement worker <role>
  (<contract>)`. With no harness recorded, one line says no harness is selected.
- `global configuration: present` when the marker is valid, otherwise `missing`. The marker is read
  with the hardened regular-file read: not a symlink itself (its parent directory may be one, as
  dotfile managers often arrange), a regular file, at most 4 KiB read with a limit of one byte more
  and refused if exceeded, valid UTF-8, a JSON object whose `schema` is the integer 1 (not a
  boolean or a float). Any other state, including a recursion error, is `missing (unreadable or
  invalid marker)` and the contents are never echoed. It is the one file the installer reads
  outside the target, the template, a store, the registry and the approvals file. Anyone with the
  owner's account can forge it; it changes only what is reported.

## Selection

- Command matrix for `--harness NAME`:

  | Command | No harness recorded | Harness recorded |
  |---|---|---|
  | new project | records `NAME` | not applicable |
  | `--add` | records `NAME` (once) | same value: no change; different value: refused |
  | `--update` | refused: `--update` never introduces a harness | same value: no change; different value: refused |
  | `--remove` | refused: the option has no meaning | refused: the option has no meaning |

  `--harness` is also refused with `--list`, `--register`, `--unregister`, `--approve` and
  `--unapprove`.
- New project: the name is recorded; every selected module's harness directory for that harness is
  installed. Without the option, no harness is recorded and no harness file is installed.
- `--add` to a project with no harness and `--harness NAME`: the name is recorded and harness files
  are installed for every installed built-in module that has a directory for it, and for an
  external module added in the same run (after its approval check). An external module installed
  earlier is not read by the activation, so its harness files are not installed then; the run names
  each such module, and `--update NAME` (or a full `--update`) installs them once the store is approved. This
  happens once; afterwards the project has a harness.
- Every refusal above happens before anything is written. An absent option uses the recorded
  harness, if any.
- A module with no directory for the project's harness installs its neutral part and prints
  `<module>: no <harness> files`.
- Interrupted runs: harness files are written before the manifest like every other file. An
  interrupted `--add` (with or without `--harness`) leaves the old manifest and may leave harness
  files on disk that the harness loads automatically but the manifest does not record; rerunning the
  same command converges, because an existing path with identical bytes is adopted (see
  Collisions). An
  interrupted `--new` leaves a non-empty target without a manifest, which the installer refuses to
  reuse today for any module; this specification does not change that.

## Collisions

One rule applies to every harness path, whatever supplies it (ADR 0004, decision 2), evaluated per
unit:

1. Within one run, two suppliers of a path with different bytes, or of a `skills/<name>/` directory
   with different trees, fail the run before any write, naming the path and both modules.
2. A path that does not exist is written and recorded with its suppliers.
3. An existing path with identical bytes (after substitution) is left alone and the module is
   recorded as a supplier.
4. An existing path with different bytes and no record for the module is not overwritten by the
   installer's replace step and is never recorded for the module. The run prints it as a conflict,
   prints a summary count, completes, and exits with the status of the rest of the run, as it does
   for files `--update` keeps today. A `skills/<name>/` unit with any conflicting file is skipped
   whole. A file created after the project scan can still be replaced, the write-path residual of
   ADR 0002.

Rules 2 to 4 also compare against suppliers installed by earlier runs, found by the project scan
and the manifest record, so a store added later with a different implementation of an installed unit
(by path, or by frontmatter `name` at another path) reaches rule 4: a reported conflict and the
unit skipped, not a failed run. Only suppliers in the same run fail the run (rule 1).

`--update` of a path already recorded for the module follows the same rules, with the record as the
baseline: bytes equal to the recorded `sha256` (unedited) are replaced by the module's new bytes and
the record's `sha256` is updated; any other bytes are left alone, reported as a conflict, and the
record is unchanged. A path with several suppliers in its record is replaced only when every
supplier in the record supplies the same new bytes in this run (so a full `--update` can move them
together); otherwise it is left, reported as a conflict, and the record is unchanged, which keeps
the invariant that the record's bytes are what every listed supplier last provided. A recorded path
whose bytes already equal the module's new bytes is adopted and the record's `sha256` set to them,
which is how a rerun converges after a run interrupted between the file write and the manifest
write. `--update` never deletes: a path the module no longer ships keeps its file and its record
until `--remove`, which deletes it if it is unedited. In `--update`, a recorded path is replaced
only when the same module's tree names it in this run.

"Exists" in rules 2 to 4 means `lexists` of the path after case folding and NFC normalisation
against the project's real entries, and anything that exists but is not a regular file (a symlink, a
directory, a special file, including entries `--skip-unsafe-entries` skipped) is a conflict. Extra
files in a skill directory that the module's tree does not contain are left alone and do not make a
conflict.

## Manifest

`.template-manifest` keeps its other keys. A project that records a harness has:

```json
"schema": 2,
"harness": "claude",
"harness_files": {
  ".claude/skills/freecad-scripts/SKILL.md": { "sha256": "<64 hex>", "modules": ["cad-freecad"] }
}
```

- `schema` is 2 exactly when `harness` is recorded and 1 otherwise, so every project without a
  harness and no format 3 store has a manifest byte-identical to today's. An installer from before
  this specification
  accepts only `schema` 1 and refuses a schema 2 manifest as malformed (exit 2, nothing written),
  so it fails closed instead of ignoring harness files. It cannot `--add`, `--update` or `--remove`
  in that project until upgraded. That cost is accepted: no project records a harness yet. The new
  installer refuses a schema 1 manifest that has `harness` or `harness_files`, which an older
  installer would ignore and preserve.
- `harness` is a name in the table. `harness_files` has at most 4000 entries, keys of at most 256
  characters, and no more than 512 KiB when serialised, and the installer refuses a run whose
  manifest would exceed the 1 MiB manifest limit before writing anything. Keys are unique after
  case folding and NFC normalisation. A `schema` of 2 without `harness` is refused. Each key passes
  `safe_relpath` and is a destination the recorded harness can map to: exactly a root-level file
  named in the table, or a path below the harness root whose first component under it is an allowed
  top-level entry of the table (the built-in column; a path installed from a store is always also
  in the external column). `sha256` is 64 lowercase hex digits of the installed bytes. `modules` is
  a non-empty, sorted, duplicate-free list of names, each valid and present in the manifest's
  `modules` or `external_modules`. Anything else is refused on load, before anything is written.
  `harness_files` is present exactly when `harness` is, and is an empty object when no file is
  supplied.
- A file is *unedited* when it is a regular file whose SHA-256 equals the recorded value. This is the
  same rule for built-in and external suppliers, and needs no store, registry or template history.
- External entries use `module_format` 3 in `external_modules` for any store that declares
  anything format 3 allows. Their `digest` is defined below. `module_info` is unchanged.

## External stores

Format 3 adds, beyond format 2: the declarations above and `template-module/harness/<harness>/`.
The installer checks `module_format` before keys (unchanged), so an installer that supports at most
format 2 refuses a format 3 store before writing, as an unknown key or an unsupported format. A
format 1 or 2 store with a `harness/` entry of any kind (a directory, empty or not, or a symlink)
is refused by the new installer too, and a symlinked `harness/` is refused in format 3. A format 3
store with a `harness/` directory, empty or not, needs an approval.

**Digest.** For format 1 and 2 stores the digest is unchanged. For format 3 it is the same SHA-256
framing (relative path, NUL, decimal length, NUL, bytes) over `module.json`, then each
`slots/<slot>.md` by slot name (as today), then every file under `harness/` sorted by its relative
path as UTF-8 bytes, the path including the `harness/<harness>/` prefix and `harness.json` among
them. Slots are ordered by name and harness files by path, which differ for names such as `a` and
`a-b`; the fixture in the tests contains such a pair. Paths are printable and contain no NUL, so
the framing is prefix-free. The tree is read once and the same bytes feed the digest and the
install.

**Registration review.** `--register PATH` verifies the store as today and, when it has a
`harness/` tree, also prints: each harness file with its size and SHA-256 (so the owner can hash
what they read); for each skill, agent and command its `name`, `description` and `tools`, so the
owner can compare the names with those the global configuration already defines; the digest; the
executable-bit files; files whose text
contains an advisory phrase from a fixed list in the installer (`ignore previous`, `disregard`,
`allowed-tools`, `hooks:`, `mcpServers`, `permissionMode`, `bypassPermissions`, `dangerously`,
`curl `, `wget `, `| sh`, `sudo `, `rm -rf`, a line beginning with `!`, case-insensitive); and any
refusal reason. Every value taken from a file is printed ASCII-escaped and capped at 200
characters. It installs nothing and records the store without an approval. The findings are
advisory and never decide, a phrase list is easily bypassed, and an empty list is not a clean bill.
The owner reviews exactly those files, with a security review. `--register` of a store already
registered under the same name and path changes nothing and prints this review again, which is how
the owner gets the current digest for `--approve`.

**Approval.** `install.py --approve DIGEST --name NAME` re-reads the registered store `NAME`,
recomputes the digest, and refuses unless it equals `DIGEST`, then writes
`{ "schema": 1, "approvals": { "<name>": { "path": "<real path>", "digest": "<digest>" } } }` to
the approvals file (same directory mode, temporary sibling and rename, symlink and size checks,
last writer wins). The approvals file is the registry file's path with `.approvals` appended
(`registry.json` becomes `registry.json.approvals`), so two registries in one directory do not share
one, and `--registry FILE` selects both; a `--registry` name ending in `.approvals` is refused. A
new `--approve` for a name replaces its entry. The registry file is not changed, so an older
installer keeps using it. `--approve` and `--unapprove` accept only `--name`, `--registry`,
`--dry-run` and `--global-config`; every other option and any target is refused, as `main()` does
for `--register`. With `--dry-run` they print what they would do and write nothing. This refines
ADR 0004, which says the approval is "recorded in the registry": it is recorded beside it, for that
compatibility.

- `install.py --unapprove NAME` removes the entry and nothing else. `--unregister NAME` keeps its
  existing meaning and also removes the name's approval, whether or not the registry still holds the
  name, so a name registered again later is not approved. It removes the approval first and the
  registry entry second: if the second write fails the store stays registered but unapproved, which
  is safe. A name found in neither file is "not registered" or "not approved" and succeeds, as
  today. A built-in name is still refused.
- The approvals file is loaded only when a store with a `harness/` tree needs it, or by `--approve`,
  `--unapprove` and `--unregister`. It goes through the registry's checks: a symlinked directory or
  file, a special file, over 1 MiB, malformed JSON, a schema other than 1, keys other than
  `schema` and `approvals`, an invalid name, a path that is not an absolute printable single line,
  a digest that is not 64 lowercase hex digits, or an entry with keys other than `path` and `digest`
  is refused before any write, naming the file and never echoing its contents. A missing file means
  no approvals.

**When approval is required.** A store whose tree has a `harness/` directory needs an approval whose
path equals the store's current real path (compared with `same_store`, by identity, not by string)
and whose digest equals the current digest of the complete format 3 tree (`module.json`, slots and
harness). "Changed" in this section always means the current digest differs from the digest in the
store's approval; a digest that differs from the one recorded in the manifest is what `--update`
delivers once it is approved. Any difference, in the neutral fragments or the descriptor as well
as in a harness file, counts. An approval counts only while the registry holds the same name at the same real
path, so a stale entry, or an entry for the same path under another name, authorises nothing, and
a typed `name=path` is accepted only when the registry holds that name at that path and the
approval matches. The approvals file is read lazily and a malformed one never blocks `--remove`,
`--add` of an installed name, `--list`, or a store with no `harness/` tree.

| Verb | Rule |
|---|---|
| `--new`, `--add` of a name not installed | Refused before any write without a matching approval, including a `name=path` store that is not registered. Message names `--register` and `--approve` |
| `--add` of a name already installed | Unchanged: reports "already installed", reads neither the store nor the registry nor the approvals |
| `--update` (all) | A registered store whose complete digest is changed or unapproved is skipped whole, neutral fragments included, with a note; its installed blocks, files and records stay |
| `--update NAME` or `NAME=PATH` | The run is refused before any write when the digest is changed or unapproved |
| `--remove` | No approval, no store, no registry read |

A store without a `harness/` directory needs no approval for any verb, whatever its format.

**One skill name, two stores.** The collision rule applies by unit: identical trees install once;
different trees fail the run when both are in it, and otherwise the later supplier's unit is
reported as a conflict and skipped (Collisions, rule 4).

## Removal

`--remove M` for each path whose record lists `M`:

- The delete list holds only record paths that are regular files in the project scan with a
  matching hash; a record naming a directory, a missing file or any other kind is dropped from the
  record and never reaches the delete step, so it cannot wedge `--remove`.
- `M` is the only supplier and the file is unedited: deleted with the existing descriptor-relative
  delete, and directories it empties are removed. If the file is edited or missing, it is kept (or
  absent), the record is dropped, and the run says so.
- Other suppliers remain: `M` is removed from the record; the file stays.
- The `harness` key stays when the last harness module goes; it records the project's choice, not
  the presence of files. `schema` stays 2.

A path that `base/` or a remaining module also ships is never deleted, as today.

## Amended clauses

Effective when ADR 0004 is Accepted and this document is Approved. Each record gets an
"Amended by 0004" note naming the clause; the rest of its text is unchanged.

| Record | Clause | Replacement |
|---|---|---|
| ADR 0001 | Decision: "Harness entry points (such as `CLAUDE.md`) are independent modules" | Module-owned harness files install under a recorded harness (this document). Entry-point modules keep working until roadmap candidate 6 retires `"harness": true` |
| ADR 0001 | Alternatives: "A single "harness" selector" rejected | Rejected for committed neutral content only; a project records one harness for module-owned harness files |
| ADR 0001 | Verification: no harness-helper names outside harness modules | The neutrality test exempts `harness/` directories |
| ADR 0003 | Decision: "Slot fragments only: no `files/`, no `requires`" | Plus `template-module/harness/<harness>/` under approval; `files/` and `requires` stay excluded |
| ADR 0003 | Alternatives: shipping files from stores deferred | Narrowed to `files/` |
| External-modules spec | Non-goals: "A `files/` directory is outside this version" | Same, plus the harness tree |
| External-modules spec | Descriptor: "no ... `harness` key", "never harness-specific" | A store may carry a harness tree under format 3; its slot fragments stay tool-neutral |
| External-modules spec | Syntax and Verification: `name=path` needs no registry entry | Except a store with a `harness/` tree (this document, Approval) |
| External-modules spec | Manifest: digest over `module.json` and fragments | Format 3 adds the harness tree |
| External-modules spec | Registry: `--unregister` deletes the registry entry only | Also deletes the name's approval; `--unapprove` removes the approval alone |
| External-modules spec | Trust model and Acceptance 2, 3 | Add the harness tree and the approval record |
| ADR 0002 | Trust model and mitigations | Addendum (plan Increment B) |
| ADR 0004 | Decision 6: approval "recorded in the registry"; "refuse a changed store" for `--update` | Recorded in a file beside the registry; a full `--update` skips a changed store (Approval). ADR 0004 was amended in its text on Acceptance |
| ADR 0004 | Decision 6: static findings include symlinks and size limits | Those are refusals; the findings are executables and advisory phrases |
| This specification | Terms: a supplier is a module; Manifest: `modules` lists installed modules | Plus the reserved supplier `base` (plan 0023) |
| README, "Writing a module" | Only modules marked `"harness": true` may be harness-specific | The flag is retired; harness files go in `harness/<harness>/`, and a module named for its tool may name it (plan 0023) |

README "Boundaries" and "Writing a module" change with the implementation plans, not here.

## Trust model

This extends [ADR 0002](../decisions/0002-installer-trust-model.md); the addendum is a work item of
the plan. A harness tree, `harness.json`, the marker file, the approvals file and every
`harness_files` entry in a manifest are untrusted data. Installed skills and agents are loaded
automatically by the harness, so the approval is the control. Static findings are advisory. Writes
stay inside the target and the registry directory (now including the approvals file).

Accepted residuals: a store changed between review and use is caught only by the digest re-check at
use, and the per-file SHA-256 in the review lets the owner hash what they read; a concurrent local
attacker can swap a store or the approvals file; files already installed do not change when the
store does; the installer does not verify that a file implements a declared role, or that its
frontmatter means to the harness what the installer's grammar says it means. The manifest record is
unauthenticated: whoever can edit a project's `.template-manifest` and knows the SHA-256 of a
regular file under the harness root (including one the user wrote) can make `--remove` of the named
module delete it, a capability `files/` removal never had; the destination check, the matching
hash and the owner running `--remove` bound it, and git history recovers the file.

## Acceptance criteria

1. Table: unknown harness name in `--harness`, in a built-in `harness/` directory and in a store is
   refused with nothing written; a name over 32 characters is not echoed.
2. Allowlist: `settings.json`, `settings.local.json`, `hooks/`, `.mcp.json`, `root/.mcp.json`,
   `root/AGENTS.md` and a top-level file in `.claude/` outside the list are refused for a store; a
   built-in module may ship `remote-runner.toml`.
3. Tree: a symlink, FIFO, `.git` component, `..`, case alias, more than 128 files, a 256 KiB+1 file,
   a 2 MiB+1 tree, NUL in a file, a missing `harness.json` target and an unknown `harness.json` key
   are each refused before any write.
   Also refused: a file containing `@module-slot:`, `BEGIN module:` or `END module:`, a path that is a
   case or NFC alias of another (using `NFC(casefold(NFC(x)))`, with the code points that differ by
   order in the test), a non-ASCII or non-`.md` name in a store, a store `root/CLAUDE.md`, a unit
   shape outside the list (`skills/x.md`, `skills/x/y/SKILL.md`, a nested agent or command), a C0 or
   C1 control character other than LF, each hostile frontmatter form (BOM, CRLF, tab, missing
   closing line, duplicate key, a second `name`, a `name` inside a block scalar, quoted or flow
   values, a name differing from its unit), two units with the same `name`, a harness path whose
   installed form equals a `base/` or `files/` path, and per-directory, per-run and walk limits (the
   walk aborts at the first). A bad built-in tree does not block `--list` or `--remove`.
   A project name outside `[A-Za-z0-9._ -]{1,200}` is refused when a harness file has a placeholder.
4. Mode: every harness write, new or replacing, is `0644 & ~umask` and never copies the mode of a
   file it replaces; tested with umask 0 and a pre-existing 0755 and 4755 file.
5. Selection: every cell of the command matrix; `--update` never adds a harness; an interrupted
   `--add` reruns to the same tree and manifest, and an interrupted `--new` is refused as today.
6. Manifest: schema 2 iff `harness` (schema 2 without `harness` is refused); a project with neither
   a harness nor a format 3 store has a byte-identical manifest to today's; hostile `harness`, `harness_files`, `sha256` and `modules` values are refused on load,
   including a key that is a valid relative path but not a destination of the recorded harness (for
   example `README.md`, `.claude/settings.json`, `src/main.py`, `.template-manifest`), an unknown or
   unsorted supplier, case-folded duplicate keys, a schema 1 manifest that has `harness` or
   `harness_files`, more than 4000 entries, a key over 256 characters, a directory-valued key
   (dropped, `--remove` still succeeds), and a run whose manifest would exceed 1 MiB (the writer
   enforces the record limits too). A forged key that is a valid destination but names a file the
   module does not ship cannot be told from a real one on load, so it loads; `--remove` deletes it
   only when the file's hash matches, as the Trust model residual says. An
   installer built from the commit before this work, run with `--update --dry-run` against a schema 2
   manifest, exits 2 and writes nothing.
7. Collisions: each of the four rules, including a `skills/<name>/` unit with one differing file and
   two stores shipping the same skill in one run (fails) and in separate runs (conflict, skipped);
   an `--update` of one co-supplier whose new bytes differ from the other's (left, recorded
   unchanged) and of both together (replaced); a run killed between a file write and the manifest
   write, rerun (the new bytes are adopted, the record updated); an existing symlink, directory or
   case-alias at a destination (a conflict); extra files in a skill directory (left alone).
8. Declarations: a role reported implemented only when the module declared it, its file is mapped
   and recorded after the run; a relative or empty home directory or `--global-config` reports the
   marker missing; each key's bounds; present and missing helpers; a worker with and without a
   `harness.json` mapping; the marker present, absent, a symlink, a directory, oversized, not JSON,
   not UTF-8, deeply nested, with `schema` `true` or `1.0`, and found through the password database
   although `HOME` points elsewhere, with no echo of its contents; nothing installed and exit
   status unchanged for any missing item.
9. Stores: format 3 only; formats 1 and 2 reject the new keys and the tree; the digest of a fixed
   fixture store is a literal in the test; changing, adding or removing a harness file, or only
   `harness.json`, changes it.
10. Approval: `--register` installs nothing and prints the listing and digest; `--approve` with a
    wrong digest, an unregistered name, a changed store or a moved store is refused; each row of the
    verb table, including a `name=path` store carrying `harness/` and `--add` of an installed name
    that reads nothing; a changed `module.json` or slot alone invalidates the approval;
    `--unapprove` and `--unregister` remove the approval; a hostile approvals file (each rejected
    form under Approval) is refused before any write but does not block `--remove`, `--list` or a
    store without `harness/`; a stale approval, one for the same path under another name, and a
    typed `name=path` with a different registered path authorise nothing; two registries in one
    directory keep separate approvals, and a `--registry` named like an approvals file is refused;
    `--register` on a registered store reprints the review with per-file hashes, escaped values and
    flags for names equal to a built-in unit; `--approve` and `--unapprove` with any option outside
    `--name`, `--registry`, `--dry-run` and `--global-config`, or with a target, are refused, and
    with `--dry-run` write nothing; a store whose digest differs from the manifest record but equals
    its approval is delivered by `--update`; a `harness/` entry that is a symlink or, in a format 1
    or 2 store, any entry is refused, and an empty `harness/` needs an approval.
11. Removal: sole supplier unedited, edited, missing; co-supplier; a path `base/` also ships; the
    `harness` key stays; no store or registry is read. An `--update` conflict on a recorded path
    keeps the old record and file, and a later `--remove` then deletes the file only if it still
    matches the record; a path dropped from a newer module version survives `--update` and is
    deleted by `--remove` when unedited.
12. Activation: `--add --harness` on a project that already has an external module installs
    nothing for it, says so, and a later approved `--update NAME` installs its files.
13. Read-only: a checksum of a store is identical before and after every command including
    `--dry-run`, and no program runs.
14. All existing tests still pass and a project without a harness is unchanged byte for byte.

### Acceptance criteria added by plan 0023

15. Base harness files (plan 0023): `--new --harness claude` installs the base files with the project id
    substituted, recorded with supplier `base`; none without a harness; activation installs them once;
    `--update` replaces an unedited base file and keeps an edited one; `--remove` never deletes or unrecords a
    `base` path; a record naming `base` loads and another unknown supplier does not; a `base` path equal to a
    `base/` or `files/` path is refused; `harness.json` in the base directory and a module named `base` are
    refused.
16. Ignore block: a recorded harness adds one `harness:claude` block to `.gitignore`; activation adds it once;
    `--update` restores an edited block and leaves other text alone; inexact or duplicated markers leave the
    file alone with a note; a symlinked or non-regular `.gitignore` is refused before any write.
17. Retired modules: `--with claude` and `--add claude` act as `--harness claude` with a note and are refused
    beside a different harness; `--list` shows none; `--remove claude` writes nothing; `--update` migrates a
    project created by the previous installer with `--with claude` and a second run changes nothing; a
    different recorded harness refuses the migration; an edited old gitignore block is left; the migration
    reads no path from the manifest.
18. A built-in `module.json` with a `harness` key is refused; `--list` shows no harness mark.

## Base harness files, the ignore block and retired modules

Added by plan 0023, which implements ADR 0004 decision 3 (the `"harness": true` flag is retired and the
`claude` module's entry-point files become the base harness directory).

**Base harness files.**

- `base/harness/<harness>/` has the layout, allowlist (the built-in column), path rules, limits, marker and
  frontmatter rules of a module's harness directory, except that `harness.json` is refused (only a module can
  declare roles). Its files are installed whenever a harness is recorded for that harness: by `--new`, by the
  activation of `--add --harness`, and refreshed by `--update`. They count toward the per-run limits.
- The supplier name is `base`. It is reserved: a built-in module or an external store named `base` is refused.
  In `harness_files`, `modules` may contain `base` without `base` being in `modules` or `external_modules`; the
  rest of the validation is unchanged, and `base` sorts with the other names.
- Collisions: a `base` path may not equal a `base/` path or any module's `files/` path (reserved paths), and
  two suppliers of one path must agree, as for modules. Existing project files follow the four collision
  rules, so an identical `CLAUDE.md` is adopted and recorded for `base`.
- `--update` refreshes `base` files under the update rules (the record is the baseline). `--remove` never
  deletes or unrecords a path whose record lists `base`, and removing the last module leaves them in place.
- Placeholders are the ordinary ones (`REPLACE_WITH_PROJECT_NAME`, `REPLACE_WITH_PROJECT_ID`), under the same
  project-name restriction as module harness files.

**The harness ignore block.** The harness table gains `gitignore`, a list of ignore lines (for `claude`:
`/.claude/settings.local.json`). When a harness is recorded, the project's `.gitignore` holds one block:

```text
# BEGIN harness:claude
/.claude/settings.local.json
# END harness:claude
```

- The block is added at the end when absent, by `--new`, by activation and by `--update`, and restored when its
  content differs; text outside the markers is never touched. If the markers are not exact lines, or appear
  more than once, the file is left alone and the run says so. The block is not a module block and the module
  block machinery ignores it. `--remove` leaves it.
- `.gitignore` goes through the ordinary write path: a symlinked or non-regular `.gitignore`, or a symlinked
  parent, is refused before any write; a missing `.gitignore` is created.

**Retired modules.** The installer holds a table of retired module names (`claude`, whose replacement is
`--harness claude`).

- `--with claude` and `--add claude` mean `--harness claude` and print that the module is retired; with a
  different `--harness` value the run is refused before any write. A retired name is not listed by `--list`,
  and is reserved for external stores.
- `--remove claude` is refused, naming the replacement, and writes nothing.
- `--update` migrates a project whose manifest lists a retired name, when the project has no harness or the
  retired name's harness: it drops the name from `modules`, `module_commits` and `module_info`, records the
  harness (`schema` 2), applies the base files under the collision rules (identical files adopted, differing
  files left and reported), and replaces the old `BEGIN module:claude slot:gitignore` block, when it still equals
  the module's old fragment text, by the harness ignore block (an edited old block is left and the new block is
  added). With a different recorded harness the migration is refused with a message. The migration names no
  path the manifest supplies, and a second `--update` changes nothing.

**The retired `harness` key.** A built-in `module.json` with a `harness` key is refused when the module loads,
naming `harness/<name>/` as the replacement. `--list` shows no harness mark.

**Neutrality.** A module named for its own tool (`codex`) may name that tool and its helper in its slots; every
other module's committed text stays tool-neutral. Harness files, which are installed only under a recorded
harness, are exempt from the scan as before.

## Open points from ADR 0004

| ADR point | Section |
|---|---|
| Harness root table; unknown harness name | The harness table |
| `root/` convention | Layout |
| Marker file location and format | The harness table; Declarations |
| Declaration syntax (helpers, workers, role mapping, global configuration) | Declarations; `harness.json` |
| Manifest shape (harness, co-suppliers, helpers, approvals) | Manifest; Approval |
| Format number and fail-closed signal | Manifest (schema 2); External stores (format 3) |
| Removal of unedited files | Manifest; Removal |
| Clauses of ADRs 0001 and 0003 amended | Amended clauses |
| `name=path` store carrying `harness/` | External stores, Approval |

## Review record

Recorded 2026-10-19 for plan "Harness file specification and trust addendum", Increment C.

### Codex review (`ask-codex review-spec`)

Model `gpt-5.6-luna`, high effort, 3 of 3 rounds used. It did not converge: round 3 still raised
three major findings. All were applied after round 3 and were not shown to Codex again. The owner
decides whether to extend the review. No finding was rejected.

| ID | Severity | Finding | Disposition |
|---|---|---|---|
| R1-F1 | blocker | `harness_files` keys only passed `safe_relpath`, so a forged manifest could aim removal at any project file | Applied: keys must be destinations of the recorded harness (Manifest) |
| R1-F2 | major | `approvals.json` had no read and validation rules | Applied (Approval) |
| R1-F3 | major | Approval checks named the harness tree, not the complete digest | Applied (When approval is required, verb table) |
| R1-F4 | major | `--update --harness` contradiction and a false claim that an interrupted `--new` reruns | Applied: command matrix; claim removed (Selection) |
| R1-F5 | major | `--unregister` conflicted with its existing meaning | Applied: `--unapprove` added, `--unregister` extended (Approval) |
| R2-F1 | major | Allowlist contradicted `harness.json` and `root/` | Applied: source-entry exceptions (The harness table) |
| R2-F2 | major | `--add --harness` versus the installed-name short circuit | Applied: activation does not read earlier external modules (Selection) |
| R2-F3 | major | Update conflict on a recorded path undefined | Applied: the record is the baseline (Collisions) |
| R2-F4 | minor | `expanduser` honours `HOME`; `--global-config` meaning | Applied (The harness table) |
| R3-F1 | major | Cross-run collisions inconsistent with "refuse the later supplier" | Applied (Collisions, External stores) |
| R3-F2 | major | Updating one co-supplier undefined | Applied: replaced only when all suppliers agree (Collisions) |
| R3-F3 | major | `--unregister` could leave a stale approval | Applied: approval removed first, whether or not registered (Approval) |

### Adversarial security pass (`security-reviewer`)

One pass, in scratch outside the repository, against the unmodified installer and the draft text; no
file in the reviewed tree changed. Observed current behaviour that the specification relies on, all
tested: a format 1 store with a `harness/` tree is accepted and the tree ignored with an unchanged
digest; format 3 and the new `module.json` keys are refused before any write; a schema 2 manifest
makes `--update`, `--add` and `--remove` exit 2 and write nothing, while a schema 1 manifest with
`harness` or `harness_files` is ignored and preserved; a registry entry with an extra key or an
extra top-level key is refused, and a separate approvals file is ignored, so old installers keep
working; the registry pins no digest today, so a store changed after `--register` is installed and
a full `--update` records the new digest silently; `other=<path registered as dup>` is accepted;
`delete_files` deletes any listed regular path without checking its content; `os.path.expanduser("~")`
honours `HOME`; `{"schema": true}` and `1.0` pass a naive `== 1`; a `files/` tree of a built-in
module can install `.claude/settings.json` and `.mcp.json`; a block marker inside a project file
makes `--remove` refuse; two paths differing only in case fail in `write_tree` with leftover empty
directories; a 1.15 MB manifest is refused by the next run.

| ID | Severity | Finding | Disposition |
|---|---|---|---|
| M1 | Medium | Allowlist is not a guarantee: skills, agents and commands can carry behaviour | Applied in part: wording softened, store files `.md` only, advisory phrases extended. Not applied: refusing frontmatter keys, because that depends on harness behaviour not verified here; the owner confirms it before approving a store |
| M2 | Medium | Identity shadowing by frontmatter `name` | Applied: `name` collisions, `name` must match the unit for stores, review prints names. The installer cannot see global names |
| M3 | Medium | `harness_files` keys let a forged manifest delete files | Applied: also covers R1-F1, plus casefold and NFC uniqueness |
| M4 | Medium | `--add --harness` versus the installed-name rule | Applied (same as R2-F2) |
| M5 | Medium | Approval semantics: stale entries, name aliases, lazy loading, file naming | Applied: name and path binding, lazy load, a file beside the registry (named `registry.json.approvals` after the second pass), option refusals, review reprint |
| M6 | Medium | Harness files could carry slot or block markers | Applied: forbidden strings, excluded from expansion and block scan |
| M7 | Medium | Built-in `files/` bypasses the allowlist | Applied as a clarification: built-in modules are trusted as template code; `files/` unchanged. The addendum no longer calls built-in trees untrusted. Not applied: extending the denylist to `files/` (out of scope, owner's call) |
| M8 | Medium | Case, Unicode and normalisation aliasing | Applied: casefold and NFC comparison, ASCII components for stores |
| M9 | Medium | `--update` never delivers a changed harness file | Applied: unedited files are replaced by recorded digest (Collisions) |
| L1 | Low | Marker read: `HOME`, boolean and float `schema`, growth after the size check, symlinked parent | Applied |
| L2 | Low | 10000 entries exceed the 1 MiB manifest limit | Applied: 4000 entries and a pre-write size check |
| L3 | Low | Interrupted-run claims | Applied: `--new` claim corrected; orphan files noted |
| L4 | Low | Conflict exit status | Applied in part: summary count added. Not applied: a distinct exit status, because `--update` keeps differing files with exit 0 today and a new code would make this the one exception |
| L5 | Low | "Never overwritten" is overclaimed | Applied: stated as the ADR 0002 write-path residual |
| L6 | Low | File mode | Applied: `0644 & ~umask` |
| L7 | Low | Resource limits | Applied: early-abort walk, per-directory and per-run caps |
| L8 | Low | Digest ordering ambiguity | Applied: ordering stated, fixture requirement |
| L9 | Low | Built-in validation blocking `--list` and `--remove` | Applied: lazy validation |
| L10 | Low | `--remove` ignoring `--harness` | Applied: refused |
| L11 | Low | Phrase list is bypassable | Applied: stated |
| L12 | Low | Schema 1 manifest with harness keys | Applied: refused, with an acceptance case |

Inconsistencies the pass reported: the ADR says the approval is "recorded in the registry" and that
`--update` refuses a changed store, and lists symlinks and size limits among the findings. The
specification states the refinements in its amended-clauses table, and ADR 0004's wording is the
owner's to amend on Acceptance. `root/` for stores was unclear and is now none. The manifest rule
for an empty `harness_files` and the installed-path comparison are now explicit.

Not exercised: the behaviour of Claude Code itself (frontmatter hooks, `!` commands, agent
precedence), a real home-directory marker, a symlinked `.claude` in a target, and concurrent swap
races. M1 and M2 rest on recalled harness behaviour. The text was revised after the pass.

### Second adversarial pass (`security-reviewer`, a fresh agent)

Told to bypass the revisions above. No Critical finding; 2 High, 8 Medium, 7 Low. It ran nine
scratch experiments against the unmodified installer and reasoned about the rest. Experiments
(tested): `write_tree` under umask 0 creates 0666 and keeps the mode of a replaced 4755 file; a
directory in the delete list fails in `check_write_paths` before any write; `load_manifest` accepts
a printable-ASCII `project_name` such as an instruction sentence; `is_text` accepts ESC, CR and BEL
where `isprintable` does not; 26 code points fold differently under `NFC(casefold(NFC(x)))` than
under `casefold(NFC(x))`; a registry named `x.approvals` collides with the derived name of `x`; a
relative home directory yields a relative marker path; a worst-case `harness_files` entry
serialises to 645 bytes; a case alias passes `lexists` and `same_store` on a case-insensitive
filesystem. Found sound (tested): malformed `project_name` is rejected for ESC and U+202E;
`same_store` treats a case alias as the same directory; a directory-valued record key fails before
any write. Found sound (by reading): approval binding per name, stale approvals, prefix-free digest
framing, single read for digest and install within one command, fail-closed schema 2,
`delete_files` not following symlinks, hardlinks surviving rename-replacement, helper detection
running nothing.

| ID | Severity | Finding | Disposition |
|---|---|---|---|
| H1 | High | The frontmatter `name` parse was unspecified, so a unit could be named one thing for the installer and another for the harness | Applied: an exact grammar for stores (Layout), acceptance cases for each hostile form. The grammar is a conservative subset; how the harness parses the same text is an assumption the owner confirms |
| H2 | High | Commands had no name rule; unit path shapes were loose | Applied: exact unit shapes, commands included, names flagged against built-in units |
| M1 | Medium | Review output could be overwritten by control characters in file text | Applied: controls other than LF refused in store files; values printed ASCII-escaped and capped |
| M2 | Medium | The manifest record is an unauthenticated delete and replace authority; a hostile `project_name` could inject text into an approved file | Applied: capability named as a residual; placeholders accepted only for names matching `[A-Za-z0-9._ -]{1,200}`; `--update` replaces only paths the module's tree names. Not applied: authenticating the manifest, which no installer feature does today |
| M3 | Medium | The mode promise was false against `write_tree` (umask, copied mode) | Applied: every harness write is created 0644 & ~umask without copying; the implementation plan changes `write_tree` for these paths |
| M4 | Medium | "Changed" had two baselines | Applied: changed means differs from the approval; the manifest digest is what `--update` delivers |
| M5 | Medium | An interrupted `--update` left a permanent conflict | Applied: identical bytes are adopted and the record's hash updated; acceptance case |
| M6 | Medium | `--approve` option matrix and `--dry-run` | Applied: explicit allowed options; `--dry-run` writes nothing |
| M7 | Medium | A relative or empty home directory made the marker relative | Applied: absolute required, otherwise missing |
| M8 | Medium | A worker could be reported implemented when nothing was installed | Applied: only declared roles whose mapped file is recorded after the run |
| L1 | Low | The 180-byte entry claim was wrong (645 worst case) | Applied: key length 256, 512 KiB serialised cap, claim removed |
| L2 | Low | Casefold and NFC order unspecified | Applied: `NFC(casefold(NFC(x)))` |
| L3 | Low | A directory-valued record key could wedge `--remove` | Applied: only regular files with a matching hash reach the delete step |
| L4 | Low | Approvals file naming collided for odd registry names | Applied: `<registry path>.approvals`; names ending `.approvals` refused |
| L5 | Low | "Does not exist" ignored aliases and non-regular entries | Applied: `lexists` after folding; non-regular is a conflict |
| L6 | Low | A store could change between listing and approval | Applied in part: per-file SHA-256 in the review; the race stays an accepted residual |
| L7 | Low | Smaller undefined points | Applied: extra files in a skill directory, `schema` 2 without `harness`, byte-identical claim narrowed, format 1/2 with `harness/` stated, empty or symlinked `harness/`, limits count `harness.json` and `root/`, `scandir` walk |

Not exercised in the second pass: Claude Code's own parsing and precedence (all assumptions), a
symlinked-ancestor marker read, a real passwd entry with a relative home, concurrent swaps, and
Windows aliases. The text was revised after this pass and has not been reviewed again; Codex's
bound is spent.
