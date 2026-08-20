from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import numpy as np

from app.recognition import (
    MULTIMODAL_INDEX_VERSION,
    RECOGNITION_SCHEMA_VERSION,
    build_shots,
    cluster_person_tracks,
    conservative_face_speaker_links,
    dense_person_sample_times,
    ground_evidence_refs,
    merge_ocr_detections,
    normalize_recognition_profile,
    recognition_summary,
    shot_sample_times,
    vector_recall,
    write_embedding_matrix,
)
from app.recognition_pipeline import enrich_multimodal_index, recognition_work_plan


class RecognitionContractTests(unittest.TestCase):
    def test_work_plan_only_enables_requested_expensive_models(self) -> None:
        speech = recognition_work_plan({"speech"}, recognition_profile="balanced")
        self.assertFalse(speech["needsFrames"])
        self.assertFalse(speech["needsOcr"])
        self.assertFalse(speech["needsVisualEmbeddings"])
        ocr = recognition_work_plan({"ocr"}, recognition_profile="balanced")
        self.assertTrue(ocr["needsFrames"])
        self.assertTrue(ocr["needsOcr"])
        self.assertFalse(ocr["needsPersons"])
        self.assertFalse(ocr["needsVisualEmbeddings"])
        audio = recognition_work_plan({"audio"}, recognition_profile="auto")
        self.assertTrue(audio["needsAudio"])
        self.assertFalse(audio["needsAudioEmbeddings"])
        full_audio = recognition_work_plan({"audio"}, recognition_profile="full")
        self.assertTrue(full_audio["needsAudioEmbeddings"])

    def test_speech_only_enrichment_does_not_extract_frames(self) -> None:
        with tempfile.TemporaryDirectory() as directory, patch(
            "app.recognition_pipeline.extract_frames_at_times",
        ) as extract:
            result = enrich_multimodal_index(
                source=Path(directory) / "source.mp4",
                root=Path(directory), duration=30, scene_cuts=[],
                transcript_segments=[], speech_units=[], settings=SimpleNamespace(),
                recognition_profile="balanced", ffmpeg="ffmpeg",
                requested_modalities={"speech"}, speech_analysis_complete=True,
            )
        extract.assert_not_called()
        self.assertEqual(result["recognitionRequestedModalities"], ["speech"])
        self.assertNotIn("ocrUnits", result)
        self.assertNotIn("embeddingVisualUnits", result)

    def test_full_ocr_enrichment_uses_dense_two_fps_timeline(self) -> None:
        ocr_engine = MagicMock()
        ocr_engine.recognize.return_value = []

        def frames_at_times(_source, _root, times, **_kwargs):
            return [SimpleNamespace(path=Path(f"frame-{position}.jpg"), time=value)
                    for position, value in enumerate(times)]

        with tempfile.TemporaryDirectory() as directory, \
                patch("app.recognition_pipeline.extract_frames_at_times", side_effect=frames_at_times), \
                patch("app.recognition_models.PaddleOcrEngine", return_value=ocr_engine):
            result = enrich_multimodal_index(
                source=Path(directory) / "source.mp4",
                root=Path(directory), duration=10, scene_cuts=[5],
                transcript_segments=[], speech_units=[], settings=SimpleNamespace(
                    recognition_ocr_enabled=True,
                    recognition_model_cache=Path(directory),
                ), recognition_profile="full", ffmpeg="ffmpeg",
                requested_modalities={"ocr"}, speech_analysis_complete=False,
            )

        self.assertEqual(result["ocrSampling"]["intervalSeconds"], .5)
        self.assertEqual(result["ocrSampling"]["requestedFrameCount"], 21)
        self.assertEqual(result["ocrSampling"]["extractedFrameCount"], 21)
        self.assertEqual(result["ocrSampling"]["coverageMode"], "continuous_sampled")
        self.assertEqual(len(ocr_engine.recognize.call_args.args[0]), 21)

    def test_shots_and_sampling_are_bounded_and_deterministic(self) -> None:
        shots = build_shots(30, [20, 10, 10, -1, 40])
        self.assertEqual([(item["start"], item["end"]) for item in shots], [(0.0, 10.0), (10.0, 20.0), (20.0, 30.0)])
        first = shot_sample_times(shots, maximum_per_shot=4, global_limit=8)
        second = shot_sample_times(build_shots(30, [10, 20]), maximum_per_shot=4, global_limit=8)
        self.assertEqual(first, second)
        self.assertLessEqual(len(first), 8)
        self.assertTrue(all(0 <= value <= 30 for value in first))

    def test_person_sampling_is_dense_and_scene_aware(self) -> None:
        shots = build_shots(10, [5])
        values = dense_person_sample_times(shots, interval=.5)
        self.assertEqual(values[0], 0.0)
        self.assertEqual(values[-1], 10.0)
        self.assertIn(5.0, values)
        self.assertGreaterEqual(len(values), 21)
        self.assertLessEqual(max(right - left for left, right in zip(values, values[1:])), .5)

    def test_person_ranges_merge_dense_observations_but_respect_scene_cuts(self) -> None:
        tracks = [
            {"id": "a1", "start": 1.0, "end": 1.0, "embedding": [1, 0]},
            {"id": "a2", "start": 1.5, "end": 1.5, "embedding": [.99, .01]},
            {"id": "a3", "start": 3.0, "end": 3.0, "embedding": [.98, .02]},
        ]
        people = cluster_person_tracks(tracks, similarity_threshold=.8, scene_cuts=[2.0])
        self.assertEqual(len(people), 1)
        self.assertEqual(len(people[0]["ranges"]), 2)
        self.assertEqual(people[0]["ranges"][0]["start"], .92)
        self.assertEqual(people[0]["ranges"][0]["end"], 1.58)
        self.assertEqual(people[0]["rangeEvidence"][0]["observedCount"], 2)
        self.assertFalse(people[0]["rangeEvidence"][0]["interpolated"])

    def test_person_range_evidence_marks_short_detection_gaps(self) -> None:
        tracks = [
            {"id": "a1", "start": 1.0, "end": 1.0, "embedding": [1, 0]},
            {"id": "a2", "start": 2.0, "end": 2.0, "embedding": [.99, .01]},
        ]
        people = cluster_person_tracks(tracks, similarity_threshold=.8, maximum_gap=1.5)
        evidence = people[0]["rangeEvidence"][0]
        self.assertTrue(evidence["interpolated"])
        self.assertLess(evidence["confidence"], .9)

    def test_ocr_merges_stable_text_but_not_distant_text(self) -> None:
        units = merge_ocr_detections([
            {"time": 1, "text": "Product X", "confidence": .8, "box": [0, 0, 100, 20]},
            {"time": 2, "text": "Product X", "confidence": .9, "box": [2, 0, 102, 20]},
            {"time": 8, "text": "Product X", "confidence": .7, "box": [0, 0, 100, 20]},
        ])
        self.assertEqual(len(units), 2)
        self.assertEqual((units[0]["start"], units[0]["end"]), (1.0, 2.0))
        self.assertEqual(units[0]["modality"], "ocr")

    def test_anonymous_persons_are_single_video_only(self) -> None:
        tracks = [
            {"id": "a1", "start": 1, "end": 1, "embedding": [1, 0]},
            {"id": "a2", "start": 2, "end": 2, "embedding": [.99, .01]},
            {"id": "b1", "start": 8, "end": 8, "embedding": [0, 1]},
        ]
        people = cluster_person_tracks(tracks, similarity_threshold=.8)
        self.assertEqual([item["label"] for item in people], ["人物 A", "人物 B"])
        self.assertTrue(all(item["anonymous"] and item["scope"] == "single_video" for item in people))
        speech = [
            {"start": .7, "end": 1.3, "speakers": ["Speaker 1"]},
            {"start": 1.5, "end": 2.0, "speakers": ["Speaker 1"]},
            {"start": 2.1, "end": 2.5, "speakers": ["Speaker 1"]},
        ]
        links = conservative_face_speaker_links(people, speech)
        self.assertLessEqual(len(links), 1)
        if links:
            self.assertEqual(links[0]["personId"], "person_1")

    def test_embedding_manifest_and_grounded_refs(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            manifest = write_embedding_matrix(
                root / "vectors.npy", ["left", "right"], np.asarray([[1, 0], [0, 1]], dtype=np.float32), model="test",
            )
            ranked = vector_recall([.9, .1], manifest, root, limit=2)
            self.assertEqual(ranked[0]["id"], "left")
        index = {"speechUnits": [{"id": "speech_1"}], "ocrUnits": [{"id": "ocr_1"}]}
        refs = ground_evidence_refs([
            {"type": "speech", "id": "speech_1"}, {"type": "ocr", "id": "missing"},
        ], index)
        self.assertEqual(refs, [{"type": "speech", "id": "speech_1"}])
        query_refs = ground_evidence_refs(
            [{"type": "visual.query_frame", "id": "query_visual_1"}], index,
            extra_evidence_ids={"query_visual_1"},
        )
        self.assertEqual(query_refs, [{"type": "visual.query_frame", "id": "query_visual_1"}])

    def test_profile_and_summary_contract(self) -> None:
        self.assertEqual(normalize_recognition_profile("auto", cuda_available=False)["effective"], "balanced")
        self.assertEqual(normalize_recognition_profile("auto", cuda_available=True)["effective"], "full")
        summary = recognition_summary({
            "schemaVersion": MULTIMODAL_INDEX_VERSION, "status": "ready",
            "shots": [{"id": "shot_1"}], "visualUnits": [{"id": "probe_1"}],
            "ocrUnits": [{"id": "ocr_1"}],
            "modalityCoverage": {"ocr": True, "visual": True}, "degradedReasons": ["audio_embeddings_on_demand"],
        })
        self.assertEqual(summary["schemaVersion"], RECOGNITION_SCHEMA_VERSION)
        self.assertEqual(summary["counts"]["ocr"], 1)
        self.assertEqual(summary["counts"]["visual"], 0)
        self.assertFalse(summary["modalityCoverage"]["visual"])
        self.assertEqual(summary["status"], "ready")


if __name__ == "__main__":
    unittest.main()
