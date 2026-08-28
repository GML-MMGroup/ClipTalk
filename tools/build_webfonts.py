#!/usr/bin/env python3
"""Build the small, locally served webfont set used by the workspace theme."""

from __future__ import annotations

from pathlib import Path

from fontTools import subset
from fontTools.ttLib import TTFont


ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "fonts"
OUTPUT = ROOT / "static" / "fonts"

DISPLAY_TEXT = (
    "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789"
    "开始剪辑最近任务创建新任务还没有可显示的任务上传视频告诉你想保留什么"
    "智能工作区内容发现人物说话人字幕二次精剪设置全部任务成片"
    "，。·—（）/："
)
METRIC_TEXT = " 0123456789%./:+-×xXfpsFPS"


def rename_font(font: TTFont, family: str, subfamily: str = "Regular") -> None:
    """Give converted fonts an internal project name instead of a reserved name."""
    name_table = font["name"]
    ps_family = "".join(ch for ch in family if ch.isalnum())
    values = {
        1: family,
        2: subfamily,
        4: f"{family} {subfamily}",
        6: f"{ps_family}-{subfamily}",
        16: family,
        17: subfamily,
    }
    for record in list(name_table.names):
        if record.nameID in values:
            name_table.setName(values[record.nameID], record.nameID, 3, 1, 0x409)
            name_table.setName(values[record.nameID], record.nameID, 1, 0, 0)


def save_full_woff2(source: Path, target: Path, family: str) -> None:
    font = TTFont(source)
    rename_font(font, family)
    font.flavor = "woff2"
    font.save(target)


def save_subset(source: Path, target: Path, family: str, text: str) -> None:
    options = subset.Options()
    options.flavor = "woff2"
    options.layout_features = ["*"]
    options.name_IDs = [0, 1, 2, 3, 4, 5, 6, 16, 17]
    options.name_languages = ["*"]
    options.notdef_glyph = True
    options.recommended_glyphs = True
    font = subset.load_font(source, options)
    subsetter = subset.Subsetter(options=options)
    subsetter.populate(text=text)
    subsetter.subset(font)
    rename_font(font, family)
    subset.save_font(font, target, options)


def main() -> None:
    OUTPUT.mkdir(parents=True, exist_ok=True)
    save_subset(
        SOURCE / "FandolSong-Bold.otf",
        OUTPUT / "vp-editorial-song.woff2",
        "VP Editorial Song",
        DISPLAY_TEXT,
    )
    save_full_woff2(
        SOURCE / "霞鹜文楷（LXGWWenKai-Medium）.ttf",
        OUTPUT / "vp-assistant-wenkai.woff2",
        "VP Assistant WenKai",
    )
    save_subset(
        SOURCE / "星汉等宽(milky-term-cn-heavyitalic).ttf",
        OUTPUT / "vp-metric-display.woff2",
        "VP Metric Display",
        METRIC_TEXT,
    )
    for path in sorted(OUTPUT.glob("vp-*.woff2")):
        print(f"{path.relative_to(ROOT)}\t{path.stat().st_size:,} bytes")


if __name__ == "__main__":
    main()
