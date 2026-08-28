from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any


ALGORITHM_V1 = "editing-algorithm-v1"
ALGORITHM_V2 = "editing-algorithm-v2"
ALGORITHM_STAGES = (
    "route", "index", "recall", "verify", "boundary", "select", "quality", "edit",
)
COVERAGE_STATUSES = frozenset({"complete", "partial", "sampled", "unknown"})


def algorithm_version(job: dict[str, Any] | None) -> str:
    """Return the durable algorithm snapshot for a task.

    Missing values intentionally mean v1.  This is what prevents an old task
    from changing behaviour merely because the service was upgraded.
    """
    value = str((job or {}).get("algorithmVersion") or "").strip()
    return value if value in {ALGORITHM_V1, ALGORITHM_V2} else ALGORITHM_V1


def uses_algorithm_v2(job: dict[str, Any] | None) -> bool:
    return algorithm_version(job) == ALGORITHM_V2


def _confidence(value: Any, fallback: float = 0.0) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        number = fallback
    if not math.isfinite(number):
        number = fallback
    return round(min(1.0, max(0.0, number)), 4)


def candidate_quality(
    *,
    retrieval_confidence: Any,
    evidence_confidence: Any,
    boundary_confidence: Any,
    coverage_status: str = "unknown",
    review_reasons: list[str] | None = None,
) -> dict[str, Any]:
    coverage = str(coverage_status or "unknown").lower()
    if coverage not in COVERAGE_STATUSES:
        coverage = "unknown"
    retrieval = _confidence(retrieval_confidence)
    evidence = _confidence(evidence_confidence, retrieval)
    boundary = _confidence(boundary_confidence, min(retrieval, evidence))
    reasons = list(dict.fromkeys(str(value).strip() for value in review_reasons or [] if str(value).strip()))
    if coverage != "complete" and "coverage_incomplete" not in reasons:
        reasons.append("coverage_incomplete")
    if evidence < .62 and "weak_evidence" not in reasons:
        reasons.append("weak_evidence")
    if boundary < .65 and "uncertain_boundary" not in reasons:
        reasons.append("uncertain_boundary")
    return {
        "retrievalConfidence": retrieval,
        "evidenceConfidence": evidence,
        "boundaryConfidence": boundary,
        "coverageStatus": coverage,
        "reviewReasons": reasons,
    }


def attach_candidate_quality(
    candidate: dict[str, Any],
    *,
    coverage_status: str = "unknown",
    review_reasons: list[str] | None = None,
) -> dict[str, Any]:
    """Attach the v2 quality contract while preserving legacy UI fields."""
    retrieval = candidate.get("retrievalConfidence", candidate.get("retrievalScore", candidate.get("score", 0)))
    try:
        if float(retrieval) > 1:
            retrieval = float(retrieval) / 100
    except (TypeError, ValueError):
        retrieval = 0
    quality = candidate_quality(
        retrieval_confidence=retrieval,
        evidence_confidence=candidate.get("evidenceConfidence", candidate.get("confidence", retrieval)),
        boundary_confidence=candidate.get("boundaryConfidence", candidate.get("confidence", retrieval)),
        coverage_status=coverage_status,
        review_reasons=[*(review_reasons or []), *(candidate.get("reviewReasons") or [])],
    )
    candidate["quality"] = quality
    candidate["retrievalConfidence"] = quality["retrievalConfidence"]
    candidate["evidenceConfidence"] = quality["evidenceConfidence"]
    candidate["boundaryConfidence"] = quality["boundaryConfidence"]
    candidate["requiresReview"] = bool(quality["reviewReasons"])
    # Low-confidence recall stays visible, but never becomes an implicit edit.
    if quality["evidenceConfidence"] < .62 or quality["boundaryConfidence"] < .65:
        candidate["selected"] = False
    candidate["confidence"] = round(min(
        quality["retrievalConfidence"], quality["evidenceConfidence"], quality["boundaryConfidence"],
    ), 3)
    return candidate


@dataclass
class CostController:
    """Task-local accounting with a hard, explainable quality-first ceiling."""

    baseline_frames: int = 0
    baseline_vlm_calls: int = 0
    baseline_llm_calls: int = 0
    latency_multiplier: float = 2.0
    frames: int = 0
    vlm_calls: int = 0
    llm_calls: int = 0
    local_seconds: float = 0.0
    degradations: list[str] = field(default_factory=list)

    def frame_limit(self) -> int:
        return max(self.baseline_frames, int(math.ceil(self.baseline_frames * self.latency_multiplier)))

    def provider_limit(self, kind: str) -> int:
        baseline = self.baseline_vlm_calls if kind == "vlm" else self.baseline_llm_calls
        return max(baseline, int(math.ceil(baseline * self.latency_multiplier)))

    def consume(self, kind: str, amount: int = 1) -> bool:
        value = max(0, int(amount))
        if kind == "frames":
            if self.frames + value > self.frame_limit():
                self.degradations.append("frame_budget_exhausted")
                return False
            self.frames += value
            return True
        if kind == "vlm":
            if self.vlm_calls + value > self.provider_limit("vlm"):
                self.degradations.append("vlm_budget_exhausted")
                return False
            self.vlm_calls += value
            return True
        if kind == "llm":
            if self.llm_calls + value > self.provider_limit("llm"):
                self.degradations.append("llm_budget_exhausted")
                return False
            self.llm_calls += value
            return True
        raise ValueError(f"未知成本类型: {kind}")

    def snapshot(self) -> dict[str, Any]:
        return {
            "version": "quality-first-2x-v1",
            "latencyMultiplier": self.latency_multiplier,
            "framesUsed": self.frames,
            "frameLimit": self.frame_limit(),
            "vlmUsed": self.vlm_calls,
            "vlmLimit": self.provider_limit("vlm"),
            "llmUsed": self.llm_calls,
            "llmLimit": self.provider_limit("llm"),
            "localSeconds": round(max(0.0, self.local_seconds), 3),
            "degradations": list(dict.fromkeys(self.degradations)),
        }
