# Roadmap: external modules

Status: Active
Updated: 2026-10-18

This roadmap is direction only. It does not authorize work, change
`docs/plans/next.md`, or commit the project to any item below.

## Purpose

Let the template coordinate standalone projects as modules. A standalone project,
first a knowledge-base store created by the sibling `claude_knowledge_base`
installer, registers with the template or is named by path, and is then installed
into projects with `--with` and `--add`, without the standalone project depending on
the template or the template carrying per-project knowledge.

## Current state

- Modules come only from this repository's `modules/`. `--with` takes names, `--add`
  takes names, and the manifest records module names and the template commit.
- Approved specification: [external-modules](../specs/external-modules.md). It
  replaces the earlier reference design, archived with its roadmap at
  [2026-10-module-references](archive/2026-10-module-references.md) and
  superseded in [module-references](../specs/module-references.md).
- Owner decisions behind it (2026-10-18): the template does the registering; each
  store has a unique name that maps 1:1 to a path; names default to the directory
  name with `--name` to override; an external module contributes slot fragments
  only, in a descriptor whose schema the template owns; several stores may be used
  in one project; the knowledge-base generator prints a registration hint and does
  not invoke the template.
- Candidate 1 is complete (2026-10-18, plan
  [0006](../plans/0006-external-module-core.md)): `name=path` works in `--with` and
  `--add`.
- Candidate 2 is complete (2026-10-18, plan [0007](../plans/0007-registry.md)):
  `--register`, `--unregister`, `--list`, and registered names work.
- Candidate 3 is complete (2026-10-18, plan
  [0008](../plans/0008-external-module-review.md)): two adversarial passes, findings
  fixed, ADR 0002 addendum, and [ADR 0003](../decisions/0003-external-module-mechanism.md)
  (Accepted 2026-10-18).
- The template side is complete, and the root `README.md` documents `name=path`,
  `--register`, the registry, and writing an external module (2026-10-18).
- `--update` refreshes installed built-in and external modules in a project
  (2026-10-18, plan [0009](../plans/0009-installer-update.md)); the manifest digest
  detects a changed store.
- `--remove` takes installed built-in and external modules out of a project: blocks
  stripped, unedited module files deleted, manifest entries dropped (2026-10-18, plan
  [0010](../plans/0010-installer-module-removal.md)).
- The sibling `claude_knowledge_base` is a generator that creates stores. Its
  roadmap (`knowledge-base-starter`, candidate 7) expects this integration; it
  will also drop `--add-to` and ship the descriptor. Its owner is implementing the
  store-side contract and the end-to-end check in that repository, outside this
  roadmap.

## Ordered plan candidates

### 1. External module core

**Outcome:** the descriptor format, `name=path` parsing in `--with` and `--add`,
read-only store verification, fragment validation and substitution, installation
of external blocks beside built-in ones, and the `external_modules` manifest entry
with its digest, as in the specification, with tests that fail before the change.
**Dependencies:** none.
**Boundary:** the installer and its tests; typed paths only, no registry, no
real store.
**Promotion trigger:** the owner asks to start.

### 2. Registry

**Outcome:** `--register`, `--unregister`, and `--list` for registered stores, bare
registered names in `--with` and `--add`, the 1:1 name-to-path rules, and lazy
registry loading.
**Dependencies:** candidate 1.
**Boundary:** the registry file and its commands; no change to the descriptor or
manifest.
**Promotion trigger:** candidate 1 is complete.

### 3. Trust-model review

**Outcome:** an independent adversarial pass over the new read boundary (symlinked
or swapped store, hostile `.git`, hostile descriptor text, registry tampering),
findings fixed with regression tests, an addendum to ADR 0002, and an ADR recording
the external-module mechanism.
**Dependencies:** candidates 1 and 2.
**Boundary:** the external-module and registry paths only.
**Promotion trigger:** candidate 2 is complete.

### 4. Store-side contract (in `claude_knowledge_base`) — not ours

Owned and in progress in `claude_knowledge_base` (2026-10-18). That repository drops
`--add-to`, ships `template-module/` in every generated store, and prints the
registration hint, as the specification's contract section requires. Nothing in the
template depends on it. This roadmap does not track or promote it.

### 5. End-to-end check — split

The README sections on registering and writing an external module are done on the
template side. The end-to-end check (a generated store registered and installed into
a scratch project) belongs to the knowledge-base owner with candidate 4. If the
template should record its result, that is a documentation update after it, not a
plan here.

## Deferred

- Shipping files from a store (`files/`), `requires` between modules, and a
  `module_format` greater than 1.
- Adopting a store in existing projects such as `game_theory` with `--add`, under
  that project's own approval.
- A Claude-specific companion module that wires harness skills to a store.
- Remote or registry-based stores.

## Related decisions

- [ADR 0001](../decisions/0001-module-and-slot-architecture.md): modules and slots.
- [ADR 0002](../decisions/0002-installer-trust-model.md): trust model, with the 2026-10-18 addendum for stores and the registry.
- [ADR 0003](../decisions/0003-external-module-mechanism.md): the external-module mechanism.
