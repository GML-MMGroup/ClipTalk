from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import numpy as np

from app.evidence_store import (
    predicate_cache_key,
    promote_source_evidence,
    query_source_evidence_vectors,
    read_predicate_evidence,
    read_source_evidence,
    scope_is_covered,
    source_evidence_revision,
    source_evidence_directory,
    write_predicate_evidence,
)


class SourceEvidenceStoreTests(unittest.TestCase):
    def test_source_store_deduplicates_reusable_observations(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            record = {
                "modality": "visual", "start": 10.0, "end": 10.6,
                "evidenceTime": 10.3, "observation": "画面中有一台白色冰箱",
                "model": "vision-a", "source": "generic_scene_observation",
                "confidence": .91,
            }
            first = promote_source_evidence(root, "same-video", [record])
            first_revision = source_evidence_revision(root, "same-video")
            second = promote_source_evidence(root, "same-video", [{**record, "confidence": .95}])
            second_revision = source_evidence_revision(root, "same-video")
            promote_source_evidence(root, "same-video", [{**record, "confidence": .95}])
            loaded = read_source_evidence(
                root, "same-video", modalities={"visual"}, start=0, end=20,
            )
            self.assertEqual(len(first), 1)
            self.assertEqual(first[0]["id"], second[0]["id"])
            self.assertEqual(len(loaded), 1)
            self.assertEqual(loaded[0]["confidence"], .95)
            self.assertTrue(loaded[0]["sourceEvidence"])
            self.assertNotEqual(first_revision, second_revision)
            self.assertEqual(second_revision, source_evidence_revision(root, "same-video"))

    def test_source_store_filters_by_scope_and_modality(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            promote_source_evidence(root, "video", [
                {"modality": "visual", "start": 2, "end": 3, "observation": "洗衣机", "model": "v"},
                {"modality": "visual", "start": 20, "end": 21, "observation": "冰箱", "model": "v"},
                {"modality": "audio", "start": 2, "end": 3, "observation": "水声", "model": "a"},
            ])
            loaded = read_source_evidence(
                root, "video", modalities={"visual"}, start=10, end=30,
            )
            self.assertEqual([item["text"] for item in loaded], ["冰箱"])

    def test_predicate_cache_requires_complete_covering_scope(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            predicate = {"id": "p1", "kind": "visual.object", "value": "冰箱"}
            key = predicate_cache_key(predicate, model_fingerprint="vision-v1")
            write_predicate_evidence(root, "video", key, {
                "scope": {"start": 0, "end": 60}, "coverageComplete": True,
                "matches": [{"start": 10, "end": 12}], "evidenceUnits": [],
            })
            loaded = read_predicate_evidence(root, "video", key)
            self.assertIsNotNone(loaded)
            self.assertTrue(scope_is_covered(loaded or {}, start=10, end=50))
            self.assertFalse(scope_is_covered(loaded or {}, start=0, end=90))

    def test_source_directory_depends_only_on_source_identity(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            self.assertEqual(
                source_evidence_directory(root, "source-hash"),
                source_evidence_directory(root, "source-hash"),
            )
            self.assertNotEqual(
                source_evidence_directory(root, "source-hash"),
                source_evidence_directory(root, "other-source"),
            )

    def test_source_vector_recall_builds_once_and_reuses_sidecar(self) -> None:
        class FakeTextEncoder:
            passage_calls = 0

            def __init__(self, *_args, **_kwargs) -> None:
                pass

            def encode_texts(self, texts, *, query=False):
                if query:
                    return np.asarray([[1.0, 0.0]], dtype=np.float32)
                FakeTextEncoder.passage_calls += 1
                return np.asarray([
                    [1.0, 0.0] if "冰箱" in text else [0.0, 1.0]
                    for text in texts
                ], dtype=np.float32)

        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            promote_source_evidence(root, "video", [
                {"modality": "visual", "start": 2, "end": 3, "observation": "白色冰箱", "model": "v"},
                {"modality": "visual", "start": 8, "end": 9, "observation": "滚筒洗衣机", "model": "v"},
            ])
            records = read_source_evidence(root, "video", modalities={"visual"}, start=0, end=20)
            with patch("app.recognition_models.TextEncoder", FakeTextEncoder):
                first, first_hit, warning = query_source_evidence_vectors(
                    root, "video", records, "找冰箱", model_id="fake-e5",
                    model_cache=root / "models", device="cpu", limit=2,
                )
                second, second_hit, second_warning = query_source_evidence_vectors(
                    root, "video", records, "还是找冰箱", model_id="fake-e5",
                    model_cache=root / "models", device="cpu", limit=2,
                )
            self.assertIsNone(warning)
            self.assertIsNone(second_warning)
            self.assertFalse(first_hit)
            self.assertTrue(second_hit)
            self.assertEqual(FakeTextEncoder.passage_calls, 1)
            self.assertEqual(first[0]["text"], "白色冰箱")
            self.assertEqual(second[0]["text"], "白色冰箱")


if __name__ == "__main__":
    unittest.main()
