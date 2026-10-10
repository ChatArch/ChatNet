"""Docs publication preserves only the existing reserved preview paths."""
import json
import os
from pathlib import Path
import subprocess
import sys

import yaml

ROOT = Path(__file__).resolve().parents[1]


def workflow(name):
    return yaml.safe_load((ROOT / '.github/workflows' / name).read_text())


def deployment_script():
    steps = workflow('deploy.yaml')['jobs']['deploy']['steps']
    candidates = [s['run'] for s in steps if s.get('name') == 'Build and deploy docs']
    assert len(candidates) == 1, 'preview-preserving deployment step is missing'
    return candidates[0]


def git(cwd, *args):
    return subprocess.run(['git', *args], cwd=cwd, text=True, capture_output=True, check=True, timeout=15).stdout


def run_publication(tmp_path, published):
    script = deployment_script()
    repo = tmp_path / 'repo'
    remote = tmp_path / 'remote.git'
    repo.mkdir()
    git(repo, 'init', '--initial-branch=master')
    git(repo, 'config', 'user.name', 'test')
    git(repo, 'config', 'user.email', 'test@example.invalid')
    (repo / 'tracked').write_text('source')
    git(repo, 'add', 'tracked')
    git(repo, 'commit', '-m', 'source')
    git(tmp_path, 'init', '--bare', str(remote))
    git(repo, 'remote', 'add', 'origin', str(remote))
    if published:
        git(repo, 'checkout', '-b', 'gh-pages')
        (repo / 'dev/en').mkdir(parents=True)
        (repo / 'dev/index.html').write_text('preview')
        (repo / 'dev/en/index.html').write_text('english preview')
        (repo / 'versions.json').write_text('[{"version":"dev"}]')
        (repo / 'obsolete.html').write_text('old production')
        git(repo, 'add', '.')
        git(repo, 'commit', '-m', 'published')
        git(repo, 'push', 'origin', 'gh-pages')
        git(repo, 'checkout', 'master')
    bins = tmp_path / 'bin'
    bins.mkdir()
    build = bins / 'mkdocs'
    build.write_text('#!' + sys.executable + '\nfrom pathlib import Path\nimport sys\nassert sys.argv[1:] == ["build","--strict"]\np=Path("site");p.mkdir();(p/"index.html").write_text("new production")\n')
    publish = bins / 'ghp-import'
    publish.write_text('#!' + sys.executable + '\nfrom pathlib import Path\nimport json\nPath("published-receipt.json").write_text(json.dumps(sorted(str(p.relative_to("site")) for p in Path("site").rglob("*") if p.is_file())))\n')
    build.chmod(0o700)
    publish.chmod(0o700)
    env = {**os.environ, 'PATH': str(bins) + os.pathsep + os.environ['PATH'], 'RUNNER_TEMP': str(tmp_path), 'GITHUB_SHA': 'test-commit', 'GIT_TERMINAL_PROMPT': '0'}
    result = subprocess.run(['bash', '-c', script], cwd=repo, env=env, capture_output=True, text=True, timeout=25)
    assert result.returncode == 0, result.stderr
    return repo, json.loads((repo / 'published-receipt.json').read_text())


def test_material_emoji_renderer_is_declared():
    text = (ROOT / 'mkdocs.yml').read_text()
    assert 'pymdownx.emoji:' in text
    assert 'material.extensions.emoji.twemoji' in text
    assert 'material.extensions.emoji.to_svg' in text


def test_preview_and_deploy_share_non_canceling_lock():
    for name in ('deploy.yaml', 'preview.yaml'):
        assert workflow(name).get('concurrency') == {'group': 'docs-pages', 'cancel-in-progress': False}


def test_no_published_branch_still_builds_fresh_production(tmp_path):
    _, files = run_publication(tmp_path, False)
    assert files == ['index.html']


def test_preview_and_versions_survive_without_obsolete_production(tmp_path):
    repo, files = run_publication(tmp_path, True)
    assert files == ['dev/en/index.html', 'dev/index.html', 'index.html', 'versions.json']
    assert not (tmp_path / 'docs-published').exists()
    assert 'docs-published' not in git(repo, 'worktree', 'list')
