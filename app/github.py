from collections.abc import Iterator
from dataclasses import dataclass
from typing import Any, Literal

import httpx


class GitHubAPIError(RuntimeError):
    """A clear, user-facing GitHub API failure."""


@dataclass(frozen=True)
class GitHubRepository:
    github_id: int
    owner: str
    name: str
    full_name: str
    html_url: str


class GitHubClient:
    def __init__(
        self,
        token: str | None = None,
        *,
        client: httpx.Client | None = None,
        base_url: str = "https://api.github.com",
    ) -> None:
        headers = {
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
            "User-Agent": "IssueLens/0.1",
        }
        if token:
            headers["Authorization"] = f"Bearer {token}"
        self._owns_client = client is None
        self.client = client or httpx.Client(
            base_url=base_url, headers=headers, timeout=30.0
        )

    def close(self) -> None:
        if self._owns_client:
            self.client.close()

    def __enter__(self) -> "GitHubClient":
        return self

    def __exit__(self, *_: object) -> None:
        self.close()

    def get_repository(self, full_name: str) -> GitHubRepository:
        data = self._get(f"/repos/{full_name}").json()
        owner, name = data["full_name"].split("/", 1)
        return GitHubRepository(
            github_id=data["id"],
            owner=owner,
            name=name,
            full_name=data["full_name"],
            html_url=data["html_url"],
        )

    def get_issue(self, full_name: str, number: int) -> dict[str, Any]:
        record = self._get(f"/repos/{full_name}/issues/{number}").json()
        if "pull_request" in record:
            raise GitHubAPIError(
                f"GitHub item {full_name}#{number} is a pull request, not an issue"
            )
        return record

    def iter_issues(
        self,
        full_name: str,
        max_issues: int,
        *,
        state: Literal["open", "closed", "all"] = "all",
        sort: Literal["created", "updated", "comments"] = "created",
        direction: Literal["asc", "desc"] = "asc",
    ) -> Iterator[dict[str, Any]]:
        if max_issues < 1:
            raise ValueError("max_issues must be at least 1")

        per_page = min(max_issues, 100)
        yielded = 0
        request_url = f"/repos/{full_name}/issues"
        request_params: dict[str, Any] | None = {
            "state": state,
            "sort": sort,
            "direction": direction,
            "per_page": per_page,
        }
        seen_next_urls: set[str] = set()

        while yielded < max_issues:
            if request_params is None:
                response = self._get(request_url)
            else:
                response = self._get(request_url, params=request_params)
            records = response.json()
            if not isinstance(records, list):
                raise GitHubAPIError("GitHub returned an unexpected issues response")

            for record in records:
                if "pull_request" in record:
                    continue
                yield record
                yielded += 1
                if yielded >= max_issues:
                    return

            next_url = response.links.get("next", {}).get("url")
            if not next_url:
                return
            if next_url in seen_next_urls:
                raise GitHubAPIError(
                    "GitHub returned a repeated pagination URL; stopping to avoid a loop"
                )
            seen_next_urls.add(next_url)
            request_url = next_url
            request_params = None

    def _get(self, path: str, **kwargs: Any) -> httpx.Response:
        try:
            response = self.client.get(path, **kwargs)
        except httpx.RequestError as exc:
            raise GitHubAPIError(f"Could not reach GitHub: {exc}") from exc

        if response.is_success:
            return response

        remaining = response.headers.get("X-RateLimit-Remaining")
        reset = response.headers.get("X-RateLimit-Reset")
        try:
            detail = response.json().get("message", response.text)
        except ValueError:
            detail = response.text
        if response.status_code in (403, 429) and remaining == "0":
            raise GitHubAPIError(
                f"GitHub API rate limit exceeded (resets at Unix timestamp {reset or 'unknown'}). "
                "Set GITHUB_TOKEN for a higher limit."
            )
        raise GitHubAPIError(
            f"GitHub API request failed with HTTP {response.status_code}: {detail}"
        )
