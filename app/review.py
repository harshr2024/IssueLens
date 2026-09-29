import csv
import json
import re
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Sequence

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.embedding import MODEL_IDENTIFIER, embedding_text, embedding_text_hash
from app.models import Issue, Repository
from app.search import SimilarIssue, retrieve_all_methods


JUDGMENT_SAME = "same underlying problem"
JUDGMENT_RELATED = "related but different"
JUDGMENT_UNRELATED = "unrelated"
VALID_JUDGMENTS = {JUDGMENT_SAME, JUDGMENT_RELATED, JUDGMENT_UNRELATED}
REVIEW_FIELDS = [
    "query_repository",
    "query_issue_number",
    "query_title",
    "query_body",
    "query_github_url",
    "query_created_at",
    "candidate_issue_number",
    "candidate_title",
    "candidate_body_excerpt",
    "candidate_github_url",
    "semantic_rank",
    "keyword_rank",
    "hybrid_rank",
    "judgment",
]
_TOPIC_WORD = re.compile(r"[^\W_]+", re.UNICODE)
_STOP_WORDS = {
    "a", "an", "and", "are", "as", "at", "be", "but", "by", "for", "from",
    "how", "i", "in", "is", "it", "of", "on", "or", "the", "this", "to",
    "was", "when", "with",
}


class ReviewError(ValueError):
    pass


@dataclass(frozen=True)
class ReviewExportResult:
    path: Path
    query_count: int
    row_count: int


def select_review_issues(issues: Sequence[Issue], count: int = 20) -> list[Issue]:
    """Select one topic-novel issue from each chronological slice."""
    if count < 1:
        raise ValueError("count must be at least 1")
    ordered = sorted(issues, key=lambda issue: (issue.github_created_at, issue.id))
    if len(ordered) < count:
        raise ReviewError(
            f"Need {count} eligible issues, but only {len(ordered)} are available"
        )

    selected: list[Issue] = []
    seen_topics: set[str] = set()
    total = len(ordered)
    for bucket_index in range(count):
        start = bucket_index * total // count
        end = (bucket_index + 1) * total // count
        bucket = ordered[start:end]
        midpoint = (len(bucket) - 1) / 2
        ranked = []
        for position, issue in enumerate(bucket):
            topics = _title_topics(issue.title)
            ranked.append(
                (
                    len(topics - seen_topics),
                    len(topics),
                    -abs(position - midpoint),
                    -issue.id,
                    issue,
                    topics,
                )
            )
        *_, chosen, topics = max(ranked, key=lambda item: item[:4])
        selected.append(chosen)
        seen_topics.update(topics)
    return selected


def export_review_sheet(
    session: Session,
    repository_full_name: str,
    output_path: str | Path,
    *,
    query_count: int = 20,
    candidates_per_method: int = 5,
) -> ReviewExportResult:
    repository = session.scalar(
        select(Repository).where(Repository.full_name == repository_full_name)
    )
    if repository is None:
        raise ReviewError(f"Repository {repository_full_name!r} has not been imported")

    issues = list(
        session.scalars(
            select(Issue)
            .where(
                Issue.repository_id == repository.id,
                func.length(func.trim(Issue.title)) > 0,
                Issue.body.is_not(None),
                func.length(func.trim(Issue.body)) > 0,
                Issue.embedding.is_not(None),
                Issue.embedding_model == MODEL_IDENTIFIER,
            )
            .order_by(Issue.github_created_at, Issue.id)
        )
    )
    current_issues = [
        issue
        for issue in issues
        if issue.embedding_text_hash == embedding_text_hash(issue.title, issue.body)
    ]
    selected = select_review_issues(current_issues, query_count)

    rows: list[dict[str, str | int]] = []
    for query_issue in selected:
        method_results = retrieve_all_methods(
            session,
            repository_full_name,
            embedding_text(query_issue.title, query_issue.body),
            list(query_issue.embedding),
            limit=candidates_per_method,
            exclude_issue_id=query_issue.id,
        )
        rows.extend(_review_rows(repository_full_name, query_issue, method_results))

    path = Path(output_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=REVIEW_FIELDS)
        writer.writeheader()
        writer.writerows(rows)
    return ReviewExportResult(path=path.resolve(), query_count=len(selected), row_count=len(rows))


def convert_review_sheet(
    input_path: str | Path,
    output_path: str | Path,
    *,
    include_related: bool = False,
) -> tuple[Path, int]:
    try:
        with Path(input_path).open("r", encoding="utf-8", newline="") as handle:
            reader = csv.DictReader(handle)
            missing_fields = set(REVIEW_FIELDS) - set(reader.fieldnames or [])
            if missing_fields:
                raise ReviewError(
                    f"Review CSV is missing columns: {', '.join(sorted(missing_fields))}"
                )
            rows = list(reader)
    except OSError as exc:
        raise ReviewError(f"Could not read review CSV: {exc}") from exc
    if not rows:
        raise ReviewError("Review CSV has no candidate rows")

    query_data: dict[tuple[str, int], dict[str, object]] = {}
    relevant: dict[tuple[str, int], set[int]] = defaultdict(set)
    for row_number, row in enumerate(rows, start=2):
        judgment = row["judgment"].strip().casefold()
        if judgment not in VALID_JUDGMENTS:
            expected = ", ".join(sorted(VALID_JUDGMENTS))
            raise ReviewError(
                f"Row {row_number} needs one of these judgments: {expected}"
            )
        try:
            query_number = int(row["query_issue_number"])
            candidate_number = int(row["candidate_issue_number"])
        except ValueError as exc:
            raise ReviewError(f"Row {row_number} has a non-numeric issue number") from exc
        key = (row["query_repository"], query_number)
        query_data.setdefault(
            key,
            {
                "id": f"review-{query_number}",
                "repository": row["query_repository"],
                "title": row["query_title"],
                "body": row["query_body"],
            },
        )
        if judgment == JUDGMENT_SAME or (
            include_related and judgment == JUDGMENT_RELATED
        ):
            relevant[key].add(candidate_number)

    queries = []
    for key, data in query_data.items():
        if not relevant[key]:
            raise ReviewError(
                f"Query #{key[1]} has no judgments included as relevant; "
                "add a same-underlying-problem judgment or use --include-related"
            )
        queries.append(
            {
                **data,
                "relevant_issue_numbers": sorted(relevant[key]),
            }
        )

    payload = {
        "version": 1,
        "illustrative_only": False,
        "judgments_verified": True,
        "evaluation_eligible": False,
        "candidate_source": "issuelens_retrieval_pool",
        "relevance_definition": (
            "same underlying problem plus related but different"
            if include_related
            else "same underlying problem"
        ),
        "queries": queries,
    }
    output = Path(output_path)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    return output.resolve(), len(queries)


def _review_rows(
    repository_full_name: str,
    query_issue: Issue,
    method_results: dict[str, list[SimilarIssue]],
) -> list[dict[str, str | int]]:
    candidates: dict[int, tuple[SimilarIssue, dict[str, int]]] = {}
    for method in ("semantic", "keyword", "hybrid"):
        for rank, candidate in enumerate(method_results[method], start=1):
            if candidate.id not in candidates:
                candidates[candidate.id] = (candidate, {})
            candidates[candidate.id][1][method] = rank

    ordered = sorted(
        candidates.values(),
        key=lambda item: (
            min(item[1].values()),
            -len(item[1]),
            item[0].number,
        ),
    )
    rows = []
    for candidate, ranks in ordered:
        rows.append(
            {
                "query_repository": repository_full_name,
                "query_issue_number": query_issue.number,
                "query_title": query_issue.title,
                "query_body": query_issue.body or "",
                "query_github_url": query_issue.html_url,
                "query_created_at": query_issue.github_created_at.isoformat(),
                "candidate_issue_number": candidate.number,
                "candidate_title": candidate.title,
                "candidate_body_excerpt": _excerpt(candidate.body),
                "candidate_github_url": candidate.html_url,
                "semantic_rank": ranks.get("semantic", ""),
                "keyword_rank": ranks.get("keyword", ""),
                "hybrid_rank": ranks.get("hybrid", ""),
                "judgment": "",
            }
        )
    return rows


def _title_topics(title: str) -> set[str]:
    return {
        match.group(0).casefold()
        for match in _TOPIC_WORD.finditer(title)
        if match.group(0).casefold() not in _STOP_WORDS
    }


def _excerpt(body: str | None, limit: int = 300) -> str:
    text = " ".join((body or "").split())
    if len(text) <= limit:
        return text
    return f"{text[: limit - 3].rstrip()}..."
