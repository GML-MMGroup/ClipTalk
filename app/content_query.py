from __future__ import annotations

import copy
import math
import re
import uuid
from collections.abc import Iterable
from typing import Any


PREDICATE_KINDS = frozenset({
    "speech.semantic", "speech.exact", "speech.dialogue_role",
    "question.evidence",
    "screen_text.text",
    "visual.semantic", "visual.object", "visual.action",
    "audio.event", "audio.semantic",
    "person.appearance", "person.speaking",
})
QUERY_PLAN_VERSION = "query-plan-v7-typed-logic-20260820"
LOGIC_OPERATORS = frozenset({"predicate", "all", "any", "not"})
RELATION_TYPES = frozenset({
    "overlaps", "before", "after", "within", "contains", "during",
    "same_shot", "same_event", "responds_to", "not",
})
KIND_MODALITY = {
    "speech.semantic": "speech", "speech.exact": "speech", "speech.dialogue_role": "speech",
    "question.evidence": "mixed",
    "screen_text.text": "ocr",
    "visual.semantic": "visual", "visual.object": "visual", "visual.action": "visual",
    "audio.event": "audio", "audio.semantic": "audio",
    "person.appearance": "person", "person.speaking": "speech",
}


def _number(value: Any, default: float = 0.0) -> float:
    try:
        result = float(value)
    except (TypeError, ValueError):
        return default
    return result if math.isfinite(result) else default


def _strings(value: Any) -> list[str]:
    if isinstance(value, str):
        values = re.split(r"[，,、;；\n]+", value)
    elif isinstance(value, (list, tuple, set)):
        values = value
    else:
        values = []
    return list(dict.fromkeys(str(item).strip() for item in values if str(item).strip()))


def _predicate_value(predicate: dict[str, Any]) -> str:
    attributes = predicate.get("attributes") if isinstance(predicate.get("attributes"), dict) else {}
    subject = predicate.get("subject")
    subject_values = [
        subject.get("description"), subject.get("role"), subject.get("text"),
    ] if isinstance(subject, dict) else [subject]
    values = [
        predicate.get("value"), predicate.get("text"), predicate.get("entity"),
        predicate.get("action"), *subject_values, predicate.get("subjectDescription"),
        predicate.get("role"),
        *[f"{key} {value}" for key, value in attributes.items() if value not in (None, "")],
    ]
    return " ".join(dict.fromkeys(
        str(value).strip() for value in values
        if value is not None and str(value).strip()
    ))[:300]


def predicate_query_text(predicate: dict[str, Any]) -> str:
    values = [_predicate_value(predicate)]
    values.extend(str(value) for value in predicate.get("concepts") or [])
    values.extend(str(value) for value in predicate.get("retrievalVariants") or [])
    return " ".join(dict.fromkeys(value.strip() for value in values if value.strip()))[:900]


def predicate_retrieval_queries(predicate: dict[str, Any]) -> list[str]:
    """Return independent semantic recall queries while preserving the original predicate."""
    base = _predicate_value(predicate).strip()
    if not base:
        return []
    variants = [
        str(value).strip() for value in (
            *list(predicate.get("concepts") or []), *list(predicate.get("retrievalVariants") or []),
        ) if str(value).strip()
    ]
    queries = [base]
    queries.extend(f"{base} {value}" for value in variants)
    return list(dict.fromkeys(query[:900] for query in queries))[:25]


def predicate_modality(predicate: dict[str, Any]) -> str:
    return KIND_MODALITY.get(str(predicate.get("kind") or ""), "")


def _normalize_predicates(raw: Any) -> list[dict[str, Any]]:
    rows = raw if isinstance(raw, list) else []
    result: list[dict[str, Any]] = []
    seen_ids: set[str] = set()
    for position, source in enumerate(rows, 1):
        if not isinstance(source, dict):
            continue
        kind = str(source.get("kind") or "").strip().lower()
        if kind not in PREDICATE_KINDS:
            continue
        predicate_id = str(source.get("id") or f"p{position}").strip()
        if not re.fullmatch(r"[A-Za-z][A-Za-z0-9_-]{0,47}", predicate_id) or predicate_id in seen_ids:
            predicate_id = f"p{position}"
        seen_ids.add(predicate_id)
        required = source.get("required", True)
        predicate = {
            "id": predicate_id,
            "kind": kind,
            "value": str(source.get("value") or source.get("text") or "").strip()[:300],
            # Never use bool("false"): string booleans are rejected by the
            # validator and remain non-authoritative here.
            "required": required if isinstance(required, bool) else True,
        }
        for key in (
            "entity", "subject", "action", "objectRef", "speakerRef", "personRef", "personId",
            "subjectPersonRef", "subjectPersonId", "subjectPersonPredicateId",
            "subjectDescription", "subjectIdentityPolicy", "subjectEvidencePolicy",
            "role", "segmentUnit", "dialogueMode", "interruptionPolicy", "source", "questionSource",
        ):
            if source.get(key) not in (None, ""):
                predicate[key] = str(source[key]).strip()[:120]
        if isinstance(source.get("subject"), dict):
            subject = source["subject"]
            description = str(
                subject.get("description") or subject.get("text") or subject.get("role") or ""
            ).strip()[:120]
            if description:
                predicate["subject"] = {"description": description}
                predicate["subjectDescription"] = description
                subject_type = str(subject.get("type") or subject.get("entityType") or "").strip().lower()
                if subject_type in {"person", "human", "role", "object", "topic", "organization", "place"}:
                    predicate["subject"]["type"] = subject_type
                policy = str(subject.get("identityPolicy") or subject.get("evidencePolicy") or "").strip().lower()
                if policy in {"ignore", "context", "verify"}:
                    predicate["subject"]["identityPolicy"] = policy
        for key in ("concepts", "retrievalVariants"):
            if isinstance(source.get(key), list):
                predicate[key] = list(dict.fromkeys(
                    str(value).strip()[:120] for value in source[key] if str(value).strip()
                ))[:24]
        for key in ("includePrompt", "requirePromptRelation"):
            if source.get(key) is not None:
                predicate[key] = source[key] if isinstance(source[key], bool) else False
        if isinstance(source.get("sourceSpan"), dict):
            span = source["sourceSpan"]
            predicate["sourceSpan"] = {
                "start": max(0, int(_number(span.get("start"), 0))),
                "end": max(0, int(_number(span.get("end"), 0))),
                "text": str(span.get("text") or "")[:300],
            }
        if isinstance(source.get("attributes"), dict):
            predicate["attributes"] = {
                str(key)[:60]: str(value)[:120]
                for key, value in source["attributes"].items() if value not in (None, "")
            }
        if not _predicate_value(predicate):
            continue
        result.append(predicate)
    return result[:12]


def _fallback_predicates(intent: dict[str, Any]) -> list[dict[str, Any]]:
    query = str(intent.get("query") or "").strip()[:300]
    modalities = list(dict.fromkeys(_strings(intent.get("modalities"))))
    speech_quotes = _strings(intent.get("speechQuotes"))
    entities = _strings(intent.get("entities"))
    actions = _strings(intent.get("actions"))
    speakers = _strings(intent.get("speakerRefs"))
    persons = _strings(intent.get("personRefs"))
    predicates: list[dict[str, Any]] = []

    def add(kind: str, value: str, **extra: Any) -> None:
        text = str(value or "").strip()
        if not text:
            return
        predicates.append({
            "id": f"p{len(predicates) + 1}", "kind": kind, "value": text[:300],
            "required": True, **extra,
        })

    for quote in speech_quotes:
        add("speech.exact", quote, **({"speakerRef": speakers[0]} if speakers else {}))
    if "speech" in modalities and not speech_quotes:
        add("speech.semantic", query, **({"speakerRef": speakers[0]} if speakers else {}))
    if "ocr" in modalities:
        add("screen_text.text", query)
    for entity in entities:
        add("visual.object", entity, entity=entity)
    for action in actions:
        add("visual.action", action, action=action)
    if "visual" in modalities and not entities and not actions:
        add("visual.semantic", query)
    if "audio" in modalities:
        kind = "audio.semantic" if re.search(r"氛围|舒缓|压迫|嘈杂|类似|ambient|mood", query, re.I) else "audio.event"
        add(kind, query)
    for person in persons:
        add("person.appearance", person, personRef=person)
    if "person" in modalities and not persons:
        add("person.appearance", query)
    if not predicates and query:
        add("speech.semantic", query)
    return predicates[:12]


def _normalize_relations(raw: Any, predicate_ids: set[str]) -> list[dict[str, Any]]:
    rows = raw if isinstance(raw, list) else []
    result: list[dict[str, Any]] = []
    seen: set[tuple[str, str, str]] = set()
    for source in rows:
        if not isinstance(source, dict):
            continue
        relation_type = str(source.get("type") or "").strip().lower()
        left = str(source.get("left") or source.get("leftPredicateId") or "").strip()
        right = str(source.get("right") or source.get("rightPredicateId") or "").strip()
        key = (relation_type, left, right)
        if relation_type not in RELATION_TYPES or left not in predicate_ids or right not in predicate_ids or left == right or key in seen:
            continue
        seen.add(key)
        tolerance_seconds = _number(source.get("toleranceSeconds"), -1.0)
        if tolerance_seconds < 0 and source.get("toleranceUs") is not None:
            tolerance_seconds = _number(source.get("toleranceUs")) / 1_000_000
        maximum_gap_seconds = _number(source.get("maximumGapSeconds"), -1.0)
        if maximum_gap_seconds < 0 and source.get("maximumGapUs") is not None:
            maximum_gap_seconds = _number(source.get("maximumGapUs")) / 1_000_000
        relation = {
            "type": relation_type, "left": left, "right": right,
            "toleranceSeconds": round(max(0.0, tolerance_seconds if tolerance_seconds >= 0 else .5), 3),
        }
        if maximum_gap_seconds >= 0:
            relation["maximumGapSeconds"] = round(max(0.0, maximum_gap_seconds), 3)
        elif relation_type == "within":
            # ``within`` has no useful deterministic meaning without a
            # bounded window.  Keep the relation so callers can explain the
            # invalid plan, but never silently turn it into an infinite join.
            relation["invalidReason"] = "within_requires_maximum_gap"
        result.append(relation)
    return result[:20]


def _raw_query_validation_errors(
    raw_predicates: Any, raw_relations: Any,
) -> list[dict[str, Any]]:
    """Report malformed model output before normalization can discard it."""
    errors: list[dict[str, Any]] = []
    rows = raw_predicates if isinstance(raw_predicates, list) else []
    raw_ids: set[str] = set()
    for position, source in enumerate(rows, 1):
        if not isinstance(source, dict):
            errors.append({
                "code": "invalid_predicate", "position": position,
                "message": "检索条件必须是结构化对象。",
            })
            continue
        predicate_id = str(source.get("id") or f"p{position}").strip()
        if predicate_id in raw_ids:
            errors.append({
                "code": "duplicate_predicate_id", "predicateId": predicate_id,
                "message": "检索条件 ID 重复。",
            })
        raw_ids.add(predicate_id)
        kind = str(source.get("kind") or "").strip().lower()
        if kind not in PREDICATE_KINDS:
            errors.append({
                "code": "unknown_predicate_kind", "predicateId": predicate_id, "kind": kind,
                "message": "检索条件使用了未知证据类型。",
            })
        for key in ("required", "includePrompt", "requirePromptRelation"):
            if key in source and not isinstance(source.get(key), bool):
                errors.append({
                    "code": "invalid_boolean", "predicateId": predicate_id, "field": key,
                    "message": f"{key} 必须是真正的布尔值。",
                })
    relation_rows = raw_relations if isinstance(raw_relations, list) else []
    for position, source in enumerate(relation_rows, 1):
        if not isinstance(source, dict):
            errors.append({
                "code": "invalid_relation", "position": position,
                "message": "条件关系必须是结构化对象。",
            })
            continue
        relation_type = str(source.get("type") or "").strip().lower()
        left = str(source.get("left") or source.get("leftPredicateId") or "").strip()
        right = str(source.get("right") or source.get("rightPredicateId") or "").strip()
        if relation_type not in RELATION_TYPES:
            errors.append({
                "code": "unknown_relation_type", "relationType": relation_type,
                "message": "条件关系类型无效。",
            })
        if left not in raw_ids or right not in raw_ids or left == right:
            errors.append({
                "code": "invalid_relation_endpoint", "left": left, "right": right,
                "message": "条件关系引用了不存在或相同的条件。",
            })
    return errors


def _normalize_logic(
    raw: Any, predicate_ids: set[str], *, positive_ids: list[str], negative_ids: set[str],
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    errors: list[dict[str, Any]] = []

    def visit(node: Any, path: str = "logic") -> dict[str, Any] | None:
        if not isinstance(node, dict):
            errors.append({"code": "invalid_logic", "path": path, "message": "逻辑表达式必须是结构化对象。"})
            return None
        op = str(node.get("op") or "").strip().lower()
        if op not in LOGIC_OPERATORS:
            errors.append({"code": "unknown_logic_operator", "path": path, "message": "逻辑表达式包含未知操作。"})
            return None
        if op == "predicate":
            predicate_id = str(node.get("predicateId") or "").strip()
            if predicate_id not in predicate_ids:
                errors.append({
                    "code": "invalid_logic_predicate", "path": path, "predicateId": predicate_id,
                    "message": "逻辑表达式引用了不存在的条件。",
                })
                return None
            return {"op": "predicate", "predicateId": predicate_id}
        if op == "not":
            child = visit(node.get("child"), f"{path}.child")
            return {"op": "not", "child": child} if child else None
        children = [visit(child, f"{path}.children[{position}]") for position, child in enumerate(node.get("children") or [])]
        children = [child for child in children if child]
        if not children:
            errors.append({"code": "empty_logic_group", "path": path, "message": "逻辑分组不能为空。"})
            return None
        return {"op": op, "children": children}

    normalized = visit(raw) if raw is not None else None
    if normalized is None:
        leaves = [{"op": "predicate", "predicateId": value} for value in positive_ids]
        leaves.extend({"op": "not", "child": {"op": "predicate", "predicateId": value}} for value in sorted(negative_ids))
        normalized = leaves[0] if len(leaves) == 1 else {"op": "all", "children": leaves}
    return normalized, errors


def _prune_logic_predicates(raw: Any, removed_ids: set[str]) -> dict[str, Any] | None:
    if not isinstance(raw, dict):
        return None
    op = str(raw.get("op") or "").strip().lower()
    if op == "predicate":
        return None if str(raw.get("predicateId") or "") in removed_ids else copy.deepcopy(raw)
    if op == "not":
        child = _prune_logic_predicates(raw.get("child"), removed_ids)
        return {"op": "not", "child": child} if child else None
    if op in {"all", "any"}:
        children = [
            child for child in (
                _prune_logic_predicates(value, removed_ids) for value in raw.get("children") or []
            ) if child
        ]
        if len(children) == 1:
            return children[0]
        return {"op": op, "children": children} if children else None
    return copy.deepcopy(raw)


def _logic_branches(logic: dict[str, Any], *, maximum_branches: int = 32) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Compile nested boolean logic to bounded DNF execution branches."""
    errors: list[dict[str, Any]] = []

    def compile_node(node: dict[str, Any], negated: bool = False) -> list[tuple[set[str], set[str]]]:
        op = str(node.get("op") or "")
        if op == "predicate":
            predicate_id = str(node.get("predicateId") or "")
            return [(set(), {predicate_id})] if negated else [({predicate_id}, set())]
        if op == "not":
            return compile_node(node.get("child") or {}, not negated)
        effective = "all" if (op == "any" and negated) else "any" if (op == "all" and negated) else op
        children = list(node.get("children") or [])
        if effective == "any":
            return [branch for child in children for branch in compile_node(child, negated)][:maximum_branches]
        result: list[tuple[set[str], set[str]]] = [(set(), set())]
        for child in children:
            next_rows: list[tuple[set[str], set[str]]] = []
            for left_positive, left_negative in result:
                for right_positive, right_negative in compile_node(child, negated):
                    positive = left_positive | right_positive
                    negative = left_negative | right_negative
                    if positive & negative:
                        continue
                    next_rows.append((positive, negative))
                    if len(next_rows) >= maximum_branches:
                        break
                if len(next_rows) >= maximum_branches:
                    break
            result = next_rows
        return result

    compiled = compile_node(logic)
    if len(compiled) >= maximum_branches:
        errors.append({"code": "logic_branch_limit", "message": "检索逻辑展开后的分支过多，请简化条件。"})
    branches = [{
        "id": f"branch_{position}",
        "predicateIds": sorted(positive),
        "negativePredicateIds": sorted(negative),
    } for position, (positive, negative) in enumerate(compiled[:maximum_branches], 1) if positive]
    if not branches:
        errors.append({"code": "logic_has_no_positive_branch", "message": "检索逻辑至少需要一个正向条件。"})
    return branches, errors


def compile_query_plan(
    intent: dict[str, Any], *, allow_fallback_predicates: bool = True,
) -> dict[str, Any]:
    raw_plan = intent.get("queryPlan") if isinstance(intent.get("queryPlan"), dict) else {}
    raw_predicates = raw_plan.get("predicates") or intent.get("predicates")
    raw_relations = raw_plan.get("relations") or intent.get("relations")
    validation_errors = _raw_query_validation_errors(raw_predicates, raw_relations)
    predicates = _normalize_predicates(raw_predicates)
    if not predicates and allow_fallback_predicates:
        predicates = _fallback_predicates(intent)
    predicate_ids = {str(item["id"]) for item in predicates}
    relations = _normalize_relations(raw_relations, predicate_ids)

    # ``person.speaking`` already proves that the referenced person is visible.
    # Keeping a second appearance predicate for the same anonymous person made
    # the temporal join compare a result with a copy of itself and presented a
    # misleading "all conditions" explanation to the user.
    speaking_refs = {
        str(item.get("personRef") or item.get("value") or "").strip().casefold()
        for item in predicates if item.get("kind") == "person.speaking"
    }
    redundant_ids = {
        str(item.get("id") or "") for item in predicates
        if item.get("kind") == "person.appearance"
        and str(item.get("personRef") or item.get("value") or "").strip().casefold() in speaking_refs
    }
    if redundant_ids:
        predicates = [item for item in predicates if str(item.get("id") or "") not in redundant_ids]
        relations = [
            item for item in relations
            if str(item.get("left") or "") not in redundant_ids
            and str(item.get("right") or "") not in redundant_ids
        ]
        predicate_ids = {str(item["id"]) for item in predicates}

    # Legacy parsers supplied relation words but no endpoints. Preserve the
    # common two-condition cases deterministically instead of silently
    # treating them as unrelated OR terms.
    if not relations and len(predicates) == 2:
        words = " ".join(_strings(intent.get("temporalRelations"))).lower()
        relation_type = ""
        if re.search(r"同时|当.+时|期间|overlap|same time", words):
            relation_type = "overlaps"
        elif re.search(r"之后|以后|随后|after", words):
            relation_type = "before"
        elif re.search(r"之前|以前|before", words):
            relation_type = "after"
        if relation_type:
            relations.append({
                "type": relation_type, "left": predicates[0]["id"], "right": predicates[1]["id"],
                "toleranceSeconds": 2.0,
            })

    negative_ids = {str(item["right"]) for item in relations if item.get("type") == "not"}
    for predicate in predicates:
        if predicate["id"] in negative_ids:
            predicate["required"] = False
    scope = intent.get("searchScope") if isinstance(intent.get("searchScope"), dict) else {}
    boundary_mode = str(intent.get("boundaryMode") or "complete")
    result_mode = str(
        raw_plan.get("result", {}).get("mode")
        if isinstance(raw_plan.get("result"), dict) else ""
    ).strip().lower() or str(intent.get("resultMode") or "top_k").strip().lower()
    if result_mode not in {"top_k", "exhaustive"}:
        result_mode = "top_k"
    requested_limit = intent.get("requestedCount")
    try:
        normalized_limit = max(1, min(200, int(requested_limit or 3)))
    except (TypeError, ValueError):
        normalized_limit = 3
    raw_person_target = (
        raw_plan.get("personTarget") if isinstance(raw_plan.get("personTarget"), dict)
        else intent.get("personTarget") if isinstance(intent.get("personTarget"), dict)
        else {}
    )
    person_target_ids = [
        str(value) for value in raw_person_target.get("predicateIds") or []
        if str(value) in predicate_ids
    ]
    person_target = None
    if person_target_ids:
        person_target = {
            "personIds": list(dict.fromkeys(
                str(value) for value in raw_person_target.get("personIds") or [] if str(value)
            ))[:12],
            "predicateIds": list(dict.fromkeys(person_target_ids))[:12],
            "matchMode": "all" if str(raw_person_target.get("matchMode")) == "all" else "any",
            "activity": "speaking" if str(raw_person_target.get("activity")) == "speaking" else "appearance",
            "speakingRelation": (
                "overlap" if str(raw_person_target.get("speakingRelation")) == "overlap"
                else "dialogue_event"
            ),
            "dialogueGapSeconds": max(1.0, min(30.0, _number(
                raw_person_target.get("dialogueGapSeconds"), 8.0,
            ))),
        }
    for relation in relations:
        if relation.get("invalidReason") == "within_requires_maximum_gap":
            validation_errors.append({
                "code": "within_requires_maximum_gap",
                "relation": {
                    "type": relation.get("type"), "left": relation.get("left"),
                    "right": relation.get("right"),
                },
                "message": "“相邻/一定时间内”需要明确最大时间间隔。",
            })
    required_positive_ids = {
        str(item.get("id")) for item in predicates if item.get("required", True)
    }
    explicit_logic = raw_plan.get("logic") if isinstance(raw_plan.get("logic"), dict) else intent.get("logic")
    if redundant_ids and isinstance(explicit_logic, dict):
        explicit_logic = _prune_logic_predicates(explicit_logic, redundant_ids)
    if explicit_logic is None:
        ambiguous_optional = [
            str(item.get("id")) for item in predicates
            if not item.get("required", True) and str(item.get("id")) not in negative_ids
        ]
        if ambiguous_optional:
            validation_errors.append({
                "code": "ambiguous_optional_predicates", "predicateIds": ambiguous_optional,
                "message": "检索条件不能用可选标记表达并集，请明确使用任一、同时或排除逻辑。",
            })
    logic, logic_errors = _normalize_logic(
        explicit_logic, predicate_ids,
        positive_ids=sorted(required_positive_ids), negative_ids=negative_ids,
    )
    branches, branch_errors = _logic_branches(logic)
    validation_errors.extend(logic_errors)
    validation_errors.extend(branch_errors)
    adjacency = {predicate_id: set() for predicate_id in required_positive_ids}
    for relation in relations:
        if relation.get("type") == "not":
            continue
        left, right = str(relation.get("left")), str(relation.get("right"))
        if left in adjacency and right in adjacency:
            adjacency[left].add(right)
            adjacency[right].add(left)
    reachable: set[str] = set()
    if required_positive_ids:
        pending = [next(iter(required_positive_ids))]
        while pending:
            predicate_id = pending.pop()
            if predicate_id in reachable:
                continue
            reachable.add(predicate_id)
            pending.extend(adjacency.get(predicate_id, set()) - reachable)
    # A person target set is one logical condition. Its members are collapsed
    # into an ANY union or ALL temporal group before the generic join runs.
    grouped_ids = set((person_target or {}).get("predicateIds") or [])
    connectivity_required = required_positive_ids - grouped_ids
    if grouped_ids:
        connectivity_required.add(next(iter(grouped_ids)))
        reachable_group = reachable & connectivity_required
        if reachable & grouped_ids:
            reachable_group.add(next(iter(grouped_ids)))
    else:
        reachable_group = reachable
    any_logic = str(logic.get("op") or "") == "any"
    if len(connectivity_required) > 1 and reachable_group != connectivity_required and not any_logic:
        validation_errors.append({
            "code": "unlinked_required_predicates",
            "predicateIds": sorted(connectivity_required - reachable_group),
            "message": "多个必要条件之间缺少明确的同时、先后、镜头或事件关系。",
        })
    for branch in branches:
        branch_ids = set(str(value) for value in branch.get("predicateIds") or [])
        if len(branch_ids) < 2:
            continue
        if grouped_ids and branch_ids <= grouped_ids:
            # personTarget owns the ANY/ALL semantics for its member tracks
            # and collapses them before the generic temporal join.
            continue
        branch_reachable: set[str] = set()
        pending = [next(iter(branch_ids))]
        while pending:
            predicate_id = pending.pop()
            if predicate_id in branch_reachable:
                continue
            branch_reachable.add(predicate_id)
            pending.extend((adjacency.get(predicate_id, set()) & branch_ids) - branch_reachable)
        if branch_reachable != branch_ids:
            error = {
                "code": "unlinked_logic_branch",
                "branchId": str(branch.get("id") or ""),
                "predicateIds": sorted(branch_ids - branch_reachable),
                "message": "必须同时满足的一组条件缺少明确的同时、先后、镜头或事件关系。",
            }
            if not any(
                item.get("code") == error["code"] and item.get("branchId") == error["branchId"]
                for item in validation_errors
            ):
                validation_errors.append(error)

    plan = {
        "schemaVersion": QUERY_PLAN_VERSION,
        "scope": {
            "coordinate": "source",
            "startUs": int(round(_number(scope.get("start")) * 1_000_000)),
            "endUs": int(round(_number(scope.get("end")) * 1_000_000)),
        },
        "predicates": predicates,
        "relations": relations,
        "logic": logic,
        "branches": branches,
        "boundary": {"target": boundary_mode},
        "result": {
            "mode": result_mode,
            "limit": None if result_mode == "exhaustive" else normalized_limit,
            "pageSize": 50,
            "diversify": result_mode != "exhaustive",
            "order": "source" if result_mode == "exhaustive" else "relevance",
        },
    }
    if person_target:
        plan["personTarget"] = person_target
    plan["validationErrors"] = validation_errors
    plan["clarificationRequired"] = bool(validation_errors)
    required_operations = {
        {
            "speech.semantic": "speech.semantic_search", "speech.exact": "speech.exact_search",
            "speech.dialogue_role": "dialogue.turn_graph",
            "question.evidence": "dialogue.turn_graph",
            "screen_text.text": "screen_text.fuzzy_search",
            "visual.semantic": "visual.embed", "visual.object": "visual.detect_object",
            "visual.action": "visual.verify_action", "audio.event": "audio.detect_event",
            "audio.semantic": "audio.semantic_embed", "person.appearance": "person.track_face",
            "person.speaking": "person.active_speaker_link",
        }[str(predicate["kind"])]
        for predicate in predicates
    }
    if any(predicate.get("kind") == "person.speaking" for predicate in predicates):
        # Active-speaker evidence is only meaningful when the same request has
        # a full person track and a searchable speech timeline.  Treat these
        # dependencies as first-class coverage requirements so an exhaustive
        # result can never be certified from mere face/transcript overlap.
        required_operations.update({
            "person.track_face", "person.active_speaker_link", "speech.semantic_search",
        })
    for predicate in predicates:
        if not str(predicate.get("subjectPersonRef") or predicate.get("subjectPersonId") or "").strip():
            subject = predicate.get("subject") if isinstance(predicate.get("subject"), dict) else {}
            policy = str(
                predicate.get("subjectIdentityPolicy")
                or predicate.get("subjectEvidencePolicy")
                or subject.get("identityPolicy")
                or "context"
            ).strip().lower()
            # Typed semantic subjects are verified by their predicate's own
            # evidence source. Do not add OCR for every object/role/topic.
            continue
        kind = str(predicate.get("kind") or "")
        if kind.startswith("speech."):
            required_operations.update({"person.track_face", "person.active_speaker_link"})
        elif kind == "visual.action":
            required_operations.update({"person.track_face", "person.verify_action_actor"})
    if any(relation.get("type") == "same_shot" for relation in relations):
        required_operations.add("timeline.shot_boundary")
    if any(relation.get("type") == "same_event" for relation in relations):
        required_operations.add("timeline.event_boundary")
    if any(relation.get("type") == "responds_to" for relation in relations):
        required_operations.add("dialogue.turn_graph")
    question_predicates = [
        predicate for predicate in predicates if predicate.get("kind") == "question.evidence"
    ]
    if question_predicates:
        question_sources = {
            str(predicate.get("source") or predicate.get("questionSource") or "all").lower()
            for predicate in question_predicates
        }
        has_other_dialogue_requirement = (
            any(predicate.get("kind") == "speech.dialogue_role" for predicate in predicates)
            or any(relation.get("type") == "responds_to" for relation in relations)
        )
        if question_sources & {"all", "spoken"}:
            required_operations.add("dialogue.turn_graph")
        elif not has_other_dialogue_requirement:
            required_operations.discard("dialogue.turn_graph")
        if question_sources & {"all", "screen"}:
            required_operations.add("screen_text.question_detect")
    plan["requiredOperations"] = sorted(required_operations)
    plan["fastPathExact"] = bool(predicates) and all(
        predicate["kind"] in {"speech.exact", "screen_text.text"} for predicate in predicates
    ) and not relations
    return plan


def _person_match_id(match: dict[str, Any], predicate: dict[str, Any]) -> str:
    evidence = match.get("activeSpeakerEvidence")
    if isinstance(evidence, dict) and evidence.get("personId"):
        return str(evidence["personId"])
    return str(predicate.get("personId") or "")


def _combine_person_group_matches(
    matches: list[dict[str, Any]], *, person_ids: list[str], title: str,
    start: float | None = None, end: float | None = None,
) -> dict[str, Any]:
    result = copy.deepcopy(matches[0])
    result["start"] = round(min(_number(item.get("start")) for item in matches) if start is None else start, 3)
    result["end"] = round(max(_number(item.get("end")) for item in matches) if end is None else end, 3)
    result["duration"] = round(max(0.0, result["end"] - result["start"]), 3)
    result["title"] = title
    result["matchedPersonIds"] = list(dict.fromkeys(person_ids))
    result["matchedPersonLabels"] = list(dict.fromkeys(
        str((item.get("activeSpeakerEvidence") or {}).get("personLabel") or "").strip()
        for item in matches if isinstance(item.get("activeSpeakerEvidence"), dict)
        and str((item.get("activeSpeakerEvidence") or {}).get("personLabel") or "").strip()
    ))
    result["matchedUnitIds"] = list(dict.fromkeys(
        str(value) for item in matches
        for value in (item.get("matchedUnitIds") or [item.get("unitId")]) if value
    ))
    result["matchedSegmentIds"] = list(dict.fromkeys(
        str(value) for item in matches for value in item.get("matchedSegmentIds") or [] if value
    ))
    result["evidenceRefs"] = list({
        (str(ref.get("type") or ""), str(ref.get("id") or "")): copy.deepcopy(ref)
        for item in matches for ref in item.get("evidenceRefs") or []
        if isinstance(ref, dict) and ref.get("id")
    }.values())
    result["evidenceTimes"] = sorted({
        _number(value) for item in matches for value in item.get("evidenceTimes") or []
    })
    result["matchedModalities"] = list(dict.fromkeys(
        str(value) for item in matches
        for value in item.get("matchedModalities") or [item.get("evidenceType")] if value
    ))
    result["speechUnits"] = sorted(
        [copy.deepcopy(value) for item in matches for value in item.get("speechUnits") or []],
        key=lambda value: _number(value.get("start")),
    )
    result["transcriptExcerpt"] = " ".join(dict.fromkeys(
        str(item.get("transcriptExcerpt") or "").strip() for item in matches
        if str(item.get("transcriptExcerpt") or "").strip()
    ))[:800]
    result["score"] = round(sum(_number(item.get("score")) for item in matches) / max(1, len(matches)), 1)
    result["confidence"] = round(min((_number(item.get("confidence"), .5) for item in matches), default=.5), 3)
    result["boundaryConfidence"] = round(min(
        (_number(item.get("boundaryConfidence"), .5) for item in matches), default=.5,
    ), 3)
    result["requiresReview"] = any(bool(item.get("requiresReview")) for item in matches)
    result["activeSpeakerEvidenceByPerson"] = {
        str(evidence.get("personId")): copy.deepcopy(evidence)
        for item in matches for evidence in [item.get("activeSpeakerEvidence")]
        if isinstance(evidence, dict) and evidence.get("personId")
    }
    result.pop("activeSpeakerEvidence", None)
    return result


def _collapse_person_target_group(
    query_plan: dict[str, Any], matches_by_predicate: dict[str, list[dict[str, Any]]],
    *, scene_cuts: list[float] | None = None, maximum_combinations: int = 240,
) -> tuple[dict[str, Any], dict[str, list[dict[str, Any]]]]:
    target = query_plan.get("personTarget")
    if not isinstance(target, dict):
        return query_plan, matches_by_predicate
    predicates = [item for item in query_plan.get("predicates") or [] if isinstance(item, dict)]
    lookup = {str(item.get("id") or ""): item for item in predicates}
    member_ids = [str(value) for value in target.get("predicateIds") or [] if str(value) in lookup]
    if not member_ids:
        return query_plan, matches_by_predicate
    person_ids = [str(value) for value in target.get("personIds") or [] if str(value)]
    member_rows = {
        member_id: [
            {**copy.deepcopy(item), "_groupPersonId": _person_match_id(item, lookup[member_id])}
            for item in matches_by_predicate.get(member_id, [])
        ] for member_id in member_ids
    }
    mode = str(target.get("matchMode") or "any")
    activity = str(target.get("activity") or "appearance")
    grouped: list[dict[str, Any]] = []
    if mode == "any":
        ordered = sorted(
            [item for rows in member_rows.values() for item in rows],
            key=lambda item: (_number(item.get("start")), _number(item.get("end"))),
        )
        for item in ordered:
            person_id = str(item.pop("_groupPersonId", ""))
            combined = _combine_person_group_matches(
                [item], person_ids=[person_id] if person_id else [],
                title=str(item.get("title") or "任一人物匹配"),
            )
            if grouped and _number(combined.get("start")) - _number(grouped[-1].get("end")) <= .35:
                previous = grouped.pop()
                ids = list(dict.fromkeys([
                    *(previous.get("matchedPersonIds") or []), *(combined.get("matchedPersonIds") or []),
                ]))
                grouped.append(_combine_person_group_matches(
                    [previous, combined], person_ids=ids,
                    title="任一人物发言" if activity == "speaking" else "任一人物出现",
                ))
            else:
                grouped.append(combined)
    elif activity == "speaking" and str(target.get("speakingRelation")) != "overlap":
        gap_limit = _number(target.get("dialogueGapSeconds"), 8.0)
        ordered = sorted(
            [item for rows in member_rows.values() for item in rows],
            key=lambda item: (_number(item.get("start")), _number(item.get("end"))),
        )
        events: list[list[dict[str, Any]]] = []
        cuts = sorted(_number(value) for value in scene_cuts or [])
        for item in ordered:
            if not events:
                events.append([item])
                continue
            previous_end = max(_number(value.get("end")) for value in events[-1])
            start = _number(item.get("start"))
            scene_break = any(previous_end < cut < start for cut in cuts)
            if start - previous_end > gap_limit or scene_break:
                events.append([item])
            else:
                events[-1].append(item)
        required_people = set(person_ids)
        for event in events:
            present = {str(item.get("_groupPersonId") or "") for item in event}
            if not required_people <= present:
                continue
            clean = [{key: value for key, value in item.items() if key != "_groupPersonId"} for item in event]
            grouped.append(_combine_person_group_matches(
                clean, person_ids=person_ids, title="同一对话中所有目标人物均有发言",
            ))
    else:
        combinations: list[list[dict[str, Any]]] = [[]]
        for member_id in member_ids:
            next_rows: list[list[dict[str, Any]]] = []
            for combination in combinations:
                for candidate in member_rows.get(member_id, []):
                    values = [*combination, candidate]
                    start = max(_number(item.get("start")) for item in values)
                    end = min(_number(item.get("end")) for item in values)
                    if end <= start:
                        continue
                    track_sets = [
                        set(str(value) for value in item.get("personTrackIds") or [])
                        for item in values if item.get("personTrackIds")
                    ]
                    seen_tracks: set[str] = set()
                    duplicate_track = False
                    for track_set in track_sets:
                        if seen_tracks & track_set:
                            duplicate_track = True
                            break
                        seen_tracks.update(track_set)
                    if duplicate_track:
                        continue
                    next_rows.append(values)
                    if len(next_rows) >= maximum_combinations:
                        break
                if len(next_rows) >= maximum_combinations:
                    break
            combinations = next_rows
            if not combinations:
                break
        for combination in combinations:
            clean = [{key: value for key, value in item.items() if key != "_groupPersonId"} for item in combination]
            start = max(_number(item.get("start")) for item in clean)
            end = min(_number(item.get("end")) for item in clean)
            grouped.append(_combine_person_group_matches(
                clean, person_ids=person_ids,
                title=("所有目标人物同时发言" if activity == "speaking" else "所有目标人物同时出现"),
                start=start, end=end,
            ))
    virtual_id = "person_target_group"
    remaining = [item for item in predicates if str(item.get("id") or "") not in member_ids]
    virtual = {
        "id": virtual_id,
        "kind": "person.speaking" if activity == "speaking" else "person.appearance",
        "value": "多人发言" if activity == "speaking" else "多人出现",
        "required": True,
    }
    relations: list[dict[str, Any]] = []
    for relation in query_plan.get("relations") or []:
        if not isinstance(relation, dict):
            continue
        updated = copy.deepcopy(relation)
        if str(updated.get("left")) in member_ids:
            updated["left"] = virtual_id
        if str(updated.get("right")) in member_ids:
            updated["right"] = virtual_id
        if updated.get("left") == updated.get("right"):
            continue
        if updated not in relations:
            relations.append(updated)
    collapsed_plan = copy.deepcopy(query_plan)
    collapsed_plan["predicates"] = [virtual, *remaining]
    collapsed_plan["relations"] = relations
    collapsed_plan.pop("personTarget", None)
    collapsed_plan["clarificationRequired"] = False
    collapsed_matches = {
        key: value for key, value in matches_by_predicate.items() if key not in member_ids
    }
    collapsed_matches[virtual_id] = grouped
    return collapsed_plan, collapsed_matches


def predicate_intent(parent: dict[str, Any], predicate: dict[str, Any]) -> dict[str, Any]:
    value = predicate_query_text(predicate)
    modality = predicate_modality(predicate)
    result = copy.deepcopy(parent)
    result.update({
        "query": value,
        "modalities": [modality] if modality else [],
        "includeRules": [value] if value else [],
        "entities": [str(predicate.get("entity"))] if predicate.get("entity") else [],
        "actions": [str(predicate.get("action"))] if predicate.get("action") else [],
        "speechQuotes": [value] if predicate.get("kind") == "speech.exact" else [],
        "speakerRefs": [str(predicate.get("speakerRef"))] if predicate.get("speakerRef") else [],
        "personRefs": (
            [] if predicate.get("kind") == "person.speaking"
            else [str(predicate.get("personRef"))] if predicate.get("personRef") else []
        ),
        "requestedCount": 24,
    })
    return result


def _interval(match: dict[str, Any]) -> tuple[float, float]:
    start = _number(match.get("start"))
    return start, max(start, _number(match.get("end"), start))


def _gap(left: tuple[float, float], right: tuple[float, float]) -> float:
    if left[1] < right[0]:
        return right[0] - left[1]
    if right[1] < left[0]:
        return left[0] - right[1]
    return 0.0


def _relation_holds(relation: dict[str, Any], left: dict[str, Any], right: dict[str, Any]) -> tuple[bool, float]:
    a, b = _interval(left), _interval(right)
    tolerance = max(0.0, _number(relation.get("toleranceSeconds"), .5))
    maximum_gap_value = relation.get("maximumGapSeconds")
    maximum_gap = _number(maximum_gap_value, -1.0)
    kind = str(relation.get("type") or "overlaps")
    gap = _gap(a, b)
    if kind == "overlaps":
        ok = gap <= tolerance
        quality = 1.0 if gap == 0 else max(0.0, 1.0 - gap / max(.001, tolerance))
    elif kind == "same_shot":
        shared = {
            str(value) for value in left.get("shotIds") or [] if str(value)
        } & {
            str(value) for value in right.get("shotIds") or [] if str(value)
        }
        ok = bool(shared)
        quality = 1.0 if ok else 0.0
    elif kind == "same_event":
        shared = {
            str(value) for value in left.get("eventIds") or [] if str(value)
        } & {
            str(value) for value in right.get("eventIds") or [] if str(value)
        }
        ok = bool(shared)
        quality = 1.0 if ok else 0.0
    elif kind == "responds_to":
        # Relation direction is question (left) -> response (right).  The
        # dialogue graph grounds response matches back to their prompt turns;
        # time proximity alone is deliberately insufficient.
        question_ids = {
            str(value) for value in left.get("dialogueTurnIds") or left.get("answerTurnIds") or []
            if str(value)
        }
        prompt_ids = {str(value) for value in right.get("promptTurnIds") or [] if str(value)}
        ok = bool(question_ids & prompt_ids)
        quality = 1.0 if ok else 0.0
    elif kind == "before":
        ordered_gap = b[0] - a[1]
        gap_ok = maximum_gap < 0 or ordered_gap <= maximum_gap
        ok = ordered_gap >= -tolerance and gap_ok
        quality = 1.0 if ordered_gap >= 0 and gap_ok else max(0.0, 1.0 - abs(ordered_gap) / max(.001, tolerance))
    elif kind == "after":
        ordered_gap = a[0] - b[1]
        gap_ok = maximum_gap < 0 or ordered_gap <= maximum_gap
        ok = ordered_gap >= -tolerance and gap_ok
        quality = 1.0 if ordered_gap >= 0 and gap_ok else max(0.0, 1.0 - abs(ordered_gap) / max(.001, tolerance))
    elif kind == "within":
        ok = maximum_gap >= 0 and gap <= maximum_gap
        quality = max(0.0, 1.0 - gap / max(.001, maximum_gap)) if ok else 0.0
    elif kind == "contains":
        ok = a[0] <= b[0] + tolerance and a[1] >= b[1] - tolerance
        quality = 1.0 if ok else 0.0
    elif kind == "during":
        ok = a[0] >= b[0] - tolerance and a[1] <= b[1] + tolerance
        quality = 1.0 if ok else 0.0
    else:
        ok = gap <= tolerance
        quality = 1.0 if ok else 0.0
    return ok, round(max(0.0, min(1.0, quality)), 4)


def _combined_interval(combo: dict[str, dict[str, Any]], relations: list[dict[str, Any]]) -> tuple[float, float]:
    values = [_interval(match) for match in combo.values()]
    if not values:
        return 0.0, 0.0
    sequential = any(
        item.get("type") in {"before", "after", "within", "responds_to"}
        for item in relations
    )
    if sequential:
        return min(value[0] for value in values), max(value[1] for value in values)
    start, end = max(value[0] for value in values), min(value[1] for value in values)
    return (start, end) if end > start else (min(value[0] for value in values), max(value[1] for value in values))


def temporal_join_matches(
    query_plan: dict[str, Any], matches_by_predicate: dict[str, list[dict[str, Any]]],
    *, coverage_completeness: float = 1.0, maximum_combinations: int = 240,
    scene_cuts: list[float] | None = None,
) -> list[dict[str, Any]]:
    if query_plan.get("clarificationRequired"):
        return []
    branches = [item for item in query_plan.get("branches") or [] if isinstance(item, dict)]
    if len(branches) > 1 or (len(branches) == 1 and branches[0].get("negativePredicateIds")):
        union: list[dict[str, Any]] = []
        predicates_by_id = {
            str(item.get("id") or ""): item
            for item in query_plan.get("predicates") or [] if isinstance(item, dict)
        }
        for branch in branches:
            positive_ids = {str(value) for value in branch.get("predicateIds") or []}
            negative_ids = {str(value) for value in branch.get("negativePredicateIds") or []}
            branch_plan = copy.deepcopy(query_plan)
            branch_plan.pop("branches", None)
            branch_plan["predicates"] = []
            for predicate_id in sorted(positive_ids | negative_ids):
                if predicate_id not in predicates_by_id:
                    continue
                predicate = copy.deepcopy(predicates_by_id[predicate_id])
                predicate["required"] = predicate_id in positive_ids
                branch_plan["predicates"].append(predicate)
            branch_plan["relations"] = [
                copy.deepcopy(item) for item in query_plan.get("relations") or []
                if str(item.get("left") or "") in positive_ids | negative_ids
                and str(item.get("right") or "") in positive_ids | negative_ids
            ]
            anchor_id = next(iter(sorted(positive_ids)), "")
            for negative_id in sorted(negative_ids):
                if not any(
                    item.get("type") == "not" and str(item.get("right") or "") == negative_id
                    for item in branch_plan["relations"]
                ):
                    branch_plan["relations"].append({
                        "type": "not", "left": anchor_id, "right": negative_id,
                        "toleranceSeconds": .5,
                    })
            union.extend(temporal_join_matches(
                branch_plan, matches_by_predicate,
                coverage_completeness=coverage_completeness,
                maximum_combinations=maximum_combinations,
                scene_cuts=scene_cuts,
            ))
        deduplicated: list[dict[str, Any]] = []
        for match in sorted(union, key=lambda item: (-_number(item.get("score")), _number(item.get("start")))):
            if any(
                abs(_number(match.get("start")) - _number(existing.get("start"))) < .08
                and abs(_number(match.get("end")) - _number(existing.get("end"))) < .08
                for existing in deduplicated
            ):
                continue
            deduplicated.append(match)
        return deduplicated
    if isinstance(query_plan.get("personTarget"), dict):
        collapsed_plan, collapsed_matches = _collapse_person_target_group(
            query_plan, matches_by_predicate,
            scene_cuts=scene_cuts, maximum_combinations=maximum_combinations,
        )
        return temporal_join_matches(
            collapsed_plan, collapsed_matches,
            coverage_completeness=coverage_completeness,
            maximum_combinations=maximum_combinations,
            scene_cuts=scene_cuts,
        )
    predicates = [item for item in query_plan.get("predicates") or [] if isinstance(item, dict)]
    relations = [item for item in query_plan.get("relations") or [] if isinstance(item, dict)]
    required = [item for item in predicates if item.get("required", True)]
    if not required:
        return []
    required.sort(key=lambda item: len(matches_by_predicate.get(str(item.get("id")), [])))
    anchor_id = str(required[0].get("id"))
    combinations: list[dict[str, dict[str, Any]]] = [
        {anchor_id: match} for match in matches_by_predicate.get(anchor_id, [])
    ]
    if not combinations:
        return []
    for predicate in required[1:]:
        predicate_id = str(predicate.get("id"))
        candidates = matches_by_predicate.get(predicate_id, [])
        next_combinations: list[dict[str, dict[str, Any]]] = []
        for combo in combinations:
            for candidate in candidates:
                linked = [
                    relation for relation in relations
                    if relation.get("type") != "not"
                    and {str(relation.get("left")), str(relation.get("right"))} <= {*combo.keys(), predicate_id}
                    and predicate_id in {str(relation.get("left")), str(relation.get("right"))}
                ]
                checks: list[tuple[bool, float]] = []
                for relation in linked:
                    left_id, right_id = str(relation.get("left")), str(relation.get("right"))
                    left = candidate if left_id == predicate_id else combo.get(left_id)
                    right = candidate if right_id == predicate_id else combo.get(right_id)
                    if left is not None and right is not None:
                        checks.append(_relation_holds(relation, left, right))
                # Unlinked required predicates are an invalid query plan, not
                # an implicit half-second overlap relation.
                if not checks:
                    continue
                if all(value[0] for value in checks):
                    next_combinations.append({**combo, predicate_id: candidate})
                    if len(next_combinations) >= maximum_combinations:
                        break
            if len(next_combinations) >= maximum_combinations:
                break
        combinations = next_combinations
        if not combinations:
            return []

    negative_relations = [item for item in relations if item.get("type") == "not"]
    filtered: list[dict[str, dict[str, Any]]] = []
    for combo in combinations:
        rejected = False
        for relation in negative_relations:
            left = combo.get(str(relation.get("left")))
            if left is None:
                continue
            for negative in matches_by_predicate.get(str(relation.get("right")), []):
                if _relation_holds({**relation, "type": "overlaps"}, left, negative)[0]:
                    rejected = True
                    break
            if rejected:
                break
        if not rejected:
            filtered.append(combo)

    results: list[dict[str, Any]] = []
    required_ids = {str(item.get("id")) for item in required}
    for combo in filtered:
        relation_qualities: list[float] = []
        for relation in relations:
            if relation.get("type") == "not":
                continue
            left, right = combo.get(str(relation.get("left"))), combo.get(str(relation.get("right")))
            if left is not None and right is not None:
                relation_qualities.append(_relation_holds(relation, left, right)[1])
        start, end = _combined_interval(combo, relations)
        refs: dict[tuple[str, str], dict[str, Any]] = {}
        modalities: list[str] = []
        for match in combo.values():
            modalities.extend(str(value) for value in match.get("matchedModalities") or [match.get("evidenceType")] if value)
            for ref in match.get("evidenceRefs") or []:
                if isinstance(ref, dict) and ref.get("id"):
                    refs[(str(ref.get("type") or ""), str(ref["id"]))] = copy.deepcopy(ref)
        retrieval = sum(_number(match.get("score")) for match in combo.values()) / max(1, len(combo)) / 100
        reliability = min((_number(match.get("confidence"), .5) for match in combo.values()), default=.5)
        boundary = min((_number(match.get("boundaryConfidence"), reliability) for match in combo.values()), default=reliability)
        temporal = min(relation_qualities, default=1.0)
        coverage = max(0.0, min(1.0, _number(coverage_completeness, 1.0)))
        predicate_coverage = len(required_ids & set(combo)) / max(1, len(required_ids))
        source_review_required = any(bool(match.get("requiresReview")) for match in combo.values())
        active_speaker_evidence = next((
            copy.deepcopy(match.get("activeSpeakerEvidence")) for match in combo.values()
            if isinstance(match.get("activeSpeakerEvidence"), dict)
        ), None)
        speakers = list(dict.fromkeys(
            str(value).strip()
            for match in combo.values()
            for value in [
                match.get("speaker"),
                (match.get("activeSpeakerEvidence") or {}).get("speaker")
                if isinstance(match.get("activeSpeakerEvidence"), dict) else None,
            ]
            if str(value or "").strip()
        ))
        # Coverage answers "did we scan everything?", not "is this candidate
        # relevant?". Keep it out of the relevance score so partial scans do
        # not inflate or suppress an otherwise grounded result.
        probability = (
            retrieval * .38 + reliability * .26 + predicate_coverage * .16
            + temporal * .10 + boundary * .10
        )
        source_tiers = {
            str(match.get("confidenceTier") or ("possible" if match.get("requiresReview") else "reliable"))
            for match in combo.values()
        }
        grounding_statuses = list(dict.fromkeys(
            str(value) for match in combo.values()
            for value in (
                match.get("groundingStatuses") or [match.get("groundingStatus")]
            ) if str(value)
        ))
        confidence_tier = (
            "reliable"
            if source_tiers == {"reliable"} and not source_review_required and probability >= .72
            else "possible"
        )
        predicate_results = [{
            "predicateId": predicate_id, "satisfied": predicate_id in combo,
            "evidenceIds": [str(ref.get("id")) for ref in combo.get(predicate_id, {}).get("evidenceRefs") or []],
        } for predicate_id in [str(item.get("id")) for item in predicates]]
        reason_parts = list(dict.fromkeys(
            str(match.get("reason") or "条件已验证").strip()
            for match in combo.values() if str(match.get("reason") or "").strip()
        )) or ["条件已验证"]
        evidence_parts = list(dict.fromkeys(
            str(match.get("matchedEvidence") or "").strip()
            for match in combo.values() if str(match.get("matchedEvidence") or "").strip()
        ))
        transcript_parts = list(dict.fromkeys(
            str(match.get("transcriptExcerpt") or "").strip()
            for match in combo.values() if str(match.get("transcriptExcerpt") or "").strip()
        ))
        matched_person_ids = list(dict.fromkeys(
            str(value) for match in combo.values()
            for value in match.get("matchedPersonIds") or [] if str(value)
        ))
        matched_person_labels = list(dict.fromkeys(
            str(value) for match in combo.values()
            for value in match.get("matchedPersonLabels") or [] if str(value)
        ))
        active_speaker_by_person = {
            str(key): copy.deepcopy(value)
            for match in combo.values()
            for key, value in (
                match.get("activeSpeakerEvidenceByPerson")
                if isinstance(match.get("activeSpeakerEvidenceByPerson"), dict) else {}
            ).items()
        }
        group_title = next((
            str(match.get("title") or "").strip() for match in combo.values()
            if (
                match.get("matchedPersonIds")
                or str(match.get("matchType") or "").startswith("dialogue_")
            ) and str(match.get("title") or "").strip()
        ), "")
        if group_title:
            result_title = group_title[:100]
        elif active_speaker_evidence:
            person_label = str(
                active_speaker_evidence.get("personLabel")
                or active_speaker_evidence.get("personId") or "目标人物"
            ).strip()[:48]
            result_title = f"{person_label}发言"
        else:
            predicate_labels = list(dict.fromkeys(
                _predicate_value(predicate).strip()[:32]
                for predicate in predicates
                if predicate.get("required", True) and _predicate_value(predicate).strip()
            ))
            if len(predicate_labels) > 1:
                relation_types = {str(item.get("type") or "") for item in relations}
                prefix = (
                    "同时出现" if relation_types & {"overlaps", "during", "contains", "same_shot", "same_event"}
                    else "先后发生" if relation_types & {"before", "after", "within"}
                    else "复合匹配"
                )
                result_title = f"{prefix}：{' + '.join(predicate_labels[:3])}"[:100]
            elif predicate_labels:
                result_title = predicate_labels[0][:100]
            else:
                result_title = "匹配片段"
        single_match = next(iter(combo.values())) if len(combo) == 1 else None
        calibrated = bool(combo) and all(bool(match.get("calibrated")) for match in combo.values())
        results.append({
            "id": f"match_{uuid.uuid4().hex[:12]}",
            "unitId": anchor_id,
            "matchedUnitIds": list(dict.fromkeys(
                str(value) for match in combo.values()
                for value in (match.get("matchedUnitIds") or [match.get("unitId")]) if value
            )),
            "matchedSegmentIds": list(dict.fromkeys(
                str(value) for match in combo.values() for value in match.get("matchedSegmentIds") or []
            )),
            "start": round(start, 3), "end": round(end, 3), "duration": round(max(0.0, end - start), 3),
            "startUs": int(round(start * 1_000_000)), "endUs": int(round(end * 1_000_000)),
            "sourceRange": {"startUs": int(round(start * 1_000_000)), "endUs": int(round(end * 1_000_000))},
            "title": result_title,
            "score": round(probability * 100, 1), "confidence": round(probability, 3),
            "retrievalScore": round(retrieval, 3),
            "evidenceConfidence": round(reliability, 3),
            "boundaryConfidence": round(boundary, 3),
            "scoreVersion": "content-score-v2-separated",
            "calibrated": calibrated,
            "confidenceTier": confidence_tier,
            "groundingStatus": "explicit" if "explicit" in grounding_statuses else "contextual",
            "groundingStatuses": grounding_statuses,
            "reason": "；".join(reason_parts)[:600],
            "matchedEvidence": "；".join(evidence_parts)[:500],
            "evidenceType": modalities[0] if len(set(modalities)) == 1 else "multimodal",
            "matchedModalities": list(dict.fromkeys(modalities)), "evidenceRefs": list(refs.values()),
            "evidenceItems": [
                copy.deepcopy(value)
                for match in combo.values() for value in (
                    match.get("evidenceItems") or [{
                        "type": ref.get("type"), "id": ref.get("id"),
                        "start": ref.get("start"), "end": ref.get("end"),
                        "supportLevel": match.get("groundingStatus") or "contextual",
                        "excerpt": match.get("matchedEvidence") or match.get("transcriptExcerpt") or "",
                    } for ref in match.get("evidenceRefs") or []]
                )
                if isinstance(value, dict)
            ][:40],
            "evidenceTimes": sorted({
                _number(value) for match in combo.values() for value in match.get("evidenceTimes") or []
            }),
            "transcriptExcerpt": " ".join(transcript_parts)[:800],
            "speaker": ", ".join(speakers)[:120] or None,
            "matchedPersonIds": matched_person_ids,
            "matchedPersonLabels": matched_person_labels,
            "activeSpeakerEvidenceByPerson": active_speaker_by_person,
            "speechUnits": [unit for match in combo.values() for unit in match.get("speechUnits") or []],
            "boundaryStatus": (
                str(single_match.get("boundaryStatus") or "condition_match")
                if single_match else "temporal_join"
            ),
            "boundarySource": (
                str(single_match.get("boundarySource") or "evidence")
                if single_match else "predicate_temporal_join"
            ),
            **({
                key: copy.deepcopy(single_match[key])
                for key in (
                    "targetSpeechRanges", "promptTurnIds", "answerTurnIds", "dialogueTurnIds",
                    "bridgedBackchannelTurnIds", "boundaryRevision", "boundaryDiagnostics",
                ) if key in single_match
            } if single_match else {}),
            "matchType": (
                "labeled_person_speaking" if active_speaker_evidence
                else "multi_predicate" if len(required_ids) > 1 else "predicate_match"
            ),
            "requiresReview": confidence_tier == "possible",
            "selected": confidence_tier == "reliable",
            "predicateResults": predicate_results,
            "temporalRelations": copy.deepcopy(relations),
            **({"activeSpeakerEvidence": active_speaker_evidence} if active_speaker_evidence else {}),
            "scores": {
                "retrievalRelevance": round(retrieval, 3), "predicateCoverage": round(predicate_coverage, 3),
                "evidenceReliability": round(reliability, 3), "temporalRelation": round(temporal, 3),
                "boundaryQuality": round(boundary, 3), "coverageCompleteness": round(coverage, 3),
            },
            "decision": {
                "matchProbability": round(probability, 3),
                "confidenceTier": confidence_tier,
                "reviewRequired": confidence_tier == "possible",
                "reviewReasons": [value for value in (
                    "证据目前只支持上下文关联" if source_tiers != {"reliable"} else "",
                    "证据强度尚未达到可靠结果阈值" if probability < .72 else "",
                    "片段边界精度有限" if boundary < .7 else "",
                ) if value],
            },
        })
    # Number repeated semantic titles in source order. Predicate satisfaction
    # remains available in diagnostics instead of leaking into every title.
    title_totals: dict[str, int] = {}
    for item in results:
        title = str(item.get("title") or "匹配片段")
        title_totals[title] = title_totals.get(title, 0) + 1
    title_positions: dict[str, int] = {}
    for item in sorted(results, key=lambda value: _number(value.get("start"))):
        title = str(item.get("title") or "匹配片段")
        if title_totals.get(title, 0) <= 1:
            continue
        title_positions[title] = title_positions.get(title, 0) + 1
        item["title"] = f"{title} · 第 {title_positions[title]} 段"[:100]
    results.sort(key=lambda item: (-_number(item.get("score")), _number(item.get("start"))))
    return results


def attach_result_coordinates_and_scores(
    matches: Iterable[dict[str, Any]], *, coverage_completeness: float = 1.0,
) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    for source in matches:
        match = copy.deepcopy(source)
        start, end = _interval(match)
        confidence = max(0.0, min(1.0, _number(match.get("confidence"), _number(match.get("score")) / 100)))
        boundary = max(0.0, min(1.0, _number(match.get("boundaryConfidence"), confidence)))
        retrieval = max(0.0, min(1.0, _number(match.get("score")) / 100))
        coverage = max(0.0, min(1.0, _number(coverage_completeness, 1.0)))
        probability = retrieval * .45 + confidence * .3 + boundary * .15 + coverage * .1
        review_status = str(match.get("reviewStatus") or "")
        existing_decision = match.get("decision") if isinstance(match.get("decision"), dict) else {}
        confidence_tier = str(
            match.get("confidenceTier") or existing_decision.get("confidenceTier")
            or ("possible" if match.get("requiresReview") or probability < .75 else "reliable")
        )
        if confidence_tier not in {"reliable", "possible"}:
            confidence_tier = "possible"
        review_required = confidence_tier == "possible" and review_status not in {"kept", "rejected"}
        match.update({
            "startUs": int(round(start * 1_000_000)), "endUs": int(round(end * 1_000_000)),
            "sourceRange": {"startUs": int(round(start * 1_000_000)), "endUs": int(round(end * 1_000_000))},
            "retrievalScore": round(retrieval, 3),
            "evidenceConfidence": round(confidence, 3),
            "boundaryConfidence": round(boundary, 3),
            "scoreVersion": "content-score-v2-separated",
            "calibrated": bool(match.get("calibrated", False)),
            "confidenceTier": confidence_tier,
            "requiresReview": review_required,
            "scores": match.get("scores") or {
                "retrievalRelevance": round(retrieval, 3), "predicateCoverage": 1.0,
                "evidenceReliability": round(confidence, 3), "temporalRelation": 1.0,
                "boundaryQuality": round(boundary, 3), "coverageCompleteness": round(coverage, 3),
            },
            "decision": {
                "matchProbability": round(probability, 3),
                "confidenceTier": confidence_tier,
                "reviewRequired": review_required,
                "reviewReasons": (
                    list(existing_decision.get("reviewReasons") or [])
                    if review_required else []
                ) or (["证据目前只支持可能相关"] if review_required else []),
            },
        })
        result.append(match)
    return result


def attach_match_context(
    matches: Iterable[dict[str, Any]], *, shots: Iterable[dict[str, Any]] = (),
    events: Iterable[dict[str, Any]] = (),
) -> list[dict[str, Any]]:
    """Attach deterministic source shot/event membership to candidate matches."""
    normalized_shots = [item for item in shots if isinstance(item, dict)]
    normalized_events = [item for item in events if isinstance(item, dict)]
    result: list[dict[str, Any]] = []
    for source in matches:
        match = copy.deepcopy(source)
        start, end = _interval(match)

        def memberships(rows: list[dict[str, Any]]) -> list[str]:
            values: list[str] = []
            for row in rows:
                row_start = _number(row.get("start"))
                row_end = max(row_start, _number(row.get("end"), row_start))
                if row_end <= start or row_start >= end:
                    continue
                value = str(
                    row.get("id") or row.get("shotId") or row.get("segmentId")
                    or row.get("eventId") or ""
                )
                if value:
                    values.append(value)
            return list(dict.fromkeys(values))

        match["shotIds"] = memberships(normalized_shots)
        match["eventIds"] = memberships(normalized_events)
        result.append(match)
    return result
