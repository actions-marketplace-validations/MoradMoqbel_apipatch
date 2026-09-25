"""
Tests for ApiPatch Manifest Version Bumper
Verifies bumping of requirements.txt, pyproject.toml, and package.json.
"""

import json
from apipatch.manifest_bumper import ManifestBumper


def test_bump_requirements_txt_pydantic():
    old_content = "openai==0.28.0\npydantic<2.0.0\nfastapi==0.95.0\n"
    new_content, changed = ManifestBumper.bump_requirements_txt(old_content, {"pydantic", "openai"})
    assert changed is True
    assert "pydantic>=2.0.0" in new_content
    assert "openai>=1.0.0" in new_content
    assert "fastapi==0.95.0" in new_content


def test_bump_requirements_txt_no_change_when_already_modern():
    old_content = "pydantic>=2.0.0\nopenai>=1.0.0\n"
    new_content, changed = ManifestBumper.bump_requirements_txt(old_content, {"pydantic", "openai"})
    assert changed is False
    assert new_content == old_content


def test_bump_package_json():
    old_data = {
        "name": "my-app",
        "dependencies": {
            "@supabase/supabase-js": "^1.35.0",
            "express": "^4.18.0"
        }
    }
    old_json = json.dumps(old_data, indent=2)
    new_json, changed = ManifestBumper.bump_package_json(old_json, {"@supabase/supabase-js"})
    assert changed is True
    parsed = json.loads(new_json)
    assert parsed["dependencies"]["@supabase/supabase-js"] == "^2.0.0"
    assert parsed["dependencies"]["express"] == "^4.18.0"


def test_bump_pyproject_toml():
    old_content = """\
[project]
name = "demo"
dependencies = [
    "pydantic<=1.10.12",
    "requests>=2.25.0",
    "openai<1.0.0"
]
"""
    new_content, changed = ManifestBumper.bump_pyproject_toml(old_content, {"pydantic", "openai"})
    assert changed is True
    assert '"pydantic>=2.0.0"' in new_content
    assert '"openai>=1.0.0"' in new_content
    assert '"requests>=2.25.0"' in new_content


def test_sync_local_manifests_monorepo_nested(tmp_path):
    subproject_a = tmp_path / "apps" / "service_a"
    subproject_a.mkdir(parents=True)
    req_a = subproject_a / "requirements.txt"
    req_a.write_text("openai==0.28.0\n", encoding="utf-8")

    subproject_b = tmp_path / "apps" / "service_b"
    subproject_b.mkdir(parents=True)
    pkg_b = subproject_b / "package.json"
    pkg_b.write_text('{"dependencies": {"@supabase/supabase-js": "^1.35.0"}}', encoding="utf-8")

    records = ManifestBumper.bump_local_manifests(str(tmp_path), {"openai", "@supabase/supabase-js"}, write=True)

    assert len(records) == 2
    assert "openai>=1.0.0" in req_a.read_text(encoding="utf-8")
    assert "^2.0.0" in pkg_b.read_text(encoding="utf-8")


def test_successor_package_replacement():
    # google-generativeai should be cleanly migrated to google-genai
    old_content = "requests>=2.28.0\ngoogle-generativeai==0.3.0\nfastapi>=0.100.0\n"
    new_content, changed = ManifestBumper.bump_requirements_txt(old_content, {"google.generativeai", "google-genai"})
    assert changed is True
    assert "google-genai>=0.1.0" in new_content
    assert "google-generativeai" not in new_content
    assert "requests>=2.28.0" in new_content


def test_append_missing_modern_package():
    # If a subproject uses google-genai or langchain-anthropic but it's not in requirements.txt, auto-append it
    old_content = "requests>=2.28.0\npytest>=8.0.0\n"
    new_content, changed = ManifestBumper.bump_requirements_txt(old_content, {"google-genai", "langchain-anthropic"})
    assert changed is True
    assert "google-genai>=0.1.0" in new_content
    assert "langchain-anthropic>=0.1.0" in new_content
    assert "requests>=2.28.0" in new_content


def test_bump_pyproject_toml_successor():
    old_content = """\
[project]
name = "demo"
dependencies = [
    "google-generativeai<=0.3.0",
    "requests>=2.25.0"
]
"""
    new_content, changed = ManifestBumper.bump_pyproject_toml(old_content, {"google.generativeai"})
    assert changed is True
    assert '"google-genai>=0.1.0"' in new_content
    assert "google-generativeai" not in new_content


