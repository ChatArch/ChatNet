# Recovery infrastructure / 恢复基础设施

The public package contains `chatnet/data/systemd/chatnet-recovery.service` and `.timer`. These are thin user-manager wrappers around the installed Python API/CLI, not a second recovery implementation. Nothing is enabled by `pip install`.

公开包自带用户级单元文件。安装 Python 包不会自动启动定时任务；既有恢复机制必须先确认唯一 owner。定时任务每 15 秒做一次检查，恢复冷却和预算仍由 ChatEnv 控制，不是每 15 秒重载一次驱动。

## Preconditions / 前提

- Linux with NetworkManager, the saved Wi-Fi profile and the corresponding non-interactive sudo permissions already configured. The package does not create sudoers or install a driver.
- Configure and validate the ChatEnv `ChatNet` profile. Module mode requires a separate physical wired rescue route; do not enable it while the only management path is the target radio.
- The default units expect the standard runtime at `$HOME/.chatarch/venv/bin/python` and application home `$HOME/.chatarch`. For an explicitly customized ChatArch home, adjust `WorkingDirectory`, `Environment` and `ExecStart` together before verification.
- Retain the private recovery state and its attempt budget. Never delete `state.json` to bypass a cap.

## Extract and verify / 提取与校验

Run with the installed standard runtime, not a checkout's Python:

```bash
"$HOME/.chatarch/venv/bin/python" - <<'PY'
from importlib.resources import files
from pathlib import Path
import os

root = Path.home() / '.chatarch/chatnet/recovery/unit-candidate'
root.mkdir(parents=True, exist_ok=True, mode=0o700)
for name in ('chatnet-recovery.service', 'chatnet-recovery.timer'):
    target = root / name
    if target.is_symlink():
        raise SystemExit('Refusing a symlink candidate')
    target.write_bytes(files('chatnet').joinpath('data/systemd', name).read_bytes())
    os.chmod(target, 0o600)
print(root)
PY
systemd-analyze --user verify \
  "$HOME/.chatarch/chatnet/recovery/unit-candidate/chatnet-recovery.service" \
  "$HOME/.chatarch/chatnet/recovery/unit-candidate/chatnet-recovery.timer"
```

## Cold update / 冷更新

Stop only the existing timer and wait for its oneshot to finish normally. Record the timer's previous enabled/active state. Do not stop an in-flight radio operation, restart the host or clear the ledger. Back up the exact previous units and state with private permissions before replacing them. If another system- or user-level owner is present, resolve that ownership first.

暂停原 timer，并等待它的 oneshot 正常退出；不要强停正在执行的网卡操作。私有备份原单元及状态，保留预算和已发生的日志。安装发布产物后，用上面的包内资源更新同一组单元，不开第二组 timer。

After validation, install the two candidate files into `$HOME/.config/systemd/user/`, then run `systemctl --user daemon-reload`. A pre-existing timer must return to its previous enabled/active state; a new installation is enabled only with explicit operator approval. Rollback restores only the backed-up units and package version, reloads the user manager and restores that recorded timer state. It must not overwrite events generated since the backup.

## Acceptance / 验收

- Read `systemctl --user show chatnet-recovery.timer` and the corresponding service result, plus several actual post-update firing timestamps. An inactive oneshot with a successful result is normal between timer firings.
- Read native events with the installed `chatnet recovery logs --json-output`, and separately read the user service journal. Stage start is not success; only a successful postcheck closes an incident.
- Validate the affected interface, default route, gateway and representative direct HTTPS independently. Gateway health is not a claim that every public service works.
- A healthy no-op does not prove the recovery command can repair a real fault. Capture a real incident or an explicitly authorized, bounded fault trial while preserving wired management, then compare command actions, native events and independent probes.
- Recovery does not prove that a recurring hardware/firmware fault is permanently cured. Preserve relapse events and report the observed interval, not an unlimited uptime promise.
