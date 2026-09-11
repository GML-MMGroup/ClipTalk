from __future__ import annotations

import math
from dataclasses import asdict, dataclass


SEMANTIC_BATCH_SIZE = 16
SEARCH_BUDGET_VERSION = "content-search-budget-v1"


@dataclass(frozen=True)
class ContentSearchBudget:
    """Deterministic cost envelope for every content-search query.

    The result limit controls how many matches may be returned.  The adaptive
    target controls when enough evidence has been found to stop model calls.
    Keeping those values separate prevents a UI default from turning into an
    expensive requirement to discover that many clips.
    """

    tier: str
    result_limit: int
    adaptive_target: int | None
    candidate_limit: int
    semantic_unit_limit: int
    first_wave_units: int
    batch_size: int
    maximum_batches: int
    attempts_per_batch: int
    source_evidence_limit: int
    requested_count_explicit: bool

    def as_dict(self) -> dict[str, int | str | bool | None]:
        return asdict(self)


def _aligned(value: int, batch_size: int = SEMANTIC_BATCH_SIZE) -> int:
    return max(batch_size, int(math.ceil(max(1, value) / batch_size)) * batch_size)


def content_search_budget(
    *,
    scope_seconds: float,
    unit_count: int,
    predicate_count: int,
    requested_count: int | None,
    requested_count_explicit: bool,
    result_mode: str,
) -> ContentSearchBudget:
    duration = max(0.0, float(scope_seconds or 0))
    available = max(0, int(unit_count or 0))
    predicates = max(1, int(predicate_count or 1))
    result_limit = max(1, min(200, int(requested_count or 3)))

    if result_mode == "exhaustive":
        batches = int(math.ceil(available / SEMANTIC_BATCH_SIZE)) if available else 0
        return ContentSearchBudget(
            tier="exhaustive",
            result_limit=result_limit,
            adaptive_target=None,
            candidate_limit=available,
            semantic_unit_limit=available,
            first_wave_units=available,
            batch_size=SEMANTIC_BATCH_SIZE,
            maximum_batches=batches,
            attempts_per_batch=2,
            source_evidence_limit=min(1200, max(160, int(math.ceil(duration)) * 3)),
            requested_count_explicit=requested_count_explicit,
        )

    if duration <= 120:
        # All three batches fit in the default concurrency window, so a short
        # clip never waits for a second 60-second model wave merely because
        # the first two batches did not contain enough reliable matches.
        tier, default_target, base_units, first_wave = "short", 3, 48, 48
    elif duration <= 600:
        tier, default_target, base_units, first_wave = "medium", 5, 80, 48
    elif duration <= 1800:
        tier, default_target, base_units, first_wave = "long", 6, 112, 48
    else:
        tier, default_target, base_units, first_wave = "extended", 8, 160, 64

    adaptive_target = result_limit if requested_count_explicit else min(result_limit, default_target)
    complexity_units = min(32, max(0, predicates - 1) * SEMANTIC_BATCH_SIZE)
    explicit_units = adaptive_target * 4 if requested_count_explicit else 0
    semantic_limit = min(200, _aligned(max(base_units + complexity_units, explicit_units)))
    semantic_limit = min(available, semantic_limit)
    candidate_limit = semantic_limit
    first_wave_units = min(semantic_limit, _aligned(max(first_wave, adaptive_target * 4)))
    source_limit = min(640, max(96, int(math.ceil(duration)) * 3))
    return ContentSearchBudget(
        tier=tier,
        result_limit=result_limit,
        adaptive_target=adaptive_target,
        candidate_limit=candidate_limit,
        semantic_unit_limit=semantic_limit,
        first_wave_units=first_wave_units,
        batch_size=SEMANTIC_BATCH_SIZE,
        maximum_batches=int(math.ceil(semantic_limit / SEMANTIC_BATCH_SIZE)) if semantic_limit else 0,
        attempts_per_batch=1,
        source_evidence_limit=source_limit,
        requested_count_explicit=requested_count_explicit,
    )
