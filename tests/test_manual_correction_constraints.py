from __future__ import annotations

from app.main import _apply_voice_correction_constraints, _record_voice_correction_constraints


def test_voice_correction_constraints_survive_changed_model_speaker_ids() -> None:
    job: dict = {}
    _record_voice_correction_constraints(job, [{
        "start": 2.0, "end": 4.0, "speaker": "User Speaker 1",
    }])
    corrected, count = _apply_voice_correction_constraints(
        [{"start": 1.0, "end": 5.0, "speaker": "Speaker 7", "text": "重新识别后的整段发言"}],
        job["voiceCorrectionConstraints"],
    )
    assert count == 1
    assert [(item["start"], item["end"]) for item in corrected] == [(1.0, 2.0), (2.0, 4.0), (4.0, 5.0)]
    assert corrected[1]["speaker"] == "User Speaker 1"
    assert corrected[1]["manualCorrection"] is True
    assert corrected[0]["speaker"] == "Speaker 7"


def test_new_voice_constraint_replaces_same_temporal_correction() -> None:
    job: dict = {}
    _record_voice_correction_constraints(job, [{"start": 2, "end": 4, "speaker": "old"}])
    _record_voice_correction_constraints(job, [{"start": 2, "end": 4, "speaker": "new"}])
    assert len(job["voiceCorrectionConstraints"]) == 1
    assert job["voiceCorrectionConstraints"][0]["targetSpeakerRef"] == "new"
