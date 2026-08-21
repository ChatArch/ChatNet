# Development Guide

## CLI Rules

- Use `chatstyle>=0.2.0,<0.3.0` and `chatenv>=0.2.10,<0.3.0` as the canonical CLI/config runtime.
- Keep the public root explicitly named `chatnet`.
- Use ChatStyle `add_tree_option()` for `--tree` and `--tree-brief`; do not add package-local tree renderers.
- Prefer `CommandSchema`, `CommandField`, `add_interactive_option()`, and `resolve_command_inputs()` for new commands.
- Missing required args should auto-enter interactive mode when recoverable.
- `-i` forces interactive mode; `-I` disables prompting and must fail fast.
- Prompt defaults must match actual execution defaults.
- Sensitive values must stay masked in prompts, summaries, and CLI tree output.
- Prefer lazy imports in CLI wiring and keep implementation imports local when possible.

## Docs and Tests

- Use doc-first CLI testing.
- Put real CLI coverage under `tests/cli-tests/`.
- Put mock/fake CLI coverage under `tests/mock-cli-tests/`.
- Keep `README.md`, `docs/`, and `CHANGELOG.md` in sync with user-facing changes.
- Test `--version`, the full registered tree, and the signature-free brief tree.

## Automation

- Keep automation small and reviewable.
- Prefer commands that can run in CI without interactive prompts.
- Ensure generated defaults are safe for local development.
