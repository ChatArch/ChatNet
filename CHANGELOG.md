# Changelog

## 0.2.2 - 2026-08-11

### Added

- Add top-level `chatnet --tree` generated from the registered Click command surface.
- Add CLI tree documentation and tests covering `ping`, `ssh`, `links`, `services`, and nested `proxy` commands.

### Changed

- Align docs metadata with the ChatArch docs domain and strict-build dependency bounds.
- Match the PyPI Trusted Publisher `(Any)` environment by removing the workflow-level `pypi` environment.
- Raise the ChatEnv dependency floor to the currently released `0.2.4` line.

## 0.2.1 - 2026-06-29

### Added

- Add `chatnet proxy serve` for non-sudo explicit HTTP/HTTPS CONNECT forward proxy serving with CIDR allowlist and optional Basic auth.
- Add `chatnet proxy check` for validating target URLs through an explicit proxy.
- Add `chatnet proxy autostart print|install` for non-sudo user systemd autostart templates.
- Add reusable `chatnet.forward_proxy` helpers so the proxy server can be embedded from Python without going through the CLI.
- Add ChatEnv provider metadata for `CHATNET_PROXY_*` values and ChatStyle `-i/-I` input resolution for new proxy commands.

## 0.2.0 - 2026-06-27

### Changed

- Refactor ChatNet into the generic ChatArch network helper layer.
- Replace the ECNU-specific `chatnet ecnu` application surface with generic network commands:
  - `chatnet ping`
  - `chatnet ssh`
  - `chatnet links`
  - `chatnet services`
- Slim package dependencies to generic runtime requirements: `click` and `requests`.
- Update README and docs to describe ChatNet as an application-neutral network foundation package.

### Added

- Add `chatnet.scanner` for ping and TCP port scanning helpers.
- Add `chatnet.link_check` for URL extraction, URL checks, and service health checks.
- Add `chatnet.service_urls` for service URL normalization and token query handling.
- Add `chatnet.portal` for reusable browser-like session/cookie state, HTML table parsing, and request/curl preview helpers.
- Add `chatnet.mcp` for MCP registration of generic network scan helpers.

### Removed

- Remove ECNU application-layer modules from ChatNet:
  - `src/chatnet/ecnu/*`
  - `src/chatnet/config.py`
  - ECNU docs and ECNU mock CLI tests.
- Remove ECNU-specific dependencies from ChatNet. ECNU login/session/visitor/CAPTCHA behavior moves to the separate ChatECNU package and should depend on this ChatNet line after release.

## 0.1.2

### Changed

- Prepare `0.1.2` release in the feature PR so the post-merge tag can publish a continuous next-patch version.
- Remove the unused top-level `chatnet hello` template command so the CLI only exposes real product functionality.
- Add a non-network `ECNUConfig.test()` implementation so `chatenv test -t ecnu` validates the installed provider without raising `NotImplementedError`.
- Trim the default `chatnet ecnu --help` surface by hiding advanced/sensitive diagnostics such as `login-init`, `cookie-header`, `selftest`, low-level state/cookie options, and `visitor lock`.
- Add `chatnet ecnu status` as the user-facing redacted session/status command while keeping `session-info` as a hidden compatibility alias.
- Make `chatnet ecnu login` the primary OCR-backed login entrypoint, keep `login-auto` as a hidden compatibility alias, and move log queries under hidden `debug` commands.
- Switch user-facing ECNU commands to human-readable summaries by default with opt-in `--json` output.
- Add `chatnet ecnu visitor default` plus `ECNU_VISITOR_PASSWORD1`, `ECNU_VISITOR_PASSWORD2`, and `ECNU_VISITOR_REMARK` for deterministic default visitor provisioning.
- Refactor ECNU login input resolution so manual and auto login share the same credential handling path.

## 0.1.1 - 2026-06-15

### Added

- Add `chatnet ecnu` commands for ECNU portal login, session inspection, log queries, and visitor account management.
- Add optional `captcha` extra for OCR-backed `chatnet ecnu login-auto`.
- Add ECNU CLI documentation and a local selftest command.
- Add ChatEnv provider metadata and `ECNUConfig` for `~/.chatarch/envs/ECNU/.env`.

### Changed

- Prepare `0.1.1` release to verify PyPI Trusted Publishing without repository-level PyPI token secrets.
- Change publish workflow to explicit `v*` tag / `workflow_dispatch` triggers with PyPI Trusted Publishing (`id-token: write` + `environment: pypi`).
- Load ECNU CLI defaults from chatenv and move default ECNU session/cache paths under `~/.chatarch/cache/chatnet/`.
