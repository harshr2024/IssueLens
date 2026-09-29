# IssueLens

IssueLens imports issues from public GitHub repositories and uses a local
`sentence-transformers/all-MiniLM-L6-v2` model plus PostgreSQL/pgvector to
retrieve semantically similar issue candidates. Phase 2 adds one read-only
triage endpoint backed by local Ollama. Similarity is a retrieval score, not a
probability that two issues are duplicates, and the generated explanations do
not make duplicate decisions. A focused local web interface lets you submit a
report, review missing details, and inspect three candidate issues.

See [local verification evidence](docs/verification.md) for the automated checks,
live demo results, and current limitations.

## Run the demo

Requires Python 3.11+, Node.js 20+, Docker Desktop, and Ollama on macOS.
The frontend uses browser JavaScript and Node's built-in build/test tools;
there are no frontend packages to install. FastAPI serves the UI and API on
the same port, so no separate frontend server or CORS configuration is needed.

### One-time setup

From the project root, install dependencies and initialize a new database.
If you already have the imported and embedded dataset, skip the import and
embedding commands below.

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -e '.[dev]'
test -f .env || cp .env.example .env
set -a; source .env; set +a
docker compose up -d --wait postgres
alembic upgrade head
python -m app.cli import-issues pallets/flask --max-issues 500 --state all --sort created --direction desc
python -m app.cli embed-issues pallets/flask --batch-size 32
npm --prefix frontend run build
```

Install Ollama if needed, start it, then download the triage model once:

```bash
brew install ollama
brew services start ollama
ollama pull qwen3:4b
```

Both model downloads need internet access on first use. Initial GitHub import
also requires internet; `GITHUB_TOKEN` is optional but increases API limits.
For the blueprint demo on a fresh database, the existing `prepare-benchmark`
command in the benchmark section imports the older referenced issues too.

### Normal startup

Reuse the stored dataset, embeddings, downloaded models, and frontend build:

```bash
source .venv/bin/activate
set -a; source .env; set +a
docker compose up -d --wait postgres
brew services start ollama
uvicorn app.main:app --host 127.0.0.1 --port 8001
```

If Ollama is already running, reuse it. Alternatively run `ollama serve` in a
separate terminal instead of using Homebrew services. Open
**http://127.0.0.1:8001/** for the frontend and
**http://127.0.0.1:8001/docs** for the API.

After code updates, run `alembic upgrade head` if migrations changed, and
`npm --prefix frontend run build` if frontend sources changed. Run
`embed-issues` again only after importing new or changed issues, or changing
the embedding model. Normal startup does not require another `ollama pull`,
GitHub import, or batch embedding run.

Click **Try a Flask example** for this realistic input:

- Repository: `pallets/flask`
- Title: `Blueprint renders a template from the wrong folder`
- Description: `I have two Flask blueprints, each with its own templates folder and an index.html file. Calling render_template("index.html") from the second blueprint renders the first blueprint’s template. I expected it to use the template in the second blueprint’s folder.`

The example is useful with the current imported Flask corpus, including the
blueprint template issues. Results depend on which issues you have imported.
For a weak-match comparison, submit `Development server fails to reload` with
`Reloading stops after a syntax error`.

Run checks:

```bash
pytest
npm --prefix frontend test
npm --prefix frontend run build
ISSUELENS_RUN_DB_TESTS=1 pytest tests/test_keyword_postgres.py
```

The UI displays errors from the API, including Ollama availability, timeout,
and invalid-output errors. Check the API terminal for database errors. Increase
`OLLAMA_TIMEOUT_SECONDS` if your Mac needs more than the default 30 seconds.
Keep the API bound to loopback; this is a local demo without authentication.

## What the demo demonstrates

The frozen ten-pair manually approved benchmark yielded semantic Recall@5
10/10 and MRR 0.875. These are small-sample retrieval results, not general
duplicate-detection accuracy. Semantic retrieval remains the default.
For concrete matches, the interface displays verbatim report/candidate excerpts
validated against their source texts. Weak matches say there is insufficient
evidence of the same underlying issue. The model still chooses the excerpts
and missing details; those choices can be imperfect and require human review.
The explanation display additionally requires two shared non-generic words
in the selected excerpts. This conservative English-language check can abstain
on valid paraphrases; it does not alter retrieval order or similarity scores.

## Architecture

- `app/github.py` calls GitHub's REST API, follows issue pages, reports API/rate-limit failures, and removes pull requests returned by the issues endpoint.
- `app/importer.py` maps GitHub data and performs idempotent inserts/updates using the stable GitHub issue ID.
- `app/models.py` stores repositories separately from issues so every row retains its source repository, source ID/number, and GitHub URL.
- `app/main.py` provides health, list, and detail endpoints.
- `app/cli.py` provides the repeatable import command.
- `app/embedding.py` builds and hashes the exact issue text, loads the local model, and embeds changed issues in batches.
- `app/search.py` provides exact cosine-distance search, PostgreSQL full-text search, and reciprocal-rank-fusion hybrid search within one repository.
- `app/triage.py` calls local Ollama, validates its structured response, and treats all issue text as untrusted prompt data.
- `frontend/` contains the responsive UI; its build writes ignored assets to `app/static/`.
- `app/evaluation.py` validates manual relevance judgments and computes Recall@5 and MRR.
- `alembic/` owns the PostgreSQL schema history.

The importer stores label names as JSON because labels are part of the imported issue snapshot and Phase 0 does not need label-level querying or synchronization. Both the GitHub timestamps and a local import timestamp are retained.

## Dependencies

- **FastAPI**: typed HTTP API and automatic OpenAPI documentation.
- **SQLAlchemy**: database models, queries, transactions, and testable session boundaries.
- **Alembic**: repeatable, versioned schema migrations.
- **psycopg**: PostgreSQL driver; the binary extra makes local setup predictable without a compiler toolchain.
- **HTTPX**: GitHub and Ollama HTTP client with timeouts and mock transports for fully offline tests.
- **pgvector**: SQLAlchemy vector type and exact cosine-distance operators.
- **sentence-transformers**: runs `all-MiniLM-L6-v2` locally; no OpenAI API key is used.
- **Uvicorn**: local ASGI server for FastAPI.
- **pytest**: test runner. Tests use in-memory SQLite for speed and require no PostgreSQL or network connection.

Python 3.11 or newer and Docker with Docker Compose are required.

## Detailed one-time setup and data maintenance

Create a virtual environment, install the application and development dependencies, and create local environment configuration:

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -e '.[dev]'
test -f .env || cp .env.example .env
set -a
source .env
set +a
```

The application reads `DATABASE_URL` and optional `GITHUB_TOKEN` directly from the environment. Sourcing `.env` is therefore intentional; no dotenv runtime dependency is needed.

### Local Ollama setup on macOS

Install Ollama with Homebrew, start it as a background service, and download the
default local model:

```bash
brew install ollama
brew services start ollama
ollama pull qwen3:4b
curl http://localhost:11434/api/tags
```

To run Ollama in the foreground instead of as a Homebrew service, use
`ollama serve` in a separate terminal. `OLLAMA_MODEL` defaults to `qwen3:4b`;
`OLLAMA_BASE_URL` defaults to `http://localhost:11434`, and
`OLLAMA_TIMEOUT_SECONDS` defaults to `30`. Override them in `.env` if needed,
then source the file again before starting the API.

Start PostgreSQL and wait for its health check. The Compose service uses the
PostgreSQL 16 pgvector image while retaining the existing named volume. IssueLens maps host port `5433`
to PostgreSQL's port `5432` inside the container, avoiding services that already
use the default host port:

```bash
docker compose up -d postgres
docker compose ps
```

When upgrading an existing Phase 0 checkout, pull and recreate only the
PostgreSQL container. This preserves `issuelens_postgres_data`:

```bash
docker compose pull postgres
docker compose up -d --force-recreate --wait postgres
```

Run all migrations:

```bash
alembic upgrade head
```

Migration `0002` enables the PostgreSQL `vector` extension and adds nullable
384-dimensional embedding columns; it does not rewrite or delete imported issues.

Import a small public sample (a token is optional for a small import):

```bash
python -m app.cli import-issues pallets/flask --max-issues 10
```

The defaults preserve the original Phase 0 behavior: all issue states, sorted by
creation time from oldest to newest. To prepare a more useful Phase 1 dataset,
import up to 500 recent open and closed issues, newest first:

```bash
python -m app.cli import-issues pallets/flask --max-issues 500 \
  --state all --sort created --direction desc
```

GitHub's unauthenticated REST API limit is low. To use a token, set `GITHUB_TOKEN` in `.env`, source the file again, and rerun the same command. Repeating an import updates existing rows instead of duplicating them. `--max-issues` counts actual issues after pull requests are excluded.

Embed all imported Flask issues in batches:

```bash
python -m app.cli embed-issues pallets/flask --batch-size 32
```

The first run downloads the model from Hugging Face and therefore may require
internet access. Later runs skip rows whose exact `title + "\n\n" + body`
text hash and model identifier are unchanged. Empty bodies are embedded as an
empty string after the two newlines. Changed issue text is recomputed.

For API-only development, an alternative port is 8000 (the normal demo above
uses 8001). Start it with:

```bash
uvicorn app.main:app --reload
```

The interactive API documentation is at <http://localhost:8000/docs>. Example requests:

```bash
curl http://localhost:8000/health
curl 'http://localhost:8000/issues?limit=10&offset=0'
curl 'http://localhost:8000/issues?repository=pallets/flask&limit=10'
curl http://localhost:8000/issues/1
curl -X POST http://localhost:8000/similar-issues \
  -H 'Content-Type: application/json' \
  -d '{"repository":"pallets/flask","title":"Development server fails to reload","body":"Reloading stops after a syntax error","method":"hybrid","limit":5}'
curl 'http://localhost:8000/issues/1/similar?method=hybrid&limit=5'
curl -X POST http://localhost:8000/triage \
  -H 'Content-Type: application/json' \
  -d '{"repository":"pallets/flask","title":"Development server fails to reload","body":"Reloading stops after a syntax error."}'
```

`method` may be `semantic`, `keyword`, or `hybrid`; it defaults to `semantic`
for comparison with the original Phase 1 behavior. Keyword-only requests do not
load or run the embedding model.

Compare all three rankings side by side for the same query:

```bash
python -m app.cli compare-search pallets/flask \
  --title 'Development server fails to reload' \
  --body 'Reloading stops after a syntax error' \
  --limit 5
```

### Manual relevance review

`reviews/` and `evaluations/` contain local generated exports and are ignored
by Git. The evidence-backed benchmark under `benchmarks/` is versioned.

Export a review sheet for 20 stored Flask issues:

```bash
python -m app.cli export-review pallets/flask \
  --output reviews/flask-relevance-review.csv \
  --query-count 20 \
  --candidates-per-method 5
```

Eligible queries have nonempty titles and bodies plus current embeddings. The
selector divides them into 20 chronological slices and picks a title with the
most not-yet-represented topic words from each slice. For every query it runs
semantic, keyword, and hybrid retrieval with self-exclusion, then writes one
CSV row per deduplicated candidate. Separate rank columns show where each
method returned that candidate.

Review the CSV and fill every `judgment` cell with exactly one of:

- `same underlying problem`
- `related but different`
- `unrelated`

IssueLens never fills this column automatically. After completing the sheet,
convert only `same underlying problem` judgments into verified relevance pairs:

```bash
python -m app.cli convert-review \
  reviews/flask-relevance-review.csv \
  evaluations/flask-verified.json
```

If the intended evaluation definition should also count related-but-different
candidates, make that choice explicit:

```bash
python -m app.cli convert-review \
  reviews/flask-relevance-review.csv \
  evaluations/flask-related-verified.json \
  --include-related
```

Conversion rejects blank or unknown judgments. It also rejects any query with
no candidate included under the chosen relevance definition. Because this
sheet contains only candidates proposed by IssueLens itself, converted files
are marked `evaluation_eligible: false`; `evaluate-search` refuses to report
Recall/MRR from them. Keep the sheet for qualitative error analysis, not an
unbiased retrieval benchmark.

### Evidence-backed duplicate benchmark

[benchmarks/flask-duplicate-candidates.json](benchmarks/flask-duplicate-candidates.json)
contains independently discovered candidate pairs. Each entry includes a
source issue URL, configured target URL, direct evidence link, and manual
`approved` status. The verbatim audit in
[benchmarks/evidence-review.md](benchmarks/evidence-review.md) records which
comments clearly establish the configured pair, which use qualified language,
and which actually reference another repository.

Open all three URLs for each pair. Set `approved` to `true` only when the linked
GitHub evidence clearly establishes that exact source-to-target duplicate
relationship. Do not approve based on similar titles or IssueLens rankings.

Import and embed every issue referenced by the candidate file:

```bash
python -m app.cli prepare-benchmark \
  benchmarks/flask-duplicate-candidates.json \
  --batch-size 32
```

This targeted import is idempotent. It may require `GITHUB_TOKEN` if GitHub's
unauthenticated API limit is exhausted, and the local model may need its first
download. Preparation does not approve any pair.

After manually approving pairs, run the benchmark:

```bash
python -m app.cli evaluate-benchmark \
  benchmarks/flask-duplicate-candidates.json
```

For each approved pair, the later source issue is the query and the explicit
canonical issue is the one relevant target. Every retrieval method is limited
to issues created strictly before the query and excludes the query itself. A
target below rank five contributes zero to Recall@5; a target absent from the
full ranking contributes zero to both Recall@5 and MRR. The command prints the
approved pair count and separate semantic, keyword, and hybrid metrics. If no
pairs are approved, it refuses to report metrics.

### Retrieval evaluation

Evaluation files are JSON with manually verified GitHub issue numbers:

```json
{
  "version": 1,
  "illustrative_only": false,
  "judgments_verified": true,
  "queries": [
    {
      "id": "reload-1",
      "repository": "pallets/flask",
      "title": "A real query title",
      "body": "Optional real query details",
      "relevant_issue_numbers": [123, 456]
    }
  ]
}
```

Only put issue numbers in `relevant_issue_numbers` after manually verifying
that they are relevant candidates, then explicitly set `judgments_verified` to
`true`. The evaluator also verifies that every referenced issue number exists
in its selected imported repository. [evaluation.example.json](evaluation.example.json)
is a format illustration, not ground truth; it has `illustrative_only: true`
and `judgments_verified: false`, and the evaluator deliberately refuses to
score it.

Run an evaluation file containing verified judgments:

```bash
python -m app.cli evaluate-search evaluation.verified.json
```

For each retrieval method this prints mean Recall@5 and MRR. Recall@5 measures
the fraction of each query's verified relevant issues found in the first five,
then averages over queries. MRR uses the reciprocal rank of the first verified
relevant issue in the full repository ranking. The illustrative file carries
no claimed metrics because it is not manually verified. The separate
evidence-backed benchmark reports only its small reviewed-pair result and is
not a general accuracy claim.

Run all tests (no GitHub access and no running PostgreSQL required):

```bash
pytest
```

Inspect imported records directly in PostgreSQL:

```bash
docker compose exec postgres psql -U issuelens -d issuelens \
  -c 'SELECT r.full_name, i.number, i.title, i.state, i.imported_at FROM issues i JOIN repositories r ON r.id = i.repository_id ORDER BY i.id LIMIT 20;'
```

Stop PostgreSQL while preserving its data:

```bash
docker compose down
```

Do not use `docker compose down -v` if you want to retain the imported dataset.

## API

- `GET /health` returns `{"status":"ok"}`. It is a process liveness endpoint and does not query PostgreSQL.
- `GET /issues?limit=50&offset=0&repository=owner/repo` lists issues in database-ID order. `repository` is optional; `limit` is 1–100.
- `GET /issues/{id}` fetches one issue by its IssueLens database ID and returns `404` when absent.
- `POST /similar-issues` runs the selected retrieval method for supplied title/body text and returns up to five candidates from one repository in score order.
- `GET /issues/{id}/similar?method=hybrid&limit=5` uses a stored issue as the query and excludes that issue from every component ranking.
- `POST /triage` retrieves up to three semantic candidates, asks local Ollama for missing bug-report details and evidence for each candidate, then returns validated JSON. It never writes to GitHub.

`POST /triage` accepts titles up to 300 characters and bodies up to 8,000
characters. Only the first 300 title characters and 2,000 body characters from
each retrieved candidate are included in the model prompt. Candidate IDs,
numbers, titles, URLs, and similarity scores in the response come from the
database, not Ollama. Free-form model explanation fields are rejected. For a
specific overlap, Ollama selects short source excerpts from constrained choices
for each issue; the API validates their attribution before rendering them.
When the texts support only a broad topical similarity, the
API explanation is `insufficient evidence of the same underlying issue`.
For specific matches, the API constructs the displayed explanation from the
validated verbatim excerpts instead of returning the model's free-form prose.
This prevents the explanation from introducing a new mechanism or fix.
The checklist selects at most three neutral requests from a fixed set covering
versions, reproduction, behavior, platform, and traces. An unreachable or
non-successful Ollama response returns `503`, a timeout returns `504`, and
invalid structured output returns `502`; IssueLens does not fabricate a
fallback response.

Phase 1 retrieval remains unchanged. Semantic retrieval is used for triage
because it found all ten manually approved Flask targets in the benchmark's
top five, with MRR 0.875. That small benchmark result motivates this demo
default; it is not a general duplicate-detection accuracy claim.

Semantic search uses exact cosine distance over the current model's stored
vectors. Keyword search extracts up to 64 unique words, joins them with
web-search `OR`, and passes the whole expression as a bound parameter to
PostgreSQL `websearch_to_tsquery`. It ranks overlap with `ts_rank_cd`; title
lexemes have weight `A` and body lexemes weight `B`, so more matching terms and
title matches rank higher. At this dataset size it uses an exact scan and does
not add another index. Hybrid search retrieves up to 50 candidates per
component and applies reciprocal rank fusion with `k=60`: for each result it
sums `1 / (60 + rank)` from the semantic and keyword rankings. Results are
sorted by that fused score with deterministic tie-breaking. No approximate
vector index is created. Retrieval scores rank candidates; they are not
duplicate probabilities or verdicts.

To run the optional regression check against the configured live PostgreSQL
database:

```bash
set -a
source .env
set +a
ISSUELENS_RUN_DB_TESTS=1 pytest tests/test_keyword_postgres.py
```

The default test suite skips this check so ordinary tests remain offline.

## Import behavior and failures

The client accepts `--state open|closed|all`, `--sort created|updated|comments`,
and `--direction asc|desc`, and requests up to 100 records at a time. The first
request has no numeric `page` parameter; subsequent requests follow GitHub's
`rel="next"` Link URL, including its cursor, exactly as returned. GitHub's
`/issues` endpoint also returns pull requests, so records containing
`pull_request` are ignored and cursor pages are followed until the requested
number of actual issues is reached or GitHub returns no next link.

An import runs in one database transaction. A network/API/database failure leaves partial changes uncommitted. HTTP errors include GitHub's status and message; exhausted rate limits include the reset timestamp and recommend `GITHUB_TOKEN`.
