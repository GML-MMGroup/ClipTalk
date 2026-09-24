from __future__ import annotations

import json
import subprocess
from pathlib import Path

from app.local_motion import build_motion_graphics_html, motion_canvas_size, write_editing_draft_package


ROOT = Path(__file__).resolve().parents[1]


def test_motion_canvas_size_defaults_to_vertical() -> None:
    assert motion_canvas_size("1:1") == (1080, 1080)
    assert motion_canvas_size("unknown") == (1080, 1920)


def test_build_motion_graphics_html_escapes_user_text() -> None:
    html = build_motion_graphics_html(
        title="<小米汽车>",
        subtitle="本地渲染 & 不调用 API",
        aspect="9:16",
    )
    assert "&lt;小米汽车&gt;" in html
    assert "本地渲染 &amp; 不调用 API" in html
    assert "--w: 1080px" in html
    assert "--h: 1920px" in html


def test_write_editing_draft_package_is_current_task_scoped(tmp_path: Path) -> None:
    destination = tmp_path / "draft.json"
    write_editing_draft_package(
        {
            "id": "job_1",
            "filename": "产品宣传.mp4",
            "sourceAssetId": "source_a",
            "activeEditSessionId": "edit_1",
            "editSessions": [{
                "id": "edit_1",
                "clips": [
                    {"id": "clip_1", "title": "片段 1", "sourceStart": 1, "sourceEnd": 4, "playbackRate": 1},
                    {"id": "clip_2", "title": "片段 2", "sourceStart": 8, "sourceEnd": 12, "playbackRate": 2},
                ],
            }],
            "outputVersions": [{"id": "v1"}],
            "coverVersions": [{"id": "cover_1"}],
        },
        destination,
    )
    payload = json.loads(destination.read_text(encoding="utf-8"))
    assert payload["schemaVersion"] == "cliptalk-editing-draft-v1"
    assert payload["jobId"] == "job_1"
    assert payload["activeEditSessionId"] == "edit_1"
    assert payload["source"]["sourceAssetId"] == "source_a"
    assert payload["timelines"][0]["duration"] == 5
    assert payload["timelines"][0]["timeline"][1]["outputStart"] == 3
    assert "不依赖外部 API" in payload["notes"][0]


def test_write_editing_draft_package_supports_source_only_export(tmp_path: Path) -> None:
    destination = tmp_path / "source-only-draft.json"
    write_editing_draft_package(
        {
            "id": "job_source_only",
            "filename": "小米产品.mp4",
            "sourceAssetId": "source_b",
            "duration": 664.1,
            "videoInfo": {"width": 3840, "height": 2160},
        },
        destination,
    )
    payload = json.loads(destination.read_text(encoding="utf-8"))
    assert payload["jobId"] == "job_source_only"
    assert payload["source"]["filename"] == "小米产品.mp4"
    assert payload["source"]["duration"] == 664.1
    assert payload["timelines"] == []
    assert payload["editSessions"] == []
    assert "源素材草稿" in payload["notes"][1]


def test_render_html_motion_script_has_help_entrypoint() -> None:
    completed = subprocess.run(
        ["node", str(ROOT / "tools" / "render_html_motion.mjs"), "--help"],
        text=True,
        capture_output=True,
        check=False,
    )
    assert completed.returncode == 0
    assert "render_html_motion.mjs" in completed.stdout
