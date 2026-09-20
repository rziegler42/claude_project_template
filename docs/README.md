# Documentation guide

This directory contains the project’s technical references, decisions, plans,
and supporting evidence.

## Index

| Location | Purpose |
|---|---|
| `architecture.md` | Current system architecture and behavioral contract |
| `development.md` | Development, build, test, and verification guidance |
| `decisions/` | Durable Architecture Decision Records (ADRs) |
| `plans/` | Active and archived implementation plans |
| `roadmaps/` | Multi-plan direction, ordering, and dependencies |

<!-- Add rows for reference/, perf/, security/, operations/, or other
project-specific directories when created. -->

## Authority and lifecycle

- Current architecture documents and accepted ADRs are the durable design
  authority.
- When a plan is used, `plans/next.md` is the sole implementation-ready plan
  and requires explicit approval before implementation.
- Roadmaps guide sequencing and dependencies. They do not authorize work or
  alter an active plan.
- Archived plans, experiments, investigations, and logs are historical
  evidence, not current authority.
- Record durable architectural choices in ADRs rather than relying only on
  plans, roadmaps, tickets, or agent memory.

## Documentation conventions

- Prefer one concise current reference over duplicated rules.
- Link to the governing document or ADR rather than restating it.
- Preserve historical records; mark them completed or superseded rather than
  rewriting their conclusions.
- Keep generated artifacts and raw experimental data in their designated
  directories.
- Use stable, descriptive lowercase kebab-case filenames unless the repository
  defines another convention.
