# Template repository plans

Plans for changing this template repository itself. They follow the lifecycle
and formats in `base/docs/plans/README.md`; `next.md` is the sole active plan.

## Archives

| Plan | Status | Outcome |
|---|---|---|
| [0001](0001-module-installer.md) | Completed | Modular `install.py` replaces `cp -R`; base and opt-in modules; explicit git identity |
| [0002](0002-runner-stub-hints-prompts.md) | Completed | Runner contract stub in the `claude` module, module post-install hints, prompts validated before asking |
| [0003](0003-installer-security-review.md) | Completed | Two adversarial security reviews of `install.py`; hardened reads and writes, scrubbed git environment, `--skip-unsafe-entries`; ADR 0002 |
| [0004](0004-plan-review-module.md) | Completed | Tool-neutral `plan-review` module: bounded read-only plan review policy and a Second opinion receipt in plans and archives |
| [0005](0005-codex-module.md) | Completed | Harness-marked `codex` module on top of `plan-review`: concrete Codex plan-review guidance and receipt mapping |
| [0006](0006-external-module-core.md) | Completed | `name=path` in `--with` and `--add`: standalone projects with a `template-module/` descriptor install as modules (fragments only), recorded in the manifest |
| [0007](0007-registry.md) | Completed | Machine-local registry: `--register`, `--unregister`, `--list` for standalone projects, and registered names in `--with` and `--add` |
| [0008](0008-external-module-review.md) | Completed | Adversarial review of the external-module and registry paths; seven findings fixed with regression tests, ADR 0002 addendum, ADR 0003 (Accepted) |
| [0009](0009-installer-update.md) | Completed | `--update`/`--upgrade` refreshes installed built-in and external modules in a project: blocks re-rendered, missing files written, differing files kept; security review skipped by the owner |
| [0010](0010-installer-module-removal.md) | Completed | `--remove` takes installed built-in and external modules out of a project: blocks stripped, unedited module files deleted descriptor-relative, manifest updated; adversarial review fixed four defects |
| [0011](0011-consistent-multi-item-options.md) | Completed | `--with` accepts space-separated modules like `--add`, `--update` and `--remove`, and still accepts commas; ordering hint when the target is swallowed |
