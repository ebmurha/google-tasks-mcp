from __future__ import annotations

from google_tasks_mcp.auth import _extract_code, _oauth_error_message, authorization_url


def test_extract_code_accepts_plain_code():
    assert _extract_code(" auth-code ") == "auth-code"


def test_extract_code_accepts_callback_url():
    callback_url = "http://127.0.0.1:8787/callback?state=abc&code=auth-code&scope=tasks"

    assert _extract_code(callback_url) == "auth-code"


def test_oauth_error_message_includes_safe_details():
    exc = ValueError("hidden raw message")
    exc.error = "invalid_grant"  # type: ignore[attr-defined]
    exc.description = "Bad Request"  # type: ignore[attr-defined]

    assert _oauth_error_message(exc) == (
        "OAuth code exchange failed; error=invalid_grant; description=Bad Request"
    )


def test_authorization_url_can_reuse_existing_flow():
    class FlowStub:
        def __init__(self) -> None:
            self.calls = 0

        def authorization_url(self, **kwargs):
            self.calls += 1
            assert kwargs["access_type"] == "offline"
            assert kwargs["prompt"] == "consent"
            return "https://accounts.example/auth", "state"

    flow = FlowStub()

    assert authorization_url(flow) == "https://accounts.example/auth"
    assert flow.calls == 1
