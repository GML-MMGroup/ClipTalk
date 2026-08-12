from __future__ import annotations

import math
import os
import json
import tempfile
import unittest
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import MagicMock, patch

from app.ark_client import ArkRequestError, ArkVisionClient, OpenAICompatibleVisionClient, parse_json_object
from app.config import Settings
from app.vision_settings import LlmConfigurationStore, VisionConfigurationStore, discover_llm_models, discover_models
from app.main import (
    analysis_cache_reuse_allowed,
    apply_timeline_history_state,
    automatic_composition_signature,
    _normalise_edit_plans,
    _edit_plan_candidates,
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
    create_preview_proxy,
    create_timeline_thumbnail_sprite,
    extract_audio_waveform,
    extract_uniform_frames,
    probe_video,
    render_clip,
    render_composition,
    validate_rendered_clip,
)
from app.pipeline import (
    HighlightCandidate,
    HighlightPipeline,
    ModelDecisionRequired,
    _candidate_from_coarse,
    _refined_candidate,
    candidate_text_similarity,
    coarse_frame_limit,
    overlaps_ranges,
    recommended_candidate_indices,
    refinement_window_seconds,
    refinement_candidate_limit,
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
from app.event_groups import allocate_event_group_budget, build_event_groups, build_final_reel, composition_duration
from app.speech import (
    _sensevoice_model_options,
    normalize_sensevoice_result,
    parse_rich_tags,
    speech_evidence,
    transcript_context,
)
import app.main as main_module


class ProgressEtaTests(unittest.TestCase):
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
        )
        self.assertIsNone(facts["etaSeconds"])
        self.assertEqual(facts["etaMode"], "waiting_first_sample")
        self.assertEqual(facts["stageObservedIndex"], 1)
        self.assertEqual(facts["stageCompleted"], 0)
        self.assertEqual(stage_progress_for("coarse_vlm", .12, "视觉大模型正在分析第 1/5 组画面"), 0)

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
        )
        self.assertEqual(facts["stageCompleted"], 32)
        self.assertEqual(facts["stageTotal"], 120)
        self.assertEqual(facts["stageUnit"], "秒")
        self.assertEqual(facts["progressMode"], "determinate")
        self.assertAlmostEqual(stage_progress_for("audio_analysis", .05, "音频波形已处理 32/120 秒"), 32 / 120)


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

    def test_normalise_edit_plan_clamps_subrange_and_rejects_overlap(self) -> None:
        rows = _edit_plan_candidates(self.job, ["event_1"], None, "selected_only")
        plans = _normalise_edit_plans({"plans": [{"label": "测试", "sequence": [
            {"candidate_id": "segment_1", "source_start": 5, "source_end": 18, "role": "hook"},
            {"candidate_id": "segment_1", "source_start": 17, "source_end": 24, "role": "climax"},
        ]}]}, rows, scope="selected_only", selected_group_ids=["event_1"], target=20)
        self.assertEqual(len(plans), 1)
        self.assertEqual(len(plans[0]["sequence"]), 2)
        self.assertEqual(plans[0]["sequence"][0]["start"], 10.0)
        self.assertAlmostEqual(plans[0]["estimatedDuration"], 20.0, places=2)

    def test_edit_plan_prompt_requires_local_subranges(self) -> None:
        prompt = llm_edit_plan_prompt(content_profile={}, theme="情绪", target_seconds=60, scope="selected_only", selected_group_ids=["event_1"], variants=["叙事完整版"], candidates=[], transcript_context="")
        self.assertIn("source_start/source_end", prompt)
        self.assertTrue(EDIT_PLAN_PROMPT_VERSION)

    def test_automatic_composition_signature_matches_plan_and_rendered_segments(self) -> None:
        plan = [{"candidateId": "segment_1", "start": 10.004, "end": 20.004}]
        rendered = [{"id": "segment_1", "start": 10.0, "end": 20.0}]
        self.assertEqual(automatic_composition_signature(plan), automatic_composition_signature(rendered))


class PublicJobPayloadTests(unittest.TestCase):
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
        self.assertTrue(PROMPT_VERSION.startswith("highlight-director-v8-peak-budget"))
        self.assertIn("不得虚构", COMMON_SYSTEM_PROMPT)
        self.assertIn('"primary_type"', classification)
        self.assertIn('"center_seconds"', discovery)
        self.assertIn('"start_seconds"', refinement)
        self.assertIn('"peak_start_seconds"', refinement)
        self.assertIn('"boundary_confidence"', refinement)
        self.assertIn('"event_groups"', director)
        self.assertIn("START、PEAK、END", director)

    def test_adaptive_sampling_bounds_typical_vlm_round_trips(self) -> None:
        frames = coarse_frame_limit(263)
        refined = refinement_candidate_limit(
            discovery_only=True, total_target_seconds=30, target_seconds=8, count=6,
        )
        discovery_pages = math.ceil(frames / 16)
        base_calls = 1 + discovery_pages + refined + 1
        self.assertEqual(frames, 48)
        self.assertEqual(refined, 5)
        # Only the two strongest candidates may request a second boundary pass.
        self.assertLessEqual(base_calls + 2, 12)


class SenseVoiceParsingTests(unittest.TestCase):
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
                main_module.delete_job(job_id)
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
                with patch.object(main_module.source_proxy_executor, "submit") as submit:
                    self.assertTrue(main_module.schedule_preview_proxy(job_id))
                    self.assertFalse(main_module.schedule_preview_proxy(job_id))
                    submit.assert_called_once()
            finally:
                with main_module.source_proxy_schedule_lock:
                    main_module.scheduled_source_proxies.discard(identity)
                    main_module.source_proxy_failures.pop(identity, None)
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
                with patch.object(main_module, "probe_video", return_value=info), patch.object(main_module, "create_preview_proxy") as create:
                    main_module.prepare_preview_proxy(job_id)
                    self.assertEqual(create.call_args.kwargs["maximum_dimension"], 720)
            finally:
                main_module.jobs.pop(job_id, None)
                main_module.settings = original_settings


class CandidateSelectionTests(unittest.TestCase):
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
                {"candidate_index": 0, "role": "事件建立", "essential": True, "transition_in": "cut"},
                {"candidate_index": 1, "role": "高潮", "essential": True, "transition_in": "cut"},
                {"candidate_index": 2, "role": "人物反应", "essential": False, "transition_in": "dissolve"},
            ],
        }]})
        self.assertEqual(len(groups), 1)
        self.assertEqual(len(groups[0]["segments"]), 3)
        self.assertAlmostEqual(groups[0]["actualDuration"], 22.82, places=2)

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
                )
            self.assertEqual(raised.exception.stage, "content_classification")
            self.assertEqual(client.system_prompt, COMMON_SYSTEM_PROMPT)
            checkpoint = load_analysis_checkpoint(root / "work")
            self.assertEqual(checkpoint["decisionStage"], "content_classification")
            self.assertTrue(Path(checkpoint["overviewSheet"]).is_file())
            self.assertGreaterEqual(len(checkpoint["frames"]), 2)

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
