# CLI Tree

ChatNet uses the shared `chatstyle.add_tree_option()` runtime to render its real Click registry. `chatnet --tree` includes parameter signatures; `chatnet --tree-brief` keeps the same nodes and summaries without signatures.

## Full tree

```text
chatnet
├── --help  # Show this message and exit.
├── --version  # Show the version and exit.
├── --tree  # Print the registered CLI tree and exit.
├── --tree-brief  # Print the registered CLI tree without parameter signatures and exit.
├── links [--path PATH-VALUE] [--glob GLOBS] [--url URLS] [--filter FILTER-REGEX] [--timeout TIMEOUT]  # Check URLs; reads local paths and sends HTTP requests.
├── ping [--network NETWORK] [--concurrency CONCURRENCY] [--output OUTPUT]  # Scan hosts with ICMP; sends network traffic and may write --output.
├── proxy  # Run explicit proxy helpers; credentials stay masked.
│   ├── autostart  # Create non-sudo user systemd autostart artifacts.
│   │   ├── install [--service-name SERVICE-NAME] [--bind BIND] [--port PORT] [--allow-cidr ALLOW-CIDR] [--user USERNAME] [--env-file ENV-FILE] [--python PYTHON-BIN] [--enable] [--interactive]  # Write a user systemd unit and optionally enable it.
│   │   └── print [--service-name SERVICE-NAME] [--bind BIND] [--port PORT] [--allow-cidr ALLOW-CIDR] [--user USERNAME] [--env-file ENV-FILE] [--python PYTHON-BIN] [--interactive]  # Render a user systemd unit; read-only text output.
│   ├── check [--proxy-url PROXY-URL] [--url TARGET-URL] [--user USERNAME] [--password PASSWORD] [--expect-status EXPECT-STATUS] [--timeout TIMEOUT] [--show-body] [--interactive]  # Check a URL via proxy; sends a request and redacts the proxy URL.
│   └── serve [--bind BIND] [--port PORT] [--allow-cidr ALLOW-CIDR] [--user USERNAME] [--password PASSWORD] [--timeout TIMEOUT] [--interactive]  # Serve a forward proxy; long-running listener with no secret output.
├── services [--chromium-url CHROMIUM-URL] [--chromium-token CHROMIUM-TOKEN] [--chromedriver-url CHROMEDRIVER-URL] [--playwright-url PLAYWRIGHT-URL] [--timeout TIMEOUT]  # Check browser services; sends requests and redacts Chromium tokens.
└── ssh [--input INPUT-FILE] [--network NETWORK] [--port PORT] [--concurrency CONCURRENCY] [--output OUTPUT]  # Scan TCP ports; sends network traffic and may write --output.
```

## Brief tree

```text
chatnet
├── --help  # Show this message and exit.
├── --version  # Show the version and exit.
├── --tree  # Print the registered CLI tree and exit.
├── --tree-brief  # Print the registered CLI tree without parameter signatures and exit.
├── links  # Check URLs; reads local paths and sends HTTP requests.
├── ping  # Scan hosts with ICMP; sends network traffic and may write --output.
├── proxy  # Run explicit proxy helpers; credentials stay masked.
│   ├── autostart  # Create non-sudo user systemd autostart artifacts.
│   │   ├── install  # Write a user systemd unit and optionally enable it.
│   │   └── print  # Render a user systemd unit; read-only text output.
│   ├── check  # Check a URL via proxy; sends a request and redacts the proxy URL.
│   └── serve  # Serve a forward proxy; long-running listener with no secret output.
├── services  # Check browser services; sends requests and redacts Chromium tokens.
└── ssh  # Scan TCP ports; sends network traffic and may write --output.
```

## Acceptance checklist

- `chatnet --help` must expose `--tree` and `--tree-brief`.
- `chatnet --tree` must list `ping`, `ssh`, `links`, `services`, and nested `proxy serve/check/autostart print/install`.
- `chatnet --tree-brief` must retain the same commands and purpose summaries while omitting signatures.
- The output must not contain the migrated `ecnu` application commands or the scaffold `hello` command.
- Passwords and tokens may appear only as option names; values must never enter tree output or runtime summaries.
- When commands are added or removed, update registry tests, this page, and README together.
