from app.analysis_completion import analysis_manifest_outcome


def test_analysis_manifest_routes_nonempty_events_to_review() -> None:
    assert analysis_manifest_outcome({"candidates": [{"id": "shot_1"}], "eventGroups": [{"id": "event_1"}]}) == "review"


def test_analysis_manifest_treats_empty_discovery_as_valid_no_result() -> None:
    assert analysis_manifest_outcome({"candidates": [], "eventGroups": []}) == "empty"


def test_analysis_manifest_rejects_candidates_without_event_groups() -> None:
    assert analysis_manifest_outcome({"candidates": [{"id": "shot_1"}], "eventGroups": []}) == "invalid"
