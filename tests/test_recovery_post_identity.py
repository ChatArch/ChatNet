"""A healthy replacement at the same sysfs path is not recovery proof."""
from dataclasses import replace
import shutil

import pytest

from test_recovery_operations import lab as lab
from test_recovery_core import recovery as recovery


@pytest.mark.parametrize('change', ['instance', 'fingerprint'])
def test_postcheck_rejects_changed_physical_identity_at_same_path(lab, change):
    api, net, settings, deps, home = lab
    settings = replace(settings, allow_module_reload=True)
    device = (deps['sys_root'] / 'class/net/wlan0/device').resolve()

    def replace_during_load(command):
        if command != ['modprobe', 'test_wifi']:
            return
        if change == 'instance':
            old = device.with_name(device.name + '-old')
            device.rename(old)
            shutil.copytree(old, device, symlinks=True)
        else:
            (device / 'uevent').write_text('DRIVER=test_wifi\nMODALIAS=pci:test_wifi\nPCI_ID=8765:4321\n')

    net.before_mutation = replace_during_load
    with pytest.raises(api.RecoveryError, match='identity-changed'):
        api.recover_network(settings, execute=True, home=home, **deps)
    events = api.read_recovery_logs(home=home)
    assert events[-1]['status'] == 'failed'
    assert events[-1]['reason'] == 'identity-changed'
    assert 'recovered_at' not in events[-1]
    ready = [e for e in events if e.get('stage') == 'device-ready']
    assert [e['status'] for e in ready] == ['started', 'failed']
    assert not any(e.get('status') == 'recovered' for e in events)
