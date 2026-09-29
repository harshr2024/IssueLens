from dataclasses import dataclass, replace
from datetime import datetime
import re
from typing import Literal

from sqlalchemy import Select, bindparam, func, literal_column, select
from sqlalchemy.orm import Session

from app.embedding import MODEL_IDENTIFIER
from app.models import Issue, Repository


SearchMethod = Literal["semantic", "keyword", "hybrid"]
RRF_K = 60
HYBRID_CANDIDATE_LIMIT = 50
MAX_KEYWORD_TERMS = 64
_WORD_PATTERN = re.compile(r"[^\W_]+", re.UNICODE)


@dataclass(frozen=True)
class SimilarIssue:
    id: int
    number: int
    title: str
    body: str | None
    html_url: str
    similarity_score: float


def build_similarity_statement(
    repository_full_name: str,
    query_embedding: list[float],
    *,
    limit: int = 5,
    exclude_issue_id: int | None = None,
    created_before: datetime | None = None,
) -> Select:
    distance = Issue.embedding.cosine_distance(query_embedding)
    score = (1.0 - distance).label("similarity_score")
    filters = [
        Repository.full_name == repository_full_name,
        Issue.embedding.is_not(None),
        Issue.embedding_model == MODEL_IDENTIFIER,
    ]
    if exclude_issue_id is not None:
        filters.append(Issue.id != exclude_issue_id)
    if created_before is not None:
        filters.append(Issue.github_created_at < created_before)

    return (
        select(Issue.id, Issue.number, Issue.title, Issue.body, Issue.html_url, score)
        .join(Issue.repository)
        .where(*filters)
        .order_by(distance.asc(), Issue.id.asc())
        .limit(limit)
    )


def build_keyword_statement(
    repository_full_name: str,
    query_text: str,
    *,
    limit: int = 5,
    exclude_issue_id: int | None = None,
    created_before: datetime | None = None,
) -> Select:
    websearch_query = keyword_websearch_query(query_text)
    if not websearch_query:
        raise ValueError("query_text must contain at least one searchable term")

    english = literal_column("'english'")
    title_vector = func.setweight(
        func.to_tsvector(english, Issue.title), literal_column("'A'")
    )
    body_vector = func.setweight(
        func.to_tsvector(english, func.coalesce(Issue.body, "")),
        literal_column("'B'"),
    )
    document = title_vector.op("||")(body_vector)
    query = func.websearch_to_tsquery(
        english, bindparam("keyword_query", websearch_query)
    )
    score = func.ts_rank_cd(document, query).label("similarity_score")
    filters = [
        Repository.full_name == repository_full_name,
        document.op("@@")(query),
    ]
    if exclude_issue_id is not None:
        filters.append(Issue.id != exclude_issue_id)
    if created_before is not None:
        filters.append(Issue.github_created_at < created_before)

    return (
        select(Issue.id, Issue.number, Issue.title, Issue.body, Issue.html_url, score)
        .join(Issue.repository)
        .where(*filters)
        .order_by(score.desc(), Issue.id.asc())
        .limit(limit)
    )


def search_similar_issues(
    session: Session,
    repository_full_name: str,
    query_embedding: list[float],
    *,
    limit: int = 5,
    exclude_issue_id: int | None = None,
    created_before: datetime | None = None,
) -> list[SimilarIssue]:
    statement = build_similarity_statement(
        repository_full_name,
        query_embedding,
        limit=limit,
        exclude_issue_id=exclude_issue_id,
        created_before=created_before,
    )
    return _rows_to_results(session.execute(statement))


def search_keyword_issues(
    session: Session,
    repository_full_name: str,
    query_text: str,
    *,
    limit: int = 5,
    exclude_issue_id: int | None = None,
    created_before: datetime | None = None,
) -> list[SimilarIssue]:
    if not keyword_websearch_query(query_text):
        return []
    statement = build_keyword_statement(
        repository_full_name,
        query_text,
        limit=limit,
        exclude_issue_id=exclude_issue_id,
        created_before=created_before,
    )
    return _rows_to_results(session.execute(statement))


def keyword_websearch_query(query_text: str) -> str:
    """Build a safe OR query; SQLAlchemy still sends the result as a bind value."""
    unique_terms: list[str] = []
    seen: set[str] = set()
    for match in _WORD_PATTERN.finditer(query_text):
        term = match.group(0).casefold()
        if term not in seen:
            seen.add(term)
            unique_terms.append(term)
        if len(unique_terms) >= MAX_KEYWORD_TERMS:
            break
    return " OR ".join(unique_terms)


def reciprocal_rank_fusion(
    semantic_results: list[SimilarIssue],
    keyword_results: list[SimilarIssue],
    *,
    limit: int = 5,
    k: int = RRF_K,
) -> list[SimilarIssue]:
    combined: dict[int, tuple[SimilarIssue, float, int]] = {}
    for results in (semantic_results, keyword_results):
        for rank, result in enumerate(results, start=1):
            contribution = 1.0 / (k + rank)
            if result.id in combined:
                original, score, best_rank = combined[result.id]
                combined[result.id] = (
                    original,
                    score + contribution,
                    min(best_rank, rank),
                )
            else:
                combined[result.id] = (result, contribution, rank)

    ranked = sorted(
        combined.values(),
        key=lambda item: (-item[1], item[2], item[0].id),
    )
    return [
        replace(result, similarity_score=score)
        for result, score, _ in ranked[:limit]
    ]


def retrieve_all_methods(
    session: Session,
    repository_full_name: str,
    query_text: str,
    query_embedding: list[float],
    *,
    limit: int = 5,
    exclude_issue_id: int | None = None,
    candidate_limit: int = HYBRID_CANDIDATE_LIMIT,
    created_before: datetime | None = None,
) -> dict[SearchMethod, list[SimilarIssue]]:
    depth = max(limit, candidate_limit)
    semantic = search_similar_issues(
        session,
        repository_full_name,
        query_embedding,
        limit=depth,
        exclude_issue_id=exclude_issue_id,
        created_before=created_before,
    )
    keyword = search_keyword_issues(
        session,
        repository_full_name,
        query_text,
        limit=depth,
        exclude_issue_id=exclude_issue_id,
        created_before=created_before,
    )
    hybrid = reciprocal_rank_fusion(semantic, keyword, limit=limit)
    return {
        "semantic": semantic[:limit],
        "keyword": keyword[:limit],
        "hybrid": hybrid,
    }


def _rows_to_results(rows) -> list[SimilarIssue]:
    return [
        SimilarIssue(
            id=row.id,
            number=row.number,
            title=row.title,
            body=row.body,
            html_url=row.html_url,
            similarity_score=float(row.similarity_score),
        )
        for row in rows
    ]
