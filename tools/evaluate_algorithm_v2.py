#!/usr/bin/env python3
"""Evaluate editing-algorithm-v2 against human-annotated real videos."""

from __future__ import annotations

import argparse
import json
import math
from collections import defaultdict
from pathlib import Path
from typing import Any

import numpy as np
from scipy.optimize import linear_sum_assignment


THRESHOLDS = {
    "content_search": {"minimumVideos": 30, "recall": .90, "precision": .95, "boundaryP95": .8, "wrongSpeakerRate": .01},
    "person_edit": {"minimumVideos": 10, "idf1": .85, "recall": .90, "precision": .95, "wrongMergeCount": 0, "wrongSplitCount": 0},
    "speaker_edit": {"minimumVideos": 10, "der": .10, "jer": .30, "wrongReliableRate": .01},
    "highlight": {"minimumVideos": 30, "recall": .90, "abWinRate": .65, "criticalTruncations": 0},
}


def overlap(left: dict[str, Any], right: dict[str, Any]) -> float:
    return max(0.0, min(float(left["end"]), float(right["end"])) - max(float(left["start"]), float(right["start"])))


def duration(item: dict[str, Any]) -> float:
    return max(0.0, float(item["end"]) - float(item["start"]))


def interval_metrics(rows: list[dict[str, Any]]) -> dict[str, float]:
    true_positive = false_positive = false_negative = 0
    boundary_errors: list[float] = []
    wrong_speaker = reliable_predictions = 0
    for row in rows:
        truth = list(row.get("groundTruth") or [])
        predictions = list(row.get("predictions") or [])
        available = set(range(len(truth)))
        for predicted in predictions:
            ranked = sorted(available, key=lambda index: overlap(predicted, truth[index]), reverse=True)
            chosen = ranked[0] if ranked and overlap(predicted, truth[ranked[0]]) / max(.001, min(duration(predicted), duration(truth[ranked[0]]))) >= .5 else None
            if chosen is None:
                false_positive += 1
                continue
            expected = truth[chosen]
            available.remove(chosen)
            true_positive += 1
            boundary_errors.extend([
                abs(float(predicted["start"]) - float(expected["start"])),
                abs(float(predicted["end"]) - float(expected["end"])),
            ])
            if str(predicted.get("confidenceTier") or "") == "reliable":
                reliable_predictions += 1
                if expected.get("speaker") and predicted.get("speaker") != expected.get("speaker"):
                    wrong_speaker += 1
        false_negative += len(available)
    precision = true_positive / max(1, true_positive + false_positive)
    recall = true_positive / max(1, true_positive + false_negative)
    boundary_errors.sort()
    boundary_p95 = boundary_errors[min(len(boundary_errors) - 1, math.ceil(len(boundary_errors) * .95) - 1)] if boundary_errors else float("inf")
    return {
        "precision": precision, "recall": recall, "boundaryP95": boundary_p95,
        "wrongSpeakerRate": wrong_speaker / max(1, reliable_predictions),
    }


def _identity_overlap_assignment(
    truth: list[dict[str, Any]], predictions: list[dict[str, Any]],
) -> tuple[dict[str, str], float, dict[tuple[str, str], float]]:
    """Globally map predicted identities to reference identities.

    A per-cluster majority match incorrectly gives a perfect score when one
    reference person is fragmented into several predicted cards.  A one-to-one
    assignment is the ID metric contract used here: one predicted identity can
    explain one reference identity, and every extra fragment becomes IDFP/IDFN.
    """
    truth_ids = sorted({str(item.get("identity") or "unknown") for item in truth})
    predicted_ids = sorted({str(item.get("identity") or "unknown") for item in predictions})
    overlaps = {
        (predicted_id, truth_id): sum(
            overlap(predicted, expected)
            for predicted in predictions if str(predicted.get("identity") or "unknown") == predicted_id
            for expected in truth if str(expected.get("identity") or "unknown") == truth_id
        )
        for predicted_id in predicted_ids for truth_id in truth_ids
    }
    if not predicted_ids or not truth_ids:
        return {}, 0.0, overlaps
    matrix = np.asarray([
        [-overlaps[(predicted_id, truth_id)] for truth_id in truth_ids]
        for predicted_id in predicted_ids
    ], dtype=np.float64)
    predicted_indexes, truth_indexes = linear_sum_assignment(matrix)
    mapping = {
        predicted_ids[int(predicted_index)]: truth_ids[int(truth_index)]
        for predicted_index, truth_index in zip(predicted_indexes, truth_indexes)
        if overlaps[(predicted_ids[int(predicted_index)], truth_ids[int(truth_index)])] > 0
    }
    matched = sum(overlaps[(predicted_id, truth_id)] for predicted_id, truth_id in mapping.items())
    return mapping, matched, overlaps


def identity_metrics(rows: list[dict[str, Any]]) -> dict[str, float | int]:
    idtp = idfp = idfn = wrong_merges = wrong_splits = 0.0
    for row in rows:
        truth = list(row.get("groundTruth") or [])
        predictions = list(row.get("predictions") or [])
        total_truth = sum(duration(item) for item in truth)
        total_predicted = sum(duration(item) for item in predictions)
        _, matched, identity_overlaps = _identity_overlap_assignment(truth, predictions)
        predicted_ids = {key[0] for key in identity_overlaps}
        truth_ids = {key[1] for key in identity_overlaps}
        wrong_merges += sum(
            len([truth_id for truth_id in truth_ids if identity_overlaps[(predicted_id, truth_id)] >= .5]) > 1
            for predicted_id in predicted_ids
        )
        wrong_splits += sum(
            len([predicted_id for predicted_id in predicted_ids if identity_overlaps[(predicted_id, truth_id)] >= .5]) > 1
            for truth_id in truth_ids
        )
        idtp += matched
        idfp += max(0.0, total_predicted - matched)
        idfn += max(0.0, total_truth - matched)
    return {
        "idf1": 2 * idtp / max(.001, 2 * idtp + idfp + idfn),
        "precision": idtp / max(.001, idtp + idfp),
        "recall": idtp / max(.001, idtp + idfn),
        "wrongMergeCount": int(wrong_merges),
        "wrongSplitCount": int(wrong_splits),
    }


def speaker_metrics(rows: list[dict[str, Any]]) -> dict[str, float]:
    reference_time = missed = false_alarm = confusion = wrong_reliable = reliable_time = 0.0
    speaker_jaccards: list[float] = []
    for row in rows:
        truth = list(row.get("groundTruth") or [])
        predictions = list(row.get("predictions") or [])
        mapping, _, identity_overlaps = _identity_overlap_assignment(truth, predictions)
        boundaries = sorted({
            float(item[key]) for item in [*truth, *predictions] for key in ("start", "end")
            if item.get(key) is not None
        })
        for start, end in zip(boundaries, boundaries[1:]):
            span = max(0.0, end - start)
            if span <= 0:
                continue
            midpoint = (start + end) * .5
            references = {
                str(item.get("identity") or "unknown") for item in truth
                if float(item["start"]) <= midpoint < float(item["end"])
            }
            active_predictions = [
                item for item in predictions
                if float(item["start"]) <= midpoint < float(item["end"])
            ]
            mapped_predictions = {
                mapping.get(str(item.get("identity") or "unknown"), "") for item in active_predictions
            } - {""}
            correct = len(references & mapped_predictions)
            reference_time += span * len(references)
            missed += span * max(0, len(references) - len(active_predictions))
            false_alarm += span * max(0, len(active_predictions) - len(references))
            confusion += span * max(0, min(len(references), len(active_predictions)) - correct)
            reliable_predictions = [item for item in active_predictions if item.get("reliable")]
            reliable_time += span * len(reliable_predictions)
            wrong_reliable += span * sum(
                mapping.get(str(item.get("identity") or "unknown"), "") not in references
                for item in reliable_predictions
            )
        predicted_ids = {key[0] for key in identity_overlaps}
        truth_ids = {key[1] for key in identity_overlaps}
        for truth_id in truth_ids:
            reference_duration = sum(duration(item) for item in truth if str(item.get("identity") or "unknown") == truth_id)
            predicted_id = next((value for value, target in mapping.items() if target == truth_id), "")
            predicted_duration = sum(
                duration(item) for item in predictions
                if str(item.get("identity") or "unknown") == predicted_id
            ) if predicted_id else 0.0
            intersection = identity_overlaps.get((predicted_id, truth_id), 0.0)
            union = reference_duration + predicted_duration - intersection
            speaker_jaccards.append(intersection / max(.001, union))
        # Keep static analyzers honest when a case contains system-only speakers.
        _ = predicted_ids
    return {
        "der": (missed + false_alarm + confusion) / max(.001, reference_time),
        "jer": 1.0 - sum(speaker_jaccards) / max(1, len(speaker_jaccards)),
        "missRate": missed / max(.001, reference_time),
        "falseAlarmRate": false_alarm / max(.001, reference_time),
        "confusionRate": confusion / max(.001, reference_time),
        "wrongReliableRate": wrong_reliable / max(.001, reliable_time),
    }


def load_cases(path: Path) -> list[dict[str, Any]]:
    rows = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
    for row in rows:
        source = Path(str(row.get("sourceVideo") or ""))
        if not source.is_file():
            raise ValueError(f"{row.get('caseId')}: sourceVideo 必须指向真实可读取视频")
        if str(row.get("annotationSource") or "").lower() in {"", "synthetic", "generated", "canned"}:
            raise ValueError(f"{row.get('caseId')}: annotationSource 必须记录人工标注来源")
        if str(row.get("algorithmVersion") or "") != "editing-algorithm-v2":
            raise ValueError(f"{row.get('caseId')}: 结果不是 editing-algorithm-v2")
    return rows


def evaluate(cases: list[dict[str, Any]]) -> dict[str, Any]:
    grouped = {workflow: [row for row in cases if row.get("workflow") == workflow] for workflow in THRESHOLDS}
    result: dict[str, Any] = {
        "content_search": {**interval_metrics(grouped["content_search"]), "videoCount": len(grouped["content_search"])},
        "person_edit": {**identity_metrics(grouped["person_edit"]), "videoCount": len(grouped["person_edit"])},
        "speaker_edit": {**speaker_metrics(grouped["speaker_edit"]), "videoCount": len(grouped["speaker_edit"])},
        "highlight": {
            "videoCount": len(grouped["highlight"]),
            "recall": interval_metrics(grouped["highlight"])["recall"],
            "abWinRate": sum(row.get("abWinner") == "v2" for row in grouped["highlight"]) / max(1, len(grouped["highlight"])),
            "criticalTruncations": sum(int(row.get("criticalTruncations") or 0) for row in grouped["highlight"]),
        },
    }
    ratios = [
        float(row["v2LatencySeconds"]) / max(.001, float(row["baselineLatencySeconds"]))
        for row in cases if row.get("v2LatencySeconds") is not None and row.get("baselineLatencySeconds") is not None
    ]
    result["latencyP95Ratio"] = sorted(ratios)[min(len(ratios) - 1, math.ceil(len(ratios) * .95) - 1)] if ratios else float("inf")
    failures: list[str] = []
    for workflow, thresholds in THRESHOLDS.items():
        for metric, threshold in thresholds.items():
            actual = result[workflow].get("videoCount") if metric == "minimumVideos" else result[workflow].get(metric)
            passed = actual >= threshold if metric not in {"boundaryP95", "wrongSpeakerRate", "wrongMergeCount", "wrongSplitCount", "der", "jer", "wrongReliableRate", "criticalTruncations"} else actual <= threshold
            if not passed:
                failures.append(f"{workflow}.{metric}: {actual} / {threshold}")
    if result["latencyP95Ratio"] > 2:
        failures.append(f"latencyP95Ratio: {result['latencyP95Ratio']} / 2.0")
    result["passed"] = not failures
    result["failures"] = failures
    return result


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("dataset", type=Path)
    parser.add_argument("--check", action="store_true")
    parser.add_argument("--require-input", action="store_true")
    args = parser.parse_args()
    if not args.dataset.is_file():
        print(json.dumps({"passed": False, "error": "缺少真实人工标注评测集", "dataset": str(args.dataset)}, ensure_ascii=False))
        return 2 if args.require_input or args.check else 0
    try:
        report = evaluate(load_cases(args.dataset))
    except (ValueError, json.JSONDecodeError) as error:
        print(json.dumps({"passed": False, "error": str(error)}, ensure_ascii=False))
        return 2
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 1 if args.check and not report["passed"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
