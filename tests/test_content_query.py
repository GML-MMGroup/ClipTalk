from __future__ import annotations

from app.content_query import (
    QUERY_PLAN_VERSION,
    attach_match_context,
    attach_result_coordinates_and_scores,
    compile_query_plan,
    predicate_intent,
    predicate_modality,
    predicate_query_text,
    predicate_retrieval_queries,
    temporal_join_matches,
)


def match(unit_id: str, start: float, end: float, modality: str, score: float = 90) -> dict:
    return {
        "id": f"match_{unit_id}", "unitId": unit_id, "matchedUnitIds": [unit_id],
        "start": start, "end": end, "score": score, "confidence": score / 100,
        "boundaryConfidence": .85, "evidenceType": modality, "matchedModalities": [modality],
        "evidenceRefs": [{"type": modality, "id": unit_id, "start": start, "end": end}],
        "reason": f"{unit_id} matched", "evidenceTimes": [(start + end) / 2],
    }


def test_compile_query_plan_preserves_structured_predicates_and_operations() -> None:
    plan = compile_query_plan({
        "query": "说到退款政策时拿着黄色电钻",
        "requestedCount": 3,
        "searchScope": {"start": 10, "end": 80},
        "predicates": [
            {"id": "speech", "kind": "speech.semantic", "value": "退款政策"},
            {"id": "drill", "kind": "visual.object", "entity": "电钻", "attributes": {"color": "黄色"}},
        ],
        "relations": [{"type": "overlaps", "left": "speech", "right": "drill", "toleranceUs": 2_000_000}],
    })
    assert [item["id"] for item in plan["predicates"]] == ["speech", "drill"]
    assert plan["relations"] == [{
        "type": "overlaps", "left": "speech", "right": "drill", "toleranceSeconds": 2.0,
    }]
    assert plan["scope"] == {"coordinate": "source", "startUs": 10_000_000, "endUs": 80_000_000}
    assert plan["requiredOperations"] == ["speech.semantic_search", "visual.detect_object"]


def test_temporal_join_requires_actual_overlap() -> None:
    plan = compile_query_plan({
        "predicates": [
            {"id": "p1", "kind": "speech.semantic", "value": "退款政策"},
            {"id": "p2", "kind": "visual.object", "value": "黄色电钻"},
        ],
        "relations": [{"type": "overlaps", "left": "p1", "right": "p2", "toleranceSeconds": 0}],
    })
    joined = temporal_join_matches(plan, {
        "p1": [match("speech_1", 120, 126, "speech"), match("speech_2", 280, 285, "speech")],
        "p2": [match("drill_1", 123, 130, "visual"), match("drill_2", 450, 456, "visual")],
    })
    assert len(joined) == 1
    assert (joined[0]["start"], joined[0]["end"]) == (123.0, 126.0)
    assert joined[0]["startUs"] == 123_000_000
    assert joined[0]["scores"]["predicateCoverage"] == 1.0
    assert {item["predicateId"] for item in joined[0]["predicateResults"]} == {"p1", "p2"}
    assert joined[0]["title"] == "同时出现：退款政策 + 黄色电钻"


def test_temporal_join_supports_after_with_maximum_gap() -> None:
    plan = compile_query_plan({
        "predicates": [
            {"id": "score", "kind": "screen_text.text", "value": "3:1"},
            {"id": "cheer", "kind": "audio.event", "value": "欢呼"},
        ],
        "relations": [{"type": "after", "left": "cheer", "right": "score", "maximumGapSeconds": 10}],
    })
    joined = temporal_join_matches(plan, {
        "score": [match("ocr_score", 20, 21, "ocr")],
        "cheer": [match("audio_near", 25, 27, "audio"), match("audio_far", 40, 42, "audio")],
    })
    assert len(joined) == 1
    assert (joined[0]["start"], joined[0]["end"]) == (20.0, 27.0)


def test_temporal_join_uses_person_label_and_numbers_repeated_speaking_clips() -> None:
    plan = compile_query_plan({
        "predicates": [
            {"id": "face", "kind": "person.appearance", "value": "绿衣哥", "personRef": "绿衣哥"},
            {"id": "talk", "kind": "person.speaking", "value": "绿衣哥说话", "personRef": "绿衣哥"},
        ],
        "relations": [{"type": "overlaps", "left": "face", "right": "talk"}],
    })
    first = match("speech_1", 1, 4, "person", 90)
    second = match("speech_2", 10, 13, "person", 95)
    for item in (first, second):
        item["speaker"] = "Speaker 2"
        item["activeSpeakerEvidence"] = {
            "personId": "person_2", "personLabel": "绿衣哥", "speaker": "Speaker 2",
        }
    joined = temporal_join_matches(plan, {
        "face": [first, second], "talk": [first, second],
    })
    titles_by_time = [item["title"] for item in sorted(joined, key=lambda item: item["start"])]
    assert titles_by_time == ["绿衣哥发言 · 第 1 段", "绿衣哥发言 · 第 2 段"]
    assert {item["speaker"] for item in joined} == {"Speaker 2"}


def test_temporal_join_supports_negative_predicate() -> None:
    plan = compile_query_plan({
        "predicates": [
            {"id": "music", "kind": "audio.semantic", "value": "背景音乐"},
            {"id": "speech", "kind": "speech.semantic", "value": "人声"},
        ],
        "relations": [{"type": "not", "left": "music", "right": "speech"}],
    })
    assert plan["predicates"][1]["required"] is False
    joined = temporal_join_matches(plan, {
        "music": [match("music_1", 0, 5, "audio"), match("music_2", 10, 15, "audio")],
        "speech": [match("speech_1", 1, 3, "speech")],
    })
    assert len(joined) == 1
    assert joined[0]["start"] == 10


def test_exact_predicate_fast_path_and_legacy_score_enrichment() -> None:
    plan = compile_query_plan({
        "query": "3:1", "modalities": ["ocr"], "requestedCount": 1,
    })
    assert plan["fastPathExact"] is True
    child = predicate_intent({"excludeRules": []}, plan["predicates"][0])
    assert child["modalities"] == ["ocr"]
    enriched = attach_result_coordinates_and_scores([match("ocr_1", 3.2, 4.6, "ocr")])
    assert enriched[0]["sourceRange"] == {"startUs": 3_200_000, "endUs": 4_600_000}
    assert enriched[0]["scores"]["predicateCoverage"] == 1.0


def test_person_speaking_requires_active_speaker_operation() -> None:
    plan = compile_query_plan({
        "query": "女嘉宾说话", "modalities": ["person", "speech"],
        "predicates": [{
            "id": "p1", "kind": "person.speaking", "value": "女嘉宾",
            "personRef": "女嘉宾", "required": True,
        }],
    })
    assert plan["requiredOperations"] == [
        "person.active_speaker_link", "person.track_face", "speech.semantic_search",
    ]
    assert predicate_modality(plan["predicates"][0]) == "speech"


def test_subject_constrained_speech_and_action_require_strict_attribution() -> None:
    plan = compile_query_plan({
        "predicates": [
            {
                "id": "speech", "kind": "speech.semantic", "value": "产品价格",
                "subjectPersonRef": "戴眼镜穿蓝衬衫的人",
            },
            {
                "id": "action", "kind": "visual.action", "value": "打开门",
                "subjectPersonRef": "戴眼镜穿蓝衬衫的人",
            },
        ],
        "relations": [{"type": "same_event", "left": "speech", "right": "action"}],
    })
    assert plan["schemaVersion"] == QUERY_PLAN_VERSION
    assert plan["predicates"][0]["subjectPersonRef"] == "戴眼镜穿蓝衬衫的人"
    assert {
        "person.track_face", "person.active_speaker_link", "person.verify_action_actor",
        "speech.semantic_search", "visual.verify_action",
    } <= set(plan["requiredOperations"])


def test_generic_subject_description_and_retrieval_variants_are_not_role_specific() -> None:
    plan = compile_query_plan({
        "query": "目标主题",
        "predicates": [{
            "id": "topic", "kind": "speech.semantic", "value": "目标主题",
            "concepts": ["概念甲", "概念乙"],
            "retrievalVariants": ["另一种表达"],
            "subject": {"description": "用户描述的任意角色", "identityPolicy": "context"},
        }],
    })
    predicate = plan["predicates"][0]
    assert predicate["subject"] == {"description": "用户描述的任意角色", "identityPolicy": "context"}
    assert predicate["concepts"] == ["概念甲", "概念乙"]
    assert "另一种表达" in predicate_query_text(predicate)
    assert "用户描述的任意角色" in predicate_query_text(predicate)
    assert predicate_retrieval_queries(predicate) == [
        "目标主题 用户描述的任意角色",
        "目标主题 用户描述的任意角色 概念甲",
        "目标主题 用户描述的任意角色 概念乙",
        "目标主题 用户描述的任意角色 另一种表达",
    ]
    assert "screen_text.fuzzy_search" not in plan["requiredOperations"]


def test_generic_subject_verify_stays_on_its_typed_evidence_source() -> None:
    plan = compile_query_plan({
        "query": "目标主题",
        "predicates": [{
            "id": "topic", "kind": "speech.semantic", "value": "目标主题",
            "subject": {"description": "另一个任意角色", "identityPolicy": "verify"},
        }],
    })
    assert plan["requiredOperations"] == ["speech.semantic_search"]


def test_exhaustive_plan_has_no_top_k_limit_and_uses_source_order() -> None:
    plan = compile_query_plan({
        "query": "绿衣哥说话", "resultMode": "exhaustive", "requestedCount": None,
        "predicates": [{
            "id": "talk", "kind": "person.speaking", "value": "绿衣哥说话",
            "personRef": "绿衣哥", "required": True,
        }],
    })
    assert plan["schemaVersion"] == QUERY_PLAN_VERSION
    assert plan["result"] == {
        "mode": "exhaustive", "limit": None, "pageSize": 50,
        "diversify": False, "order": "source",
    }


def test_person_speaking_subsumes_duplicate_appearance_predicate() -> None:
    plan = compile_query_plan({
        "predicates": [
            {"id": "face", "kind": "person.appearance", "value": "绿衣哥", "personRef": "绿衣哥"},
            {"id": "talk", "kind": "person.speaking", "value": "绿衣哥说话", "personRef": "绿衣哥"},
        ],
        "relations": [{"type": "overlaps", "left": "face", "right": "talk"}],
    })
    assert [item["id"] for item in plan["predicates"]] == ["talk"]
    assert plan["relations"] == []


def test_within_without_maximum_gap_requires_clarification_and_never_joins() -> None:
    plan = compile_query_plan({
        "predicates": [
            {"id": "a", "kind": "speech.semantic", "value": "退款"},
            {"id": "b", "kind": "visual.action", "value": "拿起产品"},
        ],
        "relations": [{"type": "within", "left": "a", "right": "b"}],
    })
    assert plan["clarificationRequired"] is True
    assert plan["validationErrors"][0]["code"] == "within_requires_maximum_gap"
    assert temporal_join_matches(plan, {
        "a": [match("a1", 1, 2, "speech")],
        "b": [match("b1", 1000, 1001, "visual")],
    }) == []


def test_same_shot_requires_shared_source_shot_id() -> None:
    plan = compile_query_plan({
        "predicates": [
            {"id": "a", "kind": "speech.semantic", "value": "退款"},
            {"id": "b", "kind": "visual.object", "value": "电钻"},
        ],
        "relations": [{"type": "same_shot", "left": "a", "right": "b"}],
    })
    contextual = attach_match_context(
        [match("a1", 1, 2, "speech"), match("b1", 2, 3, "visual")],
        shots=[
            {"id": "shot_1", "start": 0, "end": 2},
            {"id": "shot_2", "start": 2, "end": 4},
        ],
    )
    assert temporal_join_matches(plan, {"a": [contextual[0]], "b": [contextual[1]]}) == []
    contextual[1]["shotIds"] = ["shot_1"]
    assert len(temporal_join_matches(plan, {"a": [contextual[0]], "b": [contextual[1]]})) == 1


def test_unlinked_required_predicates_require_clarification() -> None:
    plan = compile_query_plan({
        "predicates": [
            {"id": "a", "kind": "speech.semantic", "value": "退款"},
            {"id": "b", "kind": "visual.object", "value": "电钻"},
        ],
        "relations": [],
    })
    assert plan["clarificationRequired"] is True
    assert plan["validationErrors"][0]["code"] == "unlinked_required_predicates"


def _person_match(person_id: str, label: str, start: float, end: float) -> dict:
    item = match(f"{person_id}_{start}", start, end, "person")
    item["activeSpeakerEvidence"] = {"personId": person_id, "personLabel": label}
    item["personTrackIds"] = [f"official_{person_id}_{start}"]
    return item


def _person_group_plan(*, activity: str, mode: str, speaking_relation: str = "dialogue_event") -> dict:
    kind = "person.speaking" if activity == "speaking" else "person.appearance"
    return compile_query_plan({
        "predicates": [
            {"id": "person_a", "kind": kind, "value": "人物 A", "personId": "person_1"},
            {"id": "person_b", "kind": kind, "value": "人物 B", "personId": "person_2"},
        ],
        "personTarget": {
            "personIds": ["person_1", "person_2"],
            "predicateIds": ["person_a", "person_b"],
            "matchMode": mode, "activity": activity,
            "speakingRelation": speaking_relation, "dialogueGapSeconds": 8,
        },
    })


def test_person_target_any_merges_and_orders_people_matches() -> None:
    plan = _person_group_plan(activity="appearance", mode="any")
    assert plan["clarificationRequired"] is False
    joined = temporal_join_matches(plan, {
        "person_a": [_person_match("person_1", "人物 A", 8, 10)],
        "person_b": [_person_match("person_2", "人物 B", 1, 3)],
    })
    assert [(item["start"], item["matchedPersonIds"]) for item in joined] == [
        (1.0, ["person_2"]), (8.0, ["person_1"]),
    ]


def test_person_target_all_appearance_requires_real_overlap() -> None:
    plan = _person_group_plan(activity="appearance", mode="all")
    joined = temporal_join_matches(plan, {
        "person_a": [_person_match("person_1", "人物 A", 1, 5)],
        "person_b": [_person_match("person_2", "人物 B", 3, 7)],
    })
    assert len(joined) == 1
    assert (joined[0]["start"], joined[0]["end"]) == (3.0, 5.0)
    assert joined[0]["matchedPersonIds"] == ["person_1", "person_2"]


def test_person_target_all_speaking_uses_eight_second_dialogue_events() -> None:
    plan = _person_group_plan(activity="speaking", mode="all")
    joined = temporal_join_matches(plan, {
        "person_a": [
            _person_match("person_1", "人物 A", 1, 2),
            _person_match("person_1", "人物 A", 20, 21),
        ],
        "person_b": [
            _person_match("person_2", "人物 B", 5, 6),
            _person_match("person_2", "人物 B", 30, 31),
        ],
    })
    assert len(joined) == 1
    assert (joined[0]["start"], joined[0]["end"]) == (1.0, 6.0)
    assert set(joined[0]["activeSpeakerEvidenceByPerson"]) == {"person_1", "person_2"}


def test_person_target_dialogue_event_splits_at_scene_cut_between_turns() -> None:
    plan = _person_group_plan(activity="speaking", mode="all")
    joined = temporal_join_matches(plan, {
        "person_a": [_person_match("person_1", "人物 A", 1, 2)],
        "person_b": [_person_match("person_2", "人物 B", 5, 6)],
    }, scene_cuts=[4.0])
    assert joined == []
