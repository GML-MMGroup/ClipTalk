"""Conservative provenance guards: repairing syntax must not erase a request."""
from __future__ import annotations

import re


def _compact(text: str) -> str:
    return re.sub(r"[\s，。；、,.!?！？:：]", "", text).lower()


def requirement_errors(query: str, predicates: list[dict], previous: list[dict] | None = None) -> list[dict]:
    # Source spans are provenance, not semantic similarity. Only compare clauses
    # grounded in the original query; never infer requirements from model prose.
    spans = [str((p.get("sourceSpan") or {}).get("text") or "").strip() for p in predicates]
    source = _compact(query)
    grounded = [s for s in spans if s and _compact(s) in source]
    represented = [_compact(s) for s in grounded]
    missing = []
    for p in previous or []:
        span = str((p.get("sourceSpan") or {}).get("text") or "").strip()
        if span and _compact(span) in source and not any(_compact(span) in s for s in represented):
            # Splitting one original span into multiple predicates is allowed.
            if not represented or any(part not in "".join(represented) for part in re.split(r"以及|并且|和|与|及", _compact(span)) if part):
                missing.append(span)
    # Detect an omitted conjunct only when at least one other conjunct has
    # explicit source provenance. Do not reject legacy/paraphrased predicates.
    clauses = [s.strip() for s in re.split(r"以及|并且|和|与", query) if len(s.strip()) >= 2]
    if len(clauses) > 1 and any(_compact(c) in s for c in clauses for s in represented):
        missing.extend(c for c in clauses if not any(_compact(c) in s for s in represented))
    return [{"code": "requirement_coverage_missing", "missingRequirements": list(dict.fromkeys(missing)),
             "message": "要求解析遗漏了原文条件：" + "、".join(dict.fromkeys(missing)) + "。请保留全部要求并修复关系，不能删除条件来通过检查。"}] if missing else []
