from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

from app.content_query import QUERY_PLAN_VERSION, compile_query_plan, temporal_join_matches
from app.content_search import (
    CONTENT_INTENT_PARSER_VERSION,
    content_query_cache_key,
    parse_content_intent,
)


def _match(start: float, end: float, modality: str) -> dict:
    return {
        "start": start, "end": end, "score": 90, "confidence": .9,
        "boundaryConfidence": .9, "calibrated": True,
        "reason": "证据匹配", "matchedEvidence": modality,
        "matchedModalities": [modality], "evidenceType": modality,
        "evidenceRefs": [{"id": f"{modality}_{start}", "type": modality}],
    }


def test_public_intent_gold_cases() -> None:
    path = Path(__file__).parents[1] / "benchmarks" / "intent-recognition-golden.jsonl"
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        case = json.loads(line)
        intent = parse_content_intent(case["instruction"], case["modelIntent"])
        kinds = [item["kind"] for item in intent["queryPlan"]["predicates"]]
        assert kinds == case["expectedKinds"], case["id"]
        assert intent["queryPlan"]["logic"]["op"] == case["expectedLogic"], case["id"]
        assert not intent["validationErrors"], case["id"]


def test_broad_multisource_is_executable_union() -> None:
    intent = parse_content_intent("找到和冰箱相关的片段", {
        "query": "冰箱", "retrievalScope": "broad_multisource",
        "predicates": [
            {"id": "v", "kind": "visual.semantic", "value": "冰箱", "required": True},
            {"id": "s", "kind": "speech.semantic", "value": "冰箱", "required": True},
            {"id": "o", "kind": "screen_text.text", "value": "冰箱", "required": True},
        ],
        "logic": {"op": "any", "children": [
            {"op": "predicate", "predicateId": "v"},
            {"op": "predicate", "predicateId": "s"},
            {"op": "predicate", "predicateId": "o"},
        ]},
    })
    plan = intent["queryPlan"]
    assert plan["schemaVersion"] == QUERY_PLAN_VERSION
    assert len(plan["branches"]) == 3
    assert "dialogue.turn_graph" not in plan["requiredOperations"]
    assert not any(value.startswith("person.") for value in plan["requiredOperations"])
    matches = temporal_join_matches(plan, {
        "v": [_match(1, 2, "visual")],
        "s": [_match(5, 6, "speech")],
        "o": [],
    })
    assert [(item["start"], item["end"]) for item in matches] == [(1.0, 2.0), (5.0, 6.0)]


def test_broad_multisource_accepts_typed_visual_action_branch() -> None:
    intent = parse_content_intent("查找有明确对白或关键动作的完整片段", {
        "query": "明确对白或关键动作", "retrievalScope": "broad_multisource",
        "predicates": [
            {"id": "s", "kind": "speech.semantic", "value": "明确对白", "required": True},
            {"id": "v", "kind": "visual.action", "value": "关键动作", "required": True},
            {"id": "o", "kind": "screen_text.text", "value": "关键文字", "required": True},
        ],
        "logic": {"op": "any", "children": [
            {"op": "predicate", "predicateId": "s"},
            {"op": "predicate", "predicateId": "v"},
            {"op": "predicate", "predicateId": "o"},
        ]},
    })
    assert not intent["validationErrors"]
    assert "visual.verify_action" in intent["queryPlan"]["requiredOperations"]


def test_concrete_object_action_does_not_expand_to_speech_and_ocr() -> None:
    intent = parse_content_intent("帮我找出来切西瓜的片段", {
        "query": "切西瓜", "retrievalScope": "broad_multisource",
        "predicates": [
            {
                "id": "v", "kind": "visual.semantic", "value": "切西瓜", "required": True,
                "subject": {"description": "西瓜", "type": "object"},
            },
            {
                "id": "s", "kind": "speech.semantic", "value": "切西瓜", "required": True,
                "subject": {"description": "西瓜", "type": "object"},
            },
            {
                "id": "o", "kind": "screen_text.text", "value": "切西瓜", "required": True,
                "subject": {"description": "西瓜", "type": "object"},
            },
        ],
        "logic": {"op": "any", "children": [
            {"op": "predicate", "predicateId": "v"},
            {"op": "predicate", "predicateId": "s"},
            {"op": "predicate", "predicateId": "o"},
        ]},
    })
    plan = intent["queryPlan"]
    assert [item["kind"] for item in plan["predicates"]] == ["visual.semantic"]
    assert plan["logic"] == {"op": "predicate", "predicateId": "v"}
    assert plan["requiredOperations"] == ["visual.embed"]
    assert intent["retrievalScope"] == "explicit_source"
    assert intent["modalities"] == ["visual"]


def test_abstract_topic_without_related_wording_remains_multisource() -> None:
    intent = parse_content_intent("找到糖尿病发作机理的片段", {
        "query": "糖尿病发作机理", "retrievalScope": "broad_multisource",
        "predicates": [
            {"id": "v", "kind": "visual.semantic", "value": "糖尿病发作机理", "subject": {"type": "topic"}},
            {"id": "s", "kind": "speech.semantic", "value": "糖尿病发作机理", "subject": {"type": "topic"}},
            {"id": "o", "kind": "screen_text.text", "value": "糖尿病发作机理", "subject": {"type": "topic"}},
        ],
        "logic": {"op": "any", "children": [
            {"op": "predicate", "predicateId": "v"},
            {"op": "predicate", "predicateId": "s"},
            {"op": "predicate", "predicateId": "o"},
        ]},
    })
    assert {item["kind"] for item in intent["queryPlan"]["predicates"]} == {
        "visual.semantic", "speech.semantic", "screen_text.text",
    }


def test_nested_any_all_and_not_are_executed() -> None:
    plan = compile_query_plan({
        "query": "复合条件",
        "predicates": [
            {"id": "a", "kind": "visual.semantic", "value": "A", "required": True},
            {"id": "b", "kind": "speech.semantic", "value": "B", "required": True},
            {"id": "c", "kind": "screen_text.text", "value": "C", "required": True},
            {"id": "d", "kind": "audio.event", "value": "D", "required": True},
        ],
        "logic": {"op": "any", "children": [
            {"op": "all", "children": [
                {"op": "predicate", "predicateId": "a"},
                {"op": "predicate", "predicateId": "b"},
                {"op": "not", "child": {"op": "predicate", "predicateId": "d"}},
            ]},
            {"op": "predicate", "predicateId": "c"},
        ]},
        "relations": [{"type": "overlaps", "left": "a", "right": "b"}],
    }, allow_fallback_predicates=False)
    assert not plan["validationErrors"]
    matches = temporal_join_matches(plan, {
        "a": [_match(1, 3, "visual"), _match(8, 10, "visual")],
        "b": [_match(2, 4, "speech"), _match(9, 11, "speech")],
        "c": [_match(15, 16, "ocr")],
        "d": [_match(1.5, 2.5, "audio")],
    })
    assert [(item["start"], item["end"]) for item in matches] == [(9.0, 10.0), (15.0, 16.0)]


def test_strict_schema_rejects_string_boolean_unknown_kind_and_bad_relation() -> None:
    plan = compile_query_plan({
        "query": "坏结构",
        "predicates": [
            {"id": "p1", "kind": "visual.semantic", "value": "目标", "required": "false"},
            {"id": "p2", "kind": "made.up", "value": "目标", "required": True},
        ],
        "relations": [{"type": "overlaps", "left": "p1", "right": "missing"}],
    }, allow_fallback_predicates=False)
    codes = {item["code"] for item in plan["validationErrors"]}
    assert {"invalid_boolean", "unknown_predicate_kind", "invalid_relation_endpoint"} <= codes


def test_screen_only_question_does_not_build_dialogue_graph() -> None:
    plan = compile_query_plan({
        "query": "画面中的题目",
        "predicates": [{
            "id": "q", "kind": "question.evidence", "value": "画面题目",
            "source": "screen", "required": True,
        }],
    }, allow_fallback_predicates=False)
    assert "screen_text.question_detect" in plan["requiredOperations"]
    assert "dialogue.turn_graph" not in plan["requiredOperations"]


def test_spoken_and_screen_question_predicates_collapse_to_one_union_source() -> None:
    intent = parse_content_intent("找出所有采访问题的片段", {
        "query": "采访问题", "resultMode": "exhaustive",
        "predicates": [
            {"id": "spoken", "kind": "question.evidence", "value": "口头采访问题", "source": "spoken", "required": True},
            {"id": "screen", "kind": "question.evidence", "value": "画面采访问题", "source": "screen", "required": True},
        ],
        "logic": {"op": "all", "children": [
            {"op": "predicate", "predicateId": "spoken"},
            {"op": "predicate", "predicateId": "screen"},
        ]},
    })
    predicates = intent["queryPlan"]["predicates"]
    assert len(predicates) == 1
    assert predicates[0]["source"] == "all"
    assert not intent["validationErrors"]


def test_semantic_role_does_not_enter_person_or_active_speaker_pipeline() -> None:
    from app import main as main_app

    decision = {
        "intent": parse_content_intent("找出医生讨论糖尿病发作机理的片段", {
            "query": "糖尿病发作机理",
            "predicates": [
                {
                    "id": "speech", "kind": "speech.semantic", "value": "糖尿病发作机理",
                    "subject": {"description": "医生", "type": "role", "identityPolicy": "context"},
                    "subjectPersonRef": "医生", "required": True,
                },
                {
                    "id": "person", "kind": "person.speaking", "value": "医生",
                    "personRef": "医生", "subject": {"description": "医生", "type": "role"},
                    "required": True,
                },
            ],
            "logic": {"op": "all", "children": [
                {"op": "predicate", "predicateId": "speech"},
                {"op": "predicate", "predicateId": "person"},
            ]},
        }),
        "_parserLlmCalls": 1,
    }
    intent = main_app._content_intent_from_decision(
        {"request": {}, "videoInfo": {"duration": 60}},
        "找出医生讨论糖尿病发作机理的片段", decision,
    )
    assert [item["kind"] for item in intent["queryPlan"]["predicates"]] == ["speech.semantic"]
    assert intent["queryPlan"]["requiredOperations"] == ["speech.semantic_search"]
    assert intent["modalities"] == ["speech"]


def test_progress_detail_is_generated_from_planned_operations() -> None:
    from app import main as main_app

    broad = compile_query_plan({
        "query": "冰箱",
        "predicates": [
            {"id": "v", "kind": "visual.semantic", "value": "冰箱"},
            {"id": "s", "kind": "speech.semantic", "value": "冰箱"},
            {"id": "o", "kind": "screen_text.text", "value": "冰箱"},
        ],
        "logic": {"op": "any", "children": [
            {"op": "predicate", "predicateId": "v"},
            {"op": "predicate", "predicateId": "s"},
            {"op": "predicate", "predicateId": "o"},
        ]},
    })
    detail = main_app._content_search_preparation_detail(broad)
    assert detail == "正在准备检索范围，并召回画面、对白和屏幕文字证据"
    assert "人物" not in detail

    person = compile_query_plan({
        "query": "人物 A 说话",
        "predicates": [{
            "id": "p", "kind": "person.speaking", "value": "人物 A",
            "personRef": "人物 A",
        }],
    })
    assert "人物发言" in main_app._content_search_preparation_detail(person)

    speech_progress = main_app._content_speech_progress_snapshot(.5, 1, 2, "recognizing")
    assert speech_progress["detail"] == "正在识别对白（1/2 个音频分块）"
    assert "说话人" not in speech_progress["detail"]


def test_structured_entities_are_not_stringified_and_cache_is_versioned() -> None:
    intent = parse_content_intent("找出冰箱画面", {
        "query": "冰箱", "entities": [{"description": "冰箱", "type": "object"}],
        "predicates": [{"id": "p1", "kind": "visual.object", "value": "冰箱", "required": True}],
    })
    assert intent["entities"] == [{"description": "冰箱", "type": "object"}]
    assert intent["parserVersion"] == CONTENT_INTENT_PARSER_VERSION
    first = content_query_cache_key("index", intent)
    changed = {**intent, "parserVersion": "legacy-parser"}
    assert first != content_query_cache_key("index", changed)


def test_invalid_first_parse_gets_one_automatic_repair() -> None:
    from app import main as main_app

    responses = [
        {
            "action": "content_search", "confidence": .9,
            "intent": {"query": "做饭", "predicates": [
                {"id": "p1", "kind": "visual.action", "value": "做饭", "required": "false"},
            ]},
        },
        {
            "action": "content_search", "confidence": .95,
            "intent": {
                "query": "做饭", "retrievalScope": "explicit_source",
                "predicates": [{"id": "p1", "kind": "visual.action", "value": "做饭", "required": True}],
                "logic": {"op": "predicate", "predicateId": "p1"},
            },
        },
    ]
    client = MagicMock()
    client.complete_json.side_effect = responses
    with patch.object(main_app, "create_llm_client_for_job", return_value=client):
        intent = main_app._parse_content_instruction(
            {"request": {"searchScopeKind": "all"}, "videoInfo": {"duration": 30}},
            "找出做饭的画面",
        )
    assert client.complete_json.call_count == 2
    assert intent["_parserLlmCalls"] == 2
    assert intent["executionPlan"]["intentRepair"]["succeeded"] is True
    assert "_clarification" not in intent
