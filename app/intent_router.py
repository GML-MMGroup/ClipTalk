from __future__ import annotations

import re
from dataclasses import dataclass


@dataclass(frozen=True)
class IntentRoutingDecision:
    task_mode: str | None
    confidence: float
    needs_confirmation: bool
    reason: str
    source: str = "instruction_router_v1"
    workflow_kind: str | None = None
    action: str = "start_workflow"

    def public_state(self) -> dict[str, object]:
        state = {
            "resolvedTaskKind": self.task_mode,
            "routingConfidence": round(self.confidence, 3),
            "routingNeedsConfirmation": self.needs_confirmation,
            "routingReason": self.reason,
            "routingSource": self.source,
            "routingAction": self.action,
        }
        if self.workflow_kind:
            state["workflowKind"] = self.workflow_kind
        return state


_WORKFLOW_TO_TASK_MODE = {
    "highlight": "highlight",
    "content_search": "content_extract",
    "person_edit": "content_extract",
    "speaker_edit": "content_extract",
}

WORKFLOW_KINDS = frozenset(_WORKFLOW_TO_TASK_MODE)
WORKFLOW_OPTIONS = (
    {"id": "highlight", "label": "自动生成高光"},
    {"id": "content_search", "label": "查找并截取内容"},
    {"id": "person_edit", "label": "按画面人物剪辑"},
    {"id": "speaker_edit", "label": "按说话人剪辑"},
)
MODEL_ROUTING_CONFIDENCE = .78

_SPEAKER_WORKFLOW_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"(?:按|根据)(?:说话人|声音|音色|speaker).{0,10}(?:剪辑|提取|筛选|分段|出片)", re.IGNORECASE),
    re.compile(r"(?:识别|区分|选择|选|试听|确认).{0,8}(?:说话人|发言人|声音|音色|speaker)", re.IGNORECASE),
    re.compile(r"(?:speaker\s*[A-Z0-9一二三四五六七八九十]+|声音\s*[A-ZＡ-Ｚ一二三四五六七八九十]+).{0,12}(?:全部|所有|发言|说话|片段)", re.IGNORECASE),
    re.compile(r"(?:某个|指定|这个|所选)(?:说话人|发言人|声音).{0,10}(?:全部|所有|发言|说话|片段)", re.IGNORECASE),
    re.compile(r"(?:不同|多个)(?:人|说话人|发言人).{0,8}(?:说话|声音|发言).{0,8}(?:分开|区分|分离|聚类)", re.IGNORECASE),
    re.compile(r"(?:分开|区分|分离).{0,8}(?:不同|多个)?(?:人|说话人|发言人)(?:的)?(?:说话|声音|发言)", re.IGNORECASE),
)

_PERSON_WORKFLOW_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"(?:按|根据)(?:画面)?人物.{0,10}(?:剪辑|提取|筛选|分段|出片)"),
    re.compile(r"(?:选择|确认|指定|识别).{0,8}(?:画面)?人物.{0,10}(?:剪辑|出镜|片段)"),
    re.compile(r"(?:人物\s*[A-ZＡ-Ｚ0-9一二三四五六七八九十]+|所选人物|目标人物).{0,12}(?:全部|所有|每次|出镜|出现|画面)"),
    re.compile(r"(?:找出|提取|保留).{0,8}(?:这个人|该人物|目标人物).{0,8}(?:所有|全部|每次)?(?:出镜|出现|画面)"),
    re.compile(r"(?:这个人|该人物|目标人物).{0,8}(?:所有|全部|每次)(?:的)?(?:出镜|出现|画面)"),
    re.compile(r"(?:按脸|人脸|面孔).{0,12}(?:选人|选择|剪辑|剪出|提取)"),
    re.compile(r"(?:有哪些人|都有谁|识别出人物).{0,16}(?:选|选择).{0,8}(?:剪|提取|保留)"),
    re.compile(r"(?:只保留|提取|找出|剪出).{0,10}(?:红衣|黑衣|白衣|蓝衣|穿.{0,5}(?:衣服|上衣)|\S{0,6}(?:女生|男生|女人|男人)).{0,10}(?:每次|所有|全部).{0,4}(?:出现|出镜|画面)"),
)


_CONTENT_PATTERNS: tuple[tuple[re.Pattern[str], int], ...] = (
    (re.compile(r"(?:找出|查找|搜索|定位|筛出|提取|截取).{0,24}(?:片段|画面|镜头|发言|对白|内容)"), 3),
    (re.compile(r"(?:谁|哪[里段个]|什么时间|何时).{0,20}(?:说|出现|展示|发生|介绍)"), 3),
    (re.compile(r"(?:全部|所有).{0,16}(?:出现|发言|说话|提到|介绍|采访问题|提问)"), 3),
    (re.compile(r"(?:说了|说过|发言|对白|屏幕文字|字幕|OCR|Speaker|人物\s*[A-ZＡ-Ｚ])", re.IGNORECASE), 2),
    (re.compile(r"(?:开头|结尾|前半段|后半段|\d{1,2}:\d{2}|\d+\s*(?:分钟|分|秒).{0,4}(?:附近|左右))"), 1),
    (re.compile(r"(?:找|查|搜|截|提取|保留|只要)"), 1),
    (re.compile(r"\b(?:find|locate|search|extract|keep only|every time|all mentions?)\b", re.IGNORECASE), 3),
    (re.compile(r"\b(?:said|says|speaking|dialogue|transcript|on-screen text|ocr)\b", re.IGNORECASE), 2),
)

_HIGHLIGHT_PATTERNS: tuple[tuple[re.Pattern[str], int], ...] = (
    (re.compile(r"(?:高光|集锦|混剪|精彩片段|精彩瞬间|最佳镜头|高潮片段)"), 4),
    (re.compile(r"(?:生成|做|剪|制作).{0,18}(?:成片|短片|视频|合集|预告|回顾)"), 1),
    (re.compile(r"(?:浓缩|总结|节奏|情绪|氛围|视觉冲击|人物反应|动作高潮)"), 2),
    (re.compile(r"(?:最精彩|最有趣|最好看|值得保留)"), 2),
    (re.compile(r"(?:\d+\s*秒|一分钟|半分钟).{0,12}(?:高光|成片|短片|视频)"), 2),
    (re.compile(r"\b(?:highlight reel|best moments|recap|trailer|montage)\b", re.IGNORECASE), 4),
    (re.compile(r"\b(?:make|create|edit|cut).{0,24}\b(?:video|short|reel)\b", re.IGNORECASE), 2),
)


def _score(text: str, patterns: tuple[tuple[re.Pattern[str], int], ...]) -> int:
    return sum(weight for pattern, weight in patterns if pattern.search(text))


def route_editing_instruction(instruction: str, requested_mode: str = "auto") -> IntentRoutingDecision:
    """Resolve the product's single instruction into an existing workflow.

    Explicit legacy modes remain authoritative. Automatic routing is
    deliberately conservative: an ambiguous request is returned to the UI
    instead of starting an expensive analysis under the wrong workflow.
    """
    mode = str(requested_mode or "auto").strip().lower().replace("-", "_")
    if mode == "content_extract":
        return IntentRoutingDecision(mode, 1.0, False, "用户明确选择了内容探索", "explicit", "content_search")
    if mode in _WORKFLOW_TO_TASK_MODE:
        return IntentRoutingDecision(
            _WORKFLOW_TO_TASK_MODE[mode], 1.0, False, "用户明确选择了剪辑方式", "explicit", mode,
        )
    if mode != "auto":
        return IntentRoutingDecision(None, 0.0, True, "任务方向参数无效")

    text = re.sub(r"\s+", " ", str(instruction or "").strip())
    if not text:
        return IntentRoutingDecision(None, 0.0, True, "需要一句剪辑要求才能判断任务方向")

    # Person/speaker are first-class workflows only when the user explicitly
    # asks to select or exhaust one identity. A topic, interview question, or
    # an action performed by a person is still ordinary multimodal search.
    if any(pattern.search(text) for pattern in _SPEAKER_WORKFLOW_PATTERNS):
        return IntentRoutingDecision(
            "content_extract", .96, False, "要求按匿名说话人选择并提取发言", workflow_kind="speaker_edit",
        )
    if any(pattern.search(text) for pattern in _PERSON_WORKFLOW_PATTERNS):
        return IntentRoutingDecision(
            "content_extract", .96, False, "要求按画面人物选择并提取全部出镜", workflow_kind="person_edit",
        )

    content_score = _score(text, _CONTENT_PATTERNS)
    highlight_score = _score(text, _HIGHLIGHT_PATTERNS)
    strongest = max(content_score, highlight_score)
    difference = abs(content_score - highlight_score)
    if strongest < 2 or difference < 2:
        return IntentRoutingDecision(
            None,
            min(0.59, 0.35 + strongest * 0.06),
            True,
            "要求同时包含多种剪辑含义，需确认是查找内容还是自动做高光",
        )

    task_mode = "content_extract" if content_score > highlight_score else "highlight"
    confidence = min(0.98, 0.68 + difference * 0.06 + strongest * 0.015)
    reason = (
        "要求包含明确的内容定位或截取意图"
        if task_mode == "content_extract"
        else "要求包含明确的高光成片或精彩内容概括意图"
    )
    return IntentRoutingDecision(
        task_mode, confidence, False, reason,
        workflow_kind="content_search" if task_mode == "content_extract" else "highlight",
    )


def normalize_model_routing(
    instruction: str,
    prediction: dict[str, object],
    *,
    current_workflow: str = "",
    confidence_threshold: float = MODEL_ROUTING_CONFIDENCE,
) -> IntentRoutingDecision:
    """Validate an LLM decision and use local routing only as a conflict guard.

    The model is the primary classifier. Deterministic matching can force a
    confirmation when it strongly disagrees, but it never replaces the model's
    selected workflow.
    """
    workflow = str(prediction.get("workflowKind") or "").strip().lower()
    if not workflow:
        legacy_mode = str(prediction.get("taskMode") or "").strip().lower()
        workflow = "highlight" if legacy_mode == "highlight" else "content_search" if legacy_mode == "content_extract" else ""
    current = str(current_workflow or "").strip().lower()
    raw_action = str(prediction.get("action") or "").strip().lower()
    mode_specific_response = False
    if not workflow and current in WORKFLOW_KINDS and raw_action not in {
        "continue_current", "switch_workflow", "clarify", "start_workflow",
    }:
        # A mode-specific parser response is necessarily an operation inside
        # the current workflow. This also keeps older parser contracts usable
        # while the top-level LLM prompt is rolled out.
        workflow = current
        raw_action = "continue_current"
        mode_specific_response = True
    if workflow not in WORKFLOW_KINDS:
        raise ValueError("模型未返回受支持的工作流")
    try:
        confidence = float(prediction.get("confidence") or 0)
    except (TypeError, ValueError) as error:
        raise ValueError("模型未返回有效置信度") from error
    confidence = max(0.0, min(1.0, confidence))
    if mode_specific_response:
        confidence = 1.0
    if current in WORKFLOW_KINDS:
        action = raw_action if raw_action in {"continue_current", "switch_workflow", "clarify"} else (
            "continue_current" if workflow == current else "switch_workflow"
        )
        if action == "continue_current":
            workflow = current
    else:
        action = "clarify" if raw_action == "clarify" else "start_workflow"

    reason = str(prediction.get("reason") or "LLM 完成剪辑工作流判断").strip()[:160]
    model_requests_confirmation = bool(prediction.get("needsConfirmation")) or action == "clarify"
    guard = route_editing_instruction(instruction)
    guard_conflict = bool(
        not guard.needs_confirmation
        and guard.confidence >= .9
        and guard.workflow_kind in WORKFLOW_KINDS
        and guard.workflow_kind != workflow
    )
    needs_confirmation = model_requests_confirmation or confidence < confidence_threshold or guard_conflict
    if guard_conflict:
        reason = f"{reason}；本地安全校验检测到意图信号冲突"
    return IntentRoutingDecision(
        _WORKFLOW_TO_TASK_MODE[workflow], confidence, needs_confirmation,
        reason, "model_primary_v2", workflow,
        "clarify" if needs_confirmation else action,
    )
