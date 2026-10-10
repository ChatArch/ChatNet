"""A release must verify its real public PyPI artifact, not a checkout."""
from pathlib import Path
import yaml


def test_publish_verifies_public_install_in_fresh_ci_job_without_checkout():
    root = Path(__file__).resolve().parents[1]
    data = yaml.safe_load((root / '.github/workflows/publish.yml').read_text())
    job = data['jobs'].get('verify-public')
    assert job is not None, 'Public artifact verification job is missing'
    assert job['needs'] == 'publish'
    assert data['jobs']['publish']['outputs']['version'] == '${{ steps.meta.outputs.version }}'
    assert job['env']['PACKAGE_VERSION'] == '${{ needs.publish.outputs.version }}'
    assert 'runner.' not in str(job['env']), 'runner context is not available in job-level env'
    smoke = next(step for step in job['steps'] if step.get('name') == 'Verify public command and bundled infrastructure')
    assert smoke.get('env', {}).get('CHATARCH_HOME') == '${{ runner.temp }}/chatnet-public-state'
    assert all('actions/checkout' not in step.get('uses', '') for step in job['steps'])
    text = '\n'.join(step.get('run', '') for step in job['steps'])
    assert '--isolated --no-cache-dir --index-url https://pypi.org/simple' in text
    assert 'ChatNet==${PACKAGE_VERSION}' in text
    assert 'chatnet --tree' in text and 'chatnet recovery logs --json-output' in text
    assert "metadata.version('chatnet') == os.environ['PACKAGE_VERSION']" in text
    assert "files('chatnet').joinpath('data/systemd')" in text
