# Offline network recovery

The first version provides one-shot diagnosis and guarded recovery on Linux with NetworkManager. Restore the real connection first, record the working procedure, then improve the CLI from observed incidents. It does not start a watchdog or claim to handle every driver failure.

```bash
chatnet recovery check
chatnet recovery run                 # read-only plan
chatnet recovery run --execute       # explicitly execute one attempt
chatnet recovery check --json-output
```

An unhealthy check or failed recovery exits nonzero. A healthy link is not reset. Failure of an optional external probe does not trigger a repair when the local gateway remains reachable.

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

Replace the example connection/peer with verified local values. An empty interface requires exactly one wireless interface. An empty connection requires an unambiguous saved Wi-Fi profile. Module reload defaults to false; the module is derived from the kernel and cannot be overridden. The rescue peer must route through an independent physical Ethernet interface with carrier.

Do not provide Wi-Fi passwords: existing NetworkManager authentication is reused unchanged. Manage the profile through ChatEnv, then run `chatenv test -t chatnet -I` for configuration validation without network mutations.

## Guarded recovery

The command protects the foreground SSH path. With module mode disabled it only attempts bounded scanning/reconnection. Explicit module mode requires a physical wired rescue path and a driver bound to exactly one device, then directly follows the proven sequence: module unload, module load, device settlement, and activation of the saved connection. A failed scan is not a prerequisite for that path. A fresh gateway check determines success.

Existing noninteractive sudo permissions are required for execution. The package does not install sudoers, restart NetworkManager/the host, replace firmware, or download dependencies during recovery. Recovery is mitigation, not proof of a permanent hardware fix.

Profiles remain in `$CHATARCH_HOME/envs/ChatNet/`; locks, budgets and metadata-only logs use `$CHATARCH_HOME/chatnet/recovery/`. The default home is `~/.chatarch`. Budgets are persisted before mutation: five-minute cooldown and at most three attempts per hour by default. Corrupt state or a regressed clock fails closed. Raw command stderr is not published.

The installed package does not depend on a source checkout. Background watch/service commands are outside this first version. Python callers can use `chatnet.recovery.check_recovery()`, `recover_network(execute=False)` and `recovery_home()`.
