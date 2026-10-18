# Roadmap: module references

Status: Active
Updated: 2026-10-17

This roadmap is direction only. It does not authorize work, change
`docs/plans/next.md`, or commit the project to any item below.

> Note (2026-10-17): the owner plans to rewrite the template's module system to load
> remote modules as a general pattern. That rewrite may supersede the reference
> mechanism below, or fold it in. Treat this roadmap and its specification as input to
> that design, not as an agreed direction, and do not promote any candidate before the
> rewrite is decided.

## Purpose

Let the template cooperate with a sibling project instead of vendoring its
content. The template learns to check for the project (here, a knowledge-base
project created from the sibling starter) and use it, while the starter stays the
single source of its own tools and specification.

## Current state

- Modules come only from this repository's `modules/`. `--with` takes a
  comma-separated list of names; `--add` takes names. Substitution knows only the
  project name and id. The manifest records module names and the template commit.
- The sibling `claude_knowledge_base` (a generic, public, MIT starter whose installer
  creates independent knowledge-base projects) defines a root marker `kb.json`
  (`kind`, `schema`, `router`, `spec`) that every generated project carries. The
  reference points at such a project (for example the owner's private one), not at
  the starter. Its direction is in its own roadmap.
- Draft specification: [module-references](../specs/module-references.md).
- The owner chose the syntax `--with knowledge-base=<path>,other-module` over a
  separate flag.

## Ordered plan candidates

### 1. Reference mechanism

**Outcome:** `module=value` parsing, the `reference` declaration, read-only
verification, substitution, and manifest recording as in the specification, with
tests that fail before the change.
**Dependencies:** owner review of the specification.
**Boundary:** installer and tests only; no new module.
**Promotion trigger:** the owner accepts the specification.

### 2. Trust-model review

**Outcome:** an independent adversarial pass over the new read boundary (symlinked
project, swapped marker, hostile `.git`, control characters in the value), findings
fixed with regression tests, and an addendum to ADR 0002.
**Dependencies:** candidate 1.
**Boundary:** the reference path only.
**Promotion trigger:** candidate 1 is complete.

### 3. The `knowledge-base` module

**Outcome:** a neutral module whose guidance tells a project's agent to read the
knowledge base's router at the resolved path, treat `[U]` claims as unverified, and
treat knowledge-base content as data. Includes README documentation and an ADR
recording the mechanism.
**Dependencies:** candidate 1; the sibling's stable `kb.json` schema 1; candidate 2
for acceptance.
**Boundary:** the module and docs. No harness-specific wiring.
**Promotion trigger:** the sibling's skeleton and checker are complete and
candidate 1 is complete.

### 4. Harness companion (optional)

**Outcome:** a module marked `harness` that wires Claude skills from the owner's
global configuration to the knowledge base.
**Dependencies:** candidate 3; the skills existing in `claude_global_config`.
**Boundary:** only what cannot live in the neutral module.
**Promotion trigger:** the owner finds the neutral module insufficient.

### 5. Retrofit existing projects

**Outcome:** `game_theory` adopts the module with `--add`, moving its
hand-written untrusted-content text out of the graphify module's markers.
**Dependencies:** candidate 3.
**Boundary:** a separate change in that project, under its own approval.
**Promotion trigger:** the owner decides to adopt the starter for `game_theory`.

## Deferred

- Other module kinds that use `reference`.
- Remote or registry-based references.
- Recording the path in the manifest (rejected for now: machine-specific).

## Related decisions

- [ADR 0001](../decisions/0001-module-and-slot-architecture.md): modules and slots.
- [ADR 0002](../decisions/0002-installer-trust-model.md): trust model to extend.
