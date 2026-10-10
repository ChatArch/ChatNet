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


def _invoke(method: str, **kwargs):
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


@recovery_cli.command(name="logs")
@click.option(
    "--limit",
    type=click.IntRange(1, 1000),
    default=100,
    show_default=True,
    help="Maximum retained events to print.",
)
@click.option("--status", help="Show events with this status only.")
@click.option("--incident-id", help="Show events for one incident UUID only.")
@click.option("--json-output", is_flag=True, help="Print validated event JSON.")
def recovery_logs(
    limit: int, status: str | None, incident_id: str | None, json_output: bool
):
    """Read retained private recovery events; never inspect hardware."""
    events = _invoke(
        "read_recovery_logs",
        limit=limit,
        status=status,
        incident_id=incident_id,
    )
    if json_output:
        click.echo(json.dumps(events, ensure_ascii=False, allow_nan=False))
        return
    if not events:
        click.echo("没有匹配的恢复事件")
        return
    for event in events:
        detail = event.get("reason") or event.get("stage") or event["event"]
        click.echo(f"{event['timestamp']}  {event['status']:<16}  {detail}")


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
