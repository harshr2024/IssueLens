import json

import pytest

from app.evaluation import (
    EvaluationFileError,
    calculate_metrics,
    load_evaluation_file,
)


def test_metric_calculations() -> None:
    rankings = [
        [9, 2, 7, 8, 3, 4],
        [10, 11, 12, 13, 14, 20],
    ]
    relevant = [frozenset({2, 3}), frozenset({20})]

    metrics = calculate_metrics(rankings, relevant)

    assert metrics.recall_at_5 == pytest.approx(0.5)
    assert metrics.mrr == pytest.approx((1 / 2 + 1 / 6) / 2)


def test_metrics_handle_empty_retrieval_results() -> None:
    metrics = calculate_metrics([[]], [frozenset({42})])

    assert metrics.recall_at_5 == 0.0
    assert metrics.mrr == 0.0


def test_illustrative_evaluation_file_cannot_report_metrics(tmp_path) -> None:
    path = tmp_path / "example.json"
    path.write_text(
        json.dumps(
            {
                "version": 1,
                "illustrative_only": True,
                "queries": [],
            }
        ),
        encoding="utf-8",
    )

    with pytest.raises(EvaluationFileError, match="illustrative_only"):
        load_evaluation_file(path)
