from __future__ import annotations

import json
import os
import signal
import subprocess
import time
import uuid
from pathlib import Path
from typing import Any, Callable

import numpy as np

from .media import extract_frames_at_times
from .recognition import (
    build_shots,
    cluster_person_tracks,
    conservative_face_speaker_links,
    dense_person_sample_times,
    link_body_tracklets,
    merge_ocr_detections,
    normalize_recognition_profile,
    shot_sample_times,
    vector_recall,
    write_embedding_matrix,
)


ProgressCallback = Callable[[float, str], None]
RECOGNITION_MODALITIES = frozenset({"speech", "visual", "ocr", "audio", "person"})


def recognition_work_plan(
    requested_modalities: set[str] | list[str] | tuple[str, ...] | None,
    *, recognition_profile: str,
) -> dict[str, Any]:
    """Resolve the expensive recognition work required for one query.

    ``full`` controls density and optional audio embeddings. The caller
    expands a new full request before subtracting cached modalities, so this
    function preserves the supplied set and can build only missing work.
    """
    requested = {
        str(value).strip().lower() for value in (requested_modalities or RECOGNITION_MODALITIES)
        if str(value).strip().lower() in RECOGNITION_MODALITIES
    }
    explicit_full = str(recognition_profile or "auto").strip().lower() == "full"
    # The caller expands an explicit ``full`` request before comparing it with
    # cached coverage. Keeping the supplied set intact here lets a full-profile
    # follow-up build only modalities that are still missing.
    frame_modalities = requested & {"visual", "ocr", "person"}
    return {
        "requested": requested,
        "explicitFull": explicit_full,
        "needsFrames": bool(frame_modalities),
        "needsOcr": "ocr" in requested,
        "needsPersons": "person" in requested,
        "needsVisualEmbeddings": "visual" in requested,
        "needsAudio": "audio" in requested,
        "needsAudioEmbeddings": explicit_full and "audio" in requested,
    }


def _spread(values: list[Any], maximum: int) -> list[Any]:
    if len(values) <= maximum:
        return values
    stride = len(values) / max(1, maximum)
    return [values[min(len(values) - 1, int(index * stride))] for index in range(maximum)]


def _audio_event_units(transcript_segments: list[dict[str, Any]]) -> list[dict[str, Any]]:
    units: list[dict[str, Any]] = []
    for segment in transcript_segments:
        labels = list(dict.fromkeys([
            *[str(value) for value in segment.get("audioEvents") or [] if str(value)],
            *([str(segment.get("emotion"))] if segment.get("emotion") not in (None, "", "neutral", "unknown") else []),
        ]))
        if not labels:
            continue
        units.append({
            "id": f"audio_event_{len(units):05d}", "modality": "audio",
            "start": round(float(segment.get("start") or 0), 3),
            "end": round(float(segment.get("end") or segment.get("start") or 0), 3),
            "labels": labels, "text": " ".join(labels), "confidence": .72,
            "source": "sensevoice",
        })
    return units


def _extract_pcm(
    source: Path, target: Path, *, ffmpeg: str, sample_rate: int = 48000,
    start: float = 0.0, duration: float | None = None,
) -> None:
    command = [ffmpeg, "-v", "error", "-y", "-ss", f"{max(0.0, start):.3f}", "-i", str(source)]
    if duration is not None:
        command.extend(["-t", f"{max(.01, duration):.3f}"])
    command.extend([
        "-vn", "-ac", "1", "-ar", str(sample_rate), "-f", "f32le", str(target),
    ])
    result = subprocess.run(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=False)
    if result.returncode:
        raise RuntimeError(result.stderr.decode("utf-8", errors="replace")[-1200:] or "ffmpeg audio extraction failed")


def _clap_audio_index(
    source: Path, root: Path, *, duration: float, ffmpeg: str, model_id: str,
    model_cache: Path, device: str, progress: ProgressCallback,
    scope_start: float = 0.0, scope_end: float | None = None,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    from .recognition_models import ClapEncoder

    sample_rate = 48000
    window_seconds = 5.0
    stride_seconds = 2.5
    units: list[dict[str, Any]] = []
    first_time = max(0.0, min(duration, float(scope_start)))
    last_time = max(first_time, min(duration, float(scope_end if scope_end is not None else duration)))
    scoped_duration = max(.01, last_time - first_time)
    starts = np.arange(0.0, scoped_duration, stride_seconds, dtype=np.float64)
    raw_path = root / "audio-f32le.raw"
    _extract_pcm(
        source, raw_path, ffmpeg=ffmpeg, sample_rate=sample_rate,
        start=first_time, duration=scoped_duration,
    )
    byte_count = raw_path.stat().st_size
    samples = byte_count // 4
    signal = np.memmap(raw_path, mode="r", dtype="<f4", shape=(samples,))
    encoder = ClapEncoder(model_id, device=device, cache_dir=model_cache)
    rows: list[np.ndarray] = []
    try:
        batch_size = 8
        for position in range(0, len(starts), batch_size):
            waveforms: list[np.ndarray] = []
            for start in starts[position:position + batch_size]:
                first = min(samples, max(0, int(start * sample_rate)))
                last = min(samples, first + int(window_seconds * sample_rate))
                waveform = np.asarray(signal[first:last], dtype=np.float32)
                if waveform.size < int(window_seconds * sample_rate):
                    waveform = np.pad(waveform, (0, int(window_seconds * sample_rate) - waveform.size))
                waveforms.append(waveform)
                absolute_start = first_time + float(start)
                end = min(last_time, absolute_start + window_seconds)
                units.append({
                    "id": f"audio_{len(units):05d}", "modality": "audio",
                    "start": round(absolute_start, 3), "end": round(end, 3),
                    "labels": [], "text": "音频窗口", "confidence": .5, "source": "clap",
                })
            rows.append(encoder.encode_audio(waveforms, sampling_rate=sample_rate, batch_size=batch_size))
            progress((position + len(waveforms)) / max(1, len(starts)), "正在建立声音语义索引")
        matrix = np.concatenate(rows, axis=0) if rows else np.empty((0, 0), dtype=np.float32)
        manifest = write_embedding_matrix(root / "audio-embeddings.npy", [unit["id"] for unit in units], matrix, model=model_id)
        return units, manifest
    finally:
        del signal
        raw_path.unlink(missing_ok=True)


def enrich_multimodal_index(
    *, source: Path, root: Path, duration: float, scene_cuts: list[float],
    transcript_segments: list[dict[str, Any]], speech_units: list[dict[str, Any]],
    settings: Any, recognition_profile: str, ffmpeg: str,
    requested_modalities: set[str] | list[str] | tuple[str, ...] | None = None,
    speech_analysis_complete: bool = False,
    scope_start: float = 0.0, scope_end: float | None = None,
    progress: ProgressCallback | None = None, cancelled: Callable[[], bool] | None = None,
    algorithm_version: str = "editing-algorithm-v1",
) -> dict[str, Any]:
    """Build optional v4 evidence without making an unavailable model fatal."""
    report = progress or (lambda _value, _detail: None)
    is_cancelled = cancelled or (lambda: False)
    bounded_start = max(0.0, min(duration, float(scope_start)))
    bounded_end = max(bounded_start, min(duration, float(scope_end if scope_end is not None else duration)))
    shots = []
    for source_shot in build_shots(duration, scene_cuts):
        start = max(bounded_start, float(source_shot.get("start") or 0))
        end = min(bounded_end, float(source_shot.get("end") or 0))
        if end - start < .08:
            continue
        shot = dict(source_shot)
        shot.update({"id": f"shot_{len(shots):05d}", "start": round(start, 3), "end": round(end, 3), "duration": round(end - start, 3)})
        shots.append(shot)
    sample_times = shot_sample_times(shots, maximum_per_shot=6, global_limit=1200)
    profile = normalize_recognition_profile(recognition_profile, cuda_available=False)
    try:
        import torch

        cuda = bool(torch.cuda.is_available())
        profile = normalize_recognition_profile(recognition_profile, cuda_available=cuda)
    except Exception:
        cuda = False
    device = "cuda" if cuda else "cpu"
    effective = profile["effective"]
    work = recognition_work_plan(requested_modalities, recognition_profile=recognition_profile)
    requested = set(work["requested"])
    frame_limit = len(sample_times) if effective == "full" else min(300, len(sample_times))
    generic_times = _spread(sample_times, frame_limit) if work["needsFrames"] else []
    if effective == "full" and work["needsOcr"]:
        # Screen text can appear between representative shot frames. A dense
        # 2 FPS stream gives exhaustive searches a real coverage contract.
        generic_times = dense_person_sample_times(
            shots, start=bounded_start, end=bounded_end, interval=.5,
        )
    elif effective == "full" and work["needsVisualEmbeddings"]:
        # Keep the reusable visual index substantially denser than six frames
        # per long shot. Query-time VLM verification remains the final proof.
        generic_times = dense_person_sample_times(
            shots, start=bounded_start, end=bounded_end, interval=1.0,
        )
    person_times = dense_person_sample_times(
        shots, start=bounded_start, end=bounded_end,
        interval=.25 if algorithm_version == "editing-algorithm-v2" else .5,
    ) if work["needsPersons"] else []
    # Person recognition has an exhaustive coverage contract. Keep it on its
    # own dense frame stream so a person-only request does not inherit the
    # sparse visual/OCR probe budget, and so adding person retrieval does not
    # accidentally make every visual embedding task run at 2 FPS.
    selected_times = person_times if work["needsPersons"] and not (work["needsOcr"] or work["needsVisualEmbeddings"]) else generic_times
    person_only_frames = bool(
        work["needsPersons"]
        and not (work["needsOcr"] or work["needsVisualEmbeddings"])
    )

    def frame_progress_reporter(
        label: str, *, start: float, span: float,
    ) -> Callable[[int, int], None]:
        def report_progress(completed: int, total: int) -> None:
            fraction = max(0.0, min(1.0, completed / max(1, total)))
            report(
                start + span * fraction,
                f"{label}（{completed}/{total} 帧）",
            )

        return report_progress

    if selected_times:
        frame_label = (
            "人物识别 1/2 · 正在准备解码分析帧"
            if person_only_frames else "正在准备多模态采样帧"
        )
        report(
            .05,
            f"{frame_label} · 共 {len(selected_times)} 帧，首批完成后显示进度",
        )
    frames = (
        extract_frames_at_times(
            source,
            root / "recognition-frames",
            selected_times,
            ffmpeg=ffmpeg,
            progress_callback=frame_progress_reporter(
                "人物识别 1/2 · 正在解码分析帧"
                if person_only_frames else "正在抽取多模态采样帧",
                start=.05,
                span=.3 if person_only_frames else .14,
            ),
        )
        if selected_times else []
    )
    person_frames = frames
    if work["needsPersons"] and selected_times is not person_times:
        report(
            .2,
            f"人物识别 1/2 · 正在准备解码分析帧 · 共 {len(person_times)} 帧，首批完成后显示进度",
        )
        person_frames = extract_frames_at_times(
            source, root / "person-frames", person_times, ffmpeg=ffmpeg,
            progress_callback=frame_progress_reporter(
                "人物识别 1/2 · 正在解码分析帧", start=.2, span=.16,
            ),
        )
    if is_cancelled():
        raise RuntimeError("任务已取消")
    paths = [Path(frame.path) for frame in frames]
    times = [float(frame.time) for frame in frames]
    result: dict[str, Any] = {
        "shots": shots if work["needsFrames"] else [], "embeddingIndexes": {},
        "recognitionProfile": profile, "degradedReasons": [], "recognitionFrameCount": len(frames),
        "personSampling": {
            "intervalSeconds": (.25 if algorithm_version == "editing-algorithm-v2" else .5) if work["needsPersons"] else None,
            "requestedFrameCount": len(person_times),
            "extractedFrameCount": len(person_frames),
            "coverageMode": "continuous_sampled" if work["needsPersons"] else "not_requested",
        },
        "ocrSampling": {
            "intervalSeconds": .5 if work["needsOcr"] and effective == "full" else None,
            "requestedFrameCount": len(generic_times) if work["needsOcr"] else 0,
            "extractedFrameCount": len(frames) if work["needsOcr"] else 0,
            "coverageMode": (
                "continuous_sampled" if work["needsOcr"] and effective == "full"
                else "sampled" if work["needsOcr"] else "not_requested"
            ),
        },
        "recognitionRequestedModalities": sorted(requested),
        "recognitionAttemptedModalities": [],
        "recognitionCompletedModalities": [],
        "recognitionAvailableModalities": [],
    }

    if work["needsOcr"]:
        result["recognitionAttemptedModalities"].append("ocr")
        result["ocrUnits"] = []
        try:
            if not getattr(settings, "recognition_ocr_enabled", True):
                raise RuntimeError("OCR 已在服务配置中关闭")
            report(.2, "正在识别画面中的文字")
            from .recognition_models import PaddleOcrEngine

            detections = PaddleOcrEngine(
                device=device, cache_dir=settings.recognition_model_cache,
            ).recognize(paths, times)
            result["ocrUnits"] = merge_ocr_detections(detections)
            result["recognitionCompletedModalities"].append("ocr")
            result["recognitionAvailableModalities"].append("ocr")
        except Exception as error:
            result["degradedReasons"].append(f"ocr_unavailable:{str(error)[:160]}")

    if work["needsPersons"]:
        result["recognitionAttemptedModalities"].append("person")
        result.update({"personTracks": [], "persons": [], "faceSpeakerLinks": []})
        try:
            report(.38, "人物识别 2/2 · 正在初始化人物检测与身份关联模型")
            from .recognition_models import AnonymousBodyEngine, AnonymousFaceEngine

            face_engine = AnonymousFaceEngine(settings.recognition_yunet_model, settings.recognition_sface_model, device=device)
            use_body_pipeline = bool(
                algorithm_version == "editing-algorithm-v2"
                and Path(settings.recognition_yolox_model).is_file()
                and Path(settings.recognition_youtureid_model).is_file()
            )
            body_engine = AnonymousBodyEngine(
                settings.recognition_yolox_model, settings.recognition_youtureid_model, device=device,
            ) if use_body_pipeline else None
            tracks: list[dict[str, Any]] = []
            person_paths = [Path(frame.path) for frame in person_frames]
            person_times_actual = [float(frame.time) for frame in person_frames]
            person_scene_cuts = sorted(float(value) for value in scene_cuts or [])
            person_frame_total = len(person_paths)
            report_stride = max(1, person_frame_total // 50)
            for frame_position, (frame_path, time_value) in enumerate(
                zip(person_paths, person_times_actual), 1,
            ):
                if body_engine is None:
                    tracks.extend(face_engine.detect(frame_path, time_value=time_value))
                else:
                    bodies = body_engine.detect(frame_path, time_value=time_value)
                    # Face normally runs at 2 FPS. Always run it at shot
                    # boundaries as well: the first identity observation after
                    # an edit must not be assigned solely from a similarly
                    # positioned body box in a fixed-camera interview.
                    near_scene_cut = any(
                        abs(time_value - cut) <= .26 for cut in person_scene_cuts
                    )
                    faces = face_engine.detect(
                        frame_path, time_value=time_value,
                    ) if frame_position % 2 or near_scene_cut else []
                    for body in bodies:
                        body["identityStatus"] = "body_tracked"
                    for face in faces:
                        face_box = list(face.get("box") or [])
                        if len(face_box) < 4:
                            continue
                        center_x = (float(face_box[0]) + float(face_box[2])) / 2
                        center_y = (float(face_box[1]) + float(face_box[3])) / 2
                        containing = [body for body in bodies if (
                            float(body["box"][0]) <= center_x <= float(body["box"][2])
                            and float(body["box"][1]) <= center_y <= float(body["box"][3])
                        )]
                        if containing:
                            target = min(containing, key=lambda body: (
                                float(body["box"][2]) - float(body["box"][0])
                            ) * (float(body["box"][3]) - float(body["box"][1])))
                            target["identityStatus"] = "face_confirmed"
                            target["faceConfidence"] = float(face.get("confidence") or 0)
                            target["faceEmbedding"] = list(face.get("embedding") or [])
                    tracks.extend(bodies)
                if (
                    frame_position == 1
                    or frame_position == person_frame_total
                    or frame_position % report_stride == 0
                ):
                    report(
                        .38 + .14 * frame_position / max(1, person_frame_total),
                        f"人物识别 2/2 · 正在检测人物并关联轨迹（{frame_position}/{person_frame_total} 帧）",
                    )
            report(.53, "人物识别 2/2 · 正在合并同一人物的连续轨迹")
            if body_engine is not None:
                tracks = link_body_tracklets(tracks, scene_cuts=scene_cuts)
            result["personTracks"] = [{
                key: value for key, value in item.items() if key not in {"embedding", "faceEmbedding"}
            } for item in tracks]
            result["persons"] = cluster_person_tracks(
                tracks, scene_cuts=scene_cuts,
                similarity_threshold=.68 if body_engine is not None else .42,
                maximum_gap=.8 if body_engine is not None else 2.0,
                algorithm_version=algorithm_version,
            )
            person_for_track = {
                track_id: person["id"]
                for person in result["persons"] for track_id in person.get("trackIds") or []
            }
            for track in result["personTracks"]:
                track["modality"] = "person"
                track["personId"] = person_for_track.get(str(track.get("id") or ""))
                person = next((item for item in result["persons"] if item["id"] == track.get("personId")), None)
                track["personLabels"] = [person["label"]] if person else []
            result["faceSpeakerLinks"] = conservative_face_speaker_links(result["persons"], speech_units)
            result["recognitionCompletedModalities"].append("person")
            result["recognitionAvailableModalities"].append("person")
            result["personIdentityPipeline"] = (
                "yolox-youtureid-sface-anchor-v3" if body_engine is not None else "yunet-sface-fallback-v1"
            )
            if algorithm_version == "editing-algorithm-v2" and body_engine is None:
                result["degradedReasons"].append("person_body_models_unavailable_face_only_fallback")
            report(.54, f"人物识别完成 · {len(result['persons'])} 个人物簇")
        except Exception as error:
            result["degradedReasons"].append(f"anonymous_persons_unavailable:{str(error)[:160]}")

    if work["needsVisualEmbeddings"]:
        result["recognitionAttemptedModalities"].append("visual")
        result["embeddingVisualUnits"] = []
        try:
            report(.55, "正在建立画面语义索引")
            from .recognition_models import SiglipEncoder

            embedding_frames = frames if effective == "full" else _spread(frames, min(240, len(frames)))
            encoder = SiglipEncoder(settings.recognition_siglip_model, device=device, cache_dir=settings.recognition_model_cache)
            matrix = encoder.encode_images([Path(frame.path) for frame in embedding_frames], batch_size=16 if cuda else 4)
            frame_ids = [f"frame_{float(frame.time):010.3f}" for frame in embedding_frames]
            result["embeddingVisualUnits"] = [{
                "id": frame_id, "modality": "visual", "start": round(max(0.0, float(frame.time) - .5), 3),
                "end": round(min(duration, float(frame.time) + .5), 3), "title": "画面语义证据帧",
                "text": "画面语义证据帧", "evidenceTimes": [round(float(frame.time), 3)],
                "confidence": .5, "source": "siglip2",
            } for frame_id, frame in zip(frame_ids, embedding_frames)]
            manifest = write_embedding_matrix(root / "visual-embeddings.npy", frame_ids, matrix, model=settings.recognition_siglip_model)
            manifest["times"] = [round(float(frame.time), 3) for frame in embedding_frames]
            (root / "visual-embeddings.json").write_text(__import__("json").dumps(manifest, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
            result["embeddingIndexes"]["visual"] = manifest
            result["recognitionCompletedModalities"].append("visual")
            result["recognitionAvailableModalities"].append("visual")
        except Exception as error:
            result["degradedReasons"].append(f"visual_embeddings_unavailable:{str(error)[:160]}")

    if work["needsAudio"]:
        result["recognitionAttemptedModalities"].append("audio")
        result["audioUnits"] = _audio_event_units(transcript_segments)
        audio_complete = bool(speech_analysis_complete)
        if work["needsAudioEmbeddings"]:
            try:
                report(.72, "正在建立声音语义索引")
                audio_units, manifest = _clap_audio_index(
                    source, root, duration=duration, ffmpeg=ffmpeg,
                    model_id=settings.recognition_clap_model, model_cache=settings.recognition_model_cache,
                    device=device, progress=lambda value, detail: report(.72 + .24 * value, detail),
                    scope_start=bounded_start, scope_end=bounded_end,
                )
                result["audioUnits"] = [*result["audioUnits"], *audio_units]
                result["embeddingIndexes"]["audio"] = manifest
                audio_complete = True
            except Exception as error:
                audio_complete = False
                result["degradedReasons"].append(f"audio_embeddings_unavailable:{str(error)[:160]}")
        if audio_complete:
            result["recognitionCompletedModalities"].append("audio")
            result["recognitionAvailableModalities"].append("audio")
    text_units = [
        item for item in [*speech_units, *(result.get("ocrUnits") or [])]
        if isinstance(item, dict) and str(item.get("id") or "")
        and str(item.get("text") or item.get("title") or "").strip()
    ]
    if text_units and requested & {"speech", "ocr"}:
        try:
            report(.94, "正在建立字幕与屏幕文字语义索引")
            from .recognition_models import TextEncoder

            texts = [str(item.get("text") or item.get("title") or "") for item in text_units]
            matrix = TextEncoder(
                settings.recognition_text_model, device=device,
                cache_dir=settings.recognition_model_cache,
            ).encode_texts(texts, batch_size=32 if cuda else 8)
            result["embeddingIndexes"]["text"] = write_embedding_matrix(
                root / "text-embeddings.npy", [str(item["id"]) for item in text_units],
                matrix, model=settings.recognition_text_model,
            )
        except Exception as error:
            result["degradedReasons"].append(f"text_embeddings_unavailable:{str(error)[:160]}")
    result["recognitionSkippedModalities"] = sorted(RECOGNITION_MODALITIES - requested)
    report(1.0, "所需内容索引已完成")
    return result


def enrich_multimodal_index_isolated(
    *, worker_python: str, source: Path, root: Path, duration: float,
    scene_cuts: list[float], transcript_segments: list[dict[str, Any]],
    speech_units: list[dict[str, Any]], settings: Any, recognition_profile: str,
    ffmpeg: str, requested_modalities: set[str] | list[str] | tuple[str, ...] | None = None,
    speech_analysis_complete: bool = False,
    scope_start: float = 0.0, scope_end: float | None = None,
    progress: ProgressCallback | None = None,
    cancelled: Callable[[], bool] | None = None,
    algorithm_version: str = "editing-algorithm-v1",
) -> dict[str, Any]:
    """Run native optional models outside the API process when configured."""
    report = progress or (lambda _value, _detail: None)
    is_cancelled = cancelled or (lambda: False)
    request_id = uuid.uuid4().hex
    request_path = root / f"recognition-worker-request-{request_id}.json"
    response_path = root / f"recognition-worker-response-{request_id}.json"
    progress_path = root / f"recognition-worker-progress-{request_id}.json"
    payload = {
        "source": str(source), "root": str(root), "duration": duration,
        "sceneCuts": scene_cuts, "transcriptSegments": transcript_segments,
        "speechUnits": speech_units, "recognitionProfile": recognition_profile,
        "requestedModalities": sorted(requested_modalities or RECOGNITION_MODALITIES),
        "speechAnalysisComplete": bool(speech_analysis_complete),
        "scopeStart": float(scope_start), "scopeEnd": scope_end,
        "algorithmVersion": algorithm_version,
        "ffmpeg": ffmpeg,
        "settings": {
            "recognition_ocr_enabled": bool(settings.recognition_ocr_enabled),
            "recognition_yunet_model": str(settings.recognition_yunet_model),
            "recognition_sface_model": str(settings.recognition_sface_model),
            "recognition_yolox_model": str(settings.recognition_yolox_model),
            "recognition_youtureid_model": str(settings.recognition_youtureid_model),
            "recognition_siglip_model": settings.recognition_siglip_model,
            "recognition_text_model": settings.recognition_text_model,
            "recognition_clap_model": settings.recognition_clap_model,
            "recognition_grounding_model": settings.recognition_grounding_model,
            "recognition_model_cache": str(settings.recognition_model_cache),
            "recognition_profile": settings.recognition_profile,
        },
        "responsePath": str(response_path),
        "progressPath": str(progress_path),
        "ownerPid": os.getpid(),
    }
    request_path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    response_path.unlink(missing_ok=True)
    report(.02, "正在启动隔离的多模态识别进程")
    process = subprocess.Popen(
        [worker_python, "-m", "app.recognition_worker", str(request_path)],
        cwd=str(Path(__file__).resolve().parents[1]), stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        start_new_session=True,
    )
    started = time.monotonic()
    last_progress_mtime = 0.0
    try:
        while process.poll() is None:
            if is_cancelled():
                try:
                    os.killpg(process.pid, signal.SIGTERM)
                except OSError:
                    process.terminate()
                try:
                    process.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    try:
                        os.killpg(process.pid, signal.SIGKILL)
                    except OSError:
                        process.kill()
                raise RuntimeError("任务已取消")
            if time.monotonic() - started > 60 * 60:
                try:
                    os.killpg(process.pid, signal.SIGTERM)
                    process.wait(timeout=5)
                except (OSError, subprocess.TimeoutExpired):
                    try:
                        os.killpg(process.pid, signal.SIGKILL)
                    except OSError:
                        process.kill()
                raise RuntimeError("隔离多模态识别超过 1 小时，已终止并可安全重试")
            try:
                progress_mtime = progress_path.stat().st_mtime
                if progress_mtime > last_progress_mtime:
                    snapshot = json.loads(progress_path.read_text(encoding="utf-8"))
                    report(float(snapshot.get("fraction") or 0), str(snapshot.get("detail") or "多模态识别处理中"))
                    last_progress_mtime = progress_mtime
            except (OSError, ValueError, TypeError, json.JSONDecodeError):
                pass
            time.sleep(.2)
        stdout, stderr = process.communicate()
        if process.returncode or not response_path.is_file():
            detail = stderr.decode("utf-8", errors="replace")[-1600:] or stdout.decode("utf-8", errors="replace")[-1600:]
            raise RuntimeError(detail or "隔离识别进程失败")
        result = json.loads(response_path.read_text(encoding="utf-8"))
        if not isinstance(result, dict):
            raise RuntimeError("隔离识别进程返回格式无效")
        report(1.0, "隔离的多模态识别已完成")
        return result
    finally:
        request_path.unlink(missing_ok=True)
        response_path.unlink(missing_ok=True)
        progress_path.unlink(missing_ok=True)


def query_embedding_indexes(
    query: str, index: dict[str, Any], directory: Path, settings: Any,
    *, modalities: set[str], limit: int = 16,
) -> tuple[list[dict[str, Any]], list[str]]:
    """Recall unit IDs from optional on-disk embeddings; failures stay local."""
    manifests = index.get("embeddingIndexes") if isinstance(index.get("embeddingIndexes"), dict) else {}
    rows: list[dict[str, Any]] = []
    warnings: list[str] = []
    profile = index.get("recognitionProfile") if isinstance(index.get("recognitionProfile"), dict) else {}
    device = "cuda" if profile.get("effective") == "full" else "cpu"
    if "visual" in modalities and isinstance(manifests.get("visual"), dict):
        try:
            from .recognition_models import SiglipEncoder

            vector = SiglipEncoder(
                settings.recognition_siglip_model, device=device,
                cache_dir=settings.recognition_model_cache,
            ).encode_texts([query])[0]
            rows.extend({**item, "modality": "visual"} for item in vector_recall(
                vector, manifests["visual"], directory, limit=limit,
            ))
        except Exception as error:
            warnings.append(f"visual_vector_query_unavailable:{str(error)[:140]}")
    if "audio" in modalities and isinstance(manifests.get("audio"), dict):
        try:
            from .recognition_models import ClapEncoder

            vector = ClapEncoder(
                settings.recognition_clap_model, device=device,
                cache_dir=settings.recognition_model_cache,
            ).encode_texts([query])[0]
            rows.extend({**item, "modality": "audio"} for item in vector_recall(
                vector, manifests["audio"], directory, limit=limit,
            ))
        except Exception as error:
            warnings.append(f"audio_vector_query_unavailable:{str(error)[:140]}")
    if modalities & {"speech", "ocr"} and isinstance(manifests.get("text"), dict):
        try:
            from .recognition_models import TextEncoder

            vector = TextEncoder(
                settings.recognition_text_model, device=device,
                cache_dir=settings.recognition_model_cache,
            ).encode_texts([query], query=True)[0]
            rows.extend({**item, "modality": "text"} for item in vector_recall(
                vector, manifests["text"], directory, limit=limit,
            ))
        except Exception as error:
            warnings.append(f"text_vector_query_unavailable:{str(error)[:140]}")
    best: dict[str, dict[str, Any]] = {}
    for row in rows:
        unit_id = str(row.get("id") or "")
        if unit_id and float(row.get("score") or -1) > float(best.get(unit_id, {}).get("score") or -1):
            best[unit_id] = row
    return sorted(best.values(), key=lambda item: float(item.get("score") or -1), reverse=True), warnings


def ground_objects_in_matches(
    *, source: Path, root: Path, matches: list[dict[str, Any]], labels: list[str],
    settings: Any, ffmpeg: str, maximum: int = 8,
) -> tuple[int, str | None]:
    """Attach on-demand object boxes to already-grounded visual candidates."""
    clean_labels = list(dict.fromkeys(str(value).strip() for value in labels if str(value).strip()))[:12]
    targets = [
        match for match in matches
        if match.get("evidenceType") in {"visual", "audiovisual", "multimodal"}
        or "visual" in set(match.get("matchedModalities") or [])
    ][:max(0, int(maximum))]
    if not clean_labels or not targets:
        return 0, None
    try:
        from .recognition_models import GroundingDinoEngine

        profile = normalize_recognition_profile(
            (settings.recognition_profile if hasattr(settings, "recognition_profile") else "auto"),
            cuda_available=False,
        )
        device = "cuda" if profile.get("effective") == "full" else "cpu"
        times: list[float] = []
        frame_owners: list[tuple[dict[str, Any], float]] = []
        for item in targets:
            start = float(item.get("start") or 0)
            end = max(start, float(item.get("end") or start))
            candidate_times = [start, (start + end) * .5, max(start, end - .04)]
            for evidence_time in dict.fromkeys(round(value, 3) for value in candidate_times):
                times.append(evidence_time)
                frame_owners.append((item, evidence_time))
        frames = extract_frames_at_times(source, root / "object-grounding", times, ffmpeg=ffmpeg)
        engine = GroundingDinoEngine(
            settings.recognition_grounding_model, device=device,
            cache_dir=settings.recognition_model_cache,
        )
        detections_by_match: dict[int, list[dict[str, Any]]] = {}
        match_by_identity = {id(item): item for item in targets}
        for (match, evidence_time), frame in zip(frame_owners, frames):
            detections = engine.detect(Path(frame.path), clean_labels)
            if detections:
                rows = detections_by_match.setdefault(id(match), [])
                rows.extend({**item, "evidenceTime": evidence_time} for item in detections[:20])
        attached = 0
        for identity, detections in detections_by_match.items():
            match = match_by_identity[identity]
            if detections:
                match["objectDetections"] = detections[:40]
                match["matchedEvidence"] = (
                    str(match.get("matchedEvidence") or "") + "；对象定位：" +
                    "、".join(str(item.get("label") or "") for item in detections[:6])
                ).strip("；")[:500]
                match["boundarySource"] = "grounding_dino_evidence"
                match["objectGroundingSampling"] = "start_mid_end"
                attached += 1
        return attached, None
    except Exception as error:
        return 0, f"object_grounding_unavailable:{str(error)[:140]}"
