from __future__ import annotations

import base64
import os
import wave
from pathlib import Path

import numpy as np
import pytest

from app.voiceprint import (
    VoiceProfileStore,
    aggregate_embeddings,
    classify_voice_match,
    cosine_similarity,
    merge_target_speech_segments,
    split_wav_exemplars,
)


def vector(index: int, *, blend: float = 0.0) -> list[float]:
    value = np.zeros(192, dtype=np.float32)
    value[index] = 1.0
    if blend:
        value[(index + 1) % 192] = blend
    value /= np.linalg.norm(value)
    return value.tolist()


def encryption_key() -> str:
    return base64.urlsafe_b64encode(os.urandom(32)).decode("ascii")


def test_store_encrypts_all_profile_content_and_rename_is_side_effect_free(tmp_path: Path) -> None:
    path = tmp_path / "profiles.enc"
    store = VoiceProfileStore(path, encryption_key())
    aggregate = aggregate_embeddings([vector(2), vector(2, blend=.03)])
    created = store.save_enrollment(label="目标人物", aggregate=aggregate, speech_seconds=12.5)

    raw = path.read_bytes()
    assert "目标人物".encode() not in raw
    assert b"centroid" not in raw
    assert "centroid" not in store.get(created["id"], public=True)

    before = store.get(created["id"])
    renamed = store.rename(created["id"], "采访对象")
    after = store.get(created["id"])
    assert renamed["label"] == "采访对象"
    assert after["centroid"] == before["centroid"]
    assert after["exemplars"] == before["exemplars"]
    assert after["speechSeconds"] == before["speechSeconds"]


def test_store_rejects_missing_or_wrong_keys(tmp_path: Path) -> None:
    disabled = VoiceProfileStore(tmp_path / "profiles.enc", "")
    assert disabled.available is False
    with pytest.raises(RuntimeError):
        disabled.list()

    path = tmp_path / "encrypted.enc"
    first = VoiceProfileStore(path, encryption_key())
    first.save_enrollment(label="A", aggregate=aggregate_embeddings([vector(0)]), speech_seconds=6)
    wrong = VoiceProfileStore(path, encryption_key())
    with pytest.raises(Exception):
        wrong.list()


def test_match_uses_score_and_competing_profile_margin() -> None:
    assert classify_voice_match(.45, competing_score=.34)["decision"] == "matched"
    assert classify_voice_match(.45, competing_score=.43)["decision"] == "review"
    assert classify_voice_match(.34, competing_score=.1)["decision"] == "review"
    assert classify_voice_match(.2)["decision"] == "rejected"
    assert cosine_similarity(vector(5), vector(5, blend=.01)) > .99


def test_merge_speaker_turns_does_not_cross_another_speaker() -> None:
    segments = [
        {"start": 0, "end": 2, "speaker": "Speaker 0", "text": "第一句"},
        {"start": 2.2, "end": 2.5, "speaker": "Speaker 1", "text": "插话"},
        {"start": 2.6, "end": 4, "speaker": "Speaker 0", "text": "第二句"},
        {"start": 4.3, "end": 5, "speaker": "Speaker 0", "text": "第三句"},
    ]
    merged = merge_target_speech_segments(segments, "Speaker 0")
    assert len(merged) == 2
    assert merged[0]["text"] == "第一句"
    assert merged[1]["text"] == "第二句第三句"


def test_merge_speaker_turns_absorbs_a_natural_pause() -> None:
    merged = merge_target_speech_segments([
        {"start": 0, "end": 2, "speaker": "Speaker 0", "text": "我先想一下"},
        {"start": 3.4, "end": 5, "speaker": "Speaker 0", "text": "再继续回答"},
    ], "Speaker 0")
    assert len(merged) == 1
    assert merged[0]["start"] == 0
    assert merged[0]["end"] == pytest.approx(5.2)
    assert merged[0]["sourceSegmentCount"] == 2
    assert merged[0]["bridgedSilenceSeconds"] == pytest.approx(1.4)


def test_merge_speaker_turns_keeps_a_two_second_natural_pause_but_not_an_interruption() -> None:
    uninterrupted = merge_target_speech_segments([
        {"start": 0, "end": 2, "speaker": "Speaker 0", "text": "第一句。"},
        {"start": 4.1, "end": 6, "speaker": "Speaker 0", "text": "第二句。"},
    ], "Speaker 0")
    assert len(uninterrupted) == 1
    assert uninterrupted[0]["bridgedSilenceSeconds"] == pytest.approx(2.1)

    interrupted = merge_target_speech_segments([
        {"start": 0, "end": 2, "speaker": "Speaker 0", "text": "第一句。"},
        {"start": 2.5, "end": 3.0, "speaker": "Speaker 1", "text": "插话。"},
        {"start": 4.1, "end": 6, "speaker": "Speaker 0", "text": "第二句。"},
    ], "Speaker 0")
    assert len(interrupted) == 2


def test_split_wav_keeps_tail_with_previous_chunk(tmp_path: Path) -> None:
    source = tmp_path / "source.wav"
    samples = (np.sin(np.arange(13 * 16000) * .03) * 1000).astype(np.int16)
    with wave.open(str(source), "wb") as writer:
        writer.setnchannels(1)
        writer.setsampwidth(2)
        writer.setframerate(16000)
        writer.writeframes(samples.tobytes())
    chunks = split_wav_exemplars(source, tmp_path / "chunks", target_seconds=6)
    assert len(chunks) == 2
    with wave.open(str(chunks[-1]), "rb") as reader:
        assert reader.getnframes() / reader.getframerate() == pytest.approx(7.0, abs=.01)
