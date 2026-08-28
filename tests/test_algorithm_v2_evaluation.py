import json
from pathlib import Path

import pytest

from tools.evaluate_algorithm_v2 import identity_metrics, load_cases, speaker_metrics


def test_evaluator_rejects_canned_or_missing_media(tmp_path: Path) -> None:
    dataset = tmp_path / "cases.jsonl"
    dataset.write_text(json.dumps({
        "caseId": "fake", "workflow": "content_search",
        "algorithmVersion": "editing-algorithm-v2",
        "sourceVideo": str(tmp_path / "missing.mp4"),
        "annotationSource": "canned", "groundTruth": [], "predictions": [],
    }), encoding="utf-8")
    with pytest.raises(ValueError):
        load_cases(dataset)


def test_identity_metric_detects_one_cluster_merging_two_people() -> None:
    report = identity_metrics([{
        "groundTruth": [
            {"start": 0, "end": 3, "identity": "a"},
            {"start": 3, "end": 6, "identity": "b"},
        ],
        "predictions": [{"start": 0, "end": 6, "identity": "merged"}],
    }])
    assert report["wrongMergeCount"] == 1
    assert report["idf1"] < .85


def test_identity_metric_penalizes_one_person_split_into_two_cards() -> None:
    report = identity_metrics([{
        "groundTruth": [{"start": 0, "end": 6, "identity": "a"}],
        "predictions": [
            {"start": 0, "end": 3, "identity": "card-a"},
            {"start": 3, "end": 6, "identity": "card-b"},
        ],
    }])
    assert report["wrongSplitCount"] == 1
    assert report["idf1"] == pytest.approx(.5)


def test_speaker_der_counts_miss_false_alarm_and_confusion_by_time() -> None:
    report = speaker_metrics([{
        "groundTruth": [
            {"start": 0, "end": 4, "identity": "a"},
            {"start": 4, "end": 8, "identity": "b"},
        ],
        "predictions": [
            {"start": 0, "end": 3, "identity": "speaker-1", "reliable": True},
            {"start": 3, "end": 6, "identity": "speaker-2", "reliable": True},
            {"start": 8, "end": 9, "identity": "speaker-3", "reliable": True},
        ],
    }])
    assert report["der"] > 0
    assert report["missRate"] > 0
    assert report["falseAlarmRate"] > 0
    assert report["confusionRate"] > 0
