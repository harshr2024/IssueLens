# Local verification — 2026-09-28

Executed against the existing PostgreSQL 16/pgvector database and local Ollama
`qwen3:4b`. API and built frontend served together at `http://127.0.0.1:8001`.

## Automated checks

- `ISSUELENS_RUN_DB_TESTS=1 .venv/bin/pytest`: **43 passed**, no skips;
  one existing Starlette/httpx deprecation warning.
- `npm --prefix frontend test`: **3 passed**.
- `npm --prefix frontend run build`: passed.
- `docker compose up -d --wait postgres`: existing container healthy.
- `.venv/bin/alembic upgrade head`: succeeded; schema already current.
- Embedding command: **0 embedded; 529 unchanged and skipped**.
- Frozen benchmark: 10 approved pairs; semantic Recall@5 **1.0000**,
  MRR **0.8750**. Keyword remained 0.4000 / 0.2023; hybrid 1.0000 / 0.5033.
  No pairs, approvals, retrieval methods, or retrieval parameters changed.

## Live browser submissions

Both requests were submitted through the actual web form, with live PostgreSQL,
MiniLM embedding, and Ollama generation. Loading and disabled-submit states were
observed, followed by rendered results. The backend logged HTTP 200 responses.

1. **Blueprint renders a template from the wrong folder** with the description
   in the README. Returned #5901 (0.781), #3747 (0.738), #5035 (0.650).
   The first two displayed source excerpts about rendering templates from the
   other blueprint. The third displayed insufficient evidence. The final model
   selected the conditional error/traceback checklist item.
2. **Development server fails to reload** / **Reloading stops after a syntax
   error**. Returned #5249 (0.407), #4715 (0.397), #5598 (0.393).
   All three displayed **insufficient evidence of the same underlying issue**.
   No SO_REUSEADDR or eager-loading causes or fixes were generated in the
   displayed explanations. The final checklist requested expected behavior.

The checklist remains model-selected: its requests can be less useful than a
human's, especially when intent is implicit. It is restricted to neutral
requests so it cannot invent application configuration or architecture.

## Failures found and corrected

Early live runs changed capitalization in quotes, attributed one candidate's
quote to another, and generated unnecessary causal prose. The API rejected
those outputs and the UI displayed errors. The final schema binds exact excerpt
choices to each candidate ID and grounding branch; no free-form explanation
field is accepted. Displayed comparisons are assembled from validated excerpts.
A conservative content-word check prevents a generic shared word such as
“server” from qualifying as specific evidence. This check can abstain on valid
paraphrases and is not a correctness proof or a retrieval score threshold.

## Repository review

At the time of this verification, the checkout had no commits: project sources
were untracked, so `git diff` could not show a baseline comparison. Reviewed the changed sources and
untracked file inventory, ran `git diff --check`, checked ignore rules, and
scanned non-ignored files for common credential/private-key patterns with no
matches. `.env`, virtualenv/caches, `.DS_Store`, and generated `app/static/`
assets are ignored. Local review/evaluation exports are now also ignored. The
review CSV and all 15 benchmark entries remain present,
with exactly ten approved entries. No database volume was removed.

Screenshot of the inspected local interface: [demo.png](demo.png).
