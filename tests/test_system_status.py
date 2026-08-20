from __future__ import annotations

from types import SimpleNamespace

from app.system_status import build_health_snapshot, build_runtime_metrics


def test_health_snapshot_preserves_current_and_legacy_fields(tmp_path) -> None:
    ffmpeg = tmp_path / "ffmpeg"
    ffprobe = tmp_path / "ffprobe"
    ffmpeg.write_text("")
    ffprobe.write_text("")
    settings = SimpleNamespace(
        speech_engine="sensevoice", whisper_model="", sensevoice_model="model",
        sensevoice_diarization=True, ffmpeg=str(ffmpeg), ffprobe=str(ffprobe),
        data_root=tmp_path,
    )
    snapshot = build_health_snapshot(
        settings=settings,
        speech_state={"status": "ready", "device": "cpu"},
        active_vision={
            "apiKey": "secret", "model": "vision-model", "baseUrl": "https://example.test",
            "provider": "openai", "thinkingType": "", "responseFormat": "json_object",
        },
        vision_provider_name="OpenAI",
        active_llm={
            "apiKey": "secret", "model": "text-model", "baseUrl": "https://example.test",
            "provider": "openai", "providerLabel": "OpenAI", "mode": "reuse_vision",
            "protocol": "openai",
        },
        recognition_state={"schemaVersion": 4},
    )
    assert snapshot["visionConfigured"] is True
    assert snapshot["arkConfigured"] is True
    assert snapshot["llmUsesVision"] is True
    assert snapshot["contentRecognition"] == {"schemaVersion": 4}
    assert snapshot["ffmpeg"] is True
    assert "apiKey" not in snapshot


def test_runtime_metrics_counts_statuses_without_job_payloads() -> None:
    metrics = build_runtime_metrics(
        job_statuses=["running", "completed", "running", ""],
        http_metrics={"requests": 4},
        analysis_queue={"queued": 1},
        render_queue={"running": 1},
        analysis_workers=3,
    )
    assert metrics["jobs"] == {"completed": 1, "running": 2, "unknown": 1}
    assert metrics["workers"] == {"analysis": 3, "render": 2, "preview": 1}
