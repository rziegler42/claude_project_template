# Template repository plans

Plans for changing this template repository itself. They follow the lifecycle
and formats in `base/docs/plans/README.md`; `next.md` is the sole active plan.

## Archives

| Plan | Status | Outcome |
|---|---|---|
| [0001](0001-module-installer.md) | Completed | Modular `install.py` replaces `cp -R`; base and opt-in modules; explicit git identity |
| [0002](0002-runner-stub-hints-prompts.md) | Completed | Runner contract stub in the `claude` module, module post-install hints, prompts validated before asking |
| [0003](0003-installer-security-review.md) | Completed | Two adversarial security reviews of `install.py`; hardened reads and writes, scrubbed git environment, `--skip-unsafe-entries`; ADR 0002 |
