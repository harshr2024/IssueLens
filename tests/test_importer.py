from datetime import datetime, timezone

from sqlalchemy import func, select

from app.importer import import_issues, map_issue
from app.models import Issue, Repository
from tests.helpers import FakeGitHubClient, issue_record


def test_import_mapping_preserves_traceability_fields() -> None:
    imported_at = datetime(2025, 3, 1, tzinfo=timezone.utc)
    mapped = map_issue(issue_record(), repository_id=9, imported_at=imported_at)

    assert mapped["repository_id"] == 9
    assert mapped["github_id"] == 1001
    assert mapped["number"] == 1
    assert mapped["html_url"].endswith("/issues/1")
    assert mapped["labels"] == ["bug", "triage"]
    assert mapped["github_created_at"].isoformat() == "2025-01-02T03:04:05+00:00"
    assert mapped["github_updated_at"].isoformat() == "2025-02-03T04:05:06+00:00"
    assert mapped["imported_at"] == imported_at


def test_repeated_import_updates_without_duplicates(session) -> None:
    original = issue_record(title="Old title")
    created, updated = import_issues(
        session, FakeGitHubClient([original]), "acme/widgets", 10
    )
    assert (created, updated) == (1, 0)

    changed = issue_record(title="New title")
    changed["state"] = "closed"
    created, updated = import_issues(
        session, FakeGitHubClient([changed]), "acme/widgets", 10
    )

    assert (created, updated) == (0, 1)
    assert session.scalar(select(func.count(Issue.id))) == 1
    assert session.scalar(select(func.count(Repository.id))) == 1
    stored = session.scalar(select(Issue))
    assert stored.title == "New title"
    assert stored.state == "closed"
