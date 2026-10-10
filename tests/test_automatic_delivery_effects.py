from pathlib import Path
from types import SimpleNamespace
import shutil
import subprocess

import pytest

from app.automatic_delivery_effects import apply_effects, delivery_effects
from app.media import probe_video


def test_effects_are_limited_to_requested_local_operations():
    assert delivery_effects({"profile": "highlight", "brief": {}}) == {}
    assert delivery_effects({"profile": "audio-polish", "brief": {}})["audio"]["noiseReduction"] is False
    effects = delivery_effects({"profile": "local-motion", "goal": "新品", "brief": {"targetSeconds": 200}})
    assert effects["motion"]["duration"] == 8


def test_optional_visual_encoder_can_be_loaded_without_network(monkeypatch):
    import sys
    from unittest.mock import Mock
    from app import recognition_models
    processor, model = Mock(), Mock()
    monkeypatch.setitem(sys.modules, "transformers", SimpleNamespace(AutoProcessor=processor, AutoModel=model))
    monkeypatch.setattr(recognition_models, "_torch_device", lambda _: "cpu")
    monkeypatch.setattr(recognition_models, "_models", {})
    recognition_models.SiglipEncoder("optional-local", local_files_only=True)
    assert processor.from_pretrained.call_args.kwargs["local_files_only"] is True
    assert model.from_pretrained.call_args.kwargs["local_files_only"] is True


@pytest.fixture
def media(tmp_path):
    ffmpeg = "/usr/bin/ffmpeg" if Path("/usr/bin/ffmpeg").is_file() else shutil.which("ffmpeg")
    ffprobe = "/usr/bin/ffprobe" if Path("/usr/bin/ffprobe").is_file() else shutil.which("ffprobe")
    if not ffmpeg or not ffprobe:
        pytest.skip("FFmpeg not installed")
    source = tmp_path / "source.mp4"
    subprocess.run([ffmpeg, "-v", "error", "-y", "-f", "lavfi", "-i", "testsrc2=size=320x180:rate=24",
                    "-f", "lavfi", "-i", "sine=frequency=440:sample_rate=48000", "-t", "1",
                    "-c:v", "libx264", "-threads", "1", "-c:a", "aac", str(source)], check=True, timeout=30)
    return SimpleNamespace(settings=SimpleNamespace(ffmpeg=ffmpeg, ffprobe=ffprobe)), source


def test_real_audio_optimization_keeps_the_video_stream(media, tmp_path):
    runtime, source = media
    target = tmp_path / "audio.mp4"
    result = apply_effects(runtime, source, target, {"audio": {"noiseReduction": True, "voiceFirst": True}}, tmp_path, lambda: None)
    assert result["hasAudio"]
    assert abs(result["duration"] - probe_video(source, runtime.settings.ffprobe).duration) < .1
    def video_hash(path):
        return subprocess.run([runtime.settings.ffmpeg, "-v", "error", "-i", str(path), "-map", "0:v:0", "-c", "copy", "-f", "hash", "-"], capture_output=True, check=True, timeout=30).stdout
    assert video_hash(source) == video_hash(target)


def test_real_relative_volume_adjustment_does_not_normalize_back(media, tmp_path):
    import re
    runtime, source = media
    target = tmp_path / "quieter.mp4"
    apply_effects(runtime, source, target, {"audio": {"gainDb": -6, "normalizeLoudness": False}}, tmp_path, lambda: None)
    def level(path):
        result = subprocess.run([runtime.settings.ffmpeg, "-hide_banner", "-i", str(path),
                                 "-af", "volumedetect", "-vn", "-f", "null", "-"],
                                capture_output=True, text=True, check=True, timeout=30)
        return float(re.search(r"mean_volume:\s*(-?[\d.]+) dB", result.stderr)[1])
    assert level(target) - level(source) == pytest.approx(-6, abs=.3)


@pytest.mark.parametrize("intro", [False, True])
def test_real_chinese_motion_can_be_delivered_alone_or_as_intro(media, tmp_path, intro):
    runtime, source = media
    target = tmp_path / "motion.mp4"
    motion = {"title": "新品发布", "subtitle": "本地中文渲染", "aspect": "16:9", "duration": .5, "intro": intro}
    result = apply_effects(runtime, source if intro else None, target, {"motion": motion}, tmp_path / "work", lambda: None)
    assert abs(result["duration"] - (1.5 if intro else .5)) < .15
    assert result["hasAudio"] == intro
    assert result["motionGraphics"]["title"] == "新品发布"
    if intro:
        assert result["motionIntro"]["introDuration"] == pytest.approx(.5, abs=.1)
    subprocess.run([runtime.settings.ffmpeg, "-v", "error", "-xerror", "-i", str(target), "-f", "null", "-"], check=True, timeout=30)
