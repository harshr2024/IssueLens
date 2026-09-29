from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator


class RepositorySummary(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    full_name: str
    html_url: str


class IssueResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    github_id: int
    number: int
    title: str
    body: str | None
    html_url: str
    state: str
    labels: list[str]
    github_created_at: datetime
    github_updated_at: datetime
    imported_at: datetime
    repository: RepositorySummary


class IssueListResponse(BaseModel):
    items: list[IssueResponse]
    total: int
    limit: int
    offset: int


class SimilarIssueQuery(BaseModel):
    title: str
    body: str | None = None
    repository: str
    limit: int = Field(default=5, ge=1, le=5)
    method: Literal["semantic", "keyword", "hybrid"] = "semantic"

    @field_validator("title")
    @classmethod
    def title_must_not_be_blank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("title must not be empty")
        return value

    @field_validator("repository")
    @classmethod
    def repository_must_be_full_name(cls, value: str) -> str:
        if value.count("/") != 1 or not all(value.split("/")):
            raise ValueError("repository must use the owner/repo format")
        return value


class SimilarIssueResponse(BaseModel):
    id: int
    number: int
    title: str
    html_url: str
    similarity_score: float


class TriageRequest(BaseModel):
    repository: str = Field(max_length=511)
    title: str = Field(max_length=300)
    body: str | None = Field(default=None, max_length=8000)

    @field_validator("title")
    @classmethod
    def title_must_not_be_blank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("title must not be empty")
        return value

    @field_validator("repository")
    @classmethod
    def repository_must_be_full_name(cls, value: str) -> str:
        if value.count("/") != 1 or not all(value.split("/")):
            raise ValueError("repository must use the owner/repo format")
        return value


class TriageCandidateResponse(BaseModel):
    id: int
    number: int
    title: str
    html_url: str
    similarity_score: float
    overlap_explanation: str


class TriageResponse(BaseModel):
    repository: str
    model: str
    missing_information: list[str]
    candidates: list[TriageCandidateResponse]
