from __future__ import annotations

import hashlib
import math
from dataclasses import dataclass
from datetime import datetime, timezone
from functools import lru_cache
from typing import Protocol, Sequence

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Issue, Repository


MODEL_IDENTIFIER = "sentence-transformers/all-MiniLM-L6-v2"
EMBEDDING_DIMENSIONS = 384


class EmbeddingError(RuntimeError):
    """A clear failure while loading or running the local embedding model."""


class RepositoryNotFoundError(RuntimeError):
    pass


class Embedder(Protocol):
    model_name: str

    def encode(self, texts: Sequence[str], *, batch_size: int) -> list[list[float]]:
        ...


class SentenceTransformerEmbedder:
    model_name = MODEL_IDENTIFIER

    def __init__(self) -> None:
        try:
            from sentence_transformers import SentenceTransformer

            self._model = SentenceTransformer(self.model_name)
        except Exception as exc:
            raise EmbeddingError(
                f"Could not load local embedding model {self.model_name}: {exc}"
            ) from exc

        if hasattr(self._model, "get_embedding_dimension"):
            dimensions = self._model.get_embedding_dimension()
        else:
            dimensions = self._model.get_sentence_embedding_dimension()
        if dimensions != EMBEDDING_DIMENSIONS:
            raise EmbeddingError(
                f"Model {self.model_name} returned dimension {dimensions}; "
                f"expected {EMBEDDING_DIMENSIONS}"
            )

    def encode(self, texts: Sequence[str], *, batch_size: int) -> list[list[float]]:
        try:
            vectors = self._model.encode(
                list(texts),
                batch_size=batch_size,
                convert_to_numpy=True,
                normalize_embeddings=True,
                show_progress_bar=False,
            )
        except Exception as exc:
            raise EmbeddingError(
                f"Model {self.model_name} failed while embedding text: {exc}"
            ) from exc
        return vectors.tolist()


@lru_cache(maxsize=1)
def get_embedder() -> SentenceTransformerEmbedder:
    return SentenceTransformerEmbedder()


def embedding_text(title: str, body: str | None) -> str:
    return f"{title}\n\n{body or ''}"


def embedding_text_hash(title: str, body: str | None) -> str:
    return hashlib.sha256(embedding_text(title, body).encode("utf-8")).hexdigest()


def encode_text(embedder: Embedder, title: str, body: str | None) -> list[float]:
    try:
        vectors = embedder.encode([embedding_text(title, body)], batch_size=1)
    except EmbeddingError:
        raise
    except Exception as exc:
        raise EmbeddingError(
            f"Model {embedder.model_name} failed while embedding text: {exc}"
        ) from exc
    return _validated_vectors(vectors, expected_count=1)[0]


@dataclass(frozen=True)
class EmbeddingResult:
    embedded: int
    skipped: int


def embed_imported_issues(
    session: Session,
    embedder: Embedder,
    repository_full_name: str,
    *,
    batch_size: int = 32,
) -> EmbeddingResult:
    if batch_size < 1:
        raise ValueError("batch_size must be at least 1")

    repository = session.scalar(
        select(Repository).where(Repository.full_name == repository_full_name)
    )
    if repository is None:
        raise RepositoryNotFoundError(
            f"Repository {repository_full_name!r} has not been imported"
        )

    embedded = 0
    skipped = 0
    last_id = 0
    while True:
        issues = list(
            session.scalars(
                select(Issue)
                .where(Issue.repository_id == repository.id, Issue.id > last_id)
                .order_by(Issue.id)
                .limit(batch_size)
            )
        )
        if not issues:
            break
        last_id = issues[-1].id

        pending: list[tuple[Issue, str]] = []
        for issue in issues:
            text_hash = embedding_text_hash(issue.title, issue.body)
            if (
                issue.embedding is not None
                and issue.embedding_model == embedder.model_name
                and issue.embedding_text_hash == text_hash
            ):
                skipped += 1
            else:
                pending.append((issue, text_hash))

        if not pending:
            continue

        texts = [embedding_text(issue.title, issue.body) for issue, _ in pending]
        try:
            vectors = embedder.encode(texts, batch_size=batch_size)
            vectors = _validated_vectors(vectors, expected_count=len(pending))
        except EmbeddingError:
            session.rollback()
            raise
        except Exception as exc:
            session.rollback()
            raise EmbeddingError(
                f"Model {embedder.model_name} failed while embedding a batch: {exc}"
            ) from exc

        embedded_at = datetime.now(timezone.utc)
        for (issue, text_hash), vector in zip(pending, vectors, strict=True):
            issue.embedding = vector
            issue.embedding_model = embedder.model_name
            issue.embedding_text_hash = text_hash
            issue.embedded_at = embedded_at
        session.commit()
        embedded += len(pending)

    return EmbeddingResult(embedded=embedded, skipped=skipped)


def _validated_vectors(
    vectors: Sequence[Sequence[float]], *, expected_count: int
) -> list[list[float]]:
    if len(vectors) != expected_count:
        raise EmbeddingError(
            f"Embedding model returned {len(vectors)} vectors for {expected_count} texts"
        )

    validated: list[list[float]] = []
    for vector in vectors:
        values = [float(value) for value in vector]
        if len(values) != EMBEDDING_DIMENSIONS:
            raise EmbeddingError(
                f"Embedding model returned dimension {len(values)}; "
                f"expected {EMBEDDING_DIMENSIONS}"
            )
        if not all(math.isfinite(value) for value in values):
            raise EmbeddingError("Embedding model returned a non-finite value")
        validated.append(values)
    return validated
