from datetime import datetime, timezone
import json

import httpx
import pytest
from fastapi.testclient import TestClient

import app.main as main_module
from app.database import get_db
from app.main import app
from app.models import Repository
from app.search import SimilarIssue
from app.triage import CandidateExplanation, OllamaClient, OllamaResponseError, OllamaTimeoutError, evidence_options, get_ollama_client, render_explanation


def add_repository(session) -> None:
    session.add(
        Repository(
            github_id=1,
            owner="pallets",
            name="flask",
            full_name="pallets/flask",
            html_url="https://github.com/pallets/flask",
            imported_at=datetime.now(timezone.utc),
        )
    )
    session.commit()


def candidates() -> list[SimilarIssue]:
    return [
        SimilarIssue(
            id=11,
            number=101,
            title="Reload stops after syntax errors",
            body="The development server does not resume watching files.",
            html_url="https://github.com/pallets/flask/issues/101",
            similarity_score=0.91,
        ),
        SimilarIssue(
            id=22,
            number=202,
            title="Debugger reload regression",
            body="A syntax error interrupts the debug reloader.",
            html_url="https://github.com/pallets/flask/issues/202",
            similarity_score=0.83,
        ),
        SimilarIssue(
            id=33,
            number=303,
            title="Reloader does not recover",
            body="File changes are ignored after an import failure.",
            html_url="https://github.com/pallets/flask/issues/303",
            similarity_score=0.75,
        ),
    ]


def ollama_client(handler) -> OllamaClient:
    return OllamaClient(
        base_url="http://ollama.test",
        model="qwen3:4b",
        timeout_seconds=1,
        transport=httpx.MockTransport(handler),
    )


def configure_endpoint(session, monkeypatch, ollama: OllamaClient) -> None:
    add_repository(session)

    def override_db():
        yield session

    app.dependency_overrides[get_db] = override_db
    app.dependency_overrides[get_ollama_client] = lambda: ollama
    monkeypatch.setattr(main_module, "get_embedder", lambda: object())
    monkeypatch.setattr(main_module, "encode_text", lambda *args: [0.0] * 384)
    monkeypatch.setattr(
        main_module,
        "search_similar_issues",
        lambda session, repository, embedding, *, limit: candidates()[:limit],
    )


def test_triage_returns_validated_model_output_with_real_candidate_metadata(
    session, monkeypatch
) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        payload = json.loads(request.content)
        assert request.url == "http://ollama.test/api/chat"
        assert payload["model"] == "qwen3:4b"
        assert payload["stream"] is False
        assert payload["think"] is False
        assert isinstance(payload["format"], dict)
        variants = payload["format"]["properties"]["candidate_explanations"]["items"]["anyOf"]
        assert [variant["properties"]["candidate_id"]["const"] for variant in variants] == [11, 11, 22, 22, 33, 33]
        assert 'A syntax error interrupts the debug reloader.' not in variants[0]["properties"]["candidate_evidence"]["enum"]
        content = {
            "missing_information": [
                "Relevant package and runtime versions.",
                "Full error message or traceback, if one is shown.",
            ],
            "candidate_explanations": [
                {
                    "candidate_id": 11,
                    "grounding": "specific_overlap",
                    "submitted_evidence": "Reloading stops after a syntax error.",
                    "candidate_evidence": "Reload stops after syntax errors",
                },
                {
                    "candidate_id": 22,
                    "grounding": "specific_overlap",
                    "submitted_evidence": "syntax error",
                    "candidate_evidence": "syntax error",
                },
                {
                    "candidate_id": 33,
                    "grounding": "insufficient_evidence",
                    "submitted_evidence": None,
                    "candidate_evidence": None,
                },
            ],
        }
        return httpx.Response(200, json={"message": {"content": json.dumps(content)}})

    configure_endpoint(session, monkeypatch, ollama_client(handler))
    try:
        with TestClient(app) as client:
            response = client.post(
                "/triage",
                json={
                    "repository": "pallets/flask",
                    "title": "Development server fails to reload",
                    "body": "Reloading stops after a syntax error.",
                },
            )
        assert response.status_code == 200
        result = response.json()
        assert result['candidates'][2]['overlap_explanation'] == 'insufficient evidence of the same underlying issue'
        assert result["model"] == "qwen3:4b"
        assert len(result["candidates"]) == 3
        assert result["candidates"][0] == {
            "id": 11,
            "number": 101,
            "title": "Reload stops after syntax errors",
            "html_url": "https://github.com/pallets/flask/issues/101",
            "similarity_score": 0.91,
            "overlap_explanation": 'Report excerpt: “Reloading stops after a syntax error.” — candidate excerpt: “Reload stops after syntax errors”. These excerpts are for comparison; they do not establish a shared cause.',
        }
    finally:
        app.dependency_overrides.clear()


def test_triage_rejects_unsupported_causal_ollama_output(session, monkeypatch) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        invalid = {
            "missing_information": [],
            "candidate_explanations": [
                {
                    "candidate_id": 11,
                    "grounding": "specific_overlap",
                    "submitted_evidence": "Development server",
                    "candidate_evidence": "development server",
                    "explanation": "The socket setting causes the reported reload failure.",
                },
                {
                    "candidate_id": 22,
                    "grounding": "insufficient_evidence",
                    "submitted_evidence": None,
                    "candidate_evidence": None,
                },
                {
                    "candidate_id": 33,
                    "grounding": "insufficient_evidence",
                    "submitted_evidence": None,
                    "candidate_evidence": None,
                },
            ],
        }
        return httpx.Response(200, json={"message": {"content": json.dumps(invalid)}})

    configure_endpoint(session, monkeypatch, ollama_client(handler))
    try:
        with TestClient(app) as client:
            response = client.post(
                "/triage",
                json={
                    "repository": "pallets/flask",
                    "title": "Development server fails to reload",
                    "body": "Reloading stops after a syntax error.",
                },
            )
        assert response.status_code == 502
        assert response.json()["detail"] == "Ollama returned invalid structured triage data"
    finally:
        app.dependency_overrides.clear()


def test_triage_reports_unavailable_ollama_service(session, monkeypatch) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("connection refused", request=request)

    configure_endpoint(session, monkeypatch, ollama_client(handler))
    try:
        with TestClient(app) as client:
            response = client.post(
                "/triage",
                json={
                    "repository": "pallets/flask",
                    "title": "Development server fails to reload",
                    "body": "Reloading stops after a syntax error.",
                },
            )
        assert response.status_code == 503
        assert response.json()["detail"] == (
            "Could not reach Ollama at http://ollama.test"
        )
    finally:
        app.dependency_overrides.clear()


@pytest.mark.parametrize("failure", ["invented_excerpt", "wrong_candidate", "duplicate_id", "invalid_json", "causal", "url"])
def test_rejects_ungrounded_or_malformed_results(failure):
    items = [{"candidate_id": item.id, "grounding": "insufficient_evidence"} for item in candidates()]
    if failure == "invented_excerpt":
        items[0].update(grounding="specific_overlap", submitted_evidence="Made up symptom",
                        candidate_evidence="does not resume watching files")
    elif failure == "wrong_candidate":
        items[0]["candidate_id"] = 999
    elif failure == "duplicate_id":
        items[0]["candidate_id"] = 22
    elif failure == "causal":
        items[0]["explanation"] = "Eager loading fixes the failure."
    elif failure == "url":
        items[0]["explanation"] = "See https://example.com for details."
    content = 'not JSON' if failure == "invalid_json" else json.dumps({"missing_information":[], "candidate_explanations":items})
    client = ollama_client(lambda request: httpx.Response(200, json={"message":{"content":content}}))
    with pytest.raises(OllamaResponseError):
        client.analyze(title="Reload failure", body=None, candidates=candidates())


def test_timeout_is_explicit():
    def handler(request):
        raise httpx.ReadTimeout("slow", request=request)
    with pytest.raises(OllamaTimeoutError):
        ollama_client(handler).analyze(title="Reload failure", body=None, candidates=[])


def test_evidence_options_preserve_exact_source_and_bound_lengths():
    text = 'Capitalized symptom.\r\n  Another symptom with "quotes". ' + 'x' * 400
    assert all(option in text and 0 < len(option) <= 180 for option in evidence_options(text))


def test_broad_server_overlap_cannot_be_displayed_as_specific_evidence():
    item = CandidateExplanation(candidate_id=1, grounding='specific_overlap',
        submitted_evidence='Development server fails to reload',
        candidate_evidence='SO_REUSEADDR set server')
    assert render_explanation(item) == 'insufficient evidence of the same underlying issue'


def test_triage_input_limits_prevent_model_call():
    with TestClient(app) as client:
        for title, body in [(' ', ''), ('x' * 301, ''), ('Bug', 'x' * 8001)]:
            response = client.post('/triage', json={'repository':'pallets/flask', 'title':title, 'body':body})
            assert response.status_code == 422
