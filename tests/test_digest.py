from __future__ import annotations

from google_tasks_mcp import digest


def test_shrink_task_strips_unknown_fields():
    task = {
        "id": "task-1",
        "title": "Pay invoice",
        "due": "2026-05-05T00:00:00.000Z",
        "status": "needsAction",
        "kind": "tasks#task",
        "etag": "etag",
        "selfLink": "https://example.test",
    }

    assert digest.shrink_task(task) == {
        "id": "task-1",
        "title": "Pay invoice",
        "due": "2026-05-05",
        "status": "needsAction",
    }


def test_shrink_task_includes_truncated_notes_only_when_requested():
    task = {
        "id": "task-1",
        "title": "Read notes",
        "status": "needsAction",
        "notes": "x" * 250,
    }

    without_notes = digest.shrink_task(task)
    with_notes = digest.shrink_task(task, include_notes=True)

    assert "notes" not in without_notes
    assert with_notes["notes"] == ("x" * 200) + "..."


def test_shrink_list_has_no_google_envelope():
    result = digest.shrink_list(
        [
            {
                "id": "task-1",
                "title": "Pay invoice",
                "status": "needsAction",
                "kind": "tasks#task",
            }
        ]
    )

    assert result == {
        "count": 1,
        "tasks": [{"id": "task-1", "title": "Pay invoice", "status": "needsAction"}],
    }


def test_text_digest_groups_by_due(monkeypatch):
    class FixedDate(digest.date):
        @classmethod
        def today(cls):
            return cls(2026, 5, 5)

    monkeypatch.setattr(digest, "date", FixedDate)

    text = digest.text_digest(
        [
            {"title": "Email Sam", "due": "2026-05-05T00:00:00.000Z"},
            {"title": "Renew domain", "due": "2026-05-04T00:00:00.000Z"},
            {"title": "Book travel", "due": "2026-05-07T00:00:00.000Z"},
        ]
    )

    assert '1 due today: "Email Sam"' in text
    assert '1 overdue: "Renew domain (yesterday)"' in text
    assert '1 upcoming: "Book travel (in 2d)"' in text
