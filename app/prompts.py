from __future__ import annotations

import json
from typing import Any


PROMPT_VERSION = "highlight-director-v12-evidence-graph-20260813"
EDIT_PLAN_PROMPT_VERSION = "edit-plan-v8-quality-gate-20260813"
BRIEF_PROMPT_VERSION = "brief-v1-20260806"
COMPOSITION_REVIEW_PROMPT_VERSION = "composition-review-v4-multi-event-gate-20260813"

COMMON_SYSTEM_PROMPT = """你是专业视频高光导演和纪录片剪辑师。
所有判断必须来自输入中真实可见的画面、图片时间码，以及明确提供的音频或逐字稿。
不得虚构对白、人物身份、因果关系、情绪或画外事件。图片中的时间码是唯一合法时间依据。
明确提供的 SenseVoice 对白、情绪、声音事件和 Speaker 编号可作为辅助证据；Speaker 编号不代表性别，不得据此推断男女或身份。
“精彩瞬间”是一个连续源视频镜头；“事件高光”可以由多个不连续但属于同一真实事件的精彩瞬间组成。
不为凑数量或时长重复画面，不把无关事件拼在一起。不能确定时降低评分并说明证据不足。
严格返回指定 JSON 对象，不添加 Markdown、解释或额外文本。"""


def generic_content_profile(theme: str = "") -> dict[str, Any]:
    return {
        "primaryType": "综合视频",
        "secondaryTypes": [],
        "narrativeMode": "综合信号",
        "highlightDefinition": [
            "真实事件发生明显变化或转折",
            "人物反应、动作、信息或视觉证据具有独立价值",
            "镜头能够与同一事件的其他画面形成完整表达",
        ],
        "downrankConditions": ["重复画面", "黑屏或模糊画面", "没有内容变化的空镜"],
        "evidenceWeights": {"visual": 0.7, "speech": 0.2, "audio": 0.1},
        "reason": f"内容类型识别降级，按通用标准分析。用户重点：{theme.strip() or '综合判断'}",
        "fallback": True,
    }


def content_classification_prompt(*, video_duration: float, theme: str, analysis_mode: str) -> str:
    return f"""请根据全片总览联系表判断视频的主要内容类型和叙事方式。

视频总时长：{video_duration:.2f} 秒
用户关注重点：{theme.strip() or '综合判断'}
可用分析信号：{'画面、声音和可用逐字稿' if analysis_mode == 'audiovisual' else '只使用画面'}

主要类型从新闻报道、访谈口播、纪实调查、体育比赛、活动记录、Vlog、产品展示、教程、剧情、风景纯视觉、其他中选择一个，可补充最多两个次要类型。
请定义这类视频中什么算高光、什么应该降权，并给出视觉、对白、声音证据权重，三项之和应约等于 1。
新闻和访谈中的静态人物画面不应自动降权；核心观点、信息揭露和人物情绪变化都可能是高光。

仅返回：
{{"primary_type":"类型","secondary_types":["次要类型"],"narrative_mode":"对白内容/人物反应/动作过程/视觉变化/音乐节奏/综合信号","highlight_definition":["具体标准"],"downrank_conditions":["降权条件"],"evidence_weights":{{"visual":0到1,"speech":0到1,"audio":0到1}},"reason":"基于可见画面的判断依据"}}"""


def coarse_discovery_prompt(
    *,
    content_profile: dict[str, Any],
    theme: str,
    video_duration: float,
    exclusions: str,
    audio_context: str,
) -> str:
    return f"""你正在粗看一段视频的分页联系表。每格按源时间顺序排列，格子下方是真实时间码。

视频内容画像：
{json.dumps(content_profile, ensure_ascii=False)}
用户关注重点：{theme.strip() or '综合判断'}
视频总时长：{video_duration:.2f} 秒
{audio_context}
{exclusions}

请在本页寻找最多 4 个值得进入边界精修阶段的精彩瞬间。候选职责可为事件建立、关键动作、信息揭露、冲突转折、人物反应、视觉证据、事件结果或必要上下文。
评分时考虑真实事件变化、叙事或情绪价值、与其他镜头组合的价值、主体和画面质量以及重复程度。
没有逐字稿时不得声称理解具体对白。不要把普通栏目包装、重复画面、黑屏或无变化画面评为高分。
这里只找候选中心和观察范围，不决定最终剪辑边界。

仅返回：
{{"candidates":[{{"center_seconds":图片中的真实时间码,"suggested_duration":建议观察秒数,"score":0到100,"title":"具体短标题","moment_role":"事件建立/关键动作/信息揭露/冲突转折/人物反应/视觉证据/事件结果/必要上下文","possible_event":"可能所属事件","reason":"为何值得精修","evidence":["实际可见证据"]}}]}}"""


def boundary_refinement_prompt(
    *,
    content_profile: dict[str, Any],
    theme: str,
    candidate_title: str,
    candidate_role: str,
    video_duration: float,
    exclusions: str,
    speech_context: str,
) -> str:
    speech_rule = (
        f"可用的本地逐字稿如下，只用于保持表达完整：{speech_context}"
        if speech_context else
        "没有逐字稿，只能根据口型、镜头变化和画面动作判断，不得描述具体对白。"
    )
    return f"""你正在精修一个将被编排进事件高光的源视频镜头。联系表是候选附近的密集真实画面，每格带时间码。

视频内容画像：{json.dumps(content_profile, ensure_ascii=False)}
用户重点：{theme.strip() or '综合判断'}
候选标题：{candidate_title}
候选职责：{candidate_role or '待判断'}
{speech_rule}
{exclusions}

你的任务只包括确定真正可剪辑的开始和结束、标出其中不可丢失的精彩核心、删除无价值前摇拖尾、保证动作/人物反应/表达完整，并判断候选是否仍值得保留。
通常保留 3–18 秒，确有完整性需要时最长 30 秒。不要把整段节目、整段采访或整个事件当成一个镜头。
开始不要落在明显动作中段，结束不要截断仍在发展的动作或表达。只能使用联系表实际显示且位于 0 到 {video_duration:.3f} 秒的时间码。
peak_start_seconds 和 peak_end_seconds 表示该候选最有价值、缩短时必须优先保留的核心范围；必须位于 start_seconds/end_seconds 内。
minimum_keep_seconds 表示不破坏核心表达所需的最短保留时长，应小于等于完整候选时长；boundary_confidence 表示你对起止边界的把握。

仅返回：
{{"start_seconds":数字,"end_seconds":数字,"peak_start_seconds":数字,"peak_end_seconds":数字,"minimum_keep_seconds":数字,"boundary_confidence":0到1,"score":0到100,"keep":true或false,"title":"精修标题","role":"镜头职责","reason":"边界与保留依据","evidence":{{"start":"起点证据","peak":"核心价值","end":"终点证据"}}}}"""


def event_director_prompt(
    *,
    moments: list[dict[str, Any]],
    content_profile: dict[str, Any],
    theme: str,
    requested_count: int | None,
    total_target_seconds: float | None,
    transcript_available: bool,
) -> str:
    compact = [{
        "index": item["index"], "start": item["start"], "end": item["end"],
        "score": item["score"], "title": item["title"], "role": item.get("role"),
        "possibleEvent": item.get("possibleEvent"), "reason": item["reason"],
        "evidence": item.get("evidence", [])[:3],
        "audioEvidence": item.get("audioEvidence") or {},
    } for item in moments]
    return f"""你是最终事件高光导演。导演联系表中每一行对应一个候选，依次展示该候选的 START、PEAK、END 三帧，标签含 CANDIDATE 编号和真实时间码。

候选数据：
{json.dumps(compact, ensure_ascii=False)}
视频内容画像：{json.dumps(content_profile, ensure_ascii=False)}
用户关注重点：{theme.strip() or '综合判断'}
事件数量上限：{requested_count if requested_count is not None else '自动推荐'}
整批目标时长：{f'{total_target_seconds:.1f} 秒' if total_target_seconds is not None else '自动推荐'}
{'候选边界已参考逐字稿。' if transcript_available else '没有逐字稿，不得虚构对白。'}

请把属于同一真实事件的候选组合为事件高光。每组只围绕一个事件，优先包含事件建立、发展、高潮、人物反应、结果和必要上下文等互补镜头。
同时显式判断镜头故事关系：story_function 说明镜头在事件中的叙事职责；requires_candidate_indices 只列出理解本镜头前必须出现的候选；leads_to_candidate_indices 表示它自然推动到的后续；standalone 表示脱离上下文是否仍成立；emotion_direction 描述情绪变化方向。
不得因为人物或地点相同就合并不同事件；主体镜头只能属于一个事件，只有栏目开场或地点建立等公共上下文可标 reusable_anchor=true。
不重复镜头、不加入无关画面、不为目标时长破坏事件完整性。新闻、访谈和纪实默认保持因果与源时间顺序；纯视觉蒙太奇才可调整顺序。
转场默认 cut，只有明显时间跳跃或情绪缓冲才可用短 dissolve；禁止漏光、双色调、闪白、强缩放等特效。
模型只负责内容分组和优先级，本地程序将重新计算实际时长与预算。
如果用户给了事件数量上限，只返回达到质量门槛的事件；高质量事件不足时宁可少返回，也不要为了凑数加入弱事件。

仅返回：
{{"event_groups":[{{"title":"事件标题","summary":"完整事件概述","score":0到100,"priority":从1开始的整数,"reason":"归组依据","story_arc":"事件如何建立、发展并落点","moments":[{{"candidate_index":整数,"role":"事件建立/发展/高潮/人物反应/结果/上下文","story_function":"建立/因果/升级/转折/反应/结果/收束","requires_candidate_indices":[整数],"leads_to_candidate_indices":[整数],"standalone":true或false,"emotion_direction":"平稳→紧张等","essential":true或false,"reusable_anchor":true或false,"transition_in":"cut或dissolve","order":从0开始的整数}}]}}]}}
    每个 candidate_index 必须来自候选数据，组内不得重复。"""


def llm_edit_plan_prompt(
    *,
    content_profile: dict[str, Any],
    theme: str,
    target_seconds: float | None,
    scope: str,
    selected_group_ids: list[str],
    variants: list[str],
    candidates: list[dict[str, Any]],
    transcript_context: str,
    technique_policy: dict[str, Any] | None = None,
    editing_intent: dict[str, Any] | None = None,
) -> str:
    """Prompt for text-only editorial planning over already validated evidence.

    The model may only select candidate IDs and sub-ranges inside their source
    windows. It is an editor, not a timestamp generator or a media analyzer.
    """
    return f"""你是资深纪录片剪辑师，正在为已经完成视觉和语音分析的视频设计最终高光成片。

这不是候选片段拼接任务。每个 candidate 是一个“可编辑素材范围”，你必须在范围内选择最有价值的局部起止点，并重新设计镜头之间的叙事关系。

视频内容画像：{json.dumps(content_profile, ensure_ascii=False)}
用户重点：{theme.strip() or '综合判断'}
目标时长：{f'{target_seconds:.1f} 秒（允许约 ±10%，先保证表达完整）' if target_seconds else '自动推荐'}
候选范围模式：{'仅当前选择' if scope == 'selected_only' else '当前选择优先，必要时从全候选池补充'}
当前选择的事件：{json.dumps(selected_group_ids, ensure_ascii=False)}
已知语音证据：{transcript_context or '无可用逐字稿，不得虚构对白'}
允许使用的剪辑手法：{json.dumps(technique_policy or {}, ensure_ascii=False)}
用户剪辑约束（hardConstraints 必须满足，softGoals 用于排序）：
{json.dumps(editing_intent or {}, ensure_ascii=False)}

候选素材数据（时间码均为源视频真实时间，start/end 是允许使用的边界）：
{json.dumps(candidates, ensure_ascii=False)}

请分别设计以下与当前内容类型匹配的版本：{json.dumps(variants, ensure_ascii=False)}

版本名称本身就是策略约束。你必须先说明每个版本针对当前素材采用的取舍，再据此设计真实不同的镜头结构；不能把同一组镜头只改一点裁剪长度就伪装成新版本。
候选中的 evidenceFacts 是 VLM/SenseVoice 的可追溯事实，evidenceScores 是多维价值分，relations 是镜头依赖关系，safeRanges 是可安全裁剪范围，uncertainty 表示尚未完全确认的内容。优先使用高价值、低不确定且有完整关系链的证据；不要把模型推断当成事实。
如果候选池足够，每个版本至少更换一个候选或明显改变镜头结构；候选不足时如实说明，不要制造伪差异。

编辑原则：
1. 先设计开场、上下文、发展、高潮、人物反应、结果/结尾，再决定每个镜头保留多长；结尾只在素材有自然结束或情绪落点时使用，不要硬塞无关镜头。
2. 每个镜头可以只保留候选范围中的一小段，也可以舍弃；不能默认使用整个候选。
3. source_start/source_end 必须严格位于对应 candidate 的 start/end 内，且 source_end 大于 source_start。
4. 不截断完整对白、动作高潮或人物反应；删除无价值前摇和拖尾。
5. 新闻、访谈、纪实内容默认尊重因果关系和源时间顺序；只有纯视觉蒙太奇才可重排。
6. 不重复镜头，不加入无关画面，不为了凑时长加入低价值片段。
7. 全池模式只有在当前选择无法补齐叙事结构或目标区间时才补充未选事件，并在 added_by_ai 中说明。
8. 转场默认 cut；禁止漏光、双色调、闪白和强特效。
9. narrative 只描述叙事和剪辑意图，不要在文字中自行填写预计秒数；实际时长由系统根据 source_start/source_end 计算并显示。
10. 如果目标时长无法自然达到，保留完整表达并在 warnings 说明“素材不足”，不要用重复镜头或无价值拖尾凑时长。
11. 候选池充足时优先覆盖 3 个不同事件；但完整保留 3 个事件会超过“目标时长 + max(5秒, 目标时长的15%)”时，应减少为 2 个或 1 个事件，不得为了事件数量截断对白。
12. minimumKeepSeconds 是硬下限；有对白的 candidate 必须在完整语句、停顿或说话人轮次边界切入切出。
13. playback_rate 只能使用 1.0、1.1、1.25、1.5；完整对白、关键反应、情绪停顿和高潮落点必须保持 1.0。
14. transition_in 只能为 cut、dissolve、fade_black。同一动作和连续对白用 cut；轻微时空跳跃才用短 dissolve；不同事件章节可用 fade_black。
15. audio_bridge 只能为 none、j_cut、l_cut。仅在一侧是完整对白、另一侧是同事件无对白画面且关系明确时使用，持续 0.3 到 1.2 秒。
16. 冷开场默认不重复正文源区间；严肃新闻和纪实不得用脱离上下文的金句制造悬念。
17. 所有 hardConstraints 是硬约束：不得使用 contentExclusions，不得遗漏明确 includeRules，不得因追求事件数量而破坏完整表达。
18. 时长不足时先补充对用户目标有贡献的上下文、反应或结果；时长过长时先移除完整的低优先级镜头，不得把每个事件都压缩成残句。
19. 每个计划必须覆盖至少两个不同事件或明确解释为何素材只支持一个事件；镜头的因果依赖必须遵守 relations，不得把结果放在必要上下文之前。
20. 如果使用 uncertainty.requiresDynamicReview=true 的镜头，必须在 warnings 中说明需复核的事实或边界；存在同等价值低不确定镜头时优先替换。
21. 一条高光成片可以包含多个真实事件章节；同一章节内部只能属于一个事件，并保持动作、对白和因果完整。章节之间必须有主题、时间、因果或情绪关系，不能仅为凑时长拼接。
22. 不同事件章节之间禁止 dissolve 和 j_cut/l_cut；大跨度章节可用短 fade_black，其他情况使用 cut。声音桥只允许发生在同一事件内部。
23. 目标时长是硬质量约束：不得超过目标 15%；短于目标 20% 以上时，只有候选证据确实不足才可返回，并必须在 warnings 明确说明，不得作为推荐方案。

仅返回以下 JSON：
{{
  "plans": [
    {{
      "label": "版本名称",
      "narrative": "成片叙事说明",
      "structure": ["hook", "context", "development", "climax", "reaction", "result"],
      "sequence": [
        {{
          "candidate_id": "候选 ID",
          "source_start": 0.0,
          "source_end": 0.0,
          "role": "hook/context/development/climax/reaction/result",
          "reason": "选择这段局部内容的理由",
          "essential": true,
          "playback_rate": 1.0,
          "speed_reason": "保持原速或轻度变速的理由",
          "transition_in": {{"type":"cut","duration":0.0,"reason":"衔接理由"}},
          "audio_bridge": {{"type":"none","duration":0.0,"reason":"声音衔接理由"}}
        }}
      ],
      "added_by_ai": ["被补充候选 ID"],
      "estimated_duration": 0.0,
      "warnings": []
    }}
  ]
}}
"""


def llm_order_prompt(*, content_profile: dict[str, Any], theme: str, candidates: list[dict[str, Any]], transcript_context: str) -> str:
    return f"""你是视频剪辑顺序编辑。只为已选镜头推荐排列顺序，不得改变、裁剪或合并任何镜头时间范围。\n\n内容画像：{json.dumps(content_profile, ensure_ascii=False)}\n用户重点：{theme.strip() or '综合判断'}\n语音证据：{transcript_context or '无'}\n已选镜头（每个 id 必须原样保留，start/end 只读）：\n{json.dumps(candidates, ensure_ascii=False)}\n\n请根据事件完整性、因果关系、情绪递进和源素材类型返回一个推荐顺序。新闻、访谈、纪实优先尊重源时间顺序；只有证据支持时才调整。不得新增、删除、修改任何镜头。\n仅返回 JSON：{{\"ordered_ids\":[\"镜头 id\"],\"reason\":\"排序理由\"}}"""


def composition_visual_review_prompt(
    *, timeline: dict[str, Any], user_goal: dict[str, Any], evidence_mode: str = "contact_sheet",
) -> str:
    evidence_note = (
        "你看到的是已经完成剪辑的实际动态成片。请连续观看动作、表情、运动和所有切点，不要把它当成静态候选图。"
        if evidence_mode == "dynamic_video" else
        "你看到的是实际成片联系表；它包含全片周期采样和每个切点前后画面，OUT 是成片时间，CUT 表示相邻镜头切点。"
    )
    return f"""你是成片画面审片导演。{evidence_note}

用户剪辑目标：{json.dumps(user_goal, ensure_ascii=False)}
实际成片时间线：{json.dumps(timeline, ensure_ascii=False)}

一条成片允许包含多个真实事件章节。请分别检查每个章节内部是否围绕同一事件、动作与表达是否完整，再检查章节之间是否存在主题、因果、时间或情绪联系。不要因为成片包含多个章节就判为“事件不完整”；只有把无关事件伪装成同一连续场景才是问题。
请检查：开场是否快速建立主题、画面信息是否可理解、动作是否截断、切点是否跳跃、景别/主体/运动是否连续、是否出现视觉重复、高潮是否成立、结尾是否有自然落点。不同事件之间使用 dissolve 或声音桥属于关键连续性问题。
如果时间线中存在 uncertainty.requiresDynamicReview=true，只选择对成片影响最大的最多 2 个镜头进行定向动态复核，判断画面事实、动作起止和高潮/结果落点是否真正成立。无法确认时 verdict 必须为 rejected，并在 issues 中给出 critical 问题；不要为普通低风险镜头增加复核项。
只能引用联系表和时间线中的真实证据；不得猜测未显示的对白，不得创建时间码，不负责直接改片。

仅返回 JSON：
{{"summary":"画面审片结论","scores":{{"content":0到100,"narrative":0到100,"rhythm":0到100,"continuity":0到100,"audiovisual":0到100,"goalMatch":0到100}},"strengths":["优点"],"uncertaintyChecks":[{{"segmentId":"真实镜头ID","verdict":"verified/rejected","actionComplete":true或false,"boundaryComplete":true或false,"evidence":"动态画面证据"}}],"issues":[{{"id":"visual_1","severity":"critical/major/minor","category":"opening/action/continuity/repetition/climax/ending","segmentIds":["真实镜头ID"],"outputTime":成片秒数,"description":"问题","evidence":"联系表证据","fixable":true或false}}]}}"""


def composition_editorial_review_prompt(
    *, timeline: dict[str, Any], visual_review: dict[str, Any], user_goal: dict[str, Any],
    candidates: list[dict[str, Any]], target_seconds: float | None,
    media_evidence: dict[str, Any] | None = None,
) -> str:
    return f"""你是最终成片审片师。请评价已经渲染的实际成片，并在确有必要时给出最多 3 个可执行返修动作。

用户剪辑目标：{json.dumps(user_goal, ensure_ascii=False)}
目标时长：{target_seconds if target_seconds else '自动'}
成片时间线（包含成片位置、源范围、逐字稿、声音证据和剪辑手法）：{json.dumps(timeline, ensure_ascii=False)}
VLM 画面审片：{json.dumps(visual_review, ensure_ascii=False)}
渲染后真实媒体检测（PCM 音轨、黑帧/冻结与切点，不是模型推测）：{json.dumps(media_evidence or {}, ensure_ascii=False)}
可用候选池（所有边界均为硬边界）：{json.dumps(candidates, ensure_ascii=False)}

重点检查内容完整性、因果和叙事、节奏、画面连续性、对白/声音连续性、用户目标匹配。成片可由多个事件章节组成：章节内部必须是同一事件，章节之间必须存在清楚的主题/因果/时间/情绪关系。不能仅因接近目标时长就给高分，也不能仅因包含多个事件章节就扣分。
返修只能引用真实 segmentId/candidateId；禁止自由创造时间范围。adjust_bounds 必须位于候选 start/end 内，不能低于 minimumKeepSeconds，不能截断 speechUnits。
remove_segment 不能删除唯一镜头；replace_segment 只能使用候选池；insert_segment 只用于补足必要上下文、故事结果或目标时长，并且只能插入候选池中尚未使用的高价值候选；afterSegmentId 为空表示放在开头。reorder_segments 必须完整保留当前镜头；完整对白、高潮、人物反应和结尾禁止变速。
没有 major/critical 且可修复的问题时 repairActions 返回空数组。不要为了凑时长加入重复或无价值素材。

仅返回 JSON：
{{"summary":"综合审片结论","overallScore":0到100,"scores":{{"content":0到100,"narrative":0到100,"rhythm":0到100,"continuity":0到100,"audiovisual":0到100,"goalMatch":0到100}},"strengths":["优点"],"issues":[{{"id":"edit_1","severity":"critical/major/minor","category":"content/narrative/rhythm/continuity/audiovisual/goal","segmentIds":["真实镜头ID"],"outputTime":成片秒数,"description":"问题","evidence":"证据","fixable":true或false}}],"repairActions":[{{"type":"adjust_bounds/remove_segment/replace_segment/insert_segment/reorder_segments/set_transition/set_audio_bridge/set_speed","segmentId":"镜头ID","replacementCandidateId":"候选ID或空","afterSegmentId":"插入位置前一个镜头ID或空","start":数字或null,"end":数字或null,"orderedSegmentIds":["完整镜头顺序"],"playbackRate":1.0或1.1或1.25,"transitionIn":{{"type":"cut/dissolve/fade_black","duration":数字}},"audioBridge":{{"type":"none/j_cut/l_cut","duration":数字}},"reason":"返修依据"}}]}}"""


def user_brief_prompt(*, filename: str, theme: str, count: str, target_seconds: str, analysis_mode: str, subtitle_mode: str = "ask", edit_mode: str = "ai_plan", structure: str = "auto") -> str:
    return f"""请把用户的视频剪辑需求整理为结构化剪辑简报。不要虚构视频内容，只整理用户明确说出的要求；未提供的字段返回空字符串、空数组或 auto。
文件：{filename}
用户重点：{theme or '综合判断'}
期望事件数量：{count}
整批目标时长：{target_seconds}
分析信号：{analysis_mode}
用户选择的字幕策略：{subtitle_mode}
用户选择的剪辑方式：{edit_mode}
用户选择的成片结构：{structure}
字幕策略、剪辑方式和成片结构如果为 ask/auto，必须保留为 ask/auto，不要擅自决定。
仅返回 JSON：{{
  "objective":"高光合集/完整叙事/信息提炼等",
  "narrativeGoal":"希望成片表达的核心目标",
  "targetDurationSeconds":数字或null,
  "eventCount":"auto"或整数,
  "focus":["人物反应"],
  "style":{{"pace":"自然/紧凑/快节奏","tone":"纪实/电影感/热血/自然","allowReorder":false}},
  "audience":"",
  "platform":"",
  "aspectRatio":"原始比例",
  "speakerFocus":[],
  "includeRules":[],
  "excludeRules":[],
  "subtitlePreference":"",
  "assumptions":[],
  "confidence":0到1
}}"""
