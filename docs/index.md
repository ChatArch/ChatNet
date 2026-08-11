# ChatNet

ChatNet 提供 ChatArch 通用网络/门户 helper：ping/TCP 扫描、URL 收集和检查、浏览器服务健康检查、服务 URL 处理、浏览器式 session/cookie 状态，以及非 sudo 显式 forward proxy 服务。

ECNU 这类应用层门户逻辑属于 `ChatECNU`；ChatNet 只保留应用无关的网络基础能力。

## 常用入口

```bash
chatnet --help
chatnet --tree
chatnet links --url https://example.com
chatnet proxy autostart print --bind 0.0.0.0 --port 18080 --allow-cidr 172.23.0.0/16 --user chatnet
```

## 文档入口

- [CLI 树](cli-tree.md)：真实注册命令树、验收条目和更新规则。
