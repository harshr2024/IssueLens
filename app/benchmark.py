import json
import re
from dataclasses import dataclass
from pathlib import Path

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.embedding import MODEL_IDENTIFIER, embedding_text, embedding_text_hash
from app.evaluation import RetrievalMetrics, calculate_metrics
from app.models import Issue, Repository
from app.search import retrieve_all_methods


_ISSUE_URL = re.compile(
    r"^https://github\.com/(?P<owner>[^/]+)/(?P<repo>[^/]+)/issues/(?P<number>\d+)$"
)


class BenchmarkError(ValueError):
    pass


@dataclass(frozen=True)
class BenchmarkPair:
    pair_id: str
    repository: str
    query_issue_number: int
    target_issue_number: int
    source_issue_url: str
    target_issue_url: str
    evidence_url: str
    evidence_note: str
    approved: bool


@dataclass(frozen=True)
class BenchmarkResult:
    pair_count: int
    metrics: dict[str, RetrievalMetrics]


def load_benchmark_file(path: str | Path) -> list[BenchmarkPair]:
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise BenchmarkError(f"Could not read benchmark file: {exc}") from exc
    if data.get("version") != 1:
        raise BenchmarkError("Benchmark file version must be 1")
    raw_pairs = data.get("pairs")
    if not isinstance(raw_pairs, list) or not raw_pairs:
        raise BenchmarkError("Benchmark file must contain at least one pair")

    pairs = []
    seen_ids = set()
    for index, raw in enumerate(raw_pairs, start=1):
        try:
            pair = BenchmarkPair(
                pair_id=str(raw["id"]),
                repository=str(raw["repository"]),
                query_issue_number=int(raw["query_issue_number"]),
                target_issue_number=int(raw["target_issue_number"]),
                source_issue_url=str(raw["source_issue_url"]),
                target_issue_url=str(raw["target_issue_url"]),
                evidence_url=str(raw["evidence_url"]),
                evidence_note=str(raw["evidence_note"]),
                approved=raw["approved"],
            )
        except (KeyError, TypeError, ValueError) as exc:
            raise BenchmarkError(f"Invalid pair at position {index}: {exc}") from exc
        if not isinstance(pair.approved, bool):
            raise BenchmarkError(f"Pair {pair.pair_id!r} approved must be true or false")
        if not pair.pair_id or pair.pair_id in seen_ids:
            raise BenchmarkError(f"Pair IDs must be nonempty and unique: {pair.pair_id!r}")
        seen_ids.add(pair.pair_id)
        _validate_pair_urls(pair)
        if pair.query_issue_number == pair.target_issue_number:
            raise BenchmarkError(f"Pair {pair.pair_id!r} references the same issue twice")
        pairs.append(pair)
    return pairs


def evaluate_benchmark_pairs(
    session: Session, pairs: list[BenchmarkPair]
) -> BenchmarkResult:
    approved = [pair for pair in pairs if pair.approved]
    if not approved:
        raise BenchmarkError(
            "No pairs are approved; manually inspect each evidence URL and set "
            "approved to true before evaluation"
        )

    rankings: dict[str, list[list[int]]] = {
        "semantic": [],
        "keyword": [],
        "hybrid": [],
    }
    relevant_sets: list[frozenset[int]] = []
    for pair in approved:
        repository = session.scalar(
            select(Repository).where(Repository.full_name == pair.repository)
        )
        if repository is None:
            raise BenchmarkError(f"Repository {pair.repository!r} is not imported")
        issues = {
            issue.number: issue
            for issue in session.scalars(
                select(Issue).where(
                    Issue.repository_id == repository.id,
                    Issue.number.in_(
                        [pair.query_issue_number, pair.target_issue_number]
                    ),
                )
            )
        }
        missing = {
            pair.query_issue_number,
            pair.target_issue_number,
        } - issues.keys()
        if missing:
            raise BenchmarkError(
                f"Pair {pair.pair_id!r} has unimported issues: "
                + ", ".join(f"#{number}" for number in sorted(missing))
            )
        query_issue = issues[pair.query_issue_number]
        target_issue = issues[pair.target_issue_number]
        if target_issue.github_created_at >= query_issue.github_created_at:
            raise BenchmarkError(
                f"Pair {pair.pair_id!r} target must be older than its query issue"
            )
        for issue in (query_issue, target_issue):
            if (
                issue.embedding is None
                or issue.embedding_model != MODEL_IDENTIFIER
                or issue.embedding_text_hash
                != embedding_text_hash(issue.title, issue.body)
            ):
                raise BenchmarkError(
                    f"Pair {pair.pair_id!r} issue #{issue.number} needs a current embedding"
                )

        earlier_count = session.scalar(
            select(func.count(Issue.id)).where(
                Issue.repository_id == repository.id,
                Issue.github_created_at < query_issue.github_created_at,
            )
        ) or 0
        results = retrieve_all_methods(
            session,
            pair.repository,
            embedding_text(query_issue.title, query_issue.body),
            list(query_issue.embedding),
            limit=max(earlier_count, 5),
            candidate_limit=max(earlier_count, 5),
            exclude_issue_id=query_issue.id,
            created_before=query_issue.github_created_at,
        )
        for method in rankings:
            rankings[method].append([result.number for result in results[method]])
        relevant_sets.append(frozenset({target_issue.number}))

    return BenchmarkResult(
        pair_count=len(approved),
        metrics={
            method: calculate_metrics(method_rankings, relevant_sets)
            for method, method_rankings in rankings.items()
        },
    )


def _validate_pair_urls(pair: BenchmarkPair) -> None:
    expected_repo = pair.repository.casefold()
    for label, url, number in (
        ("source", pair.source_issue_url, pair.query_issue_number),
        ("target", pair.target_issue_url, pair.target_issue_number),
    ):
        match = _ISSUE_URL.fullmatch(url)
        if not match:
            raise BenchmarkError(f"Pair {pair.pair_id!r} has an invalid {label} URL")
        url_repo = f"{match['owner']}/{match['repo']}".casefold()
        if url_repo != expected_repo or int(match["number"]) != number:
            raise BenchmarkError(f"Pair {pair.pair_id!r} {label} URL does not match")
    if not pair.evidence_url.startswith(f"{pair.source_issue_url}#"):
        raise BenchmarkError(
            f"Pair {pair.pair_id!r} evidence URL must link to activity on the source issue"
        )
