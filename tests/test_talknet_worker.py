from __future__ import annotations

import numpy as np

from tools.talknet_worker import identity_mask_from_similarities, target_talknet_tracks


def test_identity_mask_splits_a_real_identity_change_but_fills_short_dropout() -> None:
    mask = identity_mask_from_similarities([.71, .69, .31, .30, .66, .67], threshold=.58, max_gap_frames=1)
    assert mask == [True, True, False, False, True, True]
    assert identity_mask_from_similarities([.7, .2, .7], threshold=.58, max_gap_frames=1) == [True, True, True]


def test_target_track_boxes_are_scaled_from_recognition_to_source_coordinates() -> None:
    frames = np.arange(0, 100, dtype=np.int64)
    boxes = np.tile(np.asarray([[188.0, 379.0, 231.0, 441.0]], dtype=np.float32), (100, 1))
    tracks = [{"track": {"frame": frames, "bbox": boxes}}]
    targets = [{
        "id": "face_1", "time": 2.0,
        "box": [208.9, 421.1, 256.7, 490.0], "frameWidth": 640,
    }]

    selected = target_talknet_tracks(
        tracks, targets, 0.0, source_frame_width=576,
    )

    assert selected
    assert selected[0][0] == 0
    assert selected[0][1] == ["face_1"]
