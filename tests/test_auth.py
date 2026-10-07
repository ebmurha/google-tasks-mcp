from __future__ import annotations

import pytest

from google_tasks_mcp import db
from google_tasks_mcp.auth import (
    _extract_code,
    _oauth_error_details,
    _oauth_error_message,
    authorization_url,
    build_authorization_flow,
)


def test_google_pkce_verifier_survives_durable_state_round_trip(configured_env):
    flow = build_authorization_flow(state="durable-state")
    authorization_url(flow, state="durable-state")
    assert flow.code_verifier

    db.save_google_oauth_state(
        "durable-state",
        account_id="default",
        callback_uri="http://localhost:8787/callback",
        expires_at=9999999999,
        google_code_verifier=flow.code_verifier,
    )
    state = db.consume_google_oauth_state(
        "durable-state",
        callback_uri="http://localhost:8787/callback",
    )

    assert state is not None
    assert state.google_code_verifier == flow.code_verifier
    resumed = build_authorization_flow(
        state="durable-state",
        code_verifier=state.google_code_verifier,
    )
    assert resumed.code_verifier == flow.code_verifier
    with db._connect() as conn:
        stored = conn.execute(
            "SELECT google_code_verifier, consumed_at FROM google_oauth_states"
        ).fetchone()
    assert stored["google_code_verifier"] is None
    assert stored["consumed_at"] is not None


def test_extract_code_accepts_plain_code():
    assert _extract_code(" auth-code ") == "auth-code"


def test_extract_code_accepts_callback_url():
    callback_url = "http://127.0.0.1:8787/callback?state=abc&code=auth-code&scope=tasks"

    assert _extract_code(callback_url) == "auth-code"


def test_oauth_error_message_discards_provider_text():
    exc = ValueError("hidden raw message")
    exc.error = "invalid_grant"  # type: ignore[attr-defined]
    exc.description = "Bad Request"  # type: ignore[attr-defined]

    assert _oauth_error_message(exc) == "OAuth code exchange failed"


def test_oauth_error_details_allowlist_category_and_bound_status():
    exc = ValueError("hidden")
    exc.error = "invalid_grant"  # type: ignore[attr-defined]
    exc.status_code = 400  # type: ignore[attr-defined]
    assert _oauth_error_details(exc) == {
        "provider_error": "invalid_grant",
        "provider_status": 400,
    }


@pytest.mark.parametrize(
    ("provider_error", "provider_status"),
    [
        ("mystery", 0),
        ("x" * 10000, 9999),
        ("invalid_grant\nFORGED log entry", 400),
        ("code=secret-authorization-code", True),
        ("token=secret-refresh-token", "401"),
    ],
)
def test_oauth_error_details_reject_malformed_provider_values(
    provider_error, provider_status
):
    exc = ValueError("hidden")
    exc.error = provider_error  # type: ignore[attr-defined]
    exc.status_code = provider_status  # type: ignore[attr-defined]
    expected = {"provider_error": "unrecognized"}
    if type(provider_status) is int and 100 <= provider_status <= 599:
        expected["provider_status"] = provider_status
    assert _oauth_error_details(exc) == expected


def test_oauth_error_details_discards_response_description_and_body():
    class ResponseStub:
        status_code = 401

        @staticmethod
        def json():
            return {
                "error": "invalid_client\nFORGED log entry",
                "error_description": "token=secret-refresh-token",
            }

    exc = ValueError("raw provider response")
    exc.response = ResponseStub()  # type: ignore[attr-defined]

    assert _oauth_error_message(exc) == "OAuth code exchange failed"
    assert _oauth_error_details(exc) == {
        "provider_error": "unrecognized",
        "provider_status": 401,
    }


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


def test_authorization_url_uses_explicit_hosted_state():
    class FlowStub:
        def authorization_url(self, **kwargs):
            assert kwargs["state"] == "hosted-state"
            return "https://accounts.example/auth?state=hosted-state", "hosted-state"

    assert authorization_url(FlowStub(), state="hosted-state").endswith(
        "state=hosted-state"
    )
