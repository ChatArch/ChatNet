# 离线网络恢复

首版聚焦 Linux + NetworkManager 的一次性诊断与受控恢复。先恢复真实网络、记录可工作的脚本，再按实际复发迭代；不要求首版覆盖所有驱动或故障，也不启动后台监控。

## 日常命令

```bash
chatnet recovery check
chatnet recovery run                 # 预演，不改变网络
chatnet recovery run --execute       # 显式执行一次
chatnet recovery check --json-output
```

诊断不健康或执行失败时返回非零。链路已健康时，`run --execute` 不重载驱动。公网探测单点失败但本地网关仍可达，不触发无线恢复。

## 一次性 ENV 配置

配置归属既有 ChatEnv `ChatNet` schema；读取顺序为进程环境优先于活动 profile。日常 CLI 不要求网卡、驱动或机器参数。

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

以上为示例，不是可直接用于当前网络的地址。`INTERFACE` 留空时要求仅存在一个无线接口；`CONNECTION` 是已保存连接的名称或 UUID，留空时要求可唯一选择。多个保存连接应显式选定，工具不会猜测。`RESCUE_PEER` 应是实际可经独立物理有线接口到达的管理对端。`MODULE_RELOAD` 默认为 false；模块名始终由内核推导，没有任意模块覆盖参数。

不要填写 Wi-Fi 密码：只激活 NetworkManager 已保存的连接，不读取、复制或更改认证资料。使用现有 ChatEnv 工具管理 profile，然后运行 `chatenv test -t chatnet -I` 验证配置；该验证不修改网络。

## 恢复路径和保护

1. 诊断目标及当前 SSH 路径；当前 SSH 经目标无线接口时拒绝恢复。
2. 未开启模块模式时，仅对原保存连接做有界扫描和重连。
3. 开启模块模式时，要求有独立物理有线救援路径且驱动只绑定一个设备，直接执行已实践过的模块卸载、加载、等待设备就绪、原连接激活路径；不让已知失效的扫描步骤阻挡该路径。
4. 重新检测网关，不把命令返回 0 当作恢复成功。

执行使用既有非交互 sudo 权限；工具不安装 sudoers、不重启 NetworkManager/主机，不下载驱动或固件。实际模块/权限或连接失败需保留证据，不能宣称已根治硬件问题。

## 状态与安装边界

```text
$CHATARCH_HOME/envs/ChatNet/       # 既有 ChatEnv profile
$CHATARCH_HOME/chatnet/recovery/  # 锁、预算、执行记录
```

未设置 `CHATARCH_HOME` 时使用 `~/.chatarch`。执行前持久化恢复预算，默认五分钟冷却、一小时最多三次；状态损坏或时钟回退时停止，不清零预算。日志只保留阶段和结果，不公开原始命令 stderr。安装依赖齐备后，无需源码 checkout 或断网时联网安装。

后台 watch/service 不属于本次首版命令面。Python 调用方可使用 `chatnet.recovery.check_recovery()`、`recover_network(execute=False)` 和 `recovery_home()`。
