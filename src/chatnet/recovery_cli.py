"""Thin CLI for ENV-backed offline recovery; no hardware command options."""

from __future__ import annotations
import json
import click


def _core():
    from chatnet import recovery

    return recovery


def _emit(result: dict, json_output: bool) -> None:
    if json_output:
        click.echo(json.dumps(result, ensure_ascii=False, allow_nan=False))
        return
    labels = {
        "healthy": "网络正常",
        "unhealthy": "网络异常",
        "planned": "恢复预演（未执行）",
        "dry-run": "恢复预演（未执行）",
        "recovered": "网络已恢复",
        "failed": "恢复失败",
        "blocked": "安全检查未通过",
        "cooldown": "恢复冷却中",
        "rate_limited": "达到恢复次数上限",
        "stopped": "监测已停止",
        "not_needed": "无需恢复",
        "installed": "服务已安装",
        "running": "服务运行中",
    }
    click.echo(labels.get(result.get("status"), "网络恢复状态已更新"))
    if result.get("reason"):
        click.echo("原因：" + str(result["reason"]))


def _invoke(method: str, **kwargs) -> dict:
    api = _core()
    try:
        return getattr(api, method)(**kwargs)
    except api.RecoveryError as exc:
        raise click.ClickException(str(exc)) from None


@click.group(name="recovery")
def recovery_cli():
    """Diagnose and recover locally; settings come from ChatEnv."""


@recovery_cli.command(name="check")
@click.option("--json-output", is_flag=True, help="Print safe diagnostic JSON.")
def recovery_check(json_output: bool):
    """Check the configured link; never change network state."""
    result = _invoke("check_recovery")
    _emit(result, json_output)
    if not result.get("healthy"):
        raise click.exceptions.Exit(1)


@recovery_cli.command(name="run")
@click.option(
    "--execute", is_flag=True, help="Explicitly permit one bounded recovery attempt."
)
@click.option("--json-output", is_flag=True, help="Print safe plan or result JSON.")
def recovery_run(execute: bool, json_output: bool):
    """Plan a recovery, or execute it with safety and budget checks."""
    result = _invoke("recover_network", execute=execute)
    _emit(result, json_output)
    if not result.get("ok"):
        raise click.exceptions.Exit(1)
