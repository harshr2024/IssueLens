"""Optional live PostgreSQL regression check.

Run with: ISSUELENS_RUN_DB_TESTS=1 pytest tests/test_keyword_postgres.py
"""
import os

import pytest
from sqlalchemy.orm import Session

from app.database import engine
from app.search import search_keyword_issues


@pytest.mark.skipif(
    os.getenv("ISSUELENS_RUN_DB_TESTS") != "1",
    reason="set ISSUELENS_RUN_DB_TESTS=1 to query the configured PostgreSQL database",
)
def test_natural_language_keyword_query_returns_flask_candidates() -> None:
    query = (
        "Development server fails to reload\n\n"
        "Reloading stops after a syntax error"
    )
    with Session(engine) as session:
        results = search_keyword_issues(
            session,
            "pallets/flask",
            query,
            limit=5,
        )

    assert results, "multiword natural-language keyword query returned no candidates"
