# Development

## Setup

<!-- List supported platforms, required tool versions, dependency setup, and
local configuration. Do not include secrets. -->

## Commands

Keep this table accurate. Use `not applicable` rather than leaving an
ambiguous blank.

| Purpose | Command |
|---|---|
| Setup | `REPLACE_WITH_COMMAND` |
| Run locally | `REPLACE_WITH_COMMAND` |
| One focused test | `REPLACE_WITH_COMMAND` |
| Full tests | `REPLACE_WITH_COMMAND` |
| Format | `REPLACE_WITH_COMMAND` |
| Lint or static analysis | `REPLACE_WITH_COMMAND` |
| Type check | `REPLACE_WITH_COMMAND` |
| Build | `REPLACE_WITH_COMMAND` |
| All required checks | `REPLACE_WITH_COMMAND` |

## Verification workflow

1. Run the narrowest check covering the change.
2. Inspect the complete useful failure output and correct the root cause.
3. Rerun the failed check.
4. Run the broader required check when practical.

Document checks that intentionally update snapshots, fixtures, generated code,
or tracked artifacts.

## Local debug artifacts

Keep retained, untracked diagnostics in
`/.debug/<YYYY-MM-DD>-<topic>/`. Opt in locally; do not add this directory to
the tracked `.gitignore`:

```sh
printf '/.debug/\n' >> .git/info/exclude
mkdir -p .debug
```

Include a local README with the source commit, command and tool versions,
purpose, and conclusion. These artifacts are not portable to fresh clones or
worktrees. Record durable findings in tracked documentation, decisions, or
tests instead.

## Debugging

<!-- Explain how to run one test, enable useful logging, locate generated
artifacts, reproduce common failures, and distinguish environment problems from
product defects. -->

## Tool-specific guidance

Use the repository's documented command interface. Add guidance for a build
system, language server, generated files, or other tool only when the project
uses it. Keep project-wide tool configuration committed and distinguish each
tool's exclusions from other tools' input filters.

### CAD and FreeCAD (when used)

See [CAD workflow](cad.md) for the project's CAD conventions. Command notes
verified against FreeCAD 1.1.4:

- Run a check headless with `freecadcmd <script.py> -- <arguments>`; arguments
  after `--` appear in `sys.argv`. On macOS the binary is
  `/Applications/FreeCAD.app/Contents/Resources/bin/freecadcmd`.
- Headless FreeCAD has no GUI: `ViewObject` is `None`, constructing a Qt widget
  aborts the process, and the Curves workbench commands need the GUI session.
  Assembly joint creation was only verified in the GUI session.
- Add the project's model-check script (recompute without errors, critical
  dimensions, sketch constraint state, export read-back) to the command table
  above, and say whether it needs the GUI.
- Add-ons such as Curves or Curved Shapes are not part of FreeCAD: list the
  required versions in `cad.md` and re-run the model checks after updating them.
