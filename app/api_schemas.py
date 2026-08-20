from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class ChatRequest(BaseModel):
    text: str
    uiContext: dict[str, Any] | None = None
    subtitleMode: str | None = None
    selections: list[dict[str, Any]] | None = None
    orderMode: str | None = None
    searchScopeKind: str | None = None
    searchScopeStart: float | None = None
    searchScopeEnd: float | None = None
    searchResultLimit: int | None = None
    searchBoundaryMode: str | None = None
    contentAutoGenerate: bool | None = None
    contentExclusions: list[str] | None = None
    evidenceMode: str | None = None
    allowedCapabilities: list[str] | None = None


class ContentSearchConfirmRequest(BaseModel):
    searchId: str
    matchIds: list[str]
    outputMode: str = "single_reel"
    orderMode: str = "source"
    subtitleMode: str = "none"
    subtitleStyle: str = "clean"
    subtitleDraftId: str | None = None
    orderReason: str = ""
    acknowledgeIncomplete: bool = False


class ContentSelectionBasketRequest(BaseModel):
    items: list[dict[str, str]] = Field(default_factory=list, max_length=200)
    revision: int | None = None


class ContentSelectionBasketConfirmRequest(BaseModel):
    outputMode: str = "single_reel"
    orderMode: str = "source"
    subtitleMode: str = "none"
    subtitleStyle: str = "clean"
    subtitleDraftId: str | None = None
    acknowledgeIncomplete: bool = False
    acknowledgeOverlap: bool = False


class ContentSearchOrderRequest(BaseModel):
    searchId: str
    matchIds: list[str]


class ContentSearchReviewDraftRequest(BaseModel):
    searchId: str
    selectedMatchIds: list[str] = Field(default_factory=list, max_length=200)
    orderedMatchIds: list[str] = Field(default_factory=list, max_length=200)
    outputMode: str = "single_reel"
    orderMode: str = "source"
    subtitleEnabled: bool = False
    subtitleStyle: str = "clean"


class ContentSearchDialogueModeRequest(BaseModel):
    searchId: str
    dialogueMode: str


class ContentSearchFeedbackRequest(BaseModel):
    searchId: str | None = None
    matchId: str | None = None
    verdict: str
    note: str = ""
    evidenceIds: list[str] | None = None


class ContentSearchBoundaryRequest(BaseModel):
    searchId: str
    matchId: str
    operation: str = "save"
    start: float | None = None
    end: float | None = None


class ContentSearchBulkKeepRequest(BaseModel):
    searchId: str
    matchIds: list[str] = Field(default_factory=list, max_length=200)


class PersonLabelRequest(BaseModel):
    label: str = Field(min_length=1, max_length=48)


class PersonTargetRequest(BaseModel):
    # ``personId`` remains accepted for persisted clients.  New clients send a
    # set plus an explicit boolean mode.
    personId: str | None = Field(default=None, min_length=1, max_length=64)
    personIds: list[str] | None = Field(default=None, min_length=1, max_length=12)
    matchMode: str = Field(default="any", min_length=3, max_length=8)


class PersonSpeakerRequest(BaseModel):
    personId: str = Field(min_length=1, max_length=64)
    speakerRef: str = Field(min_length=1, max_length=64)


class BriefConfirmRequest(BaseModel):
    brief: dict[str, Any] | None = None
    confirmed: bool = True


class AnalysisDecisionRequest(BaseModel):
    action: str


class AdjustOutputRequest(BaseModel):
    start: float | None = None
    end: float | None = None
    startDelta: float = 0.0
    endDelta: float = 0.0


class KeepOutputRequest(BaseModel):
    kept: bool = True


class FinalizeOneOffJobRequest(BaseModel):
    filenames: list[str] = Field(min_length=1, max_length=16)


class DeleteJobRequest(BaseModel):
    revision: int = Field(ge=0)
    deleteIntent: str = Field(min_length=16, max_length=256)


class DeriveJobRequest(BaseModel):
    count: int | None = None
    targetSeconds: float | None = None
    theme: str | None = None
    excludeExisting: bool = True
    message: str = "根据当前结果继续生成"


class ConfirmCandidatesRequest(BaseModel):
    indices: list[int] | None = None
    groupIds: list[str] | None = None
    segmentIds: dict[str, list[str]] | None = None
    autoVariants: int | None = None
    outputMode: str = "single_reel"
    subtitleMode: str = "none"
    subtitleStyle: str = "clean"
    subtitleDraftId: str | None = None
    orderMode: str = "source"
    techniquePolicy: dict[str, Any] | None = None
    acceptOvertime: bool = False


class AutoPlanRequest(BaseModel):
    scope: str = "selected_only"
    groupIds: list[str] | None = None
    segmentIds: dict[str, list[str]] | None = None
    targetSeconds: float | None = None
    structure: str = "auto"
    variantCount: int = 3
    techniquePolicy: dict[str, Any] | None = None


class LlmOrderRequest(BaseModel):
    groupIds: list[str] = Field(default_factory=list)
    segmentIds: dict[str, list[str]] | None = None


class RenderAutoPlanRequest(BaseModel):
    planId: str
    subtitleMode: str = "none"
    subtitleStyle: str = "clean"
    subtitleDraftId: str | None = None


class FinalizeOutputVersionRequest(BaseModel):
    subtitleMode: str = "none"
    subtitleStyle: str = "clean"
    subtitleDraftId: str | None = None


class SubtitleDraftCreateRequest(BaseModel):
    outputs: list[dict[str, Any]] = Field(default_factory=list)
    subtitleStyle: str = "clean"


class SubtitleDraftUpdateRequest(BaseModel):
    revision: int
    cues: list[dict[str, Any]] = Field(default_factory=list)
    globalStyle: dict[str, Any] = Field(default_factory=dict)
    cueStyleOverrides: dict[str, dict[str, Any]] = Field(default_factory=dict)
    confirmed: bool = False
    sourceSubtitleAcknowledged: bool | None = None


class SubtitleSuggestionsRequest(BaseModel):
    cueIds: list[str] | None = None


class SubtitleStyleCommandRequest(BaseModel):
    text: str
    cueId: str | None = None


class UpdateSegmentTechniqueRequest(BaseModel):
    playbackRate: float | None = None
    speedLocked: bool | None = None
    transitionType: str | None = None
    transitionDuration: float | None = None
    transitionLocked: bool | None = None
    audioBridgeType: str | None = None
    audioBridgeDuration: float | None = None
    audioBridgeLocked: bool | None = None


class TechniquePlanRequest(BaseModel):
    groupIds: list[str] = Field(default_factory=list)
    segmentIds: dict[str, list[str]] | None = None
    targetSeconds: float | None = None
    orderMode: str = "selection"
    techniquePolicy: dict[str, Any] | None = None
    manualSelection: bool = True


class AdjustCandidateRequest(BaseModel):
    start: float
    end: float


class ReviewExclusionsRequest(BaseModel):
    indices: list[int] = Field(default_factory=list)


class TimelineSelectionRequest(BaseModel):
    start: float
    end: float


class AdjustEventSegmentRequest(BaseModel):
    start: float
    end: float


class ReorderEventSegmentsRequest(BaseModel):
    segmentIds: list[str]


class AddEventSegmentRequest(BaseModel):
    start: float
    end: float
    role: str = "用户补充镜头"


class RenameEventGroupRequest(BaseModel):
    title: str


class MoveEventSegmentRequest(BaseModel):
    destinationGroupId: str
    targetIndex: int | None = None


class CreateEventGroupRequest(BaseModel):
    start: float
    end: float
    title: str = "手动事件高光"


class CreateEventFromCandidatesRequest(BaseModel):
    indices: list[int]
    title: str = "重新编排高光"
