# Project template

A harness-agnostic template for new software, hardware, and engineering
projects. It is not a project itself: `install.py` assembles one from `base/`
plus the opt-in modules you choose, then starts a fresh git repository.

Requirements: Python 3.9+ (standard library only) and git. macOS and Linux
(Windows via WSL).

## Create a project

```sh
./install.py --list                                   # available modules
./install.py ../my-project --with cad-freecad,graphify \
    --git-name "Your Name" --git-email "id+user@users.noreply.github.com"
./install.py ../my-project --with cad --dry-run       # preview only
```

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
- `tests/` — `python3 -I -m unittest discover -s tests`.

## Modules

| Module | Purpose |
|---|---|
| `claude` | Claude Code entry point (`CLAUDE.md` importing `AGENTS.md`), local-settings ignore line, and a `.claude/remote-runner.toml` stub with the project id and no active profile (harness) |
| `graphify` | Graphify discovery/impact policy, `.graphifyignore`, plan evidence section |
| `plan-review` | Tool-neutral policy for an independent, bounded, read-only review of the plan, and a Second opinion receipt in the plan and its archive |
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
   harness-specific.
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
