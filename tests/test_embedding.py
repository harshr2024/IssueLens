from datetime import datetime, timezone

from sqlalchemy import select

from app.embedding import (
    EMBEDDING_DIMENSIONS,
    MODEL_IDENTIFIER,
    embed_imported_issues,
    embedding_text_hash,
)
from app.models import Issue, Repository


class FakeEmbedder:
    model_name = MODEL_IDENTIFIER

    def __init__(self) -> None:
        self.calls: list[list[str]] = []

    def encode(self, texts, *, batch_size: int) -> list[list[float]]:
        del batch_size
        self.calls.append(list(texts))
        return [[float(index + 1)] * EMBEDDING_DIMENSIONS for index, _ in enumerate(texts)]


def add_issue(session, *, body: str | None = None) -> Issue:
    now = datetime.now(timezone.utc)
    repository = Repository(
        github_id=42,
        owner="acme",
        name="widgets",
        full_name="acme/widgets",
        html_url="https://github.com/acme/widgets",
        imported_at=now,
    )
    issue = Issue(
        repository=repository,
        github_id=1001,
        number=1,
        title="Cannot start server",
        body=body,
        html_url="https://github.com/acme/widgets/issues/1",
        state="open",
        labels=[],
        github_created_at=now,
        github_updated_at=now,
        imported_at=now,
    )
    session.add(issue)
    session.commit()
    return issue


def test_unchanged_embeddings_skip_and_changed_text_recomputes(session) -> None:
    issue = add_issue(session, body=None)
    embedder = FakeEmbedder()

    first = embed_imported_issues(session, embedder, "acme/widgets", batch_size=8)
    assert (first.embedded, first.skipped) == (1, 0)
    assert embedder.calls == [["Cannot start server\n\n"]]
    assert issue.embedding_model == MODEL_IDENTIFIER
    assert issue.embedding_text_hash == embedding_text_hash(issue.title, None)

    second = embed_imported_issues(session, embedder, "acme/widgets", batch_size=8)
    assert (second.embedded, second.skipped) == (0, 1)
    assert len(embedder.calls) == 1

    stored = session.scalar(select(Issue).where(Issue.id == issue.id))
    stored.body = "It fails after upgrading."
    session.commit()

    third = embed_imported_issues(session, embedder, "acme/widgets", batch_size=8)
    assert (third.embedded, third.skipped) == (1, 0)
    assert embedder.calls[-1] == [
        "Cannot start server\n\nIt fails after upgrading."
    ]
    assert stored.embedding_text_hash == embedding_text_hash(stored.title, stored.body)
