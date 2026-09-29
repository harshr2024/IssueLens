from types import SimpleNamespace
from datetime import datetime, timezone

from sqlalchemy.dialects import postgresql

from app.embedding import EMBEDDING_DIMENSIONS
from app.search import (
    SimilarIssue,
    build_keyword_statement,
    build_similarity_statement,
    reciprocal_rank_fusion,
    keyword_websearch_query,
    search_keyword_issues,
    search_similar_issues,
)


def compiled_search(*, exclude_issue_id: int | None = None):
    statement = build_similarity_statement(
        "acme/widgets",
        [0.0] * EMBEDDING_DIMENSIONS,
        limit=5,
        exclude_issue_id=exclude_issue_id,
    )
    return statement.compile(dialect=postgresql.dialect())


def test_similarity_query_filters_repository_and_orders_by_cosine_score() -> None:
    compiled = compiled_search()
    sql = str(compiled)

    assert "JOIN repositories" in sql
    assert "repositories.full_name =" in sql
    assert "issues.embedding_model =" in sql
    assert "issues.embedding <=>" in sql
    assert "ORDER BY (issues.embedding <=>" in sql
    assert compiled.params["full_name_1"] == "acme/widgets"
    assert compiled.params["param_2"] == 5


def test_similarity_query_excludes_source_issue() -> None:
    compiled = compiled_search(exclude_issue_id=17)

    assert "issues.id !=" in str(compiled)
    assert 17 in compiled.params.values()


def test_search_statements_filter_to_issues_created_before_query() -> None:
    cutoff = datetime(2024, 1, 2, tzinfo=timezone.utc)
    semantic = build_similarity_statement(
        "acme/widgets",
        [0.0] * EMBEDDING_DIMENSIONS,
        created_before=cutoff,
    ).compile(dialect=postgresql.dialect())
    keyword = build_keyword_statement(
        "acme/widgets",
        "reload server",
        created_before=cutoff,
    ).compile(dialect=postgresql.dialect())

    assert "issues.github_created_at <" in str(semantic)
    assert "issues.github_created_at <" in str(keyword)
    assert cutoff in semantic.params.values()
    assert cutoff in keyword.params.values()


def test_keyword_query_filters_repository_and_excludes_source_issue() -> None:
    compiled = build_keyword_statement(
        "acme/widgets",
        "reload server",
        limit=5,
        exclude_issue_id=17,
    ).compile(dialect=postgresql.dialect())
    sql = str(compiled)

    assert "to_tsvector" in sql
    assert "websearch_to_tsquery" in sql
    assert "setweight" in sql
    assert "'A'" in sql
    assert "'B'" in sql
    assert "@@" in sql
    assert "repositories.full_name =" in sql
    assert "issues.id !=" in sql
    assert "ORDER BY similarity_score DESC" in sql
    assert "acme/widgets" in compiled.params.values()
    assert 17 in compiled.params.values()
    assert compiled.params["keyword_query"] == "reload OR server"


def test_multiword_keyword_query_uses_parameterized_or_terms() -> None:
    natural_language = (
        "Development server fails to reload\n\n"
        "Reloading stops after a syntax error"
    )
    compiled = build_keyword_statement(
        "pallets/flask", natural_language, limit=5
    ).compile(dialect=postgresql.dialect())

    assert compiled.params["keyword_query"] == (
        "development OR server OR fails OR to OR reload OR reloading OR stops OR "
        "after OR a OR syntax OR error"
    )
    assert compiled.params["keyword_query"] not in str(compiled)
    assert "keyword_query" in str(compiled)


def test_keyword_tokenization_does_not_interpolate_sql() -> None:
    malicious = "reload'); DROP TABLE issues; --"

    assert keyword_websearch_query(malicious) == (
        "reload OR drop OR table OR issues"
    )
    compiled = build_keyword_statement(
        "acme/widgets", malicious, limit=5
    ).compile(dialect=postgresql.dialect())
    assert "DROP TABLE" not in str(compiled)
    assert compiled.params["keyword_query"] == "reload OR drop OR table OR issues"


def result(issue_id: int, number: int, score: float = 0.5) -> SimilarIssue:
    return SimilarIssue(
        id=issue_id,
        number=number,
        title=f"Issue {number}",
        body=f"Body {number}",
        html_url=f"https://example/{number}",
        similarity_score=score,
    )


def test_reciprocal_rank_fusion_rewards_results_in_both_lists() -> None:
    semantic = [result(1, 101), result(2, 102), result(3, 103)]
    keyword = [result(3, 103), result(4, 104), result(2, 102)]

    fused = reciprocal_rank_fusion(semantic, keyword, limit=4, k=60)

    assert [item.number for item in fused] == [103, 102, 101, 104]
    assert fused[0].similarity_score > fused[1].similarity_score


def test_empty_keyword_and_hybrid_results_are_empty() -> None:
    class SessionMustNotExecute:
        def execute(self, statement):
            raise AssertionError(f"unexpected statement: {statement}")

    assert search_keyword_issues(SessionMustNotExecute(), "acme/widgets", "   ") == []
    assert reciprocal_rank_fusion([], []) == []

    class EmptySession:
        def execute(self, statement):
            return []

    assert (
        search_similar_issues(
            EmptySession(), "acme/widgets", [0.0] * EMBEDDING_DIMENSIONS
        )
        == []
    )
    assert search_keyword_issues(EmptySession(), "acme/widgets", "reload") == []


def test_search_results_preserve_score_order_from_exact_query() -> None:
    rows = [
        SimpleNamespace(
            id=2,
            number=2,
            title="Closer",
            body="Closer body",
            html_url="https://example/2",
            similarity_score=0.91,
        ),
        SimpleNamespace(
            id=1,
            number=1,
            title="Farther",
            body="Farther body",
            html_url="https://example/1",
            similarity_score=0.63,
        ),
    ]

    class FakeSession:
        def execute(self, statement):
            assert "ORDER BY (issues.embedding <=>" in str(
                statement.compile(dialect=postgresql.dialect())
            )
            return rows

    results = search_similar_issues(
        FakeSession(), "acme/widgets", [0.0] * EMBEDDING_DIMENSIONS
    )

    assert [result.similarity_score for result in results] == [0.91, 0.63]
