# CLI Tree

`chatnet --tree` renders the real command tree from the registered Click command surface. It is used for release acceptance and human readback so docs do not drift from source.

```text
chatnet # ChatNet generic network helper CLI
├── --help # Show help for the current command
├── --version # Show package version
├── --tree # Print the registered CLI tree
├── ping --network NETWORK [--concurrency CONCURRENCY] [--output OUTPUT] # Scan a network for active hosts using ICMP ping
├── ssh [--input INPUT-FILE] [--network NETWORK] [--port PORT] [--concurrency CONCURRENCY] [--output OUTPUT] # Scan IPs for open SSH or arbitrary TCP ports
├── links [--path PATH-VALUE] [--glob GLOBS] [--url URLS] [--filter FILTER-REGEX] [--timeout TIMEOUT] # Check URL validity from a file/directory or explicit list
├── services [--chromium-url CHROMIUM-URL] [--chromium-token CHROMIUM-TOKEN] [--chromedriver-url CHROMEDRIVER-URL] [--playwright-url PLAYWRIGHT-URL] [--timeout TIMEOUT] # Check that chromium/chromedriver/playwright URLs respond with expected content
└── proxy # Explicit forward proxy helpers
    ├── serve [--bind BIND] [--port PORT] [--allow-cidr ALLOW-CIDR] [--user USERNAME] [--password PASSWORD] [--timeout TIMEOUT] --interactive # Serve a non-sudo HTTP/HTTPS CONNECT forward proxy
    ├── check [--proxy-url PROXY-URL] [--url TARGET-URL] [--user USERNAME] [--password PASSWORD] [--expect-status EXPECT-STATUS] [--timeout TIMEOUT] --show-body --interactive # Check a URL through an explicit forward proxy
    └── autostart # Generate or install non-sudo user autostart files
        ├── print [--service-name SERVICE-NAME] [--bind BIND] [--port PORT] [--allow-cidr ALLOW-CIDR] [--user USERNAME] [--env-file ENV-FILE] [--python PYTHON-BIN] --interactive # Print a user systemd unit without writing files
        └── install [--service-name SERVICE-NAME] [--bind BIND] [--port PORT] [--allow-cidr ALLOW-CIDR] [--user USERNAME] [--env-file ENV-FILE] [--python PYTHON-BIN] --enable --interactive # Install a user systemd unit without sudo
```

## Acceptance checklist

- `chatnet --help` must expose `--tree`.
- `chatnet --tree` must list `ping`, `ssh`, `links`, `services`, and nested `proxy serve/check/autostart print/install`.
- The output must not contain the migrated `ecnu` application commands or the scaffold `hello` command.
- When commands are added or removed, update tests, this page, and README together.
