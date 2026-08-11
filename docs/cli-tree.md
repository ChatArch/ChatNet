# CLI 树

`chatnet --tree` 会从当前 Click 注册表生成真实命令树。它用于 release 验收和人工排查，避免 README 或文档里的手写命令列表和源码漂移。

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

## 验收条目

- `chatnet --help` 必须显示 `--tree`。
- `chatnet --tree` 必须列出 `ping`、`ssh`、`links`、`services`、`proxy serve/check/autostart print/install`。
- 输出不得包含已迁出的 `ecnu` 业务命令，也不得包含模板 `hello` 命令。
- 新增/删除 CLI 命令时，同步更新测试、本页和 README。
