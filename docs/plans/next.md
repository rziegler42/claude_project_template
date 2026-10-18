# Consistent multi-item options

Status: Approved
Created: 2026-10-18

## Goal

Every `install.py` option that takes several modules accepts them the same way:
space-separated values. `--with claude graphify` works like `--add claude graphify`,
and `--help` shows the same `MODULE` placeholder for all four options.

## Scope

- `--with` takes `nargs="+"` with `metavar="MODULE"` (replacing today's single
  comma-joined string with the `WITH_` placeholder). `--add`, `--update` and
  `--remove` are unchanged apart from help text.
- `--with` keeps accepting comma-joined values, so `--with cad,graphify` and the
  README examples still work. Each value is split on commas; the resulting names are
  concatenated in order.
- The interactive prompt in create mode accepts names separated by spaces or commas.
- When `--with` is given and no target remains (for example
  `install.py --with claude ../proj`, where the target was consumed as a module),
  the error says the target must come before `--with`, or after `--`.
- Help text, README usage lines and the ADR 0002 note on commas in `--with` paths.

## Non-goals

- Comma splitting for `--add`, `--update` or `--remove`. A store path containing a
  comma works in `--add` today (`test_comma_in_store_path_fails_in_with_and_works_in_add`);
  splitting there would break it.
- Removing comma support from `--with` (a breaking change to existing commands).
- Changing which modes can be combined, or any module, manifest or write behavior.

## Assumptions and constraints

- Governed by ADR 0002: a `--with` path containing a comma is split and fails closed.
  That stays true for `--with`; only the way several values are supplied changes.
- Decision (owner approved the plan): keep comma support in `--with` for
  compatibility, rather than making `--with` space-only like the others. This keeps
  one known inconsistency (`--with` alone splits commas) in exchange for no broken
  commands.
- Argparse cannot tell a trailing target from a module: with `nargs="+"`,
  `--with a b TARGET` reads `TARGET` as a module. Documented usage puts `TARGET`
  first; the clearer error above covers the mistake.
- An uncommitted one-line edit already in the working tree gives `--with` a
  `metavar`. This plan supersedes it (`MODULE` instead of `MODULES`).

## Discovery and impact evidence

Graphify: skipped — the change is confined to the `--with` argument, `parse_with`,
the create-mode prompt, and one `main` error path in `install.py`, plus tests,
README and ADR 0002, all read directly from current source.

Verified in `install.py`: `parse_with` (line 864) splits one string on commas;
`cmd_new` (line 1060) calls it on `args.with_` and tests `not args.with_` for the
interactive prompt; `main` tests `args.with_` truthiness in the `--remove`,
`--update` and `--register` conflict checks, which a list default of `[]` preserves.
`--add`, `--update` and `--remove` already use `nargs` with `metavar="MODULE"`.

## Completion criteria

- `--with a b`, `--with a,b`, and `--with a,b c` each select the same modules as
  the equivalent comma-only form, in order.
- `--with claude ../proj` fails with the target-ordering hint and writes nothing.
- `./install.py --help` shows `--with MODULE [MODULE ...]`.
- The conflict checks for `--with` in `--update`, `--remove` and registry modes still
  fire.
- Full suite passes and `git diff --check` is clean.

## Increments

### Increment A — Space-separated `--with`

Dependencies: None
Affected areas: `install.py`, `tests/test_install.py`

1. Add failing tests: space-separated, comma-separated and mixed `--with` select the
   same modules in order; a name=PATH entry works in the space form; a missing target
   after a greedy `--with` gives the ordering hint; the existing conflict checks still
   reject `--with` with `--update`, `--remove` and `--register`; the prompt accepts
   spaces and commas.
2. Change `--with` to `nargs="+"`, `default=[]`, `metavar="MODULE"`; have
   `parse_with` take a list and split each item on commas; update the prompt text and
   its parsing; improve the missing-target error in `main`.
3. Run the new tests, then the full suite.

Completion: step 1 tests fail before step 2 and pass after; full suite green.

### Increment B — Documentation

Dependencies: Increment A
Affected areas: `README.md`, `docs/decisions/0002-installer-trust-model.md`,
`docs/plans/README.md`

1. README: show the space form beside the comma form, state that `TARGET` comes
   before `--with`, and that `--with` alone still accepts commas.
2. ADR 0002: a short addendum that `--with` accepts several values and that the
   comma-path rule is unchanged.
3. Add the plan to the archive table when archived.

Completion: README commands match `./install.py --help`; `git diff --check` clean.

## Verification

- `python3 -I -m unittest discover -s tests` after each increment.
- `./install.py --help` and a `--dry-run` create into a scratch directory with the
  space, comma and mixed forms.
- `git diff --check`.

## Risks and sensitive actions

- Public CLI change: a script that places the target after `--with` (for example
  `--with claude ../proj`) breaks, now with a clear error. The README already puts
  the target first. Accepted by the owner only when this plan is approved.
- No new read or write boundary; a security review is not warranted. The comma-path
  fail-closed behavior is covered by an existing test, which must keep passing.

## Deferred work

- Making every option space-only, or adding comma splitting to `--add`, `--update`
  and `--remove`, if the owner later wants a different consistency rule.

## Result

<!-- Complete this only after verification. Archive the plan according to
base/docs/plans/README.md, then reset this file to the empty template. -->
