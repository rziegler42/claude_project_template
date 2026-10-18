# Module references

Status: Superseded by [external-modules](external-modules.md) (2026-10-18); kept as
the record of the earlier reference design
Updated: 2026-10-17

Requirements for letting a module take an inline argument that names another
local project, verify it read-only, and use it when generating files. The first
user is a `knowledge-base` module that points a project's agent guidance at a
knowledge-base project, one created by the sibling `claude_knowledge_base`
installer and identified by its `kb.json`.

## Scope

- Installer syntax for `module=value` in `--with` and `--add`.
- A `reference` declaration in `module.json`.
- Read-only verification of the referenced project through a marker file.
- Substitution of verified values into module files and slots.
- Recording the reference in `.template-manifest`.

## Non-goals

- Executing, importing, or writing anything in the referenced project.
- Copying the referenced project's files into the new project.
- Network or registry lookups; the value is a local path.
- Any rule about the referenced project beyond its marker file. The marker's
  contents belong to the referenced project.

## Syntax

```sh
install.py ../mygame --with knowledge-base=../my-kb,graphify
install.py --add knowledge-base=../my-kb
```

- In `--with`, entries are split on commas first, then each entry on its first
  `=`; the value is everything after it. `--add` takes a space-separated list and
  splits each argument on its first `=`.
- A value containing a comma is refused in `--with` (commas separate entries).
- `=value` on a module that declares no `reference` is refused.
- A module that declares a required reference and is selected without a value is
  refused, or prompted for when stdin is a terminal and the run is not `--dry-run`.
- A module that declares a required reference and is pulled in only through
  another module's `requires` is refused with a message naming the module and the
  syntax to give it a value.

## Declaration

`module.json` gains an optional object:

```json
"reference": {
  "kind": "knowledge-base",
  "marker": "kb.json",
  "schema": 1,
  "files": ["router"],
  "required": true
}
```

| Key | Meaning |
|---|---|
| `kind` | Value the marker's `kind` must equal |
| `marker` | File name at the referenced project's root |
| `schema` | Value the marker's integer `schema` must equal |
| `files` | Marker keys whose values are relative paths that must name regular files inside the referenced project |
| `required` | Whether a value must be supplied (default true) |

The declaration is validated when modules load: unknown or mistyped keys, a
`marker` containing a path separator, and a non-printable or over-long value are
module errors.

## Verification

The installer resolves the value with `realpath`. It must be an existing
directory, must not be the template, the target project, or inside any `.git`
directory, and must be printable single-line text. Then, using the installer's
existing hardened regular-file reads (no symlinks, no special files, size cap):

1. read the marker file and parse it as a JSON object;
2. require `kind` and `schema` to equal the declaration;
3. for each key in `files`, require its value to be a relative path with no `..`
   or absolute component that names a regular file inside the referenced project.

Any failure aborts the run before anything is written, with a message that names
the failing check and never repeats file content. Verification reads nothing else
and runs no program from the referenced project. The only subprocess is the
installer's sanitized `git`, used to read the referenced project's commit
(blank when it is not a git checkout).

## Substitution

Inside the module's files and slots, for each declared key `k`,
`REPLACE_WITH_REFERENCE_<K>` (key upper-cased) is replaced by the verified value
joined to the referenced project's path, and `REPLACE_WITH_REFERENCE_PATH` by the
path itself. The path is written relative to the new project when both share a
parent directory, otherwise absolute.

A committed path is specific to one checkout; the module's own text must say so.

## Manifest

`.template-manifest` keeps `schema` 1 and gains an optional object:

```json
"references": {
  "knowledge-base": { "kind": "knowledge-base", "schema": 1, "commit": "<sha or empty>" }
}
```

- The path is not stored.
- A manifest without `references` stays valid. When present it is validated:
  an object, names matching the module-name rule, bounded string fields.
- Under `--add`, a module that needs a reference requires a value again; modules
  already installed keep their recorded entry. Adding a second reference never
  rewrites an existing one.

## Acceptance criteria

1. Parsing: the syntax cases above, including the refusal and prompt cases.
2. Verification: tests fail the run, with nothing written, for a missing
   directory, a missing marker, a marker that is not JSON, a wrong `kind` or
   `schema`, a `files` entry that is missing, absolute, contains `..`, or is a
   symlink or special file, an oversized marker, and a referenced project that is
   a symlink.
3. Read-only: a checksum of the referenced project's tree is identical before and
   after a run, including `--dry-run`.
4. Substitution and manifest contents match this document.
5. A hostile referenced project (a `.git` with configured helpers, a
   `GIT_*` environment) causes no program to run.
6. All existing tests still pass.

## Related

- Roadmap: [module-references](../roadmaps/archive/2026-10-module-references.md)
- [ADR 0001](../decisions/0001-module-and-slot-architecture.md) and
  [ADR 0002](../decisions/0002-installer-trust-model.md), which this extends.
