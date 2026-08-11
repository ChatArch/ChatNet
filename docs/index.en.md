# ChatNet

ChatNet provides generic ChatArch network and portal helper primitives: ping/TCP scans, URL collection and checks, browser-service health checks, service URL helpers, browser-like session/cookie state, and non-sudo explicit forward proxy helpers.

Application-level ECNU portal logic belongs in `ChatECNU`; ChatNet stays application-neutral.

## Common entrypoints

```bash
chatnet --help
chatnet --tree
chatnet links --url https://example.com
chatnet proxy autostart print --bind 0.0.0.0 --port 18080 --allow-cidr 172.23.0.0/16 --user chatnet
```

## Documentation

- [CLI Tree](cli-tree.md): registered command tree, acceptance checks, and update rules.
