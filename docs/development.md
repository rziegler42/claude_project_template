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
