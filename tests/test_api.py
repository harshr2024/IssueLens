from datetime import datetime, timezone

from fastapi.testclient import TestClient

from app.database import get_db
from app.main import app
from app.models import Issue, Repository


def seed(session, full_name: str, number: int) -> Issue:
    now = datetime.now(timezone.utc)
    owner, name = full_name.split("/")
    repository = Repository(
        github_id=number,
        owner=owner,
        name=name,
        full_name=full_name,
        html_url=f"https://github.com/{full_name}",
        imported_at=now,
    )
    issue = Issue(
        repository=repository,
        github_id=1000 + number,
        number=number,
        title=f"Issue {number}",
        body=None,
        html_url=f"https://github.com/{full_name}/issues/{number}",
        state="open",
        labels=[],
        github_created_at=now,
        github_updated_at=now,
        imported_at=now,
    )
    session.add(issue)
    session.commit()
    return issue


def test_list_filter_pagination_and_fetch_by_id(session) -> None:
    first = seed(session, "acme/one", 1)
    seed(session, "acme/two", 2)

    def override_db():
        yield session

    app.dependency_overrides[get_db] = override_db
    try:
        with TestClient(app) as client:
            response = client.get("/issues", params={"repository": "acme/one", "limit": 1})
            assert response.status_code == 200
            assert response.json()["total"] == 1
            assert response.json()["items"][0]["repository"]["full_name"] == "acme/one"

            detail = client.get(f"/issues/{first.id}")
            assert detail.status_code == 200
            assert detail.json()["github_id"] == 1001

            assert client.get("/issues/9999").status_code == 404
            assert client.get("/health").json() == {"status": "ok"}
    finally:
        app.dependency_overrides.clear()


def test_similarity_search_rejects_empty_title_without_loading_model(session) -> None:
    def override_db():
        yield session

    app.dependency_overrides[get_db] = override_db
    try:
        with TestClient(app) as client:
            response = client.post(
                "/similar-issues",
                json={"title": "   ", "body": "", "repository": "acme/widgets"},
            )
        assert response.status_code == 422
        assert "title must not be empty" in response.text
    finally:
        app.dependency_overrides.clear()
