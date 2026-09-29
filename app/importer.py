from datetime import datetime, timezone
from typing import Any, Literal

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.embedding import embedding_text
from app.github import GitHubClient, GitHubRepository
from app.models import Issue, Repository


def parse_github_datetime(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def map_issue(record: dict[str, Any], repository_id: int, imported_at: datetime) -> dict[str, Any]:
    return {
        "repository_id": repository_id,
        "github_id": record["id"],
        "number": record["number"],
        "title": record["title"],
        "body": record.get("body"),
        "html_url": record["html_url"],
        "state": record["state"],
        "labels": [label["name"] for label in record.get("labels", [])],
        "github_created_at": parse_github_datetime(record["created_at"]),
        "github_updated_at": parse_github_datetime(record["updated_at"]),
        "imported_at": imported_at,
    }


def import_issues(
    session: Session,
    github: GitHubClient,
    full_name: str,
    max_issues: int,
    *,
    state: Literal["open", "closed", "all"] = "all",
    sort: Literal["created", "updated", "comments"] = "created",
    direction: Literal["asc", "desc"] = "asc",
) -> tuple[int, int]:
    """Import issues, returning (created, updated)."""
    if max_issues < 1:
        raise ValueError("max_issues must be at least 1")

    github_repository = github.get_repository(full_name)
    now = datetime.now(timezone.utc)
    repository = _upsert_repository(session, github_repository, now)

    created = 0
    updated = 0
    for record in github.iter_issues(
        github_repository.full_name,
        max_issues,
        state=state,
        sort=sort,
        direction=direction,
    ):
        was_created = _upsert_issue(session, repository, record, now)
        created += int(was_created)
        updated += int(not was_created)

    session.commit()
    return created, updated


def import_issue_numbers(
    session: Session,
    github: GitHubClient,
    full_name: str,
    issue_numbers: list[int] | set[int],
) -> tuple[int, int]:
    """Import specific issues referenced by an evidence-backed benchmark."""
    numbers = sorted(set(issue_numbers))
    if not numbers or any(number < 1 for number in numbers):
        raise ValueError("issue_numbers must contain positive issue numbers")

    github_repository = github.get_repository(full_name)
    now = datetime.now(timezone.utc)
    repository = _upsert_repository(session, github_repository, now)
    created = 0
    updated = 0
    for number in numbers:
        record = github.get_issue(github_repository.full_name, number)
        was_created = _upsert_issue(session, repository, record, now)
        created += int(was_created)
        updated += int(not was_created)
    session.commit()
    return created, updated


def _upsert_repository(
    session: Session, github_repository: GitHubRepository, imported_at: datetime
) -> Repository:
    repository = session.scalar(
        select(Repository).where(
            or_(
                Repository.github_id == github_repository.github_id,
                Repository.full_name == github_repository.full_name,
            )
        )
    )
    if repository is None:
        repository = Repository(
            github_id=github_repository.github_id,
            owner=github_repository.owner,
            name=github_repository.name,
            full_name=github_repository.full_name,
            html_url=github_repository.html_url,
            imported_at=imported_at,
        )
        session.add(repository)
        session.flush()
    else:
        repository.github_id = github_repository.github_id
        repository.owner = github_repository.owner
        repository.name = github_repository.name
        repository.html_url = github_repository.html_url
        repository.imported_at = imported_at
    return repository


def _upsert_issue(
    session: Session,
    repository: Repository,
    record: dict[str, Any],
    imported_at: datetime,
) -> bool:
    values = map_issue(record, repository.id, imported_at)
    issue = session.scalar(select(Issue).where(Issue.github_id == record["id"]))
    if issue is None:
        session.add(Issue(**values))
        return True

    text_changed = embedding_text(issue.title, issue.body) != embedding_text(
        values["title"], values["body"]
    )
    for key, value in values.items():
        setattr(issue, key, value)
    if text_changed:
        issue.embedding = None
        issue.embedding_model = None
        issue.embedding_text_hash = None
        issue.embedded_at = None
    return False
