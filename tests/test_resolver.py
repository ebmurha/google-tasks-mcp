from __future__ import annotations

import threading
import time

import pytest

from google_tasks_mcp import resolver
from google_tasks_mcp.errors import AmbiguousTitleError, NotFoundError


class _Request:
    def __init__(self, response, delay: float = 0) -> None:
        self.response = response
        self.delay = delay

    def execute(self):
        if self.delay:
            time.sleep(self.delay)
        return self.response


class _TasklistsResource:
    def __init__(self, responses, calls, delay: float = 0) -> None:
        self.responses = responses
        self.calls = calls
        self.delay = delay

    def list(self, **kwargs):
        self.calls.append(kwargs)
        index = len(self.calls) - 1
        return _Request(self.responses[min(index, len(self.responses) - 1)], self.delay)


class _Service:
    def __init__(self, responses, calls, delay: float = 0) -> None:
        self._tasklists = _TasklistsResource(responses, calls, delay)

    def tasklists(self):
        return self._tasklists


@pytest.fixture
def fake_resolver_service(monkeypatch, configured_env):
    calls: list[dict] = []
    responses = [
        {
            "items": [
                {"id": "abc", "title": "EB Tasks", "updated": "2026-05-07T00:00:00.000Z"},
                {"id": "def", "title": "Personal"},
            ]
        }
    ]
    monkeypatch.setattr(resolver, "build", lambda *args, **kwargs: _Service(responses, calls))
    monkeypatch.setattr(resolver, "get_credentials", lambda: object())
    return calls, responses


def test_resolve_tasklist_by_title_uses_cache(fake_resolver_service):
    calls, _responses = fake_resolver_service

    assert resolver.resolve_tasklist_by_title("EB Tasks") == "abc"
    assert resolver.resolve_tasklist_by_title(" eb tasks ") == "abc"
    assert len(calls) == 1


def test_resolver_refreshes_once_on_title_miss(monkeypatch, configured_env):
    calls: list[dict] = []
    responses = [
        {"items": [{"id": "abc", "title": "Inbox"}]},
        {"items": [{"id": "abc", "title": "Inbox"}, {"id": "def", "title": "EB Tasks"}]},
    ]
    monkeypatch.setattr(resolver, "build", lambda *args, **kwargs: _Service(responses, calls))
    monkeypatch.setattr(resolver, "get_credentials", lambda: object())

    assert resolver.resolve_tasklist_by_title("EB Tasks") == "def"
    assert len(calls) == 2


def test_resolver_not_found_after_retry(fake_resolver_service):
    with pytest.raises(NotFoundError) as exc_info:
        resolver.resolve_tasklist_by_title("Missing")

    assert exc_info.value.code == 404
    assert exc_info.value.error == "NOT_FOUND"
    assert exc_info.value.details["query"] == "Missing"


def test_resolver_ambiguous_title(monkeypatch, configured_env):
    calls: list[dict] = []
    responses = [{"items": [{"id": "one", "title": "Work"}, {"id": "two", "title": "work"}]}]
    monkeypatch.setattr(resolver, "build", lambda *args, **kwargs: _Service(responses, calls))
    monkeypatch.setattr(resolver, "get_credentials", lambda: object())

    with pytest.raises(AmbiguousTitleError) as exc_info:
        resolver.resolve_tasklist_by_title("WORK")

    assert exc_info.value.code == 409
    assert [item["id"] for item in exc_info.value.details["candidates"]] == ["one", "two"]


def test_invalidate_clears_cache(fake_resolver_service):
    calls, _responses = fake_resolver_service

    assert resolver.resolve_tasklist_by_title("EB Tasks") == "abc"
    resolver.invalidate()
    assert resolver.resolve_tasklist_by_title("EB Tasks") == "abc"
    assert len(calls) == 2


def test_concurrent_resolver_calls_single_flight(monkeypatch, configured_env):
    calls: list[dict] = []
    responses = [{"items": [{"id": "abc", "title": "EB Tasks"}]}]
    monkeypatch.setattr(resolver, "build", lambda *args, **kwargs: _Service(responses, calls, delay=0.05))
    monkeypatch.setattr(resolver, "get_credentials", lambda: object())

    results: list[str] = []
    threads = [
        threading.Thread(target=lambda: results.append(resolver.resolve_tasklist_by_title("EB Tasks")))
        for _ in range(2)
    ]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    assert results == ["abc", "abc"]
    assert len(calls) == 1
