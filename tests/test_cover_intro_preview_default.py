"""审核样片默认带封面片头（与成片一致）的回归门禁。

产品决策：只要本次要求了封面，成片和审核样片都默认把已确认封面合成为片头，
片头时长计入总时长、默认 1.0 秒。此前只有成片这样做，样片仍要求用户「明确
要求片头」且 Skill 画像含 cover-intro，导致「预览没有片头、导出成片才有」。

本文件锁定三件事：
1. 有封面（即使用户没提「片头」）→ 样片编排含 compose_cover_intro。
2. 没有封面 → 绝不含该步骤（避免给无封面任务插入无意义步骤）。
3. 片头步骤必须排在封面确认与审核样片之后（否则拿不到封面/源样片）。
"""

from __future__ import annotations

import tempfile
from pathlib import Path
from typing import Any

from app.agent_platform import AgentPlatform

ROOT = Path(__file__).resolve().parents[1]
SKILLS = ("cliptalk-shortform-hook-director", "cliptalk-cover-director")
PRIMARY = "cliptalk-shortform-hook-director"
CONTEXT: dict[str, Any] = {"editing": {"hasOutputs": False, "hasActiveSession": False}}


class _FakeAgentClient:
    """编排是纯代码生成，不消耗模型；这里只兜住平台初始化要求的接口。"""

    def plan(self, _payload: dict[str, Any]) -> dict[str, Any]:
        return {"plan": {"summary": "测试计划", "steps": []}, "events": []}

    def route_skill(self, _payload: dict[str, Any]) -> dict[str, Any]:
        return {"skillId": "", "reason": "unused"}

    def health(self) -> dict[str, Any]:
        return {"status": "ok"}


def _compile(
    goal: str, context: dict[str, Any], skill_ids: tuple[str, ...], primary_id: str,
) -> list[dict[str, Any]]:
    with tempfile.TemporaryDirectory() as directory:
        platform = AgentPlatform(
            data_root=Path(directory), service_url="http://agent.invalid",
            model_config_resolver=lambda: {"model": "fake"},
        )
        platform.client = _FakeAgentClient()  # type: ignore[assignment]
        for skill_id in skill_ids:
            platform.install_skill(
                markdown=(ROOT / "skills" / skill_id / "SKILL.md").read_text(encoding="utf-8"),
                source="test", status="enabled",
            )
        # 直接指定主 Skill：本文件锁定的是「编排是否注入片头步骤」，
        # 不依赖 goal→Skill 的路由结果，避免路由变化干扰断言。
        skill = platform.store.get("skills", primary_id)
        brief = platform._editing_brief(goal, context)
        compiled = platform._compile_profile_plan(
            {}, skill=skill, goal=goal, context=context,
            skills=platform._compose_skills(skill, brief=brief, context=context),
        )
        return compiled["steps"]


def test_review_preview_gets_cover_intro_by_default_when_cover_requested() -> None:
    steps = _compile("帮我剪一个30秒的视频，需要一张封面。", CONTEXT, SKILLS, PRIMARY)
    tools = [step["tool"] for step in steps]
    assert "confirm_cover" in tools, f"应生成封面确认步骤，实际：{tools}"
    assert "compose_cover_intro" in tools, f"有封面时样片应默认带片头，实际：{tools}"
    intro = next(step for step in steps if step["tool"] == "compose_cover_intro")
    assert intro["arguments"] == {"duration": 1.0}


def test_review_preview_has_no_cover_intro_without_cover_request() -> None:
    steps = _compile("帮我剪一个30秒的视频。", CONTEXT, SKILLS, PRIMARY)
    tools = [step["tool"] for step in steps]
    assert "compose_cover_intro" not in tools, f"无封面任务不应插入片头步骤，实际：{tools}"


def test_cover_intro_depends_on_confirmed_cover_and_review_preview() -> None:
    steps = _compile("帮我剪一个30秒的视频，需要一张封面。", CONTEXT, SKILLS, PRIMARY)
    by_tool = {step["tool"]: step for step in steps}
    intro = by_tool["compose_cover_intro"]
    assert by_tool["confirm_cover"]["id"] in intro["dependencies"]
    assert by_tool["render_review_preview"]["id"] in intro["dependencies"]
