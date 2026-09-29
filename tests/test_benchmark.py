from datetime import datetime, timedelta, timezone

from app.benchmark import BenchmarkPair, evaluate_benchmark_pairs
from app.embedding import EMBEDDING_DIMENSIONS, MODEL_IDENTIFIER, embedding_text_hash
from app.models import Issue, Repository
from app.search import SimilarIssue


def stored_issue(repository: Repository, number: int, created_at: datetime) -> Issue:
    issue = Issue(
        repository=repository,
        github_id=100_000 + number,
        number=number,
        title=f"Issue {number}",
        body=f"Body for issue {number}",
        html_url=f"https://github.com/acme/widgets/issues/{number}",
        state="closed",
        labels=[],
        github_created_at=created_at,
        github_updated_at=created_at,
        imported_at=created_at,
        embedding=[0.01] * EMBEDDING_DIMENSIONS,
        embedding_model=MODEL_IDENTIFIER,
        embedded_at=created_at,
    )
    issue.embedding_text_hash = embedding_text_hash(issue.title, issue.body)
    return issue


def candidate(number: int) -> SimilarIssue:
    return SimilarIssue(
        id=10_000 + number,
        number=number,
        title=f"Candidate {number}",
        body="Candidate body",
        html_url=f"https://github.com/acme/widgets/issues/{number}",
        similarity_score=0.5,
    )


def test_benchmark_counts_missing_target_as_miss_and_uses_chronology(
    session, monkeypatch
) -> None:
    now = datetime.now(timezone.utc)
    repository = Repository(
        github_id=42,
        owner="acme",
        name="widgets",
        full_name="acme/widgets",
        html_url="https://github.com/acme/widgets",
        imported_at=now,
    )
    target = stored_issue(repository, 10, now - timedelta(days=10))
    query = stored_issue(repository, 20, now)
    session.add_all([target, query])
    session.commit()

    captured = {}

    def fake_retrieve(*args, **kwargs):
        captured.update(kwargs)
        return {
            "semantic": [candidate(n) for n in [1, 2, 3, 4, 5, 10]],
            "keyword": [candidate(n) for n in [1, 2, 3]],
            "hybrid": [candidate(n) for n in [1, 10, 2]],
        }

    monkeypatch.setattr("app.benchmark.retrieve_all_methods", fake_retrieve)
    pair = BenchmarkPair(
        pair_id="pair-1",
        repository="acme/widgets",
        query_issue_number=20,
        target_issue_number=10,
        source_issue_url="https://github.com/acme/widgets/issues/20",
        target_issue_url="https://github.com/acme/widgets/issues/10",
        evidence_url="https://github.com/acme/widgets/issues/20#issuecomment-1",
        evidence_note="Explicit duplicate evidence",
        approved=True,
    )

    result = evaluate_benchmark_pairs(session, [pair])

    assert captured["created_before"].replace(tzinfo=timezone.utc) == now
    assert captured["exclude_issue_id"] == query.id
    assert result.pair_count == 1
    assert result.metrics["semantic"].recall_at_5 == 0.0
    assert result.metrics["semantic"].mrr == 1 / 6
    assert result.metrics["keyword"].recall_at_5 == 0.0
    assert result.metrics["keyword"].mrr == 0.0
    assert result.metrics["hybrid"].recall_at_5 == 1.0
    assert result.metrics["hybrid"].mrr == 0.5
