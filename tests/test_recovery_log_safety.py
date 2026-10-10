"""Malformed private evidence must fail promptly and without side effects."""
from dataclasses import replace
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import uuid

import pytest
from click.testing import CliRunner

from chatnet.cli import main
from chatnet import recovery_state as state_io
from test_recovery_core import recovery as recovery
from test_recovery_operations import lab as lab


def event(epoch=1000, version=1):
    return {'version': version, 'epoch': epoch, 'timestamp': datetime.fromtimestamp(1000, timezone.utc).isoformat(), 'event': 'run-finished', 'status': 'failed', 'run_id': str(uuid.uuid4())}


@pytest.mark.parametrize('kind', ['missing', 'no-identity-fields'])
def test_unavailable_physical_fingerprint_blocks_module_mutation(lab, kind):
    api, net, settings, deps, home = lab
    settings = replace(settings, allow_module_reload=True)
    path = (deps['sys_root'] / 'class/net/wlan0/device/uevent')
    if kind == 'missing':
        path.unlink()
    else:
        path.write_text('DRIVER=test_wifi\n')
    result = api.recover_network(settings, execute=True, home=home, **deps)
    assert result['status'] == 'blocked'
    assert result['reason'] == 'device-identity-unavailable'
    assert not result['performed'] and not net.mutations


@pytest.mark.parametrize('name,mode', [('events.jsonl', 'read'), ('events.1.jsonl', 'read'), ('events.jsonl', 'execute')])
def test_fifo_evidence_is_opened_nonblocking_then_rejected(lab, monkeypatch, name, mode):
    api, net, settings, deps, home = lab
    root = api.recovery_home(home)
    root.mkdir(parents=True, mode=0o700)
    fifo = root / name
    os.mkfifo(fifo, 0o600)
    original_open = os.open

    def prevent_blocking_open(path, flags, *args, **kwargs):
        if Path(path) == fifo:
            assert flags & os.O_NONBLOCK, 'Untrusted FIFO would block before its type can be rejected'
        return original_open(path, flags, *args, **kwargs)

    monkeypatch.setattr(state_io.os, 'open', prevent_blocking_open)
    with pytest.raises(api.RecoveryError, match='log-|state-'):
        if mode == 'read':
            api.read_recovery_logs(home=home)
        else:
            api.recover_network(replace(settings, allow_module_reload=True), execute=True, home=home, **deps)
    assert not net.mutations


@pytest.mark.parametrize('payload', [json.dumps(event(10 ** 400)) + '\n', json.dumps({'time': 10 ** 400, 'status': 'failed'}) + '\n', '[' * 1200 + '0' + ']' * 1200 + '\n'], ids=['oversized-epoch', 'oversized-legacy-time', 'deep-nesting'])
def test_bounded_malformed_payload_becomes_clean_domain_error(recovery, tmp_path, payload):
    root = recovery.recovery_home(tmp_path)
    root.mkdir(parents=True, mode=0o700)
    p = root / 'events.jsonl'
    p.write_text(payload)
    p.chmod(0o600)
    with pytest.raises(recovery.RecoveryError, match='log-invalid'):
        recovery.read_recovery_logs(home=tmp_path)


def test_log_cli_does_not_traceback_on_oversized_number(tmp_path, monkeypatch):
    monkeypatch.setenv('CHATARCH_HOME', str(tmp_path))
    p = tmp_path / 'chatnet/recovery/events.jsonl'
    p.parent.mkdir(parents=True, mode=0o700)
    p.write_text(json.dumps(event(10 ** 400)) + '\n')
    p.chmod(0o600)
    result = CliRunner().invoke(main, ['recovery', 'logs', '--json-output'])
    assert result.exit_code != 0
    assert 'log-invalid' in result.output
    assert 'Traceback' not in result.output
    assert not isinstance(result.exception, OverflowError)


@pytest.mark.parametrize('version', [True, 1.0])
def test_event_schema_version_requires_exact_integer(version):
    with pytest.raises(Exception, match='log-invalid'):
        state_io.validate_event(event(version=version))
