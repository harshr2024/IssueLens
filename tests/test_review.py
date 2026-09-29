import csv
import json
from datetime import datetime, timedelta, timezone

import pytest

from app.embedding import EMBEDDING_DIMENSIONS, MODEL_IDENTIFIER, embedding_text_hash
from app.models import Issue, Repository
from app.review import (
    JUDGMENT_SAME,
    JUDGMENT_UNRELATED,
    REVIEW_FIELDS,
    ReviewError,
    convert_review_sheet,
    export_review_sheet,
    select_review_issues,
)
from app.search import SimilarIssue


def make_issue(index: int, *, repository: Repository | None = None) -> Issue:
    created = datetime(2020, 1, 1, tzinfo=timezone.utc) + timedelta(days=index)
    topic = ("reload", "session", "routing", "template")[index % 4]
    issue = Issue(
        repository=repository,
        github_id=10_000 + index,
        number=1_000 + index,
        title=f"{topic} failure case {index}",
        body=f"Detailed reproduction for {topic} issue {index}",
        html_url=f"https://github.com/acme/widgets/issues/{1000 + index}",
        state="open",
        labels=[],
        github_created_at=created,
        github_updated_at=created,
        imported_at=created,
        embedding=[0.01] * EMBEDDING_DIMENSIONS,
        embedding_model=MODEL_IDENTIFIER,
        embedded_at=created,
    )
    issue.id = index + 1
    issue.embedding_text_hash = embedding_text_hash(issue.title, issue.body)
    return issue


def test_review_selection_spans_chronological_slices_and_topics() -> None:
    issues = [make_issue(index) for index in range(40)]

    selected = select_review_issues(issues, count=4)

    selected_indexes = [issue.number - 1000 for issue in selected]
    assert 0 <= selected_indexes[0] < 10
    assert 10 <= selected_indexes[1] < 20
    assert 20 <= selected_indexes[2] < 30
    assert 30 <= selected_indexes[3] < 40
    assert len({issue.title.split()[0] for issue in selected}) >= 3


def test_export_deduplicates_candidates_and_leaves_judgments_blank(
    session, tmp_path, monkeypatch
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
    session.add(repository)
    session.flush()
    for index in range(4):
        issue = make_issue(index, repository=repository)
        issue.id = None
        session.add(issue)
    session.commit()

    first = SimilarIssue(
        id=101,
        number=501,
        title="First candidate",
        body="First candidate body",
        html_url="https://example/501",
        similarity_score=0.9,
    )
    second = SimilarIssue(
        id=102,
        number=502,
        title="Second candidate",
        body="Second candidate body",
        html_url="https://example/502",
        similarity_score=0.8,
    )
    excluded_ids = []

    def fake_retrieve(*args, exclude_issue_id, **kwargs):
        excluded_ids.append(exclude_issue_id)
        return {
            "semantic": [first, second],
            "keyword": [first],
            "hybrid": [second, first],
        }

    monkeypatch.setattr("app.review.retrieve_all_methods", fake_retrieve)
    output = tmp_path / "review.csv"
    result = export_review_sheet(
        session,
        "acme/widgets",
        output,
        query_count=2,
        candidates_per_method=2,
    )

    with output.open(newline="", encoding="utf-8") as handle:
        rows = list(csv.DictReader(handle))
    assert result.query_count == 2
    assert result.row_count == 4
    assert len(excluded_ids) == 2
    assert all(rows[index]["judgment"] == "" for index in range(len(rows)))
    assert rows[0]["semantic_rank"] == "1"
    assert rows[0]["keyword_rank"] == "1"
    assert rows[0]["hybrid_rank"] == "2"


def test_completed_review_converts_to_verified_evaluation_json(tmp_path) -> None:
    review_path = tmp_path / "completed.csv"
    rows = []
    for candidate, judgment in ((501, JUDGMENT_SAME), (502, JUDGMENT_UNRELATED)):
        row = {field: "" for field in REVIEW_FIELDS}
        row.update(
            {
                "query_repository": "acme/widgets",
                "query_issue_number": "1001",
                "query_title": "Reload fails",
                "query_body": "Steps to reproduce",
                "candidate_issue_number": str(candidate),
                "judgment": judgment,
            }
        )
        rows.append(row)
    with review_path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=REVIEW_FIELDS)
        writer.writeheader()
        writer.writerows(rows)

    output_path, count = convert_review_sheet(
        review_path, tmp_path / "verified.json"
    )
    payload = json.loads(output_path.read_text(encoding="utf-8"))

    assert count == 1
    assert payload["judgments_verified"] is True
    assert payload["evaluation_eligible"] is False
    assert payload["candidate_source"] == "issuelens_retrieval_pool"
    assert payload["queries"][0]["relevant_issue_numbers"] == [501]


def test_conversion_rejects_unfinished_judgments(tmp_path) -> None:
    path = tmp_path / "unfinished.csv"
    row = {field: "" for field in REVIEW_FIELDS}
    row.update(
        {
            "query_repository": "acme/widgets",
            "query_issue_number": "1001",
            "query_title": "Reload fails",
            "candidate_issue_number": "501",
        }
    )
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=REVIEW_FIELDS)
        writer.writeheader()
        writer.writerow(row)

    with pytest.raises(ReviewError, match="needs one of these judgments"):
        convert_review_sheet(path, tmp_path / "verified.json")
