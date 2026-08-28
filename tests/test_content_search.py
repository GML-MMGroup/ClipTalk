from __future__ import annotations

import copy
import re
import tempfile
import threading
import unittest
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from app.content_search import (
    CONTENT_INTENT_PARSER_VERSION,
    CONTENT_SEARCH_VERSION,
    annotate_subject_evidence,
    build_inverted_index,
    build_macro_chapters,
    content_query_cache_key,
    content_chat_router_prompt,
    content_matches_to_segments,
    content_evidence_plan,
    content_expansion_options,
    evaluate_content_search_cases,
    fallback_content_intent,
    local_recall,
    matches_from_ranked,
    merge_content_matches,
    merge_transcript_units,
    parse_content_chat_decision,
    parse_content_intent,
    resolve_search_scope,
    filter_units_to_scope,
    rank_chapters,
    rank_predicate_units,
    rank_units,
    select_candidate_units,
    visual_units_from_page,
)


class ContentIntentTests(unittest.TestCase):
    def test_instruction_count_overrides_default_search_limit(self) -> None:
        from app import main as main_app

        intent = main_app._content_intent_from_decision(
            {
                "request": {"searchScopeKind": "all", "searchResultLimit": 12},
                "videoInfo": {"duration": 82},
            },
            "找出最相关的3个煎蛋或装盘片段",
            {
                "capabilityProposal": {"capabilities": ["visual"]},
                "intent": {
                    "action": "extract_content", "query": "煎蛋或装盘",
                    "resultMode": "top_k", "requestedCount": 3,
                    "predicates": [{"id": "action", "kind": "visual.action", "value": "煎蛋或装盘"}],
                    "logic": {"op": "predicate", "predicateId": "action"},
                    "relations": [],
                },
            },
            authorized_capabilities=["visual"],
        )
        self.assertEqual(intent["resultMode"], "top_k")
        self.assertEqual(intent["requestedCount"], 3)
        self.assertEqual(intent["queryPlan"]["result"]["limit"], 3)

    def test_full_source_scope_does_not_allow_model_to_force_exhaustive_scan(self) -> None:
        from app import main as main_app

        intent = main_app._content_intent_from_decision(
            {
                "request": {"searchScopeKind": "all", "searchResultLimit": 12},
                "videoInfo": {"duration": 542.5},
            },
            "找到鹦鹉的片段",
            {
                "capabilityProposal": {"capabilities": ["visual"]},
                "intent": {
                    "action": "extract_content", "query": "鹦鹉",
                    "resultMode": "exhaustive", "requestedCount": None,
                    "predicates": [{
                        "id": "object", "kind": "visual.object", "value": "鹦鹉",
                    }],
                    "logic": {"op": "predicate", "predicateId": "object"},
                    "relations": [],
                },
            },
            authorized_capabilities=["visual"],
        )

        self.assertEqual(intent["searchScope"]["kind"], "all")
        self.assertEqual(intent["resultMode"], "top_k")
        self.assertEqual(intent["queryPlan"]["result"]["mode"], "top_k")

    def test_contextual_visual_actor_does_not_require_person_target(self) -> None:
        from app import main as main_app

        intent = main_app._content_intent_from_decision(
            {"request": {"searchScopeKind": "all"}, "videoInfo": {"duration": 82}},
            "查找女子煎蛋的完整片段",
            {
                "capabilityProposal": {"capabilities": ["person", "visual"]},
                "intent": {
                    "action": "extract_content", "query": "女子煎蛋",
                    "predicates": [{
                        "id": "action", "kind": "visual.action", "value": "女子煎蛋",
                        "subject": {"description": "女子", "type": "person", "identityPolicy": "context"},
                        "subjectPersonRef": "anonymous:woman", "required": True,
                    }],
                    "logic": {"op": "predicate", "predicateId": "action"},
                    "relations": [],
                },
            },
            authorized_capabilities=["visual"],
        )

        predicate = intent["queryPlan"]["predicates"][0]
        self.assertNotIn("subjectPersonRef", predicate)
        self.assertEqual(intent["modalities"], ["visual"])
        self.assertNotIn("person.track_face", intent["queryPlan"]["requiredOperations"])
        self.assertNotIn("_clarification", intent)

    def test_continuous_actions_do_not_invent_same_event_index_requirement(self) -> None:
        from app import main as main_app

        instruction = "查找煎蛋、把煎蛋盛到盘子并淋上调味汁的完整连续动作"
        intent = main_app._content_intent_from_decision(
            {"request": {"searchScopeKind": "all"}, "videoInfo": {"duration": 180}},
            instruction,
            {
                "capabilityProposal": {"capabilities": ["visual"]},
                "intent": {
                    "action": "extract_content", "query": instruction,
                    "predicates": [
                        {"id": "cook", "kind": "visual.action", "value": "煎蛋"},
                        {"id": "plate", "kind": "visual.action", "value": "把煎蛋盛到盘子并淋上调味汁"},
                    ],
                    "relations": [
                        {"type": "same_event", "left": "cook", "right": "plate"},
                        {"type": "after", "left": "cook", "right": "plate"},
                    ],
                    "logic": {"op": "all", "children": [
                        {"op": "predicate", "predicateId": "cook"},
                        {"op": "predicate", "predicateId": "plate"},
                    ]},
                },
            },
            authorized_capabilities=["visual"],
        )

        self.assertEqual(len(intent["queryPlan"]["predicates"]), 1)
        self.assertTrue(intent["predicates"][0]["compositeAction"])
        self.assertEqual(intent["queryPlan"]["relations"], [])
        self.assertNotIn("timeline.event_boundary", intent["queryPlan"]["requiredOperations"])
        self.assertNotIn("_clarification", intent)

    def test_explicit_same_event_relation_is_preserved(self) -> None:
        from app import main as main_app

        raw = {
            "predicates": [
                {"id": "a", "kind": "visual.action", "value": "开门"},
                {"id": "b", "kind": "visual.action", "value": "入座"},
            ],
            "relations": [{"type": "same_event", "left": "a", "right": "b"}],
        }
        normalized = main_app._normalize_unrequested_strict_relations(raw, "找同一事件里开门并入座")
        self.assertEqual(len(normalized["predicates"]), 2)
        self.assertEqual(normalized["relations"][0]["type"], "same_event")

    def test_coverage_snapshot_uses_verified_units_not_evaluated_total(self) -> None:
        from app import main as main_app

        snapshot = main_app.content_search_coverage_snapshot({
            "id": "search_1", "coverageComplete": False,
            "retrievalStats": {
                "unitTotal": 497, "rerankUnitCount": 160,
                "semanticVerifiedUnitCount": 160,
            },
            "completeness": {"status": "incomplete", "evaluatedUnitCount": 497, "channels": []},
        })
        self.assertEqual(snapshot["semantic"], {"completed": 160, "total": 497, "percent": 32.2})
        self.assertIsNone(snapshot["overallPercent"])

    def test_subject_evidence_is_generic_and_keeps_unverified_matches(self) -> None:
        match = {
            "start": 2, "end": 5, "transcriptExcerpt": "这段内容讨论目标主题",
            "requiresReview": False,
        }
        annotate_subject_evidence(match, {
            "kind": "speech.semantic", "value": "目标主题",
            "subject": {"description": "任意角色", "identityPolicy": "context"},
        })
        self.assertEqual(match["subjectDescription"], "任意角色")
        self.assertEqual(match["subjectStatus"], "unverified")
        self.assertIn("subjectEvidence", match)

    def test_subject_context_can_be_grounded_by_overlapping_index_text(self) -> None:
        match = {"start": 2, "end": 5, "transcriptExcerpt": "目标主题", "requiresReview": False}
        annotate_subject_evidence(match, {
            "kind": "speech.semantic", "value": "目标主题",
            "subject": {"description": "任意角色", "identityPolicy": "context"},
        }, supporting_units=[{
            "id": "ocr_1", "start": 3, "end": 4, "text": "任意角色",
            "confidence": .91,
        }])
        self.assertEqual(match["subjectStatus"], "contextual")
        self.assertEqual(match["subjectEvidence"][0]["source"], "screen_or_index_context")

    def test_chat_router_retrieves_relevant_old_messages_and_late_candidates(self) -> None:
        messages = [{
            "id": f"msg_{index}", "role": "user", "kind": "message",
            "text": f"普通消息 {index}",
        } for index in range(16)]
        messages[0].update({
            "kind": "request",
            "text": "开头要求" + "甲" * 360 + "永久保留蓝色规则",
        })
        candidates = [{
            "id": f"match_{index}", "title": f"候选 {index}",
            "start": index, "end": index + 1,
            "transcriptExcerpt": "目标完整证据" if index == 17 else "普通证据",
        } for index in range(25)]
        prompt = content_chat_router_prompt(
            "继续按蓝色规则处理 match_17",
            current_search={"id": "search_1", "candidates": candidates},
            recent_messages=messages,
        )
        self.assertIn("永久保留蓝色规则", prompt)
        self.assertIn("目标完整证据", prompt)
        self.assertIn('"position": 25', prompt)

    def test_talknet_boundaries_cannot_expand_to_a_coarse_speaker_window(self) -> None:
        from app import main as main_app

        matches = main_app._talknet_rows_to_matches({
            "modelVersion": "pretrain_TalkSet.model",
            "coverageComplete": True,
            "matches": [{
                "start": 69.96, "end": 75.16, "score": .91,
                "evidenceTimes": [69.96, 71.0, 73.0, 75.0], "trackIds": ["face_1"],
            }],
        }, {
            "id": "person_1", "label": "人物 A",
        }, [
            {
                "id": "speech_wrong", "start": 2.06, "end": 37.7,
                "text": "主持人与嘉宾的多轮对白", "speakers": ["Speaker 1"],
            },
            {
                "id": "speech_right", "start": 68.85, "end": 75.36,
                "text": "目标人物发言", "speakers": ["Speaker 1"],
                "segments": [{
                    "id": "segment_right", "start": 69.8, "end": 75.2,
                    "text": "目标人物发言", "speaker": "Speaker 1",
                }],
            },
        ])

        self.assertEqual(len(matches), 1)
        self.assertEqual((matches[0]["start"], matches[0]["end"]), (69.96, 75.16))
        self.assertEqual(matches[0]["boundarySource"], "active_speaker_asd")
        self.assertNotIn("主持人", matches[0]["transcriptExcerpt"])

    def test_person_speaking_guard_rejects_diarization_only_boundaries(self) -> None:
        from app import main as main_app

        coarse = {
            "start": 2.06, "end": 37.7,
            "boundarySource": "diarization_speaker_segments",
            "activeSpeakerEvidence": {
                "associationMethod": "active_speaker_talknet",
                "evidenceTimes": [69.96],
            },
        }
        grounded = {
            "start": 69.96, "end": 75.16,
            "boundarySource": "active_speaker_asd",
            "evidenceTimes": [69.96, 71.0, 73.0, 75.0],
            "activeSpeakerEvidence": {
                "associationMethod": "active_speaker_talknet",
                "evidenceTimes": [69.96, 71.0, 73.0, 75.0],
            },
        }

        filtered = main_app._grounded_person_speaking_matches([coarse, grounded])

        self.assertEqual(len(filtered), 1)
        self.assertEqual((filtered[0]["start"], filtered[0]["end"]), (69.96, 75.16))

    def test_mixed_speaker_unit_is_trimmed_to_the_calibrated_speaker(self) -> None:
        from app import main as main_app

        match = {
            "start": 37.4, "end": 45.27, "duration": 7.87,
            "speechUnits": [
                {"id": "s1", "start": 37.4, "end": 37.7, "speaker": "Speaker 1", "text": "说。"},
                {"id": "s2", "start": 37.83, "end": 45.27, "speaker": "Speaker 2", "text": "到变化……"},
            ],
            "evidenceRefs": [{"type": "speech", "id": "u1", "start": 37.4, "end": 45.27}],
        }

        trimmed = main_app._trim_match_to_speaker_segments(match, "Speaker 1")

        self.assertIsNotNone(trimmed)
        self.assertEqual((trimmed["start"], trimmed["end"]), (37.4, 37.7))
        self.assertEqual(trimmed["matchedSegmentIds"], ["s1"])
        self.assertEqual(trimmed["transcriptExcerpt"], "说。")

    def test_user_confirmed_speaker_timeline_is_materialized_without_asd(self) -> None:
        from app import main as main_app

        matches = main_app._direct_user_confirmed_speaker_matches({
            "id": "person_1", "label": "人物 A", "primarySpeaker": "Speaker 1",
            "speakerAssociationMethod": "active_speaker_user_confirmed",
        }, [
            {"id": "s1", "start": 1.0, "end": 2.0, "text": "你好", "speakers": ["Speaker 1"]},
            {"id": "s2", "start": 2.2, "end": 3.0, "text": "继续", "speaker": "Speaker 1"},
            {"id": "s3", "start": 4.0, "end": 5.0, "text": "其他人", "speaker": "Speaker 2"},
        ], scope_start=0, scope_end=6)

        self.assertEqual(len(matches), 1)
        self.assertEqual(matches[0]["speaker"], "Speaker 1")
        self.assertEqual(matches[0]["boundarySource"], "user_confirmed_speaker_timeline")
        self.assertEqual(matches[0]["matchedSegmentIds"], ["s1", "s2"])
        self.assertEqual(len(main_app._grounded_person_speaking_matches(matches)), 1)

    def test_structured_predicates_and_relations_are_preserved_in_query_plan(self) -> None:
        intent = parse_content_intent("说退款政策时拿着黄色电钻", {
            "action": "extract_content", "query": "退款政策和黄色电钻",
            "modalities": ["speech", "visual"],
            "predicates": [
                {"id": "p1", "kind": "speech.semantic", "value": "退款政策"},
                {"id": "p2", "kind": "visual.object", "entity": "电钻", "attributes": {"color": "黄色"}},
            ],
            "relations": [{"type": "overlaps", "left": "p1", "right": "p2", "toleranceUs": 2000000}],
        })
        self.assertEqual([item["id"] for item in intent["queryPlan"]["predicates"]], ["p1", "p2"])
        self.assertEqual(intent["queryPlan"]["relations"][0]["type"], "overlaps")
        self.assertEqual(intent["queryPlan"]["relations"][0]["toleranceSeconds"], 2.0)

    def test_llm_chat_decision_is_validated_without_keyword_routing(self) -> None:
        discussion = parse_content_chat_decision("做饭属于家务吗？", {
            "action": "editorial_discussion", "confidence": .96,
            "answer": "一般属于。", "capabilityProposal": {"capabilities": []},
        })
        self.assertEqual(discussion["action"], "editorial_discussion")
        search = parse_content_chat_decision("帮我定位那一段", {
            "action": "content_search", "confidence": .91,
            "capabilityProposal": {
                "capabilities": ["visual"], "capabilityBasis": "explicit_user",
                "explicitEvidenceQuotes": ["并不存在于原文"],
            },
            "intent": {
                "action": "extract_content", "query": "那一段", "modalities": ["visual"],
                "predicates": [{"id": "p1", "kind": "visual.semantic", "value": "那一段"}],
            },
        })
        self.assertEqual(search["action"], "content_search")
        self.assertEqual(search["capabilityProposal"]["capabilityBasis"], "inferred")

    def test_low_confidence_does_not_override_llm_action(self) -> None:
        decision = parse_content_chat_decision("那后面呢", {
            "action": "content_search", "confidence": .62,
            "capabilityProposal": {"capabilities": ["speech"], "capabilityBasis": "inferred"},
            "intent": {
                "action": "extract_content", "query": "后面的内容", "modalities": ["speech"],
                "predicates": [{"id": "p1", "kind": "speech.semantic", "value": "后面的内容"}],
            },
        })
        self.assertEqual(decision["action"], "content_search")
        self.assertEqual(decision["confidence"], .62)

    def test_llm_selected_clarification_is_authoritative(self) -> None:
        decision = parse_content_chat_decision("那后面呢", {
            "action": "clarification", "confidence": .41,
            "clarificationQuestion": "你指的是当前片段之后，还是整条视频后半段？",
        })
        self.assertEqual(decision["action"], "clarification")
        self.assertIn("当前片段之后", decision["clarificationQuestion"])

    def test_invalid_llm_search_structure_requires_clarification(self) -> None:
        decision = parse_content_chat_decision("找相关片段", {
            "action": "content_search", "confidence": .99,
            "capabilityProposal": {"capabilities": ["speech"], "capabilityBasis": "inferred"},
            "intent": {"action": "extract_content", "query": "相关内容", "modalities": ["speech"]},
        })
        self.assertEqual(decision["action"], "clarification")
        self.assertIn("missing_predicates", {
            item["code"] for item in decision["validationErrors"]
        })

    def test_relation_role_intent_is_preserved_from_llm_without_code_rewrite(self) -> None:
        decision = parse_content_chat_decision("找到回答问题的人的片段", {
            "action": "content_search", "confidence": .72,
            "capabilityProposal": {
                "capabilities": ["speech"], "capabilityBasis": "explicit_user",
                "explicitEvidenceQuotes": ["回答问题"],
            },
            "intent": {
                "action": "extract_content", "query": "受访者的作答内容",
                "modalities": ["speech"],
                "predicates": [{
                    "id": "role_turn", "kind": "speech.semantic",
                    "value": "受访者针对问题进行作答或回应", "required": True,
                }],
            },
        })
        self.assertEqual(decision["action"], "content_search")
        intent = decision["intent"]
        self.assertEqual(
            intent["queryPlan"]["predicates"][0]["value"],
            "受访者针对问题进行作答或回应",
        )
        self.assertEqual(intent["personRefs"], [])

    def test_editing_route_preserves_only_supported_proposal_operations(self) -> None:
        decision = parse_content_chat_decision("把第二个镜头放前面", {
            "action": "editing_action", "confidence": .96,
            "editProposal": {
                "title": "调整镜头顺序", "summary": "第二个镜头提前。",
                "operations": [
                    {"type": "reorder_segments", "groupId": "event_1", "segmentIds": ["shot_2", "shot_1"]},
                    {"type": "invent_transition", "name": "magic"},
                ],
            },
        })
        self.assertEqual(decision["action"], "editing_action")
        self.assertEqual(decision["editProposal"]["title"], "调整镜头顺序")
        self.assertEqual([item["type"] for item in decision["editProposal"]["operations"]], ["reorder_segments"])

    def test_full_source_highlight_is_not_parsed_as_current_candidate_compose(self) -> None:
        decision = parse_content_chat_decision("把整个视频提取出30s的高光片段", {
            "action": "highlight_generation", "confidence": .98,
            "reason": "用户要求重新分析整个源视频",
            "highlightRequest": {"targetSeconds": 30, "theme": "", "scope": "all"},
            "editProposal": {
                "operations": [{"type": "compose", "matchIds": ["match_old"]}],
            },
        })
        self.assertEqual(decision["action"], "highlight_generation")
        self.assertEqual(decision["highlightRequest"]["targetSeconds"], 30)
        self.assertEqual(decision["highlightRequest"]["scope"], "all")
        self.assertEqual(decision["editProposal"]["operations"], [])

    def test_highlight_replan_preserves_duration_and_discards_edit_operations(self) -> None:
        decision = parse_content_chat_decision("重新生成为90s的高光视频", {
            "action": "highlight_replan", "confidence": .97,
            "reason": "复用当前高光任务的已有证据重新规划",
            "highlightRequest": {"targetSeconds": 90, "variantCount": 2, "scope": "all"},
            "editProposal": {"operations": [{"type": "compose", "groupIds": ["event_old"]}]},
        })
        self.assertEqual(decision["action"], "highlight_replan")
        self.assertEqual(decision["highlightRequest"]["targetSeconds"], 90)
        self.assertEqual(decision["highlightRequest"]["variantCount"], 2)
        self.assertEqual(decision["editProposal"]["operations"], [])

    def test_router_guard_corrects_full_source_highlight_misclassified_as_compose(self) -> None:
        decision = parse_content_chat_decision("把整个视频提取出30s的高光片段", {
            "action": "editing_action", "confidence": .9,
            "editProposal": {
                "title": "30秒高光", "operations": [
                    {"type": "compose", "matchIds": ["match_current"]},
                ],
            },
        })
        self.assertEqual(decision["action"], "highlight_generation")
        self.assertEqual(decision["highlightRequest"]["targetSeconds"], 30)
        self.assertEqual(decision["editProposal"]["operations"], [])

    def test_cross_search_assembly_is_not_reduced_to_current_search_compose(self) -> None:
        decision = parse_content_chat_decision("把所有检索结果合并", {
            "action": "editing_action", "confidence": .91,
            "editProposal": {"operations": [
                {"type": "compose", "matchIds": ["match_current"]},
            ]},
        })
        self.assertEqual(decision["action"], "content_assembly")
        self.assertTrue(decision["assemblyRequest"]["includeAllSearches"])
        self.assertEqual(decision["editProposal"]["operations"], [])

    def test_evidence_plan_does_not_infer_capabilities_from_language(self) -> None:
        for text in (
            "找出 Speaker 1 提到离线功能的发言",
            "找出屏幕显示产品型号的部分",
            "找出画面中打开红色盒子的动作",
        ):
            plan = content_evidence_plan(text)
            self.assertTrue(plan["clarificationRequired"])
            self.assertEqual(plan["allowedCapabilities"], [])

    def test_question_search_cannot_be_mutated_into_dialogue_mode(self) -> None:
        from app import main as main_app

        job_id = "question-dialogue-guard"
        main_app.jobs[job_id] = {
            "id": job_id,
            "taskMode": "content_extract",
            "contentSearch": {
                "id": "question-search",
                "intent": {
                    "queryPlan": {"predicates": [{
                        "id": "q", "kind": "question.evidence", "value": "采访问题",
                    }]},
                },
            },
        }
        try:
            with self.assertRaises(main_app.HTTPException) as context:
                main_app.update_content_search_dialogue_mode(
                    job_id,
                    main_app.ContentSearchDialogueModeRequest(
                        searchId="question-search", dialogueMode="qa_pair",
                    ),
                )
            self.assertEqual(context.exception.status_code, 409)
            self.assertIn("只包含问题片段", str(context.exception.detail))
        finally:
            main_app.jobs.pop(job_id, None)

    def test_ambiguous_evidence_plan_requires_confirmation(self) -> None:
        plan = content_evidence_plan("找出介绍产品功能的部分")
        self.assertTrue(plan["clarificationRequired"])
        self.assertEqual(plan["allowedCapabilities"], [])
        self.assertEqual(plan["clarification"]["kind"], "evidence_type")

    def test_user_confirmation_is_an_authorization_boundary(self) -> None:
        plan = content_evidence_plan(
            "找出介绍产品功能的部分", evidence_mode="screen_text",
            allowed_capabilities=["ocr", "visual"],
        )
        self.assertFalse(plan["clarificationRequired"])
        self.assertEqual(plan["allowedCapabilities"], ["ocr"])

    def test_no_match_expansion_does_not_auto_authorize_capabilities(self) -> None:
        options = content_expansion_options(["speech"], scope_is_narrow=True)
        self.assertEqual([item["id"] for item in options], ["add_ocr", "add_visual", "expand_scope"])
        self.assertNotIn("speech", [value for item in options for value in item.get("addCapabilities", [])])

    def test_fallback_only_keeps_deterministic_quantity_and_output_modifiers(self) -> None:
        intent = fallback_content_intent(
            "把 Speaker 2 介绍产品功能的发言截出来，不要价格部分，分别导出 3 段"
        )
        self.assertEqual(intent["schemaVersion"], CONTENT_SEARCH_VERSION)
        self.assertEqual(intent["action"], "extract_content")
        self.assertEqual(intent["modalities"], [])
        self.assertEqual(intent["speakerRefs"], [])
        self.assertEqual(intent["excludeRules"], [])
        self.assertEqual(intent["requestedCount"], 3)
        self.assertEqual(intent["assemblyMode"], "separate_events")

    def test_model_output_is_normalized_without_accepting_timecodes(self) -> None:
        intent = parse_content_intent("找出打开红色盒子的画面", {
            "action": "extract_content",
            "query": "打开红色盒子",
            "modalities": ["visual", "invalid"],
            "predicates": [{"id": "p1", "kind": "visual.action", "value": "打开红色盒子"}],
            "requestedCount": 99,
            "start": 123,
            "end": 456,
        })
        self.assertEqual(intent["modalities"], ["visual"])
        self.assertEqual(intent["requestedCount"], 99)
        self.assertNotIn("start", intent)
        self.assertNotIn("end", intent)

    def test_unspecified_result_count_defaults_to_ranked_retrieval(self) -> None:
        intent = fallback_content_intent("找出和冰箱相关的片段")
        self.assertEqual(intent["resultMode"], "top_k")
        self.assertIsNone(intent["requestedCount"])

    def test_explicit_completeness_wording_uses_exhaustive_retrieval(self) -> None:
        intent = fallback_content_intent("找出所有和冰箱相关的片段，不要遗漏")
        self.assertEqual(intent["resultMode"], "exhaustive")
        self.assertIsNone(intent["requestedCount"])

    def test_explicit_large_result_count_is_not_silently_clamped_to_twelve(self) -> None:
        intent = fallback_content_intent("找出 80 段相关内容")
        self.assertEqual(intent["resultMode"], "top_k")
        self.assertEqual(intent["requestedCount"], 80)

    def test_parser_does_not_infer_modalities_from_refs_or_actions(self) -> None:
        intent = parse_content_intent("找 Speaker 2 打开盒子的部分", {
            "action": "extract_content", "query": "打开盒子", "modalities": ["person"],
            "speakerRefs": ["Speaker 2"], "actions": ["打开"],
            "predicates": [{"id": "p1", "kind": "visual.action", "value": "打开盒子"}],
        })
        self.assertEqual(intent["modalities"], ["person"])

    def test_fallback_does_not_classify_existing_output_adjustments(self) -> None:
        intent = fallback_content_intent("第 1 条结尾提前 3 秒")
        self.assertEqual(intent["action"], "extract_content")

    def test_fallback_does_not_enable_any_semantic_modality(self) -> None:
        intent = fallback_content_intent("找出和离线功能相关的内容")
        self.assertEqual(intent["modalities"], [])

    def test_screen_text_words_do_not_bypass_llm_capability_selection(self) -> None:
        intent = fallback_content_intent("找出屏幕文字出现产品型号的部分")
        self.assertEqual(intent["modalities"], [])

    def test_explicit_ui_capability_combination_is_preserved(self) -> None:
        plan = content_evidence_plan(
            "ignored by authorization parser", evidence_mode="mixed",
            allowed_capabilities=["visual", "person", "speech"],
        )
        self.assertFalse(plan["clarificationRequired"])
        self.assertEqual(set(plan["allowedCapabilities"]), {"visual", "person", "speech"})

    def test_visible_object_words_do_not_enable_any_modality_without_llm(self) -> None:
        intent = fallback_content_intent("找出红色汽车出现的部分")
        self.assertEqual(intent["modalities"], [])

    def test_named_and_natural_time_ranges_are_intersected(self) -> None:
        scoped = resolve_search_scope(duration=1200, kind="back_half", text="找 15 分钟附近的产品演示")
        self.assertEqual((scoped["start"], scoped["end"]), (780.0, 1020.0))
        self.assertEqual(scoped["source"], "intersection")
        self.assertTrue(scoped["isNarrow"])

    def test_opening_and_ending_ranges_are_capped_at_ten_minutes(self) -> None:
        opening = resolve_search_scope(duration=7200, kind="opening")
        ending = resolve_search_scope(duration=7200, kind="ending")
        self.assertEqual((opening["start"], opening["end"]), (0.0, 600.0))
        self.assertEqual((ending["start"], ending["end"]), (6600.0, 7200.0))

    def test_conflicting_quick_and_text_ranges_request_clarification(self) -> None:
        scoped = resolve_search_scope(duration=600, kind="front_half", text="找后半段的内容")
        self.assertTrue(scoped["empty"])

    def test_scope_filter_drops_units_outside_hard_range(self) -> None:
        units = [
            {"id": "early", "start": 5, "end": 10},
            {"id": "touching", "start": 49, "end": 51},
            {"id": "late", "start": 80, "end": 90},
        ]
        scoped = filter_units_to_scope(units, {"start": 50, "end": 70})
        self.assertEqual([item["id"] for item in scoped], ["touching"])


class ContentIndexTests(unittest.TestCase):
    def test_dense_ocr_sampling_has_complete_coverage_contract(self) -> None:
        from app import main as main_app

        manifest = main_app._content_coverage_manifest({
            "duration": 10,
            "coverage": {"start": 0, "end": 10},
            "recognitionAttemptedModalities": ["ocr"],
            "recognitionCompletedModalities": ["ocr"],
            "recognitionAvailableModalities": ["ocr"],
            "ocrUnits": [],
            "ocrSampling": {
                "intervalSeconds": .5,
                "requestedFrameCount": 21,
                "extractedFrameCount": 21,
                "coverageMode": "continuous_sampled",
            },
        })
        operation = manifest["operations"]["screen_text.fuzzy_search"]
        self.assertTrue(operation["coverageComplete"])
        self.assertTrue(operation["exhaustiveEligible"])
        self.assertEqual(operation["maximumSampleGapUs"], 500000)

    def test_coverage_manifest_separates_execution_from_exhaustive_coverage(self) -> None:
        from app import main as main_app

        manifest = main_app._content_coverage_manifest({
            "duration": 100,
            "recognitionAttemptedModalities": ["speech", "visual"],
            "recognitionCompletedModalities": ["speech", "visual"],
            "recognitionAvailableModalities": ["speech", "visual"],
            "speechUnits": [{"id": "speech_1", "start": 0, "end": 10}],
            "embeddingVisualUnits": [
                {"id": "frame_1", "start": 9.5, "end": 10.5, "evidenceTimes": [10]},
                {"id": "frame_2", "start": 89.5, "end": 90.5, "evidenceTimes": [90]},
            ],
        })
        self.assertEqual(manifest["schemaVersion"], "coverage-manifest-v3")
        speech = manifest["operations"]["speech.semantic_search"]
        visual = manifest["operations"]["visual.embed"]
        self.assertTrue(speech["executionComplete"])
        self.assertTrue(speech["coverageComplete"])
        self.assertTrue(visual["executionComplete"])
        self.assertFalse(visual["coverageComplete"])
        self.assertEqual(visual["coverageMode"], "sampled")
        self.assertEqual(visual["maximumSampleGapUs"], 80000000)

    def test_query_coverage_accepts_a_continuously_indexed_narrow_scope(self) -> None:
        from app import main as main_app

        index = {
            "duration": 100, "coverage": {"start": 10, "end": 20},
            "recognitionAttemptedModalities": ["speech"],
            "recognitionCompletedModalities": ["speech"],
            "recognitionAvailableModalities": ["speech"],
            "speechUnits": [{"id": "speech_1", "start": 10, "end": 20}],
        }
        plan = {
            "requiredOperations": ["speech.semantic_search"],
        }
        manifest = main_app._query_coverage_manifest(
            index, plan, {"resultMode": "exhaustive"}, [], {"start": 10, "end": 20},
        )
        operation = manifest["operations"]["speech.semantic_search"]
        self.assertFalse(operation["coverageComplete"])
        self.assertTrue(operation["queryCoverageComplete"])
        self.assertTrue(manifest["queryCoverageComplete"])

    def test_action_actor_coverage_requires_dense_scan_and_all_candidates_processed(self) -> None:
        from app import main as main_app

        index = {
            "duration": 10, "coverage": {"start": 0, "end": 10},
            "recognitionAttemptedModalities": ["person", "visual"],
            "recognitionCompletedModalities": ["person", "visual"],
            "recognitionAvailableModalities": ["person", "visual"],
            "persons": [{"id": "person_1"}], "personTracks": [{"id": "track_1"}],
            "embeddingVisualUnits": [{"id": "frame_1", "start": 0, "end": 10}],
        }
        manifest = main_app._query_coverage_manifest(index, {
            "requiredOperations": ["person.verify_action_actor"],
        }, {
            "resultMode": "exhaustive", "strictVisualCoverageComplete": True,
            "personActionVerification": {
                "action": {"candidateCount": 1, "processedCount": 1, "modelCalls": 1},
            },
        }, [{"start": 2, "end": 4, "actorEvidence": {"personIds": ["person_1"]}}], {
            "start": 0, "end": 10,
        })
        operation = manifest["operations"]["person.verify_action_actor"]
        self.assertTrue(operation["queryCoverageComplete"])
        self.assertEqual(operation["evidenceCount"], 1)

    def test_transcript_units_keep_speaker_and_complete_text(self) -> None:
        units = merge_transcript_units([
            {"start": 0.0, "end": 2.0, "text": "今天介绍新产品。", "speaker": "Speaker 1"},
            {"start": 2.1, "end": 5.5, "text": "它支持离线模式。", "speaker": "Speaker 1"},
            {"start": 5.7, "end": 8.0, "text": "价格是多少？", "speaker": "Speaker 2"},
        ])
        self.assertEqual(len(units), 2)
        self.assertEqual(units[0]["speakers"], ["Speaker 1"])
        self.assertIn("离线模式", units[0]["text"])
        self.assertEqual(units[1]["speakers"], ["Speaker 2"])
        self.assertTrue(units[0]["segmentIds"][0].startswith("speech_segment_"))

    def test_macro_chapters_snap_and_cover_every_unit(self) -> None:
        units = [
            {"id": "speech_1", "modality": "speech", "start": 0, "end": 178, "text": "开场"},
            {"id": "visual_1", "modality": "visual", "start": 178, "end": 360, "summary": "演示"},
        ]
        chapters = build_macro_chapters(units, video_duration=360, scene_cuts=[176.5])
        self.assertEqual(chapters[0]["end"], 178.0)
        self.assertEqual({unit_id for chapter in chapters for unit_id in chapter["unitIds"]}, {"speech_1", "visual_1"})

    def test_inverted_recall_applies_speaker_and_feedback_exclusion(self) -> None:
        units = [
            {"id": "a", "modality": "speech", "start": 0, "end": 3, "text": "离线模式", "speakers": ["Speaker 1"]},
            {"id": "b", "modality": "speech", "start": 4, "end": 7, "text": "离线模式", "speakers": ["Speaker 2"]},
        ]
        intent = {"query": "离线模式", "modalities": ["speech"], "speakerRefs": ["Speaker 2"]}
        recalled = local_recall(intent, units, build_inverted_index(units), excluded_unit_ids=["a"])
        self.assertEqual([item["unit"]["id"] for item in recalled], ["b"])

    def test_visual_units_only_accept_allowed_evidence_times(self) -> None:
        units = visual_units_from_page([
            {"time_seconds": 10.0, "title": "拿起盒子", "summary": "红衣人物拿起盒子", "confidence": .9},
            {"time_seconds": 999.0, "title": "虚构时间", "summary": "不应采用"},
        ], [0.0, 10.0, 20.0], video_duration=25.0)
        self.assertEqual(len(units), 1)
        self.assertEqual(units[0]["evidenceTime"], 10.0)
        self.assertEqual((units[0]["start"], units[0]["end"]), (5.0, 15.0))


class ContentRankingTests(unittest.TestCase):
    def setUp(self) -> None:
        self.units = [
            {"id": "speech_1", "modality": "speech", "start": 5, "end": 9,
             "text": "新产品支持离线模式", "speakers": ["Speaker 1"]},
            {"id": "speech_2", "modality": "speech", "start": 10, "end": 14,
             "text": "新产品价格是一百元", "speakers": ["Speaker 1"]},
            {"id": "visual_1", "modality": "visual", "start": 20, "end": 26,
             "title": "打开红色盒子", "summary": "一名人物打开桌上的红色盒子"},
        ]

    def test_model_ids_are_grounded_and_exclusions_are_enforced(self) -> None:
        intent = {
            "query": "新产品",
            "modalities": ["speech"],
            "speakerRefs": ["Speaker 1"],
            "excludeRules": ["价格"],
            "requestedCount": 5,
        }
        ranked = rank_units(intent, self.units, [{"matches": [
            {"unit_id": "speech_1", "score": 91, "reason": "功能介绍"},
            {"unit_id": "speech_2", "score": 99, "reason": "价格"},
            {"unit_id": "made_up", "score": 100, "reason": "不存在"},
        ]}])
        self.assertEqual([item["unit"]["id"] for item in ranked], ["speech_1"])

    def _run_adaptive_top_k_search(self, *, return_all_batch_matches: bool):
        from app import main as main_app

        units = [{
            "id": f"u{index:03d}", "modality": "speech",
            "start": index * 3.0, "end": index * 3.0 + 1.0,
            "text": f"证据 {index}", "speakers": [],
        } for index in range(80)]

        class FakeClient:
            def __init__(self) -> None:
                self.calls = 0

            def complete_json(self, prompt, **_kwargs):
                self.calls += 1
                unit_ids = [
                    value for value in re.findall(r"'id': '([^']+)'", prompt)
                    if value.startswith("u")
                ]
                if not return_all_batch_matches:
                    unit_ids = unit_ids[:1]
                return {"matches": [{
                    "unit_id": unit_id, "score": 88,
                    "support_level": "explicit", "evidence_grounded": True,
                    "matched_evidence": f"证据 {int(unit_id[1:])}",
                    "reason": "明确证据",
                } for unit_id in unit_ids]}

            def cancel(self):
                return None

        client = FakeClient()
        job = {
            "id": "adaptive_top_k", "sourceHash": "adaptive-top-k",
            "request": {}, "videoInfo": {"duration": 240},
        }
        index = {
            "cacheKey": "adaptive-index", "indexRevision": "r1",
            "duration": 240, "video": {"duration": 240},
            "speechUnits": units, "transcriptSegments": [],
            "chapters": [{
                "id": "chapter", "start": 0, "end": 240,
                "unitIds": [unit["id"] for unit in units],
            }],
            "recognitionCompletedModalities": ["speech"],
            "recognitionAvailableModalities": ["speech"],
            "recognitionAttemptedModalities": ["speech"],
            "recognitionRequestedModalities": ["speech"],
        }
        intent = {
            "action": "extract_content", "query": "做家务",
            "modalities": ["speech"], "resultMode": "top_k",
            "requestedCount": 12,
            "predicates": [{
                "id": "p1", "kind": "speech.semantic",
                "value": "做家务", "required": True,
            }],
            "searchScope": {"start": 0, "end": 240},
            "boundaryMode": "complete",
        }
        recalled = [{"unit": unit, "score": 80, "lexicalScore": 0} for unit in units]
        with patch.object(main_app, "_content_progress"), patch.object(
            main_app, "read_source_evidence", return_value=[],
        ), patch.object(
            main_app, "_read_content_query_cache", return_value=None,
        ), patch.object(main_app, "_write_content_query_cache"), patch.object(
            main_app, "_promote_query_evidence",
        ), patch.object(
            main_app, "local_recall", return_value=recalled,
        ), patch.object(
            main_app, "select_candidate_units", return_value=units,
        ), patch.object(
            main_app, "create_llm_client_for_job", return_value=client,
        ):
            result = main_app._search_content_index(
                "adaptive_top_k", job, index, "做家务", intent, threading.Event(),
            )
        return result, client.calls

    def test_adaptive_top_k_expands_when_first_wave_is_under_target(self) -> None:
        result, calls = self._run_adaptive_top_k_search(return_all_batch_matches=False)
        stats = result["retrievalStats"]
        self.assertEqual(calls, 5)
        self.assertEqual(result["candidateCount"], 5)
        self.assertTrue(stats["adaptiveExpansionTriggered"])
        self.assertEqual(stats["semanticVerifiedUnitCount"], 80)
        self.assertEqual(stats["adaptiveStopReason"], "candidate_pool_exhausted")
        self.assertEqual(stats["semanticUnitsSkippedAfterRanking"], 0)

    def test_adaptive_top_k_stops_when_target_is_satisfied(self) -> None:
        result, calls = self._run_adaptive_top_k_search(return_all_batch_matches=True)
        stats = result["retrievalStats"]
        self.assertEqual(calls, 3)
        self.assertEqual(result["candidateCount"], 12)
        self.assertFalse(stats["adaptiveExpansionTriggered"])
        self.assertEqual(stats["semanticVerifiedUnitCount"], 48)
        self.assertEqual(stats["adaptiveStopReason"], "target_satisfied")
        self.assertEqual(stats["semanticUnitsSkippedAfterRanking"], 32)

    def test_first_semantic_wave_keeps_relevance_and_time_diversity(self) -> None:
        from app import main as main_app

        units = [{
            "id": f"u{index:03d}", "start": index * 2.0, "end": index * 2.0 + 1.0,
        } for index in range(80)]
        ordered = main_app._temporally_diversified_semantic_units(
            units, initial_budget=48, scope_start=0, scope_end=160,
        )
        first_ids = {item["id"] for item in ordered[:48]}
        self.assertTrue({f"u{index:03d}" for index in range(24)} <= first_ids)
        self.assertTrue(any(float(item["start"]) >= 120 for item in ordered[:48]))
        self.assertEqual(len({item["id"] for item in ordered}), 80)

    def test_predicate_ranking_keeps_conditions_on_separate_scales(self) -> None:
        plan = {"predicates": [
            {"id": "p1", "kind": "speech.semantic", "value": "离线模式", "required": True},
            {"id": "p2", "kind": "visual.action", "value": "打开红色盒子", "required": True},
        ]}
        ranked = rank_predicate_units(plan, self.units, [{"predicateMatches": [
            {"predicateId": "p1", "unitId": "speech_1", "score": 88},
            {"predicateId": "p2", "unitId": "visual_1", "score": 93},
            {"predicateId": "p2", "unitId": "speech_1", "score": 100},
        ]}])
        self.assertEqual(ranked["p1"][0]["unit"]["id"], "speech_1")
        self.assertEqual(ranked["p2"][0]["unit"]["id"], "visual_1")

    def test_predicate_ranking_rejects_untraceable_semantic_guesses(self) -> None:
        plan = {"result": {"mode": "exhaustive"}, "predicates": [
            {"id": "p1", "kind": "speech.semantic", "value": "目标主题", "required": True},
        ]}
        ranked = rank_predicate_units(plan, self.units, [{"predicateMatches": [{
            "predicateId": "p1", "unitId": "speech_2", "score": 99,
            "supportLevel": "explicit", "evidenceGrounded": False,
            "reason": "语义上可能相关", "matchedEvidence": "语义证据匹配",
        }]}])
        self.assertEqual(ranked["p1"], [])

    def test_contextual_grounded_match_is_optional_not_reliable(self) -> None:
        plan = {"result": {"mode": "exhaustive"}, "predicates": [
            {"id": "p1", "kind": "speech.semantic", "value": "目标主题", "required": True},
        ]}
        ranked = rank_predicate_units(plan, self.units, [{"predicateMatches": [{
            "predicateId": "p1", "unitId": "speech_2", "score": 76,
            "supportLevel": "contextual", "evidenceGrounded": True,
            "reason": "只有上下文关联", "matchedEvidence": "新产品价格是一百元",
        }]}])
        self.assertEqual(ranked["p1"][0]["confidenceTier"], "possible")
        self.assertTrue(ranked["p1"][0]["requiresReview"])

    def test_low_scoring_grounded_match_is_preserved_for_exhaustive_review(self) -> None:
        plan = {"result": {"mode": "exhaustive"}, "predicates": [
            {"id": "p1", "kind": "speech.semantic", "value": "目标主题", "required": True},
        ]}
        ranked = rank_predicate_units(plan, self.units, [{"predicateMatches": [{
            "predicateId": "p1", "unitId": "speech_2", "score": 42,
            "supportLevel": "explicit", "evidenceGrounded": True,
            "reason": "较弱但有原文依据", "matchedEvidence": "新产品价格是一百元",
        }]}])
        self.assertEqual(len(ranked["p1"]), 1)
        self.assertEqual(ranked["p1"][0]["confidenceTier"], "possible")

    def test_overlapping_matches_merge_before_confirmation(self) -> None:
        merged = merge_content_matches([
            {"id": "a", "start": 2, "end": 7, "score": 70, "evidenceType": "speech", "evidenceTimes": [], "speechUnits": []},
            {"id": "b", "start": 6.5, "end": 10, "score": 90, "evidenceType": "visual", "evidenceTimes": [8], "speechUnits": []},
        ])
        self.assertEqual(len(merged), 1)
        self.assertEqual(merged[0]["end"], 10.0)
        self.assertEqual(merged[0]["evidenceType"], "audiovisual")
        self.assertEqual(set(merged[0]["matchedModalities"]), {"speech", "visual"})
        self.assertTrue(merged[0]["occurrenceId"].startswith("occ_"))
        self.assertEqual(merged[0]["position"], 1)

    def test_adjacent_visual_matches_from_different_shots_stay_separate(self) -> None:
        merged = merge_content_matches([
            {"id": "a", "start": 2, "end": 5, "score": 80, "evidenceType": "visual", "predicateId": "p1", "shotIds": ["shot_1"]},
            {"id": "b", "start": 5.4, "end": 8, "score": 82, "evidenceType": "visual", "predicateId": "p1", "shotIds": ["shot_2"]},
        ], maximum_gap=1.5)
        self.assertEqual(len(merged), 2)

    def test_v2_adjacent_speech_requires_same_known_speaker(self) -> None:
        different = merge_content_matches([
            {"id": "a", "start": 2, "end": 5, "score": 80, "evidenceType": "speech", "speakerRef": "Speaker 1"},
            {"id": "b", "start": 5.4, "end": 8, "score": 82, "evidenceType": "speech", "speakerRef": "Speaker 2"},
        ], maximum_gap=1.5, algorithm_version="editing-algorithm-v2")
        same = merge_content_matches([
            {"id": "a", "start": 2, "end": 5, "score": 80, "evidenceType": "speech", "speakerRef": "Speaker 1"},
            {"id": "b", "start": 5.4, "end": 8, "score": 82, "evidenceType": "speech", "speakerRef": "Speaker 1"},
        ], maximum_gap=1.5, algorithm_version="editing-algorithm-v2")
        self.assertEqual(len(different), 2)
        self.assertEqual(len(same), 1)

    def test_v2_two_contextual_modalities_do_not_auto_promote_reliability(self) -> None:
        merged = merge_content_matches([
            {"id": "speech", "start": 2, "end": 7, "score": 68, "evidenceType": "speech", "matchedModalities": ["speech"], "confidenceTier": "possible", "groundingStatus": "contextual", "evidenceItems": [{"type": "speech", "id": "s1"}]},
            {"id": "visual", "start": 6, "end": 9, "score": 72, "evidenceType": "visual", "matchedModalities": ["visual"], "confidenceTier": "possible", "groundingStatus": "contextual", "evidenceItems": [{"type": "visual", "id": "v1"}]},
        ], algorithm_version="editing-algorithm-v2")
        self.assertEqual(merged[0]["confidenceTier"], "possible")
        self.assertTrue(merged[0]["requiresReview"])

    def test_adjacent_alternative_modalities_stay_separate_without_shared_context(self) -> None:
        merged = merge_content_matches([
            {"id": "a", "start": 2, "end": 5, "score": 80, "evidenceType": "visual", "predicateId": "p1"},
            {"id": "b", "start": 5.4, "end": 8, "score": 82, "evidenceType": "speech", "predicateId": "p2"},
        ], maximum_gap=1.5)
        self.assertEqual(len(merged), 2)

    def test_two_grounded_modalities_form_one_reliable_content_segment(self) -> None:
        merged = merge_content_matches([
            {
                "id": "speech", "start": 2, "end": 7, "score": 68,
                "evidenceType": "speech", "matchedModalities": ["speech"],
                "confidenceTier": "possible", "groundingStatus": "contextual",
                "evidenceItems": [{"type": "speech", "id": "s1"}],
            },
            {
                "id": "visual", "start": 6, "end": 9, "score": 72,
                "evidenceType": "visual", "matchedModalities": ["visual"],
                "confidenceTier": "possible", "groundingStatus": "contextual",
                "evidenceItems": [{"type": "visual", "id": "v1"}],
            },
        ])
        self.assertEqual(len(merged), 1)
        self.assertEqual(merged[0]["confidenceTier"], "reliable")
        self.assertFalse(merged[0]["requiresReview"])
        self.assertEqual({item["type"] for item in merged[0]["evidenceItems"]}, {"speech", "visual"})

    def test_confirmed_matches_become_safe_render_segments(self) -> None:
        segments = content_matches_to_segments([
            {"id": "m1", "unitId": "speech_1", "start": 5, "end": 9,
             "score": 91, "reason": "匹配功能介绍", "transcriptExcerpt": "支持离线模式",
             "speaker": "Speaker 1", "speechUnits": [{"start": 5, "end": 9, "text": "支持离线模式"}]},
        ])
        self.assertEqual(len(segments), 1)
        segment = segments[0]
        self.assertEqual((segment["start"], segment["end"]), (5.0, 9.0))
        self.assertTrue(segment["essential"])
        self.assertTrue(segment["standalone"])
        self.assertEqual(segment["playbackRate"], 1.0)
        self.assertEqual(segment["audioEvidence"]["speakers"], ["Speaker 1"])
        self.assertEqual(segment["semanticUnitId"], "m1")
        self.assertEqual(segment["sourceSemanticUnitId"], "speech_1")
        self.assertTrue(segment["userConfirmed"])

    def test_confirmed_matches_in_same_chapter_keep_distinct_semantic_ids(self) -> None:
        segments = content_matches_to_segments([
            {"id": "m1", "unitId": "chapter_0000", "start": 5, "end": 9},
            {"id": "m2", "unitId": "chapter_0000", "start": 15, "end": 19},
        ])
        self.assertEqual([item["semanticUnitId"] for item in segments], ["m1", "m2"])
        self.assertEqual(
            [item["sourceSemanticUnitId"] for item in segments],
            ["chapter_0000", "chapter_0000"],
        )

    def test_chapter_ids_are_grounded_and_candidate_budget_is_capped(self) -> None:
        units = [{"id": f"u{index}", "modality": "speech", "start": index, "end": index + 1, "text": "产品功能"} for index in range(100)]
        chapters = [{"id": "c1", "start": 0, "end": 100, "unitIds": [item["id"] for item in units], "summary": "产品功能", "keywords": ["产品"]}]
        ranked = rank_chapters({"query": "产品"}, chapters, {"chapters": [
            {"chapter_id": "invented", "score": 100}, {"chapter_id": "c1", "score": 90},
        ]})
        selected = select_candidate_units({"query": "产品", "modalities": ["speech"]}, chapters, ["c1"], units, [], limit=80)
        self.assertEqual([item["chapter"]["id"] for item in ranked], ["c1"])
        self.assertEqual(len(selected), 80)

    def test_query_cache_key_is_stable_and_ignores_parser_metadata(self) -> None:
        intent = {"action": "extract_content", "query": " 离线  模式 ", "modalities": ["speech"], "_parserLlmCalls": 1}
        left = content_query_cache_key("index", intent, language_model="llm", vision_model="vlm")
        intent["_parserLlmCalls"] = 0
        right = content_query_cache_key("index", intent, language_model="llm", vision_model="vlm")
        self.assertEqual(left, right)

    def test_query_cache_key_changes_with_scope_count_and_boundary(self) -> None:
        base = {
            "action": "extract_content", "query": "离线模式", "modalities": ["speech"],
            "requestedCount": 3, "boundaryMode": "complete",
            "searchScope": {"kind": "front_half", "start": 0, "end": 300, "source": "quick"},
        }
        first = content_query_cache_key("index", base)
        changed_scope = content_query_cache_key("index", {**base, "searchScope": {**base["searchScope"], "end": 200}})
        changed_count = content_query_cache_key("index", {**base, "requestedCount": 1})
        changed_boundary = content_query_cache_key("index", {**base, "boundaryMode": "context"})
        self.assertEqual(len({first, changed_scope, changed_count, changed_boundary}), 4)

    def test_grounded_segment_ids_and_word_timestamps_set_exact_boundary(self) -> None:
        segments = [{
            "id": "s1", "start": 1.0, "end": 3.2, "text": "hello offline mode",
            "words": [
                {"word": "hello", "start": 1.0, "end": 1.4},
                {"word": "offline", "start": 1.6, "end": 2.2},
                {"word": "mode", "start": 2.3, "end": 2.8},
            ],
        }]
        unit = {"id": "speech_1", "modality": "speech", "start": 1, "end": 3.2, "text": "hello offline mode", "segments": segments, "segmentIds": ["s1"]}
        ranked = rank_units(
            {"query": "offline mode", "modalities": ["speech"], "requestedCount": 1}, [unit],
            [{"matches": [{"unit_id": "speech_1", "segment_ids": ["s1", "made_up"], "score": 96}]}],
        )
        matches = matches_from_ranked(ranked, transcript_segments=segments, query="offline mode")
        self.assertEqual(ranked[0]["segmentIds"], ["s1"])
        self.assertEqual(matches[0]["matchType"], "exact_quote")
        self.assertEqual(matches[0]["boundarySource"], "word_timestamps")
        self.assertAlmostEqual(matches[0]["start"], 1.45)
        self.assertAlmostEqual(matches[0]["end"], 2.95)

    def test_metrics_report_recall_precision_boundary_and_call_budget(self) -> None:
        metrics = evaluate_content_search_cases([{
            "sourceType": "real", "annotatedTurnCount": 12, "annotatedQaPairCount": 4,
            "expected": [{"start": 10, "end": 20}],
            "predicted": [{
                "start": 11, "end": 19, "matchedUnitIds": ["u1"],
                "wrongSpeakerSeconds": .05, "predictedSpeechSeconds": 8,
            }],
            "excludedUnitIds": [],
            "retrievalStats": {"llmCalls": 3, "vlmCalls": 0, "totalMilliseconds": 120},
        }])
        self.assertEqual(metrics["recallAt5"], 1.0)
        self.assertEqual(metrics["precisionAt5"], 1.0)
        self.assertEqual(metrics["boundaryMaeSeconds"], 1.0)
        self.assertEqual(metrics["boundaryP95Seconds"], 1.0)
        self.assertEqual(metrics["wrongSpeakerDurationRate"], .0063)
        self.assertEqual(metrics["realCaseCount"], 1)
        self.assertEqual(metrics["annotatedTurnCount"], 12)
        self.assertEqual(metrics["annotatedQaPairCount"], 4)
        self.assertEqual(metrics["averageLlmCalls"], 3.0)


class ContentConfirmationTests(unittest.TestCase):
    def test_person_index_loader_keeps_previous_continuity_index_readable(self) -> None:
        from app import main as main_app

        job = {
            "id": "previous-person-index", "recognitionSchemaVersion": 7,
            "contentIndex": {"cacheKey": "previous-person-cache"},
        }
        seen_versions: list[str] = []

        def read_index(_path: Path, *, expected_version: str, **_kwargs):
            seen_versions.append(expected_version)
            if expected_version == main_app.PREVIOUS_MULTIMODAL_INDEX_VERSION:
                return {"schemaVersion": expected_version, "status": "ready", "persons": []}
            return None

        with patch.object(main_app, "_read_content_index", side_effect=read_index):
            loaded = main_app._load_content_person_index(job)
        self.assertEqual(loaded["schemaVersion"], main_app.PREVIOUS_MULTIMODAL_INDEX_VERSION)
        self.assertIn(main_app.MULTIMODAL_INDEX_VERSION, seen_versions)
        self.assertIn(main_app.PREVIOUS_MULTIMODAL_INDEX_VERSION, seen_versions)

    def test_person_index_loader_keeps_v8_continuity_index_readable(self) -> None:
        from app import main as main_app

        job = {
            "id": "v8-person-index", "recognitionSchemaVersion": 6,
            "contentIndex": {"cacheKey": "v8-person-cache"},
        }

        def read_index(_path: Path, *, expected_version: str, **_kwargs):
            if expected_version == main_app.CONTINUITY_MULTIMODAL_INDEX_VERSION:
                return {"schemaVersion": expected_version, "status": "ready", "persons": []}
            return None

        with patch.object(main_app, "_read_content_index", side_effect=read_index):
            loaded = main_app._load_content_person_index(job)
        self.assertEqual(loaded["schemaVersion"], main_app.CONTINUITY_MULTIMODAL_INDEX_VERSION)

    def test_reanalyze_cancelled_content_job_uses_content_worker_signature(self) -> None:
        from app import main as main_app

        job_id = "test_reanalyze_content_signature"
        job = main_app.new_job_record(
            job_id=job_id, source=Path("/tmp/test-reanalyze-source.mp4"),
            filename="source.mp4", size=100, count="auto",
            target_seconds="auto", theme="查找人物",
            source_hash="reanalyze-content-signature-hash",
        )
        job.update({
            "taskMode": "content_extract", "workflowKind": "person_edit",
            "status": "cancelled", "stage": "cancelled",
        })
        main_app.jobs[job_id] = job
        try:
            with patch.object(main_app, "save_job"), patch.object(
                main_app, "append_message",
            ), patch.object(main_app, "submit_analysis_task") as submit:
                main_app.reanalyze_cancelled_job(job_id)
            submit.assert_called_once_with(
                job_id, main_app.run_content_search_job, job_id,
            )
        finally:
            main_app.jobs.pop(job_id, None)
            main_app.cancel_events.pop(job_id, None)

    def test_person_edit_entry_builds_tracks_then_waits_for_selection(self) -> None:
        from app import main as main_app

        job_id = "test_person_discovery_waits_for_target"
        job = main_app.new_job_record(
            job_id=job_id, source=Path("/tmp/test-person-source.mp4"),
            filename="source.mp4", size=100, count="auto",
            target_seconds="auto", theme="提取所选画面人物的所有出镜片段",
            source_hash="person-discovery-waits-hash",
        )
        job.update({
            "taskMode": "content_extract", "workflowKind": "person_edit",
            "recognitionSchemaVersion": main_app.RECOGNITION_SCHEMA_VERSION,
            "videoInfo": {"duration": 30.0},
        })
        job["request"].update({
            "workflowKind": "person_edit", "entryWorkflow": "person_discovery",
            "contentInstruction": "提取所选画面人物的所有出镜片段",
            "contentEvidenceMode": "person", "contentAllowedCapabilities": ["person"],
        })
        parsed_visual_placeholder = {
            "action": "extract_content",
            "query": "提取所选画面人物的所有出镜片段",
            "modalities": ["visual"],
            "resultMode": "exhaustive",
            "predicates": [{
                "id": "p1", "kind": "visual.semantic",
                "value": "所选画面人物出镜", "required": True,
            }],
            "relations": [],
            "executionPlan": {"allowedCapabilities": ["visual"]},
        }
        index = {
            "schemaVersion": main_app._content_index_version(job),
            "cacheKey": "person-index", "indexRevision": "person-index-r1",
            "recognitionRequestedModalities": ["person"],
            "recognitionAttemptedModalities": ["person"],
            "recognitionCompletedModalities": ["person"],
            "recognitionAvailableModalities": ["person"],
            "persons": [{
                "id": "person_1", "label": "人物 A", "confidence": .91,
                "ranges": [{"start": 1.0, "end": 8.0}], "trackCount": 4,
            }],
            "personTracks": [], "video": {"duration": 30.0},
            "coverage": {"start": 0.0, "end": 30.0},
        }
        main_app.jobs[job_id] = job
        main_app.cancel_events[job_id] = threading.Event()
        try:
            with patch.object(
                main_app, "_parse_content_instruction",
                return_value=parsed_visual_placeholder,
            ), patch.object(
                main_app, "_build_content_index", return_value=index,
            ) as build_index, patch.object(
                main_app, "_search_latest_content_instruction",
            ) as execute_search, patch.object(
                main_app, "recognition_summary", return_value={},
            ), patch.object(main_app, "save_job"), patch.object(main_app, "append_message"):
                main_app.run_content_search_job(job_id)

            self.assertEqual(
                build_index.call_args.kwargs["required_modalities"], {"person"},
            )
            execute_search.assert_not_called()
            completed = main_app.jobs[job_id]
            self.assertEqual(completed["status"], "awaiting_content_confirmation")
            self.assertEqual(
                completed["contentSearch"]["clarification"]["kind"], "person_target",
            )
            self.assertEqual(completed["contentIndex"]["anonymousPersonCount"], 1)
            persisted_intent = completed["request"]["pendingContentIntent"]["intent"]
            self.assertEqual(persisted_intent["modalities"], ["person"])
            self.assertEqual(
                [item["kind"] for item in persisted_intent["predicates"]],
                ["person.appearance"],
            )
        finally:
            main_app.jobs.pop(job_id, None)
            main_app.cancel_events.pop(job_id, None)

    def test_full_source_highlight_starts_fresh_job_without_search_candidates(self) -> None:
        from app import main as main_app

        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "source.mp4"
            source.write_bytes(b"video")
            original_settings = main_app.settings
            main_app.settings = replace(original_settings, data_root=root)
            main_app.settings.ensure_directories()
            parent_id = "content_to_highlight_parent"
            main_app.jobs[parent_id] = {
                "id": parent_id, "taskMode": "content_extract",
                "status": "awaiting_content_confirmation",
                "filename": "source.mp4", "sourcePath": str(source),
                "sizeBytes": source.stat().st_size, "sourceHash": "same-source",
                "storageMode": "editable", "messages": [{
                    "id": "old_message", "role": "user", "text": "找到煎鸡蛋的画面", "kind": "content-query",
                }],
                "videoInfo": {"duration": 81.6, "width": 1280, "height": 720},
                "request": {"analysisMode": "audiovisual"},
                "contentSearch": {
                    "id": "old_search", "defaultSelectedIds": ["match_egg"],
                    "candidates": [{"id": "match_egg", "start": 35.5, "end": 41.0}],
                },
            }
            try:
                def enqueue_without_worker(job):
                    main_app.jobs[job["id"]] = job

                with patch.object(main_app, "enqueue_job", side_effect=enqueue_without_worker) as enqueue, patch.object(main_app, "save_job"):
                    created = main_app.create_highlight_job_from_source(
                        parent_id, "把整个视频提取出30s的高光片段", {
                            "highlightRequest": {"targetSeconds": 30, "theme": "", "scope": "all"},
                        },
                    )
                self.assertEqual(created["taskMode"], "highlight")
                self.assertEqual(created["request"]["totalTargetSeconds"], 30)
                self.assertEqual(created["request"]["sourceScopeKind"], "all")
                self.assertEqual(created["parentJobId"], parent_id)
                self.assertNotIn("contentSearch", created)
                self.assertNotIn("match_egg", str(created))
                self.assertIn("不会沿用上一轮内容检索候选", created["messages"][-1]["text"])
                self.assertEqual(created["handoff"]["fromJobId"], parent_id)
                self.assertEqual(created["handoff"]["reason"], "full_source_highlight")
                self.assertEqual(main_app.jobs[parent_id]["activeChildJobId"], created["id"])
                self.assertTrue(created["messages"][0]["inherited"])
                self.assertEqual(created["messages"][0]["originJobId"], parent_id)
                self.assertTrue(all(message.get("inherited") is False for message in created["messages"][-2:]))
                enqueue.assert_called_once_with(created)
            finally:
                for job_id in list(main_app.jobs):
                    if str(main_app.jobs[job_id].get("parentJobId") or "") == parent_id:
                        main_app.jobs.pop(job_id, None)
                main_app.jobs.pop(parent_id, None)
                main_app.settings = original_settings

    def test_existing_highlight_regeneration_reuses_evidence_in_same_job(self) -> None:
        from app import main as main_app

        job_id = "highlight_replan_same_job"
        job = main_app.new_job_record(
            job_id=job_id, source=Path("/tmp/replan-source.mp4"), filename="source.mp4",
            size=100, count="auto", target_seconds=60, total_target_seconds=60,
            theme="", source_hash="replan-source-hash",
        )
        job.update({
            "taskMode": "highlight", "workflowKind": "highlight",
            "status": "awaiting_confirmation", "stage": "review",
            "videoInfo": {"duration": 180, "width": 1280, "height": 720, "has_audio": True},
            "eventGroups": [{
                "id": "event_1", "title": "人物进门并落座", "score": 90,
                "segments": [{"id": "shot_1", "start": 2, "end": 62, "duration": 60}],
            }, {
                "id": "event_2", "title": "主角完成最终回应", "score": 86,
                "segments": [{"id": "shot_2", "start": 80, "end": 115, "duration": 35}],
            }],
            "candidates": [{"index": 0, "title": "进门", "start": 2, "end": 62}],
            "recommendedGroupIds": ["event_1"],
            "outputVersions": [{
                "id": "v001", "number": 1, "previewOnly": True,
                "generationBatchId": "batch_old", "outputs": [{"filename": "old.mp4", "duration": 60}],
            }],
            "outputs": [{"filename": "old.mp4", "duration": 60}],
            "autoComposition": {
                "status": "completed", "batches": [{
                    "id": "batch_old", "mode": "initial", "status": "completed",
                    "targetVariantCount": 1,
                }],
            },
        })
        main_app.jobs[job_id] = job
        decision = {
            "action": "highlight_generation", "confidence": .96,
            "highlightRequest": {"targetSeconds": 90, "variantCount": 2, "theme": ""},
        }
        try:
            with patch.object(main_app, "_conversation_workflow_route", return_value=(None, None)), \
                    patch.object(main_app, "_route_content_message", return_value=decision), \
                    patch.object(main_app, "submit_render_task") as submit, \
                    patch.object(main_app, "save_job"):
                response = main_app.chat_with_job(
                    job_id, main_app.ChatRequest(text="重新生成为90s的高光视频"),
                )
            self.assertEqual(response["action"], "highlight-replan-started")
            self.assertEqual(response["job"]["id"], job_id)
            self.assertNotIn("activeChildJobId", main_app.jobs[job_id])
            self.assertEqual(main_app.jobs[job_id]["request"]["totalTargetSeconds"], 90)
            self.assertEqual(main_app.jobs[job_id]["autoComposition"]["pendingReplan"]["evidenceSource"], "existing_analysis")
            self.assertEqual(main_app.jobs[job_id]["outputVersions"][0]["id"], "v001")
            submit.assert_called_once_with(job_id, main_app.run_automatic_composition)
        finally:
            main_app.cancel_events.pop(job_id, None)
            main_app.jobs.pop(job_id, None)

    def test_explicit_highlight_reanalysis_still_creates_a_child_task(self) -> None:
        from app import main as main_app

        job_id = "highlight_explicit_reanalysis"
        main_app.jobs[job_id] = {
            "id": job_id, "taskMode": "highlight", "workflowKind": "highlight",
            "status": "awaiting_confirmation", "eventGroups": [{
                "id": "event_1", "title": "完整叙事事件", "segments": [{"start": 1, "end": 10}],
            }],
            "messages": [], "request": {}, "outputs": [], "outputVersions": [],
        }
        decision = {
            "action": "highlight_generation", "confidence": .99,
            "highlightRequest": {"targetSeconds": 90, "variantCount": 3},
        }
        child = {"id": "child_reanalysis", "handoff": {"reason": "full_source_highlight"}}
        try:
            with patch.object(main_app, "_conversation_workflow_route", return_value=(None, None)), \
                    patch.object(main_app, "_route_content_message", return_value=decision), \
                    patch.object(main_app, "create_highlight_job_from_source", return_value=child) as create_child, \
                    patch.object(main_app, "public_job", side_effect=lambda value: value):
                response = main_app.chat_with_job(
                    job_id,
                    main_app.ChatRequest(text="不要之前候选，重新分析全片做90秒高光"),
                )
            self.assertEqual(response["action"], "job-handoff")
            create_child.assert_called_once_with(job_id, "不要之前候选，重新分析全片做90秒高光", decision)
        finally:
            main_app.jobs.pop(job_id, None)

    def test_review_draft_persists_full_selection_order_and_settings(self) -> None:
        from app import main as main_app

        job_id = "test_content_review_draft"
        job = main_app.new_job_record(
            job_id=job_id, source=Path("/tmp/test-content-source.mp4"), filename="source.mp4",
            size=100, count="auto", target_seconds="auto", theme="全部片段",
            source_hash="review-draft-hash",
        )
        job.update({
            "taskMode": "content_extract", "status": "awaiting_content_confirmation",
            "contentSearch": {
                "id": "search_draft", "candidates": [
                    {"id": "match_1", "start": 1, "end": 2, "reviewStatus": "confirmed"},
                    {"id": "match_2", "start": 3, "end": 4, "reviewStatus": "confirmed"},
                ],
            },
        })
        main_app.jobs[job_id] = job
        try:
            with patch.object(main_app, "save_job"):
                response = main_app.update_content_search_review_draft(
                    job_id, main_app.ContentSearchReviewDraftRequest(
                        searchId="search_draft",
                        selectedMatchIds=["match_1", "match_2"],
                        orderedMatchIds=["match_2", "match_1"],
                        outputMode="separate_events", orderMode="selection",
                        subtitleEnabled=True, subtitleStyle="clean",
                    ),
                )
            draft = response["reviewDraft"]
            self.assertEqual(draft["orderedMatchIds"], ["match_2", "match_1"])
            self.assertEqual(draft["outputMode"], "separate_events")
            self.assertTrue(draft["subtitleEnabled"])
            self.assertEqual(main_app.jobs[job_id]["contentSearch"]["defaultSelectedIds"], ["match_1", "match_2"])
        finally:
            main_app.jobs.pop(job_id, None)

    def test_strict_completeness_does_not_block_on_optional_candidates(self) -> None:
        from app import main as main_app

        candidate = {
            "id": "match_1", "unitId": "speech_1", "matchedUnitIds": ["speech_1"],
            "recallChannels": ["index_lexical"], "requiresReview": True, "selected": True,
        }
        report = main_app._strict_completeness_report(
            instruction="找出所有这句话",
            result_mode="exhaustive",
            query_manifest={"queryCoverageComplete": True},
            stats={"semanticVerifiedUnitCount": 1},
            matches=[candidate], unit_count=1,
        )
        self.assertEqual(report["status"], "complete")
        self.assertTrue(report["complete"])
        self.assertEqual(report["pendingCandidateIds"], [])
        self.assertEqual(report["optionalCandidateIds"], ["match_1"])
        self.assertEqual(report["possibleCount"], 1)

        candidate["reviewStatus"] = "kept"
        report = main_app._strict_completeness_report(
            instruction="找出所有这句话",
            result_mode="exhaustive",
            query_manifest={"queryCoverageComplete": True},
            stats={"semanticVerifiedUnitCount": 1},
            matches=[candidate], unit_count=1,
        )
        self.assertEqual(report["status"], "complete")
        self.assertTrue(report["reviewComplete"])

    def test_strict_completeness_honors_explicit_expected_count(self) -> None:
        from app import main as main_app

        matches = [{
            "id": f"match_{index}", "unitId": f"speech_{index}",
            "sourceOccurrenceIds": [f"occurrence:{index}"],
            "recallChannels": ["index_lexical", "semantic_verifier"],
        } for index in range(4)]
        report = main_app._strict_completeness_report(
            instruction="实际应该有5处，请全部找出",
            result_mode="exhaustive",
            query_manifest={"queryCoverageComplete": True},
            stats={"semanticVerifiedUnitCount": 4},
            matches=matches, unit_count=4,
        )
        self.assertEqual(report["expectedOccurrenceCount"], 5)
        self.assertFalse(report["expectedCountSatisfied"])
        self.assertEqual(report["status"], "incomplete")

    def test_editorial_question_answers_without_replacing_active_search(self) -> None:
        from app import main as main_app

        job_id = "test_content_editorial_question"
        job = main_app.new_job_record(
            job_id=job_id, source=Path("/tmp/test-content-source.mp4"), filename="source.mp4",
            size=100, count="auto", target_seconds="auto", theme="做家务",
            source_hash="editorial-hash",
        )
        original_search = {
            "id": "search_housework", "instruction": "做家务的片段",
            "status": "ready", "candidates": [{"id": "m1", "title": "整理房间"}],
        }
        job.update({
            "taskMode": "content_extract", "status": "awaiting_content_confirmation",
            "contentSearch": copy.deepcopy(original_search),
        })
        main_app.jobs[job_id] = job
        client = MagicMock()
        client.complete_json.return_value = {
            "action": "editorial_discussion", "confidence": .97,
            "answer": "一般属于。剪辑时可以把做饭归入家务活动，也可以按叙事重点单独成章。",
            "capabilityProposal": {"capabilities": []},
        }
        try:
            with patch.object(main_app, "create_llm_client_for_job", return_value=client), \
                    patch.object(main_app, "queue_content_followup") as queue_search, \
                    patch.object(main_app, "save_job"):
                response = main_app.chat_with_job(
                    job_id, main_app.ChatRequest(text="做饭属于家务吗？"),
                )
            self.assertEqual(response["action"], "editorial-discussion")
            queue_search.assert_not_called()
            self.assertEqual(main_app.jobs[job_id]["contentSearch"], original_search)
            self.assertEqual(main_app.jobs[job_id]["status"], "awaiting_content_confirmation")
            self.assertEqual(main_app.jobs[job_id]["messages"][-2]["kind"], "editorial-question")
            self.assertEqual(main_app.jobs[job_id]["messages"][-1]["kind"], "editorial-answer")
            self.assertIn("一般属于", main_app.jobs[job_id]["messages"][-1]["text"])
            self.assertEqual(client.complete_json.call_count, 2)
        finally:
            main_app.jobs.pop(job_id, None)

    def test_explicit_search_still_uses_content_followup_route(self) -> None:
        from app import main as main_app

        job_id = "test_content_explicit_search"
        job = main_app.new_job_record(
            job_id=job_id, source=Path("/tmp/test-content-source.mp4"), filename="source.mp4",
            size=100, count="auto", target_seconds="auto", theme="做家务",
            source_hash="search-route-hash",
        )
        job.update({
            "taskMode": "content_extract", "status": "awaiting_content_confirmation",
            "contentSearch": {"id": "search_housework", "candidates": []},
            "recognition": {"availableModalities": ["visual"]},
            "videoInfo": {"duration": 30, "width": 1280, "height": 720, "has_audio": True},
        })
        main_app.jobs[job_id] = job
        expected = {"action": "content-search", "job": {"id": job_id}}
        client = MagicMock()
        client.complete_json.return_value = {
            "action": "content_search", "confidence": .96,
            "capabilityProposal": {
                "capabilities": ["visual"], "capabilityBasis": "explicit_user",
                "explicitEvidenceQuotes": ["片段"], "reason": "需要查看画面",
            },
            "intent": {
                "action": "extract_content", "query": "做饭", "modalities": ["visual"],
                "predicates": [{"id": "p1", "kind": "visual.action", "value": "做饭"}],
            },
        }
        try:
            with patch.object(main_app, "queue_content_followup", return_value=expected) as queue_search, \
                    patch.object(main_app, "create_llm_client_for_job", return_value=client), \
                    patch.object(main_app, "save_job"):
                response = main_app.chat_with_job(
                    job_id, main_app.ChatRequest(text="找出做饭的片段"),
                )
            self.assertEqual(response, expected)
            queue_search.assert_called_once()
            self.assertEqual(client.complete_json.call_count, 1)
        finally:
            main_app.jobs.pop(job_id, None)

    def test_new_topic_resets_stale_custom_scope_to_full_video(self) -> None:
        from app import main as main_app

        job_id = "test_fresh_topic_scope"
        job = main_app.new_job_record(
            job_id=job_id, source=Path("/tmp/test-content-source.mp4"), filename="source.mp4",
            size=100, count="auto", target_seconds="auto", theme="冰箱",
            source_hash="fresh-topic-scope-hash",
        )
        job.update({
            "taskMode": "content_extract", "status": "awaiting_content_confirmation",
            "request": {
                **job["request"], "contentInstruction": "找到冰箱相关的片段",
                "searchScopeKind": "custom", "searchScopeStart": 0, "searchScopeEnd": 150,
            },
            "contentSearch": {
                "id": "search_fridge", "instruction": "找到冰箱相关的片段",
                "intent": {"searchScope": {
                    "kind": "custom", "start": 0, "end": 150, "duration": 150,
                    "videoDuration": 643, "source": "quick", "origin": "explicit_ui",
                }},
                "candidates": [],
            },
            "videoInfo": {"duration": 643, "width": 1280, "height": 720, "has_audio": True},
        })
        main_app.jobs[job_id] = job
        expected = {"action": "content-search", "job": {"id": job_id}}
        client = MagicMock()
        client.complete_json.return_value = {
            "action": "content_search", "confidence": .98,
            "capabilityProposal": {"capabilities": ["speech"]},
            "intent": {
                "action": "extract_content", "query": "洗衣机", "contextPolicy": "fresh",
                "modalities": ["speech"],
                "predicates": [{"id": "p1", "kind": "speech.semantic", "value": "洗衣机"}],
            },
        }
        try:
            with patch.object(main_app, "create_llm_client_for_job", return_value=client), \
                    patch.object(main_app, "queue_content_followup", return_value=expected) as queue_search, \
                    patch.object(main_app, "save_job"):
                response = main_app.chat_with_job(
                    job_id, main_app.ChatRequest(text="帮我找到洗衣机相关的片段"),
                )
            self.assertEqual(response, expected)
            prepared = queue_search.call_args.kwargs["prepared_intent"]
            self.assertEqual(prepared["searchScope"]["kind"], "all")
            self.assertEqual((prepared["searchScope"]["start"], prepared["searchScope"]["end"]), (0.0, 643.0))
            self.assertEqual(prepared["searchScope"]["origin"], "fresh_default")
        finally:
            main_app.jobs.pop(job_id, None)

    def test_scope_policy_preserves_continuations_and_referenced_history(self) -> None:
        from app import main as main_app

        current_scope = {
            "kind": "custom", "start": 0, "end": 150, "duration": 150,
            "videoDuration": 643, "source": "quick", "origin": "explicit_ui",
        }
        historical_scope = {
            "kind": "custom", "start": 300, "end": 420, "duration": 120,
            "videoDuration": 643, "source": "quick", "origin": "explicit_ui",
        }
        base = {
            "request": {"searchScopeKind": "custom", "searchScopeStart": 0, "searchScopeEnd": 150},
            "videoInfo": {"duration": 643},
            "contentSearch": {"id": "search_current", "intent": {"searchScope": current_scope}},
            "contentSearchHistory": [{"id": "search_old", "intent": {"searchScope": historical_scope}}],
        }

        continuation_job = copy.deepcopy(base)
        resolved = main_app._prepare_content_followup_scope(
            continuation_job, main_app.ChatRequest(text="继续当前检索"), "继续当前检索",
            {"contextPolicy": "fresh"}, continuation=True,
        )
        self.assertEqual((resolved["start"], resolved["end"]), (0.0, 150.0))
        self.assertEqual(continuation_job["request"]["contentSearchScopeOrigin"], "continuation")

        inherited_job = copy.deepcopy(base)
        resolved = main_app._prepare_content_followup_scope(
            inherited_job, main_app.ChatRequest(text="继续上次范围找洗衣机"), "继续上次范围找洗衣机",
            {"contextPolicy": "inherit", "referencedSearchIds": ["search_old"]},
        )
        self.assertEqual((resolved["start"], resolved["end"]), (300.0, 420.0))
        self.assertEqual(inherited_job["request"]["contentSearchScopeOrigin"], "inherited")

    def test_fresh_text_time_scope_does_not_intersect_stale_custom_scope(self) -> None:
        from app import main as main_app

        job = {
            "request": {"searchScopeKind": "custom", "searchScopeStart": 0, "searchScopeEnd": 150},
            "videoInfo": {"duration": 600},
        }
        resolved = main_app._prepare_content_followup_scope(
            job, main_app.ChatRequest(text="找后半段的洗衣机"), "找后半段的洗衣机",
            {"contextPolicy": "fresh"},
        )
        self.assertEqual((resolved["start"], resolved["end"]), (300.0, 600.0))
        self.assertEqual(job["request"]["searchScopeKind"], "all")
        self.assertEqual(job["request"]["contentSearchScopeOrigin"], "explicit_text")

    def test_fresh_followup_resets_to_task_source_scope_not_previous_query_scope(self) -> None:
        from app import main as main_app

        job = {
            "request": {
                "sourceScopeKind": "custom", "sourceScopeStart": 120, "sourceScopeEnd": 480,
                "searchScopeKind": "custom", "searchScopeStart": 300, "searchScopeEnd": 360,
            },
            "videoInfo": {"duration": 600},
            "contentSearch": {
                "id": "previous", "intent": {"searchScope": {
                    "kind": "custom", "start": 300, "end": 360, "duration": 60,
                    "videoDuration": 600, "source": "quick", "origin": "explicit_text",
                }},
            },
        }
        resolved = main_app._prepare_content_followup_scope(
            job, main_app.ChatRequest(text="找冰箱相关的片段"), "找冰箱相关的片段",
            {"contextPolicy": "fresh"},
        )
        self.assertEqual((resolved["start"], resolved["end"]), (120.0, 480.0))
        self.assertEqual(job["request"]["contentSearchScopeOrigin"], "fresh_default")

    def test_followup_time_condition_cannot_expand_outside_task_source_scope(self) -> None:
        from app import main as main_app

        job = {
            "request": {
                "sourceScopeKind": "custom", "sourceScopeStart": 120, "sourceScopeEnd": 480,
                "searchScopeKind": "custom", "searchScopeStart": 120, "searchScopeEnd": 480,
            },
            "videoInfo": {"duration": 600},
        }
        resolved = main_app._prepare_content_followup_scope(
            job, main_app.ChatRequest(text="找后半段的洗衣机"), "找后半段的洗衣机",
            {"contextPolicy": "fresh"},
        )
        self.assertEqual((resolved["start"], resolved["end"]), (300.0, 480.0))

    def test_explicit_full_scope_overrides_old_time_words_in_instruction(self) -> None:
        from app import main as main_app

        job = {
            "request": {
                "contentInstruction": "找后半段的洗衣机", "searchScopeKind": "all",
                "searchScopeStart": 0, "searchScopeEnd": 600,
                "contentSearchScopeOrigin": "explicit_ui",
            },
            "videoInfo": {"duration": 600},
        }
        decision = {
            "_parserLlmCalls": 0,
            "intent": {
                "action": "extract_content", "query": "洗衣机", "contextPolicy": "fresh",
                "predicates": [{"id": "p1", "kind": "speech.semantic", "value": "洗衣机"}],
            },
            "capabilityProposal": {"capabilities": ["speech"]},
        }
        intent = main_app._content_intent_from_decision(job, "找后半段的洗衣机", decision)
        self.assertEqual((intent["searchScope"]["start"], intent["searchScope"]["end"]), (0.0, 600.0))
        self.assertEqual(intent["searchScope"]["origin"], "explicit_ui")
        self.assertEqual(
            (main_app._content_execution_scope(job)["start"], main_app._content_execution_scope(job)["end"]),
            (0.0, 600.0),
        )

    def test_source_index_cache_key_does_not_split_by_query_scope(self) -> None:
        from app import main as main_app

        base = main_app.new_job_record(
            job_id="scope_cache_a", source=Path("/tmp/source.mp4"), filename="source.mp4",
            size=100, count="auto", target_seconds="auto", theme="冰箱",
            source_hash="shared-source-index-hash",
        )
        base.update({"recognitionSchemaVersion": 7, "videoInfo": {"duration": 600}})
        narrow = copy.deepcopy(base)
        narrow["request"].update({
            "searchScopeKind": "custom", "searchScopeStart": 0, "searchScopeEnd": 120,
        })
        full = copy.deepcopy(base)
        full["request"].update({
            "searchScopeKind": "all", "searchScopeStart": 0, "searchScopeEnd": 600,
        })
        self.assertEqual(
            main_app.content_index_cache_key(narrow), main_app.content_index_cache_key(full),
        )

    def test_latest_instruction_rebuilds_index_when_scope_cache_key_changed(self) -> None:
        from app import main as main_app

        job_id = "test_scope_index_rebuild"
        job = {
            "id": job_id, "request": {"contentInstruction": "找洗衣机", "searchScopeKind": "all"},
            "videoInfo": {"duration": 643}, "recognitionSchemaVersion": 4,
        }
        main_app.jobs[job_id] = job
        old_index = {"cacheKey": "narrow-scope", "schemaVersion": main_app._content_index_version(job)}
        rebuilt_index = {"cacheKey": "full-scope", "schemaVersion": main_app._content_index_version(job)}
        intent = {"modalities": ["speech"], "queryPlan": {"requiredOperations": []}}
        expected_search = {"id": "search_full", "candidates": [], "candidateCount": 0}
        try:
            with patch.object(main_app, "_parse_content_instruction", return_value=intent), \
                    patch.object(main_app, "_requested_content_modalities", return_value={"speech"}), \
                    patch.object(main_app, "_intent_requires_dialogue_graph", return_value=False), \
                    patch.object(main_app, "_recognition_modality_state", return_value=({"speech"}, {"speech"}, {"speech"})), \
                    patch.object(main_app, "content_index_cache_key", return_value="full-scope"), \
                    patch.object(main_app, "_build_content_index", return_value=rebuilt_index) as rebuild, \
                    patch.object(main_app, "_search_content_index", return_value=expected_search) as search_index:
                search, _, instruction = main_app._search_latest_content_instruction(
                    job_id, old_index, threading.Event(),
                )
            self.assertEqual(search, expected_search)
            self.assertEqual(instruction, "找洗衣机")
            rebuild.assert_called_once()
            self.assertIs(search_index.call_args.args[2], rebuilt_index)
        finally:
            main_app.jobs.pop(job_id, None)

    def test_completed_interview_answerer_followup_survives_low_router_confidence(self) -> None:
        from app import main as main_app

        job_id = "test_completed_answerer_followup"
        job = main_app.new_job_record(
            job_id=job_id, source=Path("/tmp/test-content-source.mp4"), filename="source.mp4",
            size=100, count="auto", target_seconds="auto", theme="人物 A 发言",
            source_hash="completed-answerer-followup-hash",
        )
        job.update({
            "taskMode": "content_extract", "status": "completed",
            "contentSearch": {
                "id": "search_questioner", "instruction": "剪出人物 A 说话的全部片段",
                "status": "confirmed", "candidates": [{
                    "id": "m1", "title": "人物 A 发言", "start": 10, "end": 15,
                    "transcriptExcerpt": "你最大的改变是什么呢？",
                }],
            },
            "videoInfo": {"duration": 90, "width": 1280, "height": 720, "has_audio": True},
        })
        main_app.jobs[job_id] = job
        client = MagicMock()
        # Mirrors the production failure: the semantic action was right, but
        # 0.72 used to be globally converted into a route clarification.
        client.complete_json.return_value = {
            "action": "content_search", "confidence": .72,
            "reason": "用户要求定位回答问题的人，但没有人物标签",
            "capabilityProposal": {
                "capabilities": ["speech"], "capabilityBasis": "explicit_user",
                "explicitEvidenceQuotes": ["回答问题"],
            },
            "intent": {
                "action": "extract_content", "query": "受访者的作答或回应",
                "modalities": ["speech"],
                "predicates": [{
                    "id": "role_turn", "kind": "speech.semantic",
                    "value": "受访者针对问题进行作答或回应",
                }],
            },
        }
        try:
            with patch.object(main_app, "create_llm_client_for_job", return_value=client), \
                    patch.object(main_app, "queue_content_followup") as queue_search, \
                    patch.object(main_app, "save_job"):
                response = main_app.chat_with_job(
                    job_id, main_app.ChatRequest(text="找到回答问题的人的片段"),
                )
            queue_search.assert_called_once()
            pending = queue_search.call_args.kwargs["prepared_intent"]
            self.assertNotIn("_clarification", pending)
            self.assertEqual(pending["modalities"], ["speech"])
            self.assertEqual(pending["executionPlan"]["authorizationSource"], "intent_automatic")
            self.assertEqual(main_app.jobs[job_id]["lastContentChatRoute"]["action"], "content_search")
            self.assertEqual(main_app.jobs[job_id]["lastContentChatRoute"]["confidence"], .72)
            self.assertNotIn("resolution", main_app.jobs[job_id]["lastContentChatRoute"])
        finally:
            main_app.jobs.pop(job_id, None)

    def test_new_llm_query_clears_stale_ui_person_target(self) -> None:
        from app import main as main_app

        job_id = "test_clear_stale_person_target"
        job = main_app.new_job_record(
            job_id=job_id, source=Path("/tmp/test-content-source.mp4"), filename="source.mp4",
            size=100, count="auto", target_seconds="auto", theme="人物 A 发言",
            source_hash="clear-stale-person-target-hash",
        )
        job.update({
            "taskMode": "content_extract", "status": "completed",
            "request": {
                **job["request"],
                "contentSearchTargetPersonId": "person_1",
                "contentSearchPersonTarget": {"personIds": ["person_1"], "matchMode": "any"},
            },
            "contentSearch": {"id": "search_old", "instruction": "人物 A 发言", "candidates": []},
            "videoInfo": {"duration": 90, "width": 1280, "height": 720, "has_audio": True},
        })
        prepared = {
            "action": "extract_content", "query": "受访者回答",
            "modalities": ["speech"],
            "predicates": [{"id": "p1", "kind": "speech.semantic", "value": "受访者回答"}],
            "queryPlan": {"predicates": [{"id": "p1", "kind": "speech.semantic", "value": "受访者回答"}]},
        }
        main_app.jobs[job_id] = job
        try:
            with patch.object(main_app, "submit_analysis_task"), \
                    patch.object(main_app, "append_message"), \
                    patch.object(main_app, "save_job"):
                response = main_app.queue_content_followup(
                    job_id, "找到回答问题的人的片段",
                    main_app.ChatRequest(text="找到回答问题的人的片段"),
                    prepared_intent=prepared,
                )
            self.assertEqual(response["action"], "content-search")
            self.assertNotIn("contentSearchTargetPersonId", main_app.jobs[job_id]["request"])
            self.assertNotIn("contentSearchPersonTarget", main_app.jobs[job_id]["request"])
        finally:
            main_app.jobs.pop(job_id, None)
            main_app.cancel_events.pop(job_id, None)

    def test_llm_predicate_is_automatically_compiled_to_required_capability(self) -> None:
        from app import main as main_app

        job = {
            "request": {"contentInstruction": "找出介绍产品功能的部分", "searchScopeKind": "all"},
            "videoInfo": {"duration": 120},
        }
        client = MagicMock()
        client.complete_json.return_value = {
            "action": "content_search", "confidence": .94,
            "capabilityProposal": {
                "capabilities": ["speech"], "capabilityBasis": "inferred",
                "reason": "产品介绍更可能来自对白",
            },
            "intent": {
                "action": "extract_content", "query": "产品功能", "modalities": ["speech"],
                "predicates": [{"id": "p1", "kind": "speech.semantic", "value": "产品功能"}],
            },
        }
        with patch.object(main_app, "create_llm_client_for_job", return_value=client):
            intent = main_app._parse_content_instruction(job, "找出介绍产品功能的部分")
        client.complete_json.assert_called_once()
        self.assertNotIn("_clarification", intent)
        self.assertEqual(intent["modalities"], ["speech"])
        self.assertEqual(intent["executionPlan"]["recommendedCapabilities"], ["speech"])
        self.assertEqual(intent["executionPlan"]["authorizationSource"], "intent_automatic")

    def test_initial_user_capability_confirmation_overrides_llm_recommendation_only_for_authorization(self) -> None:
        from app import main as main_app

        job = {
            "request": {
                "contentInstruction": "找出产品功能", "searchScopeKind": "all",
                "contentEvidenceMode": "screen_text", "contentAllowedCapabilities": ["ocr"],
            },
            "videoInfo": {"duration": 120},
        }
        client = MagicMock()
        client.complete_json.return_value = {
            "action": "content_search", "confidence": .95,
            "capabilityProposal": {
                "capabilities": ["ocr"], "capabilityBasis": "inferred",
            },
            "intent": {
                "action": "extract_content", "query": "产品功能", "modalities": ["ocr"],
                "predicates": [{"id": "p1", "kind": "screen_text.text", "value": "产品功能"}],
            },
        }
        with patch.object(main_app, "create_llm_client_for_job", return_value=client):
            intent = main_app._parse_content_instruction(job, "找出产品功能")
        self.assertEqual(intent["modalities"], ["ocr"])
        self.assertNotIn("_clarification", intent)
        self.assertEqual(intent["executionPlan"]["authorizationSource"], "user_confirmation")

    def test_explicit_person_speaking_request_auto_selects_complete_capability_set(self) -> None:
        from app import main as main_app

        job = {
            "request": {"contentInstruction": "找出穿绿色短袖的人正在说话的片段", "searchScopeKind": "all"},
            "videoInfo": {"duration": 90},
        }
        client = MagicMock()
        client.complete_json.return_value = {
            "action": "content_search", "confidence": .96,
            "capabilityProposal": {
                "capabilities": ["person", "speech", "visual"],
                "capabilityBasis": "explicit_user",
                "explicitEvidenceQuotes": ["穿绿色短袖的人正在说话"],
            },
            "intent": {
                "action": "extract_content", "query": "绿色短袖的人正在说话",
                "personRefs": ["绿色短袖的人"],
                "predicates": [
                    {"id": "p1", "kind": "person.appearance", "value": "绿色短袖的人", "personRef": "绿色短袖的人", "subject": {"description": "绿色短袖的人", "type": "person"}},
                    {"id": "p2", "kind": "person.speaking", "value": "该人物正在说话", "personRef": "绿色短袖的人"},
                ],
            },
        }
        with patch.object(main_app, "create_llm_client_for_job", return_value=client):
            intent = main_app._parse_content_instruction(job, "找出穿绿色短袖的人正在说话的片段")
        self.assertEqual(set(intent["modalities"]), {"person", "speech", "visual"})
        self.assertEqual(set(intent["executionPlan"]["recommendedCapabilities"]), {"person", "speech", "visual"})
        self.assertNotIn("_clarification", intent)
        self.assertFalse(intent["executionPlan"]["clarificationRequired"])

    def test_visual_person_plus_speech_overlap_is_normalized_to_active_speaker(self) -> None:
        from app import main as main_app

        decision = {
            "capabilityProposal": {
                "capabilities": ["speech", "visual"],
                "capabilityBasis": "explicit_user",
            },
            "intent": {
                "action": "extract_content",
                "query": "戴眼镜穿蓝色衬衫的男生发言",
                "predicates": [
                    {
                        "id": "p1", "kind": "visual.semantic",
                        "value": "画面中出现戴眼镜、穿蓝色衬衫的男生",
                        "subject": {"description": "戴眼镜、穿蓝色衬衫的男生", "type": "person"},
                    },
                    {
                        "id": "p2", "kind": "speech.semantic",
                        "value": "该人物正在发言或说话",
                    },
                ],
                "relations": [{"type": "overlaps", "left": "p1", "right": "p2"}],
            },
        }
        intent = main_app._content_intent_from_decision(
            {"request": {"searchScopeKind": "all"}, "videoInfo": {"duration": 120}},
            "找出戴眼镜穿蓝色衬衫的男生发言的所有片段",
            decision,
            authorized_capabilities=["person", "speech", "visual"],
        )
        self.assertEqual(set(intent["modalities"]), {"person", "speech", "visual"})
        self.assertEqual(
            [item["kind"] for item in intent["queryPlan"]["predicates"]],
            ["person.speaking"],
        )
        self.assertEqual(
            set(intent["queryPlan"]["requiredOperations"]),
            {"person.track_face", "person.active_speaker_link", "speech.semantic_search"},
        )

    def test_person_speech_topic_preserves_topic_and_adds_speaker_attribution(self) -> None:
        from app import main as main_app

        intent = main_app._content_intent_from_decision(
            {"request": {"searchScopeKind": "all"}, "videoInfo": {"duration": 120}},
            "找出戴眼镜穿蓝色衬衫的人提到产品价格的所有片段",
            {
                "capabilityProposal": {
                    "capabilities": ["person", "speech", "visual"],
                    "capabilityBasis": "explicit_user",
                },
                "intent": {
                    "action": "extract_content", "query": "提到产品价格",
                    "personRefs": ["戴眼镜穿蓝色衬衫的人"],
                    "predicates": [
                        {"id": "person", "kind": "visual.semantic", "value": "戴眼镜穿蓝色衬衫的人", "subject": {"description": "戴眼镜穿蓝色衬衫的人", "type": "person"}},
                        {"id": "topic", "kind": "speech.semantic", "value": "该人物提到产品价格"},
                    ],
                    "relations": [{"type": "overlaps", "left": "person", "right": "topic"}],
                },
            },
            authorized_capabilities=["person", "speech", "visual"],
        )
        predicates = intent["queryPlan"]["predicates"]
        topic = next(item for item in predicates if item["id"] == "topic")
        speaker = next(item for item in predicates if item["kind"] == "person.speaking")
        self.assertIn("产品价格", topic["value"])
        self.assertEqual(topic["subjectPersonRef"], "戴眼镜穿蓝色衬衫的人")
        self.assertEqual(topic["subjectPersonPredicateId"], speaker["id"])
        self.assertIn("person.active_speaker_link", intent["queryPlan"]["requiredOperations"])

    def test_person_action_is_marked_for_actor_verification(self) -> None:
        from app import main as main_app

        normalized = main_app._normalize_described_person_speaking_intent({
            "predicates": [
                {"id": "person", "kind": "visual.semantic", "value": "戴眼镜穿蓝色衬衫的人"},
                {"id": "action", "kind": "visual.action", "value": "打开房门"},
            ],
            "relations": [{"type": "overlaps", "left": "person", "right": "action"}],
        }, "找出戴眼镜穿蓝色衬衫的人打开房门的所有片段")
        action = next(item for item in normalized["predicates"] if item["id"] == "action")
        self.assertEqual(action["subjectPersonRef"], "戴眼镜穿蓝色衬衫的人")
        self.assertEqual(action["subjectPersonPredicateId"], "person")

    def test_unconfirmed_described_speaker_pauses_for_person_target(self) -> None:
        from app import main as main_app

        search = main_app._search_content_index(
            "job_person_target",
            {
                "id": "job_person_target",
                "request": {},
                "videoInfo": {"duration": 90},
            },
            {
                "cacheKey": "person-target-index",
                "duration": 90,
                "persons": [
                    {
                        "id": "person_1", "label": "人物 A",
                        "ranges": [{"start": 1, "end": 20}],
                    },
                    {
                        "id": "person_2", "label": "人物 B",
                        "ranges": [{"start": 25, "end": 50}],
                    },
                ],
            },
            "找出蓝色衬衫的人发言的所有片段",
            {
                "action": "extract_content", "query": "蓝色衬衫的人发言",
                "modalities": ["person", "speech", "visual"],
                "resultMode": "exhaustive",
                "predicates": [{
                    "id": "speaker", "kind": "person.speaking",
                    "value": "蓝色衬衫的人发言", "personRef": "蓝色衬衫的人",
                    "required": True,
                }],
                "searchScope": {"start": 0, "end": 90},
            },
            threading.Event(),
        )
        self.assertEqual(search["status"], "needs_clarification")
        self.assertEqual(search["clarification"]["kind"], "person_target")
        self.assertIn("2 个人物簇", search["clarification"]["message"])

    def test_language_alone_does_not_authorize_clothing_speaker_capabilities(self) -> None:
        plan = content_evidence_plan("找到绿色短袖衣服说话的片段")
        self.assertTrue(plan["clarificationRequired"])
        self.assertEqual(plan["allowedCapabilities"], [])

    def test_chat_auto_runs_elliptical_clothing_speaking_request(self) -> None:
        from app import main as main_app

        job_id = "test_explicit_clothing_speaker_chat"
        job = main_app.new_job_record(
            job_id=job_id, source=Path("/tmp/test-content-source.mp4"), filename="source.mp4",
            size=100, count="auto", target_seconds="auto", theme="绿色短袖",
            source_hash="explicit-clothing-speaker-hash",
        )
        job.update({
            "taskMode": "content_extract", "status": "awaiting_content_confirmation",
            "contentSearch": {"id": "search_1", "candidates": []},
            "videoInfo": {"duration": 90, "width": 1280, "height": 720, "has_audio": True},
        })
        main_app.jobs[job_id] = job
        client = MagicMock()
        client.complete_json.return_value = {
            "action": "content_search", "confidence": .96,
            "capabilityProposal": {
                "capabilities": ["visual", "person", "speech"],
                "capabilityBasis": "explicit_user",
                "explicitEvidenceQuotes": ["绿色短袖衣服说话"],
            },
            "intent": {
                "action": "extract_content", "query": "绿色短袖衣服说话",
                "personRefs": ["绿色短袖"],
                "predicates": [{
                    "id": "p1", "kind": "person.speaking", "value": "正在说话",
                    "personRef": "绿色短袖", "required": True,
                }],
            },
        }
        try:
            with patch.object(main_app, "create_llm_client_for_job", return_value=client), \
                    patch.object(main_app, "queue_content_followup") as queue_search, \
                    patch.object(main_app, "save_job"):
                response = main_app.chat_with_job(
                    job_id, main_app.ChatRequest(text="找到绿色短袖衣服说话的片段"),
                )
            queue_search.assert_called_once()
            pending = queue_search.call_args.kwargs["prepared_intent"]
            self.assertNotIn("_clarification", pending)
            self.assertEqual(set(pending["executionPlan"]["recommendedCapabilities"]), {"person", "speech", "visual"})
        finally:
            main_app.jobs.pop(job_id, None)

    def test_pending_legacy_capability_clarification_is_automatically_upgraded(self) -> None:
        from app import main as main_app

        instruction = "找出穿绿色短袖的人正在说话的片段"
        prepared = {
            "action": "extract_content", "query": "绿色短袖的人正在说话",
            "personRefs": ["绿色短袖"],
            "predicates": [{
                "id": "p1", "kind": "person.speaking", "value": "正在说话",
                "personRef": "绿色短袖", "required": True,
            }],
            "modalities": [],
            "_clarification": {"kind": "evidence_type", "message": "请选择"},
        }
        job = {
            "request": {"searchScopeKind": "all", "pendingContentIntent": {
                "instructionId": main_app._content_instruction_id(instruction),
                "intent": prepared,
            }},
            "videoInfo": {"duration": 90},
        }
        intent = main_app._parse_content_instruction(job, instruction)
        self.assertEqual(set(intent["modalities"]), {"person", "speech", "visual"})
        self.assertNotIn("_clarification", intent)
        self.assertEqual(intent["executionPlan"]["authorizationSource"], "intent_automatic")

    def test_old_pending_person_speech_overlap_uses_confirmed_capabilities_after_upgrade(self) -> None:
        from app import main as main_app

        instruction = "找出戴眼镜穿蓝色衬衫的男生发言的所有片段"
        prepared = {
            "action": "extract_content", "query": instruction,
            "modalities": ["speech", "visual"], "resultMode": "exhaustive",
            "predicates": [
                {"id": "p1", "kind": "visual.semantic", "value": "画面中出现戴眼镜、穿蓝色衬衫的男生"},
                {"id": "p2", "kind": "speech.semantic", "value": "该人物正在发言或说话"},
            ],
            "relations": [{"type": "overlaps", "left": "p1", "right": "p2"}],
        }
        job = {
            "request": {
                "searchScopeKind": "all", "contentEvidenceMode": "mixed",
                "contentAllowedCapabilities": ["speech", "person", "visual"],
                "pendingContentIntent": {
                    "instructionId": main_app._content_instruction_id(instruction),
                    "intent": prepared,
                },
            },
            "videoInfo": {"duration": 90},
        }
        intent = main_app._parse_content_instruction(job, instruction)
        self.assertEqual(set(intent["modalities"]), {"speech", "person", "visual"})
        self.assertNotIn("_clarification", intent)
        self.assertEqual(
            [predicate["kind"] for predicate in intent["queryPlan"]["predicates"]],
            ["person.speaking"],
        )

    def test_exact_screen_text_uses_llm_for_semantics_then_local_fast_path(self) -> None:
        from app import main as main_app

        job = {"request": {"searchScopeKind": "all"}, "videoInfo": {"duration": 120}}
        client = MagicMock()
        client.complete_json.return_value = {
            "action": "content_search", "confidence": .97,
            "capabilityProposal": {
                "capabilities": ["ocr"], "capabilityBasis": "explicit_user",
                "explicitEvidenceQuotes": ["屏幕显示“3:1”"],
            },
            "intent": {
                "action": "extract_content", "query": "3:1", "modalities": ["ocr"],
                "predicates": [{"id": "p1", "kind": "screen_text.text", "value": "3:1"}],
            },
        }
        with patch.object(main_app, "create_llm_client_for_job", return_value=client):
            intent = main_app._parse_content_instruction(job, "找出屏幕显示“3:1”的地方")
        client.complete_json.assert_called_once()
        self.assertEqual(intent["modalities"], ["ocr"])
        self.assertEqual(intent["query"], "3:1")
        self.assertEqual(intent["_parserLlmCalls"], 1)
        self.assertTrue(intent["queryPlan"]["fastPathExact"])
        self.assertNotIn("_clarification", intent)

    def test_user_labeled_person_speaking_becomes_active_speaker_predicate(self) -> None:
        from app import main as main_app

        job = {
            "request": {"searchScopeKind": "all"}, "videoInfo": {"duration": 120},
            "contentIndex": {"persons": [{
                "id": "person_1", "label": "女嘉宾", "defaultLabel": "人物 A",
                "primarySpeaker": "Speaker 2", "speakerConfidence": .93,
            }]},
        }
        decision = {
            "intent": {
                "action": "extract_content", "query": "女嘉宾说话",
                "modalities": ["person", "speech", "visual"],
                "predicates": [{
                    "id": "p1", "kind": "person.speaking", "value": "女嘉宾说话",
                    "personRef": "女嘉宾", "required": True,
                }],
            },
            "capabilityProposal": {
                "capabilities": ["person", "speech", "visual"], "capabilityBasis": "explicit_user",
            },
        }
        intent = main_app._content_intent_from_decision(
            job, "把女嘉宾说话的镜头剪出来", decision,
            authorized_capabilities=["person", "speech", "visual"],
        )
        self.assertTrue(any(
            item["kind"] == "person.speaking" and item["personRef"] == "女嘉宾"
            for item in intent["queryPlan"]["predicates"]
        ))

    def test_known_person_exhaustive_speaking_query_uses_llm_semantic_router(self) -> None:
        from app import main as main_app

        job = {
            "request": {
                "searchScopeKind": "all", "contentEvidenceMode": "mixed",
                "contentAllowedCapabilities": ["person", "speech", "visual"],
            },
            "videoInfo": {"duration": 120},
            "contentIndex": {"persons": [{
                "id": "person_1", "label": "绿衣哥", "defaultLabel": "人物 A",
                "userLabeled": True, "primarySpeaker": None,
            }]},
        }
        client = MagicMock()
        client.complete_json.return_value = {
            "action": "content_search", "confidence": .98,
            "capabilityProposal": {
                "capabilities": ["person", "speech", "visual"],
                "capabilityBasis": "explicit_user",
                "explicitEvidenceQuotes": ["绿衣哥说话的全部片段"],
            },
            "intent": {
                "action": "extract_content", "query": "绿衣哥说话",
                "modalities": ["person", "speech", "visual"], "resultMode": "exhaustive",
                "personRefs": ["绿衣哥"],
                "predicates": [{
                    "id": "person_speaking", "kind": "person.speaking",
                    "value": "绿衣哥说话", "personRef": "绿衣哥", "required": True,
                }],
            },
        }
        with patch.object(main_app, "create_llm_client_for_job", return_value=client):
            intent = main_app._parse_content_instruction(job, "剪出绿衣哥说话的全部片段")
        client.complete_json.assert_called_once()
        self.assertEqual(intent["_parserMode"], "llm_router")
        self.assertEqual(intent["_parserLlmCalls"], 1)
        self.assertEqual(intent["resultMode"], "exhaustive")
        self.assertEqual(intent["queryPlan"]["result"]["mode"], "exhaustive")
        self.assertEqual(
            [item["kind"] for item in intent["queryPlan"]["predicates"]],
            ["person.speaking"],
        )

    def test_unlinked_labeled_person_speaking_requires_visual_verification(self) -> None:
        from app import main as main_app

        job = {
            "request": {"searchScopeKind": "all"}, "videoInfo": {"duration": 120},
            "contentIndex": {"persons": [{
                "id": "person_1", "label": "绿衣哥", "defaultLabel": "人物 A",
                "userLabeled": True, "primarySpeaker": None,
            }]},
        }
        decision = {
            "intent": {
                "action": "extract_content", "query": "绿衣哥说话",
                "modalities": ["person", "speech"],
                "predicates": [{
                    "id": "p1", "kind": "person.speaking", "value": "绿衣哥说话",
                    "personRef": "绿衣哥", "required": True,
                }],
            },
            "capabilityProposal": {"capabilities": ["person", "speech"]},
        }
        insufficient = main_app._content_intent_from_decision(
            job, "剪出绿衣哥说话的全部片段", decision,
            authorized_capabilities=["person", "speech"],
        )
        self.assertEqual(set(insufficient["modalities"]), {"person", "speech", "visual"})
        self.assertEqual(
            set(insufficient["executionPlan"]["recommendedCapabilities"]),
            {"person", "speech", "visual"},
        )
        self.assertNotIn("_clarification", insufficient)
        self.assertEqual(insufficient["executionPlan"]["authorizationSource"], "user_preference_plus_required")
        authorized = main_app._content_intent_from_decision(
            job, "剪出绿衣哥说话的全部片段", decision,
            authorized_capabilities=["person", "speech", "visual"],
        )
        self.assertEqual(set(authorized["modalities"]), {"person", "speech", "visual"})

    def test_incomplete_manual_capabilities_are_completed_before_indexing(self) -> None:
        from app import main as main_app

        decision = {
            "intent": {
                "action": "extract_content", "query": "绿色衣服的人说话", "modalities": ["visual"],
                "personRefs": ["绿色衣服"],
                "predicates": [
                    {"id": "p1", "kind": "person.appearance", "value": "绿色衣服", "personRef": "绿色衣服"},
                    {"id": "p2", "kind": "person.speaking", "value": "正在说话", "personRef": "绿色衣服"},
                ],
            },
            "capabilityProposal": {"capabilities": ["visual", "person"]},
        }
        intent = main_app._content_intent_from_decision(
            {"request": {}, "videoInfo": {"duration": 90}},
            "找出绿色衣服的人说话的全部片段", decision,
            authorized_capabilities=["visual"],
        )
        self.assertEqual(set(intent["modalities"]), {"visual", "person", "speech"})
        self.assertFalse(intent["executionPlan"]["clarificationRequired"])
        self.assertEqual(
            set(intent["executionPlan"]["recommendedCapabilities"]),
            {"visual", "person", "speech"},
        )
        self.assertNotIn("_clarification", intent)
        self.assertEqual(intent["executionPlan"]["authorizationSource"], "user_preference_plus_required")

    def test_person_catalog_applies_job_label_without_mutating_index(self) -> None:
        from app import main as main_app

        index = {
            "persons": [{
                "id": "person_1", "label": "人物 A", "start": 2, "end": 8,
                "ranges": [{"start": 2, "end": 4}], "trackCount": 3, "confidence": .8,
            }],
            "faceSpeakerLinks": [{
                "personId": "person_1", "speaker": "Speaker 2", "confidence": .93, "turnCount": 4,
            }],
        }
        catalog = main_app._content_person_catalog({
            "id": "job_1", "personLabels": {"person_1": {"label": "女嘉宾", "updatedAt": "now"}},
        }, index)
        self.assertEqual(catalog[0]["label"], "女嘉宾")
        self.assertEqual(catalog[0]["primarySpeaker"], "Speaker 2")
        self.assertEqual(index["persons"][0]["label"], "人物 A")

    def test_person_catalog_prefers_user_confirmed_speaker_link(self) -> None:
        from app import main as main_app

        index = {
            "persons": [{
                "id": "person_1", "label": "人物 A", "start": 2, "end": 8,
                "ranges": [{"start": 2, "end": 4}], "trackCount": 3, "confidence": .8,
            }],
            "faceSpeakerLinks": [{
                "personId": "person_1", "speaker": "Speaker 2", "confidence": .95,
            }],
        }
        catalog = main_app._content_person_catalog({
            "id": "job_1",
            "personLabels": {"person_1": {"label": "绿衣哥", "updatedAt": "now"}},
            "personSpeakerLinks": {"person_1": {"speaker": "Speaker 1", "updatedAt": "later"}},
        }, index)
        self.assertEqual(catalog[0]["primarySpeaker"], "Speaker 1")
        self.assertEqual(catalog[0]["speakerAssociationMethod"], "active_speaker_user_confirmed")
        self.assertFalse(catalog[0]["speakerReviewRequired"])

    def test_person_catalog_applies_reversible_merge_overlay(self) -> None:
        from app import main as main_app

        index = {"persons": [
            {"id": "person_1", "label": "人物 A", "ranges": [{"start": 1, "end": 2}], "trackCount": 1, "confidence": .7},
            {"id": "person_2", "label": "人物 B", "ranges": [{"start": 4, "end": 6}], "trackCount": 2, "confidence": .9},
        ]}
        catalog = main_app._content_person_catalog({
            "id": "job_1", "personMergeAliases": {"person_2": "person_1"},
        }, index)
        self.assertEqual(len(catalog), 1)
        self.assertEqual(catalog[0]["sourcePersonIds"], ["person_1", "person_2"])
        self.assertEqual(catalog[0]["appearanceSeconds"], 3)
        self.assertEqual(catalog[0]["trackCount"], 3)
        self.assertTrue(catalog[0]["userMerged"])

    def test_person_catalog_exposes_face_anchor_duplicate_evidence(self) -> None:
        from app import main as main_app

        catalog = main_app._content_person_catalog({"id": "job_1"}, {"persons": [{
            "id": "person_1", "label": "人物 A",
            "ranges": [{"start": 1, "end": 3}], "trackCount": 2, "confidence": .86,
            "faceAnchorCount": 5, "duplicateReviewRecommended": True,
            "possibleDuplicatePersonIds": ["person_2"], "duplicateSimilarity": .73,
            "duplicateEvidenceType": "face_anchor",
        }]})
        self.assertEqual(catalog[0]["faceAnchorCount"], 5)
        self.assertTrue(catalog[0]["duplicateReviewRecommended"])
        self.assertEqual(catalog[0]["possibleDuplicatePersonIds"], ["person_2"])
        self.assertEqual(catalog[0]["duplicateEvidenceType"], "face_anchor")

    def test_person_catalog_does_not_apply_overlays_from_obsolete_index(self) -> None:
        from app import main as main_app

        index = {"cacheKey": "new-index", "persons": [
            {"id": "person_1", "label": "人物 A", "ranges": [{"start": 1, "end": 2}]},
            {"id": "person_2", "label": "人物 B", "ranges": [{"start": 4, "end": 5}]},
        ]}
        catalog = main_app._content_person_catalog({
            "id": "job_1", "personIdentityIndexCacheKey": "old-index",
            "personLabels": {"person_1": {"label": "旧人物"}},
            "personMergeAliases": {"person_2": "person_1"},
        }, index)
        self.assertEqual([item["id"] for item in catalog], ["person_1", "person_2"])
        self.assertEqual(catalog[0]["label"], "人物 A")

    def test_reindex_clears_stale_person_identity_corrections(self) -> None:
        from app import main as main_app

        job = {
            "contentIndex": {"cacheKey": "old-index"},
            "personMergeRevision": 3,
            "personMergeAliases": {"person_2": "person_1"},
            "personLabels": {"person_1": {"label": "嘉宾"}},
            "personMergeHistory": [{"revision": 2}],
            "request": {
                "contentSearchTargetPersonId": "person_1",
                "contentSearchPersonTarget": {"personIds": ["person_1"], "matchMode": "any"},
            },
        }
        changed = main_app._reset_stale_person_identity_overlays(
            job, {"cacheKey": "new-index"},
        )
        self.assertTrue(changed)
        self.assertNotIn("personMergeAliases", job)
        self.assertNotIn("personLabels", job)
        self.assertNotIn("personMergeHistory", job)
        self.assertNotIn("contentSearchTargetPersonId", job["request"])
        self.assertNotIn("contentSearchPersonTarget", job["request"])
        self.assertEqual(job["personIdentityIndexCacheKey"], "new-index")
        self.assertEqual(job["personMergeRevision"], 4)

    def test_person_catalog_reassigns_selected_ranges_into_durable_new_card(self) -> None:
        from app import main as main_app

        index = {"persons": [{
            "id": "person_1", "label": "人物 A",
            "ranges": [{"start": 1, "end": 2}, {"start": 4, "end": 6}],
            "trackCount": 2, "confidence": .9,
        }]}
        catalog = main_app._content_person_catalog({
            "id": "job_1",
            "personRangeAssignments": {"person_1_range_0001": "person_user_1"},
            "personLabels": {"person_user_1": {"label": "人物 B", "updatedAt": "now"}},
        }, index)
        by_id = {item["id"]: item for item in catalog}
        self.assertEqual([item["id"] for item in by_id["person_1"]["ranges"]], ["person_1_range_0000"])
        self.assertEqual([item["id"] for item in by_id["person_user_1"]["ranges"]], ["person_1_range_0001"])
        self.assertEqual(by_id["person_user_1"]["label"], "人物 B")
        self.assertEqual(by_id["person_user_1"]["sourcePersonIds"], ["person_1"])

        regenerated = {"persons": [{
            "id": "person_1", "label": "人物 A",
            "ranges": [{"start": 1, "end": 2}, {"start": 3.9, "end": 6.1}],
            "trackCount": 2, "confidence": .9,
        }]}
        catalog = main_app._content_person_catalog({
            "id": "job_1",
            "personIdentityConstraints": [{
                "operation": "reassign_ranges", "sourcePersonId": "person_1",
                "targetPersonId": "person_user_1", "ranges": [{"start": 4, "end": 6}],
            }],
        }, regenerated)
        by_id = {item["id"]: item for item in catalog}
        self.assertEqual(by_id["person_user_1"]["ranges"][0]["start"], 3.9)

    def test_candidate_events_group_nearby_person_matches_without_changing_ids(self) -> None:
        from app import main as main_app

        candidates = [
            {"id": "one", "start": 1, "end": 2, "matchedPersonIds": ["person_1"], "matchedPersonLabels": ["人物 A"]},
            {"id": "two", "start": 3, "end": 4, "matchedPersonIds": ["person_1"], "matchedPersonLabels": ["人物 A"]},
            {"id": "three", "start": 20, "end": 21, "matchedPersonIds": ["person_1"], "matchedPersonLabels": ["人物 A"]},
        ]
        events = main_app.content_candidate_events(candidates, "person_edit")
        self.assertEqual([item["matchIds"] for item in events], [["one", "two"], ["three"]])
        self.assertEqual(events[0]["clipDuration"], 2)
        self.assertEqual(events[0]["sourceSpanDuration"], 3)

    def test_speaker_confirmation_options_fall_back_to_all_diarized_speakers(self) -> None:
        from app import main as main_app

        options = main_app._speaker_confirmation_options({
            "speechUnits": [
                {"start": .6, "end": 2.4, "text": "Hello there", "speakers": ["Speaker 1"]},
                {"start": 9.6, "end": 12.0, "text": "Any ideas?", "speakers": ["Speaker 2"]},
            ],
        }, [{
            "speaker": "Speaker 2", "start": 9.6, "end": 12.0,
            "transcript": "Any ideas?", "keep": False, "score": .25,
        }], person_id="person_2")
        self.assertEqual([item["speakerRef"] for item in options], ["Speaker 1", "Speaker 2"])
        self.assertTrue(all(item["personId"] == "person_2" for item in options))
        self.assertEqual(options[0]["start"], .6)

    def test_speaker_confirmation_options_require_a_resolved_person(self) -> None:
        from app import main as main_app

        options = main_app._speaker_confirmation_options({
            "speechUnits": [{
                "start": .6, "end": 2.4, "text": "Hello there",
                "speakers": ["Speaker 1"],
            }],
        }, [], person_id="")

        self.assertEqual(options, [])

    def test_generic_speaking_predicate_inherits_related_labeled_person(self) -> None:
        from app import main as main_app

        resolved = main_app._resolve_person_speaking_predicates({
            "id": "job_1",
            "personLabels": {"person_1": {"label": "戴红领巾的女孩"}},
        }, {
            "persons": [{
                "id": "person_1", "label": "人物 A",
                "ranges": [{"start": 1, "end": 8}],
            }],
        }, {
            "predicates": [
                {
                    "id": "appearance", "kind": "person.appearance",
                    "value": "戴红领巾的女孩",
                },
                {
                    "id": "speaking", "kind": "person.speaking",
                    "value": "该人物正在说话或发言",
                },
            ],
            "relations": [{
                "type": "overlaps", "left": "appearance", "right": "speaking",
            }],
        })

        speaking = next(
            item for item in resolved["predicates"] if item["id"] == "speaking"
        )
        self.assertEqual(speaking["personId"], "person_1")
        self.assertEqual(speaking["personRef"], "戴红领巾的女孩")
        self.assertEqual(speaking["linkedPersonPredicateId"], "appearance")
        self.assertEqual(speaking["resolutionStatus"], "speaker_link_requires_review")

    def test_legacy_empty_person_speaker_clarification_becomes_person_selection(self) -> None:
        from app import main as main_app

        normalized = main_app._normalize_active_speaker_clarification({
            "contentIndex": {
                "persons": [{"id": "person_1"}, {"id": "person_2"}],
            },
            "request": {},
        }, {
            "status": "needs_clarification",
            "clarification": {
                "kind": "active_speaker_link",
                "options": [{"speakerRef": "Speaker 1", "personId": ""}],
            },
        })

        self.assertEqual(normalized["clarification"]["kind"], "person_target")
        self.assertEqual(normalized["clarification"]["options"], [])
        self.assertIn("2 个人物簇", normalized["clarification"]["message"])

    def test_default_anonymous_person_can_be_confirmed_to_a_speaker(self) -> None:
        from app import main as main_app

        job_id = "test_default_person_speaker_confirmation"
        job = main_app.new_job_record(
            job_id=job_id, source=Path("/tmp/test-content-source.mp4"), filename="source.mp4",
            size=100, count="auto", target_seconds="auto", theme="人物 B",
            source_hash="default-person-speaker-hash",
        )
        index = {
            "persons": [{
                "id": "person_2", "label": "人物 B", "start": 1, "end": 8,
                "ranges": [{"start": 1, "end": 8}], "trackCount": 4, "confidence": .9,
            }],
            "speechUnits": [{
                "id": "speech_1", "start": .6, "end": 7.8,
                "text": "Hello", "speakers": ["Speaker 1"],
            }],
        }
        main_app.jobs[job_id] = job
        expected = {"action": "content-search-reused", "reused": True, "job": {"id": job_id}}
        try:
            with patch.object(main_app, "_load_content_person_index", return_value=index), \
                    patch.object(main_app, "_reuse_content_person_appearance_tracks", return_value=expected) as reuse_timeline, \
                    patch.object(main_app, "queue_content_followup") as queue_search, \
                    patch.object(main_app, "save_job"):
                response = main_app.confirm_content_person_speaker(
                    job_id, main_app.PersonSpeakerRequest(
                        personId="person_2", speakerRef="Speaker 1",
                    ),
                )
            self.assertEqual(response, expected)
            queue_search.assert_not_called()
            self.assertEqual(reuse_timeline.call_args.kwargs["reuse_kind"], "speaker_timeline")
            prepared = reuse_timeline.call_args.args[2]
            self.assertEqual(
                [item["kind"] for item in prepared["queryPlan"]["predicates"]],
                ["person.speaking"],
            )
            self.assertEqual(
                main_app.jobs[job_id]["personSpeakerLinks"]["person_2"]["speaker"],
                "Speaker 1",
            )
            self.assertEqual(
                main_app.jobs[job_id]["contentIndex"]["persons"][0]["primarySpeaker"],
                "Speaker 1",
            )
        finally:
            main_app.jobs.pop(job_id, None)

    def test_default_anonymous_person_can_be_selected_as_search_target(self) -> None:
        from app import main as main_app

        job_id = "test_default_person_target_confirmation"
        job = main_app.new_job_record(
            job_id=job_id, source=Path("/tmp/test-content-source.mp4"), filename="source.mp4",
            size=100, count="auto", target_seconds="auto", theme="人物 A",
            source_hash="default-person-target-hash",
        )
        index = {
            "persons": [{
                "id": "person_1", "label": "人物 A", "start": 1, "end": 8,
                "ranges": [{"start": 1, "end": 8}], "trackCount": 4, "confidence": .9,
            }],
        }
        main_app.jobs[job_id] = job
        expected = {"action": "content-search-reused", "reused": True, "job": {"id": job_id}}
        try:
            with patch.object(main_app, "_load_content_person_index", return_value=index), \
                    patch.object(main_app, "_reuse_content_person_appearance_tracks", return_value=expected) as reuse_tracks, \
                    patch.object(main_app, "queue_content_followup") as queue_search, \
                    patch.object(main_app, "save_job"):
                response = main_app.select_content_person_target(
                    job_id, main_app.PersonTargetRequest(personId="person_1"),
                )
            self.assertEqual(response, expected)
            self.assertEqual(
                main_app.jobs[job_id]["request"]["contentSearchTargetPersonId"],
                "person_1",
            )
            queue_search.assert_not_called()
            prepared = reuse_tracks.call_args.args[2]
            self.assertEqual(
                [item["kind"] for item in prepared["queryPlan"]["predicates"]],
                ["person.appearance"],
            )
            self.assertEqual(
                main_app.jobs[job_id]["request"]["contentSearchPersonTarget"]["activity"],
                "appearance",
            )
        finally:
            main_app.jobs.pop(job_id, None)

    def test_multiple_person_targets_preserve_original_search_instruction(self) -> None:
        from app import main as main_app

        job_id = "test_multiple_person_target_confirmation"
        job = main_app.new_job_record(
            job_id=job_id, source=Path("/tmp/test-content-source.mp4"), filename="source.mp4",
            size=100, count="auto", target_seconds="auto", theme="找出两个人同框的画面",
            source_hash="multiple-person-target-hash",
        )
        instruction = "找出两个人同框的画面"
        intent = {
            "query": instruction, "modalities": ["person"],
            "predicates": [{
                "id": "unknown_person", "kind": "person.appearance",
                "value": "目标人物", "required": True,
            }],
            "executionPlan": {"allowedCapabilities": ["person"]},
            "_clarification": {"kind": "person_target", "question": "请确认目标人物"},
        }
        job["request"].update({
            "contentInstruction": instruction,
            "pendingContentIntent": {
                "instructionId": main_app._content_instruction_id(instruction), "intent": intent,
            },
        })
        job["contentSearch"] = {
            "instruction": instruction, "intent": intent,
            "executionPlan": {"allowedCapabilities": ["person"], "evidenceMode": "person"},
        }
        index = {"persons": [
            {"id": "person_1", "label": "人物 A", "ranges": [{"start": 1, "end": 8}]},
            {"id": "person_2", "label": "人物 B", "ranges": [{"start": 2, "end": 9}]},
        ]}
        main_app.jobs[job_id] = job
        expected = {"action": "content-search-reused", "reused": True, "job": {"id": job_id}}
        try:
            with patch.object(main_app, "_load_content_person_index", return_value=index), \
                    patch.object(main_app, "_reuse_content_person_appearance_tracks", return_value=expected) as reuse_tracks, \
                    patch.object(main_app, "queue_content_followup") as queue_search, \
                    patch.object(main_app, "save_job"):
                response = main_app.select_content_person_target(
                    job_id, main_app.PersonTargetRequest(
                        personIds=["person_1", "person_2"], matchMode="all",
                    ),
                )
            self.assertEqual(response, expected)
            queue_search.assert_not_called()
            self.assertEqual(reuse_tracks.call_args.args[1], instruction)
            prepared = reuse_tracks.call_args.args[2]
            self.assertNotIn("_clarification", prepared)
            self.assertEqual(prepared["personTarget"]["personIds"], ["person_1", "person_2"])
            self.assertEqual(prepared["personTarget"]["matchMode"], "all")
            self.assertEqual(prepared["personTarget"]["activity"], "appearance")
            _, prepared_any, _ = main_app._bind_content_person_target(
                job, index["persons"], "any", "appearance",
            )
            self.assertEqual(prepared_any["personTarget"]["matchMode"], "any")
            self.assertNotEqual(
                content_query_cache_key("same-person-index", prepared),
                content_query_cache_key("same-person-index", prepared_any),
                "任一人物与所有人物不能复用同一个检索缓存",
            )
            self.assertEqual(main_app.jobs[job_id]["request"]["contentSearchPersonTarget"], {
                "personIds": ["person_1", "person_2"], "matchMode": "all",
                "activity": "appearance",
            })
            self.assertNotIn("contentSearchTargetPersonId", main_app.jobs[job_id]["request"])
        finally:
            main_app.jobs.pop(job_id, None)

    def test_multiple_person_targets_preserve_action_subject_constraint(self) -> None:
        from app import main as main_app

        instruction = "找出戴帽子的人打开房门的所有片段"
        intent = {
            "query": instruction, "modalities": ["person", "visual"],
            "resultMode": "exhaustive",
            "predicates": [
                {"id": "person", "kind": "person.appearance", "value": "戴帽子的人", "personRef": "戴帽子的人"},
                {
                    "id": "action", "kind": "visual.action", "value": "打开房门",
                    "subjectPersonRef": "戴帽子的人", "subjectPersonPredicateId": "person",
                },
            ],
            "relations": [{"type": "overlaps", "left": "person", "right": "action"}],
        }
        job = {
            "request": {"contentInstruction": instruction, "pendingContentIntent": {"intent": intent}},
            "contentSearch": {"instruction": instruction, "intent": intent},
        }
        _, prepared, _ = main_app._bind_content_person_target(job, [
            {"id": "person_1", "label": "人物 A"},
            {"id": "person_2", "label": "人物 B"},
        ], "all")
        action = next(item for item in prepared["queryPlan"]["predicates"] if item["id"] == "action")
        self.assertEqual(action["subjectPersonRef"], "人物 A、人物 B")
        self.assertNotIn("subjectPersonId", action)
        self.assertIn("person.verify_action_actor", prepared["queryPlan"]["requiredOperations"])
        self.assertEqual(prepared["personTarget"]["matchMode"], "all")

    def test_multiple_person_targets_bind_speech_subject_to_every_selected_person(self) -> None:
        from app import main as main_app

        speech = {
            "id": "speech", "kind": "speech.semantic", "value": "正在讨论这个问题",
            "subjectPersonRef": "目标人物",
        }
        job = {
            "request": {
                "contentInstruction": "找出两个人对话的片段",
                "pendingContentIntent": {"intent": {
                    "query": "找出两个人对话的片段",
                    "modalities": ["person", "speech"],
                    "predicates": [speech], "relations": [],
                }},
            },
            "contentSearch": {},
        }
        _, prepared, _ = main_app._bind_content_person_target(job, [
            {"id": "person_1", "label": "人物 A"},
            {"id": "person_2", "label": "人物 B"},
        ], "all")

        targets = [
            item for item in prepared["queryPlan"]["predicates"]
            if item["kind"] == "person.speaking"
        ]
        self.assertEqual(len(targets), 2)
        self.assertEqual(prepared["personTarget"]["activity"], "speaking")
        self.assertEqual(prepared["personTarget"]["matchMode"], "all")
        self.assertTrue(all(
            any(
                relation.get("left") == target["id"]
                and relation.get("right") == "speech"
                for relation in prepared["queryPlan"]["relations"]
            )
            for target in targets
        ))
        self.assertNotEqual(prepared["queryPlan"].get("clarification", {}).get("kind"), "query_relation")

    def test_llm_router_failure_only_asks_for_clarification(self) -> None:
        from app import main as main_app

        job_id = "test_content_router_failure"
        job = main_app.new_job_record(
            job_id=job_id, source=Path("/tmp/test-content-source.mp4"), filename="source.mp4",
            size=100, count="auto", target_seconds="auto", theme="做家务", source_hash="router-failure-hash",
        )
        job.update({
            "taskMode": "content_extract", "status": "awaiting_content_confirmation",
            "contentSearch": {"id": "search_1", "instruction": "做家务", "candidates": []},
            "videoInfo": {"duration": 30, "width": 1280, "height": 720, "has_audio": True},
        })
        main_app.jobs[job_id] = job
        client = MagicMock()
        client.complete_json.side_effect = RuntimeError("offline")
        try:
            with patch.object(main_app, "create_llm_client_for_job", return_value=client), \
                    patch.object(main_app, "queue_content_followup") as queue_search, \
                    patch.object(main_app, "save_job"):
                response = main_app.chat_with_job(
                    job_id, main_app.ChatRequest(text="那后面呢？"),
                )
            self.assertEqual(response["action"], "workflow-confirmation")
            queue_search.assert_not_called()
            self.assertEqual(main_app.jobs[job_id]["status"], "awaiting_content_confirmation")
            self.assertIn("AI 意图判断暂时不可用", response["routingConfirmation"]["message"])
        finally:
            main_app.jobs.pop(job_id, None)

    def test_llm_editing_action_does_not_fall_through_to_search(self) -> None:
        from app import main as main_app

        job_id = "test_content_editing_route"
        job = main_app.new_job_record(
            job_id=job_id, source=Path("/tmp/test-content-source.mp4"), filename="source.mp4",
            size=100, count="auto", target_seconds="auto", theme="做家务", source_hash="editing-route-hash",
        )
        original_search = {"id": "search_1", "instruction": "做家务", "candidates": [{"id": "m1"}]}
        job.update({
            "taskMode": "content_extract", "status": "awaiting_content_confirmation",
            "contentSearch": copy.deepcopy(original_search),
            "videoInfo": {"duration": 30, "width": 1280, "height": 720, "has_audio": True},
        })
        main_app.jobs[job_id] = job
        client = MagicMock()
        client.complete_json.return_value = {
            "action": "editing_action", "confidence": .95,
            "answer": "你希望调整已有候选的排列方式。",
            "intent": {"action": "update_style", "query": "按动作顺序排列"},
            "capabilityProposal": {"capabilities": []},
        }
        try:
            with patch.object(main_app, "create_llm_client_for_job", return_value=client), \
                    patch.object(main_app, "queue_content_followup") as queue_search, \
                    patch.object(main_app, "save_job"):
                response = main_app.chat_with_job(
                    job_id, main_app.ChatRequest(text="这些片段按动作顺序排列"),
                )
            self.assertEqual(response["action"], "editing-action-guidance")
            queue_search.assert_not_called()
            self.assertEqual(main_app.jobs[job_id]["contentSearch"], original_search)
        finally:
            main_app.jobs.pop(job_id, None)

    def test_prepared_llm_intent_is_reused_without_another_model_call(self) -> None:
        from app import main as main_app

        instruction = "找出做饭的画面"
        prepared = {
            "action": "extract_content", "query": "做饭", "modalities": ["visual"],
            "parserVersion": CONTENT_INTENT_PARSER_VERSION,
            "searchScope": {"kind": "all", "start": 0, "end": 30, "empty": False},
        }
        job = {
            "request": {"pendingContentIntent": {
                "instructionId": main_app._content_instruction_id(instruction),
                "intent": prepared,
            }},
            "videoInfo": {"duration": 30},
        }
        with patch.object(main_app, "create_llm_client_for_job") as create_client:
            intent = main_app._parse_content_instruction(job, instruction)
        create_client.assert_not_called()
        self.assertEqual(intent, prepared)

    def test_explicit_evidence_button_reuses_llm_intent_without_second_call(self) -> None:
        from app import main as main_app

        job_id = "test_content_explicit_evidence"
        base_intent = {
            "action": "extract_content", "query": "做饭", "modalities": [],
            "_clarification": {"kind": "evidence_type", "message": "请选择"},
        }
        job = main_app.new_job_record(
            job_id=job_id, source=Path("/tmp/test-content-source.mp4"), filename="source.mp4",
            size=100, count="auto", target_seconds="auto", theme="做饭", source_hash="button-hash",
        )
        job.update({
            "taskMode": "content_extract", "status": "awaiting_content_confirmation",
            "contentSearch": {"id": "search_1", "instruction": "找出做饭的片段", "intent": base_intent, "candidates": []},
            "videoInfo": {"duration": 30, "width": 1280, "height": 720, "has_audio": True},
        })
        main_app.jobs[job_id] = job
        expected = {"action": "content-search", "job": {"id": job_id}}
        try:
            with patch.object(main_app, "queue_content_followup", return_value=expected) as queue_search, \
                    patch.object(main_app, "create_llm_client_for_job") as create_client:
                response = main_app.chat_with_job(job_id, main_app.ChatRequest(
                    text="找出做饭的片段", evidenceMode="visual", allowedCapabilities=["visual"],
                ))
            self.assertEqual(response, expected)
            create_client.assert_not_called()
            prepared = queue_search.call_args.kwargs["prepared_intent"]
            self.assertEqual(prepared["modalities"], ["visual"])
            self.assertNotIn("_clarification", prepared)
        finally:
            main_app.jobs.pop(job_id, None)

    def test_requested_modalities_are_strictly_driven_by_search_intent(self) -> None:
        from app import main as main_app

        balanced = {"request": {"recognitionProfile": "balanced"}}
        self.assertEqual(
            main_app._requested_content_modalities(balanced, {"modalities": ["speech"]}),
            {"speech"},
        )
        full = {"request": {"recognitionProfile": "full"}}
        self.assertEqual(
            main_app._requested_content_modalities(full, {"modalities": ["speech"]}),
            {"speech"},
        )

    def test_dialogue_graph_is_required_only_by_dialogue_semantics(self) -> None:
        from app import main as main_app

        self.assertFalse(main_app._intent_requires_dialogue_graph({
            "modalities": ["speech", "visual"],
            "predicates": [{"id": "topic", "kind": "speech.semantic", "value": "冰箱"}],
        }))
        self.assertFalse(main_app._intent_requires_dialogue_graph({
            "modalities": ["visual"],
            "predicates": [{"id": "object", "kind": "visual.object", "value": "冰箱"}],
        }))
        self.assertTrue(main_app._intent_requires_dialogue_graph({
            "modalities": ["speech"],
            "predicates": [{"id": "answer", "kind": "speech.dialogue_role", "value": "回答"}],
        }))
        self.assertTrue(main_app._intent_requires_dialogue_graph({
            "modalities": ["speech", "ocr"],
            "predicates": [{"id": "question", "kind": "question.evidence", "value": "采访问题"}],
        }))

    def test_unbound_object_cannot_enter_person_or_active_speaker_pipeline(self) -> None:
        from app import main as main_app

        intent = main_app._content_intent_from_decision(
            {"request": {"searchScopeKind": "all"}, "videoInfo": {"duration": 90}},
            "找到和目标产品相关的片段",
            {"intent": {
                "action": "extract_content", "query": "目标产品",
                "personRefs": [],
                "predicates": [
                    {
                        "id": "object", "kind": "person.appearance",
                        "value": "画面中出现目标产品", "personRef": "目标产品",
                        "subject": {"description": "目标产品", "type": "object"},
                    },
                    {
                        "id": "speech", "kind": "speech.semantic",
                        "value": "对白提到目标产品", "subjectPersonRef": "目标产品",
                    },
                    {
                        "id": "speaker", "kind": "person.speaking",
                        "value": "目标产品", "personRef": "目标产品",
                    },
                ],
                "relations": [{"type": "overlaps", "left": "speaker", "right": "speech"}],
            }},
        )
        predicates = intent["queryPlan"]["predicates"]
        self.assertEqual(
            {item["kind"] for item in predicates},
            {"visual.semantic", "speech.semantic"},
        )
        self.assertNotIn("person", intent["modalities"])
        self.assertFalse(main_app._intent_requires_dialogue_graph(intent))
        speech = next(item for item in predicates if item["kind"] == "speech.semantic")
        self.assertNotIn("subjectPersonRef", speech)

    def test_speech_index_reuse_does_not_require_a_dialogue_graph(self) -> None:
        from app import main as main_app

        job = {
            "id": "plain-topic-search", "sourceHash": "plain-topic-source",
            "recognitionSchemaVersion": main_app.RECOGNITION_SCHEMA_VERSION,
            "request": {},
        }
        cached = {
            "schemaVersion": main_app._content_index_version(job),
            "recognitionCompletedModalities": ["speech"],
            "recognitionAttemptedModalities": ["speech"],
            "recognitionAvailableModalities": ["speech"],
            "transcriptSegments": [{"id": "s1", "start": 0, "end": 1, "text": "介绍冰箱功能"}],
            "speechUnits": [{"id": "speech_1", "modality": "speech", "start": 0, "end": 1}],
        }
        with patch.object(main_app, "_read_content_index", return_value=cached), \
                patch.object(main_app, "_content_progress") as progress, \
                patch.object(main_app, "_build_dialogue_graph") as build_graph:
            result = main_app._build_content_index_unlocked(
                "plain-topic-search", job, threading.Event(),
                required_modalities={"speech"}, require_dialogue_graph=False,
            )
        self.assertIs(result, cached)
        build_graph.assert_not_called()
        self.assertIn("已复用", progress.call_args.args[3])

    def test_recognition_enrichment_merges_only_new_modality_state(self) -> None:
        from app import main as main_app

        partial = {
            "recognitionCompletedModalities": ["speech"],
            "recognitionAttemptedModalities": ["speech"],
            "recognitionAvailableModalities": ["speech"],
            "speechUnits": [{"id": "speech_1"}],
            "embeddingIndexes": {},
        }
        main_app._merge_recognition_enrichment(partial, {
            "ocrUnits": [],
            "recognitionAttemptedModalities": ["ocr"],
            "recognitionCompletedModalities": ["ocr"],
            "recognitionAvailableModalities": ["ocr"],
            "embeddingIndexes": {},
        }, requested={"speech", "ocr"})
        self.assertEqual(partial["recognitionCompletedModalities"], ["ocr", "speech"])
        self.assertEqual(partial["speechUnits"], [{"id": "speech_1"}])
        self.assertEqual(partial["recognitionSkippedModalities"], ["audio", "person", "visual"])

    def test_auto_generation_requires_every_candidate_to_be_reliable(self) -> None:
        from app import main as main_app

        job_id = "test_content_auto_generate"
        job = main_app.new_job_record(
            job_id=job_id, source=Path("/tmp/test-content-source.mp4"), filename="source.mp4",
            size=100, count="auto", target_seconds="auto", theme="产品演示", source_hash="auto-hash",
        )
        job.update({
            "taskMode": "content_extract", "status": "awaiting_content_confirmation",
            "request": {**job.get("request", {}), "contentAutoGenerate": True},
            "contentSearch": {"id": "search_auto", "candidates": []},
        })
        main_app.jobs[job_id] = job
        reliable = {
            "id": "match_1", "confidence": .9, "boundaryConfidence": .85,
            "evidenceRefs": [{"type": "speech", "id": "speech_1"}], "requiresReview": False,
            "calibrated": True, "scoreVersion": "content-score-v2-separated",
        }
        try:
            with patch.object(main_app, "confirm_content_search") as confirm:
                self.assertTrue(main_app._auto_generate_content_search_if_ready(
                    job_id, {"id": "search_auto", "candidates": [reliable]},
                ))
                confirm.assert_called_once()
            with patch.object(main_app, "save_job"), patch.object(main_app, "confirm_content_search") as confirm:
                self.assertFalse(main_app._auto_generate_content_search_if_ready(
                    job_id, {"id": "search_auto", "candidates": [{**reliable, "confidence": .7}]},
                ))
                confirm.assert_not_called()
                self.assertEqual(main_app.jobs[job_id]["contentSearch"]["autoGenerateStatus"], "review_required")
            with patch.object(main_app, "save_job"), patch.object(main_app, "confirm_content_search") as confirm:
                self.assertFalse(main_app._auto_generate_content_search_if_ready(
                    job_id, {"id": "search_auto", "candidates": [{**reliable, "calibrated": False}]},
                ))
                confirm.assert_not_called()
        finally:
            main_app.jobs.pop(job_id, None)

    def test_confirmation_builds_event_edl_and_dispatches_existing_renderer(self) -> None:
        from app import main as main_app

        job_id = "test_content_confirmation"
        job = main_app.new_job_record(
            job_id=job_id,
            source=Path("/tmp/test-content-source.mp4"),
            filename="source.mp4",
            size=100,
            count="auto",
            target_seconds="auto",
            theme="离线模式",
            source_hash="content-test-hash",
        )
        job.update({
            "taskMode": "content_extract",
            "status": "awaiting_content_confirmation",
            "videoInfo": {"duration": 30, "width": 1280, "height": 720, "has_audio": True},
            "contentSearch": {
                "id": "search_test",
                "instruction": "截取离线模式介绍",
                "status": "ready",
                "candidates": [{
                    "id": "match_1", "unitId": "speech_1", "start": 5, "end": 9,
                    "duration": 4, "title": "离线模式", "score": 92,
                    "reason": "对白直接匹配", "transcriptExcerpt": "产品支持离线模式",
                    "speechUnits": [{"start": 5, "end": 9, "text": "产品支持离线模式"}],
                }],
            },
            "brief": {"objective": "按描述截取内容", "focus": ["离线模式"], "includeRules": [], "excludeRules": []},
            "editingIntent": {"hardConstraints": {"includeRules": [], "excludeRules": []}, "style": {"allowReorder": False}},
        })
        main_app.jobs[job_id] = job
        request = main_app.ContentSearchConfirmRequest(
            searchId="search_test", matchIds=["match_1"], outputMode="single_reel",
        )
        try:
            with patch.object(main_app, "save_job"), patch.object(main_app, "append_message"), patch.object(main_app, "submit_render_task") as submit:
                response = main_app.confirm_content_search(job_id, request)
            updated = response["job"]
            self.assertEqual(updated["status"], "running")
            self.assertEqual(updated["stage"], "rendering")
            self.assertEqual(updated["eventGroups"][0]["assemblyStrategy"], "content_query")
            self.assertEqual(updated["eventGroups"][0]["segments"][0]["start"], 5.0)
            snapshot = updated["contentSearch"]["confirmationSnapshot"]
            self.assertEqual(snapshot["selectedMatchIds"], ["match_1"])
            self.assertEqual(snapshot["selectedCandidates"][0]["transcriptExcerpt"], "产品支持离线模式")
            submit.assert_called_once()
            self.assertEqual(submit.call_args.args[0], job_id)
            self.assertIs(submit.call_args.args[1], main_app.run_confirmed_render)
            self.assertEqual(submit.call_args.args[3], "single_reel")
        finally:
            main_app.jobs.pop(job_id, None)
            main_app.cancel_events.pop(job_id, None)

    def test_person_confirmation_has_one_clear_clip_to_composition_handoff(self) -> None:
        from app import main as main_app

        job_id = "test_person_composition_handoff"
        job = main_app.new_job_record(
            job_id=job_id, source=Path("/tmp/test-person-source.mp4"), filename="people.mp4",
            size=100, count="auto", target_seconds="auto", theme="人物出镜", source_hash="person-handoff",
        )
        job.update({
            "taskMode": "content_extract", "workflowKind": "person_edit",
            "status": "awaiting_content_confirmation",
            "videoInfo": {"duration": 30, "width": 1280, "height": 720, "has_audio": True},
            "contentSearch": {
                "id": "search_person", "instruction": "提取人物 A 的全部出镜", "status": "ready",
                "candidates": [{
                    "id": "person_match", "start": 5, "end": 9, "duration": 4,
                    "title": "人物 A 出镜", "score": 96, "evidenceType": "person",
                }],
            },
            "brief": {"objective": "按人物剪辑", "focus": [], "includeRules": [], "excludeRules": []},
            "editingIntent": {"hardConstraints": {"includeRules": [], "excludeRules": []}, "style": {"allowReorder": False}},
        })
        main_app.jobs[job_id] = job
        request = main_app.ContentSearchConfirmRequest(
            searchId="search_person", matchIds=["person_match"], outputMode="single_reel",
        )
        try:
            with patch.object(main_app, "save_job"), \
                 patch.object(main_app, "append_message") as append, \
                 patch.object(main_app, "submit_render_task") as submit:
                response = main_app.confirm_content_search(job_id, request)
            updated = response["job"]
            self.assertEqual(updated["detail"], "已确认出镜片段，正在合成人物出镜视频")
            self.assertEqual(updated["currentAction"], "正在合成已确认的出镜片段")
            messages = [call.args[2] for call in append.call_args_list]
            self.assertIn("已确认 1 个出镜片段，开始合成人物出镜视频。", messages)
            self.assertTrue(any("合成阶段不会再增删片段" in message for message in messages))
            self.assertEqual(submit.call_args.args[13]["displayName"], "人物剪辑")
        finally:
            main_app.jobs.pop(job_id, None)
            main_app.cancel_events.pop(job_id, None)

    def test_duplicate_content_composition_is_blocked_before_render(self) -> None:
        from fastapi import HTTPException
        from app import main as main_app

        job_id = "test_duplicate_content_composition"
        with tempfile.TemporaryDirectory() as temporary_directory:
            output_directory = Path(temporary_directory)
            output_file = output_directory / "v001-content.mp4"
            output_file.write_bytes(b"playable-placeholder")
            candidate = {
                "id": "match_1", "start": 5, "end": 9, "duration": 4,
                "title": "离线模式", "score": 92, "reason": "对白直接匹配",
            }
            segments = content_matches_to_segments([candidate])
            job = main_app.new_job_record(
                job_id=job_id, source=Path("/tmp/test-content-source.mp4"),
                filename="source.mp4", size=100, count="auto", target_seconds="auto",
                theme="离线模式", source_hash="duplicate-content-hash",
            )
            job.update({
                "taskMode": "content_extract", "status": "awaiting_content_confirmation",
                "outputDirectory": str(output_directory),
                "contentSearch": {
                    "id": "search_duplicate", "instruction": "截取离线模式介绍",
                    "status": "ready", "candidates": [candidate],
                },
                "outputVersions": [{
                    "id": "version_1", "number": 1, "outputMode": "single_reel",
                    "subtitleMode": "none", "outputs": [{
                        "filename": output_file.name, "segments": segments,
                    }],
                }],
                "outputs": [{"filename": output_file.name, "segments": segments}],
                "messages": [{"id": "before", "role": "assistant", "text": "已保存为 V1", "kind": "result"}],
            })
            main_app.jobs[job_id] = job
            try:
                with patch.object(main_app, "save_job"), patch.object(main_app, "append_message") as append, \
                        patch.object(main_app, "submit_render_task") as submit:
                    with self.assertRaises(HTTPException) as blocked:
                        main_app.confirm_content_search(job_id, main_app.ContentSearchConfirmRequest(
                            searchId="search_duplicate", matchIds=["match_1"], outputMode="single_reel",
                        ))
                self.assertEqual(blocked.exception.status_code, 409)
                self.assertEqual(blocked.exception.detail["code"], "duplicate_content_composition")
                self.assertEqual(blocked.exception.detail["existingVersionNumber"], 1)
                self.assertEqual(blocked.exception.detail["filename"], output_file.name)
                self.assertEqual(main_app.jobs[job_id]["status"], "awaiting_content_confirmation")
                append.assert_not_called()
                submit.assert_not_called()
            finally:
                main_app.jobs.pop(job_id, None)
                main_app.cancel_events.pop(job_id, None)

    def test_content_signature_ignores_random_subtitle_ids(self) -> None:
        from app import main as main_app

        job = {"sourceHash": "same-source"}
        outputs = [[{"start": 1.0, "end": 3.5, "playbackRate": 1}]]
        base_cue = {
            "outputIndex": 0, "start": 0, "end": 2.5,
            "sourceStart": 1, "sourceEnd": 3.5, "text": "同一条字幕",
            "speakerLabel": "说话人 B", "showSpeakerLabel": True,
        }
        left = main_app._content_composition_signature(
            job, outputs, output_mode="single_reel", subtitle_mode="burn", subtitle_style="clean",
            subtitle_draft={"id": "draft_random_1", "cues": [{"id": "cue_random_1", **base_cue}]},
        )
        right = main_app._content_composition_signature(
            job, outputs, output_mode="single_reel", subtitle_mode="burn", subtitle_style="clean",
            subtitle_draft={"id": "draft_random_2", "cues": [{"id": "cue_random_2", **base_cue}]},
        )
        changed = main_app._content_composition_signature(
            job, outputs, output_mode="single_reel", subtitle_mode="burn", subtitle_style="clean",
            subtitle_draft={"id": "draft_random_3", "cues": [{"id": "cue_random_3", **base_cue, "text": "字幕内容已修改"}]},
        )
        self.assertEqual(left, right)
        self.assertNotEqual(left, changed)

    def test_incomplete_exhaustive_search_can_render_only_after_acknowledgement(self) -> None:
        from fastapi import HTTPException
        from app import main as main_app

        job_id = "test_incomplete_content_confirmation"
        job = main_app.new_job_record(
            job_id=job_id, source=Path("/tmp/test-content-source.mp4"), filename="source.mp4",
            size=100, count="auto", target_seconds="auto", theme="全部回答",
            source_hash="incomplete-confirm-hash",
        )
        job.update({
            "taskMode": "content_extract", "status": "awaiting_content_confirmation",
            "contentSearch": {
                "id": "search_incomplete", "instruction": "找到所有回答", "resultMode": "exhaustive",
                "completeness": {"status": "incomplete", "pendingCount": 0},
                "candidates": [{
                    "id": "match_1", "start": 5, "end": 9, "duration": 4,
                    "title": "回答", "score": 88, "reason": "当前匹配",
                }],
            },
        })
        main_app.jobs[job_id] = job
        try:
            with self.assertRaises(HTTPException) as blocked:
                main_app.confirm_content_search(job_id, main_app.ContentSearchConfirmRequest(
                    searchId="search_incomplete", matchIds=["match_1"],
                ))
            self.assertEqual(blocked.exception.status_code, 409)
            with patch.object(main_app, "save_job"), patch.object(main_app, "append_message"), \
                    patch.object(main_app, "submit_render_task"):
                response = main_app.confirm_content_search(job_id, main_app.ContentSearchConfirmRequest(
                    searchId="search_incomplete", matchIds=["match_1"], acknowledgeIncomplete=True,
                ))
            self.assertTrue(response["job"]["contentSearch"]["incompleteCoverageAcknowledged"])
            self.assertEqual(response["job"]["status"], "running")
        finally:
            main_app.jobs.pop(job_id, None)
            main_app.cancel_events.pop(job_id, None)

    def test_llm_order_recommendation_is_grounded_deduplicated_and_non_mutating(self) -> None:
        from app import main as main_app

        job_id = "test_content_llm_order"
        job = main_app.new_job_record(
            job_id=job_id, source=Path("/tmp/test-content-source.mp4"), filename="source.mp4",
            size=100, count="auto", target_seconds="auto", theme="产品故事", source_hash="order-hash",
        )
        candidates = [
            {"id": "match_1", "start": 5, "end": 9, "duration": 4, "title": "结果", "reason": "展示结果"},
            {"id": "match_2", "start": 15, "end": 20, "duration": 5, "title": "起因", "reason": "交代背景"},
        ]
        job.update({
            "taskMode": "content_extract", "status": "awaiting_content_confirmation",
            "contentSearch": {"id": "search_order", "instruction": "按故事逻辑排列", "candidates": candidates},
        })
        main_app.jobs[job_id] = job
        client = MagicMock()
        client.complete_json.return_value = {
            "ordered_ids": ["match_2", "match_2", "invented"],
            "reason": "先交代起因，再展示结果。",
        }
        try:
            with patch.object(main_app, "create_llm_client_for_job", return_value=client), patch.object(main_app, "save_job"):
                response = main_app.recommend_content_search_order(
                    job_id,
                    main_app.ContentSearchOrderRequest(searchId="search_order", matchIds=["match_1", "match_2"]),
                )
            self.assertEqual(response["orderedMatchIds"], ["match_2", "match_1"])
            self.assertEqual(response["reason"], "先交代起因，再展示结果。")
            self.assertEqual(main_app.jobs[job_id]["contentSearch"]["candidates"], candidates)
            client.complete_json.assert_called_once()
            client.cancel.assert_called_once()
        finally:
            main_app.active_ark_clients.pop(job_id, None)
            main_app.jobs.pop(job_id, None)

    def test_ai_plan_confirmation_preserves_recommended_match_order(self) -> None:
        from app import main as main_app

        job_id = "test_content_ai_plan_confirmation"
        job = main_app.new_job_record(
            job_id=job_id, source=Path("/tmp/test-content-source.mp4"), filename="source.mp4",
            size=100, count="auto", target_seconds="auto", theme="产品故事", source_hash="ai-plan-hash",
        )
        job.update({
            "taskMode": "content_extract", "status": "awaiting_content_confirmation",
            "videoInfo": {"duration": 30, "width": 1280, "height": 720, "has_audio": True},
            "contentSearch": {
                "id": "search_ai_plan", "instruction": "按故事逻辑排列", "status": "ready",
                "candidates": [
                    {"id": "match_1", "start": 5, "end": 9, "duration": 4, "title": "结果", "score": 90},
                    {"id": "match_2", "start": 15, "end": 20, "duration": 5, "title": "起因", "score": 88},
                ],
            },
            "brief": {"objective": "按描述截取内容", "focus": [], "includeRules": [], "excludeRules": []},
            "editingIntent": {"hardConstraints": {"includeRules": [], "excludeRules": []}, "style": {"allowReorder": True}},
        })
        main_app.jobs[job_id] = job
        request = main_app.ContentSearchConfirmRequest(
            searchId="search_ai_plan", matchIds=["match_2", "match_1"], outputMode="single_reel",
            orderMode="ai_plan", orderReason="先起因后结果",
        )
        try:
            with patch.object(main_app, "save_job"), patch.object(main_app, "append_message"), patch.object(main_app, "submit_render_task") as submit:
                response = main_app.confirm_content_search(job_id, request)
            updated = response["job"]
            self.assertEqual([group["contentMatchId"] for group in updated["eventGroups"]], ["match_2", "match_1"])
            self.assertEqual(updated["llmOrder"]["reason"], "先起因后结果")
            self.assertEqual(updated["contentSearch"]["orderStrategy"], "llm_recommend")
            self.assertEqual(submit.call_args.args[11], "ai_plan")
        finally:
            main_app.jobs.pop(job_id, None)
            main_app.cancel_events.pop(job_id, None)

    def test_feedback_excludes_units_and_restore_needs_no_model_call(self) -> None:
        from app import main as main_app

        job_id = "test_content_feedback"
        job = main_app.new_job_record(
            job_id=job_id, source=Path("/tmp/test-content-source.mp4"), filename="source.mp4",
            size=100, count="auto", target_seconds="auto", theme="离线模式", source_hash="feedback-hash",
        )
        old_search = {"id": "old_search", "instruction": "旧请求", "candidates": [], "candidateCount": 0}
        job.update({
            "taskMode": "content_extract", "status": "awaiting_content_confirmation",
            "contentSearchHistory": [old_search],
            "contentSearch": {
                "id": "new_search", "instruction": "新请求", "candidateCount": 1,
                "defaultSelectedIds": ["m1"],
                "candidates": [{"id": "m1", "unitId": "u1", "matchedUnitIds": ["u1"], "selected": True}],
            },
        })
        main_app.jobs[job_id] = job
        try:
            with patch.object(main_app, "save_job"):
                response = main_app.content_search_feedback(
                    job_id, main_app.ContentSearchFeedbackRequest(matchId="m1", verdict="not_relevant"),
                )
                self.assertEqual(response["job"]["contentSearch"]["candidateCount"], 0)
                self.assertEqual(response["job"]["contentSearchFeedback"]["excludedUnitIds"], ["u1"])
                restored = main_app.restore_content_search(job_id, "old_search")
            self.assertEqual(restored["search"]["restoredFrom"], "old_search")
            self.assertEqual(restored["job"]["status"], "awaiting_content_confirmation")
        finally:
            main_app.jobs.pop(job_id, None)
            main_app.cancel_events.pop(job_id, None)

    def test_missed_content_feedback_queues_forced_dense_search(self) -> None:
        from app import main as main_app

        job_id = "test_content_missed"
        job = main_app.new_job_record(
            job_id=job_id, source=Path("/tmp/test-content-source.mp4"), filename="source.mp4",
            size=100, count="auto", target_seconds="auto", theme="红色盒子", source_hash="missed-hash",
        )
        job.update({
            "taskMode": "content_extract", "status": "awaiting_content_confirmation",
            "contentSearch": {"id": "search_1", "instruction": "红色盒子", "candidates": [], "candidateCount": 0},
        })
        main_app.jobs[job_id] = job
        try:
            with patch.object(main_app, "save_job"), patch.object(main_app, "submit_analysis_task") as submit:
                response = main_app.content_search_feedback(
                    job_id, main_app.ContentSearchFeedbackRequest(verdict="missed_content"),
                )
            self.assertTrue(response["queued"])
            self.assertTrue(main_app.jobs[job_id]["request"]["contentSearchForceDense"])
            submit.assert_called_once_with(job_id, main_app.run_content_search_only, job_id)
        finally:
            main_app.jobs.pop(job_id, None)
            main_app.cancel_events.pop(job_id, None)

    def test_boundary_feedback_recomputes_without_accepting_user_times(self) -> None:
        from app import main as main_app

        job_id = "test_content_boundary_retry"
        job = main_app.new_job_record(
            job_id=job_id, source=Path("/tmp/test-content-source.mp4"), filename="source.mp4",
            size=100, count="auto", target_seconds="auto", theme="人物 A 发言",
            source_hash="boundary-retry-hash",
        )
        original = {
            "id": "match_1", "start": 2.06, "end": 37.7, "duration": 35.64,
            "boundarySource": "diarization_speaker_segments", "selected": True,
        }
        job.update({
            "taskMode": "content_extract", "status": "awaiting_content_confirmation",
            "contentSearch": {
                "id": "search_1", "instruction": "人物 A 正在说话",
                "candidates": [copy.deepcopy(original)], "candidateCount": 1,
            },
        })
        main_app.jobs[job_id] = job
        try:
            with patch.object(main_app, "save_job"), patch.object(main_app, "submit_analysis_task") as submit:
                response = main_app.content_search_feedback(
                    job_id,
                    main_app.ContentSearchFeedbackRequest(
                        matchId="match_1", verdict="boundary_incorrect",
                        evidenceIds=["speech_1"],
                    ),
                )
            self.assertTrue(response["queued"])
            self.assertTrue(main_app.jobs[job_id]["request"]["contentSearchForceDense"])
            self.assertEqual(
                main_app.jobs[job_id]["contentSearch"]["candidates"][0]["start"],
                original["start"],
            )
            self.assertEqual(
                main_app.jobs[job_id]["contentSearchFeedback"]["boundaryRetryMatchIds"],
                ["match_1"],
            )
            target = main_app.jobs[job_id]["contentSearchFeedback"]["boundaryRefinementTargets"][0]
            self.assertEqual(target["status"], "pending")
            self.assertEqual((target["start"], target["end"]), (2.06, 37.7))
            entry = main_app.jobs[job_id]["contentSearchFeedback"]["entries"][0]
            self.assertEqual(entry["resolution"]["status"], "queued")
            submit.assert_called_once_with(job_id, main_app.run_content_search_only, job_id)
        finally:
            main_app.jobs.pop(job_id, None)
            main_app.cancel_events.pop(job_id, None)

    def test_manual_boundary_save_and_reset_do_not_rerun_search(self) -> None:
        from app import main as main_app

        job_id = "test_content_manual_boundary"
        job = main_app.new_job_record(
            job_id=job_id, source=Path("/tmp/test-content-source.mp4"), filename="source.mp4",
            size=100, count="auto", target_seconds="auto", theme="人物 A 发言",
            source_hash="manual-boundary-hash",
        )
        original = {
            "id": "match_1", "start": 2.06, "end": 37.7, "duration": 35.64,
            "boundarySource": "diarization_speaker_segments", "boundaryStatus": "automatic",
            "selected": True,
        }
        job.update({
            "taskMode": "content_extract", "status": "awaiting_content_confirmation",
            "videoInfo": {"duration": 90, "frame_rate": 25},
            "contentSearch": {
                "id": "search_1", "instruction": "人物 A 正在说话",
                "candidates": [copy.deepcopy(original)], "candidateCount": 1,
            },
        })
        main_app.jobs[job_id] = job
        try:
            with patch.object(main_app, "save_job"), patch.object(main_app, "submit_analysis_task") as submit:
                response = main_app.update_content_search_boundary(
                    job_id,
                    main_app.ContentSearchBoundaryRequest(
                        searchId="search_1", matchId="match_1", start=2.02, end=37.66,
                    ),
                )
                adjusted = response["job"]["contentSearch"]["candidates"][0]
                self.assertEqual((adjusted["start"], adjusted["end"]), (2.02, 37.66))
                self.assertEqual(adjusted["boundarySource"], "user_manual_trim")
                self.assertTrue(adjusted["manualBoundary"])
                self.assertEqual(adjusted["automaticBoundary"]["start"], original["start"])
                self.assertTrue(adjusted["selected"])

                restored = main_app.update_content_search_boundary(
                    job_id,
                    main_app.ContentSearchBoundaryRequest(
                        searchId="search_1", matchId="match_1", operation="reset",
                    ),
                )["job"]["contentSearch"]["candidates"][0]
            self.assertEqual((restored["start"], restored["end"]), (2.06, 37.7))
            self.assertEqual(restored["boundarySource"], "diarization_speaker_segments")
            self.assertNotIn("manualBoundary", restored)
            submit.assert_not_called()
        finally:
            main_app.jobs.pop(job_id, None)
            main_app.cancel_events.pop(job_id, None)

    def test_manual_boundary_rejects_ranges_shorter_than_one_source_frame(self) -> None:
        from app import main as main_app

        job_id = "test_content_manual_boundary_invalid"
        job = main_app.new_job_record(
            job_id=job_id, source=Path("/tmp/test-content-source.mp4"), filename="source.mp4",
            size=100, count="auto", target_seconds="auto", theme="人物 A 发言",
            source_hash="manual-boundary-invalid-hash",
        )
        job.update({
            "taskMode": "content_extract", "videoInfo": {"duration": 30, "frame_rate": 25},
            "contentSearch": {"id": "search_1", "candidates": [{"id": "m1", "start": 1, "end": 2}]},
        })
        main_app.jobs[job_id] = job
        try:
            with self.assertRaisesRegex(Exception, "至少晚于开始时间一帧"):
                main_app.update_content_search_boundary(
                    job_id,
                    main_app.ContentSearchBoundaryRequest(
                        searchId="search_1", matchId="m1", start=1.0, end=1.02,
                    ),
                )
        finally:
            main_app.jobs.pop(job_id, None)
            main_app.cancel_events.pop(job_id, None)

    def test_manual_range_is_added_to_active_exploration_review_draft(self) -> None:
        from app import main as main_app

        job_id = "test_content_manual_range"
        job = main_app.new_job_record(
            job_id=job_id, source=Path("/tmp/test-content-source.mp4"), filename="source.mp4",
            size=100, count="auto", target_seconds="auto", theme="人物发言",
            source_hash="manual-range-hash",
        )
        job.update({
            "taskMode": "content_extract", "status": "awaiting_content_confirmation",
            "videoInfo": {"duration": 90, "frame_rate": 25},
            "manualSelection": {"start": 20, "end": 26, "duration": 6},
            "contentSearch": {
                "id": "search_1", "instruction": "人物发言",
                "candidates": [{
                    "id": "match_1", "start": 2, "end": 5, "duration": 3,
                    "reviewStatus": "kept", "selected": True,
                }],
                "defaultSelectedIds": ["match_1"],
            },
        })
        main_app.jobs[job_id] = job
        try:
            with patch.object(main_app, "save_job"):
                response = main_app.add_content_search_manual_range(
                    job_id,
                    main_app.ContentSearchManualRangeRequest(
                        searchId="search_1", start=20, end=26, title="补充回答",
                    ),
                )
            added = response["match"]
            search = main_app.jobs[job_id]["contentSearch"]
            self.assertEqual((added["start"], added["end"], added["title"]), (20, 26, "补充回答"))
            self.assertEqual(added["boundarySource"], "user_manual_range")
            self.assertIn(added["id"], search["reviewDraft"]["selectedMatchIds"])
            self.assertIn(added["id"], search["reviewDraft"]["orderedMatchIds"])
            self.assertEqual(search["candidateCount"], 2)
            self.assertNotIn("manualSelection", main_app.jobs[job_id])
        finally:
            main_app.jobs.pop(job_id, None)
            main_app.cancel_events.pop(job_id, None)

    def test_public_content_job_rewrites_legacy_highlight_completion_copy(self) -> None:
        from app import main as main_app

        job = main_app.new_job_record(
            job_id="test_content_public_copy", source=Path("/tmp/test-content-source.mp4"),
            filename="source.mp4", size=100, count="auto", target_seconds="auto",
            theme="人物说话", source_hash="content-public-copy-hash",
        )
        output = {
            "filename": "v001-content.mp4", "title": "内容视频", "duration": 12.0,
            "segmentCount": 3, "segments": [{"start": 1, "end": 3}],
        }
        job.update({
            "taskMode": "content_extract", "status": "completed",
            "detail": "已生成 1 条高光成片，共 3 个高光事件、3 个镜头",
            "contentSearch": {"orderMode": "source"},
            "messages": [{
                "role": "assistant", "kind": "result",
                "text": "已保存为 V1：将 3 个高光事件、3 个镜头合成为 1 条视频。 已校验 3/3 个确认片段，媒体完整性检查已通过。",
            }, {
                "role": "user", "kind": "revision", "text": "重新选择已经分析好的镜头并合成",
            }, {
                "role": "assistant", "kind": "revision",
                "text": "已返回事件审核。可以重新选择高光事件，并从“镜头候选”中增删或移动镜头。",
            }, {
                "role": "assistant", "kind": "guidance",
                "text": "可以说“单条成片目标改成 60 秒”“删除救援事件第 2 个镜头”。",
            }],
            "outputs": [output],
            "outputVersions": [{"id": "v001", "number": 1, "outputMode": "single_reel", "outputs": [output]}],
            "currentOutputVersionId": "v001",
        })
        visible = main_app.public_job(job)
        self.assertNotIn("高光", visible["detail"])
        self.assertEqual(visible["detail"], "已将 3 个已确认内容片段合成为 1 条视频")
        self.assertIn("按源视频时间顺序将 3 个已确认内容片段", visible["messages"][0]["text"])
        self.assertNotIn("高光事件", visible["messages"][0]["text"])
        self.assertEqual(visible["messages"][1]["text"], "重新选择已经检索到的内容片段")
        self.assertIn("已返回内容片段确认", visible["messages"][2]["text"])
        self.assertNotIn("高光事件", visible["messages"][2]["text"])
        self.assertIn("旧路由误判", visible["messages"][3]["text"])
        self.assertNotIn("单条成片目标", visible["messages"][3]["text"])

    def test_public_content_workflow_exposes_review_phase_and_real_capability_steps(self) -> None:
        from app import main as main_app

        job = main_app.new_job_record(
            job_id="test_content_workflow", source=Path("/tmp/test-content-source.mp4"),
            filename="source.mp4", size=100, count="auto", target_seconds="auto",
            theme="绿衣人物说话", source_hash="content-workflow-hash",
        )
        job.update({
            "taskMode": "content_extract",
            "status": "awaiting_content_confirmation",
            "stage": "content_confirmation",
            "contentSearch": {
                "instruction": "找出绿衣人物说话的片段",
                "candidates": [{"id": "match_1", "start": 1, "end": 3}],
                "coverageStatus": "partial",
                "executionPlan": {
                    "allowedCapabilities": ["person", "speech", "visual"],
                    "warnings": ["主动说话人分析只覆盖了部分范围。"],
                },
            },
        })
        visible = main_app.public_job(job)
        workflow = visible["workflow"]
        self.assertEqual(workflow["phase"], "review")
        self.assertEqual(workflow["state"], "ready")
        self.assertEqual(
            [step["label"] for step in workflow["steps"]],
            ["读取素材", "识别人物并关联轨迹", "识别对白", "建立画面索引", "检索目标内容", "确认内容片段", "生成内容视频"],
        )
        self.assertEqual(workflow["steps"][-2]["state"], "current")
        self.assertEqual(workflow["actionRequired"]["kind"], "coverage_incomplete")
        self.assertFalse(workflow["actionRequired"]["blocking"])

    def test_content_workflow_marks_each_capability_from_actual_recognition_state(self) -> None:
        from app import main as main_app

        job = main_app.new_job_record(
            job_id="test_content_capability_progress", source=Path("/tmp/test-content-source.mp4"),
            filename="source.mp4", size=100, count="auto", target_seconds="auto",
            theme="人物发言", source_hash="content-capability-progress-hash",
        )
        job.update({
            "taskMode": "content_extract", "status": "running", "stage": "content_recognition",
            "recognition": {"processedModalities": ["speech"]},
            "contentSearch": {"executionPlan": {
                "allowedCapabilities": ["person", "speech", "visual"],
            }},
        })
        workflow = main_app.content_workflow_snapshot(job)
        states = {step["label"]: step["state"] for step in workflow["steps"]}
        self.assertEqual(states["读取素材"], "complete")
        self.assertEqual(states["识别对白"], "complete")
        self.assertEqual(states["识别人物并关联轨迹"], "current")
        self.assertEqual(states["建立画面索引"], "pending")
        self.assertEqual(states["检索目标内容"], "pending")

        job["stage"] = "content_transcription"
        refreshed = main_app.content_workflow_snapshot(job)
        refreshed_states = {step["label"]: step["state"] for step in refreshed["steps"]}
        self.assertEqual(refreshed_states["识别对白"], "current")

    def test_content_reedit_returns_to_match_confirmation_instead_of_event_review(self) -> None:
        from app import main as main_app

        job_id = "test_content_reedit"
        job = main_app.new_job_record(
            job_id=job_id, source=Path("/tmp/test-content-source.mp4"), filename="source.mp4",
            size=100, count="auto", target_seconds="auto", theme="人物说话",
            source_hash="content-reedit-hash",
        )
        job.update({
            "taskMode": "content_extract", "status": "completed",
            "contentSearch": {
                "id": "search_1", "status": "confirmed", "confirmedMatchIds": ["match_1"],
                "candidates": [{"id": "match_1", "start": 1, "end": 4, "title": "人物发言"}],
            },
            "eventGroups": [{
                "id": "content_event_1", "segments": [{"id": "segment_1", "start": 1, "end": 4}],
            }],
            "confirmedGroupIds": ["content_event_1"],
            "outputs": [{"filename": "v001-content.mp4", "duration": 3}],
            "outputVersions": [{
                "id": "v001", "number": 1, "strategyKey": "content_extract",
                "outputs": [{"filename": "v001-content.mp4", "duration": 3}],
            }],
        })
        main_app.jobs[job_id] = job
        try:
            with patch.object(main_app, "save_job"):
                reopened = main_app.reopen_job_for_editing(job_id)["job"]
            self.assertEqual(reopened["status"], "awaiting_content_confirmation")
            self.assertEqual(reopened["stage"], "content_confirmation")
            self.assertEqual(reopened["contentSearch"]["defaultSelectedIds"], ["match_1"])
            self.assertIn("内容片段确认", reopened["detail"])
            self.assertNotIn("事件审核", reopened["detail"])
            self.assertIn("已有版本仍可预览和下载", reopened["messages"][-1]["text"])
        finally:
            main_app.jobs.pop(job_id, None)

    def test_new_content_query_bypasses_event_editing_state_after_render(self) -> None:
        from app import main as main_app

        job_id = "test_content_search_after_render"
        job = main_app.new_job_record(
            job_id=job_id, source=Path("/tmp/test-content-source.mp4"), filename="source.mp4",
            size=100, count="auto", target_seconds="auto", theme="绿衣人物",
            source_hash="content-search-after-render-hash",
        )
        job.update({
            "taskMode": "content_extract", "status": "awaiting_confirmation",
            "videoInfo": {"duration": 90, "width": 1280, "height": 720, "has_audio": True},
            "contentSearch": {"id": "search_old", "instruction": "绿衣人物", "candidates": []},
            "eventGroups": [{"id": "content_event_1", "segments": [{"start": 1, "end": 3}]}],
            "outputs": [{"filename": "v001-content.mp4", "duration": 2}],
        })
        main_app.jobs[job_id] = job
        decision = {
            "action": "content_search", "confidence": .99,
            "intent": {
                "action": "extract_content", "query": "蓝色衣服的说话人",
                "personRefs": ["蓝色衣服"],
                "predicates": [{
                    "id": "p1", "kind": "person.speaking", "value": "正在说话",
                    "personRef": "蓝色衣服", "required": True,
                }],
            },
            "capabilityProposal": {
                "capabilities": ["person", "speech", "visual"], "capabilityBasis": "explicit_user",
            },
        }
        try:
            with patch.object(main_app, "_route_content_message", return_value=decision), \
                    patch.object(main_app, "queue_content_followup") as queue_search:
                response = main_app.chat_with_job(
                    job_id, main_app.ChatRequest(text="找到蓝色衣服的说话人的片段"),
                )
            queue_search.assert_called_once()
            prepared = queue_search.call_args.kwargs["prepared_intent"]
            self.assertEqual(set(prepared["modalities"]), {"person", "speech", "visual"})
            self.assertNotIn("_clarification", prepared)
        finally:
            main_app.jobs.pop(job_id, None)

    def test_typed_person_reply_binds_pending_query_without_llm_reroute(self) -> None:
        from app import main as main_app

        job_id = "test_typed_person_reply"
        instruction = "找出戴眼镜穿蓝色衬衫的男生发言的所有片段"
        intent = {
            "action": "extract_content", "query": instruction,
            "modalities": ["person", "speech", "visual"], "resultMode": "exhaustive",
            "predicates": [{
                "id": "speaker", "kind": "person.speaking",
                "value": "戴眼镜穿蓝色衬衫的男生发言",
                "personRef": "戴眼镜穿蓝色衬衫的男生", "required": True,
            }],
            "_clarification": {"kind": "person_target", "question": "请确认目标人物"},
        }
        people = [
            {"id": "person_1", "label": "人物 A", "defaultLabel": "人物 A", "ranges": [{"start": 1, "end": 4}]},
            {"id": "person_3", "label": "人物 C", "defaultLabel": "人物 C", "ranges": [{"start": 8, "end": 12}]},
        ]
        job = main_app.new_job_record(
            job_id=job_id, source=Path("/tmp/test-content-source.mp4"), filename="source.mp4",
            size=100, count="auto", target_seconds="auto", theme=instruction,
            source_hash="typed-person-reply-hash",
        )
        job.update({
            "taskMode": "content_extract", "status": "awaiting_content_confirmation",
            "videoInfo": {"duration": 90, "width": 1280, "height": 720, "has_audio": True},
            "request": {**job["request"], "contentInstruction": instruction, "pendingContentIntent": {
                "instructionId": main_app._content_instruction_id(instruction), "intent": intent,
            }},
            "contentIndex": {"persons": people, "availableModalities": ["person", "speech", "visual"]},
            "contentSearch": {
                "id": "search_pending_person", "instruction": instruction, "intent": intent,
                "status": "needs_clarification", "candidates": [],
                "clarification": {"kind": "person_target", "question": "请确认目标人物", "options": []},
            },
        })
        main_app.jobs[job_id] = job
        expected = {"action": "content-search", "job": {"id": job_id}}
        try:
            with patch.object(main_app, "_load_content_person_index", return_value={"persons": people}), \
                    patch.object(main_app, "_route_content_message") as route, \
                    patch.object(main_app, "queue_content_followup", return_value=expected) as queue_search, \
                    patch.object(main_app, "save_job"):
                response = main_app.chat_with_job(job_id, main_app.ChatRequest(text="人物C"))
            self.assertEqual(response, expected)
            route.assert_not_called()
            self.assertEqual(queue_search.call_args.args[1], instruction)
            self.assertEqual(queue_search.call_args.kwargs["display_text"], "人物C")
            prepared = queue_search.call_args.kwargs["prepared_intent"]
            self.assertEqual(prepared["personTarget"]["personIds"], ["person_3"])
            self.assertEqual(prepared["resultMode"], "exhaustive")
            self.assertEqual(prepared["_parserLlmCalls"], 0)
            self.assertEqual(main_app.jobs[job_id]["request"]["contentInstruction"], instruction)
        finally:
            main_app.jobs.pop(job_id, None)

    def test_cached_required_capability_is_automatically_authorized(self) -> None:
        from app import main as main_app

        intent = main_app._content_intent_from_decision(
            {
                "request": {"searchScopeKind": "all"}, "videoInfo": {"duration": 90},
                "contentIndex": {"availableModalities": ["speech"]},
            },
            "找到回答问题的人的片段",
            {"intent": {
                "action": "extract_content", "query": "回答者的完整回答",
                "predicates": [{"id": "answer", "kind": "speech.semantic", "value": "回答者作答"}],
            }},
        )
        self.assertEqual(intent["modalities"], ["speech"])
        self.assertNotIn("_clarification", intent)
        self.assertEqual(intent["executionPlan"]["authorizationSource"], "cached_automatic")

    def test_model_call_breakdown_has_no_visual_call_limit(self) -> None:
        from app import main as main_app

        stats = {"llmCalls": 2, "vlmCalls": 7}
        main_app._finalize_content_call_stats(
            stats, {"_parserLlmCalls": 1}, text_reason="semantic_or_ambiguous_candidates",
        )
        self.assertEqual(stats["llmCalls"], 2)
        self.assertEqual(stats["vlmCalls"], 7)
        self.assertEqual(stats["callBreakdown"]["intent"]["used"], 1)
        self.assertEqual(stats["callBreakdown"]["textRerank"]["used"], 1)
        self.assertEqual(stats["callBreakdown"]["visionVerify"]["used"], 7)
        self.assertIsNone(stats["callBreakdown"]["visionVerify"]["limit"])
        self.assertFalse(stats["budgetExceeded"])

    def test_strict_visual_scan_continues_beyond_four_model_calls(self) -> None:
        from app import main as main_app

        client = MagicMock()
        client.analyze_image.return_value = {"matches": []}
        stats = {"vlmCalls": 0}

        def frames_at_times(_source, _root, times, **_kwargs):
            return [SimpleNamespace(path=Path(f"frame-{position}.jpg"), time=value)
                    for position, value in enumerate(times)]

        with patch.object(main_app, "create_vision_client_for_job", return_value=client), \
                patch.object(main_app, "extract_frames_at_times", side_effect=frames_at_times), \
                patch.object(main_app, "create_contact_sheet", return_value=Path("sheet.jpg")), \
                patch.object(main_app, "settings", replace(
                    main_app.settings, content_search_model_concurrency=1,
                )), \
                patch.object(main_app, "_content_progress"):
            matches = main_app._targeted_visual_chapter_matches(
                "job_unbounded", {
                    "sourcePath": "/tmp/source.mp4", "workDirectory": "/tmp/work",
                    "visionConfig": {"model": "test-vlm"},
                }, "search_unbounded", "冰箱", [{"start": 0.0, "end": 29.5}],
                threading.Event(), stats, [], global_scan=True, strict_scan=True,
            )

        self.assertEqual(matches, [])
        self.assertEqual(stats["vlmCalls"], 5)
        self.assertEqual(client.analyze_image.call_count, 5)
        self.assertEqual(stats["strictVisualVerifiedFrames"], 60)
        self.assertTrue(stats["strictVisualCoverageComplete"])

    def test_strict_visual_schedule_never_requests_exclusive_media_end(self) -> None:
        from app import main as main_app

        values = main_app._strict_visual_sample_times(0.0, 81.567, scene_cuts=[10.0, 20.0])
        self.assertEqual(values[0], 0.0)
        self.assertLess(values[-1], 81.567)
        self.assertGreaterEqual(values[-1], 81.5)
        self.assertTrue(all(0.0 <= value < 81.567 for value in values))

    def test_dense_visual_index_coverage_detects_large_holes(self) -> None:
        from app import main as main_app

        dense = {"embeddingVisualUnits": [
            {"start": value, "end": value + .1, "evidenceTime": value}
            for value in (0.0, 1.0, 2.0, 3.0)
        ]}
        sparse = {"embeddingVisualUnits": [
            {"start": value, "end": value + .1, "evidenceTime": value}
            for value in (0.0, 3.0)
        ]}
        self.assertTrue(main_app._dense_visual_index_coverage(
            dense, start=0.0, end=3.0,
        )["complete"])
        self.assertFalse(main_app._dense_visual_index_coverage(
            sparse, start=0.0, end=3.0,
        )["complete"])

    def test_adaptive_semantic_candidates_keep_strong_tail_evidence(self) -> None:
        from app import main as main_app

        units = [{"id": f"unit_{index}"} for index in range(80)]
        recalled = [
            {"unit": unit, "score": 90 - index, "vectorScore": .1, "lexicalScore": 0}
            for index, unit in enumerate(units)
        ]
        recalled[-1].update({"vectorScore": .7, "lexicalScore": 1})
        selected = main_app._adaptive_semantic_units(
            units, recalled, scope_seconds=60, predicate_count=1,
        )
        self.assertEqual(len(selected), 49)
        self.assertEqual(selected[-1]["id"], "unit_79")

    def test_strict_visual_scan_retries_failed_page_and_keeps_later_results(self) -> None:
        from app import main as main_app

        client = MagicMock()
        client.analyze_image.side_effect = [
            RuntimeError("temporary-1"), RuntimeError("temporary-2"), RuntimeError("temporary-3"),
            {"matches": [{
                "start_seconds": 6.0, "end_seconds": 7.0,
                "evidence_times": [6.0, 7.0], "score": 82,
                "title": "后续页面命中", "reason": "后续页面包含目标",
            }]},
        ]
        stats = {"vlmCalls": 0}

        def frames_at_times(_source, _root, times, **_kwargs):
            return [SimpleNamespace(path=Path(f"frame-{position}.jpg"), time=value)
                    for position, value in enumerate(times)]

        with patch.object(main_app, "create_vision_client_for_job", return_value=client), \
                patch.object(main_app, "extract_frames_at_times", side_effect=frames_at_times), \
                patch.object(main_app, "create_contact_sheet", return_value=Path("sheet.jpg")), \
                patch.object(main_app, "settings", replace(
                    main_app.settings, content_search_model_concurrency=1,
                )), \
                patch.object(main_app, "_content_progress"):
            matches = main_app._targeted_visual_chapter_matches(
                "job_retry", {
                    "sourcePath": "/tmp/source.mp4", "workDirectory": "/tmp/work",
                    "visionConfig": {"model": "test-vlm"},
                }, "search_retry", "目标", [{"start": 0.0, "end": 11.5}],
                threading.Event(), stats, [], global_scan=True, strict_scan=True,
            )

        self.assertEqual(client.analyze_image.call_count, 4)
        self.assertEqual(len(stats["strictVisualFailedPages"]), 1)
        self.assertEqual(stats["strictVisualVerifiedFrames"], 12)
        self.assertFalse(stats["strictVisualCoverageComplete"])
        self.assertEqual(len(matches), 1)

    def test_strict_visual_scan_uses_configured_page_concurrency(self) -> None:
        from app import main as main_app

        barrier = threading.Barrier(3)
        state_lock = threading.Lock()
        active = 0
        maximum_active = 0

        def analyze_image(*_args, **_kwargs):
            nonlocal active, maximum_active
            with state_lock:
                active += 1
                maximum_active = max(maximum_active, active)
            try:
                barrier.wait(timeout=2)
                return {"matches": []}
            finally:
                with state_lock:
                    active -= 1

        client = MagicMock()
        client.analyze_image.side_effect = analyze_image
        stats = {"vlmCalls": 0}

        def frames_at_times(_source, _root, times, **_kwargs):
            return [SimpleNamespace(path=Path(f"frame-{position}.jpg"), time=value)
                    for position, value in enumerate(times)]

        with patch.object(main_app, "create_vision_client_for_job", return_value=client), \
                patch.object(main_app, "extract_frames_at_times", side_effect=frames_at_times), \
                patch.object(main_app, "create_contact_sheet", return_value=Path("sheet.jpg")), \
                patch.object(main_app, "settings", replace(
                    main_app.settings, content_search_model_concurrency=3,
                )), \
                patch.object(main_app, "_content_progress"):
            matches = main_app._targeted_visual_chapter_matches(
                "job_parallel", {
                    "sourcePath": "/tmp/source.mp4", "workDirectory": "/tmp/work",
                    "visionConfig": {"model": "test-vlm"},
                }, "search_parallel", "目标", [{"start": 0.0, "end": 17.5}],
                threading.Event(), stats, [], global_scan=True, strict_scan=True,
            )

        self.assertEqual(matches, [])
        self.assertEqual(client.analyze_image.call_count, 3)
        self.assertEqual(stats["vlmCalls"], 3)
        self.assertEqual(stats["strictVisualConcurrency"], 3)
        self.assertEqual(maximum_active, 3)
        self.assertEqual(stats["strictVisualVerifiedFrames"], 36)
        self.assertTrue(stats["strictVisualCoverageComplete"])

    def test_person_appearance_direct_path_returns_all_continuous_ranges(self) -> None:
        from app import main as main_app

        person = {
            "id": "person_1", "label": "人物 A", "confidence": .94,
            "ranges": [{"start": 1.0, "end": 4.0}, {"start": 20.0, "end": 25.0}],
        }
        index = {
            "persons": [person],
            "personTracks": [
                {"id": "track_1", "personId": "person_1", "start": 2.0, "end": 2.0},
                {"id": "track_2", "personId": "person_1", "start": 22.0, "end": 22.0},
            ],
        }
        matches = main_app._direct_person_appearance_matches(
            person, index, scope_start=0.0, scope_end=30.0,
        )
        self.assertEqual([(item["start"], item["end"]) for item in matches], [(1.0, 4.0), (20.0, 25.0)])
        self.assertEqual(matches[0]["personTrackIds"], ["track_1"])
        self.assertEqual(matches[1]["personTrackIds"], ["track_2"])
        self.assertEqual(matches[0]["recallChannels"], ["person_track_continuous"])

    def test_person_boundary_refinement_rebuilds_and_splits_track_ranges(self) -> None:
        from app import main as main_app

        ranges = main_app._person_track_refined_ranges(
            "person_1",
            [
                {"personId": "person_1", "start": 10.0, "end": 10.0},
                {"personId": "person_1", "start": 10.5, "end": 10.5},
                {"personId": "person_1", "start": 13.0, "end": 13.0},
                {"personId": "other", "start": 14.0, "end": 14.0},
            ],
            scope_start=8.0, scope_end=16.0, scene_cuts=[12.0],
        )
        self.assertEqual([(item["start"], item["end"]) for item in ranges], [
            (9.96, 10.54), (12.96, 13.04),
        ])
        self.assertEqual([item["trackCount"] for item in ranges], [2, 1])

    def test_described_person_appearance_binds_to_speaking_predicate(self) -> None:
        from app import main as main_app

        normalized = main_app._normalize_described_person_speaking_intent(
            {
                "predicates": [
                    {"id": "person", "kind": "person.appearance", "value": "短头发、穿条形衬衫的男性"},
                    {"id": "speech", "kind": "speech.semantic", "value": "说话的片段"},
                ],
                "personRefs": ["短头发、穿条形衬衫的男性"],
                "query": "找到视频里短头发、穿条形衬衫的男性说话的片段",
            },
            "找到视频里短头发、穿条形衬衫的男性说话的片段",
        )
        predicates = normalized["predicates"]
        speaking = next(item for item in predicates if item["kind"] == "person.speaking")
        self.assertEqual(speaking["personRef"], "短头发、穿条形衬衫的男性")
        plan = main_app.compile_query_plan(normalized)
        self.assertFalse(plan["clarificationRequired"])
        self.assertEqual([item["kind"] for item in plan["predicates"]], ["person.speaking"])

    def test_embedded_female_speech_subject_is_promoted_to_active_speaker(self) -> None:
        from app import main as main_app

        intent = main_app._content_intent_from_decision(
            {"request": {"searchScopeKind": "all"}, "videoInfo": {"duration": 699.84}},
            "找到女性说话的片段",
            {
                "capabilityProposal": {"capabilities": ["speech"]},
                "intent": {
                    "action": "extract_content", "query": "找到女性说话的片段",
                    "predicates": [{
                        "id": "p1", "kind": "speech.semantic",
                        "value": "女性正在说话或发言", "required": True,
                        "subject": {
                            "description": "女性", "type": "person", "identityPolicy": "context",
                        },
                    }],
                    "logic": {"op": "predicate", "predicateId": "p1"},
                },
            },
        )
        self.assertEqual(set(intent["modalities"]), {"person", "speech", "visual"})
        self.assertEqual(
            [item["kind"] for item in intent["queryPlan"]["predicates"]],
            ["person.speaking"],
        )
        self.assertEqual(intent["queryPlan"]["predicates"][0]["personRef"], "女性")
        self.assertEqual(
            set(intent["queryPlan"]["requiredOperations"]),
            {"person.track_face", "person.active_speaker_link", "speech.semantic_search"},
        )
        self.assertIn(
            "embedded_person_speech_promoted_to_active_speaker",
            {item["code"] for item in intent.get("normalizationDiagnostics") or []},
        )

    def test_described_person_speaking_predicate_id_binding_is_executable(self) -> None:
        from app import main as main_app

        raw_intent = {
            "action": "extract_content", "query": "找到女性说话的片段",
            "predicates": [
                {
                    "id": "p1", "kind": "person.appearance", "value": "女性",
                    "subject": {
                        "description": "女性", "type": "person", "identityPolicy": "context",
                    },
                    "required": True,
                },
                {
                    "id": "p2", "kind": "person.speaking", "value": "说话",
                    "subjectPersonRef": "p1",
                    "subject": {
                        "description": "女性", "type": "person", "identityPolicy": "context",
                    },
                    "required": True,
                },
            ],
            "logic": {"op": "all", "children": [
                {"op": "predicate", "predicateId": "p1"},
                {"op": "predicate", "predicateId": "p2"},
            ]},
            "relations": [{"type": "during", "left": "p2", "right": "p1"}],
        }
        parsed = main_app.parse_content_intent("找到女性说话的片段", raw_intent)
        self.assertEqual(parsed["validationErrors"], [])
        intent = main_app._content_intent_from_decision(
            {"request": {"searchScopeKind": "all"}, "videoInfo": {"duration": 699.84}},
            "找到女性说话的片段",
            {
                "capabilityProposal": {"capabilities": ["speech", "person", "visual"]},
                "intent": parsed,
            },
        )
        self.assertNotIn("_clarification", intent)
        self.assertEqual(intent["validationErrors"], [])
        self.assertEqual(
            [item["kind"] for item in intent["queryPlan"]["predicates"]],
            ["person.speaking"],
        )
        self.assertEqual(intent["queryPlan"]["predicates"][0]["personRef"], "女性")
        self.assertEqual(
            set(intent["queryPlan"]["requiredOperations"]),
            {"person.track_face", "person.active_speaker_link", "speech.semantic_search"},
        )

    def test_persisted_described_speaker_error_upgrades_without_another_model_call(self) -> None:
        from app import main as main_app

        instruction = "找到女性说话的片段"
        persisted = {
            "schemaVersion": main_app.CONTENT_SEARCH_VERSION,
            "parserVersion": main_app.CONTENT_INTENT_PARSER_VERSION,
            "action": "extract_content", "query": instruction,
            "modalities": ["speech", "person", "visual"],
            "predicates": [
                {
                    "id": "p1", "kind": "person.appearance", "value": "女性",
                    "subject": {"description": "女性", "type": "person", "identityPolicy": "context"},
                    "required": True,
                },
                {
                    "id": "p2", "kind": "person.speaking", "value": "说话",
                    "subjectPersonRef": "p1",
                    "subject": {"description": "女性", "type": "person", "identityPolicy": "context"},
                    "required": True,
                },
            ],
            "logic": {"op": "all", "children": [
                {"op": "predicate", "predicateId": "p1"},
                {"op": "predicate", "predicateId": "p2"},
            ]},
            "relations": [{"type": "during", "left": "p2", "right": "p1"}],
            "validationErrors": [{
                "code": "person_speaking_requires_person_ref",
                "message": "person.speaking 必须引用人物目录中的 personRef。",
            }],
            "_clarification": {
                "kind": "query_semantics", "question": "请补充这次想找的内容关系",
                "message": "person.speaking 必须引用人物目录中的 personRef。",
            },
        }
        job = {
            "request": {
                "searchScopeKind": "all",
                "pendingContentIntent": {
                    "instructionId": main_app._content_instruction_id(instruction),
                    "intent": persisted,
                },
            },
            "videoInfo": {"duration": 699.84},
        }
        with patch.object(main_app, "create_llm_client_for_job") as create_client:
            upgraded = main_app._parse_content_instruction(job, instruction)
        create_client.assert_not_called()
        self.assertNotIn("_clarification", upgraded)
        self.assertEqual(upgraded["validationErrors"], [])
        self.assertEqual(upgraded["queryPlan"]["predicates"][0]["personRef"], "女性")

    def test_described_speaker_expands_to_all_visually_matched_people(self) -> None:
        from app import main as main_app

        intent = {
            "predicates": [{
                "id": "female_speaker", "kind": "person.speaking",
                "value": "女性正在说话", "personRef": "女性", "required": True,
            }],
            "logic": {"op": "predicate", "predicateId": "female_speaker"},
        }
        plan = main_app.compile_query_plan(intent)
        bound = main_app._bind_described_person_speaking_targets(
            intent, plan, "female_speaker",
            [
                {"id": "person_1", "label": "人物 A"},
                {"id": "person_2", "label": "人物 B"},
            ],
            "女性",
        )
        compiled = main_app.compile_query_plan(bound)
        self.assertFalse(compiled["clarificationRequired"])
        self.assertEqual(compiled["personTarget"]["personIds"], ["person_1", "person_2"])
        self.assertEqual(compiled["personTarget"]["activity"], "speaking")
        self.assertEqual(compiled["logic"]["op"], "any")
        self.assertEqual(
            {item["personId"] for item in compiled["predicates"]},
            {"person_1", "person_2"},
        )

    def test_person_description_samples_span_the_identity_track(self) -> None:
        from app import main as main_app

        samples = main_app._person_description_samples({
            "id": "person_1", "representativeTime": 5.0,
            "representativeBox": [1, 2, 20, 30],
            "ranges": [{"start": 0, "end": 30}],
        }, [
            {"personId": "person_1", "start": 1.0, "box": [1, 1, 10, 10]},
            {"personId": "person_1", "start": 15.0, "box": [2, 2, 11, 11]},
            {"personId": "person_1", "start": 29.0, "box": [3, 3, 12, 12]},
            {"personId": "person_2", "start": 20.0, "box": [4, 4, 13, 13]},
        ], maximum=3)

        self.assertEqual(len(samples), 3)
        self.assertEqual(samples[0]["time"], 5.0)
        self.assertGreater(max(item["time"] for item in samples), 20.0)
        self.assertTrue(all(item["box"] for item in samples))

    def test_multi_frame_person_description_keeps_uncertain_match_for_review(self) -> None:
        from app import main as main_app
        from app.media import SampledFrame

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "source.mp4"
            source.touch()
            frames = [SampledFrame(path=root / f"frame-{index}.jpg", time=float(index)) for index in range(6)]
            client = MagicMock()
            client.analyze_image.return_value = {"matches": [{
                "personId": "person_1", "classification": "match", "confidence": .91,
                "visiblePanels": [1, 2, 3], "matchingPanels": [1, 2, 3],
                "conflictingPanels": [], "reason": "三张画面均符合",
            }, {
                "personId": "person_2", "classification": "uncertain", "confidence": .56,
                "visiblePanels": [4, 5, 6], "matchingPanels": [4],
                "conflictingPanels": [], "reason": "仅一张画面支持",
            }]}
            catalog = [{
                "id": "person_1", "label": "人物 A", "representativeTime": 0,
                "representativeBox": [0, 0, 10, 10], "ranges": [{"start": 0, "end": 3}],
            }, {
                "id": "person_2", "label": "人物 B", "representativeTime": 3,
                "representativeBox": [0, 0, 10, 10], "ranges": [{"start": 3, "end": 6}],
            }]
            tracks = [
                {"personId": person_id, "start": start, "box": [0, 0, 10, 10]}
                for person_id, starts in (("person_1", [0, 1, 2]), ("person_2", [3, 4, 5]))
                for start in starts
            ]
            with (
                patch.object(main_app, "extract_frames_at_times", return_value=frames),
                patch.object(main_app, "create_contact_sheet", return_value=root / "sheet.jpg"),
                patch.object(main_app, "_write_person_crop", return_value=False),
                patch.object(main_app, "create_vision_client_for_job", return_value=client),
                patch.object(main_app, "_content_progress"),
            ):
                matched, diagnostics = main_app._match_person_catalog_by_visual_description(
                    "missing_job", {
                        "sourcePath": str(source), "workDirectory": str(root),
                    }, "search_1", "女性", catalog, threading.Event(), person_tracks=tracks,
                )

        self.assertEqual([item["id"] for item in matched], ["person_1", "person_2"])
        self.assertEqual(diagnostics["reliablePersonIds"], ["person_1"])
        self.assertEqual(diagnostics["uncertainPersonIds"], ["person_2"])
        self.assertEqual(matched[1]["personDescriptionEvidence"]["status"], "possible")

    def test_possible_person_description_marks_speaking_result_for_review(self) -> None:
        from app import main as main_app

        matches = [{
            "id": "match_1", "matchedPersonIds": ["person_2"],
            "activeSpeakerEvidence": {"personId": "person_2", "asdScore": .92},
            "requiresReview": False, "confidenceTier": "reliable",
        }]
        main_app._attach_person_description_evidence(matches, {"evidence": [{
            "personId": "person_2", "status": "possible", "confidence": .56,
            "reason": "仅一张代表画面支持",
        }]})

        self.assertTrue(matches[0]["requiresReview"])
        self.assertEqual(matches[0]["confidenceTier"], "possible")
        self.assertEqual(matches[0]["personDescriptionEvidence"]["confidence"], .56)
        self.assertIn("人物外观描述", matches[0]["reviewReasons"][0])

    def test_person_coverage_manifest_accepts_dense_scan(self) -> None:
        from app import main as main_app

        manifest = main_app._content_coverage_manifest({
            "duration": 10.0,
            "coverage": {"start": 0.0, "end": 10.0},
            "recognitionAttemptedModalities": ["person"],
            "recognitionCompletedModalities": ["person"],
            "recognitionAvailableModalities": ["person"],
            "personTracks": [
                {"id": "track_1", "start": 0.0, "end": .5},
                {"id": "track_2", "start": 9.5, "end": 10.0},
            ],
            "personSampling": {
                "intervalSeconds": .5, "requestedFrameCount": 21,
                "extractedFrameCount": 21,
            },
        })
        operation = manifest["operations"]["person.track_face"]
        self.assertTrue(operation["coverageComplete"])
        self.assertEqual(operation["coverageMode"], "continuous_sampled")
        self.assertEqual(operation["maximumSampleGapUs"], 500000)


if __name__ == "__main__":
    unittest.main()
