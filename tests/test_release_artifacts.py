from __future__ import annotations

import json
import tomllib
from pathlib import Path

import google_tasks_mcp


ROOT = Path(__file__).resolve().parents[1]
EXPECTED_VERSION = "0.3.0"
EXPECTED_TOOLS = [
    "list_tasklists",
    "create_tasklist",
    "get_tasklist",
    "update_tasklist",
    "delete_tasklist",
    "list_tasks",
    "clear_completed",
    "today",
    "overdue",
    "upcoming",
    "search",
    "get_task",
    "digest",
    "add",
    "complete",
    "update",
    "uncomplete",
    "delete",
    "move",
]


def _read(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def test_vps_templates_use_placeholders_only():
    caddyfile = _read("deploy/caddy/Caddyfile")
    combined = "\n".join(
        [
            caddyfile,
            _read("deploy/systemd/google-tasks-mcp.service"),
            _read(".env.example"),
        ]
    )

    site_address = next(line.strip() for line in caddyfile.splitlines() if line.strip())
    assert site_address == "{$GOOGLE_TASKS_MCP_DOMAIN:tasks.example.com} {"
    assert "your-domain.example" not in combined
    assert "MCP_BEARER_TOKEN=" in combined


def test_root_docker_files_exist_and_exclude_secrets():
    dockerfile = _read("Dockerfile")
    dockerignore = _read(".dockerignore")
    compose = _read("docker-compose.yml")

    assert '"python", "-m", "google_tasks_mcp", "--transport", "http"' in dockerfile
    assert "USER google-tasks" in dockerfile
    assert "127.0.0.1:8787:8787" in compose
    assert "google-tasks-data:/var/lib/google-tasks-mcp" in compose
    for pattern in [
        ".env",
        ".env.*",
        "gcp-oauth.keys.json",
        "gitleaks-report.json",
        "*.db",
        "*.sqlite",
        "*.sqlite3",
        "docs/",
        "tests/",
        "*.mcpb",
    ]:
        assert pattern in dockerignore


def test_mcpb_ignore_excludes_secret_and_build_artifacts():
    ignore = _read(".mcpbignore")

    for pattern in [
        ".env",
        ".env.*",
        "gcp-oauth.keys.json",
        "gitleaks-report.json",
        "*.db",
        "*.sqlite",
        "*.sqlite3",
        ".venv/",
        ".pytest_cache/",
        "docs/",
        "tests/",
        "deploy/",
        "*.mcpb",
    ]:
        assert pattern in ignore


def test_mcpb_manifest_declares_exact_tools_and_sensitive_config():
    manifest = json.loads(_read("manifest.json"))

    assert manifest["version"] == EXPECTED_VERSION
    assert manifest["server"]["type"] == "uv"
    assert manifest["server"]["mcp_config"]["args"][-2:] == ["--transport", "stdio"]
    assert [tool["name"] for tool in manifest["tools"]] == EXPECTED_TOOLS
    assert manifest["tools_generated"] is False
    assert manifest["user_config"]["google_client_secret"]["sensitive"] is True
    assert "mcp_bearer_token" not in manifest["user_config"]


def test_registry_metadata_declares_pypi_stdio_and_exact_secret_flags():
    server_json = json.loads(_read("server.json"))
    package = server_json["packages"][0]

    assert server_json["version"] == EXPECTED_VERSION
    assert package["version"] == EXPECTED_VERSION
    assert f"mcp-name: {server_json['name']}" in _read("README.md")
    assert package["registryType"] == "pypi"
    assert package["identifier"] == "google-tasks-mcp"
    assert package["transport"] == {"type": "stdio"}
    env = {item["name"]: item for item in package["environmentVariables"]}
    assert env["GOOGLE_CLIENT_SECRET"]["isSecret"] is True
    assert "MCP_BEARER_TOKEN" not in env
    assert env["DB_PATH"]["isSecret"] is False


def test_directory_metadata_lists_exact_tools_and_private_model():
    metadata = json.loads(_read("metadata/glama.json"))

    assert metadata["version"] == EXPECTED_VERSION
    assert metadata["tools"] == EXPECTED_TOOLS
    assert metadata["privacy"]["sharedHostedEndpoint"] is False


def test_release_version_is_consistent_across_artifacts():
    pyproject = tomllib.loads(_read("pyproject.toml"))
    manifest = json.loads(_read("manifest.json"))
    server_json = json.loads(_read("server.json"))
    metadata = json.loads(_read("metadata/glama.json"))

    assert pyproject["project"]["version"] == EXPECTED_VERSION
    assert manifest["version"] == EXPECTED_VERSION
    assert server_json["version"] == EXPECTED_VERSION
    assert server_json["packages"][0]["version"] == EXPECTED_VERSION
    assert metadata["version"] == EXPECTED_VERSION
    assert google_tasks_mcp.__version__ == EXPECTED_VERSION
