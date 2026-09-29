import httpx
import pytest

from app.github import GitHubAPIError, GitHubClient
from tests.helpers import issue_record


def make_client(handler) -> GitHubClient:
    http_client = httpx.Client(
        transport=httpx.MockTransport(handler), base_url="https://api.github.test"
    )
    return GitHubClient(client=http_client)


def test_pull_requests_are_excluded() -> None:
    issue = issue_record()
    pull_request = issue_record(github_id=2002, number=2, title="A pull request")
    pull_request["pull_request"] = {"url": "https://api.github.test/pulls/2"}

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=[pull_request, issue], request=request)

    github = make_client(handler)
    assert list(github.iter_issues("acme/widgets", 2)) == [issue]


def test_sort_state_and_newest_first_parameters_are_sent() -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(200, json=[], request=request)

    github = make_client(handler)
    assert list(
        github.iter_issues(
            "acme/widgets",
            10,
            state="all",
            sort="created",
            direction="desc",
        )
    ) == []

    assert len(requests) == 1
    assert requests[0].url.params["state"] == "all"
    assert requests[0].url.params["sort"] == "created"
    assert requests[0].url.params["direction"] == "desc"
    assert "page" not in requests[0].url.params


def test_page_with_pull_request_does_not_count_toward_max_issues() -> None:
    requested_urls: list[str] = []
    pull_request = issue_record(github_id=9000, number=90)
    pull_request["pull_request"] = {"url": "https://api.github.test/pulls/90"}

    def handler(request: httpx.Request) -> httpx.Response:
        requested_urls.append(str(request.url))
        if request.url.params.get("after") == "cursor-1":
            return httpx.Response(
                200,
                json=[issue_record(3, 3), issue_record(4, 4)],
                request=request,
            )
        return httpx.Response(
            200,
            json=[pull_request, issue_record(1, 1), issue_record(2, 2)],
            headers={
                "Link": '<https://api.github.test/repos/acme/widgets/issues?after=cursor-1>; rel="next"'
            },
            request=request,
        )

    github = make_client(handler)
    records = list(github.iter_issues("acme/widgets", 3))

    assert [record["number"] for record in records] == [1, 2, 3]
    assert len(requested_urls) == 2
    assert "page" not in httpx.URL(requested_urls[0]).params
    assert "after=cursor-1" in requested_urls[1]


def test_multiple_cursor_pages_follow_next_links() -> None:
    requested_cursors: list[str | None] = []

    def handler(request: httpx.Request) -> httpx.Response:
        cursor = request.url.params.get("after")
        requested_cursors.append(cursor)
        if cursor is None:
            records = [issue_record(1, 1)]
            next_cursor = "one"
        elif cursor == "one":
            records = [issue_record(2, 2)]
            next_cursor = "two"
        else:
            records = [issue_record(3, 3)]
            next_cursor = None

        headers = {}
        if next_cursor:
            headers["Link"] = (
                "<https://api.github.test/repos/acme/widgets/issues"
                f"?after={next_cursor}>; rel=\"next\""
            )
        return httpx.Response(200, json=records, headers=headers, request=request)

    records = list(make_client(handler).iter_issues("acme/widgets", 10))

    assert [record["number"] for record in records] == [1, 2, 3]
    assert requested_cursors == [None, "one", "two"]


def test_no_next_link_stops_pagination() -> None:
    requests = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal requests
        requests += 1
        return httpx.Response(200, json=[issue_record()], request=request)

    records = list(make_client(handler).iter_issues("acme/widgets", 10))

    assert len(records) == 1
    assert requests == 1


def test_repeated_next_url_is_rejected() -> None:
    next_url = "https://api.github.test/repos/acme/widgets/issues?after=stuck"

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json=[issue_record()],
            headers={"Link": f'<{next_url}>; rel="next"'},
            request=request,
        )

    github = make_client(handler)
    with pytest.raises(GitHubAPIError, match="repeated pagination URL"):
        list(github.iter_issues("acme/widgets", 10))


def test_rate_limit_error_is_actionable() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            403,
            json={"message": "API rate limit exceeded"},
            headers={"X-RateLimit-Remaining": "0", "X-RateLimit-Reset": "12345"},
            request=request,
        )

    github = make_client(handler)
    with pytest.raises(GitHubAPIError, match="GITHUB_TOKEN"):
        list(github.iter_issues("acme/widgets", 1))
