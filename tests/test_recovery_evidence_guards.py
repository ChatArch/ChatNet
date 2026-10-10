"""Do not report a repair without the right profile and intact evidence."""
from dataclasses import replace
import os

import pytest

from test_recovery_operations import lab as lab, UUID
from test_recovery_core import recovery as recovery
from test_recovery_events import StepClock, RADIO_COMMAND

CONNECT = ('nmcli', '--wait', '30', 'connection', 'up', 'uuid', UUID, 'ifname', 'wlan0')
OTHER = 'aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee'


def test_explicit_saved_selector_cannot_mask_other_active_profile(lab):
    api, net, settings, deps, home = lab
    settings = replace(settings, connection=UUID, allow_module_reload=True)
    net.fail[CONNECT] = (4, 'SECRET=password')

    def another_profile(command):
        if tuple(command) == CONNECT:
            net.current_uuid = OTHER
            net.gateway_ok = True

    net.before_mutation = another_profile
    result = api.recover_network(settings, execute=True, home=home, **deps)
    assert not result['ok']
    assert result['status'] == 'failed' and result['reason'] == 'identity-changed'
    assert result['active_connection_uuid'] == OTHER
    assert 'recovered_at' not in result
    terminal = api.read_recovery_logs(home=home)[-1]
    assert terminal['status'] == 'failed'
    assert terminal['diagnosis']['active_connection_uuid'] == OTHER


def test_every_stage_has_durable_start_before_terminal_event(lab):
    api, net, settings, deps, home = lab
    settings = replace(settings, allow_module_reload=True)
    result = api.recover_network(settings, execute=True, home=home, clock=StepClock(1000), **deps)
    assert result['status'] == 'recovered'
    events = api.read_recovery_logs(home=home)
    starts = {e['stage']: e for e in events if e['event'] == 'stage-started'}
    ends = {e['stage']: e for e in events if e['event'] == 'stage-finished'}
    assert set(starts) == set(ends) == {'module-unload', 'module-load', 'device-ready', 'reconnect', 'postcheck'}
    for stage in starts:
        assert starts[stage]['epoch'] < ends[stage]['epoch']
        assert starts[stage]['attempt_id'] == ends[stage]['attempt_id'] == result['attempt_id']


@pytest.mark.parametrize('stage', ['module-unload', 'postcheck'])
def test_interruption_identifies_in_flight_stage(lab, stage):
    api, net, settings, deps, home = lab
    settings = replace(settings, allow_module_reload=True)
    if stage == 'module-unload':
        def interrupt(_command):
            raise KeyboardInterrupt
        net.before_mutation = interrupt
    else:
        def interrupt_postcheck(argv, **kwargs):
            if tuple(argv) == RADIO_COMMAND and net.loaded:
                raise KeyboardInterrupt
            return net(argv, **kwargs)
        deps['runner'] = interrupt_postcheck
    with pytest.raises(KeyboardInterrupt):
        api.recover_network(settings, execute=True, home=home, clock=StepClock(1000), **deps)
    events = api.read_recovery_logs(home=home)
    starts = [e for e in events if e['event'] == 'stage-started' and e['stage'] == stage]
    assert len(starts) == 1
    assert not any(e['event'] == 'stage-finished' and e['stage'] == stage for e in events)


@pytest.mark.parametrize('name', ['events.jsonl', 'events.1.jsonl', 'events.previous.jsonl'])
def test_malformed_retained_history_blocks_all_mutation(lab, name):
    api, net, settings, deps, home = lab
    settings = replace(settings, allow_module_reload=True)
    root = api.recovery_home(home)
    root.mkdir(parents=True, mode=0o700)
    path = root / name
    bad = '{"status":"failed"}\n'
    path.write_text(bad)
    path.chmod(0o600)
    with pytest.raises(api.RecoveryError, match='log-invalid'):
        api.recover_network(settings, execute=True, home=home, **deps)
    assert not net.mutations
    assert path.read_text() == bad


@pytest.mark.parametrize('unsafe', ['mode', 'symlink', 'hardlink'])
def test_unsafe_retained_archive_blocks_mutation(lab, unsafe):
    api, net, settings, deps, home = lab
    settings = replace(settings, allow_module_reload=True)
    root = api.recovery_home(home)
    root.mkdir(parents=True, mode=0o700)
    target = root / 'history-target.jsonl'
    target.write_text('{"time":900,"status":"failed","reason":"postcheck-failed"}\n')
    target.chmod(0o600)
    archive = root / 'events.1.jsonl'
    if unsafe == 'symlink':
        archive.symlink_to(target)
    elif unsafe == 'hardlink':
        os.link(target, archive)
    else:
        archive.write_bytes(target.read_bytes())
        archive.chmod(0o644)
    with pytest.raises(api.RecoveryError, match='log-|state-'):
        api.recover_network(settings, execute=True, home=home, **deps)
    assert not net.mutations
