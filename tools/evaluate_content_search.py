#!/usr/bin/env python3
"""Compute grounded content-search quality, dialogue and cost metrics.

Each line must contain expected/predicted ranges and may include
excludedUnitIds plus retrievalStats. This intentionally evaluates saved
results and never invokes ASR, LLM or VLM providers.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.content_search import evaluate_content_search_cases


def main() -> None:
    parser = argparse.ArgumentParser(description="Evaluate annotated content-search JSONL results")
    parser.add_argument("input", type=Path, help="JSONL file with expected and predicted ranges")
    parser.add_argument(
        "--require-input", action="store_true",
        help="Fail instead of reporting not-run when a private dataset is absent",
    )
    parser.add_argument("--check", action="store_true", help="Fail when regression thresholds are not met")
    parser.add_argument("--min-recall", type=float, default=0.80)
    parser.add_argument("--min-precision", type=float, default=0.75)
    parser.add_argument("--max-boundary-mae", type=float, default=2.0)
    parser.add_argument("--max-boundary-p95", type=float, default=999.0)
    parser.add_argument("--max-wrong-speaker-rate", type=float, default=1.0)
    parser.add_argument("--min-intent-accuracy", type=float, default=0.0)
    parser.add_argument("--max-llm-calls", type=float, default=4.0)
    parser.add_argument("--max-vlm-calls", type=float, default=3.0)
    parser.add_argument("--min-grounding-rate", type=float, default=1.0)
    parser.add_argument("--min-exhaustive-recall", type=float, default=0.92)
    parser.add_argument("--min-high-confidence-precision", type=float, default=0.97)
    parser.add_argument("--require-complete-coverage", action="store_true")
    parser.add_argument("--min-real-cases", type=int, default=0)
    parser.add_argument("--min-annotated-turns", type=int, default=0)
    parser.add_argument("--min-annotated-qa-pairs", type=int, default=0)
    parser.add_argument(
        "--strict-interview", action="store_true",
        help="Apply the production interview/lesson quality bar from the dialogue-v2 plan",
    )
    args = parser.parse_args()
    if not args.input.is_file():
        print(json.dumps({
            "status": "not_run",
            "dataset": str(args.input),
            "reason": "标注集未提供；请按 benchmarks/INTERVIEW_ANNOTATION.md 准备本地私有数据",
        }, ensure_ascii=False, indent=2))
        if args.require_input:
            raise SystemExit(2)
        return
    cases = [
        json.loads(line)
        for line in args.input.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    metrics = evaluate_content_search_cases(cases)
    print(json.dumps(metrics, ensure_ascii=False, indent=2))
    if args.check:
        if args.strict_interview:
            args.min_recall = .90
            args.min_precision = .95
            args.max_boundary_p95 = .8
            args.max_wrong_speaker_rate = .01
            args.min_intent_accuracy = .95
            args.min_grounding_rate = 1.0
            args.min_real_cases = max(args.min_real_cases, 30)
            args.min_annotated_turns = max(args.min_annotated_turns, 600)
            args.min_annotated_qa_pairs = max(args.min_annotated_qa_pairs, 200)
            args.require_complete_coverage = True
        failures = []
        checks = (
            (metrics["recallAt5"] >= args.min_recall, f"recallAt5 {metrics['recallAt5']} < {args.min_recall}"),
            (metrics["precisionAt5"] >= args.min_precision, f"precisionAt5 {metrics['precisionAt5']} < {args.min_precision}"),
            (metrics["boundaryMaeSeconds"] <= args.max_boundary_mae, f"boundary MAE {metrics['boundaryMaeSeconds']} > {args.max_boundary_mae}"),
            (metrics["boundaryP95Seconds"] <= args.max_boundary_p95, f"boundary P95 {metrics['boundaryP95Seconds']} > {args.max_boundary_p95}"),
            (metrics["wrongSpeakerDurationRate"] <= args.max_wrong_speaker_rate, f"wrong-speaker rate {metrics['wrongSpeakerDurationRate']} > {args.max_wrong_speaker_rate}"),
            (metrics["intentAccuracy"] >= args.min_intent_accuracy, f"intent accuracy {metrics['intentAccuracy']} < {args.min_intent_accuracy}"),
            (metrics["realCaseCount"] >= args.min_real_cases, f"real cases {metrics['realCaseCount']} < {args.min_real_cases}"),
            (metrics["annotatedTurnCount"] >= args.min_annotated_turns, f"annotated turns {metrics['annotatedTurnCount']} < {args.min_annotated_turns}"),
            (metrics["annotatedQaPairCount"] >= args.min_annotated_qa_pairs, f"annotated QA pairs {metrics['annotatedQaPairCount']} < {args.min_annotated_qa_pairs}"),
            (metrics["exclusionViolations"] == 0, f"exclusion violations = {metrics['exclusionViolations']}"),
            (metrics["averageLlmCalls"] <= args.max_llm_calls, f"average LLM calls {metrics['averageLlmCalls']} > {args.max_llm_calls}"),
            (metrics["averageVlmCalls"] <= args.max_vlm_calls, f"average VLM calls {metrics['averageVlmCalls']} > {args.max_vlm_calls}"),
            (metrics["evidenceGroundingRate"] >= args.min_grounding_rate, f"evidence grounding {metrics['evidenceGroundingRate']} < {args.min_grounding_rate}"),
        )
        failures.extend(message for passed, message in checks if not passed)
        if metrics.get("exhaustiveCaseCount"):
            if metrics["exhaustiveRecall"] < args.min_exhaustive_recall:
                failures.append(
                    f"exhaustive recall {metrics['exhaustiveRecall']} < {args.min_exhaustive_recall}"
                )
            if args.require_complete_coverage and metrics["coverageCompleteRate"] < 1.0:
                failures.append(f"coverage complete rate {metrics['coverageCompleteRate']} < 1.0")
        if metrics.get("highConfidenceCount") and metrics["highConfidencePrecision"] < args.min_high_confidence_precision:
            failures.append(
                f"high-confidence precision {metrics['highConfidencePrecision']} < {args.min_high_confidence_precision}"
            )
        if failures:
            raise SystemExit("Quality regression: " + "; ".join(failures))


if __name__ == "__main__":
    main()
