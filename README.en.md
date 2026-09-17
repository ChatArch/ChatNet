# ChatNet

ChatNet is the ChatArch generic network helper package. ECNU-specific portal automation has moved to `ChatECNU`.

Current generic helpers include ping/port scanning, URL/link checking, browser-service health checks, service URL helpers, browser-like session state, cookie persistence, simple HTML table parsing, request/curl preview helpers, non-sudo explicit forward proxy serving/checking/user autostart for trusted LAN clients, and ChatEnv metadata for `CHATNET_PROXY_*` defaults.


## Offline recovery

On Linux with NetworkManager, use `chatnet recovery check` and `chatnet recovery run --execute`. Hardware settings and thresholds come from ChatEnv, not daily CLI arguments. Runtime state stays under `CHATARCH_HOME`; recovery needs no source checkout or downloads.

See [offline recovery](docs/recovery.en.md) for permissions and persistent retry limits. The first version does not start a background watcher. Recovery is mitigation, not proof that the hardware fault is fixed.

## CLI Tree

Run `chatnet --tree` for the registered command surface with signatures or `chatnet --tree-brief` for the same nodes without signatures. Both views use ChatStyle's shared renderer and never include secret values.
