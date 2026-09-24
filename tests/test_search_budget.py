from app.search_budget import content_search_budget


def budget(duration, units=500, predicates=1, requested=12, explicit=False, mode="top_k"):
    return content_search_budget(
        scope_seconds=duration,
        unit_count=units,
        predicate_count=predicates,
        requested_count=requested,
        requested_count_explicit=explicit,
        result_mode=mode,
    )


def test_short_video_default_is_not_twelve_required_results() -> None:
    value = budget(60)
    assert value.tier == "short"
    assert value.result_limit == 12
    assert value.adaptive_target == 3
    assert value.maximum_batches == 3
    assert value.first_wave_units == 48
    assert value.attempts_per_batch == 1


def test_budget_scales_by_duration_with_hard_bounds() -> None:
    assert budget(300).maximum_batches == 5
    assert budget(1200).maximum_batches == 7
    assert budget(7200).maximum_batches == 10
    assert budget(7200, predicates=8).maximum_batches <= 13


def test_explicit_count_is_respected_without_unbounded_search() -> None:
    value = budget(240, units=1000, requested=12, explicit=True)
    assert value.adaptive_target == 12
    assert value.semantic_unit_limit == 80
    assert value.first_wave_units == 48


def test_exhaustive_mode_keeps_full_coverage_contract() -> None:
    value = budget(60, units=81, mode="exhaustive")
    assert value.adaptive_target is None
    assert value.semantic_unit_limit == 81
    assert value.maximum_batches == 6
    assert value.attempts_per_batch == 2
