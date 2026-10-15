## Graphify

Graphify is a discovery and impact-analysis aid, not a source of truth or an
implementation requirement.

Use it when:

- Architecture or ownership is unfamiliar.
- A change, refactor, ADR, or review spans multiple components.
- Dependency or impact analysis is needed.
- Ordinary file inspection might miss affected paths during debugging or review.

Skip it when:

- The change is narrow and the relevant files are known.
- The task is an isolated test, documentation edit, or mechanical change.
- The active plan already enumerates the complete file scope.

For a substantive detailed plan, use one focused Graphify discovery or impact
query when Graphify is configured, then record its freshness, purpose, and a
conclusion verified against current source in the plan. When the scope, files,
and precedents are already fully enumerated, record `Graphify: skipped —
<concise reason>` instead. A non-current graph may orient discovery but is not
evidence for a plan conclusion without that direct verification and recorded
limitation.

Refresh policy:

- Do not build or refresh the graph automatically at session start.
- Check freshness before relying on a graph query and verify important findings
  against current files.
- Refresh code relationships after a coherent code change only when future
  impact analysis would benefit.
- Request a semantic refresh only after a material architecture, ADR, or design
  document change that should be discoverable through the graph.
- Do not refresh merely because documentation changed.
