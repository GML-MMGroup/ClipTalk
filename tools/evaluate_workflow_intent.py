from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import httpx

PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CORPUS = PROJECT_ROOT / "benchmarks" / "workflow-intent.jsonl"


def load_cases(path: Path) -> list[dict[str, str]]:
    cases = []
    for line_number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        if not line.strip():
            continue
        value = json.loads(line)
        expected = str(value.get("expected") or "")
        text = str(value.get("text") or "")
        if expected not in {"highlight", "content_search", "person_edit", "speaker_edit", "clarification"} or not text:
            raise ValueError(f"{path}:{line_number} 不是有效意图样例")
        cases.append({"expected": expected, "text": text})
    return cases


def evaluate(args: argparse.Namespace) -> tuple[dict[str, Any], int]:
    cases = load_cases(args.corpus)
    headers = {"X-Highlight-Token": args.token} if args.token else {}
    results = []
    with httpx.Client(base_url=args.base_url.rstrip("/"), headers=headers, timeout=args.timeout) as client:
        for case in cases:
            try:
                response = client.post("/api/workflow-intent/classify", json={"text": case["text"]})
                response.raise_for_status()
                payload = response.json()
                decision = payload.get("decision") if isinstance(payload, dict) else {}
                actual = "clarification" if decision.get("needsConfirmation") else str(decision.get("workflowKind") or "")
                safe = actual == case["expected"] or actual == "clarification"
                results.append({
                    **case, "actual": actual, "exact": actual == case["expected"], "safe": safe,
                    "decision": decision,
                })
            except (httpx.HTTPError, ValueError, KeyError, TypeError) as error:
                results.append({**case, "actual": "error", "exact": False, "safe": True, "error": str(error)})
    exact_count = sum(bool(item["exact"]) for item in results)
    unsafe_count = sum(not bool(item["safe"]) for item in results)
    exact_rate = exact_count / len(results) if results else 0.0
    passed = exact_rate >= args.minimum_exact_rate and unsafe_count == 0
    report = {
        "schemaVersion": 1,
        "createdAt": datetime.now(timezone.utc).isoformat(),
        "baseUrl": args.base_url,
        "corpus": str(args.corpus),
        "summary": {
            "total": len(results), "exact": exact_count,
            "exactRate": round(exact_rate, 4), "unsafe": unsafe_count,
            "minimumExactRate": args.minimum_exact_rate, "passed": passed,
        },
        "results": results,
    }
    return report, 0 if passed else 1


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="使用服务当前配置的 LLM 评测四工作流意图判断")
    parser.add_argument("--base-url", default="http://127.0.0.1:5191")
    parser.add_argument("--token", default="")
    parser.add_argument("--corpus", type=Path, default=DEFAULT_CORPUS)
    parser.add_argument("--output", type=Path, default=PROJECT_ROOT / "test-results" / "workflow-intent-llm.json")
    parser.add_argument("--timeout", type=float, default=30.0)
    parser.add_argument("--minimum-exact-rate", type=float, default=.95)
    args = parser.parse_args(argv)
    report, exit_code = evaluate(args)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    summary = report["summary"]
    print(
        f"意图评测：{summary['exact']}/{summary['total']} 精确，"
        f"{summary['unsafe']} 条不安全自动路由，报告：{args.output}"
    )
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
