# ChatNet

ChatNet is the ChatArch generic network helper package. It owns reusable network and portal/session helpers such as:

- ICMP ping scanning and TCP port scanning;
- URL collection and link checking;
- browser/chromedriver/playwright service URL health checks;
- service URL helpers such as `append_token()` and `ensure_path()`;
- browser-like `requests.Session` setup with common headers;
- state-file backed cookie persistence;
- cookie header parsing/export;
- simple HTML table parsing helpers;
- safe request-spec / curl-preview generation for dry-run workflows;
- non-sudo explicit forward proxy serving, checking, and user autostart for trusted LAN clients.

Application-level campus portal logic belongs in packages such as `ChatECNU`, which depends on ChatNet for generic network and portal helpers.

## Quick start

```bash
pip install -e ".[dev]"
chatnet --help
chatnet --tree
chatnet --tree-brief
chatnet links --url https://example.com
CHATNET_PROXY_PASSWORD='<password>' chatnet proxy serve --bind 0.0.0.0 --port 18080 --allow-cidr 172.23.0.0/16 --user chatnet
CHATNET_PROXY_PASSWORD='<password>' chatnet proxy check --proxy-url http://127.0.0.1:18080 --user chatnet
chatnet proxy autostart print --bind 0.0.0.0 --port 18080 --allow-cidr 172.23.0.0/16 --user chatnet
chatenv status -t chatnet --detail
python -m pytest -q
```

`chatnet --tree` renders the registered command surface with signatures through ChatStyle; `chatnet --tree-brief` renders the same nodes without signatures. Tree output names sensitive options but never contains their values.

Proxy defaults can also come from ChatEnv under `$CHATARCH_HOME/envs/ChatNet/.env`:

```bash
CHATNET_PROXY_BIND='127.0.0.1'
CHATNET_PROXY_PORT='18080'
CHATNET_PROXY_ALLOW_CIDR='127.0.0.0/8'
CHATNET_PROXY_USER='chatnet'
CHATNET_PROXY_PASSWORD='<password>'
```

## 离线网络恢复

Linux + NetworkManager 可使用 `chatnet recovery check` 诊断、`chatnet recovery run --execute --json-output` 受控恢复，并用 `chatnet recovery logs` 读取带时间、incident 和阶段结果的私有持久事件。设备信息和阈值由 ChatEnv 管理，不放进日常命令参数。运行态遵循 `CHATARCH_HOME`，不依赖项目目录或联网下载。

参见 [离线网络恢复](docs/recovery.md)，包括权限、冷却、有限日志保留和持久化恢复预算。接口消失回退只接受先前缓存且当前仍可核验的内核设备/驱动身份、未改变的连接以及独立物理有线救援路径；同一设备的 `DRIVER` 绑定字段消失不会单独阻止核验，旧缓存须精确核验后迁移。模块加载后还须确认原设备已绑定并出现目标无线接口。不满足任一条件便停止。只提供一次性恢复，不启用后台监控。恢复是缓解措施，不等于修复硬件根因。

## Boundary

ChatNet should stay application-neutral. ECNU login, visitor management, ECNU-specific ChatEnv schema, and ECNU CAPTCHA behavior belong in `ChatECNU`, not in ChatNet.
