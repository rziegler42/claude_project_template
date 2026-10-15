## Formal verification

- Read the governing spec or decision before writing a property, and state each
  property as an observable claim.
- An assumption on an interface input needs a written source, such as a spec
  clause or ADR. Until one exists, keep it out of the main proof, put it in a
  separately named conditional task, and report its results as conditional.
- Fix a failing induction step with the missing invariant, not a larger depth or
  an assumed state.
- If a cover does not reach, cover an earlier prerequisite and work forward;
  do not force it with an assumption.
- Pair each important safety proof with a reachability cover and a deliberately
  broken fixture that must fail.
- A timeout or unknown result is inconclusive, not a pass. Record the engine,
  depth, timeout, and elapsed time, and keep counterexample traces until the
  finding is resolved.
