"""Regression: anchor-start parsing must keep the full semantic phrase.

Found by running tests/real_video_acceptance.py: the goal
"从拿起西瓜的地方开始" produced the anchor query "拿" because the lazy group
stopped at the first character and the alternation "(?:开始|起)" ate the
trailing "起" of the verb "拿起".  A one-character query is then treated as a
broad multi-source topic, which demands a visual/speech/screen-text union and
conflicts with the single speech predicate, ending in zero candidates.
"""
from __future__ import annotations

from app.agent_platform import AgentPlatform


def _anchor_query(text: str) -> str | None:
    brief = AgentPlatform._editing_brief(text, {})
    anchor = brief.get("anchorStart") if isinstance(brief, dict) else None
    if not isinstance(anchor, dict):
        return None
    return str(anchor.get("query") or "") or None


def test_verb_phrase_is_not_truncated_to_one_character() -> None:
    assert _anchor_query("从拿起西瓜的地方开始") == "拿起西瓜"


def test_verb_phrase_without_boundary_word() -> None:
    assert _anchor_query("从拿起西瓜开始") == "拿起西瓜"


def test_speech_anchor_parsing_is_unchanged() -> None:
    assert _anchor_query("从讲价格的地方开始") == "价格"
    assert _anchor_query("从讲价格的地方开始剪") == "价格"
    assert _anchor_query("从介绍产品的部分开始") == "产品"


def test_time_anchor_still_takes_precedence() -> None:
    brief = AgentPlatform._editing_brief("从 1:20 出现汽车的地方开始剪。", {})
    assert brief["anchorStart"] == {
        "query": "汽车",
        "selectionPolicy": "unique_or_review",
        "sourceTimeSeconds": 80.0,
    }


def test_semantic_range_anchor_is_unchanged() -> None:
    brief = AgentPlatform._editing_brief("把讲价格的地方开始到讲配置结束剪出来", {})
    assert brief["anchorStart"] == {"query": "价格", "selectionPolicy": "unique_or_review"}
    assert brief["sourceEndAnchor"] == {"query": "配置", "selectionPolicy": "unique_or_review"}
