from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field

ActorType = Literal["human", "agent"]
Namespace = Literal["company", "project"]
PageStatus = Literal["draft", "proposed", "approved"]
BucketId = Literal[
    "glossary",
    "business_rule",
    "org",
    "convention",
    "constraint",
    "progress",
]


class WikiError(Exception):
    def __init__(self, code: str, message: str, http_status: int = 400) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.http_status = http_status

    def as_dict(self) -> dict[str, str]:
        return {"code": self.code, "message": self.message}


class Actor(BaseModel):
    actor: str
    actor_type: ActorType
    project_id: str | None = None
    agent_run_id: str | None = None
    agent_name: str | None = None


class WikiSource(BaseModel):
    source_id: str
    filename: str
    sha256: str
    namespace: str
    project_id: str | None = None
    storage_uri: str
    markdown_extract: str
    page_map: list[dict[str, Any]] = Field(default_factory=list)
    ingested_at: str
    ingested_by: str


class WikiPage(BaseModel):
    page_id: str
    namespace: str
    project_id: str | None = None
    bucket_id: str
    title: str
    abbrev: str | None = None
    expansion: str | None = None
    disambiguation: str | None = None
    status: PageStatus
    version: str
    body: str
    source_ids: list[str] = Field(default_factory=list)
    owner: str
    updated_at: str


class WikiRevision(BaseModel):
    revision_id: str
    page_id: str
    version: str
    status: str
    body_snapshot: str
    diff_ref: str | None = None
    actor: str
    created_at: str


class SearchHit(BaseModel):
    page_id: str
    title: str
    snippet: str
    version: str
    bucket_id: str
    score: float


class SearchQuery(BaseModel):
    query: str = ""
    namespace: str
    project_id: str | None = None
    bucket_id: str | None = None
    status: str | None = None
    limit: int = 5


class ProposePageIn(BaseModel):
    page_id: str | None = None
    namespace: str
    project_id: str | None = None
    bucket_id: str
    title: str | None = None
    abbrev: str | None = None
    expansion: str | None = None
    disambiguation: str | None = None
    body: str
    source_ids: list[str] = Field(default_factory=list)
    owner: str | None = None
    version: str = "1.0.0"
