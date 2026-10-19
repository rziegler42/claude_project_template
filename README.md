# Project template

A harness-agnostic template for new software, hardware, and engineering
projects. It is not a project itself: `install.py` assembles one from `base/`
plus the opt-in modules you choose, then starts a fresh git repository.

Requirements: a POSIX-compatible environment, Python 3.9+ (standard library
only), and git.

## Create a project

```sh
./install.py --list                                   # available modules
./install.py ../my-project --with cad-freecad,graphify \
    --git-name "Your Name" --git-email "id+user@users.noreply.github.com"
./install.py ../my-project --with cad --dry-run       # preview only
./install.py ../my-project --with cad-freecad graphify   # space-separated works too
./install.py ../my-project --with cad --harness claude   # also install modules' Claude files
```

- `--with`, `--add`, `--update` and `--remove` take several modules separated by
  spaces. `--with` also accepts commas. Put the target before `--with` (or end the
  list with `--`, as in `--with cad graphify -- ../my-project`), because `--with`
  reads every following value as a module.

- The project name is the target directory name unless `--name` is given.
- The target must not exist or be an empty directory, and must not be inside
  this repository.
- `git init` runs on branch `main` with **no remote and no commits**.
- **Git identity is explicit.** The new repository gets a local `user.name` and
  `user.email` from `--git-name`/`--git-email` (or an interactive prompt). It
  never silently inherits your global identity; `--use-global-git-identity`
  opts in and is reported. A non-noreply email produces a warning.
- Required modules are added automatically (`cad-freecad` pulls in `cad`).
- `/.debug/` is added to the new repository's `.git/info/exclude`.
- `REPLACE_WITH_PROJECT_NAME` is replaced by the project name (the target
  directory name, or `--name`). `REPLACE_WITH_PROJECT_ID` is the same name with
  every character outside `[A-Za-z0-9_-]` replaced by `-`; it must start with a
  letter or digit. The installer refuses a name that cannot form an id only
  when a selected file uses the id.
- The installer prints any `REPLACE_WITH_*` placeholders still to fill in and
  records the chosen modules in the tracked `.template-manifest`.
- `--harness NAME` also installs the harness files the chosen modules ship for that
  harness (see [Harness files](#harness-files)). Without it, a project gets only the
  neutral content.

## Add a module later

```sh
cd ../my-project
~/projects/claude_project_template/install.py --add graphify
```

`--add` works only on projects created by the installer (it needs
`.template-manifest`). It refuses to overwrite a file that differs, is
idempotent, and never commits. It refuses a project that contains symlinks
(including the project directory itself, `.template-manifest`, and any path it
would write through) or non-regular files, a malformed manifest, and any module
file under `.git/`. Name placeholders in a module's files are
filled from the project directory name (or `--name`).

## Update a project

```sh
cd ../my-project
~/projects/claude_project_template/install.py --update --dry-run   # preview
~/projects/claude_project_template/install.py --update             # all modules
~/projects/claude_project_template/install.py --update graphify    # one module
~/projects/claude_project_template/install.py --update my_kb=~/projects/my_kb
```

`--update` (alias `--upgrade`) brings a project created by the installer in line
with this checkout. It never commits.

- **Blocks** (`BEGIN/END module:<name> slot:<slot>`) are replaced with the module's
  current fragment, and a fragment with a marker but no block is inserted. Edit
  outside the blocks: an edit inside one is overwritten. Two exceptions: only files
  the template ships (`base/` and the modules' files) are touched, so your own files,
  such as completed plans, are never patched; and blocks already in
  `docs/plans/next.md` are kept as written, because you fill them in per plan.
  `--add` likewise inserts fragments only into files the template ships.
- **Module files** that are missing are written. A file that exists and differs is
  kept and reported, because the manifest records no baseline to tell your edits from
  an older template.
- `base/` files are not updated, and no module or orphaned block is removed. A file
  whose block markers are malformed or were rearranged by hand is left alone and
  reported.
- **Report.** Every file it leaves alone is listed with a reason: `kept` for a
  `base/` or module file that differs from the template (module blocks are ignored
  in the comparison), including a `docs/plans/next.md` in use, and `skipped` for a
  file you created that carries slot or block markers. The list is printed with
  `--dry-run` too, so you can see what differs before changing anything. For a
  `kept` file the line also says whether the template changed that file since the
  commit recorded in `.template-manifest` (`template changed since <commit>`, or
  `unchanged`), found by rebuilding the template as installed from this checkout's
  git history, or why that is not possible (`no merge base: ...`). The manifest
  also records the project name, the commit of modules added later with `--add`,
  and, for files `--update` left differing, the commit they were judged against.
- **`--merge`** (with `--update`, and with `--dry-run` to preview) carries the
  template's changes into those files. A `kept` file whose template text changed
  since install is handled by what is true of it: unmodified since install, it takes
  the new template text (`updated`); edited by you, the template's changes are merged
  three-way against the template as installed when your edits do not overlap theirs
  (`merged`); if they overlap, or the file has no merge base, it is left exactly as it
  is (`conflict` or `kept`). No conflict markers are ever written, and nothing is
  merged into files you created. `docs/plans/next.md` is replaced only while it is
  unmodified. A project that does not record its name needs `--name` with `--merge`.
  `--merge` cannot be limited to named modules. `--update` records the template commit
  only after a full run, so a run limited to named modules leaves the base in place.
- **External modules** are compared by the digest in `.template-manifest`. Without
  names, a registered store is looked up in the registry; one that is not registered
  or fails verification is skipped with a note. Name it by registered name or
  `name=path` to require it. The store is verified read-only, as for `--add`.
- The manifest's `template_commit` and `template_dirty` are refreshed when anything
  is written. `--skip-unsafe-entries` works as for `--add`.

## Remove a module

```sh
cd ../my-project
~/projects/claude_project_template/install.py --remove graphify --dry-run   # preview
~/projects/claude_project_template/install.py --remove graphify
~/projects/claude_project_template/install.py --remove cad-freecad cad my_kb
```

`--remove` takes installed modules (built-in, or an external one by its recorded name)
out of a project created by the installer. It never commits.

- **Blocks** of the module are stripped from every file, with the rest of the file and
  the `@module-slot:` marker lines untouched. A built-in module's block must still
  equal the module's fragment: an edited block, or a template that changed since you
  installed, stops the run with nothing written (run `--update`, or restore the block).
  An external module's blocks cannot be checked, since its store may be gone, so
  anything you wrote inside one goes with it.
- **Module files** are deleted only when the project's copy is identical to the
  module's file. One you edited, or that still carries another module's block, is kept
  and reported. `base/` files are never deleted, and a directory left empty is
  removed.
- A module that another installed module `requires` is refused unless you name that
  module too.
- If a file that holds the module's blocks has malformed or hand-rearranged markers, or
  would still hold them after the run (CRLF line endings, a binary file), the command
  stops and writes nothing, because dropping the module from the manifest would leave
  orphan blocks. With `--skip-unsafe-entries`, skipped files may still hold blocks and
  the run says so.
- An external module is removed from its recorded name alone; its store need not exist
  and the registry is not read or changed (`--unregister` is separate).
- Deletion opens each directory relative to its parent without following symlinks, so a
  path swapped for a symlink during the run is refused. Where the platform lacks that,
  files are kept and only blocks are stripped.
- `.template-manifest` drops the module and refreshes `template_commit` and
  `template_dirty`. `--dry-run` and `--skip-unsafe-entries` work as for `--update`.

## Use a standalone project as a module

A standalone project can ship a `template-module/` descriptor and be installed as
an external module. It contributes slot fragments only, never `files/`, and, from
`module_format` 3, harness files under approval (see
[Harness files in a store](#harness-files-in-a-store)). Name it by
path for one run, or register it once on this machine:

```sh
./install.py --register ~/projects/my_kb [--name my_kb] [--dry-run]
./install.py --list                                   # built-in modules, then registered stores
./install.py ../my-project --with graphify,my_kb      # registered name
./install.py ../my-project --with scratch=~/projects/my_kb   # name=path, no registration
~/projects/claude_project_template/install.py --add my_kb     # in an existing project
./install.py --unregister my_kb
```

- The registered name defaults to the store's directory name (`--name` overrides)
  and must match `[a-z0-9][a-z0-9_-]*`. It never equals a built-in module name.
  A name maps to one path and a path to one name.
- The registry is `registry.json` under `$XDG_CONFIG_HOME/claude-project-template/`
  (`~/.config/claude-project-template/` when unset). It is machine-local, read
  only when a command needs it, and never repaired by the installer.
- The store is verified read-only on every use (no symlinked store, no `.git`
  component, no program or `git` command run in it). The path is not recorded in
  the project; `.template-manifest` keeps the module's format and a SHA-256 digest
  of its descriptor under `external_modules`.
- External modules install after the built-in ones. `--add` of a name already in
  the manifest reports it as installed and reads nothing.
- `--unregister` removes the registry entry and the store's approval, if any. Projects keep their blocks.

The descriptor format, rules, and trust model are in
`docs/specs/external-modules.md`, `docs/decisions/0002-installer-trust-model.md`,
and `docs/decisions/0003-external-module-mechanism.md`.

### Writing an external module

A store contains `template-module/module.json` and `template-module/slots/<slot>.md`:

```json
{ "module_format": 1, "description": "One line, 1-200 characters", "hint": "optional next step" }
```

- `module_format` must be 1, 2 or 3. There is no `name`, `order`, `requires` or
  `harness` key; unknown keys are errors. Format 2 additionally allows the optional
  `type`, `paths` and `data` keys described under "Module info"; format 1 rejects
  them. A store that uses them needs an installer that knows format 2: an older one
  refuses it, with an "unknown module.json keys" or "module_format 2 is not
  supported" error, and writes nothing.
- Each fragment is named for a slot in the table below, is UTF-8 text of at most
  64 KiB, and at most 16 are allowed. It must not contain `@module-slot:`,
  `BEGIN module:` or `END module:`, and its text must be tool-neutral.
- `REPLACE_WITH_MODULE_NAME` and `REPLACE_WITH_MODULE_PATH` are filled in. The path
  is specific to one checkout, so a fragment that uses it should say so.

### Harness files in a store

A `module_format` 3 store may ship `template-module/harness/claude/` with skills, agents and
commands, and may declare `helpers`, `workers` and `global_config` like a built-in module.
Skills, agents and commands are instructions the harness loads on its own, so they install
only after you approve exactly what they are:

```sh
./install.py --register ~/projects/my_kb          # lists every file, its SHA-256, each unit's name,
                                                  # description and tools, findings, and the digest
./install.py --approve <digest> --name my_kb      # after you have read those files
./install.py ../my-project --with my_kb --harness claude
./install.py --unapprove my_kb                    # or --unregister my_kb, which also removes it
```

- Shape: `skills/<name>/SKILL.md` (other `.md` files may sit beside it), `agents/<name>.md`
  and `commands/<name>.md`, each with plain `---` frontmatter whose `name` equals `<name>`.
  Only ASCII path components, `.md` files, UTF-8 text without control characters, at most 128
  files, 256 KiB per file and 2 MiB per store. A store has no `CLAUDE.md`, `settings`, hooks,
  MCP configuration or scripts; anything else is refused when the store is registered.
- The digest covers `module.json`, every fragment and every harness file as stored. Approval
  is recorded in `registry.json.approvals`, beside the registry, bound to the store's real path
  and that digest. `--new` and `--add` refuse a store whose harness files are not approved or
  whose digest changed since. A named `--update` refuses it; a full `--update` skips it with a
  note and leaves what it installed. `--remove` needs no approval and reads no store.
- The installer runs no model, no program from a store and no network call. The findings in the
  listing (executable files, phrases such as `ignore previous` or `curl `) are advisory and
  easily bypassed: read the files yourself. Approval guards new installs only; files already
  copied into a project do not change when the store does.
- Placeholders in a harness file (`REPLACE_WITH_PROJECT_NAME`, `REPLACE_WITH_PROJECT_ID`,
  `REPLACE_WITH_MODULE_NAME`, `REPLACE_WITH_MODULE_PATH`) are filled in one pass, and a project
  name or store path with unusual characters is refused rather than written into an approved file.
- Two stores shipping the same skill install it once when identical; when they differ the run
  fails if both are in it, otherwise the later store's unit is reported as a conflict and skipped.
  An installer from before this version refuses a project that records a format 3 store.

The rules are in [the specification](docs/specs/module-harness-files.md).

## Security notes

The installer treats everything in a project under `--add`, every command-line
value, forked modules, and the caller's git environment as untrusted data. It
writes only inside the target (or project) directory and its
`.git/info/exclude`. See `docs/decisions/0002-installer-trust-model.md` for
the trust model, mitigations, and accepted residuals. In practice:

- `--add` refuses a project containing symlinks or non-regular files outside
  `.git` (a `.venv` or `node_modules/.bin` will trigger this) and files over
  16 MiB. Pass `--skip-unsafe-entries` to skip and list them instead; skipped
  entries are never read, patched, or written through, and every write-time
  check still applies.
- `git` subprocesses ignore `GIT_*` variables, configured helper programs,
  and template directories; new repositories have no sample hooks.
- Review a forked or edited module before using it; its files and slots are
  copied into your project.

## Layout

- `base/` — files every project receives (instructions, docs skeleton,
  plan/roadmap/spec/decision conventions).
- `modules/<name>/` — opt-in content:
  - `module.json` — `description`, `requires`, `order`, and optional `hint` (one printable line, at most 200 characters) that the
    installer prints under "Next steps" after a new install or `--add`, and
    optional `type`, `paths` and `data` (see [Module info](#module-info)), and
    optional `helpers`, `workers` and `global_config` (see
    [Declared dependencies](#declared-dependencies)).
  - `files/` — copied verbatim to the same relative path.
  - `harness/<harness>/` — files for one harness (`claude`), installed into that
    harness's directory only when a project records the harness (see
    [Harness files](#harness-files)).
  - `slots/<slot>.md` — fragments inserted at `@module-slot: <slot>` marker
    lines in `base/` files or other modules' files, wrapped in
    `BEGIN/END module:<name> slot:<slot>` markers.
- `LICENSE` — this repository's license. It is never copied; each project
  chooses its own.
- `docs/` — this repository's own decisions and plans (not shipped).
- `tests/` — `python3 -I -m unittest discover -s tests`; the `tests` profile in
  `.claude/remote-runner.toml` runs the same suite on a Linux runner.

## Modules

| Module | Purpose |
|---|---|
| `graphify` | Graphify discovery/impact policy, `.graphifyignore`, plan evidence section, and the `tools/graphify` workflow tool; with `--harness claude`, also the `graphify-workflow` skill and the `graphify-semantic` agent |
| `plan-review` | Tool-neutral policy for an independent, bounded, read-only review of the plan, and a Second opinion receipt in the plan and its archive |
| `codex` | Codex plan review through the `ask-codex` helper: request, limits, owner-only commands, state, and mapping to the plan's receipt; with `--harness claude`, also the `second-opinion` skill; requires `plan-review` |
| `formal` | Tool-neutral formal verification guidance; with `--harness claude`, also the `verilog-sby-formal` skill |
| `cad` | Tool-neutral CAD workflow (`docs/cad.md`) |
| `cad-freecad` | FreeCAD conventions; requires `cad`; with `--harness claude`, also the `freecad-scripts` skill |

## Module info

A built-in module may declare, in `module.json`, what it is and where its files live,
so a skill or another module can find it from one file:

- `type`: a lowercase name for the kind of module (`knowledge-base`), at most 64
  characters. Two modules may share a type.
- `paths`: up to 16 roles, each mapped to a safe project-relative path
  (`{"store": "docs/kb"}`).
- `data`: a small JSON object of other module-specific values: plain JSON, at most
  4 levels deep, 256 values and 4096 bytes, with short printable strings.

All three are optional. The installer copies what a module declares into
`.template-manifest` as `module_info` (`{module: {type, paths, data}}`), one entry per
installed module that declares anything. `--new` and `--add` record entries, `--remove`
drops them, and a full `--update` rebuilds them from the current template (an entry for
a module the template no longer provides is kept). A run limited to named modules
leaves them alone. A module that declares nothing has no entry, and a project with no
declaring module has no `module_info` key.

An external module (a standalone project used as a module) may declare `type`,
`paths` and `data` in its `module.json` when it uses `module_format` 2. Every
external module has an entry, format 1 included, because the entry also records
`store`: where the store lives, as the user gave it. `store` is `../name` when the
store is a sibling of the project, otherwise the absolute path, and no other form is
accepted. A full `--update` re-verifies each registered store and rewrites its entry
even when the descriptor is unchanged, so a moved store or an older manifest is
corrected; a store it cannot verify keeps its entry. An absolute `store` is specific
to one machine, so prefer keeping the project and the store side by side. An installer
from before external entries refuses a project whose manifest has them (it fails closed
with a "malformed" error and writes nothing), so update the template checkout before
running it on such a project.

```json
"module_info": { "my_kb": { "store": "../my_kb", "type": "knowledge-base",
                            "paths": { "index": "docs/kb/index.md" } } }
```

For readers of the manifest: a missing entry means "not declared", and projects
installed before this key existed have none until their next full `--update`.
Treat the values as untrusted data, as with the rest of the manifest: resolve each
path against the project root, check with `realpath` that it stays inside, and do not
follow a symlink out of the project. A path may name any file in the project.
Resolve a relative `store` against the project root too, and expect the store to be
missing: treat that as "not available", not an error. For a built-in module the
values come from the template, so they are the same in every project; the only
location chosen at install time is an external module's `store`.

## Writing a module

1. Create `modules/<name>/` (lowercase letters, digits, hyphens).
2. Add `module.json`; use `requires` for modules it builds on and `order` to
   control insertion order (lower first).
3. Put whole files under `files/` and fragments under `slots/`. A fragment for
   a slot with no marker anywhere is an error.
4. Keep committed content neutral: name capabilities and policy, never a
   private helper or skill. Harness-specific content goes in
   `harness/<harness>/`. A module named for a tool, such as `codex`, may name
   that tool and its helper, but never a harness skill, slash command or harness;
   it requires the neutral module that holds the policy. The `"harness"` key in
   `module.json` is retired and refused.
5. Skills, agents and commands that serve the module go under
   `harness/<harness>/`, not in `files/` (see [Harness files](#harness-files)).
6. Run the tests; add a case if the module introduces new behavior.

Slots available in `base/` (a fragment's file name is the slot name):

| Slot | File | Position |
|---|---|---|
| `agents-guidance` | `AGENTS.md` | end of the working agreement |
| `docs-index` | `docs/README.md` | documentation index list |
| `readme-docs` | `README.md` | documentation links |
| `development-tools` | `docs/development.md` | tool-specific guidance |
| `plan-discovery` | `docs/plans/next.md` | before "Completion criteria" |
| `plan-review` | `docs/plans/next.md` | before "Deferred work" |
| `plans-review-note` | `docs/plans/README.md` | after the archive-format notes |
| `gitignore` | `.gitignore` | end of the file |

A slot marker added to `base/` is present only in projects created after it
was added. `--add` for a module whose fragment needs a newer marker fails
with "fragments with no matching slot marker" on an older project; the fix
is to add the marker line by hand or create the project again.

## Harness files

A built-in module may ship the files that serve it for one coding harness, such as
Claude Code skills and agents, instead of leaving them in a developer's global
configuration. They live in `modules/<name>/harness/<harness>/`; the installer owns the
table of harnesses, which has one entry, `claude` (root `.claude/`). The template's own
harness files, `CLAUDE.md` (importing `AGENTS.md`) and the `.claude/remote-runner.toml`
stub with the project id, live in `base/harness/claude/` and install with every
`--harness claude` project, recorded with the supplier `base`; `--harness claude` also
adds a `# BEGIN harness:claude` block to `.gitignore` for `/.claude/settings.local.json`.
The former `claude` module is retired: `--with claude` and `--add claude` act as
`--harness claude` with a note, `--remove claude` is refused, and a full `--update` of a
project that lists it migrates the project to the harness record.

```text
modules/<name>/harness/claude/
  skills/<skill>/SKILL.md      -> .claude/skills/<skill>/SKILL.md
  agents/<agent>.md            -> .claude/agents/<agent>.md
  commands/<command>.md        -> .claude/commands/<command>.md
  remote-runner.toml           -> .claude/remote-runner.toml
  root/CLAUDE.md               -> CLAUDE.md   (root-level entry points only)
  harness.json                 (optional; checked, never installed)
```

- A project has at most one harness. `--harness NAME` on a new project records it;
  `--add --harness NAME` records it once on a project that has none and installs the
  files of every installed built-in module; a different name than the recorded one is
  refused, `--update --harness` accepts only the recorded name, and `--update` never
  introduces a harness. Switching harness means creating a new project.
- A file that already exists with identical bytes is adopted; one that differs is never
  overwritten and is reported as a `conflict`, and a skill directory with any
  conflicting file is skipped whole. `--update` replaces a file you have not edited
  (judged by the SHA-256 the manifest records) and keeps one you edited; it never
  deletes. `--remove` deletes the unedited files a module alone supplied and keeps the
  rest. Installed files are created `0644 & ~umask`, never executable.
- A harness tree is checked before anything is written: only `skills/`, `agents/`,
  `commands/` and `remote-runner.toml` (plus `root/CLAUDE.md` and `harness.json`) are
  allowed, so settings, hooks and MCP files cannot be shipped; no symlinks, special
  files, `.git`, case or Unicode aliases, slot or block markers, or binary files; at most
  128 files, 256 KiB per file and 2 MiB per module, and 512 files and 8 MiB per run.
  A skill, agent or command is identified by its frontmatter `name`, and two units with
  the same name conflict. A module with nothing for the project's harness installs its
  neutral part and says so.
- The manifest of a project that records a harness has `schema` 2, `harness`, and
  `harness_files` (each installed path with its SHA-256 and supplying modules); other
  projects keep `schema` 1 and are unchanged. An installer from before this feature
  refuses a `schema` 2 manifest (it fails closed with a "malformed" error and writes
  nothing), so update the template checkout before running it on such a project.
- Four modules ship harness files so far. With `--harness claude`, `codex` installs the
  `second-opinion` skill, `cad-freecad` installs
  the `freecad-scripts` skill (a `SKILL.md`, ten references and a mesh script) into
  `.claude/skills/freecad-scripts/`, `formal` installs the `verilog-sby-formal` skill
  (`SKILL.md` and `reference.md`) into `.claude/skills/verilog-sby-formal/`, and `graphify`
  installs the `graphify-workflow` skill and the `graphify-semantic` agent (see
  [Graphify tooling](#graphify-tooling)). For a project that already has one of them,
  `install.py --add <module> --harness claude --dir <project>` records the harness and
  installs the files. A registered external store may ship harness files too, after you approve
  them (see [Harness files in a store](#harness-files-in-a-store)). The decision is
  [ADR 0004](docs/decisions/0004-harness-files-in-modules.md) and the rules are in
  [the specification](docs/specs/module-harness-files.md).

## Graphify tooling

The `graphify` module ships a stdlib-only workflow tool in the project, run with `python3`
(installed files do not keep an executable bit):

```sh
python3 tools/graphify/workflow.py status            # graph freshness
python3 tools/graphify/workflow.py doctor            # workflow state and one safe next action
python3 tools/graphify/workflow.py query "..."       # also path, explain, affected, god-nodes, diagnose, benchmark
python3 tools/graphify/workflow.py refresh-code      # explicit code-only update
python3 tools/graphify/workflow.py prepare           # semantic refresh: prepare, extract, validate-chunk, finalize
```

Every command takes `--root DIR` (default: the current directory) and prints one JSON line. The
queries go through the `graphify` executable on a trusted `PATH` (an absolute directory outside the
repository), which the tool never replaces or installs, and the refresh scripts and the chunk
contract live beside it in `tools/graphify/` (`refresh.md` is the neutral procedure).

- **Nothing refreshes the graph on its own.** There is no git hook and nothing runs after a commit.
  `doctor` reports `stale_code` or `stale_semantic` and the one safe next action; `refresh-code` is
  the explicit code-only update, and changed documents need the `prepare` and `finalize` procedure.
- **State** lives under the ignored `graphify-out/`, in `.workflow_*` files. A graph built by the
  older global helper has `.claude_*` state files, which are ignored: it reads as `present` (stale)
  once and a refresh rebuilds it.
- **It is project code.** A cloned project could carry a modified copy, so run it only in a project you
  have reviewed; `install.py --update` reports an edited copy as kept but cannot detect one in a fresh
  clone. The tool runs git with the repository's own `core.fsmonitor`, hooks path and similar settings
  overridden, scrubs inherited `GIT_*` variables, and refuses to run when the repository's git config
  defines programs git may run (filter drivers, `core.sshCommand`, includes and the like; it names the
  settings, never their values) unless you pass `--allow-repo-programs` after reviewing them.
- With `--harness claude` the module also installs the `graphify-workflow` skill and the
  `graphify-semantic` agent, and declares the `graphify` helper, the `graphify-chunk-extractor`
  worker role and a dependency on the harness's global configuration (the agent's write guard is a
  hook from there). Claude Code runs a project agent's frontmatter hooks only after the workspace
  trust dialog is accepted, so a semantic refresh needs a trusted workspace. For an existing
  project, `install.py --add graphify --harness claude --dir <project>` installs them.

## Declared dependencies

A built-in module's harness files may rely on things the installer never installs: a
helper program, a worker role a harness must supply, and the harness's global
configuration. The module says so in `module.json`, and `--new`, `--add` and `--update`
report each item without ever installing, running or failing on one (the exit status is
unchanged):

```json
{ "helpers": ["ask-codex"],
  "workers": { "chunk-extractor": "reads the listed files, writes one named chunk" },
  "global_config": true }
```

- `helpers`: at most 16 unique names (letters, digits, `.`, `_`, `-`, at most 64
  characters). A helper is `present` when a regular file of that name is executable and
  sits in an absolute `PATH` directory, and `missing` otherwise; it is never run. It is
  reported with or without a harness.
- `workers`: at most 16 role ids (`[a-z][a-z0-9-]*`) each with a one-line contract of 1 to
  200 characters. With a harness, the module's `harness.json` maps a role to the file that
  implements it; a role is `implemented` only when that file was installed for the module
  in this run (or earlier), and otherwise reports a warning with the contract; under
  `--dry-run` it says `would be implemented`. Without a harness the line says no harness is
  selected.
- `global_config`: `true` when the files need the harness's global configuration. The
  installer reports `present` when the harness's marker file is valid JSON with
  `"schema": 1`, `missing` when it is absent, and `missing (unreadable or invalid marker)`
  for anything else, never echoing its contents. For `claude` the marker is
  `~/.claude/global-config.json` in the account's home from the password database (not
  `$HOME`); `--global-config DIR` reads `DIR/global-config.json` instead. A symlinked
  marker, a file over 4 KiB, or an empty or relative directory is not accepted.

The lines appear under "Declared dependencies" for the modules in the run: the new
modules for `--new` and `--add` (every installed built-in module when `--add --harness`
activates a harness), and the updated modules for `--update`. An `--add` that finds
everything installed prints "Nothing to add" and no lines. The `graphify` module declares all three.

## Boundaries

Committed content names capabilities and policy, never a specific helper or
skill. Harness-specific skills, agents, and helpers belong to each developer's
own harness configuration, or in a module's `harness/<harness>/` directory (see
[Harness files](#harness-files)); everything outside those directories stays
tool-neutral. Policy that appears in both a project's
`AGENTS.md` and a developer's global instructions (no commit or push without
approval, no AI attribution, plan location) is intentionally duplicated so
other harnesses follow it; keep the two consistent when either changes.
