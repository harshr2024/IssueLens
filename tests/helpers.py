from copy import deepcopy

from app.github import GitHubRepository


def issue_record(
    github_id: int = 1001,
    number: int = 1,
    title: str = "Example issue",
) -> dict:
    return {
        "id": github_id,
        "number": number,
        "title": title,
        "body": "Useful reproduction details",
        "html_url": f"https://github.com/acme/widgets/issues/{number}",
        "state": "open",
        "labels": [{"name": "bug"}, {"name": "triage"}],
        "created_at": "2025-01-02T03:04:05Z",
        "updated_at": "2025-02-03T04:05:06Z",
    }


class FakeGitHubClient:
    def __init__(self, issues: list[dict]) -> None:
        self.issues = issues

    def get_repository(self, full_name: str) -> GitHubRepository:
        owner, name = full_name.split("/")
        return GitHubRepository(
            github_id=42,
            owner=owner,
            name=name,
            full_name=full_name,
            html_url=f"https://github.com/{full_name}",
        )

    def iter_issues(
        self,
        full_name: str,
        max_issues: int,
        *,
        state: str = "all",
        sort: str = "created",
        direction: str = "asc",
    ):
        del full_name
        del state, sort, direction
        yield from deepcopy(self.issues[:max_issues])
