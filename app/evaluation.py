import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any


class EvaluationFileError(ValueError):
    pass


@dataclass(frozen=True)
class EvaluationQuery:
    query_id: str
    repository: str
    title: str
    body: str | None
    relevant_issue_numbers: frozenset[int]


@dataclass(frozen=True)
class RetrievalMetrics:
    recall_at_5: float
    mrr: float


def load_evaluation_file(path: str | Path) -> list[EvaluationQuery]:
    try:
        data: dict[str, Any] = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise EvaluationFileError(f"Could not read evaluation file: {exc}") from exc

    if data.get("illustrative_only") is True:
        raise EvaluationFileError(
            "This file is marked illustrative_only and cannot be evaluated"
        )
    if data.get("judgments_verified") is not True:
        raise EvaluationFileError(
            "Evaluation files must set judgments_verified to true after manual review"
        )
    if data.get("evaluation_eligible") is False:
        raise EvaluationFileError(
            "This file was derived from an IssueLens retrieval pool and is not "
            "eligible for unbiased Recall/MRR; use evaluate-benchmark"
        )
    if data.get("version") != 1:
        raise EvaluationFileError("Evaluation file version must be 1")
    raw_queries = data.get("queries")
    if not isinstance(raw_queries, list) or not raw_queries:
        raise EvaluationFileError("Evaluation file must contain at least one query")

    queries: list[EvaluationQuery] = []
    for index, raw in enumerate(raw_queries, start=1):
        try:
            query_id = str(raw["id"])
            repository = str(raw["repository"])
            title = str(raw["title"])
            body = raw.get("body")
            relevant = frozenset(int(value) for value in raw["relevant_issue_numbers"])
        except (KeyError, TypeError, ValueError) as exc:
            raise EvaluationFileError(f"Invalid query at position {index}: {exc}") from exc
        if not query_id or repository.count("/") != 1 or not title.strip():
            raise EvaluationFileError(f"Invalid query metadata at position {index}")
        if body is not None and not isinstance(body, str):
            raise EvaluationFileError(f"Query body at position {index} must be text or null")
        if not relevant or any(number < 1 for number in relevant):
            raise EvaluationFileError(
                f"Query at position {index} needs verified positive issue numbers"
            )
        queries.append(
            EvaluationQuery(
                query_id=query_id,
                repository=repository,
                title=title,
                body=body,
                relevant_issue_numbers=relevant,
            )
        )
    return queries


def calculate_metrics(
    rankings: list[list[int]], relevant_sets: list[frozenset[int]]
) -> RetrievalMetrics:
    if not rankings or len(rankings) != len(relevant_sets):
        raise ValueError("rankings and relevant_sets must have the same non-zero length")

    recalls: list[float] = []
    reciprocal_ranks: list[float] = []
    for ranking, relevant in zip(rankings, relevant_sets, strict=True):
        if not relevant:
            raise ValueError("each query must have at least one relevant issue")
        recalls.append(len(set(ranking[:5]) & relevant) / len(relevant))
        first_relevant_rank = next(
            (rank for rank, number in enumerate(ranking, start=1) if number in relevant),
            None,
        )
        reciprocal_ranks.append(
            0.0 if first_relevant_rank is None else 1.0 / first_relevant_rank
        )

    count = len(rankings)
    return RetrievalMetrics(
        recall_at_5=sum(recalls) / count,
        mrr=sum(reciprocal_ranks) / count,
    )
