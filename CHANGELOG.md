# Changelog

## Unreleased

## 0.2.4 - 2026-10-10

### 新增

- 增加通过 ChatEnv 配置的本地诊断与显式单次恢复，保留冷却、滑动窗口预算及并发锁。
- 增加持久事件：故障观察、阻止和错误、尝试、每阶段开始/结束、复测与恢复确认，关联 incident、attempt 和 run，提供有界分段保留。
- 增加可调用的 `read_recovery_logs()` 与 `chatnet recovery logs`，支持有界查询、状态/incident 过滤和 JSON 输出。
- 增加仅基于先前内核核验身份的缺失接口恢复；未知设备、空指纹、共享模块及不安全管理路径一律拒绝操作。
- 将用户级恢复 oneshot/timer 基础设施随包发布，并在既有 CI 中验证独立 wheel 与真实公开 PyPI 安装。

### 修正

- 健康空操作、检查失败和阻止也记录真实结果；`check` 和预演仍不修改恢复状态。
- 将选定保存连接与实际活动连接 UUID 分开，复测必须确认尝试目标已活动，且物理实例、指纹和 profile 身份一致，避免误报恢复。
- `recovered_at` 只取成功复测的实际完成时间；被中断的阶段和尝试保留未完成记录，不倒推成功。
- 修改网络前验证全部保留历史；拒绝损坏或不安全记录、非普通文件、数字溢出和过深 JSON，保留可识别的旧格式记录及原预算。
- 保持恢复离线且单次执行，不重启主机或 NetworkManager，不读取/更改 Wi-Fi 凭据，不新增后台看门狗。

## 0.2.3 - 2026-08-22

### Added

- Add `chatnet --tree-brief` and registry-backed full/brief tree contract tests.
- Add installed editable and built-wheel CLI readbacks to the Python 3.10-3.12 CI matrix.

### Changed

- Replace the package-local tree renderer with ChatStyle `add_tree_option()`.
- Align runtime bounds to `chatstyle>=0.2.0,<0.3.0` and `chatenv>=0.2.10,<0.3.0`.
- Document command side effects and secret-output boundaries in both registered tree views.
- Guard tag publication so the tagged commit must belong to the `master` default branch.

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
