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
an external module. It contributes slot fragments only, never files. Name it by
path for one run, or register it once on this machine:

```sh
./install.py --register ~/projects/my_kb [--name my_kb] [--dry-run]
./install.py --list                                   # built-in modules, then registered stores
./install.py ../my-project --with claude,my_kb        # registered name
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
- `--unregister` removes only the registry entry. Projects keep their blocks.

The descriptor format, rules, and trust model are in
`docs/specs/external-modules.md`, `docs/decisions/0002-installer-trust-model.md`,
and `docs/decisions/0003-external-module-mechanism.md`.

### Writing an external module

A store contains `template-module/module.json` and `template-module/slots/<slot>.md`:

```json
{ "module_format": 1, "description": "One line, 1-200 characters", "hint": "optional next step" }
```

- `module_format` must be 1. There is no `name`, `order`, `requires` or `harness`
  key; unknown keys are errors.
- Each fragment is named for a slot in the table below, is UTF-8 text of at most
  64 KiB, and at most 16 are allowed. It must not contain `@module-slot:`,
  `BEGIN module:` or `END module:`, and its text must be tool-neutral.
- `REPLACE_WITH_MODULE_NAME` and `REPLACE_WITH_MODULE_PATH` are filled in. The path
  is specific to one checkout, so a fragment that uses it should say so.

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
  - `module.json` — `description`, `requires`, `order`, optional `harness`,
    and optional `hint` (one printable line, at most 200 characters) that the
    installer prints under "Next steps" after a new install or `--add`.
  - `files/` — copied verbatim to the same relative path.
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
| `claude` | Claude Code entry point (`CLAUDE.md` importing `AGENTS.md`), local-settings ignore line, and a `.claude/remote-runner.toml` stub with the project id and no active profile (harness) |
| `graphify` | Graphify discovery/impact policy, `.graphifyignore`, plan evidence section |
| `plan-review` | Tool-neutral policy for an independent, bounded, read-only review of the plan, and a Second opinion receipt in the plan and its archive |
| `codex` | Codex plan review through the `ask-codex` helper and `second-opinion` skill: request, limits, owner-only commands, state, and mapping to the plan's receipt; requires `plan-review` (harness) |
| `formal` | Tool-neutral formal verification guidance |
| `cad` | Tool-neutral CAD workflow (`docs/cad.md`) |
| `cad-freecad` | FreeCAD conventions; requires `cad` |

## Writing a module

1. Create `modules/<name>/` (lowercase letters, digits, hyphens).
2. Add `module.json`; use `requires` for modules it builds on and `order` to
   control insertion order (lower first).
3. Put whole files under `files/` and fragments under `slots/`. A fragment for
   a slot with no marker anywhere is an error.
4. Keep committed content neutral: name capabilities and policy, never a
   private helper or skill. Only modules marked `"harness": true` may be
   harness-specific or name a Claude-owned helper or skill; a module bound to
   one tool, such as `codex`, is marked this way and requires the neutral
   module that holds the policy.
5. Run the tests; add a case if the module introduces new behavior.

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

## Boundaries

Committed content names capabilities and policy, never a specific helper or
skill. Harness-specific skills, agents, and helpers belong to each developer's
own harness configuration. Policy that appears in both a project's
`AGENTS.md` and a developer's global instructions (no commit or push without
approval, no AI attribution, plan location) is intentionally duplicated so
other harnesses follow it; keep the two consistent when either changes.
