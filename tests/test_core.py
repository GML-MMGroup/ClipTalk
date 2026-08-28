from __future__ import annotations

import math
import os
import json
import copy
import tempfile
import unittest
import httpx
from concurrent.futures import Future
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import MagicMock, patch

from app.ark_client import ArkRequestError, ArkVisionClient, OpenAICompatibleVisionClient, parse_json_object
from app.config import Settings
from app.editing_techniques import (
    composition_effective_duration,
    plan_editing_techniques,
    source_duration_meets_minimum,
    source_pieces,
)
from app.editing_intent import (
    apply_user_feedback_to_brief,
    candidate_requirement_alignment,
    compile_editing_intent,
    evaluate_sequence_against_intent,
)
from app.composition_review import (
    calibrate_review_report,
    apply_review_repairs,
    composition_review_timeline,
    normalize_review_report,
    rendered_visual_metrics,
    review_cache_key,
    review_improved,
    sanitize_review_report,
)
from app.composition_assets import validate_render_selections
from app.vision_settings import LlmConfigurationStore, VisionConfigurationStore, discover_llm_models, discover_models
from app.main import (
    analysis_cache_reuse_allowed,
    apply_timeline_history_state,
    automatic_composition_signature,
    automatic_composition_similarity,
    build_output_editing_explanation,
    distinct_event_replacement_plans,
    execution_snapshot,
    _build_quality_recovery_sequence,
    _content_selection_fidelity,
    _normalise_edit_plans,
    _edit_plan_candidates,
    _semantic_safe_selections,
    _synthesise_review_repairs,
    parse_candidate_adjustment,
    parse_absolute_time_range,
    parse_manual_selection_adjustment,
    parse_named_candidate_adjustment,
    parse_requested_title,
    public_job_status,
    public_job_summary,
    resolve_candidate_reference,
    stage_progress_for,
    structured_progress,
)
from app.media import (
    MediaError,
    SampledFrame,
    create_preview_proxy,
    create_timeline_thumbnail_sprite,
    extract_audio_waveform,
    extract_frames_at_times,
    extract_uniform_frames,
    exclusive_render_duration,
    probe_video,
    render_clip,
    render_composition,
    snapshot_sampled_frames,
    silence_intervals_from_waveform,
    validate_uniform_frame_coverage,
    validate_video_decodable_coverage,
    validate_rendered_clip,
)
from app.subtitle_review import output_fingerprints, save_draft
from app.event_groups import build_final_reel
from app.pipeline import (
    HighlightCandidate,
    HighlightPipeline,
    ModelDecisionRequired,
    _candidate_from_coarse,
    _refined_candidate,
    candidate_text_similarity,
    coarse_frame_limit,
    coarse_priority_times,
    merge_priority_frames,
    overlaps_ranges,
    recommended_candidate_indices,
    refinement_window_seconds,
    refinement_candidate_limit,
    speech_signal_candidates,
    visual_change_candidates,
    waveform_hotspot_candidates,
    select_non_overlapping,
    touches_refinement_boundary,
    clean_model_evidence,
    load_analysis_checkpoint,
    normalize_content_profile,
    validated_model_time,
)
from app.prompts import (
    COMMON_SYSTEM_PROMPT,
    EDIT_PLAN_PROMPT_VERSION,
    PROMPT_VERSION,
    boundary_refinement_prompt,
    coarse_discovery_prompt,
    content_classification_prompt,
    event_director_prompt,
    llm_edit_plan_prompt,
)
from app.store import JobStore
from app.event_groups import allocate_event_group_budget, build_event_groups, build_final_reel, composition_duration, event_groups_total, normalize_output_event_hierarchy, split_event_groups_at_scene_cuts
from app.edit_boundaries import annotate_candidate_boundaries, semantic_safe_range
from app.edl_optimizer import optimize_edl
from app.speech import (
    _cluster_short_speaker_embeddings,
    _sensevoice_model_options,
    enforce_speaker_turn_contract,
    normalize_sensevoice_result,
    parse_rich_tags,
    speech_evidence,
    transcript_context,
)
import app.main as main_module


class ProgressEtaTests(unittest.TestCase):
    def test_content_speech_worker_counts_are_exposed_during_finalization(self) -> None:
        progress = main_module._content_speech_progress_snapshot(None, 40, 40, "finalizing")
        self.assertEqual(progress["completed"], 40)
        self.assertEqual(progress["total"], 40)
        self.assertEqual(progress["progress_mode"], "finalizing")
        self.assertEqual(progress["eta_mode"], "finalizing")
        self.assertIn("40/40", progress["detail"])

        facts = main_module.progress_facts_snapshot({
            "status": "running",
            "stage": "content_transcription",
            "progress": progress["value"],
            "stageProgress": 1.0,
            "stageCompleted": progress["completed"],
            "stageTotal": progress["total"],
            "stageUnit": progress["unit"],
            "progressMode": progress["progress_mode"],
            "etaMode": progress["eta_mode"],
        })
        self.assertEqual(facts["stage"]["mode"], "finalizing")
        self.assertIsNone(facts["stage"]["fraction"])
        self.assertEqual(facts["stage"]["completed"], 40)
        self.assertEqual(facts["stage"]["total"], 40)

    def test_content_speech_worker_reports_measured_batch_progress(self) -> None:
        progress = main_module._content_speech_progress_snapshot(.5, 20, 40, "recognizing_measured")
        self.assertEqual(progress["progress_mode"], "determinate")
        self.assertEqual(progress["completed"], 20)
        self.assertEqual(progress["total"], 40)
        self.assertIn("20/40", progress["detail"])

    def test_content_speech_worker_exposes_queue_position(self) -> None:
        progress = main_module._content_speech_progress_snapshot(None, None, None, "queued:2:4")
        self.assertEqual(progress["progress_mode"], "indeterminate")
        self.assertIn("队列第 2/4", progress["detail"])

    def test_speech_finalizing_does_not_invent_a_percentage(self) -> None:
        facts = structured_progress(
            {
                "stage": "speech_recognition",
                "stageObservedIndex": 98,
                "stageSampleCount": 97,
                "stageAverageSeconds": .5,
                "stageUnitStartedAt": datetime.now(timezone.utc).isoformat(),
            },
            stage="speech_recognition",
            overall=.0798,
            detail="SenseVoice 正在整理识别结果",
            facts={"finalizing": True},
        )
        self.assertIsNone(stage_progress_for("speech_recognition", .0798, "SenseVoice 正在整理识别结果"))
        self.assertIsNone(facts["stageCompleted"])
        self.assertIsNone(facts["stageTotal"])
        self.assertEqual(facts["progressMode"], "finalizing")
        self.assertEqual(facts["etaMode"], "finalizing")
        self.assertIsNone(facts["etaSeconds"])

    def test_progress_contract_separates_workflow_and_measured_stage(self) -> None:
        snapshot = main_module.progress_facts_snapshot({
            "status": "running",
            "stage": "refine_vlm",
            "progress": .63,
            "stageProgress": .25,
            "stageCompleted": 3,
            "stageTotal": 12,
            "stageUnit": "候选",
            "progressMode": "determinate",
            "model": "VLM",
            "detail": "视觉大模型正在精修候选 4/12",
        })
        self.assertEqual(snapshot["workflow"]["fraction"], .63)
        self.assertEqual(snapshot["workflow"]["phase"], "analysis")
        self.assertEqual(snapshot["stage"]["mode"], "determinate")
        self.assertEqual(snapshot["stage"]["fraction"], .25)
        self.assertEqual(snapshot["stage"]["completed"], 3)
        self.assertEqual(snapshot["stage"]["total"], 12)

    def test_uncounted_model_request_has_no_stage_fraction(self) -> None:
        snapshot = main_module.progress_facts_snapshot({
            "status": "running",
            "stage": "content_classification",
            "progress": .12,
            "stageProgress": None,
            "progressMode": "indeterminate",
            "model": "VLM",
            "detail": "视觉大模型正在识别视频类型与高光标准",
        })
        self.assertEqual(snapshot["workflow"]["fraction"], .12)
        self.assertEqual(snapshot["stage"]["mode"], "indeterminate")
        self.assertIsNone(snapshot["stage"]["fraction"])

    def test_waits_for_first_counted_stage_sample(self) -> None:
        started = (datetime.now(timezone.utc) - timedelta(seconds=90)).isoformat()
        facts = structured_progress(
            {"stage": "coarse_vlm", "stageStartedAt": started, "startedAt": started},
            stage="coarse_vlm",
            overall=.12,
            detail="视觉大模型正在分析第 1/5 组画面",
            facts={"completed": 0, "total": 5, "unit": "组", "currentItemIndex": 1, "fraction": 0},
        )
        self.assertIsNone(facts["etaSeconds"])
        self.assertEqual(facts["etaMode"], "waiting_first_sample")
        self.assertEqual(facts["stageObservedIndex"], 1)
        self.assertEqual(facts["stageCompleted"], 0)
        self.assertEqual(stage_progress_for(
            "coarse_vlm", .12, "视觉大模型正在分析第 1/5 组画面", completed=0, total=5,
        ), 0)

    def test_uses_completed_stage_unit_average_for_eta(self) -> None:
        now = datetime.now(timezone.utc)
        unit_started = (now - timedelta(seconds=40)).isoformat()
        facts = structured_progress(
            {
                "stage": "coarse_vlm",
                "stageStartedAt": (now - timedelta(seconds=80)).isoformat(),
                "stageUnitStartedAt": unit_started,
                "stageObservedIndex": 1,
                "stageSampleCount": 0,
                "startedAt": (now - timedelta(seconds=120)).isoformat(),
            },
            stage="coarse_vlm",
            overall=.196,
            detail="视觉大模型正在分析第 2/5 组画面",
            facts={"completed": 1, "total": 5, "unit": "组", "currentItemIndex": 2, "fraction": .2},
        )
        self.assertEqual(facts["etaMode"], "stage_average")
        self.assertEqual(facts["stageSampleCount"], 1)
        self.assertEqual(facts["stageCompleted"], 1)
        self.assertAlmostEqual(facts["stageAverageSeconds"], 40, delta=2)
        self.assertGreater(facts["etaSeconds"], 100)

    def test_uncounted_model_stage_does_not_invent_eta(self) -> None:
        started = (datetime.now(timezone.utc) - timedelta(seconds=120)).isoformat()
        facts = structured_progress(
            {"stage": "content_classification", "startedAt": started},
            stage="content_classification",
            overall=.10,
            detail="视觉大模型正在识别视频类型与高光标准",
        )
        self.assertIsNone(facts["etaSeconds"])
        self.assertEqual(facts["etaMode"], "unavailable")
        self.assertEqual(facts["progressMode"], "indeterminate")
        self.assertIsNone(stage_progress_for(
            "content_classification", .12,
            "视觉大模型正在识别视频类型与高光标准",
        ))

    def test_media_seconds_are_reported_as_measured_stage_work(self) -> None:
        facts = structured_progress(
            {"stage": "audio_analysis", "startedAt": datetime.now(timezone.utc).isoformat()},
            stage="audio_analysis",
            overall=.05,
            detail="音频波形已处理 32/120 秒",
            facts={"completed": 32, "total": 120, "unit": "秒", "fraction": 32 / 120},
        )
        self.assertEqual(facts["stageCompleted"], 32)
        self.assertEqual(facts["stageTotal"], 120)
        self.assertEqual(facts["stageUnit"], "秒")
        self.assertEqual(facts["progressMode"], "determinate")
        self.assertAlmostEqual(stage_progress_for(
            "audio_analysis", .05, "音频波形已处理 32/120 秒", completed=32, total=120,
        ), 32 / 120)

    def test_progress_does_not_parse_presentation_prose(self) -> None:
        facts = structured_progress(
            {"stage": "coarse_vlm", "startedAt": datetime.now(timezone.utc).isoformat()},
            stage="coarse_vlm",
            overall=.3,
            detail="视觉大模型已完成 3/4 组，当前 75%",
        )
        self.assertIsNone(facts["stageCompleted"])
        self.assertIsNone(facts["stageTotal"])
        self.assertEqual(facts["progressMode"], "indeterminate")
        self.assertIsNone(stage_progress_for(
            "coarse_vlm", .3, "视觉大模型已完成 3/4 组，当前 75%",
        ))


class JsonParsingTests(unittest.TestCase):
    def test_parses_fenced_json(self) -> None:
        self.assertEqual(parse_json_object('answer\n```json\n{"candidates": []}\n```')["candidates"], [])

    def test_rejects_non_json(self) -> None:
        with self.assertRaises(ArkRequestError) as raised:
            parse_json_object("not json")
        self.assertTrue(raised.exception.retryable)

    def test_non_retryable_error_defaults_to_false(self) -> None:
        self.assertFalse(ArkRequestError("bad request").retryable)


class ChatTimeRangeTests(unittest.TestCase):
    def test_parses_seconds_and_clock_ranges(self) -> None:
        self.assertEqual(parse_absolute_time_range("把 00:10 到 00:20 合成"), {"start": 10.0, "end": 20.0})
        self.assertEqual(parse_absolute_time_range("生成 10秒到20秒的片段"), {"start": 10.0, "end": 20.0})
        self.assertEqual(parse_absolute_time_range("裁剪 1:02.5~1:18"), {"start": 62.5, "end": 78.0})

    def test_ignores_single_duration_commands(self) -> None:
        self.assertIsNone(parse_absolute_time_range("整批成片改成 60 秒"))

    def test_rejects_reverse_ranges(self) -> None:
        with self.assertRaises(Exception):
            parse_absolute_time_range("从 20 秒到 10 秒合成")


class WaveformSilenceTests(unittest.TestCase):
    def test_derives_conservative_silence_without_second_media_decode(self) -> None:
        waveform = {"rms": [.2, .1, .004, .003, .002, .1, .2, .001, .2, .2]}
        intervals = silence_intervals_from_waveform(
            waveform, duration=5.0, minimum_duration=1.0,
        )
        self.assertEqual(intervals, [{
            "start": 1.0, "end": 2.5, "duration": 1.5, "source": "waveform_rms",
        }])

    def test_does_not_treat_short_quiet_dip_as_edit_boundary(self) -> None:
        waveform = {"rms": [.2, .001, .2, .2]}
        self.assertEqual(silence_intervals_from_waveform(
            waveform, duration=2.0, minimum_duration=1.0,
        ), [])


class EditPlanTests(unittest.TestCase):
    def setUp(self) -> None:
        self.job = {"eventGroups": [{
            "id": "event_1", "title": "冲突事件", "segments": [{
                "id": "segment_1", "start": 10.0, "end": 30.0, "duration": 20.0,
                "role": "高潮", "score": 92, "evidence": ["人物明显反应"],
            }], "availableSegments": [{
                "id": "segment_2", "start": 34.0, "end": 48.0, "duration": 14.0,
                "role": "结果", "score": 80, "evidence": ["事件结果出现"],
            }],
        }]}

    def test_edit_plan_candidates_include_available_pool(self) -> None:
        rows = _edit_plan_candidates(self.job, ["event_1"], {"event_1": ["segment_1"]}, "all_pool")
        self.assertEqual({row["id"] for row in rows}, {"segment_1", "segment_2"})
        self.assertEqual({row["candidateId"] for row in rows}, {"segment_1", "segment_2"})

    def test_manual_technique_plan_never_deletes_selected_shots(self) -> None:
        segments = [
            {"id": "talk", "start": 0, "end": 10, "hasSpeech": True, "role": "上下文"},
            {"id": "action", "start": 12, "end": 32, "hasSpeech": False, "role": "过程"},
            {"id": "climax", "start": 35, "end": 45, "role": "高潮"},
        ]
        plan = plan_editing_techniques(
            segments, target_seconds=20, policy={"preset": "attraction"}, manual_selection=True,
        )
        self.assertEqual([item["id"] for item in plan["segments"]], ["talk", "action", "climax"])
        self.assertEqual(plan["segments"][0]["playbackRate"], 1.0)
        self.assertEqual(plan["segments"][2]["playbackRate"], 1.0)
        self.assertGreater(plan["segments"][1]["playbackRate"], 1.0)
        self.assertEqual(plan["durationStatus"], "over_target")
        self.assertIn("手动选择不会被自动删除", "".join(plan["warnings"]))

    def test_silence_compression_and_speed_change_effective_duration(self) -> None:
        segment = {
            "id": "action", "start": 0, "end": 10, "playbackRate": 1.25,
            "silenceCuts": [{"start": 3, "end": 5, "retained": .2}],
        }
        self.assertEqual(source_pieces(segment), [{"start": 0.0, "end": 3.2}, {"start": 5.0, "end": 10.0}])
        self.assertAlmostEqual(composition_effective_duration([segment]), 6.56, places=2)

    def test_quiet_visual_action_is_not_treated_as_disposable_silence(self) -> None:
        segment = {
            "id": "cooking", "start": 0, "end": 20, "hasSpeech": True,
            "speechUnits": [{"start": 18, "end": 19, "text": "完成了"}],
            "role": "事件发展", "actionComplete": True,
        }
        plan = plan_editing_techniques(
            [segment], target_seconds=20,
            policy={"preset": "tight", "allowSilenceCompression": True},
            silences=[{"start": 2, "end": 12}, {"start": 13, "end": 17}],
        )
        self.assertEqual(plan["segments"][0]["silenceCuts"], [])
        self.assertEqual(plan["effectiveDuration"], 20.0)

    def test_speech_dominant_segment_compresses_only_bounded_pause_budget(self) -> None:
        segment = {
            "id": "answer", "start": 0, "end": 10, "hasSpeech": True,
            "speechUnits": [{"start": 0, "end": 8, "text": "完整回答"}],
            "role": "回答",
        }
        plan = plan_editing_techniques(
            [segment], target_seconds=8,
            policy={"preset": "tight", "allowSilenceCompression": True},
            silences=[{"start": 2, "end": 4}, {"start": 5, "end": 9}],
        )
        removed = 10 - plan["segments"][0]["effectiveDuration"]
        self.assertGreater(removed, 0)
        self.assertLessEqual(removed, 3.5)

    def test_all_pool_uses_full_verified_candidate_before_budget_preview(self) -> None:
        segment = {
            "id": "same", "candidateId": "candidate_1", "semanticUnitId": "semantic_1",
            "start": 0, "end": 12, "duration": 12, "score": 90,
        }
        available = {**segment, "start": 0, "end": 24, "duration": 24}
        job = {"eventGroups": [{
            "id": "event_1", "title": "完整做饭过程", "score": 90,
            "segments": [segment], "availableSegments": [available],
        }]}
        rows = _edit_plan_candidates(job, ["event_1"], None, "all_pool")
        self.assertEqual([(row["start"], row["end"]) for row in rows], [(0.0, 24.0)])

    def test_legacy_detector_group_never_enters_edit_plan_pool(self) -> None:
        job = {"eventGroups": [{
            "id": "raw", "title": "画面变化热点", "score": 99,
            "segments": [{"id": "raw_1", "start": 0, "end": 8, "score": 99}],
        }, {
            "id": "semantic", "title": "人物完成煎蛋", "score": 88,
            "segments": [{"id": "semantic_1", "start": 10, "end": 18, "score": 88}],
        }]}
        rows = _edit_plan_candidates(job, ["raw", "semantic"], None, "all_pool")
        self.assertEqual([row["groupId"] for row in rows], ["semantic"])

    def test_automatic_render_blocks_duration_outside_ten_percent(self) -> None:
        with self.assertRaisesRegex(RuntimeError, "目标时长"):
            validate_render_selections(
                [{"segments": [{"id": "short", "start": 0, "end": 18}]}],
                editing_intent={}, target_seconds=30, automatic=True,
            )

    def test_normalise_edit_plan_clamps_subrange_and_rejects_overlap(self) -> None:
        rows = _edit_plan_candidates(self.job, ["event_1"], None, "selected_only")
        plans = _normalise_edit_plans({"plans": [{"label": "测试", "sequence": [
            {"candidate_id": "segment_1", "source_start": 5, "source_end": 18, "role": "hook"},
            {"candidate_id": "segment_1", "source_start": 17, "source_end": 24, "role": "climax"},
        ]}]}, rows, scope="selected_only", selected_group_ids=["event_1"], target=20)
        self.assertEqual(len(plans), 1)
        self.assertEqual(len(plans[0]["sequence"]), 1)
        self.assertEqual(plans[0]["sequence"][0]["start"], 10.0)
        self.assertEqual(plans[0]["sequence"][0]["end"], 30.0)
        self.assertAlmostEqual(plans[0]["sourceDuration"], 20.0, places=2)
        self.assertAlmostEqual(plans[0]["estimatedDuration"], 20.0, places=2)

    def test_edit_plan_prompt_requires_local_subranges(self) -> None:
        prompt = llm_edit_plan_prompt(content_profile={}, theme="情绪", target_seconds=60, scope="selected_only", selected_group_ids=["event_1"], variants=["叙事完整版"], candidates=[], transcript_context="")
        self.assertIn("source_start/source_end", prompt)
        self.assertTrue(EDIT_PLAN_PROMPT_VERSION)

    def test_edit_plan_enforces_minimum_keep_seconds(self) -> None:
        self.job["eventGroups"][0]["segments"][0]["minimumKeepSeconds"] = 8.0
        rows = _edit_plan_candidates(self.job, ["event_1"], None, "selected_only")
        plans = _normalise_edit_plans({"plans": [{"label": "测试", "sequence": [
            {"candidate_id": "segment_1", "source_start": 15, "source_end": 17, "role": "climax"},
        ]}]}, rows, scope="selected_only", selected_group_ids=["event_1"], target=None)
        self.assertGreaterEqual(plans[0]["sequence"][0]["duration"], 8.0)

    def test_edit_plan_expands_a_cut_inside_spoken_expression(self) -> None:
        self.job["eventGroups"][0]["segments"][0].update({"hasSpeech": True, "minimumKeepSeconds": 15.0})
        rows = _edit_plan_candidates(self.job, ["event_1"], None, "selected_only")
        speech = [{"start": 12.0, "end": 27.0, "text": "这是一句必须完整保留的话。"}]
        plans = _normalise_edit_plans({"plans": [{"label": "测试", "sequence": [
            {"candidate_id": "segment_1", "source_start": 15, "source_end": 20, "role": "climax"},
        ]}]}, rows, scope="selected_only", selected_group_ids=["event_1"], target=None, speech_segments=speech)
        segment = plans[0]["sequence"][0]
        self.assertEqual((segment["start"], segment["end"]), (12.0, 27.0))

    def test_edit_plan_keeps_story_and_speech_evidence_for_later_validation(self) -> None:
        self.job["eventGroups"][0]["segments"][0].update({
            "candidateIndex": 7, "semanticUnitId": "story_7", "storyFunction": "结果",
            "requiresCandidateIndices": [6], "standalone": False, "hasSpeech": True,
            "speechUnits": [{"start": 10, "end": 20, "text": "完整结论"}],
        })
        rows = _edit_plan_candidates(self.job, ["event_1"], None, "selected_only")
        plans = _normalise_edit_plans({"plans": [{"label": "测试", "sequence": [
            {"candidate_id": "segment_1", "source_start": 10, "source_end": 20, "role": "result"},
        ]}]}, rows, scope="selected_only", selected_group_ids=["event_1"], target=None)
        segment = plans[0]["sequence"][0]
        self.assertEqual(segment["candidateIndex"], 7)
        self.assertEqual(segment["semanticUnitId"], "story_7")
        self.assertTrue(segment["hasSpeech"])
        self.assertEqual(segment["requiresCandidateIndices"], [6])

    def test_final_edl_removes_whole_shot_instead_of_cutting_speech(self) -> None:
        segments = [
            {"id": "a", "candidateId": "a", "groupId": "one", "start": 0, "end": 20, "score": 95, "essential": True},
            {"id": "b", "candidateId": "b", "groupId": "two", "start": 30, "end": 50, "score": 80},
        ]
        transcript = [
            {"start": 0, "end": 20, "text": "第一段完整对白"},
            {"start": 30, "end": 50, "text": "第二段完整对白"},
        ]
        optimized = optimize_edl(
            segments, speech_segments=transcript, target_seconds=30,
            order_mode="source", allow_fill=False, video_duration=60,
        )
        self.assertEqual(optimized["shotCount"], 1)
        self.assertEqual((optimized["segments"][0]["start"], optimized["segments"][0]["end"]), (0.0, 20.0))
        self.assertEqual(len(optimized["removedSegments"]), 1)

    def test_final_edl_fills_short_automatic_reel_from_a_new_event(self) -> None:
        selected = [{
            "id": "segment_1", "candidateId": "candidate_a", "groupId": "event_a",
            "start": 0, "end": 8, "score": 94,
        }]
        pool = [selected[0], {
            "id": "segment_2", "candidateId": "candidate_b", "groupId": "event_b",
            "start": 20, "end": 32, "score": 90,
        }]
        optimized = optimize_edl(
            selected, candidate_pool=pool, target_seconds=20,
            order_mode="source", allow_fill=True, video_duration=40,
        )
        self.assertEqual(optimized["shotCount"], 2)
        self.assertEqual(optimized["eventCount"], 2)
        self.assertEqual(optimized["actualDuration"], 20.0)
        self.assertTrue(optimized["qualityReport"]["passed"])

    def test_final_edl_never_semantically_deduplicates_user_confirmed_segments(self) -> None:
        segments = [
            {"id": "a", "candidateId": "m1", "semanticUnitId": "chapter_0000",
             "userConfirmed": True, "start": 0, "end": 5, "score": 90},
            {"id": "b", "candidateId": "m2", "semanticUnitId": "chapter_0000",
             "userConfirmed": True, "start": 10, "end": 15, "score": 80},
        ]
        optimized = optimize_edl(
            segments, target_seconds=None, order_mode="source", allow_fill=False,
            video_duration=20,
        )
        self.assertEqual(optimized["shotCount"], 2)
        self.assertEqual(
            [item["candidateId"] for item in optimized["segments"]], ["m1", "m2"],
        )
        self.assertEqual(optimized["semanticDeduplication"], [])

    def test_exact_point_two_second_confirmed_person_match_survives_float_roundoff(self) -> None:
        segment = {
            "id": "person_match", "candidateId": "match_person", "userConfirmed": True,
            "semanticUnitId": "match_person", "start": 24.42, "end": 24.62, "score": 90,
        }
        optimized = optimize_edl(
            [segment], target_seconds=None, order_mode="source", allow_fill=False,
            video_duration=63.73,
        )
        self.assertEqual(optimized["shotCount"], 1)
        self.assertEqual(optimized["segments"][0]["candidateId"], "match_person")
        self.assertAlmostEqual(optimized["segments"][0]["duration"], .2, places=3)

    def test_content_selection_fidelity_counts_merged_confirmed_ranges(self) -> None:
        fidelity = _content_selection_fidelity([{"segments": [
            {"candidateId": "m1", "contributingMatchIds": ["m1", "m2"]},
            {"candidateId": "m3"},
        ]}], ["m1", "m2", "m3"])
        self.assertTrue(fidelity["passed"])
        self.assertEqual(fidelity["renderedCount"], 3)

        missing = _content_selection_fidelity(
            [{"segments": [{"candidateId": "m1"}]}], ["m1", "m2"],
        )
        self.assertFalse(missing["passed"])
        self.assertEqual(missing["missingMatchIds"], ["m2"])

    def test_safe_boundary_optimization_preserves_merged_content_match_ids(self) -> None:
        job = {"videoInfo": {"duration": 30}, "request": {}}
        selections, _ = _semantic_safe_selections(job, [{"segments": [
            {"candidateId": "m1", "contributingMatchIds": ["m1", "m2"], "start": 0, "end": 5},
            {"candidateId": "m3", "start": 5, "end": 10},
        ]}], order_mode="source", target_seconds=None, allow_fill=False)
        fidelity = _content_selection_fidelity(selections, ["m1", "m2", "m3"])
        self.assertTrue(fidelity["passed"])

    def test_final_edl_reports_when_only_one_event_can_fill_target(self) -> None:
        selected = [{
            "id": "segment_1", "groupId": "event_a", "start": 0, "end": 8, "score": 94,
        }]
        optimized = optimize_edl(
            selected, candidate_pool=selected, target_seconds=30,
            order_mode="source", allow_fill=True, video_duration=40,
        )
        self.assertEqual(optimized["durationStatus"], "under_target")
        self.assertTrue(optimized["qualityReport"]["warnings"])

    def test_automatic_composition_signature_matches_plan_and_rendered_segments(self) -> None:
        plan = [{"candidateId": "segment_1", "start": 10.004, "end": 20.004}]
        rendered = [{"id": "segment_1", "start": 10.0, "end": 20.0}]
        self.assertEqual(automatic_composition_signature(plan), automatic_composition_signature(rendered))

    def test_automatic_composition_similarity_rejects_cosmetic_boundary_changes(self) -> None:
        left = automatic_composition_signature([
            {"id": "a", "start": 10, "end": 20}, {"id": "b", "start": 30, "end": 40},
        ])
        right = automatic_composition_signature([
            {"id": "x", "start": 10.5, "end": 20}, {"id": "y", "start": 30, "end": 39.5},
        ])
        distinct = automatic_composition_signature([
            {"id": "z", "start": 50, "end": 60},
        ])
        self.assertGreaterEqual(automatic_composition_similarity(left, right), .85)
        self.assertEqual(automatic_composition_similarity(left, distinct), 0.0)

    def test_duplicate_auto_plans_use_full_pool_until_user_confirms_events(self) -> None:
        def group(group_id: str, start: float, end: float, score: float) -> dict:
            segment = {
                "id": f"segment_{group_id}", "candidateId": f"candidate_{group_id}",
                "start": start, "end": end, "duration": end - start,
                "score": score, "role": "精彩镜头",
            }
            return {
                "id": group_id, "title": f"事件 {group_id}",
                "segments": [segment], "availableSegments": [segment],
            }

        job = {
            "recommendedGroupIds": ["event_a"],
            "eventGroups": [
                group("event_a", 0, 30, 96),
                group("event_b", 60, 89, 94),
                group("event_c", 120, 151, 92),
            ],
        }
        existing = [automatic_composition_signature([{"id": "segment_event_a", "start": 0, "end": 30}])]
        plans = distinct_event_replacement_plans(job, existing, 2, 30)

        self.assertTrue(plans)
        self.assertTrue(all(
            str(segment.get("groupId")) in {"event_b", "event_c"}
            for plan in plans for segment in plan.get("sequence") or []
        ))

        job["confirmedGroupIds"] = ["event_a"]
        self.assertEqual(distinct_event_replacement_plans(job, existing, 2, 30), [])

    def test_render_validation_preserves_reviewed_edl_over_target(self) -> None:
        selections = [{
            "id": "reviewed_reel",
            "segments": [
                {"id": "shot_a", "start": 0, "end": 12, "duration": 12, "editOrder": 0},
                {"id": "shot_b", "start": 240, "end": 270.6, "duration": 30.6, "editOrder": 1},
            ],
        }]
        validated, _ = _semantic_safe_selections(
            {"videoInfo": {"duration": 700}}, selections,
            order_mode="selection", target_seconds=None, allow_fill=False,
        )

        segments = validated[0]["segments"]
        self.assertEqual([item["id"] for item in segments], ["shot_a", "shot_b"])
        self.assertAlmostEqual(validated[0]["actualDuration"], 42.6, places=2)


class CompositionReviewTests(unittest.TestCase):
    def test_review_cache_key_changes_with_prompt_version(self) -> None:
        common = {
            "version_signature": "shots", "goal": {"objective": "高光"},
            "visual_model": "vlm", "llm_model": "llm",
        }
        self.assertNotEqual(
            review_cache_key(**common, prompt_version="prompt-v1"),
            review_cache_key(**common, prompt_version="prompt-v2"),
        )

    def test_review_sanitizer_ignores_batch_count_and_valid_transition_overlap(self) -> None:
        timeline = {
            "duration": 23.016,
            "segments": [
                {"segmentId": "a", "outputStart": 0, "outputEnd": 19.566, "transitionOverlap": 0, "transitionIn": {"type": "cut"}},
                {"segmentId": "b", "outputStart": 19.216, "outputEnd": 23.016, "transitionOverlap": .35, "transitionIn": {"type": "fade_black"}},
            ],
        }
        cleaned = sanitize_review_report({
            "issues": [
                {"id": "duration", "severity": "critical", "category": "duration", "outputTime": 23.016, "description": "成片仅23秒，且未完成生成两个30s高光视频的目标，仅产出1条视频"},
                {"id": "overlap", "severity": "major", "category": "continuity", "segmentIds": ["a", "b"], "outputTime": 19.216, "description": "outputEnd为19.566但下一镜头19.216开始，时间重叠"},
                {"id": "climax", "severity": "critical", "category": "climax", "outputTime": 18, "description": "高潮不够明确"},
            ],
            "repairActions": [],
        }, timeline=timeline, target_seconds=30)
        self.assertEqual(len(cleaned["issues"]), 2)
        self.assertNotIn("overlap", {item["id"] for item in cleaned["issues"]})
        duration = next(item for item in cleaned["issues"] if item["id"] == "duration")
        self.assertEqual(duration["severity"], "major")
        self.assertNotIn("两个", duration["description"])
        self.assertEqual(next(item for item in cleaned["issues"] if item["id"] == "climax")["severity"], "major")

    def test_review_sanitizer_only_keeps_evidence_backed_action_as_model_critical(self) -> None:
        cleaned = sanitize_review_report({
            "issues": [
                {"id": "content", "severity": "critical", "category": "content", "segmentIds": ["a"], "description": "内容不够精彩", "evidence": "主观判断"},
                {"id": "ending", "severity": "critical", "category": "ending", "segmentIds": ["b"], "description": "结尾不够有力", "evidence": "主观判断"},
                {"id": "action", "severity": "critical", "category": "action", "segmentIds": ["c"], "description": "动作中途被截断", "evidence": "动态画面显示手仍在移动"},
            ],
            "repairActions": [],
        }, timeline={"duration": 10, "segments": []})
        severity = {item["id"]: item["severity"] for item in cleaned["issues"]}
        self.assertEqual(severity, {"content": "major", "ending": "major", "action": "critical"})

    def test_review_sanitizer_uses_incoming_clip_semantics_for_audio_bridges(self) -> None:
        timeline = {
            "duration": 30,
            "segments": [
                {"segmentId": "setup", "eventId": "magic", "outputStart": 0, "audioBridge": {"type": "none"}},
                {"segmentId": "climax", "eventId": "magic", "outputStart": 10, "audioBridge": {"type": "j_cut"}},
                {"segmentId": "reaction", "eventId": "reaction", "outputStart": 20, "audioBridge": {"type": "none"}},
            ],
        }
        cleaned = sanitize_review_report({
            "issues": [{
                "id": "false_bridge", "severity": "major", "category": "audiovisual",
                "segmentIds": ["climax", "reaction"], "outputTime": 20,
                "description": "J-cut 从高潮延续到下一独立事件，形成跨事件声音桥",
            }],
            "repairActions": [],
        }, timeline=timeline)
        self.assertEqual(cleaned["issues"], [])
        self.assertEqual(cleaned["sanitizedIssueIds"], ["false_bridge"])

    def test_review_sanitizer_keeps_an_actual_cross_event_audio_bridge(self) -> None:
        timeline = {
            "duration": 20,
            "segments": [
                {"segmentId": "a", "eventId": "event_a", "outputStart": 0, "audioBridge": {"type": "none"}},
                {"segmentId": "b", "eventId": "event_b", "outputStart": 10, "audioBridge": {"type": "j_cut"}},
            ],
        }
        cleaned = sanitize_review_report({
            "issues": [{
                "id": "real_bridge", "severity": "major", "category": "audiovisual",
                "segmentIds": ["a", "b"], "outputTime": 10,
                "description": "不同事件之间使用 J-cut 声音桥",
            }],
            "repairActions": [],
        }, timeline=timeline)
        self.assertEqual([item["id"] for item in cleaned["issues"]], ["real_bridge"])

    def test_review_timeline_maps_source_to_rendered_time(self) -> None:
        timeline = composition_review_timeline([
            {"id": "s1", "start": 10, "end": 14, "playbackRate": 1.0},
            {"id": "s2", "start": 30, "end": 35, "playbackRate": 1.25,
             "transitionIn": {"type": "dissolve", "duration": .2}},
        ], [{"start": 10.5, "end": 12, "speaker": "A", "text": "完整表达"}])
        self.assertEqual(len(timeline["segments"]), 2)
        self.assertEqual(timeline["segments"][0]["transcript"][0]["text"], "完整表达")
        self.assertAlmostEqual(timeline["segments"][1]["outputStart"], 3.8, places=2)
        self.assertAlmostEqual(timeline["duration"], 7.8, places=2)

    def test_review_report_merges_scores_and_limits_actions(self) -> None:
        report = normalize_review_report(
            {"scores": {"continuity": 55}, "issues": [{
                "id": "v1", "severity": "major", "category": "continuity",
                "segmentIds": ["s2"], "description": "动作跳切", "evidence": "切点前后动作不连续",
            }]},
            {"overallScore": 68, "scores": {"content": 80}, "repairActions": [
                {"type": "set_transition", "segmentId": "s2", "transitionIn": {"type": "dissolve", "duration": .2}, "reason": "缓冲时空跳跃"},
                {"type": "invent_clip", "segmentId": "s2"},
            ]},
        )
        self.assertEqual(report["overallScore"], 68)
        self.assertEqual(report["majorCount"], 1)
        self.assertEqual(report["repairActions"][0]["type"], "set_transition")
        self.assertEqual(len(report["repairActions"]), 1)

    def test_repairs_are_constrained_to_candidate_boundaries(self) -> None:
        segments = [
            {"id": "s1", "candidateId": "c1", "start": 10, "end": 15, "role": "发展"},
            {"id": "s2", "candidateId": "c2", "start": 20, "end": 25, "role": "人物反应"},
        ]
        candidates = [
            {"id": "c1", "start": 9, "end": 16, "minimumKeepSeconds": 2},
            {"id": "c2", "start": 19, "end": 26, "minimumKeepSeconds": 2},
        ]
        repaired = apply_review_repairs(segments, [
            {"type": "adjust_bounds", "segmentId": "s1", "start": 5, "end": 18, "reason": "补完整动作"},
            {"type": "set_speed", "segmentId": "s2", "playbackRate": 1.25, "reason": "压缩反应"},
        ], candidates)
        self.assertEqual(repaired["segments"][0]["start"], 9)
        self.assertEqual(repaired["segments"][0]["end"], 16)
        self.assertEqual(len(repaired["appliedActions"]), 1)
        self.assertEqual(repaired["rejectedActions"][0]["rejectedReason"], "对白、高潮、反应或结尾镜头禁止自动变速")

    def test_repairs_prefer_verified_safe_boundaries_over_broad_candidate_window(self) -> None:
        repaired = apply_review_repairs(
            [{"id": "s1", "candidateId": "c1", "start": 10, "end": 14}],
            [{"type": "adjust_bounds", "segmentId": "s1", "start": 5, "end": 20, "reason": "补完整动作"}],
            [{"id": "c1", "start": 5, "end": 20, "safeStart": 8.5, "safeEnd": 16.25, "minimumKeepSeconds": 2}],
        )
        self.assertEqual(repaired["segments"][0]["start"], 8.5)
        self.assertEqual(repaired["segments"][0]["end"], 16.25)

    def test_review_can_insert_a_real_unused_candidate(self) -> None:
        repaired = apply_review_repairs(
            [{"id": "s1", "candidateId": "c1", "start": 1, "end": 4}],
            [{"type": "insert_segment", "replacementCandidateId": "c2", "afterSegmentId": "s1", "reason": "补充结果"}],
            [
                {"id": "c1", "start": 1, "end": 4, "minimumKeepSeconds": 1},
                {"id": "c2", "start": 8, "end": 12, "minimumKeepSeconds": 2, "storyFunction": "结果"},
            ],
        )
        self.assertEqual([item["candidateId"] for item in repaired["segments"]], ["c1", "c2"])
        self.assertEqual(len(repaired["appliedActions"]), 1)

    def test_review_can_smooth_both_sides_of_an_audio_cut(self) -> None:
        repaired = apply_review_repairs(
            [
                {"id": "s1", "candidateId": "c1", "start": 1, "end": 4},
                {"id": "s2", "candidateId": "c2", "start": 8, "end": 12},
            ],
            [{"type": "set_audio_fade", "segmentId": "s2", "audioFadeSeconds": .18, "reason": "平滑突变"}],
            [{"id": "c1", "start": 1, "end": 4}, {"id": "c2", "start": 8, "end": 12}],
        )
        self.assertEqual(repaired["segments"][0]["audioEdgeFadeSeconds"], .18)
        self.assertEqual(repaired["segments"][1]["audioEdgeFadeSeconds"], .18)

    def test_missing_editorial_actions_are_synthesized_from_measured_issues(self) -> None:
        segments = [
            {"id": "s1", "candidateId": "c1", "start": 0, "end": 5},
            {"id": "s2", "candidateId": "c2", "start": 10, "end": 15},
        ]
        actions = _synthesise_review_repairs(segments, {"issues": [
            {"severity": "major", "category": "audio_cut", "outputTime": 5, "description": "切点音量和波形突变"},
            {"severity": "critical", "category": "content", "segmentIds": ["s2"], "description": "动作未完整，操作中途结束，缺少结果状态"},
        ]}, [
            {"id": "c1", "start": 0, "end": 5, "safeStart": 0, "safeEnd": 5},
            {"id": "c2", "start": 8, "end": 18, "safeStart": 9, "safeEnd": 17},
        ])
        self.assertIn(("set_audio_fade", "s2"), {(item["type"], item["segmentId"]) for item in actions})
        self.assertIn(("adjust_bounds", "s2"), {(item["type"], item["segmentId"]) for item in actions})

    def test_quality_recovery_replaces_an_unavailable_problem_candidate(self) -> None:
        job = {
            "videoInfo": {"duration": 40}, "request": {"totalTargetSeconds": 8},
            "eventGroups": [{
                "id": "event", "title": "事件", "segments": [
                    {"id": "bad", "start": 0, "end": 4, "duration": 4, "score": 95, "actionComplete": False},
                    {"id": "good1", "start": 10, "end": 14, "duration": 4, "score": 90, "actionComplete": True},
                    {"id": "good2", "start": 20, "end": 24, "duration": 4, "score": 88, "actionComplete": True},
                ], "availableSegments": [],
            }],
            "brief": {"techniquePolicy": {"allowTransitions": False, "allowAudioBridges": False}},
        }
        result = _build_quality_recovery_sequence(
            job,
            {"targetSeconds": 8, "segments": [{"id": "bad", "candidateId": "bad", "groupId": "event", "start": 0, "end": 4, "actionComplete": False}]},
            {"issues": [{"severity": "critical", "category": "action", "segmentIds": ["bad"], "description": "动作未完整"}]},
            {"attempted": 1, "recovered": {}, "unavailable": ["bad"]},
            set(),
        )
        self.assertTrue(result["ok"])
        self.assertNotIn("bad", {item.get("candidateId") for item in result["segments"]})
        self.assertGreaterEqual(result["duration"], 6.4)

    def test_repair_is_only_preferred_for_real_improvement(self) -> None:
        before = {"overallScore": 72, "criticalCount": 0, "majorCount": 2}
        self.assertTrue(review_improved(before, {"overallScore": 75, "criticalCount": 0, "majorCount": 2}))
        self.assertTrue(review_improved(before, {"overallScore": 72, "criticalCount": 0, "majorCount": 1}))
        self.assertFalse(review_improved(before, {"overallScore": 74, "criticalCount": 1, "majorCount": 1}))

    def test_review_score_is_calibrated_by_rendered_media_failures(self) -> None:
        report = normalize_review_report(
            {"scores": {key: 90 for key in ("content", "narrative", "rhythm", "continuity", "audiovisual", "goalMatch")}},
            {"overallScore": 96, "scores": {"content": 95}},
        )
        calibrated = calibrate_review_report(report, media_evidence={
            "audioMetrics": {"issues": [{"severity": "major", "category": "audio_cut", "description": "突变"}]},
            "visualMetrics": {"blackFrameRatio": .12, "freezePairRatio": 0},
        }, target_seconds=30, actual_seconds=15)
        self.assertLess(calibrated["overallScore"], calibrated["modelOverallScore"])
        self.assertEqual(calibrated["calibrationVersion"], "composition-calibration-v7-root-cause-balanced")
        self.assertGreaterEqual(calibrated["majorCount"], 2)

    def test_review_calibration_penalizes_one_incomplete_action_only_once(self) -> None:
        report = normalize_review_report(
            {"scores": {key: 80 for key in ("content", "narrative", "rhythm", "continuity", "audiovisual", "goalMatch")}},
            {"overallScore": 80, "scores": {}, "issues": [
                {"severity": "major", "category": "action", "segmentIds": ["s1"], "description": "动作未完整呈现"},
                {"severity": "major", "category": "content", "segmentIds": ["s1"], "description": "动作在中途截断，缺少结果状态"},
                {"severity": "critical", "category": "unverified_evidence", "segmentIds": ["s1"], "description": "动作未完成，边界未验证"},
            ]},
        )
        calibrated = calibrate_review_report(report)
        self.assertEqual(calibrated["criticalCount"], 1)
        self.assertEqual(calibrated["majorCount"], 0)
        self.assertEqual(calibrated["deterministicPenalty"], 5.0)
        self.assertEqual(calibrated["overallScore"], 75.0)


class PublicJobPayloadTests(unittest.TestCase):
    def test_output_explanation_traces_selection_order_timing_and_quality(self) -> None:
        job = {
            "request": {"theme": "人物反应", "totalTargetSeconds": 30},
            "brief": {"focus": ["人物反应"], "excludeRules": ["片头广告"]},
            "eventGroups": [{"id": "e1", "title": "关键回应"}],
        }
        output = {
            "title": "情绪集中版", "displayName": "情绪集中版",
            "strategyDescription": "优先保留情绪高点", "duration": 28.4,
            "targetSeconds": 30, "durationStatus": "on_target", "eventGroupIds": ["e1"],
            "segments": [
                {"id": "s1", "groupId": "e1", "start": 10, "end": 16, "role": "事件建立", "reason": "交代人物与现场"},
                {"id": "s2", "groupId": "e1", "start": 20, "end": 28, "role": "人物反应", "reason": "保留情绪变化", "hasSpeech": True, "speechBoundaryStatus": "complete"},
            ],
            "qualityReport": {"score": 88, "passed": True, "userIntent": {"score": 91}},
        }
        explanation = build_output_editing_explanation(job, output, {"recommended": True})
        self.assertEqual(explanation["selection"]["eventTitles"], ["关键回应"])
        self.assertEqual(explanation["selection"]["shotCount"], 2)
        self.assertEqual(explanation["ordering"]["label"], "按源视频时间顺序")
        self.assertEqual(explanation["duration"]["statusLabel"], "已进入目标区间")
        self.assertEqual(explanation["quality"]["score"], 88)
        self.assertEqual(len(explanation["shots"]), 2)

    def test_new_jobs_snapshot_both_model_roles_without_credentials(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "source.mp4"
            source.touch()
            job = main_module.new_job_record(
                job_id="job_model_snapshot", source=source, filename="source.mp4",
                size=0, count="auto", target_seconds="auto", theme="",
            )
        self.assertIn("visionConfig", job)
        self.assertIn("llmConfig", job)
        self.assertNotIn("apiKey", json.dumps(job["visionConfig"]))
        self.assertNotIn("apiKey", json.dumps(job["llmConfig"]))

    def test_summary_and_status_exclude_heavy_review_evidence(self) -> None:
        job = {
            "id": "job_test", "revision": 7, "status": "running", "stage": "refine_vlm",
            "filename": "source.mp4", "workDirectory": "/tmp/job_test",
            "createdAt": "2026-08-10T00:00:00Z", "updatedAt": "2026-08-10T00:01:00Z",
            "videoInfo": {"duration": 60, "width": 1920, "height": 1080, "has_audio": True},
            "candidates": [{"index": 0, "evidence": ["large evidence"]}],
            "eventGroups": [{"id": "event_1", "segments": [{"id": "segment_1"}]}],
            "autoPlans": [{"sequence": [{"id": "segment_1"}]}],
            "autoComposition": {
                "status": "running", "phase": "rendering", "progress": .42,
                "completedVersions": 1, "totalVersions": 3, "currentVersion": 2,
                "plannedVariantCount": 3, "generatedVariantCount": 1, "repairVersionCount": 0,
                "currentVersionProgress": .26, "renderedSeconds": 7.8, "renderTotalSeconds": 30,
            },
            "messages": [{"text": "正在分析"}], "outputVersions": [],
        }
        summary = public_job_summary(job)
        status = public_job_status(job)
        self.assertEqual(summary["candidateCount"], 1)
        self.assertEqual(status["eventGroupCount"], 1)
        self.assertNotIn("candidates", summary)
        self.assertNotIn("eventGroups", status)
        self.assertNotIn("autoPlans", status)
        self.assertEqual(status["autoComposition"]["currentVersionProgress"], .26)
        self.assertEqual(status["autoComposition"]["renderedSeconds"], 7.8)
        self.assertEqual(status["autoComposition"]["plannedVariantCount"], 3)
        self.assertEqual(status["autoComposition"]["generatedVariantCount"], 1)
        self.assertTrue(summary["execution"]["active"])
        self.assertEqual(summary["execution"]["operation"], "auto_composition")
        self.assertEqual(status["execution"]["status"], "running")
        self.assertEqual(status["execution"]["progress"]["completed"], 1)

    def test_execution_counts_independent_rejections_separately_from_repairs(self) -> None:
        snapshot = execution_snapshot({
            "id": "quality_counts", "status": "awaiting_confirmation", "stage": "auto_composition",
            "outputs": [], "outputVersions": [],
            "autoComposition": {
                "status": "completed", "phase": "done",
                "plannedVariantCount": 3, "generatedVariantCount": 3,
                "qualityPassedCount": 0, "rejectedVersionCount": 5,
                "qualityRejectedVariantCount": 3, "qualityRejectedRepairCount": 2,
            },
        })
        self.assertEqual(snapshot["result"]["qualityRejectedCount"], 3)
        self.assertEqual(snapshot["result"]["qualityRejectedRepairCount"], 2)

    def test_manual_review_draft_keeps_no_acceptable_output_outcome(self) -> None:
        snapshot = execution_snapshot({
            "id": "quality_manual", "status": "awaiting_confirmation", "stage": "auto_composition",
            "outputs": [{"filename": "draft.mp4"}],
            "outputVersions": [{
                "id": "v001", "previewOnly": True, "manualReviewRequired": True,
                "outputs": [{"filename": "draft.mp4"}],
                "qualityGate": {"passed": False},
            }],
            "autoComposition": {
                "status": "completed", "phase": "done", "qualityPassedCount": 0,
                "rejectedVersionCount": 1, "qualityRejectedVariantCount": 1,
                "manualReviewRequired": True,
            },
        })
        self.assertEqual(snapshot["outcome"], "no_acceptable_output")
        self.assertEqual(snapshot["result"]["qualityPassedCount"], 0)

    def test_public_preview_output_uses_sample_directly_and_stays_marked(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "source.mp4"
            source.touch()
            job = main_module.new_job_record(
                job_id="job_preview", source=source, filename="source.mp4",
                size=0, count="auto", target_seconds="auto", theme="",
            )
            job["outputDirectory"] = str(root)
            job["outputVersions"] = [{
                "id": "v001", "number": 1, "previewOnly": True,
                "outputs": [{"filename": "sample.mp4", "title": "AI 样片", "previewOnly": True}],
            }]
            visible = main_module.public_job(job)
        output = visible["outputVersions"][0]["outputs"][0]
        self.assertTrue(output["previewOnly"])
        self.assertTrue(output["previewReady"])
        self.assertEqual(output["previewUrl"], "/api/jobs/job_preview/outputs/sample.mp4")

    def test_public_highlight_job_hides_legacy_raw_signal_candidates_and_groups(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "source.mp4"
            source.touch()
            job = main_module.new_job_record(
                job_id="job_signal_gate", source=source, filename="source.mp4",
                size=0, count="auto", target_seconds="auto", theme="",
            )
            concrete = {
                "id": "event_concrete", "title": "男子打开冰箱", "summary": "取出食材",
                "assemblyStrategy": "adaptive", "segments": [{"start": 5, "end": 9}],
            }
            raw = {
                "id": "event_signal", "title": "画面变化热点", "summary": "变化强度高",
                "assemblyStrategy": "source_order", "segments": [{"start": 12, "end": 18}],
            }
            job.update({
                "taskMode": "highlight", "eventGroups": [concrete, raw],
                "recommendedGroupIds": ["event_signal", "event_concrete"],
                "recommendedIndices": [0, 1],
                "outputs": [{
                    "filename": "legacy.mp4", "segments": [{
                        "id": "legacy_segment", "candidateId": "candidate_1",
                        "chapterId": "event_signal", "chapterTitle": "画面变化热点",
                        "start": 12, "end": 18, "role": "核心镜头",
                    }],
                }],
                "candidates": [{
                    "index": 0, "title": "声音能量热点", "start": 12, "end": 18,
                    "candidateOrigin": "waveform", "semanticStatus": "recall_only",
                }, {
                    "index": 1, "title": "男子打开冰箱", "start": 5, "end": 9,
                    "candidateOrigin": "vlm", "semanticStatus": "verified",
                }],
            })
            visible = main_module.public_job(job)
        self.assertEqual([group["id"] for group in visible["eventGroups"]], ["event_concrete"])
        self.assertEqual(visible["recommendedGroupIds"], ["event_concrete"])
        self.assertEqual(visible["recommendedIndices"], [1])
        self.assertEqual([item["title"] for item in visible["candidates"]], ["男子打开冰箱"])
        self.assertEqual(visible["eventGroupCount"], 1)
        self.assertEqual(visible["candidateCount"], 1)
        output_segment = visible["outputs"][0]["segments"][0]
        self.assertTrue(output_segment["eventGroupId"].startswith("legacy_unclassified_"))
        self.assertIn("待重新分析", output_segment["eventTitle"])
        self.assertNotIn("热点", output_segment["eventTitle"])

    def test_public_job_exposes_retained_manual_review_preview(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "source.mp4"
            source.touch()
            (root / "draft.mp4").touch()
            job = main_module.new_job_record(
                job_id="job_manual_preview", source=source, filename="source.mp4",
                size=0, count="auto", target_seconds="auto", theme="",
            )
            version = {
                "id": "v001", "number": 1, "previewOnly": True,
                "manualReviewRequired": True, "reviewStatus": "needs_user_review",
                "qualityGate": {"passed": False, "score": 48},
                "outputs": [{"filename": "draft.mp4", "previewOnly": True}],
            }
            job.update({
                "status": "awaiting_confirmation", "stage": "auto_composition",
                "outputDirectory": str(root), "outputVersions": [version],
                "outputs": list(version["outputs"]), "currentOutputVersionId": "v001",
                "autoComposition": {
                    "status": "completed", "phase": "done", "qualityPassedCount": 0,
                    "rejectedVersionCount": 1, "qualityRejectedVariantCount": 1,
                    "manualReviewRequired": True, "manualReviewVersionId": "v001",
                },
            })
            visible = main_module.public_job(job)
        self.assertEqual(len(visible["outputVersions"]), 1)
        self.assertEqual(len(visible["outputs"]), 1)
        self.assertTrue(visible["outputVersions"][0]["manualReviewRequired"])
        self.assertEqual(visible["execution"]["outcome"], "no_acceptable_output")

    def test_recoverable_auto_render_keeps_review_state_and_retries_clean_batch(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            old = root / "old.mp4"
            interrupted = root / "interrupted.mp4"
            old.touch()
            interrupted.touch()
            job = {
                "id": "job_recover_auto", "status": "awaiting_confirmation",
                "stage": "auto_composition", "outputDirectory": str(root),
                "outputVersions": [
                    {"id": "v001", "number": 1, "outputs": [{"filename": old.name}]},
                    {"id": "v002", "number": 2, "previewOnly": True, "outputs": [{"filename": interrupted.name}]},
                ],
                "outputs": [{"filename": interrupted.name}], "currentOutputVersionId": "v002",
                "autoComposition": {
                    "status": "running", "phase": "llm_plan",
                    "generatedVariantCount": 1, "completedVersions": 1,
                },
            }
            main_module._prepare_recoverable_render_job(job)
            self.assertEqual(job["status"], "awaiting_confirmation")
            self.assertEqual(job["autoComposition"]["status"], "queued")
            self.assertTrue(job["autoComposition"]["recovering"])
            files = main_module._discard_interrupted_automatic_previews(job)
            self.assertEqual(files, [interrupted])
            self.assertEqual([item["id"] for item in job["outputVersions"]], ["v001"])
            self.assertEqual(job["currentOutputVersionId"], "v001")
            self.assertNotIn("recovering", job["autoComposition"])

    def test_interrupted_partial_preview_becomes_visible_manual_draft(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            preview = root / "interrupted.mp4"
            source = root / "source.mp4"
            preview.touch()
            source.touch()
            version = {
                "id": "v001", "number": 1, "previewOnly": True,
                "outputs": [{"filename": preview.name, "previewOnly": True}],
            }
            job = main_module.new_job_record(
                job_id="job_interrupted_preview", source=source, filename="source.mp4",
                size=0, count="auto", target_seconds="auto", theme="",
            )
            job.update({
                "status": "awaiting_confirmation", "outputDirectory": str(root),
                "outputVersions": [version], "outputs": list(version["outputs"]),
                "currentOutputVersionId": "v001", "autoComposition": {"status": "partial"},
            })
            self.assertTrue(main_module._retain_interrupted_auto_previews(job))
            visible = main_module.public_job(job)
        self.assertTrue(job["outputVersions"][0]["manualReviewRequired"])
        self.assertEqual(len(visible["outputVersions"]), 1)
        self.assertEqual(len(visible["outputs"]), 1)

    def test_accepts_literal_control_character_in_json_string(self) -> None:
        parsed = parse_json_object('{"reason":"line one\nline two"}')
        self.assertEqual(parsed["reason"], "line one\nline two")

    def test_removes_untrusted_model_timecodes_from_evidence(self) -> None:
        cleaned = clean_model_evidence(["起点证据：T=00:08:04 药房工作人员出现", "7.52秒展示医院外景"])
        self.assertNotIn("00:08:04", cleaned[0])
        self.assertNotIn("7.52秒", cleaned[1])

    def test_ark_sends_distinct_system_and_user_messages(self) -> None:
        response = MagicMock(status_code=200)
        response.json.return_value = {
            "choices": [{"message": {"content": '{"ok":true}'}}],
            "usage": {"total_tokens": 3},
        }
        http_client = MagicMock()
        http_client.post.return_value = response
        context = MagicMock()
        context.__enter__.return_value = http_client
        with patch("app.ark_client.httpx.Client", return_value=context):
            client = ArkVisionClient(api_key="test", model="vlm", base_url="https://example.test")
            result = client.complete_json("USER PROMPT", system_prompt="SYSTEM PROMPT")
        payload = http_client.post.call_args.kwargs["json"]
        self.assertEqual(payload["messages"], [
            {"role": "system", "content": "SYSTEM PROMPT"},
            {"role": "user", "content": "USER PROMPT"},
        ])
        self.assertTrue(result["ok"])

    def test_vision_settings_override_legacy_ark_configuration(self) -> None:
        with patch.dict(os.environ, {
            "VISION_PROVIDER": "openai_compatible",
            "VISION_API_KEY": "generic-key",
            "VISION_MODEL": "generic-vlm",
            "VISION_BASE_URL": "https://vision.example/v1",
            "VISION_THINKING_TYPE": "",
            "VISION_RESPONSE_FORMAT": "none",
        }):
            settings = Settings.from_environment()
        self.assertEqual(settings.vision_provider, "openai_compatible")
        self.assertEqual(settings.vision_api_key, "generic-key")
        self.assertEqual(settings.vision_model, "generic-vlm")
        self.assertEqual(settings.vision_base_url, "https://vision.example/v1")
        self.assertEqual(settings.vision_thinking_type, "")
        self.assertEqual(settings.vision_response_format, "none")

    def test_generic_vision_client_can_omit_provider_extensions(self) -> None:
        response = MagicMock(status_code=200)
        response.json.return_value = {"choices": [{"message": {"content": '{"ok":true}'}}]}
        http_client = MagicMock()
        http_client.post.return_value = response
        context = MagicMock()
        context.__enter__.return_value = http_client
        with patch("app.ark_client.httpx.Client", return_value=context):
            client = OpenAICompatibleVisionClient(
                api_key="test",
                model="generic-vlm",
                base_url="https://example.test/v1/chat/completions",
                thinking_type="",
                response_format="none",
            )
            result = client.complete_json("PROMPT")
        payload = http_client.post.call_args.kwargs["json"]
        self.assertNotIn("thinking", payload)
        self.assertNotIn("response_format", payload)
        self.assertEqual(client.url, "https://example.test/v1/chat/completions")
        self.assertTrue(result["ok"])

    def test_discovers_and_prioritizes_probable_visual_models(self) -> None:
        response = MagicMock(status_code=200)
        response.json.return_value = {"data": [
            {"id": "text-embedding-3-small", "owned_by": "provider"},
            {"id": "gpt-4.1", "owned_by": "provider"},
            {"id": "custom-vlm", "owned_by": "team"},
        ]}
        with patch("app.vision_settings.httpx.get", return_value=response) as request:
            models = discover_models(api_key="secret", base_url="https://example.test/v1", provider="openai")
        self.assertEqual(request.call_args.args[0], "https://example.test/v1/models")
        self.assertEqual([item["id"] for item in models], ["custom-vlm", "gpt-4.1"])
        self.assertTrue(all(item["recommended"] for item in models))

    def test_model_discovery_uses_explicit_image_capability_when_available(self) -> None:
        response = MagicMock(status_code=200)
        response.json.return_value = {"data": [
            {"id": "doubao-text", "status": "Active", "modalities": {"input_modalities": ["text"]}},
            {"id": "doubao-vision", "status": "Active", "modalities": {"input_modalities": ["text", "image", "video"]}},
            {"id": "old-vision", "status": "Shutdown", "modalities": {"input_modalities": ["image"]}},
        ]}
        with patch("app.vision_settings.httpx.get", return_value=response):
            models = discover_models(api_key="secret", base_url="https://example.test/v1", provider="ark")
        self.assertEqual([item["id"] for item in models], ["doubao-vision"])
        self.assertTrue(models[0]["supportsImage"])
        self.assertTrue(models[0]["supportsVideo"])

    def test_runtime_vision_settings_never_expose_full_key(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "vision-settings.json"
            store = VisionConfigurationStore(path, {
                "provider": "ark", "apiKey": "environment-secret", "model": "default-vlm",
                "baseUrl": "https://ark.example/v3", "thinkingType": "disabled",
                "responseFormat": "json_object", "timeoutSeconds": 90,
            })
            store.save(
                provider="openai", api_key="saved-secret-value", model="gpt-4.1",
                base_url="https://api.openai.com/v1", thinking_type="",
                response_format="json_object", models=[{"id": "gpt-4.1", "recommended": True}],
            )
            public = store.public_state()
            self.assertNotIn("saved-secret-value", json.dumps(public))
            self.assertIn("save****alue", json.dumps(public))
            self.assertEqual(path.stat().st_mode & 0o777, 0o600)

    def test_discovers_text_models_without_utility_models(self) -> None:
        response = MagicMock(status_code=200)
        response.json.return_value = {"data": [
            {"id": "text-embedding-3-small"},
            {"id": "gpt-4.1", "modalities": {"input_modalities": ["text", "image"], "output_modalities": ["text"]}},
            {"id": "video-generation-model", "modalities": {"input_modalities": ["text"], "output_modalities": ["video"]}},
            {"id": "reasoning-model", "modalities": {"input_modalities": ["text"], "output_modalities": ["text"]}},
        ]}
        with patch("app.vision_settings.httpx.get", return_value=response) as request:
            models = discover_llm_models(
                api_key="secret", base_url="https://example.test/v1",
                provider="openai_compatible", protocol="openai",
            )
        self.assertEqual(request.call_args.args[0], "https://example.test/v1/models")
        self.assertEqual([item["id"] for item in models], ["gpt-4.1", "reasoning-model"])

    def test_anthropic_model_discovery_uses_native_headers(self) -> None:
        response = MagicMock(status_code=200)
        response.json.return_value = {"data": [{"id": "claude-sonnet", "display_name": "Claude Sonnet"}]}
        with patch("app.vision_settings.httpx.get", return_value=response) as request:
            models = discover_llm_models(
                api_key="anthropic-secret", base_url="https://api.anthropic.com",
                provider="anthropic", protocol="anthropic",
            )
        self.assertEqual(request.call_args.args[0], "https://api.anthropic.com/v1/models")
        self.assertEqual(request.call_args.kwargs["headers"]["x-api-key"], "anthropic-secret")
        self.assertEqual([item["id"] for item in models], ["claude-sonnet"])

    def test_ark_anthropic_compatibility_uses_ark_model_catalog(self) -> None:
        response = MagicMock(status_code=200)
        response.json.return_value = {"data": [{"id": "doubao-seed-evolving"}]}
        with patch("app.vision_settings.httpx.get", return_value=response) as request:
            models = discover_llm_models(
                api_key="ark-secret", base_url="https://ark.cn-beijing.volces.com/api/compatible",
                provider="anthropic_compatible", protocol="anthropic",
            )
        self.assertEqual(request.call_args.args[0], "https://ark.cn-beijing.volces.com/api/v3/models")
        self.assertEqual(request.call_args.kwargs["headers"]["Authorization"], "Bearer ark-secret")
        self.assertEqual([item["id"] for item in models], ["doubao-seed-evolving"])

    def test_runtime_llm_settings_support_reuse_and_independent_modes(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "llm-settings.json"
            store = LlmConfigurationStore(path, {
                "mode": "reuse_vision", "provider": "ark", "apiKey": "environment-secret",
                "model": "default-text", "baseUrl": "https://ark.example/v3",
                "thinkingType": "disabled", "responseFormat": "json_object", "timeoutSeconds": 60,
            })
            self.assertTrue(store.public_state()["reuseVision"])
            store.save(
                reuse_vision=False, provider="openai", api_key="saved-llm-secret",
                model="gpt-4.1", base_url="https://api.openai.com/v1",
                thinking_type="", response_format="json_object",
                models=[{"id": "gpt-4.1", "recommended": True}],
            )
            public = store.public_state()
            self.assertFalse(public["reuseVision"])
            self.assertNotIn("saved-llm-secret", json.dumps(public))
            self.assertEqual(store.snapshot()["model"], "gpt-4.1")
            store.save(reuse_vision=True)
            self.assertEqual(store.snapshot(), {"mode": "reuse_vision"})
            self.assertEqual(path.stat().st_mode & 0o777, 0o600)


class PromptContractTests(unittest.TestCase):
    def test_four_stage_prompts_have_separate_contracts(self) -> None:
        profile = normalize_content_profile({
            "primary_type": "纪实调查",
            "narrative_mode": "综合信号",
            "highlight_definition": ["信息揭露"],
            "evidence_weights": {"visual": .5, "speech": .4, "audio": .1},
        }, "人物反应")
        classification = content_classification_prompt(video_duration=60, theme="人物反应", analysis_mode="visual")
        discovery = coarse_discovery_prompt(
            content_profile=profile, theme="人物反应", video_duration=60,
            exclusions="无排除区间", audio_context="无音频信息",
        )
        refinement = boundary_refinement_prompt(
            content_profile=profile, theme="人物反应", candidate_title="受访者停顿",
            candidate_role="人物反应", video_duration=60, exclusions="无排除区间",
            speech_context="",
        )
        director = event_director_prompt(
            moments=[{"index": 0, "start": 1, "end": 5, "score": 90, "title": "反应",
                      "role": "人物反应", "possibleEvent": "采访", "reason": "表情变化", "evidence": []}],
            content_profile=profile, theme="人物反应", requested_count=1,
            total_target_seconds=30, transcript_available=False,
        )
        self.assertTrue(PROMPT_VERSION.startswith("highlight-director-v13-semantic-signal-gate"))
        self.assertIn("不得虚构", COMMON_SYSTEM_PROMPT)
        self.assertIn('"primary_type"', classification)
        self.assertIn('"center_seconds"', discovery)
        self.assertIn('"start_seconds"', refinement)
        self.assertIn('"peak_start_seconds"', refinement)
        self.assertIn('"boundary_confidence"', refinement)
        self.assertIn('"event_groups"', director)
        self.assertIn("START、PEAK、END", director)
        self.assertIn("requires_candidate_indices", director)
        self.assertIn("召回线索，不是事件", director)
        self.assertIn("无法确认具体内容时必须 keep=false", refinement)


class EditingIntentTests(unittest.TestCase):
    def test_chat_feedback_becomes_durable_constraints(self) -> None:
        brief, changes = apply_user_feedback_to_brief(
            {"focus": ["人物反应"]},
            "开头太慢，不要片头广告，必须保留医生结论，目标控制在45秒，保持原顺序",
        )
        self.assertEqual(brief["targetDurationSeconds"], 45)
        self.assertIn("片头广告", brief["excludeRules"])
        self.assertIn("医生结论", brief["includeRules"])
        self.assertEqual(brief["style"]["pace"], "紧凑")
        self.assertFalse(brief["style"]["allowReorder"])
        self.assertGreaterEqual(len(changes), 4)

    def test_intent_filters_exclusions_and_requires_explicit_keep(self) -> None:
        intent = compile_editing_intent({
            "targetDurationSeconds": 10,
            "includeRules": ["医生结论"],
            "excludeRules": ["广告"],
        }, {})
        self.assertTrue(candidate_requirement_alignment({"title": "片头广告"}, intent)["hardRejected"])
        missing = evaluate_sequence_against_intent([
            {"id": "s1", "start": 0, "end": 10, "title": "普通介绍", "speechBoundaryStatus": "complete"},
        ], intent)
        self.assertIn("医生结论", missing["missingIncludeRules"])
        self.assertFalse(missing["passed"])
        covered = evaluate_sequence_against_intent([
            {"id": "s2", "start": 0, "end": 10, "title": "医生结论", "speechBoundaryStatus": "complete"},
        ], intent)
        self.assertTrue(covered["passed"])

    def test_adaptive_sampling_bounds_typical_vlm_round_trips(self) -> None:
        frames = coarse_frame_limit(263)
        refined = refinement_candidate_limit(
            discovery_only=True, total_target_seconds=30, target_seconds=8, count=6,
            video_duration=263,
        )
        discovery_pages = math.ceil(frames / 16)
        base_calls = 1 + discovery_pages + refined + 1
        self.assertEqual(frames, 48)
        self.assertEqual(refined, 4)
        # Only the two strongest candidates may request a second boundary pass.
        self.assertLessEqual(base_calls + 2, 15)

    def test_long_video_sampling_uses_duration_tiers(self) -> None:
        self.assertEqual(coarse_frame_limit(600), 72)
        self.assertEqual(coarse_frame_limit(601), 96)
        self.assertEqual(coarse_frame_limit(1801), 120)
        self.assertEqual(coarse_frame_limit(3601), 150)
        self.assertEqual(coarse_frame_limit(7201), 180)
        self.assertEqual(coarse_frame_limit(9002), 180)

    def test_priority_sampling_combines_global_evidence_within_budget(self) -> None:
        duration = 9000.0
        times = coarse_priority_times(
            duration=duration,
            frame_budget=180,
            scene_cuts=[100, 2000, 4000, 6000, 8000],
            waveform={"rms": [.1, .9, .2, .8, .1, .7, .2, .6]},
            speech_segments=[
                {"start": 500, "end": 510},
                {"start": 4500, "end": 4510},
                {"start": 8500, "end": 8510},
            ],
        )
        self.assertLessEqual(len(times), 45)
        self.assertTrue(any(value < 1000 for value in times))
        self.assertTrue(any(value > 8000 for value in times))

    def test_priority_frames_replace_nearest_uniform_frames_without_growing_budget(self) -> None:
        uniform = [SampledFrame(Path(f"u-{index}.jpg"), index * 10.0) for index in range(10)]
        priority = [SampledFrame(Path("p-1.jpg"), 23.0), SampledFrame(Path("p-2.jpg"), 77.0)]
        merged = merge_priority_frames(uniform, priority)
        self.assertEqual(len(merged), len(uniform))
        self.assertEqual(merged[0].time, 0.0)
        self.assertEqual(merged[-1].time, 90.0)
        self.assertIn(23.0, [item.time for item in merged])
        self.assertIn(77.0, [item.time for item in merged])


class SenseVoiceParsingTests(unittest.TestCase):
    @staticmethod
    def _speaker_vector(axis: int, blend: float = 0.0) -> list[float]:
        vector = [0.0] * 192
        vector[axis] = 1.0
        if blend:
            vector[(axis + 1) % 192] = blend
        return vector

    def test_short_diarization_does_not_force_distinct_voices_into_one_speaker(self) -> None:
        rows = [
            self._speaker_vector(0, .03), self._speaker_vector(0, .07),
            self._speaker_vector(0, .11), self._speaker_vector(0, .15),
            self._speaker_vector(8, .03), self._speaker_vector(8, .07),
            self._speaker_vector(8, .11), self._speaker_vector(8, .15),
        ]
        labels = _cluster_short_speaker_embeddings(rows)
        self.assertEqual(len(set(int(value) for value in labels)), 2)

    def test_short_diarization_keeps_one_compact_voice_together(self) -> None:
        rows = [self._speaker_vector(0, value) for value in (.01, .03, .05, .07, .09, .11)]
        labels = _cluster_short_speaker_embeddings(rows)
        self.assertEqual(len(set(int(value) for value in labels)), 1)

    def test_expected_speaker_count_overrides_automatic_clustering(self) -> None:
        rows = [self._speaker_vector(0, value) for value in (.01, .02, .03, .04)]
        labels = _cluster_short_speaker_embeddings(rows, oracle_num=2)
        self.assertEqual(len(set(int(value) for value in labels)), 2)

    def test_native_punctuation_does_not_download_external_punc_model(self) -> None:
        options = _sensevoice_model_options(
            model_name="iic/SenseVoiceSmall",
            device="cpu",
            vad_model="fsmn-vad",
            punc_model="",
            spk_model="cam++",
            diarization=False,
        )
        self.assertNotIn("punc_model", options)
        self.assertNotIn("spk_model", options)

    def test_optional_speaker_model_uses_vad_aligned_segments(self) -> None:
        options = _sensevoice_model_options(
            model_name="iic/SenseVoiceSmall",
            device="cpu",
            vad_model="fsmn-vad",
            punc_model="ct-punc",
            spk_model="cam++",
            diarization=True,
        )
        self.assertEqual(options["punc_model"], "ct-punc")
        self.assertEqual(options["spk_model"], "cam++")
        self.assertEqual(options["spk_mode"], "vad_segment")

    def test_v2_speaker_vad_uses_three_second_chunks(self) -> None:
        options = _sensevoice_model_options(
            model_name="iic/SenseVoiceSmall", device="cpu", vad_model="fsmn-vad",
            punc_model="", spk_model="cam++", diarization=True,
            algorithm_version="editing-algorithm-v2",
        )
        self.assertEqual(options["vad_kwargs"]["max_single_segment_time"], 3000)

    def test_v2_overlapping_turns_are_cannot_linked_and_reviewable(self) -> None:
        turns = enforce_speaker_turn_contract([
            {"start": 0, "end": 2, "speaker": "Speaker 1", "text": "第一个人在说话", "words": [{"text": "一"}]},
            {"start": 1.5, "end": 3, "speaker": "Speaker 1", "text": "另一个重叠声音", "words": [{"text": "二"}]},
        ])
        self.assertNotEqual(turns[0]["speaker"], turns[1]["speaker"])
        self.assertEqual(turns[1]["overlapStatus"], "separated_overlap")
        self.assertTrue(turns[1]["requiresReview"])
        self.assertIn("clusterConfidence", turns[0])
        self.assertIn("boundaryConfidence", turns[0])

    def test_normalizes_rich_tags_speakers_and_timestamps(self) -> None:
        result = normalize_sensevoice_result([{
            "text": "<|zh|><|HAPPY|><|Speech|>完整内容",
            "sentence_info": [
                {"start": 0, "end": 1250, "text": "<|zh|><|NEUTRAL|><|Speech|>主持人开场", "spk": 7},
                {"start": 1300, "end": 2800, "text": "<|ANGRY|><|Applause|>受访者反驳", "spk": 3},
                {"start": 2900, "end": 3500, "text": "<|Laughter|>现场回应", "spk": 7},
            ],
        }])
        self.assertEqual(result["language"], "zh")
        self.assertTrue(result["diarization"])
        self.assertEqual([item["speaker"] for item in result["segments"]], ["Speaker 1", "Speaker 2", "Speaker 1"])
        self.assertEqual(result["segments"][1]["start"], 1.3)
        self.assertEqual(result["segments"][1]["emotion"], "angry")
        self.assertEqual(result["segments"][1]["audioEvents"], ["applause"])

    def test_normalizes_vad_sentence_field_and_list_text(self) -> None:
        result = normalize_sensevoice_result([{
            "text": ["完整", "逐字稿"],
            "sentence_info": [
                {"start": 1000, "end": 2400, "sentence": "<|zh|><|Speech|>第一位发言", "spk": 4},
                {"start": 2500, "end": 4100, "sentence": ["第二位", "回应"], "spk": 9},
            ],
        }])
        self.assertEqual([item["text"] for item in result["segments"]], ["第一位发言", "第二位 回应"])
        self.assertEqual([item["speaker"] for item in result["segments"]], ["Speaker 1", "Speaker 2"])

    def test_splits_strong_punctuation_with_token_timestamps(self) -> None:
        result = normalize_sensevoice_result([{
            "text": "你好。继续！",
            "sentence_info": [{
                "start": 1000, "end": 4000, "text": "你好。继续！",
                "timestamp": [[0, 400], [400, 800], [800, 900], [1000, 1500], [1500, 2100], [2100, 2200]],
            }],
        }])
        self.assertEqual([item["text"] for item in result["segments"]], ["你好。", "继续！"])
        self.assertEqual((result["segments"][0]["start"], result["segments"][0]["end"]), (1.0, 1.9))
        self.assertEqual((result["segments"][1]["start"], result["segments"][1]["end"]), (2.0, 3.2))
        self.assertTrue(all(item["timingSource"] == "sensevoice_token_timestamp" for item in result["segments"]))

    def test_repairs_file_length_sensevoice_segment_instead_of_failing(self) -> None:
        transcript = " ".join(f"word{index}" for index in range(160))
        result = normalize_sensevoice_result([{
            "text": transcript,
            "sentence_info": [{"start": 0, "end": 240000, "text": transcript}],
        }])
        segments = result["segments"]
        self.assertEqual(result["repairedLongSegments"], 1)
        self.assertEqual(result["droppedLongSegments"], 0)
        self.assertEqual(len(segments), 4)
        self.assertTrue(all(item["end"] - item["start"] <= 60.001 for item in segments))
        self.assertTrue(all(item["timingApproximate"] for item in segments))
        self.assertEqual(" ".join(item["text"] for item in segments), transcript)

    def test_drops_punctuation_only_file_length_segment(self) -> None:
        result = normalize_sensevoice_result([{
            "text": ".",
            "sentence_info": [{"start": 0, "end": 180000, "text": "."}],
        }])
        self.assertEqual(result["segments"], [])
        self.assertEqual(result["repairedLongSegments"], 0)
        self.assertEqual(result["droppedLongSegments"], 1)

    def test_builds_bounded_rich_context_and_candidate_evidence(self) -> None:
        segments = [
            {"start": 1, "end": 3, "text": "关键观点", "speaker": "Speaker 1", "emotion": "angry", "audioEvents": [], "language": "zh"},
            {"start": 3, "end": 5, "text": "现场鼓掌", "speaker": "Speaker 2", "emotion": "happy", "audioEvents": ["applause"], "language": "zh"},
        ]
        context = transcript_context(segments, 0, 6)
        evidence = speech_evidence(segments, 2, 4)
        self.assertIn("Speaker 1", context)
        self.assertIn("emotion=angry", context)
        self.assertEqual(evidence["speakers"], ["Speaker 1", "Speaker 2"])
        self.assertEqual(evidence["speakerTurns"], 1)
        self.assertEqual(evidence["audioEvents"], ["applause"])
        self.assertNotIn("male", context.lower())

    def test_strips_tags_without_losing_text(self) -> None:
        parsed = parse_rich_tags("<|yue|><|SAD|><|BGM|>今日天气转差")
        self.assertEqual(parsed["text"], "今日天气转差")
        self.assertEqual(parsed["language"], "yue")
        self.assertEqual(parsed["emotions"], ["sad"])
        self.assertEqual(parsed["audioEvents"], ["bgm"])


class StoreTests(unittest.TestCase):
    def test_sqlite_job_store_round_trip(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            store = JobStore(Path(directory) / "jobs.sqlite3")
            store.save({"id": "job_test", "status": "queued", "updatedAt": "2026-01-01"})
            self.assertEqual(store.load_all()[0]["id"], "job_test")
            store.delete("job_test")
            self.assertEqual(store.load_all(), [])


class JobCancellationTests(unittest.TestCase):
    @staticmethod
    def _job(job_id: str, status: str) -> dict:
        return {
            "id": job_id, "status": status, "stage": status, "progress": 0.0,
            "detail": status, "filename": "source.mp4", "messages": [],
            "sourcePath": f"/tmp/{job_id}-source.mp4",
            "workDirectory": f"/tmp/{job_id}-work",
            "outputDirectory": f"/tmp/{job_id}-outputs",
            "outputs": [], "outputVersions": [], "eventGroups": [], "candidates": [],
            "request": {}, "createdAt": "2026-01-01T00:00:00+00:00",
            "updatedAt": "2026-01-01T00:00:00+00:00",
        }

    def tearDown(self) -> None:
        for job_id in ("job_cancel_queued", "job_cancel_running", "job_cancel_orphan", "job_cancel_brief", "job_cancel_auto"):
            main_module.jobs.pop(job_id, None)
            main_module.cancel_events.pop(job_id, None)
            main_module.analysis_futures.pop(job_id, None)
            main_module.render_futures.pop(job_id, None)
            main_module.active_ark_clients.pop(job_id, None)

    def test_queued_future_is_removed_and_becomes_cancelled_immediately(self) -> None:
        job_id = "job_cancel_queued"
        future: Future = Future()
        event = main_module.threading.Event()
        main_module.jobs[job_id] = self._job(job_id, "queued")
        main_module.cancel_events[job_id] = event
        main_module.analysis_futures[job_id] = future
        with patch.object(main_module, "save_job"):
            result = main_module.cancel_job(job_id)["job"]
        self.assertTrue(future.cancelled())
        self.assertTrue(event.is_set())
        self.assertEqual(result["status"], "cancelled")
        self.assertNotIn(job_id, main_module.analysis_futures)
        self.assertNotIn(job_id, main_module.cancel_events)

    def test_running_future_signals_worker_and_closes_model_client(self) -> None:
        job_id = "job_cancel_running"
        future: Future = Future()
        self.assertTrue(future.set_running_or_notify_cancel())
        event = main_module.threading.Event()
        client = MagicMock()
        main_module.jobs[job_id] = self._job(job_id, "running")
        main_module.cancel_events[job_id] = event
        main_module.analysis_futures[job_id] = future
        main_module.active_ark_clients[job_id] = client
        with patch.object(main_module, "save_job"):
            result = main_module.cancel_job(job_id)["job"]
        self.assertTrue(event.is_set())
        client.cancel.assert_called_once_with()
        self.assertEqual(result["status"], "cancelling")

    def test_orphaned_cancelling_record_is_finalized(self) -> None:
        job_id = "job_cancel_orphan"
        main_module.jobs[job_id] = self._job(job_id, "cancelling")
        with patch.object(main_module, "save_job"):
            result = main_module.cancel_job(job_id)["job"]
        self.assertEqual(result["status"], "cancelled")

    def test_cancelled_brief_cannot_overwrite_terminal_state(self) -> None:
        job_id = "job_cancel_brief"
        event = main_module.threading.Event()
        event.set()
        main_module.jobs[job_id] = self._job(job_id, "briefing")
        main_module.cancel_events[job_id] = event
        with patch.object(main_module, "save_job"):
            main_module.run_brief_generation(job_id)
        self.assertEqual(main_module.jobs[job_id]["status"], "cancelled")
        self.assertNotEqual(main_module.jobs[job_id]["stage"], "brief_confirmation")
        self.assertNotIn(job_id, main_module.cancel_events)

    def test_cancelling_background_auto_composition_preserves_review_state(self) -> None:
        job_id = "job_cancel_auto"
        job = self._job(job_id, "awaiting_confirmation")
        job["eventGroups"] = [{"id": "event_1", "segments": []}]
        job["autoComposition"] = {"status": "queued", "phase": "vlm_render"}
        event = main_module.threading.Event()
        future: Future = Future()
        main_module.jobs[job_id] = job
        main_module.cancel_events[job_id] = event
        main_module.render_futures[job_id] = {future}
        with patch.object(main_module, "save_job"), patch.object(main_module, "schedule_cancel_finalization"):
            result = main_module.cancel_job(job_id)["job"]
            self.assertEqual(result["status"], "cancelling")
            main_module.finalize_operation_cancellation(job_id)
        self.assertTrue(event.is_set())
        self.assertTrue(future.cancelled())
        self.assertEqual(main_module.jobs[job_id]["status"], "awaiting_confirmation")
        self.assertEqual(main_module.jobs[job_id]["autoComposition"]["status"], "cancelled")
        self.assertEqual(len(main_module.jobs[job_id]["eventGroups"]), 1)


class ModelClientCancellationTests(unittest.TestCase):
    def test_cancelled_vision_request_does_not_retry(self) -> None:
        client = OpenAICompatibleVisionClient(
            api_key="secret", model="vision-model", base_url="https://vision.example/v1",
        )
        transport = MagicMock()
        context = MagicMock()
        context.__enter__.return_value = transport
        transport.post.side_effect = lambda *_args, **_kwargs: (
            client.cancel(), (_ for _ in ()).throw(httpx.ReadError("closed by cancellation"))
        )[1]
        with patch("app.ark_client.httpx.Client", return_value=context) as factory:
            with self.assertRaisesRegex(ArkRequestError, "已取消"):
                client.complete_json("analyze")
        self.assertEqual(factory.call_count, 1)
        transport.close.assert_called_once_with()


class AutomaticCompositionSafetyTests(unittest.TestCase):
    def tearDown(self) -> None:
        main_module.jobs.pop("job_auto_confirm_guard", None)
        main_module.active_automatic_compositions.discard("job_auto_confirm_guard")
        main_module.jobs.pop("job_review_draft", None)

    def test_manual_confirmation_is_blocked_while_auto_composition_runs(self) -> None:
        job_id = "job_auto_confirm_guard"
        main_module.jobs[job_id] = {
            "id": job_id, "status": "awaiting_confirmation",
            "autoComposition": {"status": "running", "phase": "vlm_render"},
            "eventGroups": [{"id": "event_1", "title": "事件", "segments": [{
                "id": "segment_1", "start": 0.0, "end": 2.0, "duration": 2.0,
            }]}],
            "recommendedGroupIds": ["event_1"],
        }
        with self.assertRaises(main_module.HTTPException) as raised:
            main_module.confirm_job_candidates(
                job_id, main_module.ConfirmCandidatesRequest(groupIds=["event_1"]),
            )
        self.assertEqual(raised.exception.status_code, 409)
        self.assertIn("后台自动成片仍在运行", raised.exception.detail)

    def test_best_failed_auto_version_is_retained_as_manual_review_draft(self) -> None:
        job_id = "job_review_draft"
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "draft.mp4"
            output.write_bytes(b"preview")
            version = {
                "id": "version_1", "number": 1, "previewOnly": True,
                "displayName": "完整事件版", "outputs": [{
                    "filename": output.name,
                    "sequenceValidation": {"passed": True, "issues": []},
                }],
            }
            main_module.jobs[job_id] = {
                "id": job_id, "status": "awaiting_confirmation",
                "outputDirectory": directory, "sourcePath": "source.mp4",
                "outputVersions": [version], "outputs": list(version["outputs"]),
                "currentOutputVersionId": "version_1", "autoComposition": {},
            }
            report = {
                "summary": "动作结尾不完整",
                "qualityGate": {
                    "passed": False, "score": 48.0,
                    "criticalCount": 0, "majorCount": 1,
                    "reasons": ["动作结尾不完整"], "issues": [],
                },
            }
            with patch.object(main_module, "save_job"):
                result = main_module._finalize_review_quality_gates(
                    job_id, [("version_1", report)],
                )
            retained = main_module.jobs[job_id]["outputVersions"][0]
            self.assertEqual(result["passed"], 0)
            self.assertEqual(result["manualReviewVersionId"], "version_1")
            self.assertTrue(retained["manualReviewRequired"])
            self.assertEqual(retained["reviewStatus"], "needs_user_review")
            self.assertTrue(output.is_file())
            self.assertEqual(main_module.jobs[job_id]["outputs"][0]["filename"], output.name)

    def test_failed_variant_remains_reviewable_when_another_variant_passes(self) -> None:
        job_id = "job_mixed_quality_versions"
        self.addCleanup(main_module.jobs.pop, job_id, None)
        with tempfile.TemporaryDirectory() as directory:
            passed_output = Path(directory) / "passed.mp4"
            review_output = Path(directory) / "review.mp4"
            passed_output.write_bytes(b"passed preview")
            review_output.write_bytes(b"review preview")
            versions = [{
                "id": "version_passed", "number": 1, "previewOnly": True,
                "displayName": "连贯版", "outputs": [{"filename": passed_output.name}],
            }, {
                "id": "version_review", "number": 2, "previewOnly": True,
                "displayName": "节奏版", "outputs": [{"filename": review_output.name}],
            }]
            main_module.jobs[job_id] = {
                "id": job_id, "status": "awaiting_confirmation",
                "outputDirectory": directory, "sourcePath": "source.mp4",
                "outputVersions": versions, "outputs": list(versions[0]["outputs"]),
                "currentOutputVersionId": "version_passed", "autoComposition": {},
            }
            reports = [("version_passed", {
                "summary": "结构完整",
                "qualityGate": {
                    "passed": True, "recommended": True, "score": 86.0,
                    "criticalCount": 0, "majorCount": 0, "reasons": [], "issues": [],
                },
            }), ("version_review", {
                "summary": "节奏仍需确认",
                "qualityGate": {
                    "passed": False, "recommended": False, "score": 68.0,
                    "criticalCount": 0, "majorCount": 1,
                    "reasons": ["节奏仍需确认"], "issues": [],
                },
            })]
            with patch.object(main_module, "save_job"):
                result = main_module._finalize_review_quality_gates(job_id, reports)
            retained = main_module.jobs[job_id]["outputVersions"]
            self.assertEqual(result["passed"], 1)
            self.assertEqual(result["reviewable"], 1)
            self.assertEqual(len(retained), 2)
            self.assertFalse(retained[0].get("manualReviewRequired", False))
            self.assertTrue(retained[1]["manualReviewRequired"])
            self.assertEqual(retained[1]["reviewStatus"], "needs_user_review")
            self.assertEqual(
                main_module.jobs[job_id]["autoComposition"]["manualReviewVersionIds"],
                ["version_review"],
            )
            self.assertTrue(passed_output.is_file())
            self.assertTrue(review_output.is_file())
            self.assertEqual(
                main_module.jobs[job_id]["outputs"][0]["filename"],
                passed_output.name,
            )


class EventGroupEditingTests(unittest.TestCase):
    def test_create_add_reorder_adjust_and_undo_event_segments(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            original_settings = main_module.settings
            original_store = main_module.job_store
            root = Path(directory)
            main_module.settings = replace(original_settings, data_root=root)
            main_module.settings.ensure_directories()
            main_module.job_store = JobStore(root / "jobs.sqlite3")
            job_id = "job_event_edit_test"
            job = {
                "id": job_id, "status": "awaiting_confirmation", "progress": 1,
                "stage": "awaiting_confirmation", "detail": "test", "filename": "test.mp4",
                "sourcePath": str(root / "source.mp4"), "workDirectory": str(root / "work" / job_id),
                "outputDirectory": str(root / "outputs" / job_id), "videoInfo": {"duration": 100},
                "eventGroups": [], "recommendedGroupIds": [], "messages": [], "request": {},
                "createdAt": "2026-01-01T00:00:00+00:00", "updatedAt": "2026-01-01T00:00:00+00:00",
            }
            main_module.jobs[job_id] = job
            try:
                created = main_module.create_event_group(
                    job_id, main_module.CreateEventGroupRequest(start=10, end=16, title="救援事件"),
                )
                group_id = created["groupId"]
                main_module.add_event_group_segment(
                    job_id, group_id, main_module.AddEventSegmentRequest(start=30, end=36, role="人物反应"),
                )
                group = main_module.jobs[job_id]["eventGroups"][0]
                first, second = [item["id"] for item in group["segments"]]
                main_module.reorder_event_group_segments(
                    job_id, group_id, main_module.ReorderEventSegmentsRequest(segmentIds=[second, first]),
                )
                self.assertEqual(
                    [item["id"] for item in main_module.jobs[job_id]["eventGroups"][0]["availableSegments"][:2]],
                    [second, first],
                )
                main_module.adjust_event_group_segment(
                    job_id, group_id, second, main_module.AdjustEventSegmentRequest(start=29, end=36),
                )
                self.assertEqual(main_module.jobs[job_id]["eventGroups"][0]["segments"][0]["start"], 29)
                main_module.undo_job_timeline(job_id)
                self.assertEqual(main_module.jobs[job_id]["eventGroups"][0]["segments"][0]["start"], 30)
                created_destination = main_module.create_event_group(
                    job_id, main_module.CreateEventGroupRequest(start=60, end=66, title="后续事件"),
                )
                destination_id = created_destination["groupId"]
                main_module.move_event_group_segment(
                    job_id, group_id, first,
                    main_module.MoveEventSegmentRequest(destinationGroupId=destination_id),
                )
                source_group = main_module.find_event_group(main_module.jobs[job_id], group_id)
                destination_group = main_module.find_event_group(main_module.jobs[job_id], destination_id)
                self.assertNotIn(first, [item["id"] for item in source_group["availableSegments"]])
                self.assertIn(first, [item["id"] for item in destination_group["availableSegments"]])
            finally:
                main_module.jobs.pop(job_id, None)
                main_module.settings = original_settings
                main_module.job_store = original_store


class ConversationalEditProposalTests(unittest.TestCase):
    def _job(self, job_id: str) -> dict:
        segment_1 = {
            "id": "shot_1", "start": 10.0, "end": 15.0, "duration": 5.0,
            "role": "开场", "score": 86, "essential": True,
        }
        segment_2 = {
            "id": "shot_2", "start": 20.0, "end": 26.0, "duration": 6.0,
            "role": "发展", "score": 82,
        }
        group = main_module.recalculate_event_group({
            "id": "event_1", "title": "原事件",
            "segments": [segment_1, segment_2],
            "availableSegments": [copy.deepcopy(segment_1), copy.deepcopy(segment_2)],
        })
        return {
            "id": job_id, "taskMode": "highlight", "status": "awaiting_confirmation",
            "stage": "review", "progress": 1.0, "detail": "等待确认", "filename": "test.mp4",
            "sourcePath": f"/tmp/{job_id}/source.mp4", "workDirectory": f"/tmp/{job_id}/work",
            "outputDirectory": f"/tmp/{job_id}/outputs",
            "videoInfo": {"duration": 60}, "eventGroups": [group],
            "recommendedGroupIds": ["event_1"], "confirmedSegmentIds": {"event_1": ["shot_1", "shot_2"]},
            "candidates": [], "recommendedIndices": [], "reviewExcludedCandidates": [],
            "contentSearch": {}, "messages": [], "request": {},
            "createdAt": "2026-01-01T00:00:00+00:00", "updatedAt": "2026-01-01T00:00:00+00:00",
        }

    def test_proposal_previews_then_applies_atomically_and_can_be_undone(self) -> None:
        job_id = "job_conversational_proposal"
        main_module.jobs[job_id] = self._job(job_id)
        decision = {
            "answer": "缩短开场并调整顺序。",
            "editProposal": {
                "title": "收紧开场",
                "summary": "把开场收紧一秒，再把发展镜头放到前面。",
                "operations": [
                    {"type": "adjust_range", "targetType": "segment", "groupId": "event_1", "segmentId": "shot_1", "start": 11, "end": 15},
                    {"type": "reorder_segments", "groupId": "event_1", "segmentIds": ["shot_2", "shot_1"]},
                ],
            },
        }
        try:
            with patch.object(main_module, "save_job"):
                response = main_module.create_edit_proposal(
                    job_id, "开场短一点，第二个镜头放前面", decision,
                    {"playheadSeconds": 12.0, "viewer": {"kind": "segment", "segmentId": "shot_1"}},
                )
                proposal = response["job"]["pendingEditProposal"]
                self.assertNotIn("_previewWorkspace", proposal)
                self.assertEqual(main_module.jobs[job_id]["eventGroups"][0]["segments"][0]["start"], 10.0)
                self.assertTrue(proposal["preview"]["ranges"])
                self.assertEqual(
                    [item["segmentId"] for item in proposal["preview"]["schedule"]],
                    ["shot_2", "shot_1"],
                )
                self.assertEqual(proposal["preview"]["schedule"][0]["outputStart"], 0.0)
                self.assertEqual(proposal["preview"]["totalOutputDuration"], 10.0)
                self.assertEqual(proposal["preview"]["durationBefore"], 11.0)
                self.assertEqual(proposal["preview"]["durationAfter"], 10.0)

                main_module.apply_edit_proposal(job_id, proposal["id"])
                group = main_module.jobs[job_id]["eventGroups"][0]
                self.assertEqual([item["id"] for item in group["segments"]], ["shot_2", "shot_1"])
                self.assertEqual(group["segments"][1]["start"], 11.0)
                self.assertEqual(main_module.jobs[job_id]["timelineUndo"][-1]["target"], "editorialWorkspace")

                main_module.undo_job_timeline(job_id)
                restored = main_module.jobs[job_id]["eventGroups"][0]
                self.assertEqual([item["id"] for item in restored["segments"]], ["shot_1", "shot_2"])
                self.assertEqual(restored["segments"][0]["start"], 10.0)
        finally:
            main_module.jobs.pop(job_id, None)

    def test_cancel_keeps_workspace_and_stale_proposal_cannot_overwrite_changes(self) -> None:
        job_id = "job_conversational_cancel"
        main_module.jobs[job_id] = self._job(job_id)
        decision = {
            "editProposal": {
                "title": "选择镜头", "summary": "只保留第一个镜头。",
                "operations": [{
                    "type": "select_event_segments", "groupIds": ["event_1"],
                    "segmentIds": {"event_1": ["shot_1"]},
                }],
            },
        }
        try:
            with patch.object(main_module, "save_job"):
                first = main_module.create_edit_proposal(job_id, "只留第一个", decision, None)
                main_module.cancel_edit_proposal(job_id, first["proposalId"])
                self.assertEqual(main_module.jobs[job_id]["confirmedSegmentIds"]["event_1"], ["shot_1", "shot_2"])

                second = main_module.create_edit_proposal(job_id, "只留第一个", decision, None)
                main_module.jobs[job_id]["confirmedSegmentIds"]["event_1"] = ["shot_2"]
                with self.assertRaises(main_module.HTTPException) as raised:
                    main_module.apply_edit_proposal(job_id, second["proposalId"])
                self.assertEqual(raised.exception.status_code, 409)
                self.assertEqual(main_module.jobs[job_id]["confirmedSegmentIds"]["event_1"], ["shot_2"])
        finally:
            main_module.jobs.pop(job_id, None)

    def test_compose_proposal_rejects_unknown_ids_before_persisting(self) -> None:
        job_id = "job_conversational_invalid_compose"
        main_module.jobs[job_id] = self._job(job_id)
        decision = {"editProposal": {
            "title": "立即生成", "summary": "生成不存在的事件。",
            "operations": [{
                "type": "compose", "groupIds": ["invented_event"],
                "outputMode": "single_reel", "orderMode": "selection",
            }],
        }}
        try:
            with patch.object(main_module, "save_job"), self.assertRaises(main_module.HTTPException) as raised:
                main_module.create_edit_proposal(job_id, "生成这个", decision, None)
            self.assertEqual(raised.exception.status_code, 400)
            self.assertNotIn("pendingEditProposal", main_module.jobs[job_id])
            self.assertEqual(main_module.jobs[job_id]["recommendedGroupIds"], ["event_1"])
        finally:
            main_module.jobs.pop(job_id, None)

    def test_content_proposal_builds_one_output_time_track_per_export(self) -> None:
        job_id = "job_content_proposal_schedule"
        job = self._job(job_id)
        job.update({
            "taskMode": "content_extract", "status": "awaiting_content_confirmation",
            "eventGroups": [], "recommendedGroupIds": [], "confirmedSegmentIds": {},
            "contentSearch": {
                "id": "search_1", "defaultSelectedIds": ["match_1", "match_2"],
                "candidates": [
                    {"id": "match_1", "title": "后出现", "start": 20, "end": 24},
                    {"id": "match_2", "title": "先出现", "start": 5, "end": 8},
                ],
            },
        })
        main_module.jobs[job_id] = job
        decision = {"editProposal": {
            "title": "分别导出", "summary": "每段单独输出。",
            "operations": [{
                "type": "compose", "matchIds": ["match_1", "match_2"],
                "outputMode": "separate_events", "orderMode": "selection",
            }],
        }}
        try:
            with patch.object(main_module, "save_job"):
                response = main_module.create_edit_proposal(job_id, "分别导出", decision, None)
            preview = response["job"]["pendingEditProposal"]["preview"]
            self.assertEqual(preview["outputMode"], "separate_events")
            self.assertEqual(len(preview["outputs"]), 2)
            self.assertEqual([item["duration"] for item in preview["outputs"]], [4.0, 3.0])
            self.assertTrue(all(item["schedule"][0]["outputStart"] == 0 for item in preview["outputs"]))
            self.assertEqual(preview["totalOutputDuration"], 7.0)
        finally:
            main_module.jobs.pop(job_id, None)

    def test_proposal_schedule_uses_speed_and_transition_overlap(self) -> None:
        job_id = "job_proposal_technique_schedule"
        main_module.jobs[job_id] = self._job(job_id)
        decision = {"editProposal": {
            "title": "加快发展镜头", "summary": "发展镜头加速并叠化进入。",
            "operations": [{
                "type": "set_technique", "groupId": "event_1", "segmentId": "shot_2",
                "playbackRate": 1.5, "transitionType": "dissolve",
            }],
        }}
        try:
            with patch.object(main_module, "save_job"):
                response = main_module.create_edit_proposal(job_id, "第二段加速并叠化", decision, None)
            preview = response["job"]["pendingEditProposal"]["preview"]
            second = preview["schedule"][1]
            self.assertEqual(second["playbackRate"], 1.5)
            self.assertEqual(second["transitionType"], "dissolve")
            self.assertEqual(second["transitionOverlap"], .35)
            self.assertEqual(preview["totalOutputDuration"], 8.65)
        finally:
            main_module.jobs.pop(job_id, None)


class KeptLibraryTests(unittest.TestCase):
    def test_kept_output_survives_job_deletion(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            original_settings = main_module.settings
            original_store = main_module.job_store
            root = Path(directory)
            main_module.settings = replace(original_settings, data_root=root)
            main_module.settings.ensure_directories()
            main_module.job_store = JobStore(root / "jobs.sqlite3")
            job_id = "job_kept_test"
            source = root / "uploads" / f"{job_id}.mp4"
            output_directory = root / "outputs" / job_id
            work_directory = root / "work" / job_id
            output_directory.mkdir(parents=True)
            work_directory.mkdir(parents=True)
            source.write_bytes(b"source")
            filename = "01-highlight.mp4"
            (output_directory / filename).write_bytes(b"retained-video")
            job = {
                "id": job_id, "status": "completed", "stage": "completed", "progress": 1,
                "detail": "done", "filename": "source.mp4", "sourcePath": str(source),
                "workDirectory": str(work_directory), "outputDirectory": str(output_directory),
                "outputs": [{"filename": filename, "title": "精彩成片", "duration": 12, "score": 91}],
                "messages": [], "request": {}, "createdAt": "2026-01-01T00:00:00+00:00",
                "updatedAt": "2026-01-01T00:00:00+00:00",
            }
            main_module.jobs[job_id] = job
            main_module.job_store.save(job)
            try:
                main_module.keep_job_output(job_id, filename, main_module.KeepOutputRequest(kept=True))
                kept_media, kept_metadata = main_module.kept_output_paths(job_id, filename)
                self.assertEqual(kept_media.read_bytes(), b"retained-video")
                self.assertTrue(kept_metadata.is_file())
                self.assertTrue(main_module.jobs[job_id]["outputs"][0]["kept"])
                main_module._perform_job_deletion(job_id, source="test")
                self.assertTrue(kept_media.is_file())
                records = main_module.list_kept_records()
                self.assertEqual(len(records), 1)
                self.assertEqual(records[0]["title"], "精彩成片")
                main_module.delete_kept_output(job_id, filename)
                self.assertFalse(kept_media.exists())
            finally:
                main_module.jobs.pop(job_id, None)
                main_module.settings = original_settings
                main_module.job_store = original_store

    def test_shared_derived_caches_are_removed_only_after_last_job(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            original_settings = main_module.settings
            root = Path(directory)
            main_module.settings = replace(original_settings, data_root=root)
            main_module.settings.ensure_directories()
            identity = "shared-source-hash"
            analysis_key = "shared-analysis-key"
            base = {
                "status": "completed", "stage": "completed", "taskMode": "content_extract",
                "sourceHash": identity, "analysisCacheKey": analysis_key,
                "request": {"analysisMode": "audiovisual", "searchScopeKind": "all"},
                "videoInfo": {"duration": 30}, "recognitionSchemaVersion": 4,
            }
            first = {**base, "id": "job_shared_cache_1"}
            second = {**base, "id": "job_shared_cache_2"}
            main_module.jobs[first["id"]] = first
            main_module.jobs[second["id"]] = second
            waveform = main_module.waveform_cache_path(identity)
            waveform.parent.mkdir(parents=True, exist_ok=True)
            waveform.write_text("{}", encoding="utf-8")
            analysis = main_module.analysis_cache_path(analysis_key)
            analysis.write_text("{}", encoding="utf-8")
            content_directory = main_module.content_index_directory(first)
            content_directory.mkdir(parents=True)
            (content_directory / "index.json").write_text("{}", encoding="utf-8")
            try:
                main_module.jobs.pop(first["id"])
                main_module.cleanup_unreferenced_media_cache(first)
                main_module.cleanup_unreferenced_analysis_cache(first)
                main_module.cleanup_unreferenced_content_index(first)
                self.assertTrue(waveform.is_file())
                self.assertTrue(analysis.is_file())
                self.assertTrue(content_directory.is_dir())

                main_module.jobs.pop(second["id"])
                main_module.cleanup_unreferenced_media_cache(second)
                main_module.cleanup_unreferenced_analysis_cache(second)
                main_module.cleanup_unreferenced_content_index(second)
                self.assertFalse(waveform.exists())
                self.assertFalse(analysis.exists())
                self.assertFalse(content_directory.exists())
            finally:
                main_module.jobs.pop(first["id"], None)
                main_module.jobs.pop(second["id"], None)
                main_module.settings = original_settings

    def test_persisted_previous_content_index_is_protected_from_orphan_cleanup(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            original_settings = main_module.settings
            root = Path(directory)
            main_module.settings = replace(original_settings, data_root=root)
            main_module.settings.ensure_directories()
            job = {
                "id": "job_previous_index", "taskMode": "content_extract",
                "sourceHash": "source-v2", "recognitionSchemaVersion": 4,
                "request": {"analysisMode": "audiovisual", "searchScopeKind": "all"},
                "videoInfo": {"duration": 30},
                "contentIndex": {"cacheKey": "persisted-old-key"},
                "contentSearch": {"indexCacheKey": "search-old-key"},
            }
            main_module.jobs[job["id"]] = job
            old_directory = root / "cache" / "content-index-persisted-old-key"
            search_directory = root / "cache" / "content-index-search-old-key"
            orphan_directory = root / "cache" / "content-index-no-reference"
            for path in (old_directory, search_directory, orphan_directory):
                path.mkdir(parents=True)
            try:
                main_module.cleanup_orphaned_media_cache()
                self.assertTrue(old_directory.is_dir())
                self.assertTrue(search_directory.is_dir())
                self.assertFalse(orphan_directory.exists())
            finally:
                main_module.jobs.pop(job["id"], None)
                main_module.settings = original_settings

    def test_finalize_one_off_keeps_formal_output_then_removes_workspace(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            original_settings = main_module.settings
            original_store = main_module.job_store
            root = Path(directory)
            main_module.settings = replace(original_settings, data_root=root)
            main_module.settings.ensure_directories()
            main_module.job_store = JobStore(root / "jobs.sqlite3")
            job_id = "job_one_off_test"
            source = root / "uploads" / f"{job_id}.mp4"
            work_directory = root / "work" / job_id
            output_directory = root / "outputs" / job_id
            work_directory.mkdir(parents=True)
            output_directory.mkdir(parents=True)
            source.write_bytes(b"source")
            filename = "final.mp4"
            (output_directory / filename).write_bytes(b"formal-video")
            job = {
                "id": job_id, "status": "completed", "stage": "completed", "storageMode": "one_off",
                "filename": "source.mp4", "sourcePath": str(source), "sourceHash": "one-off-source",
                "workDirectory": str(work_directory), "outputDirectory": str(output_directory),
                "outputs": [{"filename": filename, "title": "正式成片", "duration": 8, "score": 90}],
                "outputVersions": [], "messages": [], "request": {},
                "createdAt": "2026-01-01T00:00:00+00:00", "updatedAt": "2026-01-01T00:00:00+00:00",
            }
            main_module.jobs[job_id] = job
            main_module.job_store.save(job)
            try:
                with patch.object(main_module.render_task_store, "recoverable_job_ids", return_value=set()):
                    result = main_module.finalize_one_off_job(
                        job_id, main_module.FinalizeOneOffJobRequest(filenames=[filename]),
                    )
                self.assertTrue(result["deleted"])
                self.assertNotIn(job_id, main_module.jobs)
                self.assertFalse(source.exists())
                self.assertFalse(work_directory.exists())
                self.assertFalse(output_directory.exists())
                kept_media, kept_metadata = main_module.kept_output_paths(job_id, filename)
                self.assertEqual(kept_media.read_bytes(), b"formal-video")
                self.assertTrue(kept_metadata.is_file())
            finally:
                main_module.jobs.pop(job_id, None)
                main_module.settings = original_settings
                main_module.job_store = original_store

    def test_finalize_one_off_copy_failure_preserves_workspace(self) -> None:
        job_id = "job_one_off_copy_failure"
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "source.mp4"
            output_directory = root / "outputs"
            output_directory.mkdir()
            source.write_bytes(b"source")
            (output_directory / "final.mp4").write_bytes(b"video")
            job = {
                "id": job_id, "status": "completed", "stage": "completed", "storageMode": "one_off",
                "filename": "source.mp4", "sourcePath": str(source), "sourceHash": job_id,
                "workDirectory": str(root / "work"), "outputDirectory": str(output_directory),
                "outputs": [{"filename": "final.mp4", "title": "正式成片", "duration": 8}],
                "outputVersions": [], "messages": [], "request": {},
                "createdAt": "2026-01-01T00:00:00+00:00", "updatedAt": "2026-01-01T00:00:00+00:00",
            }
            main_module.jobs[job_id] = job
            try:
                with patch.object(main_module.render_task_store, "recoverable_job_ids", return_value=set()), patch.object(
                    main_module, "save_output_to_kept_library", side_effect=OSError("disk full"),
                ):
                    with self.assertRaisesRegex(main_module.HTTPException, "原任务尚未清理"):
                        main_module.finalize_one_off_job(
                            job_id, main_module.FinalizeOneOffJobRequest(filenames=["final.mp4"]),
                        )
                self.assertIn(job_id, main_module.jobs)
                self.assertTrue(source.is_file())
                self.assertTrue((output_directory / "final.mp4").is_file())
            finally:
                main_module.jobs.pop(job_id, None)

    def test_finalize_one_off_rejects_preview_only_output(self) -> None:
        job_id = "job_one_off_preview"
        job = {
            "id": job_id, "status": "completed", "stage": "completed", "storageMode": "one_off",
            "filename": "source.mp4", "sourcePath": "/tmp/missing-source.mp4", "sourceHash": job_id,
            "workDirectory": "/tmp/missing-work", "outputDirectory": "/tmp/missing-outputs",
            "outputs": [],
            "outputVersions": [{
                "id": "v001", "number": 1, "previewOnly": True, "outputs": [],
                "previewOutputs": [{"filename": "preview.mp4", "title": "审核样片", "previewOnly": True}],
            }],
            "messages": [], "request": {}, "createdAt": "2026-01-01T00:00:00+00:00",
            "updatedAt": "2026-01-01T00:00:00+00:00",
        }
        main_module.jobs[job_id] = job
        try:
            with patch.object(main_module.render_task_store, "recoverable_job_ids", return_value=set()):
                with self.assertRaises(main_module.HTTPException) as captured:
                    main_module.finalize_one_off_job(
                        job_id, main_module.FinalizeOneOffJobRequest(filenames=["preview.mp4"]),
                    )
            self.assertEqual(captured.exception.status_code, 409)
            self.assertIn("先导出高清成片", str(captured.exception.detail))
            self.assertIn(job_id, main_module.jobs)
        finally:
            main_module.jobs.pop(job_id, None)


class ReeditingTests(unittest.TestCase):
    def test_completed_job_can_reselect_candidates_without_model_analysis(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            original_settings = main_module.settings
            original_store = main_module.job_store
            root = Path(directory)
            main_module.settings = replace(original_settings, data_root=root)
            main_module.settings.ensure_directories()
            main_module.job_store = JobStore(root / "jobs.sqlite3")
            job_id = "job_reedit_test"
            group_id = "event_original"
            job = {
                "id": job_id, "status": "completed", "stage": "completed", "progress": 1,
                "detail": "done", "filename": "source.mp4", "sourcePath": str(root / "source.mp4"),
                "workDirectory": str(root / "work" / job_id), "outputDirectory": str(root / "outputs" / job_id),
                "videoInfo": {"duration": 100, "width": 1920, "height": 1080},
                "candidates": [
                    {"index": 0, "start": 10, "end": 16, "duration": 6, "score": 92, "title": "反应", "reason": "人物反应"},
                    {"index": 1, "start": 30, "end": 38, "duration": 8, "score": 95, "title": "高潮", "reason": "动作高潮"},
                ],
                "eventGroups": [{
                    "id": group_id, "title": "原章节", "summary": "原结果", "score": 92,
                    "segments": [{"id": "segment_old", "candidateIndex": 0, "start": 10, "end": 16, "duration": 6}],
                }],
                "recommendedGroupIds": [group_id], "confirmedGroupIds": [group_id],
                "outputs": [{"filename": "01-old.mp4", "title": "旧成片", "duration": 6}],
                "messages": [], "request": {}, "createdAt": "2026-01-01T00:00:00+00:00",
                "updatedAt": "2026-01-01T00:00:00+00:00",
            }
            Path(job["workDirectory"]).mkdir(parents=True)
            Path(job["outputDirectory"]).mkdir(parents=True)
            main_module.jobs[job_id] = job
            main_module.job_store.save(job)
            try:
                reopened = main_module.reopen_job_for_editing(job_id)["job"]
                self.assertEqual(reopened["status"], "awaiting_confirmation")
                self.assertTrue(reopened["reediting"])
                self.assertEqual(reopened["recommendedGroupIds"], [group_id])
                created = main_module.create_event_group_from_candidates(
                    job_id,
                    main_module.CreateEventFromCandidatesRequest(indices=[0, 1], title="重新组合"),
                )
                new_group_id = created["groupId"]
                new_group = next(group for group in created["job"]["eventGroups"] if group["id"] == new_group_id)
                self.assertEqual(len(new_group["segments"]), 2)
                self.assertEqual(created["job"]["recommendedGroupIds"], [new_group_id])
                restored = main_module.cancel_job_reediting(job_id)["job"]
                self.assertEqual(restored["status"], "completed")
                self.assertEqual(restored["outputs"][0]["filename"], "01-old.mp4")
            finally:
                main_module.jobs.pop(job_id, None)
                main_module.settings = original_settings
                main_module.job_store = original_store


class OutputVersionTests(unittest.TestCase):
    def _job(self, root: Path, job_id: str) -> dict:
        output_directory = root / "outputs" / job_id
        work_directory = root / "work" / job_id
        output_directory.mkdir(parents=True)
        work_directory.mkdir(parents=True)
        source = root / "uploads" / f"{job_id}.mp4"
        source.parent.mkdir(parents=True, exist_ok=True)
        source.write_bytes(b"source")
        old_filename = "01-旧成片.mp4"
        (output_directory / old_filename).write_bytes(b"old-version")
        return {
            "id": job_id, "status": "running", "stage": "rendering", "progress": .82,
            "detail": "rendering", "filename": "source.mp4", "sourcePath": str(source),
            "workDirectory": str(work_directory), "outputDirectory": str(output_directory),
            "outputs": [{"filename": old_filename, "title": "旧成片", "duration": 4, "score": 80}],
            "eventGroups": [{
                "id": "event_1", "title": "事件", "summary": "精彩事件", "score": 92,
                "segments": [{"id": "segment_1", "start": 2, "end": 7, "duration": 5}],
            }],
            "candidates": [], "messages": [], "request": {"theme": "人物反应"},
            "createdAt": "2026-01-01T00:00:00+00:00", "updatedAt": "2026-01-01T00:00:00+00:00",
        }

    def test_recomposition_appends_version_without_overwriting_old_media(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            original_settings, original_store = main_module.settings, main_module.job_store
            root = Path(directory)
            main_module.settings = replace(original_settings, data_root=root)
            main_module.settings.ensure_directories()
            main_module.job_store = JobStore(root / "jobs.sqlite3")
            job_id = "job_versions"
            job = self._job(root, job_id)
            main_module.jobs[job_id] = job
            main_module.cancel_events[job_id] = main_module.threading.Event()
            info = MagicMock(duration=20, width=1280, height=720, has_audio=True)

            progress_seen = []

            def fake_render(_source, output, **_kwargs):
                progress_seen.append(_kwargs.get("progress_callback"))
                if _kwargs.get("progress_callback"):
                    _kwargs["progress_callback"](.5)
                output.write_bytes(b"new-version")
                return 5.0

            try:
                with patch.object(main_module, "probe_video", return_value=info), \
                     patch.object(main_module, "render_composition", side_effect=fake_render), \
                     patch.object(main_module, "validate_rendered_clip", return_value=MagicMock(duration=5.0)), \
                     patch.object(main_module.output_preview_executor, "submit"):
                    main_module.run_confirmed_render(job_id, ["event_1"], "single_reel")
                current = main_module.jobs[job_id]
                self.assertEqual(current["status"], "completed")
                self.assertEqual(len(current["outputVersions"]), 2)
                self.assertEqual(current["currentOutputVersionId"], "v002")
                self.assertTrue(progress_seen)
                self.assertTrue(callable(progress_seen[0]))
                self.assertEqual((Path(current["outputDirectory"]) / "01-旧成片.mp4").read_bytes(), b"old-version")
                new_filename = current["outputs"][0]["filename"]
                self.assertTrue(new_filename.startswith("v002-"))
                self.assertEqual((Path(current["outputDirectory"]) / new_filename).read_bytes(), b"new-version")
            finally:
                main_module.cancel_events.pop(job_id, None)
                main_module.jobs.pop(job_id, None)
                main_module.settings, main_module.job_store = original_settings, original_store

    def test_content_extract_render_uses_content_copy_and_exposes_a_version(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            original_settings, original_store = main_module.settings, main_module.job_store
            root = Path(directory)
            main_module.settings = replace(original_settings, data_root=root)
            main_module.settings.ensure_directories()
            main_module.job_store = JobStore(root / "jobs.sqlite3")
            job_id = "job_content_version"
            job = self._job(root, job_id)
            job["taskMode"] = "content_extract"
            job["contentSearch"] = {"orderMode": "source"}
            job["eventGroups"][0]["segments"][0]["candidateId"] = "match_1"
            main_module.jobs[job_id] = job
            main_module.cancel_events[job_id] = main_module.threading.Event()
            info = MagicMock(duration=20, width=1280, height=720, has_audio=True)

            def fake_render(_source, output, **_kwargs):
                output.write_bytes(b"content-version")
                return 5.0

            try:
                with patch.object(main_module, "probe_video", return_value=info), \
                     patch.object(main_module, "render_composition", side_effect=fake_render), \
                     patch.object(main_module, "validate_rendered_clip", return_value=MagicMock(duration=5.0, width=1280, height=720, has_audio=True)), \
                     patch.object(main_module.output_preview_executor, "submit"):
                    main_module.run_confirmed_render(
                        job_id, ["event_1"], "single_reel", order_mode="source",
                        auto_meta={
                            "strategyKey": "content_extract", "displayName": "内容剪辑",
                            "sourceLabel": "找出绿衣哥说话的片段", "matchIds": ["match_1"],
                        },
                    )
                current = main_module.jobs[job_id]
                self.assertEqual(current["status"], "completed")
                self.assertEqual(current["detail"], "已将 1 个已确认内容片段合成为 1 条视频")
                self.assertEqual(current["outputs"][0]["reason"], "由用户审核确认的内容片段按指定顺序合成")
                self.assertIn("内容视频", current["outputs"][0]["filename"])
                self.assertNotIn("高光", current["outputs"][0]["filename"])
                self.assertEqual(current["outputVersions"][-1]["strategyKey"], "content_extract")
                result_text = next(
                    item["text"] for item in reversed(current["messages"])
                    if item.get("kind") == "result"
                )
                self.assertIn("按源视频时间顺序将 1 个已确认内容片段合成为 1 条视频", result_text)
                self.assertNotIn("高光", result_text)
            finally:
                main_module.cancel_events.pop(job_id, None)
                main_module.jobs.pop(job_id, None)
                main_module.settings, main_module.job_store = original_settings, original_store

    def test_requested_subtitles_are_blocked_without_confirmed_review(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            original_settings, original_store = main_module.settings, main_module.job_store
            root = Path(directory)
            main_module.settings = replace(original_settings, data_root=root)
            main_module.settings.ensure_directories()
            main_module.job_store = JobStore(root / "jobs.sqlite3")
            job_id = "job_subtitle_no_dialogue"
            job = self._job(root, job_id)
            job["speechAnalysis"] = {"segments": []}
            main_module.jobs[job_id] = job
            main_module.cancel_events[job_id] = main_module.threading.Event()
            info = MagicMock(duration=20, width=1280, height=720, has_audio=True)
            render_arguments = {}

            def fake_render(_source, output, **kwargs):
                render_arguments.update(kwargs)
                output.write_bytes(b"no-dialogue-version")
                return 5.0

            try:
                with patch.object(main_module, "probe_video", return_value=info), \
                     patch.object(main_module, "render_composition", side_effect=fake_render), \
                     patch.object(main_module, "validate_rendered_clip", return_value=MagicMock(duration=5.0, width=1280, height=720, has_audio=True)), \
                     patch.object(main_module.output_preview_executor, "submit"):
                    main_module.run_confirmed_render(
                        job_id, ["event_1"], "single_reel", subtitle_mode="burn",
                    )
                current = main_module.jobs[job_id]
                self.assertFalse(render_arguments)
                self.assertIn("必须完成字幕校对", current.get("error", ""))
                self.assertEqual(current["outputs"][0]["title"], "旧成片")
            finally:
                main_module.cancel_events.pop(job_id, None)
                main_module.jobs.pop(job_id, None)
                main_module.settings, main_module.job_store = original_settings, original_store

    def test_requested_subtitles_remain_enabled_for_overlapping_dialogue(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            original_settings, original_store = main_module.settings, main_module.job_store
            root = Path(directory)
            main_module.settings = replace(original_settings, data_root=root)
            main_module.settings.ensure_directories()
            main_module.job_store = JobStore(root / "jobs.sqlite3")
            job_id = "job_subtitle_with_dialogue"
            job = self._job(root, job_id)
            job["speechAnalysis"] = {"segments": [{"start": 3, "end": 4.5, "text": "这是一段有效对白。"}]}
            final_reel = build_final_reel(job["eventGroups"], order_mode="source")
            safe_selections, _ = main_module._semantic_safe_selections(
                job, [final_reel], order_mode="source", target_seconds=None, allow_fill=False,
            )
            draft_id = "sub_1234567890abcdef"
            save_draft(job["workDirectory"], {
                "id": draft_id, "jobId": job_id, "status": "confirmed", "revision": 2,
                "outputFingerprints": output_fingerprints([{"segments": safe_selections[0]["segments"]}]),
                "globalStyle": {"preset": "clean", "fontSizeRatio": .04, "horizontal": "center", "vertical": "bottom", "offsetXRatio": 0, "offsetYRatio": 0},
                "cueStyleOverrides": {},
                "cues": [{"id": "cue_1", "outputIndex": 0, "start": 1, "end": 2.5, "sourceStart": 3, "sourceEnd": 4.5, "text": "人工校正后的对白。", "originalText": "这是一段有效对白。", "suggestionStatus": "none"}],
            })
            main_module.jobs[job_id] = job
            main_module.cancel_events[job_id] = main_module.threading.Event()
            info = MagicMock(duration=20, width=1280, height=720, has_audio=True)
            render_arguments = {}

            def fake_render(_source, output, **kwargs):
                render_arguments.update(kwargs)
                output.write_bytes(b"dialogue-version")
                return 5.0

            try:
                with patch.object(main_module, "probe_video", return_value=info), \
                     patch.object(main_module, "render_composition", side_effect=fake_render), \
                     patch.object(main_module, "validate_rendered_clip", return_value=MagicMock(duration=5.0, width=1280, height=720, has_audio=True)), \
                     patch.object(main_module.output_preview_executor, "submit"):
                    main_module.run_confirmed_render(
                        job_id, ["event_1"], "single_reel", subtitle_mode="burn",
                        subtitle_draft_id=draft_id,
                    )
                current = main_module.jobs[job_id]
                self.assertEqual(current["outputs"][0]["subtitleMode"], "burn")
                self.assertEqual(current["outputVersions"][-1]["subtitleMode"], "burn")
                self.assertIsNotNone(render_arguments["subtitle_path"])
                self.assertEqual(len(render_arguments["subtitle_cues"]), 1)
                self.assertEqual(render_arguments["subtitle_cues"][0]["text"], "人工校正后的对白。")
            finally:
                main_module.cancel_events.pop(job_id, None)
                main_module.jobs.pop(job_id, None)
                main_module.settings, main_module.job_store = original_settings, original_store

    def test_finalizing_preview_keeps_sample_and_appends_master_version(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            original_settings, original_store = main_module.settings, main_module.job_store
            root = Path(directory)
            main_module.settings = replace(original_settings, data_root=root)
            main_module.settings.ensure_directories()
            main_module.job_store = JobStore(root / "jobs.sqlite3")
            job_id = "job_finalize_preview"
            job = self._job(root, job_id)
            output_directory = Path(job["outputDirectory"])
            sample_filename = "v001-01-情绪集中版.mp4"
            (output_directory / sample_filename).write_bytes(b"review-sample")
            segments = [{
                "id": "segment_1", "groupId": "event_1", "start": 2, "end": 7,
                "duration": 5, "role": "climax", "reason": "保留情绪高点",
            }]
            sample_output = {
                "filename": sample_filename, "title": "情绪集中版", "displayName": "情绪集中版",
                "duration": 5, "score": 91, "previewOnly": True, "segments": segments,
            }
            job.update({
                "outputs": [sample_output], "currentOutputVersionId": "v001",
                "outputVersions": [{
                    "id": "v001", "number": 1, "createdAt": "2026-01-01T00:00:00+00:00",
                    "previewOnly": True, "strategyKey": "emotion", "displayName": "情绪集中版",
                    "sourceLabel": "剪辑规划", "strategyDescription": "优先保留情绪高点",
                    "recommended": True, "outputs": [sample_output],
                }],
            })
            main_module.jobs[job_id] = job
            main_module.cancel_events[job_id] = main_module.threading.Event()
            info = MagicMock(duration=20, width=1280, height=720, has_audio=True)

            def fake_render(_source, output, **_kwargs):
                output.write_bytes(b"high-resolution-master")
                return 5.0

            try:
                with patch.object(main_module, "probe_video", return_value=info), \
                     patch.object(main_module, "render_composition", side_effect=fake_render), \
                     patch.object(main_module, "validate_rendered_clip", return_value=MagicMock(duration=5.0, width=1280, height=720, has_audio=True)), \
                     patch.object(main_module.output_preview_executor, "submit"):
                    main_module.run_confirmed_render(
                        job_id, [], "single_reel", planned_sequence=segments,
                        planned_title="情绪集中版", auto_meta={
                            "strategyKey": "emotion", "displayName": "情绪集中版",
                            "sourceLabel": "剪辑规划", "strategyDescription": "优先保留情绪高点",
                            "recommended": True,
                        }, finalize_source_version_id="v001",
                    )
                current = main_module.jobs[job_id]
                self.assertEqual(len(current["outputVersions"]), 2)
                sample, version = current["outputVersions"]
                self.assertEqual(sample["id"], "v001")
                self.assertTrue(sample["previewOnly"])
                self.assertEqual(version["id"], "v002")
                self.assertEqual(version["number"], 2)
                self.assertFalse(version["previewOnly"])
                self.assertTrue(version["masterReady"])
                self.assertEqual(version["sourceVersionId"], "v001")
                self.assertEqual(version["variantKind"], "formal_export")
                self.assertEqual(version["displayName"], "情绪集中版")
                self.assertTrue(version["recommended"])
                self.assertEqual(version["previewOutputs"][0]["filename"], sample_filename)
                self.assertEqual(current["currentOutputVersionId"], "v002")
                master_filename = version["outputs"][0]["filename"]
                self.assertTrue(master_filename.startswith("v002-master-"))
                self.assertEqual((output_directory / master_filename).read_bytes(), b"high-resolution-master")
                self.assertEqual((output_directory / sample_filename).read_bytes(), b"review-sample")
                sample_context = main_module.output_download_context(current, sample_filename)
                self.assertIsNotNone(sample_context)
                self.assertTrue(sample_context[0]["previewOnly"])
            finally:
                main_module.cancel_events.pop(job_id, None)
                main_module.jobs.pop(job_id, None)
                main_module.settings, main_module.job_store = original_settings, original_store

    def test_legacy_auto_versions_gain_batch_and_recovery_metadata(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            job = self._job(root, "job_legacy_batch")
            preview = Path(job["outputDirectory"]) / "legacy-preview.mp4"
            formal = Path(job["outputDirectory"]) / "manual-master.mp4"
            preview.write_bytes(b"preview")
            formal.write_bytes(b"master")
            job.update({
                "status": "awaiting_confirmation", "taskMode": "highlight",
                "autoComposition": {"status": "completed", "plannedVariantCount": 3},
                "outputVersions": [{
                    "id": "v001", "number": 1, "previewOnly": True,
                    "strategyKey": "vlm", "qualityStatus": "passed",
                    "outputs": [{"filename": preview.name, "previewOnly": True}],
                }, {
                    "id": "v002", "number": 2, "previewOnly": False,
                    "generationBatchId": "batch_formal_legacy", "variantKind": "formal_export",
                    "qualityStatus": "passed", "outputs": [{"filename": formal.name}],
                }],
                "outputs": [{"filename": preview.name, "previewOnly": True}],
                "currentOutputVersionId": "v001",
            })

            main_module.normalize_output_versions(job)
            batch = job["autoComposition"]["batches"][0]
            self.assertEqual(batch["generatedVariantCount"], 1)
            self.assertEqual(batch["missingVariantCount"], 2)
            self.assertNotIn("generationBatchId", job["outputVersions"][1])
            visible = main_module.public_job(job)
            self.assertTrue(visible["autoComposition"]["recovery"]["canRegenerateMissingVariants"])
            self.assertEqual(visible["autoComposition"]["recovery"]["missingVariantCount"], 2)

    def test_risky_preview_requires_explicit_export_acknowledgement(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            original_settings, original_store = main_module.settings, main_module.job_store
            root = Path(directory)
            main_module.settings = replace(original_settings, data_root=root)
            main_module.settings.ensure_directories()
            main_module.job_store = JobStore(root / "jobs.sqlite3")
            job_id = "job_risky_export"
            job = self._job(root, job_id)
            filename = "risky-preview.mp4"
            (Path(job["outputDirectory"]) / filename).write_bytes(b"preview")
            output = {"filename": filename, "previewOnly": True, "segments": [{"id": "s", "start": 1, "end": 5}]}
            job.update({
                "status": "awaiting_confirmation", "taskMode": "highlight",
                "outputs": [output], "currentOutputVersionId": "v001",
                "outputVersions": [{
                    "id": "v001", "number": 1, "previewOnly": True,
                    "qualityStatus": "needs_review", "manualReviewRequired": True,
                    "qualityGate": {"passed": False, "reasons": ["时长不足"]},
                    "outputs": [output],
                }],
            })
            main_module.jobs[job_id] = job
            try:
                with self.assertRaises(main_module.HTTPException) as captured:
                    main_module.finalize_preview_output_version(
                        job_id, "v001", main_module.FinalizeOutputVersionRequest(),
                    )
                self.assertEqual(captured.exception.status_code, 409)
                with patch.object(main_module, "submit_render_task") as submit:
                    main_module.finalize_preview_output_version(
                        job_id, "v001",
                        main_module.FinalizeOutputVersionRequest(acknowledgeQualityRisk=True),
                    )
                submit.assert_called_once()
            finally:
                main_module.cancel_events.pop(job_id, None)
                main_module.jobs.pop(job_id, None)
                main_module.settings, main_module.job_store = original_settings, original_store

    def test_batch_deletion_removes_only_preview_media(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            original_settings, original_store = main_module.settings, main_module.job_store
            root = Path(directory)
            main_module.settings = replace(original_settings, data_root=root)
            main_module.settings.ensure_directories()
            main_module.job_store = JobStore(root / "jobs.sqlite3")
            job_id = "job_delete_batch"
            job = self._job(root, job_id)
            output_directory = Path(job["outputDirectory"])
            preview_path = output_directory / "sample.mp4"
            master_path = output_directory / "master.mp4"
            preview_path.write_bytes(b"preview")
            master_path.write_bytes(b"master")
            job.update({
                "status": "completed", "taskMode": "highlight",
                "autoComposition": {"status": "completed", "currentBatchId": "batch_1", "batches": [{"id": "batch_1", "status": "completed", "targetVariantCount": 1}]},
                "outputVersions": [
                    {"id": "v001", "number": 1, "previewOnly": True, "generationBatchId": "batch_1", "variantKind": "independent", "outputs": [{"filename": preview_path.name}]},
                    {"id": "v002", "number": 2, "previewOnly": False, "generationBatchId": "batch_1", "variantKind": "formal_export", "sourceVersionId": "v001", "outputs": [{"filename": master_path.name}]},
                ],
                "currentOutputVersionId": "v002", "outputs": [{"filename": master_path.name}],
            })
            main_module.jobs[job_id] = job
            try:
                result = main_module.delete_auto_composition_batch(job_id, "batch_1")
                self.assertEqual(result["deletedVersionCount"], 1)
                self.assertFalse(preview_path.exists())
                self.assertTrue(master_path.exists())
                self.assertEqual([version["id"] for version in main_module.jobs[job_id]["outputVersions"]], ["v002"])
            finally:
                main_module.jobs.pop(job_id, None)
                main_module.settings, main_module.job_store = original_settings, original_store

    def test_regeneration_is_noop_when_complete_and_queues_only_missing_count(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            original_settings, original_store = main_module.settings, main_module.job_store
            root = Path(directory)
            main_module.settings = replace(original_settings, data_root=root)
            main_module.settings.ensure_directories()
            main_module.job_store = JobStore(root / "jobs.sqlite3")
            job_id = "job_regenerate_missing"
            job = self._job(root, job_id)
            preview_path = Path(job["outputDirectory"]) / "sample.mp4"
            preview_path.write_bytes(b"preview")
            output = {"filename": preview_path.name, "previewOnly": True, "segments": [{"id": "s", "start": 1, "end": 5}]}
            job.update({
                "status": "awaiting_confirmation", "taskMode": "highlight",
                "recommendedGroupIds": ["event_1"],
                "autoComposition": {"status": "completed", "plannedVariantCount": 3},
                "outputVersions": [{
                    "id": "v001", "number": 1, "previewOnly": True,
                    "strategyKey": "vlm", "qualityStatus": "passed", "outputs": [output],
                }],
                "currentOutputVersionId": "v001", "outputs": [output],
            })
            main_module.jobs[job_id] = job
            try:
                complete = main_module.regenerate_auto_composition(
                    job_id, main_module.RegenerateAutoCompositionRequest(targetVariantCount=1),
                )
                self.assertFalse(complete["queued"])
                with patch.object(main_module, "submit_render_task") as submit:
                    queued = main_module.regenerate_auto_composition(
                        job_id, main_module.RegenerateAutoCompositionRequest(targetVariantCount=3),
                    )
                self.assertTrue(queued["queued"])
                self.assertEqual(queued["missingVariantCount"], 2)
                submit.assert_called_once_with(
                    job_id, main_module.run_missing_auto_variants, queued["batchId"],
                )
                batch = next(item for item in main_module.jobs[job_id]["autoComposition"]["batches"] if item["id"] == queued["batchId"])
                self.assertEqual(batch["requestedAdditionalCount"], 2)
            finally:
                main_module.jobs.pop(job_id, None)
                main_module.settings, main_module.job_store = original_settings, original_store

    def test_failed_recomposition_preserves_previous_version(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            original_settings, original_store = main_module.settings, main_module.job_store
            root = Path(directory)
            main_module.settings = replace(original_settings, data_root=root)
            main_module.settings.ensure_directories()
            main_module.job_store = JobStore(root / "jobs.sqlite3")
            job_id = "job_version_failure"
            job = self._job(root, job_id)
            main_module.jobs[job_id] = job
            main_module.cancel_events[job_id] = main_module.threading.Event()
            info = MagicMock(duration=20, width=1280, height=720, has_audio=True)

            def fake_render(_source, output, **_kwargs):
                output.write_bytes(b"invalid-new-version")
                return 5.0

            try:
                with patch.object(main_module, "probe_video", return_value=info), \
                     patch.object(main_module, "render_composition", side_effect=fake_render), \
                     patch.object(main_module, "validate_rendered_clip", side_effect=RuntimeError("质检失败")):
                    main_module.run_confirmed_render(job_id, ["event_1"], "single_reel")
                current = main_module.jobs[job_id]
                self.assertEqual(current["status"], "completed")
                self.assertEqual(current["currentOutputVersionId"], "v001")
                self.assertEqual(len(current["outputVersions"]), 1)
                self.assertEqual((Path(current["outputDirectory"]) / "01-旧成片.mp4").read_bytes(), b"old-version")
                self.assertFalse(any(Path(current["outputDirectory"]).glob("v002-*.mp4")))
            finally:
                main_module.cancel_events.pop(job_id, None)
                main_module.jobs.pop(job_id, None)
                main_module.settings, main_module.job_store = original_settings, original_store

    def test_repeated_composition_reuses_existing_version(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            original_settings, original_store = main_module.settings, main_module.job_store
            root = Path(directory)
            main_module.settings = replace(original_settings, data_root=root)
            main_module.settings.ensure_directories()
            main_module.job_store = JobStore(root / "jobs.sqlite3")
            job_id = "job_versions_reuse"
            job = self._job(root, job_id)
            main_module.jobs[job_id] = job
            main_module.cancel_events[job_id] = main_module.threading.Event()
            info = MagicMock(duration=20, width=1280, height=720, has_audio=True)

            def fake_render(_source, output, **_kwargs):
                output.write_bytes(b"new-version")
                return 5.0

            try:
                with patch.object(main_module, "probe_video", return_value=info), \
                     patch.object(main_module, "render_composition", side_effect=fake_render), \
                     patch.object(main_module, "validate_rendered_clip", return_value=MagicMock(duration=5.0)), \
                     patch.object(main_module.output_preview_executor, "submit"):
                    main_module.run_confirmed_render(job_id, ["event_1"], "single_reel")
                main_module.jobs[job_id].update({"status": "running", "stage": "rendering", "progress": .82})
                main_module.cancel_events[job_id] = main_module.threading.Event()
                with patch.object(main_module, "probe_video", side_effect=AssertionError("重复选择不应再次探测媒体")), \
                     patch.object(main_module, "render_composition", side_effect=AssertionError("重复选择不应再次渲染")):
                    main_module.run_confirmed_render(job_id, ["event_1"], "single_reel")
                current = main_module.jobs[job_id]
                self.assertEqual(current["status"], "completed")
                self.assertEqual(current["currentOutputVersionId"], "v002")
                self.assertEqual(len(current["outputVersions"]), 2)
            finally:
                main_module.cancel_events.pop(job_id, None)
                main_module.jobs.pop(job_id, None)
                main_module.settings, main_module.job_store = original_settings, original_store


class AnalysisCachePolicyTests(unittest.TestCase):
    def test_new_analysis_can_explicitly_skip_or_reuse_cache(self) -> None:
        reusable = {"request": {"forceReanalyze": False}, "excludedRanges": []}
        forced = {"request": {"forceReanalyze": True}, "excludedRanges": []}
        self.assertTrue(analysis_cache_reuse_allowed(reusable))
        self.assertFalse(analysis_cache_reuse_allowed(forced))
        self.assertFalse(analysis_cache_reuse_allowed(reusable, "retry"))
        self.assertFalse(analysis_cache_reuse_allowed({**reusable, "excludedRanges": [{"start": 1, "end": 2}]}))

    def test_analysis_cache_rejects_legacy_output_manifest_shape(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            original_settings = main_module.settings
            main_module.settings = replace(original_settings, data_root=Path(directory))
            try:
                cache_path = main_module.analysis_cache_path("legacy")
                cache_path.parent.mkdir(parents=True, exist_ok=True)
                cache_path.write_text(json.dumps({
                    "cacheVersion": main_module.ANALYSIS_CACHE_VERSION,
                    "schemaVersion": 1,
                    "candidates": [{"id": "shot_1"}],
                    "outputs": [{"filename": "legacy.mp4"}],
                }), encoding="utf-8")
                self.assertIsNone(main_module.load_analysis_cache("legacy"))
            finally:
                main_module.settings = original_settings


class SourceProxySchedulingTests(unittest.TestCase):
    def test_on_demand_proxy_is_deduplicated(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            original_settings = main_module.settings
            root = Path(directory)
            main_module.settings = replace(original_settings, data_root=root)
            main_module.settings.ensure_directories()
            job_id = "job_proxy_schedule"
            identity = "same-source"
            source = root / "uploads" / "source.mp4"
            source.write_bytes(b"video")
            main_module.jobs[job_id] = {
                "id": job_id, "sourceHash": identity, "sourcePath": str(source),
                "outputs": [], "createdAt": "2026-01-01T00:00:00+00:00",
                "updatedAt": "2026-01-01T00:00:00+00:00",
            }
            try:
                isolated_scheduler = main_module.PreviewProxyScheduler(
                    executor=MagicMock(), prepare=main_module.prepare_preview_proxy,
                )
                with patch.object(main_module, "preview_proxy_scheduler", isolated_scheduler):
                    self.assertTrue(main_module.schedule_preview_proxy(job_id))
                    self.assertFalse(main_module.schedule_preview_proxy(job_id))
                    isolated_scheduler.executor.submit.assert_called_once()
            finally:
                main_module.jobs.pop(job_id, None)
                main_module.settings = original_settings

    def test_long_source_uses_lightweight_proxy_dimension(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            original_settings = main_module.settings
            root = Path(directory)
            main_module.settings = replace(original_settings, data_root=root)
            main_module.settings.ensure_directories()
            job_id = "job_long_proxy"
            source = root / "uploads" / "long.mp4"
            source.write_bytes(b"video")
            main_module.jobs[job_id] = {
                "id": job_id, "sourceHash": "long-source", "sourcePath": str(source),
                "outputs": [], "createdAt": "2026-01-01T00:00:00+00:00",
                "updatedAt": "2026-01-01T00:00:00+00:00",
            }
            info = MagicMock(duration=4542.7, has_audio=True)
            try:
                with patch("app.preview_assets.probe_video", return_value=info), patch("app.preview_assets.create_preview_proxy") as create:
                    main_module.prepare_preview_proxy(job_id)
                    self.assertEqual(create.call_args.kwargs["maximum_dimension"], 720)
            finally:
                main_module.jobs.pop(job_id, None)
                main_module.settings = original_settings


class CandidateSelectionTests(unittest.TestCase):
    def test_audio_and_dialogue_signals_create_candidates_for_visual_verification(self) -> None:
        candidates = speech_signal_candidates([
            {"start": 10, "end": 16, "text": "这是本次发布最重要的产品结论。", "emotion": "happy", "audioEvents": ["applause"]},
            {"start": 20, "end": 21, "text": "嗯", "emotion": "neutral", "audioEvents": []},
        ], video_duration=60)
        self.assertEqual(len(candidates), 1)
        self.assertEqual((candidates[0].start, candidates[0].end), (10.0, 16.0))
        self.assertEqual(candidates[0].audio_evidence["source"], "sensevoice")

    def test_visual_and_waveform_hotspots_expand_recall_pool(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            frames = []
            for index, value in enumerate((10, 12, 245, 240)):
                path = root / f"{index}.png"
                from PIL import Image
                Image.new("L", (32, 32), color=value).save(path)
                frames.append(SampledFrame(path, index * 5.0))
            visual = visual_change_candidates(frames, video_duration=20)
        audio = waveform_hotspot_candidates(
            {"rms": [.01, .012, .011, .2, .01, .18, .01]}, video_duration=20,
        )
        self.assertTrue(visual)
        self.assertTrue(audio)
        self.assertEqual(visual[0].candidate_origin, "visual_change")
        self.assertEqual(visual[0].semantic_status, "recall_only")
        self.assertEqual(audio[0].audio_evidence["source"], "waveform")
        self.assertEqual(audio[0].candidate_origin, "waveform")
        self.assertEqual(audio[0].semantic_status, "recall_only")

    def test_undo_snapshot_restores_candidate_collection(self) -> None:
        job = {"candidates": [{"index": 0, "title": "新标题"}], "recommendedIndices": [0]}
        edit = {
            "target": "candidates",
            "before": {"candidates": [{"index": 0, "title": "原标题"}], "recommendedIndices": []},
            "after": {"candidates": [{"index": 0, "title": "新标题"}], "recommendedIndices": [0]},
        }
        apply_timeline_history_state(job, edit, "before")
        self.assertEqual(job["candidates"][0]["title"], "原标题")
        self.assertEqual(job["recommendedIndices"], [])

    def test_model_time_must_be_supported_by_displayed_frame(self) -> None:
        self.assertEqual(validated_model_time(10.3, [8.0, 10.0, 12.0], tolerance=1.0), 10.0)
        self.assertIsNone(validated_model_time(30.0, [8.0, 10.0, 12.0], tolerance=1.0))

    def test_resolves_candidate_by_number_or_custom_name(self) -> None:
        candidates = [{"title": "调查开场"}, {"title": "药房证据"}]
        self.assertEqual(resolve_candidate_reference("第 2 条", candidates), 1)
        self.assertEqual(resolve_candidate_reference("药房证据", candidates), 1)

    def test_parses_candidate_duration_chat_adjustments(self) -> None:
        self.assertEqual(parse_candidate_adjustment("第三条增加10s"), {
            "index": 3, "kind": "relative", "direction": 1, "seconds": 10.0,
        })
        self.assertEqual(parse_candidate_adjustment("第 2 条结尾提前 3 秒"), {
            "index": 2, "kind": "boundary", "boundary": "end", "direction": -1, "seconds": 3.0,
        })
        self.assertEqual(parse_candidate_adjustment("第1条改成20秒"), {
            "index": 1, "kind": "duration", "seconds": 20.0,
        })

    def test_parses_manual_timeline_selection_adjustments(self) -> None:
        self.assertEqual(parse_manual_selection_adjustment("选中片段增加5秒"), {
            "kind": "relative", "direction": 1, "seconds": 5.0,
        })
        self.assertEqual(parse_manual_selection_adjustment("时间轴选区前后各扩展3秒"), {
            "kind": "both", "seconds": 3.0,
        })
        self.assertEqual(parse_manual_selection_adjustment("将选中的片段扩大10s"), {
            "kind": "expand_total", "seconds": 10.0,
        })

    def test_parses_custom_candidate_names(self) -> None:
        self.assertEqual(parse_requested_title("把选中片段加入候选，命名为药房证据"), "药房证据")
        self.assertEqual(parse_requested_title("将选区命名为“调查开场”并加入候选"), "调查开场")
        self.assertEqual(parse_requested_title("第 5 条改名为医院回扣调查"), "医院回扣调查")

    def test_adjusts_candidate_by_custom_name(self) -> None:
        candidates = [{"title": "药房证据"}, {"title": "调查开场"}]
        self.assertEqual(parse_named_candidate_adjustment("药房证据增加5秒", candidates), {
            "index": 1, "kind": "relative", "direction": 1, "seconds": 5.0,
        })

    def test_selects_highest_scoring_non_overlapping_ranges(self) -> None:
        candidates = [
            HighlightCandidate(0, 10, 80, "a", "", []),
            HighlightCandidate(2, 8, 95, "b", "", []),
            HighlightCandidate(12, 20, 70, "c", "", []),
        ]
        selected = select_non_overlapping(candidates, 2)
        self.assertEqual([item.title for item in selected], ["b", "c"])

    def test_detects_overlap_with_excluded_ranges(self) -> None:
        candidate = HighlightCandidate(10, 20, 80, "a", "", [])
        self.assertTrue(overlaps_ranges(candidate, [(18, 24)]))
        self.assertFalse(overlaps_ranges(candidate, [(20, 24)]))

    def test_automatic_moment_refinement_uses_thirty_second_cap(self) -> None:
        fallback = HighlightCandidate(0, 80, 80, "a", "", [])
        result = _refined_candidate(
            {"start_seconds": 0, "end_seconds": 80},
            fallback,
            duration=120,
            target_seconds=20,
            automatic_duration=True,
        )
        self.assertAlmostEqual(result.duration, 30, delta=0.01)
        self.assertGreaterEqual(result.peak_start, result.start)
        self.assertLessEqual(result.peak_end, result.end)
        self.assertGreater(result.minimum_keep_seconds, 0)

    def test_automatic_coarse_moment_is_capped_for_montage_editing(self) -> None:
        result = _candidate_from_coarse(
            {"center_seconds": 100, "suggested_duration": 55, "title": "完整事件"},
            duration=300,
            target_seconds=20,
            automatic_duration=True,
        )
        self.assertIsNotNone(result)
        self.assertAlmostEqual(result.duration, 30, delta=0.01)

    def test_groups_multiple_moments_into_one_event(self) -> None:
        candidates = [
            {"index": 0, "start": 10, "end": 18, "score": 90, "title": "列车受困", "reason": "环境"},
            {"index": 1, "start": 30, "end": 39, "score": 94, "title": "人员救援", "reason": "行动"},
            {"index": 2, "start": 50, "end": 56, "score": 88, "title": "乘客反应", "reason": "人物"},
        ]
        groups = build_event_groups(candidates, {"event_groups": [{
            "title": "暴雪列车救援", "score": 95, "summary": "同一救援事件",
            "moments": [
                {"candidate_index": 0, "role": "事件建立", "story_function": "建立", "leads_to_candidate_indices": [1], "essential": True, "transition_in": "cut"},
                {"candidate_index": 1, "role": "高潮", "story_function": "升级", "requires_candidate_indices": [0], "essential": True, "transition_in": "cut"},
                {"candidate_index": 2, "role": "人物反应", "essential": False, "transition_in": "dissolve"},
            ],
        }]})
        self.assertEqual(len(groups), 1)
        self.assertEqual(len(groups[0]["segments"]), 3)
        self.assertAlmostEqual(groups[0]["actualDuration"], 22.82, places=2)
        self.assertEqual(groups[0]["segments"][1]["requiresCandidateIndices"], [0])
        self.assertEqual(groups[0]["storyGraph"][0]["leadsTo"], [1])

    def test_raw_signal_omitted_by_director_does_not_become_fallback_event(self) -> None:
        candidates = [{
            "index": 0, "start": 10, "end": 18, "score": 91,
            "title": "画面变化热点", "reason": "变化强度高",
            "candidateOrigin": "visual_change", "semanticStatus": "recall_only",
        }]
        self.assertEqual(build_event_groups(candidates, {"event_groups": []}), [])

    def test_director_can_turn_raw_signal_into_concrete_event(self) -> None:
        candidates = [{
            "index": 0, "start": 10, "end": 18, "score": 91,
            "title": "声音能量热点", "reason": "音量峰值",
            "candidateOrigin": "waveform", "semanticStatus": "recall_only",
        }]
        groups = build_event_groups(candidates, {"event_groups": [{
            "title": "观众鼓掌庆祝", "summary": "掌声与现场反应形成事件落点",
            "moments": [{"candidate_index": 0, "role": "人物反应"}],
        }]})
        self.assertEqual(len(groups), 1)
        self.assertEqual(groups[0]["title"], "观众鼓掌庆祝")
        self.assertEqual(groups[0]["semanticStatus"], "verified")

    def test_reusable_anchor_does_not_create_second_selectable_event(self) -> None:
        candidates = [
            {"index": 0, "start": 0, "end": 12, "score": 92, "title": "打开冰箱取出食材"},
            {"index": 1, "start": 20, "end": 28, "score": 86, "title": "完成备菜"},
        ]
        groups = build_event_groups(candidates, {"event_groups": [{
            "title": "准备晚餐", "moments": [{"candidate_index": 0, "reusable_anchor": True}],
        }]})
        represented = [
            segment.get("candidateIndex")
            for group in groups for segment in group.get("availableSegments") or []
        ]
        self.assertEqual(represented.count(0), 1)
        self.assertEqual(represented.count(1), 1)

    def test_generic_director_group_for_raw_signal_is_rejected(self) -> None:
        candidates = [{
            "index": 0, "start": 10, "end": 18, "score": 91,
            "title": "画面变化热点", "reason": "变化强度高",
            "candidateOrigin": "visual_change", "semanticStatus": "recall_only",
        }]
        groups = build_event_groups(candidates, {"event_groups": [{
            "title": "视觉变化热点", "moments": [{"candidate_index": 0}],
        }]})
        self.assertEqual(groups, [])

    def test_output_hierarchy_recovers_semantic_events_and_quarantines_legacy_signals(self) -> None:
        groups = [{
            "id": "event_cooking", "title": "男子完成煎蛋",
            "segments": [{"id": "shot_1", "candidateId": "candidate_1", "start": 10, "end": 15}],
        }, {
            "id": "event_signal", "title": "画面变化热点",
            "segments": [{"id": "shot_2", "candidateId": "candidate_2", "start": 20, "end": 24}],
        }]
        output = normalize_output_event_hierarchy({
            "segments": [{
                "id": "rendered_1", "candidateId": "candidate_1", "start": 10, "end": 15,
                "role": "事件结果",
            }, {
                "id": "rendered_2", "candidateId": "candidate_2", "chapterId": "event_signal",
                "chapterTitle": "画面变化热点", "start": 20, "end": 24, "role": "核心镜头",
            }],
            "chapters": [{"id": "event_signal", "title": "画面变化热点"}],
        }, groups)
        self.assertEqual(output["timelineHierarchyVersion"], 1)
        self.assertEqual(output["segments"][0]["eventGroupId"], "event_cooking")
        self.assertEqual(output["segments"][0]["eventTitle"], "男子完成煎蛋")
        self.assertEqual(output["segments"][0]["shotTitle"], "事件结果")
        self.assertTrue(output["segments"][1]["eventGroupId"].startswith("legacy_unclassified_"))
        self.assertIn("待重新分析", output["segments"][1]["eventTitle"])
        self.assertNotIn("热点", output["segments"][1]["eventTitle"])
        self.assertEqual(len(output["timelineEvents"]), 2)

    def test_scene_cuts_expose_multiple_shots_inside_one_event(self) -> None:
        candidates = [{"index": 0, "start": 10, "end": 20, "score": 92, "title": "连续事件", "reason": ""}]
        groups = build_event_groups(candidates, {"event_groups": [{
            "title": "连续事件", "score": 92,
            "moments": [{"candidate_index": 0, "essential": True}],
        }]})
        split = split_event_groups_at_scene_cuts(groups, [13, 17])
        self.assertEqual(len(split[0]["segments"]), 3)
        self.assertEqual([(item["start"], item["end"]) for item in split[0]["segments"]], [(10.0, 13.0), (13.0, 17.0), (17.0, 20.0)])

    def test_scene_cuts_keep_spoken_semantic_unit_but_expose_visual_shots(self) -> None:
        candidates = [{
            "index": 0, "start": 10, "end": 20, "score": 92, "title": "完整对白", "reason": "",
            "hasSpeech": True, "minimumKeepSeconds": 10,
        }]
        groups = build_event_groups(candidates, {"event_groups": []})
        split = split_event_groups_at_scene_cuts(groups, [13, 17])
        segment = split[0]["segments"][0]
        self.assertEqual(len(split[0]["segments"]), 1)
        self.assertEqual(segment["physicalShotCount"], 3)
        self.assertEqual(len(segment["visualShots"]), 3)

    def test_allocates_one_total_budget_across_event_groups(self) -> None:
        candidates = [
            {"index": index, "start": index * 20, "end": index * 20 + 10, "score": 95 - index, "title": f"镜头{index}", "reason": ""}
            for index in range(4)
        ]
        groups = build_event_groups(candidates, {"event_groups": [
            {"title": "事件一", "score": 95, "moments": [{"candidate_index": 0, "essential": True}, {"candidate_index": 1}]},
            {"title": "事件二", "score": 90, "moments": [{"candidate_index": 2, "essential": True}, {"candidate_index": 3}]},
        ]})
        allocated, ids = allocate_event_group_budget(groups, total_target_seconds=30, requested_count=2)
        self.assertEqual(len(ids), 2)
        self.assertLessEqual(sum(group["actualDuration"] for group in allocated if group["id"] in ids), 33.01)

    def test_default_recommendation_removes_refined_overlap_before_review(self) -> None:
        candidates = [
            {"index": 0, "start": 0, "end": 8, "score": 96, "title": "动作开始", "reason": ""},
            {"index": 1, "start": 7, "end": 12, "score": 94, "title": "动作结果", "reason": ""},
            {"index": 2, "start": 7.5, "end": 14, "score": 92, "title": "重复结果", "reason": ""},
            {"index": 3, "start": 20, "end": 24, "score": 91, "title": "另一事件", "reason": ""},
        ]
        groups = build_event_groups(candidates, {"event_groups": [
            {"title": "事件一", "score": 96, "moments": [
                {"candidate_index": 0, "essential": True},
                {"candidate_index": 1},
            ]},
            {"title": "事件二", "score": 92, "moments": [
                {"candidate_index": 2, "essential": True},
                {"candidate_index": 3},
            ]},
        ]})

        allocated, ids = allocate_event_group_budget(
            groups, total_target_seconds=None, requested_count=2,
        )

        selected = [group for group in allocated if group["id"] in ids]
        ranges = [
            (segment["start"], segment["end"])
            for group in selected for segment in group["segments"]
            if not segment.get("reusableAnchor")
        ]
        self.assertTrue(all(
            max(left[0], right[0]) >= min(left[1], right[1])
            for index, left in enumerate(ranges)
            for right in ranges[index + 1:]
        ))
        self.assertTrue(any(group.get("selectionOverlapResolutions") for group in selected))

    def test_default_recommendation_trims_tiny_boundary_overlap(self) -> None:
        candidates = [
            {"index": 0, "start": 43.746, "end": 51.746, "score": 96, "title": "动作", "reason": ""},
            {"index": 1, "start": 51.715, "end": 55.715, "score": 94, "title": "结果", "reason": ""},
        ]
        groups = build_event_groups(candidates, {"event_groups": [{
            "title": "连续事件", "score": 96, "moments": [
                {"candidate_index": 0, "essential": True},
                {"candidate_index": 1},
            ],
        }]})

        allocated, ids = allocate_event_group_budget(
            groups, total_target_seconds=None, requested_count=1,
        )

        selected = next(group for group in allocated if group["id"] in ids)
        self.assertEqual(len(selected["segments"]), 2)
        self.assertEqual(selected["segments"][1]["start"], 51.746)
        self.assertTrue(any(
            item.get("action") == "trimmed_subframe_overlap"
            for item in selected.get("selectionOverlapResolutions") or []
        ))

    def test_prefers_three_complete_events_when_they_fit_dynamic_limit(self) -> None:
        candidates = [
            {"index": index, "start": index * 20, "end": index * 20 + 10, "score": 95 - index,
             "title": f"事件{index}", "reason": "", "hasSpeech": True, "minimumKeepSeconds": 10}
            for index in range(4)
        ]
        groups = build_event_groups(candidates, {"event_groups": []})
        allocated, ids = allocate_event_group_budget(groups, total_target_seconds=30, requested_count=None)
        self.assertEqual(len(ids), 3)
        self.assertAlmostEqual(event_groups_total(allocated, ids), 30.0)

    def test_allocator_ignores_legacy_hotspots_and_hits_target_with_semantic_events(self) -> None:
        candidates = [
            {"index": 0, "start": 0, "end": 24, "score": 90, "title": "回家后整理厨房"},
            {"index": 1, "start": 30, "end": 36, "score": 86, "title": "清洗餐具"},
            {"index": 2, "start": 40, "end": 44, "score": 82, "title": "坐下休息"},
        ]
        groups = build_event_groups(candidates, {"event_groups": []})
        groups.insert(0, {
            "id": "raw_signal", "index": 0, "title": "声音能量热点", "score": 99,
            "preferredDuration": 8, "actualDuration": 8,
            "segments": [{"id": "raw", "start": 50, "end": 58, "duration": 8}],
            "availableSegments": [{"id": "raw", "start": 50, "end": 58, "duration": 8}],
        })
        allocated, ids = allocate_event_group_budget(
            groups, total_target_seconds=30, requested_count=None,
        )
        self.assertNotIn("raw_signal", ids)
        self.assertGreaterEqual(event_groups_total(allocated, ids), 27.0)
        self.assertLessEqual(event_groups_total(allocated, ids), 33.0)

    def test_reduces_event_count_instead_of_cutting_dialogue(self) -> None:
        candidates = [
            {"index": index, "start": index * 30, "end": index * 30 + 15, "score": 95 - index,
             "title": f"对白事件{index}", "reason": "", "hasSpeech": True, "minimumKeepSeconds": 15}
            for index in range(3)
        ]
        groups = build_event_groups(candidates, {"event_groups": []})
        allocated, ids = allocate_event_group_budget(groups, total_target_seconds=30, requested_count=None)
        self.assertEqual(len(ids), 2)
        self.assertAlmostEqual(event_groups_total(allocated, ids), 30.0)
        selected = [group for group in allocated if group["id"] in ids]
        self.assertTrue(all(group["segments"][0]["duration"] == 15 for group in selected))
        self.assertTrue(selected[0]["eventReductionReason"])

    def test_rechecks_actual_fitted_duration_when_complete_speech_units_expand_budget(self) -> None:
        durations = [31.99, 16.07, 12.70, 11.69, 10.17]
        groups = []
        cursor = 0.0
        for index, duration in enumerate(durations):
            segment = {
                "id": f"segment_{index}", "candidateId": f"candidate_{index}",
                "semanticUnitId": f"semantic_{index}", "start": cursor,
                "end": cursor + duration, "duration": duration,
                "score": 96 - index, "essential": True, "hasSpeech": True,
                "minimumKeepSeconds": 3.0,
                # The theoretical minimum is short, but the sentence containing
                # the peak is indivisible and therefore expands during fitting.
                "speechUnits": [{
                    "id": f"speech_{index}", "start": cursor,
                    "end": cursor + duration,
                }],
                "peakStart": cursor + duration / 2 - .1,
                "peakEnd": cursor + duration / 2 + .1,
            }
            groups.append({
                "id": f"event_{index}", "index": index,
                "title": f"产品发布事件 {index + 1}", "summary": "完整发布对白",
                "score": 96 - index, "segments": [copy.deepcopy(segment)],
                "availableSegments": [copy.deepcopy(segment)],
                "preferredDuration": duration, "actualDuration": duration,
            })
            cursor += duration + 5

        allocated, ids = allocate_event_group_budget(
            groups, total_target_seconds=60, requested_count=None,
        )

        selected_duration = event_groups_total(allocated, ids)
        self.assertLess(len(ids), len(groups))
        self.assertLessEqual(selected_duration, 66.001)
        self.assertGreaterEqual(selected_duration, 54.0)
        self.assertTrue(all(
            "按完整语音和动作边界复核后" in str(group.get("eventReductionReason") or "")
            for group in allocated if group["id"] in ids
        ))

    def test_semantic_boundary_uses_silence_inside_long_speech_segment(self) -> None:
        safe = semantic_safe_range(
            10, 20,
            speech_segments=[{"start": 5, "end": 25, "text": "较长的一段对白"}],
            silences=[{"start": 8.5, "end": 9.0}, {"start": 21.5, "end": 22.0}],
        )
        self.assertEqual((safe["start"], safe["end"]), (9.0, 21.5))
        self.assertEqual(safe["speechBoundaryStatus"], "adjusted")

    def test_semantic_boundary_reports_candidate_window_that_cannot_hold_full_speech(self) -> None:
        safe = semantic_safe_range(
            10, 20,
            speech_segments=[{"start": 5, "end": 25, "text": "候选框外仍在说话"}],
            lower_bound=10, upper_bound=20,
        )
        self.assertEqual((safe["start"], safe["end"]), (10.0, 20.0))
        self.assertEqual(safe["speechBoundaryStatus"], "unsafe")
        self.assertTrue(safe["unresolvedSpeechBoundary"])

    def test_broad_spoken_candidate_uses_sentence_level_minimum_keep(self) -> None:
        annotated = annotate_candidate_boundaries(
            [{
                "id": "candidate_1", "start": 0, "end": 30,
                "title": "受访者完整说明核心观点",
                "peakStart": 11, "peakEnd": 13, "minimumKeepSeconds": 5,
            }],
            speech_segments=[
                {"id": "s1", "start": 1, "end": 8, "text": "第一句完整表达。"},
                {"id": "s2", "start": 10, "end": 16, "text": "第二句是核心表达。"},
                {"id": "s3", "start": 20, "end": 28, "text": "第三句完整表达。"},
            ],
            duration=40,
        )[0]
        self.assertTrue(annotated["hasSpeech"])
        self.assertEqual(annotated["speechUnitCount"], 3)
        self.assertEqual(annotated["minimumKeepSeconds"], 6.0)

        groups = build_event_groups([annotated], {"event_groups": []})
        allocated, ids = allocate_event_group_budget(
            groups, total_target_seconds=10, requested_count=1,
        )
        selected = next(group for group in allocated if group["id"] in ids)
        segment = selected["segments"][0]
        self.assertTrue(segment["trimmedToCompleteSpeechUnits"])
        self.assertEqual((segment["start"], segment["end"]), (10.0, 16.0))

    def test_long_essential_segment_is_trimmed_around_peak_to_total_budget(self) -> None:
        candidates = [{
            "index": 0, "start": 0, "end": 110, "score": 97, "title": "完整采访",
            "reason": "核心表达", "peakStart": 45, "peakEnd": 55,
            "minimumKeepSeconds": 10, "boundaryConfidence": .9,
        }]
        groups = build_event_groups(candidates, {"event_groups": [{
            "title": "采访高光", "score": 97,
            "moments": [{"candidate_index": 0, "essential": True}],
        }]})
        allocated, ids = allocate_event_group_budget(groups, total_target_seconds=30, requested_count=1)
        selected = next(group for group in allocated if group["id"] in ids)
        self.assertLessEqual(selected["actualDuration"], 33.0)
        self.assertGreaterEqual(selected["actualDuration"], 27.0)
        segment = selected["segments"][0]
        self.assertLessEqual(segment["start"], 45)
        self.assertGreaterEqual(segment["end"], 55)
        self.assertTrue(segment["trimmedForBudget"])

    def test_combines_event_chapters_into_one_non_repeating_final_reel(self) -> None:
        groups = [
            {
                "id": "late", "title": "救援结果", "score": 88,
                "segments": [
                    {"id": "late_b", "start": 45, "end": 50, "editOrder": 1},
                    {"id": "late_a", "start": 40, "end": 45, "editOrder": 0},
                ],
            },
            {
                "id": "early", "title": "事件爆发", "score": 96,
                "segments": [
                    {"id": "early_a", "start": 10, "end": 16, "editOrder": 0},
                    {"id": "duplicate", "start": 40, "end": 45, "editOrder": 1},
                ],
            },
        ]
        reel = build_final_reel(groups)
        self.assertEqual(reel["id"], "final_reel")
        self.assertEqual([chapter["id"] for chapter in reel["chapters"]], ["early", "late"])
        self.assertEqual([segment["id"] for segment in reel["segments"]], ["early_a", "duplicate", "late_b"])
        self.assertEqual(reel["chapters"][0]["segmentCount"], 2)
        self.assertEqual(reel["chapters"][1]["segmentCount"], 1)
        self.assertAlmostEqual(reel["actualDuration"], 16.0)
        self.assertTrue(all(segment["transitionIn"]["type"] == "cut" for segment in reel["segments"]))

    def test_final_reel_records_all_matches_when_confirmed_ranges_overlap(self) -> None:
        groups = [
            {"id": "one", "title": "片段一", "segments": [
                {"id": "a", "candidateId": "m1", "start": 10, "end": 15},
            ]},
            {"id": "two", "title": "片段二", "segments": [
                {"id": "b", "candidateId": "m2", "start": 14, "end": 20},
            ]},
        ]
        reel = build_final_reel(groups)
        self.assertEqual(len(reel["segments"]), 1)
        self.assertEqual(reel["segments"][0]["contributingMatchIds"], ["m1", "m2"])
        self.assertEqual((reel["segments"][0]["start"], reel["segments"][0]["end"]), (10.0, 20.0))

    def test_exact_two_tenths_source_range_is_renderable_despite_float_precision(self) -> None:
        self.assertTrue(source_duration_meets_minimum(49.52, 49.72))
        reel = build_final_reel([{
            "id": "boundary",
            "title": "边界片段",
            "segments": [{
                "id": "boundary_segment", "candidateId": "boundary_match",
                "start": 49.52, "end": 49.72,
            }],
        }])
        self.assertEqual(len(reel["segments"]), 1)
        self.assertEqual(reel["segments"][0]["contributingMatchIds"], ["boundary_match"])

    def test_automatic_refinement_window_uses_candidate_duration(self) -> None:
        candidate = HighlightCandidate(70, 125, 90, "事件", "", [])
        window = refinement_window_seconds(
            candidate,
            video_duration=300,
            target_seconds=20,
            automatic_duration=True,
        )
        self.assertEqual(window, 90)

    def test_detects_candidate_touching_refinement_edge(self) -> None:
        candidate = HighlightCandidate(20.5, 47, 90, "事件", "", [])
        self.assertTrue(touches_refinement_boundary(
            candidate,
            window_start=20,
            window_end=50,
            sample_step=2.5,
            video_duration=300,
        ))

    def test_semantically_similar_titles_are_not_both_selected(self) -> None:
        left = HighlightCandidate(0, 10, 95, "铁路积雪抢险现场", "", [])
        right = HighlightCandidate(100, 110, 90, "铁路积雪抢险救援现场", "", [])
        self.assertGreater(candidate_text_similarity(left, right), 0.58)
        self.assertEqual(len(select_non_overlapping([left, right], 2)), 1)

    def test_recommendations_are_relative_to_best_candidate(self) -> None:
        candidates = [
            {"index": 0, "score": 82},
            {"index": 1, "score": 76},
            {"index": 2, "score": 60},
        ]
        self.assertEqual(recommended_candidate_indices(candidates), [0])


class MediaIntegrationTests(unittest.TestCase):
    def test_content_render_uses_right_open_end_boundary(self) -> None:
        import subprocess
        from PIL import Image

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "boundary-source.mp4"
            output = root / "boundary-output.mp4"
            subprocess.run([
                "/usr/bin/ffmpeg", "-hide_banner", "-loglevel", "error",
                "-f", "lavfi", "-i", "color=c=red:size=160x90:rate=30:duration=1",
                "-f", "lavfi", "-i", "color=c=blue:size=160x90:rate=30:duration=1",
                "-filter_complex", "[0:v][1:v]concat=n=2:v=1:a=0[v]", "-map", "[v]",
                "-c:v", "libx264", "-pix_fmt", "yuv420p", "-y", str(source),
            ], check=True)
            expected = render_composition(
                source, output,
                segments=[{"start": 0.0, "end": 1.0, "transitionIn": {"type": "cut"}}],
                has_audio=False, ffmpeg="/usr/bin/ffmpeg", strict_source_boundaries=True,
            )
            self.assertLess(exclusive_render_duration(1.0, strict=True), 1.0)
            self.assertEqual(exclusive_render_duration(1.0, strict=False), 1.0)
            last_frame = root / "last-frame.jpg"
            subprocess.run([
                "/usr/bin/ffmpeg", "-hide_banner", "-loglevel", "error", "-i", str(output),
                "-vf", r"select=eq(n\,29)", "-frames:v", "1", "-y", str(last_frame),
            ], check=True)
            with Image.open(last_frame) as image:
                red, _, blue = image.convert("RGB").getpixel((80, 45))
            self.assertGreater(red, blue, "内容片段末帧不应落入结束边界之后的蓝色画面")

    def test_analysis_frame_snapshot_survives_source_cache_refresh(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            cached = root / "coarse-frames" / "frame-00001.jpg"
            cached.parent.mkdir()
            cached.write_bytes(b"jpeg-data")
            frozen = snapshot_sampled_frames(
                [SampledFrame(cached, 1.5)], root / "analysis-frames",
            )
            cached.unlink()
            self.assertTrue(frozen[0].path.is_file())
            self.assertEqual(frozen[0].path.read_bytes(), b"jpeg-data")

    def test_uniform_sampling_rejects_partial_timeline_coverage(self) -> None:
        frames = [
            SampledFrame(Path(f"frame-{index}.jpg"), index * 125.028)
            for index in range(3)
        ]
        with self.assertRaisesRegex(MediaError, "实际仅获得 3 帧"):
            validate_uniform_frame_coverage(
                frames, duration=9002.015, maximum_frames=72,
            )

    def test_tail_validation_requires_a_decoded_frame(self) -> None:
        completed = __import__("subprocess").CompletedProcess(
            args=[], returncode=0,
            stdout="#stream#, dts, pts, duration, size, hash\n",
            stderr="",
        )
        with patch("app.media.subprocess.run", return_value=completed):
            with self.assertRaisesRegex(MediaError, "源视频没有可解码画面"):
                validate_video_decodable_coverage(
                    Path("partial.mp4"), duration=9002.015, ffmpeg="ffmpeg",
                )

    def test_tail_validation_falls_back_across_long_gop_without_rejecting(self) -> None:
        import subprocess
        empty = subprocess.CompletedProcess(args=[], returncode=0, stdout="# framehash\n", stderr="")
        decoded = subprocess.CompletedProcess(args=[], returncode=0, stdout="# framehash\n0, 0, 0, 1, 1, hash\n", stderr="")
        with patch("app.media.subprocess.run", side_effect=[empty, empty, decoded]) as run:
            report = validate_video_decodable_coverage(
                Path("long-gop.mp4"), duration=9002.015, container_duration=9018.0, ffmpeg="ffmpeg",
            )
        self.assertEqual(report["status"], "warning")
        self.assertEqual(len(run.call_args_list), 3)
        self.assertTrue(any("长 GOP" in warning for warning in report["warnings"]))
        self.assertTrue(any("尾部可能只有声音" in warning for warning in report["warnings"]))

    def test_truncated_tail_is_rejected_instead_of_shortening_timeline(self) -> None:
        import subprocess
        def fake_run(command, **_kwargs):
            second = float(command[command.index("-ss") + 1])
            body = "# framehash\n0, 0, 0, 1, 1, hash\n" if second <= 300 else "# framehash\n"
            return subprocess.CompletedProcess(args=command, returncode=0, stdout=body, stderr="")
        with patch("app.media.subprocess.run", side_effect=fake_run):
            with self.assertRaisesRegex(MediaError, "内容不完整.*2:30:02.*05:00"):
                validate_video_decodable_coverage(
                    Path("metadata-too-long.mp4"), duration=9002.015, ffmpeg="ffmpeg",
                )

    def test_probe_uses_video_stream_duration_instead_of_longer_audio_container(self) -> None:
        import subprocess
        payload = {
            "streams": [
                {"codec_type": "video", "duration": "120.0", "width": 1280, "height": 720, "avg_frame_rate": "25/1"},
                {"codec_type": "audio", "duration": "132.5"},
            ],
            "format": {"duration": "132.5"},
        }
        completed = subprocess.CompletedProcess(args=[], returncode=0, stdout=json.dumps(payload), stderr="")
        with patch("app.media._run", return_value=completed):
            info = probe_video(Path("audio-tail.mp4"), "ffprobe")
        self.assertEqual(info.duration, 120.0)
        self.assertEqual(info.video_duration, 120.0)
        self.assertEqual(info.audio_duration, 132.5)
        self.assertEqual(info.container_duration, 132.5)
        self.assertEqual(info.frame_rate, 25.0)

    def test_sensevoice_failure_pauses_with_audio_checkpoint(self) -> None:
        import subprocess

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "source.mp4"
            subprocess.run([
                "/usr/bin/ffmpeg", "-hide_banner", "-loglevel", "error",
                "-f", "lavfi", "-i", "testsrc2=size=160x90:rate=8",
                "-f", "lavfi", "-i", "sine=frequency=440:sample_rate=16000",
                "-t", "3", "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac", "-y", str(source),
            ], check=True)
            pipeline = HighlightPipeline(client=MagicMock(), ffmpeg="/usr/bin/ffmpeg", ffprobe="/usr/bin/ffprobe")
            with patch("app.pipeline.analyze_speech", side_effect=RuntimeError("sensevoice unavailable")):
                with self.assertRaises(ModelDecisionRequired) as raised:
                    pipeline.run(
                        source=source, work_directory=root / "work", output_directory=root / "outputs",
                        count=2, target_seconds=8, theme="人物情绪", progress=lambda *_: None,
                        cancelled=lambda: False, automatic_duration=True, discovery_only=True,
                        analysis_mode="audiovisual", total_target_seconds=20, requested_count=1,
                    )
            self.assertEqual(raised.exception.stage, "speech_analysis")
            checkpoint = load_analysis_checkpoint(root / "work")
            self.assertEqual(checkpoint["decisionStage"], "speech_analysis")
            self.assertTrue(checkpoint["audioWaveform"]["rms"])
            self.assertFalse((root / "work" / "coarse-frames").exists())

    def test_content_classification_failure_preserves_resume_checkpoint(self) -> None:
        import subprocess

        class FailingClassificationClient:
            def analyze_image(
                self, prompt: str, image_path: Path, *, maximum_tokens: int = 0, system_prompt: str = "",
            ) -> dict:
                self.system_prompt = system_prompt
                raise ArkRequestError("classification unavailable", retryable=True)

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "source.mp4"
            subprocess.run([
                "/usr/bin/ffmpeg", "-hide_banner", "-loglevel", "error",
                "-f", "lavfi", "-i", "testsrc2=size=160x90:rate=8",
                "-t", "5", "-c:v", "libx264", "-pix_fmt", "yuv420p", "-y", str(source),
            ], check=True)
            client = FailingClassificationClient()
            pipeline = HighlightPipeline(client=client, ffmpeg="/usr/bin/ffmpeg", ffprobe="/usr/bin/ffprobe")
            with self.assertRaises(ModelDecisionRequired) as raised:
                pipeline.run(
                    source=source, work_directory=root / "work", output_directory=root / "outputs",
                    count=2, target_seconds=8, theme="动作", progress=lambda *_: None,
                    cancelled=lambda: False, automatic_duration=True, discovery_only=True,
                    total_target_seconds=20, requested_count=1,
                    analysis_start=1.0, analysis_end=4.0,
                )
            self.assertEqual(raised.exception.stage, "content_classification")
            self.assertEqual(client.system_prompt, COMMON_SYSTEM_PROMPT)
            checkpoint = load_analysis_checkpoint(root / "work")
            self.assertEqual(checkpoint["decisionStage"], "content_classification")
            self.assertTrue(Path(checkpoint["overviewSheet"]).is_file())
            self.assertGreaterEqual(len(checkpoint["frames"]), 2)
            self.assertTrue(all(1.0 <= float(item["time"]) <= 4.0 for item in checkpoint["frames"]))

    def test_pipeline_builds_multi_shot_event_without_real_api(self) -> None:
        import subprocess

        class FakeVisionClient:
            def __init__(self) -> None:
                self.refine_call = 0
                self.coarse_calls = 0
                self.fail_director = True
                self.system_prompts: list[str] = []

            def analyze_image(
                self, prompt: str, image_path: Path, *, maximum_tokens: int = 0, system_prompt: str = "",
            ) -> dict:
                self.system_prompts.append(system_prompt)
                if '"primary_type"' in prompt:
                    return {
                        "primary_type": "纪实调查", "secondary_types": ["新闻报道"],
                        "narrative_mode": "综合信号", "highlight_definition": ["事件发生变化"],
                        "downrank_conditions": ["重复画面"],
                        "evidence_weights": {"visual": .7, "speech": .2, "audio": .1},
                        "reason": "联系表显示连续事件", "_usage": {},
                    }
                if "center_seconds" in prompt:
                    self.coarse_calls += 1
                    return {"candidates": [
                        {"center_seconds": 2, "suggested_duration": 4, "score": 94, "title": "事件环境", "reason": "建立场景", "moment_role": "事件建立", "possible_event": "完整动作事件"},
                        {"center_seconds": 6, "suggested_duration": 4, "score": 96, "title": "事件行动", "reason": "动作高潮", "moment_role": "高潮", "possible_event": "完整动作事件"},
                    ], "_usage": {}}
                if '"event_groups"' in prompt:
                    if self.fail_director:
                        raise ArkRequestError("director unavailable", retryable=True)
                    return {"event_groups": [{
                        "title": "完整动作事件", "summary": "由环境和行动两个镜头组成", "score": 96,
                        "moments": [
                            {"candidate_index": 0, "role": "事件建立", "essential": True, "transition_in": "cut", "order": 0},
                            {"candidate_index": 1, "role": "高潮", "essential": True, "transition_in": "dissolve", "order": 1},
                        ],
                    }], "_usage": {}}
                self.refine_call += 1
                return {
                    "start_seconds": 4 if self.refine_call == 1 else 0,
                    "end_seconds": 7.9 if self.refine_call == 1 else 4,
                    "score": 95, "keep": True, "title": "同一事件镜头", "role": "事件镜头",
                    "reason": "镜头完整", "evidence": {"start": "动作开始", "peak": "真实画面", "end": "动作结束"},
                    "_usage": {},
                }

            def complete_json(
                self, prompt: str, *, maximum_tokens: int = 0, system_prompt: str = "",
            ) -> dict:
                raise AssertionError("事件导演必须查看三帧联系表，不能只调用文本模型")

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "source.mp4"
            subprocess.run([
                "/usr/bin/ffmpeg", "-hide_banner", "-loglevel", "error",
                "-f", "lavfi", "-i", "testsrc2=size=320x180:rate=12",
                "-t", "8", "-c:v", "libx264", "-pix_fmt", "yuv420p", "-y", str(source),
            ], check=True)
            client = FakeVisionClient()
            pipeline = HighlightPipeline(client=client, ffmpeg="/usr/bin/ffmpeg", ffprobe="/usr/bin/ffprobe")
            arguments = {
                "source": source, "work_directory": root / "work", "output_directory": root / "outputs",
                "count": 2, "target_seconds": 8, "theme": "动作", "progress": lambda *_: None,
                "cancelled": lambda: False, "automatic_duration": True, "discovery_only": True,
                "total_target_seconds": 12, "requested_count": 1,
            }
            with self.assertRaises(ModelDecisionRequired) as raised:
                pipeline.run(**arguments)
            self.assertEqual(raised.exception.stage, "event_director")
            checkpoint = load_analysis_checkpoint(root / "work")
            self.assertEqual(checkpoint["decisionStage"], "event_director")
            self.assertEqual(len(checkpoint["candidates"]), 2)
            coarse_calls = client.coarse_calls
            client.fail_director = False
            result = pipeline.run(**arguments, resume_action="retry")
            self.assertEqual(client.coarse_calls, coarse_calls, "恢复时不应重新粗看全片")
            self.assertTrue(all(value == COMMON_SYSTEM_PROMPT for value in client.system_prompts))
            self.assertEqual(result["schemaVersion"], 4)
            self.assertEqual(result["promptVersion"], PROMPT_VERSION)
            self.assertEqual(result["contentProfile"]["primaryType"], "纪实调查")
            self.assertFalse(result["directorDegraded"])
            self.assertEqual(len(result["eventGroups"]), 1)
            self.assertEqual(
                len(result["eventGroups"][0]["segments"]), 2,
                msg=str([(item["title"], len(item["segments"])) for item in result["eventGroups"]]),
            )
            self.assertEqual(result["recommendedGroupIds"], [result["eventGroups"][0]["id"]])

    def test_probe_and_render_real_video(self) -> None:
        import subprocess

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "source.mp4"
            output = root / "clip.mp4"
            subprocess.run([
                "/usr/bin/ffmpeg", "-hide_banner", "-loglevel", "error",
                "-f", "lavfi", "-i", "testsrc2=size=320x180:rate=25",
                "-f", "lavfi", "-i", "sine=frequency=440:sample_rate=48000",
                "-t", "3", "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac", "-y", str(source),
            ], check=True)
            info = probe_video(source, "/usr/bin/ffprobe")
            self.assertGreater(info.duration, 2.8)
            self.assertTrue(info.has_audio)
            validate_video_decodable_coverage(
                source, duration=info.duration, ffmpeg="/usr/bin/ffmpeg",
            )
            waveform_progress: list[tuple[float, float, float]] = []
            waveform = extract_audio_waveform(
                source, ffmpeg="/usr/bin/ffmpeg", bins=200, duration=info.duration,
                progress_callback=lambda fraction, processed, total: waveform_progress.append((fraction, processed, total)),
            )
            self.assertGreater(len(waveform["peaks"]), 100)
            self.assertEqual(len(waveform["peaks"]), len(waveform["rms"]))
            self.assertEqual(len(waveform["peaks"]), len(waveform["minimums"]))
            self.assertEqual(len(waveform["peaks"]), len(waveform["maximums"]))
            self.assertGreater(max(waveform["peaks"]), 0.01)
            self.assertLess(min(waveform["minimums"]), -0.01)
            self.assertGreater(max(waveform["maximums"]), 0.01)
            self.assertTrue(waveform_progress)
            self.assertAlmostEqual(waveform_progress[-1][0], 1.0)
            self.assertAlmostEqual(waveform_progress[-1][1], info.duration)
            sprite = root / "timeline.jpg"
            partial_sprite = root / "timeline.partial.jpg"
            shared_frames = root / "coarse-frames"
            partial_counts: list[int] = []
            sprite_metadata = create_timeline_thumbnail_sprite(
                source, sprite, duration=info.duration, ffmpeg="/usr/bin/ffmpeg", frame_count=12, columns=4,
                partial_output=partial_sprite,
                partial_callback=lambda metadata: partial_counts.append(len(metadata["items"])),
                frames_directory=shared_frames,
                preserve_frames=True,
            )
            self.assertTrue(sprite.is_file())
            self.assertGreaterEqual(len(sprite_metadata["items"]), 2)
            self.assertTrue(partial_sprite.is_file())
            self.assertTrue(partial_counts)
            self.assertEqual(partial_counts[-1], len(sprite_metadata["items"]))
            cached_frames = extract_uniform_frames(
                source, shared_frames, duration=info.duration,
                ffmpeg="/definitely/missing/ffmpeg", maximum_frames=12,
            )
            self.assertEqual(len(cached_frames), len(sprite_metadata["items"]))
            detail_directory = root / "detail-frames"
            detail_frames = extract_frames_at_times(
                source, detail_directory, [0.25, 1.0, 2.0], ffmpeg="/usr/bin/ffmpeg",
            )
            reused_detail_frames = extract_frames_at_times(
                source, detail_directory, [0.25, 1.0, 2.0], ffmpeg="/definitely/missing/ffmpeg",
            )
            self.assertEqual(
                [(item.path.name, item.time) for item in reused_detail_frames],
                [(item.path.name, item.time) for item in detail_frames],
            )
            proxy = root / "proxy.mp4"
            create_preview_proxy(source, proxy, has_audio=True, ffmpeg="/usr/bin/ffmpeg")
            proxy_info = probe_video(proxy, "/usr/bin/ffprobe")
            self.assertAlmostEqual(proxy_info.duration, info.duration, delta=.3)
            render_clip(source, output, start=0.5, end=2.0, has_audio=True, ffmpeg="/usr/bin/ffmpeg")
            rendered = validate_rendered_clip(
                output,
                expected_duration=1.5,
                expect_audio=True,
                ffmpeg="/usr/bin/ffmpeg",
                ffprobe="/usr/bin/ffprobe",
            )
            self.assertAlmostEqual(rendered.duration, 1.5, delta=0.3)
            self.assertTrue(rendered.has_audio)
            composition = root / "composition.mp4"
            composition_progress: list[float] = []
            expected = render_composition(
                source, composition,
                segments=[
                    {"start": 0, "end": 1.0, "transitionIn": {"type": "cut"}},
                    {"start": 1.5, "end": 2.7, "transitionIn": {"type": "dissolve", "duration": .18}},
                ],
                has_audio=True,
                ffmpeg="/usr/bin/ffmpeg",
                progress_callback=composition_progress.append,
            )
            composed = validate_rendered_clip(
                composition, expected_duration=expected, expect_audio=True,
                ffmpeg="/usr/bin/ffmpeg", ffprobe="/usr/bin/ffprobe",
            )
            self.assertAlmostEqual(composed.duration, 2.02, delta=.3)
            self.assertTrue(composition_progress)
            self.assertEqual(composition_progress, sorted(composition_progress))
            self.assertTrue(any(0 < value < 1 for value in composition_progress))
            self.assertEqual(composition_progress[-1], 1.0)
            advanced = root / "advanced-composition.mp4"
            advanced_segments = [
                {
                    "id": "a", "start": 0, "end": 1.2, "playbackRate": 1.25,
                    "silenceCuts": [{"start": .35, "end": .85, "retained": .15}],
                    "transitionIn": {"type": "cut"},
                },
                {
                    "id": "b", "start": 1.35, "end": 2.75, "playbackRate": 1.1,
                    "transitionIn": {"type": "fade_black", "duration": .3},
                    "audioBridge": {"type": "j_cut", "duration": .3},
                },
            ]
            advanced_expected = render_composition(
                source, advanced, segments=advanced_segments, has_audio=True,
                ffmpeg="/usr/bin/ffmpeg",
                preview_width=160,
                subtitle_cues=[{
                    "id": "advanced-cue", "start": .1, "end": 1.6,
                    "text": "调速转场字幕同步测试",
                }],
                subtitle_style="clean",
                subtitle_frame_width=160,
                subtitle_frame_height=90,
                cutaways=[{
                    "primarySegmentId": "b", "sourceStart": .1, "sourceEnd": .55,
                    "outputOffset": .35, "duration": .45, "muted": True,
                }],
            )
            advanced_info = validate_rendered_clip(
                advanced, expected_duration=advanced_expected, expect_audio=True,
                ffmpeg="/usr/bin/ffmpeg", ffprobe="/usr/bin/ffprobe",
            )
            self.assertAlmostEqual(
                advanced_info.duration, composition_effective_duration(advanced_segments), delta=.3,
            )
            self.assertEqual(advanced_info.width, 160)

    def test_portrait_preview_proxy_caps_the_long_edge(self) -> None:
        import subprocess

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "portrait-source.mp4"
            proxy = root / "portrait-proxy.mp4"
            subprocess.run([
                "/usr/bin/ffmpeg", "-hide_banner", "-loglevel", "error",
                "-f", "lavfi", "-i", "color=c=navy:size=540x1350:rate=5",
                "-t", "0.4", "-c:v", "libx264", "-pix_fmt", "yuv420p", "-an", "-y", str(source),
            ], check=True)
            create_preview_proxy(source, proxy, has_audio=False, ffmpeg="/usr/bin/ffmpeg")
            info = probe_video(proxy, "/usr/bin/ffprobe")
            self.assertGreater(info.height, info.width)
            self.assertLessEqual(max(info.width, info.height), 1280)
            self.assertEqual(info.height, 1280)


if __name__ == "__main__":
    unittest.main()
