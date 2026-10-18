# 0003: External module mechanism

Status: Proposed
Date: 2026-10-18

## Context

The template installs modules from its own `modules/`. Standalone projects such
as a knowledge-base store created by `claude_knowledge_base` must stay
independent of the template yet be installable into projects with `--with` and
`--add`. The approved [specification](../specs/external-modules.md) fixes the
behaviour; plans 0006 and 0007 implemented it; plan 0008 reviewed it adversarially.

## Decision

- A standalone project ships `template-module/module.json` and
  `template-module/slots/*.md`. The template owns the schema; the project owns
  its text. Slot fragments only: no `files/`, no `requires`.
- A store is named by `name=path`, or by a bare name registered in a machine-local
  registry (`--register`, `--unregister`, `--list`). The name is unique and maps
  1:1 to a real path. It defaults to the directory name; `--name` overrides it.
  Built-in names are reserved. Several stores may be used in one project.
- Fragments use the placeholders `REPLACE_WITH_MODULE_NAME` and
  `REPLACE_WITH_MODULE_PATH` (`../<store>` when the store and project share a
  parent, else absolute) and install as `BEGIN/END module:<name>` blocks after
  all built-in modules.
- The manifest records an installed store in `external_modules` as
  `{module_format, digest}` (no path); `modules` still lists built-ins only. The
  digest is a SHA-256 over the descriptor files in a fixed order and lets a later
  refresh detect drift.
- The registry is `registry.json` (schema 1) under `$XDG_CONFIG_HOME` or
  `~/.config`, overridable with `--registry`, loaded lazily and re-verified at
  every use. The trust model is the ADR 0002 addendum.

## Alternatives considered

- A generator flag (`--add-to`) in the store's tool that runs the template.
  Rejected: it couples the standalone project to the template.
- Copying a store's text into the template or into each project once.
  Rejected: the store owns its text and the copy drifts.
- Shipping files (`files/`) from stores, `requires` between modules, or a remote
  or registry-hosted store. Deferred: they enlarge the read boundary.
- Reference-only modules that record a path in the manifest. Rejected: a path in
  a committed manifest is machine-specific and a path-based trust input.
- Requiring registration. Rejected: a path needs no registry entry.

## Consequences

- A project can install a store without the store knowing the template.
- The installer now reads outside the template and writes a registry file; both
  follow the ADR 0002 addendum.
- Refreshing an installed store when it changes is not implemented; the digest is
  recorded for that purpose.

## Verification

- `python3 -I -W error::ResourceWarning -m unittest discover -s tests` passes
  (167 tests).
- Plan 0008: two independent `security-reviewer` passes with scratch
  experiments and a read-only diff review. Of ten hypotheses, seven were refuted
  (symlink and swap handling of a store, containment, hostile `.git`,
  `module.json`, names, registry tampering, forged manifest entries); the three
  partly confirmed (markers, output, `--dry-run`) and the new findings the
  experiments turned up gave seven fixes plus one regression the diff review
  caught. Each has a regression test that failed first:
  - a placeholder completing a reserved marker
    (`test_placeholder_cannot_complete_a_reserved_marker`);
  - one store under two case aliases (`test_same_store_under_a_case_alias_is_one_store`,
    `test_register_refuses_the_same_store_under_a_case_alias`);
  - a non-printable real path (`test_non_printable_real_path_is_refused`,
    `test_register_refuses_a_non_printable_real_path`);
  - `--unregister --dry-run` deleting the entry (`test_unregister_dry_run_removes_nothing`);
  - `..` through a symlink (`test_dotdot_through_a_symlink_resolves_physically`);
  - a trailing newline in names and a flooded format message
    (`test_name_pattern_rejects_a_trailing_newline`,
    `test_unsupported_format_message_does_not_echo_a_huge_number`);
  - fragment count checked after reading (`test_fragment_count_is_checked_before_reading_fragments`).
  - a symlinked store named with a trailing `/.`, which the fix for `..` briefly
    let through (`test_refuses_symlinked_store_with_trailing_dot_components`,
    `test_dot_names_the_current_directory`).
  The second pass found no bypass and no new traceback.
- Accepted residuals: see the ADR 0002 addendum.

## Related files and decisions

- `install.py`, `tests/test_install.py`, `docs/specs/external-modules.md`.
- ADR 0001 (modules and slots), ADR 0002 (trust model and addendum); plans 0006,
  0007, and 0008.
