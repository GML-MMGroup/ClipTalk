from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace

from app.active_speaker import (
    _talknet_progress_snapshot,
    active_speaker_runtime,
    calibrate_diarized_speaker,
    run_talknet_active_speaker,
    run_talknet_active_speakers,
)


def settings_for(tmp_path: Path, worker: Path) -> SimpleNamespace:
    checkpoint = tmp_path / "talknet.model"
    checkpoint.write_bytes(b"checkpoint")
    repository = tmp_path / "TalkNet-ASD"
    repository.mkdir()
    (repository / "demoTalkNet.py").write_text("# test marker\n", encoding="utf-8")
    return SimpleNamespace(
        active_speaker_mode="shadow",
        talknet_worker_python=sys.executable,
        talknet_worker_script=str(worker),
        talknet_repository=str(repository),
        talknet_checkpoint=str(checkpoint),
        talknet_device="cpu",
        talknet_timeout_seconds=10,
    )


def test_talknet_worker_protocol_is_grounded_and_cached(tmp_path: Path) -> None:
    worker = tmp_path / "worker.py"
    worker.write_text(
        """import argparse, json, sys
if '--healthcheck' in sys.argv: raise SystemExit(0)
p=argparse.ArgumentParser(); p.add_argument('--request'); p.add_argument('--response'); a=p.parse_args()
r=json.load(open(a.request, encoding='utf-8'))
assert r['talknetRepository'].endswith('TalkNet-ASD')
json.dump({'protocolVersion':r['protocolVersion'],'modelVersion':'test-1','matches':[{'start':1.0,'end':2.0,'score':0.91,'evidenceTimes':[1.2,1.8],'trackIds':['track_1']},{'start':99,'end':100,'score':1.0}]},open(a.response,'w',encoding='utf-8'))
""",
        encoding="utf-8",
    )
    settings = settings_for(tmp_path, worker)
    assert active_speaker_runtime(settings)["status"] == "ready"
    kwargs = dict(
        source=tmp_path / "source.mp4", work_directory=tmp_path / "work", source_hash="hash",
        person={"id": "person_1", "representativeTime": 1.2, "representativeBox": [0, 0, 10, 10]},
        person_tracks=[{"id": "track_1", "personId": "person_1", "start": 1.2, "box": [0, 0, 10, 10]}],
        speech_units=[{"id": "speech_1", "start": .5, "end": 2.5}],
        scope_start=0.0, scope_end=3.0, settings=settings,
    )
    progress_events: list[dict[str, object]] = []
    first = run_talknet_active_speaker(**kwargs, progress=progress_events.append)
    assert first["matches"] == [{
        "start": 1.0, "end": 2.0, "score": .91,
        "evidenceTimes": [1.2, 1.8], "trackIds": ["track_1"],
    }]
    assert first["cacheHit"] is False
    assert first["coverageComplete"] is True
    assert [event["phase"] for event in progress_events] == ["starting", "complete"]
    second = run_talknet_active_speaker(**kwargs)
    assert second["cacheHit"] is True
    assert second["coverageComplete"] is True


def test_talknet_progress_uses_real_pipeline_artifacts(tmp_path: Path) -> None:
    root = tmp_path / "run"
    input_root = root / "talknet-official" / "input"
    frames = input_root / "pyframes"
    work = input_root / "pywork"
    crops = input_root / "pycrop"
    for directory in (frames, work, crops):
        directory.mkdir(parents=True)
    response = root / "response.json"
    started = 0.0

    assert _talknet_progress_snapshot(root, response, 2, started_wall_time=started) == {
        "phase": "frame_extraction", "fraction": 0.0,
        "completed": 0, "total": 2, "unit": "帧",
    }
    (frames / "000001.jpg").write_bytes(b"frame")
    extracting = _talknet_progress_snapshot(root, response, 2, started_wall_time=started)
    assert extracting["phase"] == "frame_extraction"
    assert extracting["fraction"] == .26
    (frames / "000002.jpg").write_bytes(b"frame")
    assert _talknet_progress_snapshot(root, response, 2, started_wall_time=started)["phase"] == "scene_detection"
    (work / "scene.pckl").write_bytes(b"scene")
    assert _talknet_progress_snapshot(root, response, 2, started_wall_time=started)["phase"] == "face_detection"
    (work / "faces.pckl").write_bytes(b"faces")
    (crops / "00000.avi").write_bytes(b"crop")
    tracking = _talknet_progress_snapshot(root, response, 2, started_wall_time=started)
    assert tracking["phase"] == "track_building"
    assert tracking["completed"] == 1
    (work / "tracks.pckl").write_bytes(b"tracks")
    assert _talknet_progress_snapshot(root, response, 2, started_wall_time=started)["phase"] == "av_scoring"
    (work / "scores.pckl").write_bytes(b"scores")
    assert _talknet_progress_snapshot(root, response, 2, started_wall_time=started)["phase"] == "finalizing"
    response.write_text("{}", encoding="utf-8")
    assert _talknet_progress_snapshot(root, response, 2, started_wall_time=started)["phase"] == "complete"


def test_talknet_batch_submits_all_people_in_one_worker_run(tmp_path: Path) -> None:
    worker = tmp_path / "multi-worker.py"
    counter = tmp_path / "runs.txt"
    worker.write_text(
        f"""import argparse, json, sys
if '--healthcheck' in sys.argv: raise SystemExit(0)
p=argparse.ArgumentParser(); p.add_argument('--request'); p.add_argument('--response'); a=p.parse_args()
r=json.load(open(a.request, encoding='utf-8'))
open({str(counter)!r},'a',encoding='utf-8').write('run\\n')
assert [item['id'] for item in r['targets']] == ['person_1','person_2']
result={{item['id']:{{'matches':[{{'start':1,'end':2,'score':.9,'trackIds':[item['targetTracks'][0]['id']]}}], 'presenceMatches':[{{'start':0,'end':3,'score':.8,'officialTrackIds':['official_'+item['id']]}}]}} for item in r['targets']}}
json.dump({{'protocolVersion':r['protocolVersion'],'modelVersion':'multi-test','resultsByPerson':result}},open(a.response,'w',encoding='utf-8'))
""",
        encoding="utf-8",
    )
    settings = settings_for(tmp_path, worker)
    source = tmp_path / "source.mp4"
    source.write_bytes(b"video")
    result = run_talknet_active_speakers(
        source=source, work_directory=tmp_path / "work", source_hash="multi-hash",
        persons=[{"id": "person_1"}, {"id": "person_2"}],
        person_tracks=[
            {"id": "track_1", "personId": "person_1", "start": 1, "box": [0, 0, 10, 10]},
            {"id": "track_2", "personId": "person_2", "start": 1, "box": [20, 0, 30, 10]},
        ],
        speech_units=[], scope_start=0, scope_end=3, settings=settings,
    )
    assert counter.read_text(encoding="utf-8").splitlines() == ["run"]
    assert set(result["resultsByPerson"]) == {"person_1", "person_2"}
    assert result["resultsByPerson"]["person_2"]["presenceMatches"][0]["officialTrackIds"] == ["official_person_2"]


def test_talknet_is_degraded_when_isolated_runtime_is_not_configured(tmp_path: Path) -> None:
    settings = SimpleNamespace(
        active_speaker_mode="shadow", talknet_worker_python="", talknet_worker_script="",
        talknet_repository="", talknet_checkpoint="", talknet_device="cuda:0",
    )
    assert active_speaker_runtime(settings)["status"] == "degraded"


def test_talknet_is_degraded_when_worker_healthcheck_fails(tmp_path: Path) -> None:
    worker = tmp_path / "broken-worker.py"
    worker.write_text(
        "import sys\nraise SystemExit(9 if '--healthcheck' in sys.argv else 0)\n",
        encoding="utf-8",
    )
    runtime = active_speaker_runtime(settings_for(tmp_path, worker))
    assert runtime["status"] == "degraded"
    assert runtime["coverageComplete"] is False
    assert "healthcheck" in runtime["reason"]


def test_repeated_asd_intervals_calibrate_a_single_diarized_speaker() -> None:
    result = calibrate_diarized_speaker(
        [
            {"start": 10.0, "end": 14.0},
            {"start": 30.0, "end": 34.0},
            {"start": 50.0, "end": 52.0},
        ],
        [
            {"start": 9.5, "end": 14.2, "speakers": ["Speaker 1"]},
            {"start": 29.8, "end": 34.1, "speakers": ["Speaker 1"]},
            {"start": 49.8, "end": 52.2, "speakers": ["Speaker 1"]},
            {"start": 20.0, "end": 25.0, "speakers": ["Speaker 2"]},
        ],
    )

    assert result["speaker"] == "Speaker 1"
    assert result["confidence"] >= .9
    assert result["evidenceIntervals"] == 3


def test_one_asd_interval_is_not_enough_for_global_speaker_calibration() -> None:
    result = calibrate_diarized_speaker(
        [{"start": 10.0, "end": 14.0}],
        [{"start": 9.5, "end": 14.2, "speakers": ["Speaker 1"]}],
    )

    assert result["speaker"] is None


def test_single_diarization_label_never_becomes_a_global_person_binding() -> None:
    result = calibrate_diarized_speaker(
        [
            {"start": 10.0, "end": 14.0},
            {"start": 30.0, "end": 34.0},
            {"start": 50.0, "end": 54.0},
        ],
        [
            {"start": 0.0, "end": 20.0, "speakers": ["Speaker 1"]},
            {"start": 20.0, "end": 40.0, "speakers": ["Speaker 1"]},
            {"start": 40.0, "end": 60.0, "speakers": ["Speaker 1"]},
        ],
    )

    assert result["speaker"] is None
    assert result["reason"] == "insufficient_diarization_diversity"
    assert result["availableSpeakers"] == ["Speaker 1"]
