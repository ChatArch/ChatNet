from pathlib import Path

from chatstyle import render_click_tree

from chatnet.cli import main

ROOT = Path(__file__).resolve().parents[1]


def _text_blocks(path: Path) -> list[str]:
    text = path.read_text(encoding="utf-8")
    return [chunk.split("```", 1)[0].rstrip() for chunk in text.split("```text\n")[1:]]


def test_runtime_and_docs_dependency_contract():
    pyproject = (ROOT / "pyproject.toml").read_text(encoding="utf-8")

    assert '"chatenv>=0.2.10,<0.3.0"' in pyproject
    assert '"chatstyle>=0.2.0,<0.3.0"' in pyproject
    assert '"click>=8.0,<9.0"' in pyproject
    assert '"requests>=2.0,<3.0"' in pyproject
    assert 'chatnet = "chatnet.config"' in pyproject
    assert '"mkdocs-material>=9.5,<9.7"' in pyproject
    assert "site/" in (ROOT / ".gitignore").read_text(encoding="utf-8").splitlines()


def test_publish_workflow_is_tag_only_oidc_and_master_guarded():
    workflow = (ROOT / ".github" / "workflows" / "publish.yml").read_text(encoding="utf-8")

    assert "tags:" in workflow
    assert "workflow_dispatch" not in workflow
    assert "id-token: write" in workflow
    assert "pypa/gh-action-pypi-publish@release/v1" in workflow
    assert "git fetch --no-tags origin master:refs/remotes/origin/master" in workflow
    assert 'git merge-base --is-ancestor "${GITHUB_SHA}" refs/remotes/origin/master' in workflow
    legacy_secret_markers = ["PYPI" + "_API_TOKEN", "TWINE" + "_PASSWORD", "secrets" + ".PYPI"]
    assert all(marker not in workflow for marker in legacy_secret_markers)


def test_ci_checks_installed_full_and_brief_trees_and_distributions():
    workflow = (ROOT / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")

    assert 'python-version: ["3.10", "3.11", "3.12"]' in workflow
    assert "chatnet --version" in workflow
    assert "chatnet --tree" in workflow
    assert "chatnet --tree-brief" in workflow
    assert "python -m build" in workflow
    assert "python -m twine check dist/*" in workflow
    assert '"$RUNNER_TEMP/chatnet-wheel/bin/python" -m pip install dist/*.whl' in workflow
    assert "mkdocs build --strict" in workflow


def test_docs_preview_uses_configured_chatarch_site_url():
    preview = (ROOT / ".github" / "workflows" / "preview.yaml").read_text(encoding="utf-8")

    assert "CHATARCH_PREVIEW_URL" in preview
    assert "site_url=$(python" in preview
    assert "mkdocs.yml" in preview
    assert "github.io" not in preview


def test_public_docs_expose_full_and_brief_tree_commands():
    checked = [
        ROOT / "README.md",
        ROOT / "README.en.md",
        ROOT / "docs" / "index.md",
        ROOT / "docs" / "index.en.md",
        ROOT / "docs" / "cli-tree.md",
        ROOT / "docs" / "cli-tree.en.md",
    ]
    for path in checked:
        text = path.read_text(encoding="utf-8")
        assert "chatnet --tree" in text, path
        assert "chatnet --tree-brief" in text, path


def test_bilingual_cli_tree_docs_match_registered_full_and_brief_trees():
    expected = [
        render_click_tree(main, root_name="chatnet"),
        render_click_tree(main, root_name="chatnet", brief=True),
    ]

    for path in (ROOT / "docs" / "cli-tree.md", ROOT / "docs" / "cli-tree.en.md"):
        text = path.read_text(encoding="utf-8")
        assert "chatstyle.add_tree_option()" in text
        assert _text_blocks(path)[:2] == expected
