from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field


class ExtensibleResponse(BaseModel):
    """Compatibility base: document stable fields without dropping old ones."""

    model_config = ConfigDict(extra="allow")


class JobRequestResponse(ExtensibleResponse):
    instruction: str | None = None
    count: int | str = "auto"
    targetSeconds: float | str = "auto"
    totalTargetSeconds: float | str | None = None
    autoVariantCount: int = 3


class OutputItemResponse(ExtensibleResponse):
    filename: str
    duration: float = 0


class OutputVersionResponse(ExtensibleResponse):
    id: str | None = None
    number: int = 1
    outputs: list[OutputItemResponse] = Field(default_factory=list)


class JobDocumentResponse(ExtensibleResponse):
    """Stable workspace fields; domain payloads remain forward compatible."""

    id: str
    schemaVersion: int = 2
    revision: int = 0
    status: str | None = None
    stage: str | None = None
    taskMode: str = "highlight"
    workflowKind: str = "highlight"
    sourceProjectId: str | None = None
    resolvedTaskKind: str = "highlight"
    routingConfidence: float = 1.0
    routingNeedsConfirmation: bool = False
    request: JobRequestResponse = Field(default_factory=JobRequestResponse)
    outputs: list[OutputItemResponse] = Field(default_factory=list)
    outputVersions: list[OutputVersionResponse] = Field(default_factory=list)


class JobSummaryResponse(ExtensibleResponse):
    id: str
    revision: int = 0
    status: str | None = None
    stage: str | None = None
    detail: str | None = None
    filename: str | None = None
    taskMode: str = "highlight"
    workflowKind: str = "highlight"
    sourceProjectId: str | None = None
    resolvedTaskKind: str = "highlight"
    routingConfidence: float = 1.0
    storageMode: str = "editable"
    eventGroupCount: int = 0
    candidateCount: int = 0
    outputCount: int = 0


class JobsResponse(BaseModel):
    jobs: list[JobSummaryResponse] = Field(default_factory=list)


class JobEnvelopeResponse(BaseModel):
    job: JobDocumentResponse
