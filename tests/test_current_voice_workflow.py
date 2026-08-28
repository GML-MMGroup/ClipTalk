from __future__ import annotations

import copy
import json
from pathlib import Path

from app import main
from app.api_schemas import (
    ChatRequest,
    CurrentVoiceDiscoveryRequest,
    CurrentVoiceEditRequest,
    CurrentVoiceLabelRequest,
    CurrentVoiceRoleRequest,
    SubtitleDraftCreateRequest,
)


def test_voice_cluster_embeddings_are_reused_in_memory(monkeypatch, tmp_path: Path) -> None:
    source = tmp_path / "source.mp4"
    source.write_bytes(b"video")
    calls: list[Path] = []
    monkeypatch.setattr(
        main, "normalize_audio",
        lambda _source, destination, **_kwargs: calls.append(Path(destination)),
    )
    monkeypatch.setattr(main.voice_encoder, "encode", lambda _path: [1.0, *([0.0] * 191)])
    segments = [
        {"start": 0.0, "end": 2.4, "speaker": "Speaker 1", "text": "第一句"},
        {"start": 2.6, "end": 4.8, "speaker": "Speaker 1", "text": "第二句"},
    ]
    with main.voice_cluster_cache_lock:
        main.voice_cluster_cache.clear()
    first, first_ranges = main._voice_cluster_embedding(
        source, tmp_path / "first", "Speaker 1", segments,
    )
    first_call_count = len(calls)
    second, second_ranges = main._voice_cluster_embedding(
        source, tmp_path / "second", "Speaker 1", segments,
    )
    assert first["cacheHit"] is False
    assert second["cacheHit"] is True
    assert first_call_count > 0
    assert len(calls) == first_call_count
    assert first_ranges == second_ranges


def current_voice_job(job_id: str) -> dict:
    return {
        "id": job_id, "taskMode": "content_extract",
        "status": "awaiting_content_confirmation", "stage": "voice_discovery_ready",
        "request": {}, "messages": [], "contentSearchHistory": [], "revision": 0,
        "videoInfo": {"duration": 12.0},
        "speechAnalysis": {
            "diarization": True,
            "segments": [
                {"start": 0.0, "end": 2.0, "speaker": "Speaker 0", "text": "第一句话"},
                {"start": 2.3, "end": 4.0, "speaker": "Speaker 0", "text": "离线功能"},
                {"start": 6.0, "end": 8.0, "speaker": "Speaker 1", "text": "另一个人"},
            ],
        },
        "voiceDiscovery": {"status": "ready", "speakerCount": 2, "storesEmbeddings": False},
        "voiceSpeakerCatalog": [
            {"speakerRef": "Speaker 0", "speechSeconds": 3.7, "segmentCount": 2,
             "quality": {"clusterMinimumSimilarity": .82}, "requiresReview": False,
             "representativeSegments": [{"start": 0, "end": 2, "text": "第一句话"}]},
            {"speakerRef": "Speaker 1", "speechSeconds": 2.0, "segmentCount": 1,
             "quality": {"clusterMinimumSimilarity": .75}, "requiresReview": False,
             "representativeSegments": [{"start": 6, "end": 8, "text": "另一个人"}]},
        ],
    }


def test_current_voice_can_be_named_and_filtered_without_profile_store(monkeypatch) -> None:
    job_id = "test_current_voice"
    job = current_voice_job(job_id)
    monkeypatch.setattr(main, "save_job", lambda _job: None)
    monkeypatch.setattr(main, "append_message", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(main, "public_job", lambda value: copy.deepcopy(value))
    main.jobs[job_id] = job
    try:
        result = main.label_current_voice(
            job_id, CurrentVoiceLabelRequest(speakerRef="Speaker 0", label="黑衣男"),
        )
        assert result["voice"]["label"] == "黑衣男"
        assert result["voice"]["userLabeled"] is True

        public = main._apply_current_speaker_search(job_id, "Speaker 0", "离线功能")
        search = public["contentSearch"]
        assert search["candidateCount"] == 1
        assert "离线功能" in search["candidates"][0]["text"]
        assert search["candidates"][0]["selected"] is True
        assert search["intent"]["schemaVersion"] == "current-voice-target-intent-v2"
        assert search["coverageComplete"] is True
    finally:
        main.jobs.pop(job_id, None)


def test_uncertain_current_voice_candidates_are_optional_not_a_generation_gate(monkeypatch) -> None:
    job_id = "test_uncertain_current_voice"
    job = current_voice_job(job_id)
    job["voiceSpeakerCatalog"][0]["requiresReview"] = True
    monkeypatch.setattr(main, "save_job", lambda _job: None)
    monkeypatch.setattr(main, "append_message", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(main, "public_job", lambda value: copy.deepcopy(value))
    main.jobs[job_id] = job
    try:
        public = main._apply_current_speaker_search(job_id, "Speaker 0", "离线功能")
        search = public["contentSearch"]
        candidate = search["candidates"][0]
        assert candidate["confidenceTier"] == "possible"
        assert candidate["reviewStatus"] == "pending"
        assert candidate["selected"] is False
        assert search["completeness"]["status"] == "complete"
        assert search["completeness"]["pendingCount"] == 0
        assert search["completeness"]["optionalCandidateIds"] == [candidate["id"]]
        assert search["coverageComplete"] is True
    finally:
        main.jobs.pop(job_id, None)


def test_current_voice_catalog_contains_no_embeddings() -> None:
    job = current_voice_job("catalog")
    voices = main._public_current_voice_catalog(job)
    assert [item["label"] for item in voices] == ["说话人 A", "说话人 B"]
    assert all("centroid" not in item and "embedding" not in item for item in voices)


def test_current_voice_catalog_suggests_only_the_strongest_narrator_candidate() -> None:
    voices = main._public_current_voice_catalog(current_voice_job("narrator_candidate"))
    assert voices[0]["narration"]["status"] == "candidate"
    assert voices[0]["narration"]["score"] >= .67
    assert voices[0]["narration"]["confirmedByUser"] is False
    assert voices[1]["narration"]["status"] == "unlikely"
    assert voices[0]["narration"]["basis"] == "speaker-timeline-heuristics-v1"


def test_visible_person_link_prevents_automatic_narrator_suggestion() -> None:
    job = current_voice_job("visible_speaker")
    job["personSpeakerLinks"] = {
        "person_1": {"speaker": "Speaker 0", "source": "user"},
    }
    voices = main._public_current_voice_catalog(job)
    first = next(item for item in voices if item["speakerRef"] == "Speaker 0")
    assert first["narration"]["status"] == "unlikely"
    assert first["narration"]["linkedToVisiblePerson"] is True
    assert any("画面人物" in value for value in first["narration"]["reasons"])


def test_current_voice_can_be_confirmed_as_narrator_without_visual_analysis(monkeypatch) -> None:
    job_id = "confirmed_narrator"
    job = current_voice_job(job_id)
    monkeypatch.setattr(main, "save_job", lambda _job: None)
    main.jobs[job_id] = job
    try:
        result = main.set_current_voice_role(
            job_id, CurrentVoiceRoleRequest(speakerRef="Speaker 0", role="narrator"),
        )
        assert job["voiceSpeakerRoles"]["Speaker 0"]["role"] == "narrator"
        assert result["voice"]["label"] == "旁白"
        assert result["voice"]["narration"]["status"] == "confirmed"
        assert result["voice"]["narration"]["confirmedByUser"] is True
    finally:
        main.jobs.pop(job_id, None)


def test_confirmed_narrator_query_reuses_speaker_timeline(monkeypatch) -> None:
    job_id = "narrator_query"
    job = current_voice_job(job_id)
    job["voiceSpeakerRoles"] = {
        "Speaker 0": {"role": "narrator", "source": "user"},
    }
    monkeypatch.setattr(main, "save_job", lambda _job: None)
    monkeypatch.setattr(main, "append_message", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(main, "public_job", lambda value: copy.deepcopy(value))
    monkeypatch.setattr(
        main, "_route_content_message",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("不应调用意图模型")),
    )
    main.jobs[job_id] = job
    try:
        result = main.chat_with_job(
            job_id, ChatRequest(text="找出旁白提到离线功能的片段"),
        )
        assert result["accepted"] is True
        search = result["job"]["contentSearch"]
        assert search["candidateCount"] == 1
        assert search["candidates"][0]["speaker"] == "Speaker 0"
        assert "离线功能" in search["candidates"][0]["text"]
        assert search["retrievalStats"]["source"] == "current_video_diarization"
    finally:
        main.jobs.pop(job_id, None)


def test_unconfirmed_narrator_query_requests_voice_confirmation(monkeypatch) -> None:
    job_id = "narrator_confirmation"
    job = current_voice_job(job_id)
    messages: list[str] = []
    monkeypatch.setattr(main, "save_job", lambda _job: None)
    monkeypatch.setattr(
        main, "append_message",
        lambda _job_id, _role, text, **_kwargs: messages.append(text),
    )
    monkeypatch.setattr(main, "public_job", lambda value: copy.deepcopy(value))
    main.jobs[job_id] = job
    try:
        result = main.chat_with_job(
            job_id, ChatRequest(text="提取旁白讲述离线功能的片段"),
        )
        assert result["action"] == "narrator-confirmation"
        assert job["narratorSelectionPending"]["query"] == "离线功能"
        assert any("疑似旁白" in value for value in messages)
    finally:
        main.jobs.pop(job_id, None)


def test_current_voice_quality_uses_cluster_consistency_not_cross_video_threshold(monkeypatch) -> None:
    job = current_voice_job("cluster_quality")
    job["voiceSpeakerCatalog"][0]["quality"]["clusterMinimumSimilarity"] = .5
    job["voiceSpeakerCatalog"][0]["requiresReview"] = False
    monkeypatch.setattr(main, "save_job", lambda _job: None)
    main._rebuild_current_voice_catalog(job)
    first = next(item for item in job["voiceSpeakerCatalog"] if item["speakerRef"] == "Speaker 0")
    assert first["requiresReview"] is True


def test_legacy_low_outlier_requires_review_without_claiming_mixed_speakers() -> None:
    job = current_voice_job("legacy_outlier")
    first = job["voiceSpeakerCatalog"][0]
    first["sampleCount"] = 6
    first["requiresReview"] = True
    first["quality"] = {
        "clusterMinimumSimilarity": .47,
        "suspectedMixed": True,
        "warning": "簇内声音差异较大，可能包含多个说话人",
    }
    public = main._public_current_voice_catalog(job)[0]
    assert public["requiresReview"] is True
    assert public["quality"]["suspectedMixed"] is False
    assert public["quality"]["warning"] == "声音样本一致度偏低，建议试听确认"


def test_forced_voice_discovery_accepts_expected_speaker_count_and_clears_old_labels(monkeypatch) -> None:
    job_id = "forced_voice_discovery"
    job = current_voice_job(job_id)
    job["voiceSpeakerLabels"] = {"Speaker 0": {"label": "旧人物"}}
    job["voiceSpeakerRoles"] = {"Speaker 0": {"role": "narrator"}}
    monkeypatch.setattr(main, "save_job", lambda _job: None)
    monkeypatch.setattr(main, "append_message", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(main, "submit_analysis_task", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(main, "public_job", lambda value: copy.deepcopy(value))
    main.jobs[job_id] = job
    try:
        result = main.discover_current_voices(job_id, CurrentVoiceDiscoveryRequest(
            expectedSpeakerCount=2, force=True,
        ))
        assert result["accepted"] is True
        assert job["voiceDiscovery"]["expectedSpeakerCount"] == 2
        assert job["voiceSpeakerLabels"] == {}
        assert job["voiceSpeakerRoles"] == {}
        assert "voiceSpeakerCatalog" not in job
    finally:
        main.jobs.pop(job_id, None)
        main.cancel_events.pop(job_id, None)


def test_forced_voice_discovery_preserves_user_constraints_and_labels(monkeypatch) -> None:
    job_id = "forced_voice_discovery_with_corrections"
    job = current_voice_job(job_id)
    job["voiceSpeakerLabels"] = {"User Speaker 1": {"label": "主持人"}}
    job["voiceSpeakerRoles"] = {"User Speaker 1": {"role": "narrator"}}
    job["voiceCorrectionConstraints"] = [{
        "id": "manual_1", "start": 1, "end": 3,
        "targetSpeakerRef": "User Speaker 1", "source": "user",
    }]
    monkeypatch.setattr(main, "save_job", lambda _job: None)
    monkeypatch.setattr(main, "append_message", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(main, "submit_analysis_task", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(main, "public_job", lambda value: copy.deepcopy(value))
    main.jobs[job_id] = job
    try:
        main.discover_current_voices(job_id, CurrentVoiceDiscoveryRequest(force=True))
        assert job["voiceSpeakerLabels"]["User Speaker 1"]["label"] == "主持人"
        assert job["voiceSpeakerRoles"]["User Speaker 1"]["role"] == "narrator"
        assert job["voiceCorrectionConstraints"][0]["targetSpeakerRef"] == "User Speaker 1"
    finally:
        main.jobs.pop(job_id, None)
        main.cancel_events.pop(job_id, None)


def test_voice_discovery_start_exposes_live_progress_before_completion(monkeypatch) -> None:
    job_id = "voice_discovery_progress"
    job = current_voice_job(job_id)
    notices: list[tuple[str, str]] = []
    monkeypatch.setattr(main, "save_job", lambda _job: None)
    monkeypatch.setattr(
        main, "append_message",
        lambda _job_id, role, text, **_kwargs: notices.append((role, text)),
    )
    monkeypatch.setattr(main, "submit_analysis_task", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(main, "public_job", lambda value: copy.deepcopy(value))
    main.jobs[job_id] = job
    try:
        result = main.discover_current_voices(
            job_id, CurrentVoiceDiscoveryRequest(expectedSpeakerCount=2, force=True),
        )
        assert result["accepted"] is True
        assert job["status"] == "running"
        assert job["voiceDiscovery"]["status"] == "running"
        assert job["stageProgress"] is None
        assert job["progressMode"] == "indeterminate"
        assert notices[0] == ("user", "识别当前视频中的说话人")
        assert "已开始分析语音" in notices[1][1]
        assert not any("已从当前视频识别出" in text for _role, text in notices)
        assert main.public_job_status(job)["voiceDiscovery"]["status"] == "running"
    finally:
        main.jobs.pop(job_id, None)
        main.cancel_events.pop(job_id, None)


def test_current_voice_multiselect_exclude_and_timeline(monkeypatch) -> None:
    job_id = "multi_voice"
    job = current_voice_job(job_id)
    monkeypatch.setattr(main, "save_job", lambda _job: None)
    monkeypatch.setattr(main, "append_message", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(main, "public_job", lambda value: copy.deepcopy(value))
    main.jobs[job_id] = job
    try:
        timeline = main.list_current_voices(job_id)["timeline"]
        assert [item["turnId"] for item in timeline] == ["voice_turn_00000", "voice_turn_00001", "voice_turn_00002"]
        result = main._apply_current_speakers_search(job_id, ["Speaker 1"], "", "exclude")
        assert result["contentSearch"]["candidateCount"] == 1
        assert result["contentSearch"]["candidates"][0]["speaker"] == "Speaker 0"
        assert result["contentSearch"]["intent"]["voiceSelectionMode"] == "exclude"
    finally:
        main.jobs.pop(job_id, None)


def test_current_voice_merge_reassign_and_undo(monkeypatch) -> None:
    job_id = "edit_voice"
    job = current_voice_job(job_id)
    monkeypatch.setattr(main, "save_job", lambda _job: None)
    monkeypatch.setattr(main, "append_message", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(main, "public_job", lambda value: copy.deepcopy(value))
    main.jobs[job_id] = job
    try:
        merged = main.edit_current_voices(job_id, CurrentVoiceEditRequest(
            operation="merge", speakerRefs=["Speaker 0", "Speaker 1"],
            targetSpeakerRef="Speaker 0", revision=0,
        ))
        assert len(merged["voices"]) == 1
        assert merged["voices"][0]["userCorrected"] is True
        assert merged["revision"] == 1

        moved = main.edit_current_voices(job_id, CurrentVoiceEditRequest(
            operation="reassign", turnIds=["voice_turn_00002"],
            targetSpeakerRef="new", label="声音 C", revision=1,
        ))
        assert {item["label"] for item in moved["voices"]} == {"说话人 A", "声音 C"}
        assert moved["revision"] == 2
        corrected_ref = next(item["speakerRef"] for item in moved["voices"] if item["label"] == "声音 C")
        corrected_search = main._apply_current_speakers_search(job_id, [corrected_ref], "", "include")
        assert corrected_search["contentSearch"]["candidateCount"] == 1
        assert corrected_search["contentSearch"]["candidates"][0]["speaker"] == corrected_ref
        assert corrected_search["contentSearch"]["candidates"][0]["start"] == 5.85

        undone = main.undo_current_voice_edit(job_id)
        assert len(undone["voices"]) == 1
        assert undone["revision"] == 1
    finally:
        main.jobs.pop(job_id, None)


def test_current_voice_can_split_one_turn_at_playhead(monkeypatch) -> None:
    job_id = "split_voice"
    job = current_voice_job(job_id)
    monkeypatch.setattr(main, "save_job", lambda _job: None)
    main.jobs[job_id] = job
    try:
        result = main.edit_current_voices(job_id, CurrentVoiceEditRequest(
            operation="split", turnIds=["voice_turn_00000"], splitTime=1.5,
            targetSpeakerRef="new", label="新声音", revision=0,
        ))
        assert len(result["timeline"]) == 4
        assert result["timeline"][0]["end"] == 1.5
        assert result["timeline"][1]["start"] == 1.5
        assert result["timeline"][1]["label"] == "新声音"
    finally:
        main.jobs.pop(job_id, None)


def test_temporary_voice_sources_are_unique_and_catalog_has_no_vectors(tmp_path) -> None:
    reference = current_voice_job("reference")
    target = current_voice_job("target")
    duplicate = current_voice_job("duplicate")
    reference_path = tmp_path / "reference.mp4"
    target_path = tmp_path / "target.mp4"
    reference_path.write_bytes(b"video")
    target_path.write_bytes(b"video")
    reference.update({"sourcePath": str(reference_path), "sourceHash": "ref", "videoInfo": {"duration": 12, "has_audio": True}})
    target.update({"sourcePath": str(target_path), "sourceHash": "target", "filename": "target.mp4", "videoInfo": {"duration": 12, "has_audio": True}})
    duplicate.update({"sourcePath": str(target_path), "sourceHash": "target", "filename": "duplicate.mp4", "videoInfo": {"duration": 12, "has_audio": True}})
    main.jobs.update({"reference": reference, "target": target, "duplicate": duplicate})
    try:
        sources = main.list_temporary_voice_sources("reference")["sources"]
        selected_sources = [item for item in sources if item["jobId"] in {"target", "duplicate"}]
        assert len(selected_sources) == 1
        catalog, labels = main._temporary_voice_catalog(
            target["speechAnalysis"], [{
                "speaker": "Speaker 0", "decision": "matched", "score": .8,
                "margin": .2, "sampleCount": 2, "minimumSampleSimilarity": .7,
            }], "黑衣男",
        )
        assert all("centroid" not in item and "embedding" not in item and "exemplars" not in item for item in catalog)
        assert labels["Speaker 0"]["label"] == "黑衣男"
    finally:
        for value in ("reference", "target", "duplicate"):
            main.jobs.pop(value, None)


def test_speaker_labels_are_added_to_subtitle_cues() -> None:
    job = current_voice_job("subtitles")
    job["voiceSpeakerLabels"] = {"Speaker 0": {"label": "黑衣男"}}
    cues = main._subtitle_cues(job, {"segments": [{"start": 0, "end": 8}]})
    assert cues
    assert cues[0]["speakerLabel"] == "黑衣男"
    assert cues[0]["showSpeakerLabel"] is True
    assert cues[0]["speakerColor"].startswith("0x")


def test_subtitle_draft_loads_transcript_when_speech_analysis_keeps_only_count(tmp_path: Path) -> None:
    job_id = "subtitle_from_compact_speech_summary"
    (tmp_path / "transcript.json").write_text(
        '{"segments":[{"start":1,"end":3,"text":"可用字幕文本"}]}',
        encoding="utf-8",
    )
    job = {
        "id": job_id,
        "videoInfo": {"duration": 12.0},
        "workDirectory": str(tmp_path),
        "speechAnalysis": {"status": "ready", "segments": 1},
    }
    main.jobs[job_id] = job
    try:
        result = main.create_subtitle_draft(
            job_id,
            SubtitleDraftCreateRequest(outputs=[{
                "segments": [{"id": "clip_1", "start": 0, "end": 5}],
            }]),
        )
        assert result["draft"]["cues"][0]["text"] == "可用字幕文本"
    finally:
        main.jobs.pop(job_id, None)


def test_subtitle_draft_queues_on_demand_transcription_when_transcript_is_missing(
    monkeypatch, tmp_path: Path,
) -> None:
    job_id = "subtitle_needs_transcription"
    job = {
        "id": job_id,
        "videoInfo": {"duration": 12.0, "has_audio": True},
        "workDirectory": str(tmp_path),
        "speechAnalysis": {"segments": []},
    }
    main.jobs[job_id] = job
    monkeypatch.setattr(main, "save_job", lambda _job: None)
    monkeypatch.setattr(main, "queue_subtitle_transcription", lambda _job_id: {
        "status": "queued", "progress": 0.0, "detail": "对白识别已进入队列",
        "completed": None, "total": None, "unit": "", "segmentCount": 0, "error": "",
    })
    try:
        response = main.create_subtitle_draft(
            job_id,
            SubtitleDraftCreateRequest(outputs=[{
                "segments": [{"id": "clip_1", "start": 0, "end": 5}],
            }]),
        )
        assert response.status_code == 202
        payload = json.loads(response.body)
        assert payload["status"] == "transcribing"
        assert payload["transcription"]["status"] == "queued"
    finally:
        main.jobs.pop(job_id, None)


def test_on_demand_subtitle_transcription_persists_reusable_transcript(
    monkeypatch, tmp_path: Path,
) -> None:
    job_id = "subtitle_transcription_worker"
    source = tmp_path / "source.mp4"
    source.write_bytes(b"video")
    work = tmp_path / "work"
    job = {
        "id": job_id,
        "sourcePath": str(source),
        "sourceHash": "subtitle-source-hash",
        "workDirectory": str(work),
        "videoInfo": {"duration": 12.0, "has_audio": True},
        "request": {"analysisMode": "audiovisual"},
        "speechAnalysis": {"segments": []},
    }
    main.jobs[job_id] = job
    main.subtitle_transcription_cancels[job_id] = main.threading.Event()
    monkeypatch.setattr(main, "save_job", lambda _job: None)
    monkeypatch.setattr(main, "content_index_directory", lambda _job: tmp_path / "shared")

    def fake_analyze(_source, _cache, **kwargs):
        kwargs["progress_callback"](.5, 1, 2, "recognizing")
        return {
            "schemaVersion": "speech-v-test", "engine": "sensevoice",
            "segments": [{"start": 1.0, "end": 3.0, "text": "这是一段对白"}],
        }

    monkeypatch.setattr(main, "analyze_speech", fake_analyze)
    try:
        main.run_subtitle_transcription(job_id)
        transcript = json.loads((work / "transcript.json").read_text(encoding="utf-8"))
        assert transcript["segments"][0]["text"] == "这是一段对白"
        assert main.jobs[job_id]["speechAnalysis"]["segments"] == 1
        assert main.jobs[job_id]["subtitleTranscription"]["status"] == "completed"
    finally:
        main.subtitle_transcription_cancels.pop(job_id, None)
        main.jobs.pop(job_id, None)
