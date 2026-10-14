# 离线网络恢复

ChatNet 为 Linux + NetworkManager 提供一次性诊断和受保护的恢复；它不会启动后台看门狗，也不宣称修复硬件根因。

## 日常命令

```bash
chatnet recovery check
chatnet recovery check --json-output
chatnet recovery run                         # 只读预演
chatnet recovery run --execute --json-output # 执行一次受保护恢复
chatnet recovery logs --limit 100
chatnet recovery logs --status failed --json-output
chatnet recovery logs --incident-id <uuid>
```

诊断不健康或执行失败时返回非零。`check` 会读取网络状态，但不读取或写入恢复状态；预演也不创建状态。每次 `run --execute` 都写入原生结果，包括健康空操作、安全阻止和检查错误。链路健康时不重置网络；本地网关仍可达时，公网探测单点失败不会触发恢复。

## ChatEnv 配置

配置归属既有 ChatEnv `ChatNet` schema；进程环境优先于活动 profile。日常 CLI 不接收网卡、驱动或机器参数。

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

以上连接和地址仅为示例，应替换为已核验的本地值。`INTERFACE` 留空时必须只有一个无线接口；`CONNECTION` 留空时必须能唯一选择已保存的 Wi-Fi profile。模块重载默认关闭；模块名只从内核证据推导，不能通过 CLI 指定。救援对端必须经带 carrier 的独立物理以太网接口到达。

不要提供 Wi-Fi 密码。恢复只复用 NetworkManager 的既有 profile，不读取或修改认证信息。通过 ChatEnv 管理 profile，再用 `chatenv test -t chatnet -I` 做不修改网络的配置校验。

## 恢复路径和保护

命令保护当前 SSH 路径，并在首次修改网络前持久化冷却和每小时预算。未启用模块模式时，只执行有界 Wi-Fi 扫描、激活选定连接并复查网关。模块模式还要求独立有线救援路径、完整非空的物理身份和仅绑定该适配器的驱动，再依次执行模块卸载、模块加载、设备等待、既有连接激活和复查。每个命令与复查都在开始前持久化 `stage-started`，完成后写入 `stage-finished` 及净化后的返回码；未匹配的开始记录明确表示该阶段未确认完成。只有实际活动连接 UUID 等于尝试目标，设备实例、指纹和 profile 身份一致，且网关复查成功，才返回 `status=recovered`；`recovered_at` 是复查实际完成时间。诊断中的 `connection_uuid` 是选定的保存连接，`active_connection_uuid` 是现场活动连接，不用配置值替代现场事实。

接口存在时的一次 execute 观察可以缓存私有恢复身份：接口、已保存 profile 的指纹（UUID、类型、名称和绑定）、内核设备路径和实例、带版本的内核身份指纹以及推导出的模块。指纹排除 uevent 中的 `DRIVER` 绑定字段，因此仅此字段和无线接口消失不会改变物理身份；设备路径和 inode 必须一致，产品、modalias、序列号等其余 uevent 证据仍参与核验。0.2.4 旧缓存迁移时不清除尝试预算或事件历史；若设备已解绑，旧原始指纹必须与使用已核验模块的唯一注册驱动精确重建的原始内容一致。旧证据无法唯一核验、profile 或物理身份不完整、缓存版本未知、硬件移除或更换、profile 改变、模块共享、有线或 SSH 路径不安全时一律拒绝修改。ChatNet 不从接口名猜驱动、不接受模块选项，也不猜设备。

模块加载和有界 `udevadm settle` 后，`device-ready` 先确认原物理实例、目标模块的唯一绑定及目标无线接口，再尝试连接。模块命令返回零不代表驱动探测成功；探测失败会记录阶段和尝试失败，消耗既有预算，只有冷却结束后才能再次尝试。sysfs 中已消失的硬件、内核设备实例已改变的硬件、重载后接口仍未返回的情况不能恢复；旧 `DRIVER` 行无法精确重建时也会安全阻止。真实 USB/驱动行为依赖硬件，仍需操作员现场验证。

执行要求既有非交互 sudo 权限。工具不安装 sudoers、不静默提权、不重启 NetworkManager 或主机、不替换固件/驱动、不联网下载，也不执行调用方提供的任意命令。

## 持久事件和保留边界

```text
$CHATARCH_HOME/envs/ChatNet/       # 既有 ChatEnv profile
$CHATARCH_HOME/chatnet/recovery/  # 锁、预算、缓存身份和事件
```

未设置 `CHATARCH_HOME` 时使用 `~/.chatarch`。目录和文件仅所有者可访问。状态损坏、权限不安全、事件 JSON 形状错误或时钟回退都会停止执行；原始子进程 stderr 永不写入或返回。

事件包含 epoch、带时区时间、`run_id`、不健康期间持久的 `incident_id`，以及实际尝试的 `attempt_id`，并记录净化后的诊断、动作、阶段结果和终态。`detected_at` 是首次观察到不健康的时间，不是猜测的物理断线时间。失败和阻止保持在同一开放 incident，直到观察到健康；之后再次复发会创建新 incident。健康空操作始终为 `performed=false`。被中断的尝试保留已落盘的 `attempt-started`（及活动状态），但没有成功的 `attempt-finished`；后续健康也不会倒推该尝试成功。

保留量有限：8 个 JSONL 分段，每段以 1 MiB 为轮转目标（约 8 MiB，另加至多一个有界事件）。`recovery logs` 安全读取全部仍保留的分段，默认返回最新 100 条，`--limit` 范围为 1 到 1000。状态和 incident 过滤只作用于保留范围，不能找回已轮转删除的历史。升级时会严格识别并继续保留 0.2.4 之前的元数据行，但它们没有可信的 run/incident 身份，因此不进入新版 API 结果。Python 调用方可使用 `chatnet.recovery` 中的 `check_recovery()`、`recover_network(execute=False)`、`read_recovery_logs()` 和 `recovery_home()`。

已安装包不依赖源码 checkout。后台 watch/service 不属于本命令面。
