# Next plan

Status: Approved
Created: 2026-10-18

## Goal

`install.py` keeps a machine-local registry of standalone projects so a registered
name works anywhere a built-in module name does (`--with my_kb`, `--add my_kb`),
and `--register`, `--unregister`, and `--list` manage and show it. This is
candidate 2 of [roadmap external-modules](../roadmaps/external-modules.md),
implementing the Registry section of the approved
[external-modules spec](../specs/external-modules.md) on top of plan
[0006](0006-external-module-core.md).

## Scope

- The registry file: location, schema, validation, atomic writes.
- `--register PATH [--name N] [--dry-run]`, `--unregister NAME`, `--registry FILE`.
- `--list` showing registered stores with `ok`, `missing`, or `invalid: <reason>`.
- Bare registered names in `--with` and `--add`, the registered-name collision rule
  for `name=path`, lazy registry loading, and re-verification at every use.
- Tests in `tests/test_install.py`, and the `--register`, `--unregister`,
  `--registry`, and `--name` help text.

## Non-goals

- Descriptor, manifest, or `name=path` changes (plan 0006 is final).
- The adversarial trust-model review, ADR 0002 addendum, and mechanism ADR
  (candidate 3), the store-side contract (candidate 4), and README prose
  (candidate 5).
- Refresh on drift, locking or concurrent-writer protection (last writer wins,
  an accepted residual in the spec), registry migration tooling, and
  `--unregister --all`.

## Assumptions and constraints

- The spec governs; spec sections: Names, Registry, Syntax, Verification,
  Acceptance criteria 1, 5, 6, 7.
- `install.py` stays one stdlib-only file, Python 3.9+; no subprocess touches a store
  or the registry.
- Registry file (spec): `registry.json` under `$XDG_CONFIG_HOME/claude-project-template/`
  when that variable is set and absolute, else `~/.config/claude-project-template/`;
  `--registry FILE` overrides. Content `{"schema": 1, "stores": {"<name>": {"path":
  "<absolute printable single-line path>"}}}`, at most 1 MiB; names match
  `EXT_NAME_RE`; unknown top-level keys, a wrong schema, or a malformed entry make
  the registry malformed.
- `--name` already means "project name" for a new project; with `--register` it
  means the registered name. Exactly one mode flag among `--list`, `--add`,
  `--register`, `--unregister`, or a positional target is allowed.
- Implementation choices the spec leaves open:
  - `read_external(name, value, target, builtin)` accepts `target=None`, which skips
    the target-containment check and returns the store's real path in place of
    the `../` text; `--register` and `--list` use that.
  - Registry values are re-verified through `load_external` at every use, so the
    registry is never trusted for content.
  - A built-in name always wins as a bare name and is never looked up in the
    registry; `--list` marks a registry entry whose name has since become a
    built-in as `invalid: shadowed by a built-in module`.
  - The registry directory is created with mode 0700; the file is written through
    a temporary sibling and `os.replace`.
  - A bare name that is neither built-in nor registered keeps the existing
    "unknown module" error, with the registered names added to the available list.

## Discovery and impact evidence

Graphify: skipped — the affected paths are fully enumerated: `install.py` and
`tests/test_install.py`. Verified against current source (commit `7307ab9`):
`parse_entries`, `load_external` / `read_external`, `load_externals`, `resolve`,
`cmd_new`, `cmd_add`, `cmd_list`, `build_parser`, `main`, `refuse_symlink`,
`read_regular`, and `ExternalModuleTest`. `cmd_new` and `cmd_add` already merge
externals into the `modules` mapping before `resolve`, so a registry lookup only
has to produce `(name, path)` entries ahead of `load_externals`.

## Completion criteria

- `python3 -I -m unittest discover -s tests` passes with the new tests, and
  `git diff --check` is clean.
- Spec acceptance criteria 1 (registered-name collision cases), 5, 6, and 7 hold.
- A run that names only built-in modules never opens the registry, even a malformed
  one; its output is unchanged.
- A checksum of a fixture store (dotfiles included) is identical before and after
  every command, including `--dry-run`.

## Increments

### Increment A — registry file

Dependencies: None
Affected areas: `install.py`, `tests/test_install.py`

Interfaces produced:

- `REGISTRY_SCHEMA = 1`, `MAX_REGISTRY_BYTES = 1024 * 1024`.
- `registry_path(override: str = None) -> str`: the override, else the XDG location
  per the assumptions; reads `os.environ`.
- `load_registry(path: str, builtin: set) -> dict`: name → real path string; a
  missing file is `{}`; refuses a symlinked file or directory, a non-regular file,
  size over the cap, bad JSON, wrong schema, unknown keys, a bad name, a
  non-absolute or non-printable path. Messages name the file, never its content.
- `save_registry(path: str, stores: dict) -> None`: creates the directory (0700),
  refuses a symlinked directory or file, writes a temporary sibling and replaces.

Steps:

1. Tests first (a `RegistryTest` class with its own scratch directory and a
   `--registry`-style explicit path):
   - `test_registry_path_default_and_xdg`: with `XDG_CONFIG_HOME` unset the path is
     `~/.config/claude-project-template/registry.json`; set and absolute it is used;
     set but relative it is ignored; an override wins.
   - `test_load_missing_is_empty` and `test_save_then_load_round_trips` (the file
     reads back as `{"schema": 1, "stores": {...}}`, directory mode 0700).
   - Refusals, one subTest each: invalid JSON; not an object; `schema` 2 or `true`;
     unknown top-level key; `stores` not an object; bad name (`Bad`, `kb\n`); entry
     not an object; relative path; multi-line path; file over 1 MiB; registry file
     or its directory a symlink; registry path a FIFO.
   - `test_save_does_not_follow_symlink`: a symlinked target file stays untouched.
2. Implement the three functions with `read_regular` for the read and the temporary
   sibling pattern of `write_tree` for the write.
3. Run the new tests, then the whole suite.

Completion: new tests pass and failed before the code; whole suite passes.

### Increment B — `--register` and `--unregister`

Dependencies: Increment A
Affected areas: `install.py`, `tests/test_install.py`

Interfaces produced: `cmd_register(args, out) -> int`, `cmd_unregister(args, out) ->
int`; parser options `--register PATH`, `--unregister NAME`, `--registry FILE`;
`main` mode exclusivity; `read_external(..., target=None)` as described.

Steps:

1. Tests first (call `run(["--register", store, "--registry", reg])`):
   - `test_register_defaults_name_to_directory_name`: entry `my_kb` with the real
     path; output shows name, path, and description; exit 0.
   - `test_register_name_override`, `test_register_expands_tilde_and_relative`.
   - `test_register_same_name_same_path_is_noop`, and refusals that leave the registry
     bytes unchanged: same name at a different path (message names the existing entry
     and says to unregister first); same path under another name; a built-in name
     (`--name cad`); a directory name that fails `EXT_NAME_RE` (message says to pass
     `--name`, nothing is transformed); a store that fails verification (symlinked,
     no descriptor, bad `module.json`); a store inside the template.
   - `test_register_dry_run_writes_nothing`.
   - `test_unregister_removes_entry_only`: the store tree hash and an existing
     project are unchanged; works when the store path no longer exists; reads nothing
     from the store.
   - `test_unregister_unknown_name_succeeds` ("not registered", exit 0);
     `test_unregister_builtin_name_refused`.
   - `test_mode_flags_are_exclusive`: `--register` with a positional target, `--with`,
     `--list`, or `--add` exits 2.
   - `test_register_read_only`: store tree hash (dotfiles included) unchanged.
2. Implement. `cmd_register` resolves the path (`~`, relative, `realpath`),
   verifies through `load_external(name, path, None, builtin)` (discarding the
   result), then edits the registry; the final path component must not be a symlink.
   `--name` doubles as the registered name. `cmd_unregister` loads the registry and
   deletes the key; it never touches the filesystem path it held.
3. Run the whole suite.

Completion: new tests pass; every pre-existing test passes unmodified.

### Increment C — `--list`, bare names, and collisions

Dependencies: Increment B
Affected areas: `install.py`, `tests/test_install.py`

Interfaces produced: `registry_entries(args, names, builtin) -> list` mapping the bare
non-built-in names to `(name, registered path)` entries, loading the registry only
when `names` is non-empty; `cmd_list` extension.

Steps:

1. Tests first:
   - `test_list_shows_registered_stores_with_status`: after the built-in lines, a
     "Registered stores:" section with `ok`, `missing` (path deleted),
     `invalid: <reason>` (descriptor broken, or symlinked), and
     `invalid: shadowed by a built-in module`; re-verified on every listing; listing
     with no registry prints only the built-ins (output byte-identical to today).
   - `test_with_registered_name_matches_typed_path`: `--with my_kb` and
     `--with my_kb=<same path>` produce identical `AGENTS.md` and manifest.
   - `test_add_registered_name`, and `test_add_recorded_name_does_not_open_registry`
     (a malformed registry does not matter for an already recorded name).
   - `test_two_registered_stores_in_one_project`.
   - `test_registered_name_with_different_typed_path_refused`; same typed path
     accepted.
   - `test_builtin_only_run_never_opens_registry`: a malformed registry (and a
     missing parent directory) does not affect `--with claude,graphify`.
   - `test_unknown_name_error_lists_registered_names`.
   - `test_registered_path_is_reverified_at_use`: after the store's descriptor is
     broken or its directory replaced by a symlink, `--with my_kb` exits 2 and writes
     nothing, with a message that says to re-register.
   - `test_malformed_registry_errors_name_the_file` for `--with unknown_name`.
2. Implement: in `cmd_new` and `cmd_add`, collect the bare names not in `modules`
   (and, for `--add`, not recorded) and resolve them through `registry_entries`;
   for `name=path` entries whose name is not built-in, load the registry once and
   refuse a different registered path (compare real paths); feed everything to the
   existing `load_externals`. Extend `cmd_list`.
3. Run the whole suite.

Completion: new tests pass; every pre-existing test passes unmodified.

### Increment D — help text and final checks

Dependencies: Increment C
Affected areas: `install.py` (usage docstring, argparse help), `tests/test_install.py`

1. Update the docstring and the `--register`, `--unregister`, `--registry`,
   `--name`, and `--list` help.
2. Run the full suite with `-W error::ResourceWarning`, `git diff --check`, and the
   scratch runs under Verification.

Completion: all completion criteria met.

## Verification

- `python3 -I -m unittest discover -s tests`.
- Scratch runs under the session scratchpad with `--registry` pointing inside it:
  register, list, `--with` and `--add` by registered name, unregister; and
  `--with graphify,cad,plan-review,claude` diffed against the previous commit's
  installer (only the project name and template commit may differ).
- A store tree checksum (dotfiles included) before and after each scratch command.
- `git diff --check`.

## Risks and sensitive actions

- The installer now writes outside the project: the registry file and its directory
  under the owner's configuration directory. Tests use `--registry` under a temporary
  directory and never touch the real `~/.config`; the plan's scratch runs do the same.
- The registry is machine state shaped by the owner's commands. Each use re-verifies
  the store; a tampered registry can only point at a directory that passes the same
  read-only checks. The adversarial review is candidate 3, so the feature should not
  be announced in the README before then.
- A default-path test must not create `~/.config/claude-project-template`; the tests
  that exercise the default set `HOME` and `XDG_CONFIG_HOME` to a temporary directory.
- Commits only on explicit approval; nothing pushed without it.

## Deferred work

- Trust-model review and ADRs (candidate 3); store-side contract (candidate 4);
  end-to-end check and README (candidate 5).
- Locking for concurrent writers; refresh on drift using the recorded digest.

## Review Focus

- A relative or `~` register path from another working directory: stored as the real
  absolute path (Increment B).
- A store directory renamed after registration: `--with name` fails clearly and
  `--list` shows `missing` (Increment C).
- A store registered under a name that later becomes a built-in module (Increment C).
- An empty `--registry` value or a path to a directory (Increment A: refused).
- Registering a store that the registry file's own directory contains or is inside:
  the store check is independent of the registry and still passes or fails on its
  own merits (Increment B).

## Result

<!-- Complete this only after verification. Archive the plan according to
base/docs/plans/README.md, then reset this file to the empty template. -->
