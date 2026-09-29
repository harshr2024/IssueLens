"""Add pgvector issue embeddings.

Revision ID: 0002
Revises: 0001
"""
from alembic import op
import sqlalchemy as sa
from pgvector.sqlalchemy import Vector


revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")
    op.add_column("issues", sa.Column("embedding", Vector(384), nullable=True))
    op.add_column(
        "issues", sa.Column("embedding_model", sa.String(length=255), nullable=True)
    )
    op.add_column(
        "issues", sa.Column("embedding_text_hash", sa.String(length=64), nullable=True)
    )
    op.add_column(
        "issues", sa.Column("embedded_at", sa.DateTime(timezone=True), nullable=True)
    )


def downgrade() -> None:
    op.drop_column("issues", "embedded_at")
    op.drop_column("issues", "embedding_text_hash")
    op.drop_column("issues", "embedding_model")
    op.drop_column("issues", "embedding")
