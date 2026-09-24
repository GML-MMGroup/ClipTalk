from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
from PIL import Image, ImageDraw

from app.agent_platform import AgentPlatform
from app import copy_messages
from app.media import SampledFrame, VideoInfo


def test_cover_profile_compiles_a_forced_review_plan(tmp_path: Path) -> None:
    platform = AgentPlatform(
        data_root=tmp_path, service_url="http://agent.invalid",
        model_config_resolver=lambda: {},
    )
    skill = {
        "id": "cliptalk-cover-director", "source": "test", "version": "1.0.0",
        "contentHash": "cover-hash", "workflowProfile": "cover",
        "allowedTools": [
            "inspect_workspace", "propose_cover_candidates", "render_cover_variants",
            "review_cover_variants", "confirm_cover",
        ],
    }
    goal = "为视频做一张 9:16 封面，标题：关键时刻"
    context = {"jobId": "job_cover", "editing": {"hasOutputs": True}}

    plan = platform._compile_profile_plan(
        {}, skill=skill, goal=goal, context=context,
        execution_mode="autonomous_review",
    )

    assert plan["profile"] == "cover"
    assert plan["executionMode"] == "stepwise_review"
    assert [step["tool"] for step in plan["steps"]] == [
        "inspect_workspace", "propose_cover_candidates", "render_cover_variants",
        "review_cover_variants", "confirm_cover",
    ]
    assert plan["brief"]["coverAspect"] == "9:16"
    assert plan["brief"]["coverTitle"] == "关键时刻"
    assert plan["brief"]["socialDelivery"]["requested"] is False


def test_cover_saved_copy_does_not_imply_hidden_video_render() -> None:
    assert copy_messages.cover_saved() == "封面已保存；本次只更新封面，不修改视频画面"
    assert copy_messages.cover_saved(1) == "封面已保存，并关联到 1 条当前成片；视频画面未改动"


def test_cover_tools_generate_review_and_activate_a_version(
    tmp_path: Path, monkeypatch: Any,
) -> None:
    from app import main

    job_id = "job_cover_tools"
    work = tmp_path / "work"
    outputs = tmp_path / "outputs"
    source = tmp_path / "source.mp4"
    work.mkdir()
    outputs.mkdir()
    source.write_bytes(b"video")
    rendered_video = outputs / "final.mp4"
    rendered_video.write_bytes(b"rendered-video")
    output = {"filename": "final.mp4", "title": "正式成片", "segments": []}
    output_version = {"id": "v001", "number": 1, "outputs": [output]}
    job = {
        "id": job_id, "revision": 1, "sourcePath": str(source),
        "filename": "source.mp4", "sourceHash": "source-hash",
        "workDirectory": str(work), "outputDirectory": str(outputs),
        "videoInfo": {"duration": 30}, "outputs": [output],
        "outputVersions": [output_version], "currentOutputVersionId": "v001",
        "candidates": [
            {"id": "event_1", "start": 4, "end": 8, "score": 92, "title": "关键人物反应"},
            {"id": "event_2", "start": 18, "end": 23, "score": 86, "title": "动作结果"},
        ],
    }
    monkeypatch.setitem(main.jobs, job_id, job)
    monkeypatch.setattr(main, "save_job", lambda _job: None)
    monkeypatch.setattr(main, "probe_video", lambda *_args, **_kwargs: VideoInfo(30, 1280, 720, True))

    def extract(_source: Path, directory: Path, times: Any, **_kwargs: Any) -> list[SampledFrame]:
        directory.mkdir(parents=True, exist_ok=True)
        frames = []
        for index, second in enumerate(times):
            path = directory / f"detail-{index:03d}.jpg"
            image = Image.new("RGB", (640, 360), (25 + index * 11, 60, 100 + index * 7))
            draw = ImageDraw.Draw(image)
            offset = (index * 29) % 260
            draw.ellipse((80 + offset, 55, 260 + offset, 300), fill=(220, 90 + index * 5, 45))
            image.save(path, "JPEG")
            frames.append(SampledFrame(path=path, time=float(second)))
        return frames

    monkeypatch.setattr(main, "extract_frames_at_times", extract)
    workspace = {"id": "ws_cover", "jobId": job_id, "executionMode": "stepwise_review"}

    proposed = main.dispatch_agent_tool(workspace, "propose_cover_candidates", {
        "sourceScope": "accepted_cut", "candidateBudget": 8,
        "aspectRatios": ["16:9"], "focus": "关键人物反应", "sourceTime": 12,
    })
    proposed_artifact = proposed["future"].result(timeout=5)["artifact"]
    assert proposed_artifact["kind"] == "cover_candidates"
    assert len(job["coverDraft"]["candidates"]) >= 3
    assert all(
        abs(float(item["sourceTime"]) - 12.0) <= .75
        for item in job["coverDraft"]["candidates"]
    )

    rendered = main.dispatch_agent_tool(workspace, "render_cover_variants", {
        "aspectRatios": ["16:9"],
        "directions": ["source_clean", "source_editorial", "source_cinematic"],
        "titleText": "小米牛逼！",
    })
    rendered_artifact = rendered["future"].result(timeout=5)["artifact"]
    assert rendered_artifact["kind"] == "cover_variant_set"
    assert len(job["coverDraft"]["variants"]) == 3
    assert all(item["titleText"] == "小米牛逼！" for item in job["coverDraft"]["variants"])
    assert all(item["titleLines"] == ["小米牛逼！"] for item in job["coverDraft"]["variants"])
    for item in job["coverDraft"]["variants"]:
        with Image.open(work / str(item["artifactFile"])).convert("RGB") as cover_image:
            title_region = cover_image.crop((
                0, 0, round(cover_image.width * .82), round(cover_image.height * .48),
            ))
            bright_neutral_pixels = sum(
                1 for red, green, blue in title_region.getdata()
                if red > 205 and green > 205 and blue > 205
            )
        # The synthetic source frames contain no neutral white pixels; these
        # pixels therefore prove the requested title was rasterized, not just
        # copied into variant metadata.
        assert bright_neutral_pixels > 100

    selected = job["coverDraft"]["variants"][1]
    invalid = {**selected, "variantId": "cover_variant_wrong_time", "sourceTime": 23.0}
    job["coverDraft"]["variants"].append(invalid)
    with pytest.raises(ValueError, match="不是指定的 12.0 秒附近"):
        main.validate_agent_action_resolution(
            workspace, {"tool": "review_cover_variants"}, {
                "context": {"jobId": job_id},
                "selection": {
                    "kind": "cover_variant", "variantIds": [invalid["variantId"]],
                    "contentHash": invalid["contentHash"],
                },
            },
        )
    job["coverDraft"]["variants"].pop()
    verified = main.validate_agent_action_resolution(
        workspace, {"tool": "review_cover_variants"}, {
            "context": {"jobId": job_id},
            "selection": {
                "kind": "cover_variant", "variantIds": [selected["variantId"]],
                "contentHash": selected["contentHash"],
            },
        },
    )
    assert verified["verifiedJobRevision"] == 1
    assert job["coverDraft"]["selectedVariantId"] == selected["variantId"]

    # A cover-only confirmation must remain independent from video export.
    # This mirrors an existing edit session whose source subtitles have not
    # yet been acknowledged: saving the cover is still valid and must not
    # trigger run_agent_final_output (which would correctly block on that
    # unrelated export precondition).
    job["activeEditSessionId"] = "edit_cover_only"
    job["editSessions"] = [{
        "id": "edit_cover_only", "revision": 3,
        "renderedVersionId": None,
        "subtitleEnabled": True,
        "subtitleDraftId": "subtitle_unacknowledged",
    }]

    def unexpected_render(*_args: Any, **_kwargs: Any) -> Any:
        raise AssertionError("confirm_cover must not start a video render")

    monkeypatch.setattr(main, "submit_render_task", unexpected_render)
    confirmed = main.dispatch_agent_tool(workspace, "confirm_cover", {})["artifact"]
    assert confirmed["kind"] == "current_cover"
    assert job["currentCoverVersionId"] == "cover_v001"
    assert len(job["coverVersions"]) == 1
    assert job["coverTimelineDraft"]["schemaVersion"] == "cover-timeline-draft-v1"
    assert len(job["coverTimelineDraft"]["variants"]) == 3
    assert main.thumbnail_cache_path(job).is_file()
    assert output["coverVersionId"] == "cover_v001"
    assert (outputs / "final-cover.jpg").is_file()
    assert confirmed["boundOutputs"][0]["filename"] == "final.mp4"
    assert job["coverIntroDraft"]["schemaVersion"] == "cover-intro-timeline-v1"
    assert job["coverIntroDraft"]["duration"] == 1.0
    assert job["messages"][-1]["kind"] == "result"
    assert job["messages"][-1]["text"] == "封面已保存，并关联到 1 条当前成片；视频画面未改动"


def test_review_render_gets_an_automatic_cover_without_user_selection(
    tmp_path: Path, monkeypatch: Any,
) -> None:
    from app import main

    job_id = "job_auto_review_cover"
    work = tmp_path / "work"
    outputs = tmp_path / "outputs"
    source = tmp_path / "source.mp4"
    preview = work / "review.mp4"
    work.mkdir()
    outputs.mkdir()
    source.write_bytes(b"source")
    preview.write_bytes(b"preview")
    session = {
        "id": "edit_review", "revision": 2, "previewPath": str(preview),
        "duration": 8.0,
        "clips": [
            {"id": "clip_one", "sourceStart": 3.0, "sourceEnd": 7.0, "title": "主体展示"},
            {"id": "clip_two", "sourceStart": 12.0, "sourceEnd": 16.0, "title": "结果画面"},
        ],
    }
    job = {
        "id": job_id, "revision": 1, "sourcePath": str(source),
        "filename": "source.mp4", "sourceHash": "source-hash",
        "workDirectory": str(work), "outputDirectory": str(outputs),
        "activeEditSessionId": session["id"], "editSessions": [session],
        "brief": {"goal": "整理主体展示画面", "coverRequested": False},
    }
    monkeypatch.setitem(main.jobs, job_id, job)
    monkeypatch.setattr(main, "save_job", lambda _job: None)
    monkeypatch.setattr(main, "probe_video", lambda *_args, **_kwargs: VideoInfo(20, 1280, 720, True))

    def extract(_source: Path, directory: Path, times: Any, **_kwargs: Any) -> list[SampledFrame]:
        directory.mkdir(parents=True, exist_ok=True)
        frames = []
        for index, second in enumerate(times):
            path = directory / f"auto-{index:03d}.jpg"
            image = Image.new("RGB", (640, 360), (35 + index * 13, 80, 125))
            ImageDraw.Draw(image).rectangle((90 + index * 9, 60, 410, 310), fill=(210, 125, 52))
            image.save(path, "JPEG")
            frames.append(SampledFrame(path=path, time=float(second)))
        return frames

    monkeypatch.setattr(main, "extract_frames_at_times", extract)

    cover = main.ensure_automatic_review_cover(job_id, session["id"], 2)

    assert cover is not None
    assert job["currentCoverVersionId"] == "cover_v001"
    assert job["coverDraft"]["selectionMode"] == "automatic_default"
    assert job["coverDraft"]["status"] == "approved"
    assert len(job["coverDraft"]["variants"]) == 3
    assert all(item["evidenceRefs"] for item in job["coverDraft"]["variants"])
    assert job["coverIntroDraft"]["enabled"] is False
    assert main.thumbnail_cache_path(job).is_file()
    assert main.ensure_automatic_review_cover(job_id, session["id"], 2)["id"] == "cover_v001"


def test_cover_candidates_from_accepted_timeline_never_sample_unselected_source(
    tmp_path: Path, monkeypatch: Any,
) -> None:
    from app import main

    job_id = "job_cover_timeline_scope"
    work = tmp_path / "work"
    outputs = tmp_path / "outputs"
    source = tmp_path / "source.mp4"
    work.mkdir()
    outputs.mkdir()
    source.write_bytes(b"video")
    job = {
        "id": job_id, "sourcePath": str(source), "filename": "source.mp4",
        "sourceHash": "current-task-source", "workDirectory": str(work),
        "outputDirectory": str(outputs), "activeEditSessionId": "edit_current",
        "contentSearch": {
            "id": "search_current",
            "candidates": [
                {"id": "match_car_1", "title": "汽车正面", "normalizedScore": .96},
                {"id": "match_car_2", "title": "汽车侧面", "normalizedScore": .92},
            ],
        },
        "editSessions": [{
            "id": "edit_current", "sourceSearchId": "search_current",
            "clips": [
                {"id": "clip_1", "sourceStart": 10.0, "sourceEnd": 18.0,
                 "title": "汽车正面", "sourceRef": {"kind": "content_match", "id": "match_car_1"}},
                {"id": "clip_2", "sourceStart": 70.0, "sourceEnd": 76.0,
                 "title": "汽车侧面", "sourceRef": {"kind": "content_match", "id": "match_car_2"}},
            ],
        }],
        "outputVersions": [], "outputs": [],
    }
    monkeypatch.setitem(main.jobs, job_id, job)
    monkeypatch.setattr(main, "save_job", lambda _job: None)
    monkeypatch.setattr(main, "probe_video", lambda *_args, **_kwargs: VideoInfo(120, 1280, 720, True))
    sampled_times: list[float] = []

    def extract(_source: Path, directory: Path, times: Any, **_kwargs: Any) -> list[SampledFrame]:
        directory.mkdir(parents=True, exist_ok=True)
        frames: list[SampledFrame] = []
        for index, second in enumerate(times):
            sampled_times.append(float(second))
            path = directory / f"frame-{index}.jpg"
            Image.new("RGB", (640, 360), (30 + index * 20, 80, 130)).save(path, "JPEG")
            frames.append(SampledFrame(path=path, time=float(second)))
        return frames

    monkeypatch.setattr(main, "extract_frames_at_times", extract)
    operation = main.dispatch_agent_tool(
        {"id": "ws", "jobId": job_id, "executionMode": "autonomous_review"},
        "propose_cover_candidates",
        {"sourceScope": "accepted_cut", "candidateBudget": 8,
         "aspectRatios": ["16:9"], "focus": "汽车"},
    )
    artifact = operation["future"].result(timeout=5)["artifact"]

    assert artifact["source"]["kind"] == "accepted_timeline"
    assert artifact["source"]["editSessionId"] == "edit_current"
    assert sampled_times
    assert all(10.0 <= value <= 18.0 or 70.0 <= value <= 76.0 for value in sampled_times)
    assert all(item["evidenceRefs"] for item in job["coverDraft"]["candidates"])
