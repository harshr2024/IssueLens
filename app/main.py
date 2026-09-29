from pathlib import Path

from fastapi import Depends, FastAPI, HTTPException, Query
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy import func, select
from sqlalchemy.orm import Session, joinedload

from app.database import get_db
from app.embedding import (
    MODEL_IDENTIFIER,
    EmbeddingError,
    embedding_text,
    embedding_text_hash,
    encode_text,
    get_embedder,
)
from app.models import Issue, Repository
from app.schemas import (
    IssueListResponse,
    IssueResponse,
    SimilarIssueQuery,
    SimilarIssueResponse,
    TriageCandidateResponse,
    TriageRequest,
    TriageResponse,
)
from app.search import (
    retrieve_all_methods,
    search_keyword_issues,
    search_similar_issues,
)
from app.triage import (
    OllamaClient,
    OllamaResponseError,
    OllamaTimeoutError,
    OllamaUnavailableError,
    get_ollama_client,
    render_explanation,
)


app = FastAPI(title="IssueLens", version="0.3.0")
FRONTEND_DIR = Path(__file__).resolve().parent / "static"
app.mount("/assets", StaticFiles(directory=FRONTEND_DIR, check_dir=False), name="assets")


@app.get("/", include_in_schema=False)
def frontend():
    if not (FRONTEND_DIR / "index.html").exists():
        raise HTTPException(503, "Frontend not built. Run npm --prefix frontend run build.")
    return FileResponse(FRONTEND_DIR / "index.html")


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/issues", response_model=IssueListResponse)
def list_issues(
    limit: int = Query(default=50, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    repository: str | None = Query(default=None, description="Repository full name, e.g. owner/repo"),
    session: Session = Depends(get_db),
) -> IssueListResponse:
    filters = []
    if repository:
        filters.append(Repository.full_name == repository)

    count_statement = select(func.count(Issue.id)).join(Issue.repository).where(*filters)
    total = session.scalar(count_statement) or 0
    statement = (
        select(Issue)
        .join(Issue.repository)
        .options(joinedload(Issue.repository))
        .where(*filters)
        .order_by(Issue.id)
        .limit(limit)
        .offset(offset)
    )
    items = list(session.scalars(statement))
    return IssueListResponse(items=items, total=total, limit=limit, offset=offset)


@app.get("/issues/{issue_id}", response_model=IssueResponse)
def get_issue(issue_id: int, session: Session = Depends(get_db)) -> Issue:
    issue = session.scalar(
        select(Issue)
        .options(joinedload(Issue.repository))
        .where(Issue.id == issue_id)
    )
    if issue is None:
        raise HTTPException(status_code=404, detail="Issue not found")
    return issue


@app.post("/similar-issues", response_model=list[SimilarIssueResponse])
def find_similar_issues(
    query: SimilarIssueQuery,
    session: Session = Depends(get_db),
) -> list[SimilarIssueResponse]:
    repository_exists = session.scalar(
        select(Repository.id).where(Repository.full_name == query.repository)
    )
    if repository_exists is None:
        raise HTTPException(status_code=404, detail="Repository not found")
    query_text = embedding_text(query.title, query.body)
    if query.method == "keyword":
        return search_keyword_issues(
            session, query.repository, query_text, limit=query.limit
        )

    try:
        query_embedding = encode_text(get_embedder(), query.title, query.body)
    except EmbeddingError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    if query.method == "semantic":
        return search_similar_issues(
            session,
            query.repository,
            query_embedding,
            limit=query.limit,
        )
    return retrieve_all_methods(
        session,
        query.repository,
        query_text,
        query_embedding,
        limit=query.limit,
    )["hybrid"]


@app.get("/issues/{issue_id}/similar", response_model=list[SimilarIssueResponse])
def find_issues_similar_to_stored_issue(
    issue_id: int,
    limit: int = Query(default=5, ge=1, le=5),
    method: str = Query(default="semantic", pattern="^(semantic|keyword|hybrid)$"),
    session: Session = Depends(get_db),
) -> list[SimilarIssueResponse]:
    issue = session.scalar(
        select(Issue)
        .options(joinedload(Issue.repository))
        .where(Issue.id == issue_id)
    )
    if issue is None:
        raise HTTPException(status_code=404, detail="Issue not found")
    if method in ("semantic", "hybrid") and (
        issue.embedding is None
        or issue.embedding_model != MODEL_IDENTIFIER
        or issue.embedding_text_hash != embedding_text_hash(issue.title, issue.body)
    ):
        raise HTTPException(
            status_code=409,
            detail="Issue has no current embedding; run the embed-issues command",
        )
    query_text = embedding_text(issue.title, issue.body)
    if method == "keyword":
        return search_keyword_issues(
            session,
            issue.repository.full_name,
            query_text,
            limit=limit,
            exclude_issue_id=issue.id,
        )
    query_embedding = list(issue.embedding)
    if method == "semantic":
        return search_similar_issues(
            session,
            issue.repository.full_name,
            query_embedding,
            limit=limit,
            exclude_issue_id=issue.id,
        )
    return retrieve_all_methods(
        session,
        issue.repository.full_name,
        query_text,
        query_embedding,
        limit=limit,
        exclude_issue_id=issue.id,
    )["hybrid"]


@app.post("/triage", response_model=TriageResponse)
def triage_issue(
    query: TriageRequest,
    session: Session = Depends(get_db),
    ollama: OllamaClient = Depends(get_ollama_client),
) -> TriageResponse:
    repository_exists = session.scalar(
        select(Repository.id).where(Repository.full_name == query.repository)
    )
    if repository_exists is None:
        raise HTTPException(status_code=404, detail="Repository not found")

    try:
        query_embedding = encode_text(get_embedder(), query.title, query.body)
    except EmbeddingError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    candidates = search_similar_issues(
        session,
        query.repository,
        query_embedding,
        limit=3,
    )

    try:
        model_output = ollama.analyze(
            title=query.title,
            body=query.body,
            candidates=candidates,
        )
    except OllamaTimeoutError as exc:
        raise HTTPException(status_code=504, detail=str(exc)) from exc
    except OllamaUnavailableError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except OllamaResponseError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc

    explanations = {
        item.candidate_id: render_explanation(item)
        for item in model_output.candidate_explanations
    }
    return TriageResponse(
        repository=query.repository,
        model=ollama.model,
        missing_information=model_output.missing_information,
        candidates=[
            TriageCandidateResponse(
                id=candidate.id,
                number=candidate.number,
                title=candidate.title,
                html_url=candidate.html_url,
                similarity_score=candidate.similarity_score,
                overlap_explanation=explanations[candidate.id],
            )
            for candidate in candidates
        ],
    )
