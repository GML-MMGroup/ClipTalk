import pytest

from app.intent_router import normalize_model_routing, route_editing_instruction
from app.job_schema import CURRENT_JOB_SCHEMA_VERSION, normalize_job_schema


def test_routes_highlight_instruction() -> None:
    decision = route_editing_instruction("生成一条 60 秒高光，重点保留人物反应和动作高潮")
    assert decision.task_mode == "highlight"
    assert decision.needs_confirmation is False


def test_routes_content_instruction() -> None:
    decision = route_editing_instruction("找出后半段女嘉宾介绍离线功能的全部发言片段")
    assert decision.task_mode == "content_extract"
    assert decision.needs_confirmation is False


def test_ambiguous_instruction_requires_confirmation() -> None:
    decision = route_editing_instruction("帮我剪一下这个视频")
    assert decision.task_mode is None
    assert decision.needs_confirmation is True


def test_explicit_legacy_mode_remains_authoritative() -> None:
    decision = route_editing_instruction("帮我剪一下", "content_extract")
    assert decision.task_mode == "content_extract"
    assert decision.source == "explicit"


def test_routes_first_class_person_and_speaker_workflows() -> None:
    person = route_editing_instruction("按人物剪辑，先选择人物 A，再提取他的所有出镜")
    speaker = route_editing_instruction("按说话人剪辑，试听后保留 Speaker 2 的全部发言")
    assert person.workflow_kind == "person_edit"
    assert speaker.workflow_kind == "speaker_edit"
    assert person.task_mode == speaker.task_mode == "content_extract"


def test_person_topic_and_interview_question_remain_content_search() -> None:
    topic = route_editing_instruction("找出医生讨论糖尿病发作机理的片段")
    questions = route_editing_instruction("找出所有采访问题，包括提问画面和口头提问")
    assert topic.workflow_kind == "content_search"
    assert questions.workflow_kind == "content_search"


def test_model_is_primary_but_strong_local_conflict_requires_confirmation() -> None:
    decision = normalize_model_routing(
        "生成一条比赛高光集锦",
        {"workflowKind": "content_search", "confidence": .94, "reason": "按比赛内容查找"},
    )
    assert decision.workflow_kind == "content_search"
    assert decision.source == "model_primary_v2"
    assert decision.needs_confirmation is True
    assert "冲突" in decision.reason


def test_model_low_confidence_requires_confirmation_without_rule_override() -> None:
    decision = normalize_model_routing(
        "做得适合发出去",
        {"workflowKind": "highlight", "confidence": .62, "reason": "可能需要成片"},
    )
    assert decision.workflow_kind == "highlight"
    assert decision.needs_confirmation is True
    assert decision.action == "clarify"


def test_contextual_model_decision_can_continue_or_switch_workflow() -> None:
    stay = normalize_model_routing(
        "把这些片段按动作顺序排列",
        {"action": "continue_current", "workflowKind": "content_search", "confidence": .96},
        current_workflow="content_search",
    )
    switch = normalize_model_routing(
        "重新通看全片做一个高光",
        {"action": "switch_workflow", "workflowKind": "highlight", "confidence": .96},
        current_workflow="content_search",
    )
    assert stay.action == "continue_current"
    assert stay.workflow_kind == "content_search"
    assert switch.action == "switch_workflow"
    assert switch.workflow_kind == "highlight"


def test_model_routing_rejects_unknown_workflow() -> None:
    with pytest.raises(ValueError, match="受支持"):
        normalize_model_routing("处理视频", {"workflowKind": "unknown", "confidence": .9})


def test_job_schema_migration_preserves_legacy_variant_default() -> None:
    job = {"taskMode": "highlight", "request": {}}
    assert normalize_job_schema(job) is True
    assert job["schemaVersion"] == CURRENT_JOB_SCHEMA_VERSION
    assert job["request"]["autoVariantCount"] == 3
    assert normalize_job_schema(job) is False


INTENT_REGRESSION_CASES = [
    *(('highlight', value) for value in (
        "帮我生成一条高光集锦",
        "做一个30秒的精彩回顾视频",
        "从全片挑出最精彩的瞬间做成短片",
        "剪一个有节奏的旅行 vlog 成片",
        "做一条预告片，突出情绪起伏",
        "把关键动作和人物反应剪成一分钟视频",
        "制作比赛最佳镜头合集",
        "把整段浓缩成一条短视频",
        "生成婚礼高光，保留最感人的时刻",
        "create a highlight reel with the best moments",
    )),
    *(('content_search', value) for value in (
        "查找所有提到产品续航的发言片段",
        "定位后半段女嘉宾介绍离线功能的画面",
        "找出医生讨论糖尿病发作机理的片段",
        "截取主持人说欢迎大家的完整对白",
        "搜索屏幕上出现价格的画面",
        "找出所有采访问题，包括口头提问",
        "保留开头两分钟里展示手机的镜头",
        "查一下谁介绍了电池容量",
        "find every time someone says battery life",
        "提取 03:20 附近的内容",
    )),
    *(('person_edit', value) for value in (
        "按人物剪辑，先让我选择一个人",
        "识别画面人物后提取目标人物所有出镜",
        "把这个人的所有出镜都找出来",
        "人物 A 的所有出现画面都保留",
        "选择目标人物并剪出他的全部片段",
        "根据人物分段，分别提取每个人",
        "提取该人物全部出镜",
        "按脸选人，再剪出这个人出现的所有镜头",
        "先看看视频里有哪些人，我选一个再剪",
        "只保留红衣女生每次出现的画面",
    )),
    *(('speaker_edit', value) for value in (
        "按说话人剪辑，先试听再选择",
        "先识别有哪些声音，再提取其中一个人的发言",
        "保留这个说话人的所有发言",
        "Speaker 2 的全部说话片段",
        "根据音色筛选并剪辑",
        "选一个声音，提取他的全部发言",
        "把不同人的说话分开，我再选一个",
        "识别发言人并提取目标声音",
        "先区分说话人，然后只保留其中一位",
        "只要某个声音说话的全部片段",
    )),
    *(('clarification', value) for value in (
        "帮我剪一下这个视频",
        "处理一下这个素材",
        "给我做个视频",
        "整理一下",
        "看看这个视频怎么剪",
    )),
]


@pytest.mark.parametrize(("expected", "instruction"), INTENT_REGRESSION_CASES)
def test_natural_language_workflow_intent_regression(expected: str, instruction: str) -> None:
    decision = route_editing_instruction(instruction)
    actual = "clarification" if decision.needs_confirmation else decision.workflow_kind
    assert actual == expected
