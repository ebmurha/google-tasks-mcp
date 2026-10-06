from __future__ import annotations

import os
import subprocess
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from google_tasks_mcp.healthcheck import health_path_for_issuer


ROOT = Path(__file__).resolve().parents[1]


def test_health_path_follows_runtime_issuer_path():
    assert health_path_for_issuer("https://tasks.example/base") == "/base/healthz"
    assert health_path_for_issuer("https://tasks.example") == "/healthz"


def test_docker_health_command_probes_path_bearing_issuer():
    requests: list[str] = []

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            requests.append(self.path)
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(b'{"ok": true}')

        def log_message(self, _format, *_args):
            return

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        env = os.environ.copy()
        env["MCP_OAUTH_ISSUER"] = "https://tasks.example/base"
        env["BIND_PORT"] = str(server.server_port)
        env["PYTHONPATH"] = os.pathsep.join(
            filter(None, [str(ROOT / "src"), env.get("PYTHONPATH")])
        )
        result = subprocess.run(
            [sys.executable, "-m", "google_tasks_mcp.healthcheck"],
            cwd=ROOT,
            env=env,
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
        )
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)

    assert result.returncode == 0, result.stderr
    assert requests == ["/base/healthz"]
    assert 'CMD ["python", "-m", "google_tasks_mcp.healthcheck"]' in (
        ROOT / "Dockerfile"
    ).read_text(encoding="utf-8")
