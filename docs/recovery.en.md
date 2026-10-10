# Offline network recovery

ChatNet provides one-shot diagnosis and guarded recovery on Linux with NetworkManager. It does not start a watchdog or claim to repair the hardware fault.

## Commands

```bash
chatnet recovery check
chatnet recovery check --json-output
chatnet recovery run                         # read-only plan
chatnet recovery run --execute --json-output # one guarded attempt
chatnet recovery logs --limit 100
chatnet recovery logs --status failed --json-output
chatnet recovery logs --incident-id <uuid>
```

An unhealthy check or failed recovery exits nonzero. `check` inspects the network but never reads or writes recovery state. A dry run also creates no state. Every `run --execute` invocation records a native result, including healthy no-ops, blocked attempts, and inspection errors. A healthy link is never reset, and a failed optional external probe does not trigger repair while the local gateway remains reachable.

## ChatEnv configuration

Use the existing `ChatNet` provider. Process environment overrides the active profile; hardware options do not belong in daily CLI arguments.

```dotenv
CHATNET_RECOVERY_INTERFACE=
CHATNET_RECOVERY_CONNECTION=saved-wifi
CHATNET_RECOVERY_RESCUE_PEER=192.0.2.1
CHATNET_RECOVERY_PROBE_HOST=
CHATNET_RECOVERY_MODULE_RELOAD=true
CHATNET_RECOVERY_COOLDOWN=300
CHATNET_RECOVERY_MAX_ATTEMPTS=3
CHATNET_RECOVERY_WINDOW=3600
```

Replace the example connection and peer with verified local values. An empty interface requires exactly one wireless interface. An empty connection requires an unambiguous saved Wi-Fi profile. Module reload defaults to false; the module is derived from kernel evidence and cannot be supplied as a CLI option. The rescue peer must route through an independent physical Ethernet interface with carrier.

Do not provide Wi-Fi passwords. Recovery reuses an existing NetworkManager profile without reading or changing its authentication. Manage the profile through ChatEnv, then use `chatenv test -t chatnet -I` for configuration validation without network mutation.

## Guarded recovery

The command protects the foreground SSH path and persists the cooldown/hourly budget before its first mutation. Without module mode, it runs a bounded Wi-Fi rescan, activates the selected saved connection, and postchecks the gateway. Module mode also requires independent wired rescue, complete nonempty physical identity, and a driver bound to that adapter alone. Each command and postcheck persists `stage-started` before execution and `stage-finished` afterward with sanitized return codes; unmatched starts mean completion was not confirmed. `status=recovered` requires the actual active connection UUID to match the attempted target, matching physical instance/fingerprint and saved-profile identity, and a successful gateway postcheck. `recovered_at` is that postcheck's actual completion time. `connection_uuid` describes the selected saved profile; `active_connection_uuid` describes the observed active profile, never a substitution from configuration.

An execute observation made while the interface is present may cache a private recovery identity: interface, a saved-profile fingerprint (UUID, type, name, and binding), kernel device path and instance, kernel identity fingerprint, and derived module. If that interface later disappears, module-mode recovery is considered only when all of that evidence still matches. The kernel device must still exist, no replacement may occupy it, the module may control no other device, the saved profile selection must be unchanged, and the Ethernet/SSH safety checks must still pass. Missing or legacy identity, removed or replaced hardware, a changed profile, a shared module, or an unsafe management route blocks mutation. ChatNet never derives a driver from an interface name, accepts module options, or guesses a device.

This fallback is deliberately narrow. It cannot recover hardware that has vanished from sysfs, a device whose kernel instance changed, or an interface that does not return after the verified module reload. Live USB/driver behavior remains hardware-specific and must be validated by an operator.

Existing noninteractive sudo permissions are required for execution. The package does not install sudoers, silently escalate privileges, restart NetworkManager or the host, replace firmware/drivers, download dependencies, or execute caller-supplied commands.

## Durable events and retention

Profiles remain in `$CHATARCH_HOME/envs/ChatNet/`; locks, budgets, cached identity, and events use `$CHATARCH_HOME/chatnet/recovery/`. The default home is `~/.chatarch`. Directories and files are owner-only. Corrupt state, unsafe permissions, malformed event JSON, or a regressed clock fails closed; raw subprocess stderr is never stored or returned.

Events contain an epoch and timezone-qualified timestamp, `run_id`, a persistent `incident_id` for unhealthy observations, and `attempt_id` for actual attempts. They also carry the sanitized diagnosis, planned actions, stage outcomes, and terminal result. `detected_at` is the first observed unhealthy time, not an estimated physical disconnect time. Failures and blocks remain in the same open incident until a healthy observation; a later relapse starts another incident. Healthy no-ops always have `performed=false`. An interrupted attempt retains its durable `attempt-started` event (and active state) without an `attempt-finished` success; later health never rewrites that attempt as successful.

Retention is finite: eight JSONL segments with a 1 MiB rotation target (roughly 8 MiB plus at most one bounded event). `recovery logs` reads all retained segments safely, returns the newest 100 events by default, and accepts limits from 1 through 1000. Status and incident filters apply within retained data; they cannot recover rotated-out history. Recognized pre-0.2.4 metadata-only lines remain on disk through normal rotation but are omitted from versioned API results because they have no trustworthy run or incident identity. Python callers can use `check_recovery()`, `recover_network(execute=False)`, `read_recovery_logs()`, and `recovery_home()` from `chatnet.recovery`.

The installed package does not depend on a source checkout. Background watch/service commands remain outside this command surface.
