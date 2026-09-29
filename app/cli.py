import argparse
import sys

from sqlalchemy import func, select

from app.benchmark import BenchmarkError, evaluate_benchmark_pairs, load_benchmark_file
from app.config import get_github_token
from app.database import SessionLocal
from app.embedding import (
    EmbeddingError,
    RepositoryNotFoundError,
    SentenceTransformerEmbedder,
    embed_imported_issues,
    embedding_text,
    encode_text,
)
from app.evaluation import EvaluationFileError, calculate_metrics, load_evaluation_file
from app.github import GitHubAPIError, GitHubClient
from app.importer import import_issue_numbers, import_issues
from app.models import Issue, Repository
from app.review import ReviewError, convert_review_sheet, export_review_sheet
from app.search import SimilarIssue, retrieve_all_methods


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="issuelens")
    subparsers = parser.add_subparsers(dest="command", required=True)
    import_parser = subparsers.add_parser(
        "import-issues", help="Import issues from a public GitHub repository"
    )
    import_parser.add_argument("repository", help="Repository in owner/repo format")
    import_parser.add_argument("--max-issues", type=int, default=100)
    import_parser.add_argument(
        "--state",
        choices=("open", "closed", "all"),
        default="all",
        help="Issue state to request (default: all)",
    )
    import_parser.add_argument(
        "--sort",
        choices=("created", "updated", "comments"),
        default="created",
        help="GitHub field used to sort issues (default: created)",
    )
    import_parser.add_argument(
        "--direction",
        choices=("asc", "desc"),
        default="asc",
        help="Sort direction; use desc for newest first (default: asc)",
    )
    embed_parser = subparsers.add_parser(
        "embed-issues", help="Embed imported issues with the local model"
    )
    embed_parser.add_argument("repository", help="Repository in owner/repo format")
    embed_parser.add_argument(
        "--batch-size",
        type=int,
        default=32,
        help="Texts passed to the model per batch (default: 32)",
    )
    compare_parser = subparsers.add_parser(
        "compare-search", help="Compare semantic, keyword, and hybrid rankings"
    )
    compare_parser.add_argument("repository", help="Repository in owner/repo format")
    compare_parser.add_argument("--title", required=True, help="Query issue title")
    compare_parser.add_argument("--body", default=None, help="Optional query issue body")
    compare_parser.add_argument("--limit", type=int, default=5)
    evaluate_parser = subparsers.add_parser(
        "evaluate-search", help="Evaluate retrieval using manually verified judgments"
    )
    evaluate_parser.add_argument("evaluation_file", help="Path to evaluation JSON")
    review_parser = subparsers.add_parser(
        "export-review", help="Export a manual relevance-review CSV"
    )
    review_parser.add_argument("repository", help="Repository in owner/repo format")
    review_parser.add_argument(
        "--output",
        default="reviews/relevance-review.csv",
        help="CSV output path (default: reviews/relevance-review.csv)",
    )
    review_parser.add_argument("--query-count", type=int, default=20)
    review_parser.add_argument("--candidates-per-method", type=int, default=5)
    convert_parser = subparsers.add_parser(
        "convert-review", help="Convert a completed review CSV to evaluation JSON"
    )
    convert_parser.add_argument("review_csv", help="Completed review CSV")
    convert_parser.add_argument("output_json", help="Verified evaluation JSON output")
    convert_parser.add_argument(
        "--include-related",
        action="store_true",
        help="Treat 'related but different' judgments as relevant too",
    )
    prepare_benchmark_parser = subparsers.add_parser(
        "prepare-benchmark",
        help="Import and embed issues referenced by a benchmark candidate file",
    )
    prepare_benchmark_parser.add_argument("benchmark_file")
    prepare_benchmark_parser.add_argument("--batch-size", type=int, default=32)
    benchmark_parser = subparsers.add_parser(
        "evaluate-benchmark",
        help="Evaluate manually approved evidence-backed issue pairs",
    )
    benchmark_parser.add_argument("benchmark_file")
    return parser


def main() -> None:
    args = build_parser().parse_args()
    if args.command == "import-issues":
        if args.repository.count("/") != 1:
            raise SystemExit("repository must use the owner/repo format")
        if args.max_issues < 1:
            raise SystemExit("--max-issues must be at least 1")
        try:
            with GitHubClient(token=get_github_token()) as github, SessionLocal() as session:
                created, updated = import_issues(
                    session,
                    github,
                    args.repository,
                    args.max_issues,
                    state=args.state,
                    sort=args.sort,
                    direction=args.direction,
                )
        except GitHubAPIError as exc:
            print(f"Import failed: {exc}", file=sys.stderr)
            raise SystemExit(1) from exc
        except Exception:
            print("Import failed; the database transaction was rolled back.", file=sys.stderr)
            raise
        print(f"Import complete: {created} created, {updated} updated")
    elif args.command == "embed-issues":
        if args.repository.count("/") != 1:
            raise SystemExit("repository must use the owner/repo format")
        if args.batch_size < 1:
            raise SystemExit("--batch-size must be at least 1")
        try:
            embedder = SentenceTransformerEmbedder()
            with SessionLocal() as session:
                result = embed_imported_issues(
                    session,
                    embedder,
                    args.repository,
                    batch_size=args.batch_size,
                )
        except (EmbeddingError, RepositoryNotFoundError) as exc:
            print(f"Embedding failed: {exc}", file=sys.stderr)
            raise SystemExit(1) from exc
        print(
            f"Embedding complete: {result.embedded} embedded, "
            f"{result.skipped} unchanged and skipped"
        )
    elif args.command == "compare-search":
        if args.repository.count("/") != 1:
            raise SystemExit("repository must use the owner/repo format")
        if not args.title.strip():
            raise SystemExit("--title must not be empty")
        if not 1 <= args.limit <= 20:
            raise SystemExit("--limit must be between 1 and 20")
        try:
            embedder = SentenceTransformerEmbedder()
            query_embedding = encode_text(embedder, args.title, args.body)
            with SessionLocal() as session:
                _require_repository(session, args.repository)
                results = retrieve_all_methods(
                    session,
                    args.repository,
                    embedding_text(args.title, args.body),
                    query_embedding,
                    limit=args.limit,
                )
        except (EmbeddingError, RepositoryNotFoundError) as exc:
            print(f"Search failed: {exc}", file=sys.stderr)
            raise SystemExit(1) from exc
        _print_side_by_side(results, args.limit)
    elif args.command == "evaluate-search":
        try:
            queries = load_evaluation_file(args.evaluation_file)
            embedder = SentenceTransformerEmbedder()
            rankings = {"semantic": [], "keyword": [], "hybrid": []}
            relevant_sets = []
            with SessionLocal() as session:
                for query in queries:
                    repository = _require_repository(session, query.repository)
                    issue_count = session.scalar(
                        select(func.count(Issue.id)).where(
                            Issue.repository_id == repository.id
                        )
                    ) or 0
                    stored_relevant = set(
                        session.scalars(
                            select(Issue.number).where(
                                Issue.repository_id == repository.id,
                                Issue.number.in_(query.relevant_issue_numbers),
                            )
                        )
                    )
                    missing = query.relevant_issue_numbers - stored_relevant
                    if missing:
                        missing_text = ", ".join(
                            f"#{number}" for number in sorted(missing)
                        )
                        raise EvaluationFileError(
                            f"Query {query.query_id!r} references issue numbers not "
                            f"stored in {query.repository}: {missing_text}"
                        )
                    query_embedding = encode_text(embedder, query.title, query.body)
                    results = retrieve_all_methods(
                        session,
                        query.repository,
                        embedding_text(query.title, query.body),
                        query_embedding,
                        limit=max(issue_count, 5),
                        candidate_limit=max(issue_count, 5),
                    )
                    for method in rankings:
                        rankings[method].append(
                            [result.number for result in results[method]]
                        )
                    relevant_sets.append(query.relevant_issue_numbers)
            for method in ("semantic", "keyword", "hybrid"):
                metrics = calculate_metrics(rankings[method], relevant_sets)
                print(
                    f"{method:8} Recall@5={metrics.recall_at_5:.4f} "
                    f"MRR={metrics.mrr:.4f}"
                )
        except (
            EmbeddingError,
            EvaluationFileError,
            RepositoryNotFoundError,
        ) as exc:
            print(f"Evaluation failed: {exc}", file=sys.stderr)
            raise SystemExit(1) from exc
    elif args.command == "export-review":
        if args.repository.count("/") != 1:
            raise SystemExit("repository must use the owner/repo format")
        if args.query_count < 1:
            raise SystemExit("--query-count must be at least 1")
        if not 1 <= args.candidates_per_method <= 20:
            raise SystemExit("--candidates-per-method must be between 1 and 20")
        try:
            with SessionLocal() as session:
                result = export_review_sheet(
                    session,
                    args.repository,
                    args.output,
                    query_count=args.query_count,
                    candidates_per_method=args.candidates_per_method,
                )
        except ReviewError as exc:
            print(f"Review export failed: {exc}", file=sys.stderr)
            raise SystemExit(1) from exc
        print(
            f"Review sheet saved to {result.path} "
            f"({result.query_count} queries, {result.row_count} candidate rows)"
        )
    elif args.command == "convert-review":
        try:
            output, query_count = convert_review_sheet(
                args.review_csv,
                args.output_json,
                include_related=args.include_related,
            )
        except ReviewError as exc:
            print(f"Review conversion failed: {exc}", file=sys.stderr)
            raise SystemExit(1) from exc
        print(f"Verified evaluation JSON saved to {output} ({query_count} queries)")
    elif args.command == "prepare-benchmark":
        if args.batch_size < 1:
            raise SystemExit("--batch-size must be at least 1")
        try:
            pairs = load_benchmark_file(args.benchmark_file)
            by_repository: dict[str, set[int]] = {}
            for pair in pairs:
                by_repository.setdefault(pair.repository, set()).update(
                    [pair.query_issue_number, pair.target_issue_number]
                )
            embedder = SentenceTransformerEmbedder()
            with GitHubClient(token=get_github_token()) as github, SessionLocal() as session:
                total_created = 0
                total_updated = 0
                total_embedded = 0
                total_skipped = 0
                for repository, numbers in by_repository.items():
                    created, updated = import_issue_numbers(
                        session, github, repository, numbers
                    )
                    embedding_result = embed_imported_issues(
                        session,
                        embedder,
                        repository,
                        batch_size=args.batch_size,
                    )
                    total_created += created
                    total_updated += updated
                    total_embedded += embedding_result.embedded
                    total_skipped += embedding_result.skipped
        except (BenchmarkError, EmbeddingError, GitHubAPIError) as exc:
            print(f"Benchmark preparation failed: {exc}", file=sys.stderr)
            raise SystemExit(1) from exc
        print(
            f"Benchmark preparation complete: {total_created} imported, "
            f"{total_updated} updated, {total_embedded} embedded, "
            f"{total_skipped} unchanged embeddings skipped"
        )
    elif args.command == "evaluate-benchmark":
        try:
            pairs = load_benchmark_file(args.benchmark_file)
            with SessionLocal() as session:
                result = evaluate_benchmark_pairs(session, pairs)
        except BenchmarkError as exc:
            print(f"Benchmark evaluation failed: {exc}", file=sys.stderr)
            raise SystemExit(1) from exc
        print(f"Verified pairs: {result.pair_count}")
        for method in ("semantic", "keyword", "hybrid"):
            metrics = result.metrics[method]
            print(
                f"{method:8} Recall@5={metrics.recall_at_5:.4f} "
                f"MRR={metrics.mrr:.4f}"
            )


def _require_repository(session, full_name: str) -> Repository:
    repository = session.scalar(
        select(Repository).where(Repository.full_name == full_name)
    )
    if repository is None:
        raise RepositoryNotFoundError(f"Repository {full_name!r} has not been imported")
    return repository


def _format_result(result: SimilarIssue | None) -> str:
    if result is None:
        return ""
    title = " ".join(result.title.split())
    if len(title) > 31:
        title = f"{title[:28]}..."
    return f"#{result.number} {title} [{result.similarity_score:.4f}]"


def _print_side_by_side(
    results: dict[str, list[SimilarIssue]], limit: int
) -> None:
    width = 48
    print(
        f"{'Rank':<5}"
        f"{'Semantic':<{width}}"
        f"{'Keyword':<{width}}"
        "Hybrid"
    )
    for index in range(limit):
        cells = [
            _format_result(results[method][index] if index < len(results[method]) else None)
            for method in ("semantic", "keyword", "hybrid")
        ]
        print(
            f"{index + 1:<5}"
            f"{cells[0]:<{width}}"
            f"{cells[1]:<{width}}"
            f"{cells[2]}"
        )


if __name__ == "__main__":
    main()
