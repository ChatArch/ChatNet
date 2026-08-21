# CLI 树

ChatNet 使用共享的 `chatstyle.add_tree_option()` 从 Click 注册表生成真实命令树。`chatnet --tree` 包含参数签名，`chatnet --tree-brief` 保留相同节点和说明但省略签名。

## 完整树

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

## 简版树

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

## 验收条目

- `chatnet --help` 必须显示 `--tree` 和 `--tree-brief`。
- `chatnet --tree` 必须列出 `ping`、`ssh`、`links`、`services`、`proxy serve/check/autostart print/install`。
- `chatnet --tree-brief` 必须保留相同命令和用途说明，但不显示参数签名。
- 输出不得包含已迁出的 `ecnu` 业务命令，也不得包含模板 `hello` 命令。
- 密码和 token 只能以选项名出现；值不得写入树或运行摘要。
- 新增/删除 CLI 命令时，同步更新注册表测试、本页和 README。
