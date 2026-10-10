"""锁定「覆盖不完整 + 零命中」场景下，澄清文案承诺的出路必须真实存在。

背景：main.py 的 coverage_incomplete 澄清消息会指引用户
「补充其他线索（对白、画面文字、人物）继续查找」。这些出路实际由
expansionOptions 渲染成按钮（前端 app.js 的 data-content-expansion）。

若将来 content_expansion_options 的建议逻辑变动，文案就会指向不存在的
选项，变成新的死路。本测试把「文案承诺」与「代码能力」绑定。

注意：本测试只锁出路可用性，不锁 strictVisualCoverageComplete 的质量闸门——
那个闸门是「宁可不给结果也不给错结果」的保守策略，不应放开。
"""

from __future__ import annotations

from app.content_search import content_expansion_options


def _ids(capabilities: list[str], **kwargs: object) -> set[str]:
    return {
        str(item.get("id") or "")
        for item in content_expansion_options(capabilities, **kwargs)  # type: ignore[arg-type]
        if isinstance(item, dict)
    }


def test_visual_only_search_offers_the_clues_named_in_the_message() -> None:
    """画面检索零命中时，必须能补充对白 / 屏幕文字 / 人物三类线索。"""
    offered = _ids(["visual"])
    assert "add_speech" in offered, "缺少「继续查对白」出路"
    assert "add_ocr" in offered, "缺少「继续查屏幕文字」出路"
    assert "add_person" in offered, "缺少「继续查人物」出路"


def test_already_used_capability_is_not_suggested_again() -> None:
    """已有能力不该重复建议，否则按钮点了等于原样重跑。"""
    offered = _ids(["visual"])
    assert "add_visual" not in offered


def test_narrow_scope_offers_full_reel_expansion() -> None:
    """时间范围窄时应给出「扩大到全片」。"""
    offered = _ids(["visual"], scope_is_narrow=True)
    assert "expand_scope" in offered


def test_suggestions_are_bounded_and_labeled() -> None:
    options = content_expansion_options(["visual"])
    assert 1 <= len(options) <= 4
    for item in options:
        assert str(item.get("label") or "").strip(), "选项必须带可见文案"
        assert str(item.get("id") or "").strip(), "选项必须带 id"
