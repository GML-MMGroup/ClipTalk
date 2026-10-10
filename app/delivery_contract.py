"""Shared, deterministic delivery constraints; never imply unavailable abilities."""
from __future__ import annotations

import math
import re


def parse_audio_operations(goal: str, affirmative: str) -> dict:
    negative_denoise = bool(re.search(r"(?:不要|无需|不需要|禁止|别)[^，,。；;]{0,8}降噪", goal))
    denoise = "降噪" in affirmative and not negative_denoise
    quieter = bool(re.search(r"(?:音量|声音)[^，,。；;]{0,10}(?:调小|小一点|降低|减小|压低)|(?:调小|降低|减小)[^，,。；;]{0,8}(?:音量|声音)", affirmative))
    louder = bool(re.search(r"(?:音量|声音)[^，,。；;]{0,10}(?:调大|大一点|提高|增大)|(?:调大|提高|增大)[^，,。；;]{0,8}(?:音量|声音)", affirmative))
    explicit_gain = re.search(r"(?:音量|声音)[^，,。；;]{0,12}?(降低|减小|提高|增大|[+-])\s*(\d+(?:\.\d+)?)\s*dB", affirmative, re.I)
    gain = -3.0 if quieter else 3.0 if louder else 0.0
    if explicit_gain:
        gain = float(explicit_gain[2]) * (-1 if explicit_gain[1] in {"降低", "减小", "-"} else 1)
    mute = bool(re.search(r"(?:静音|去掉声音|移除音轨)", affirmative)) and not re.search(r"静音(?:段|片段|部分)", affirmative)
    # A denoiser cannot isolate vocals or operate on a separate music stem.
    unsupported = []
    if re.search(r"(?:去掉|移除|删除|消除|分离)[^，,。；;]{0,8}(?:背景音乐|配乐)|(?:人声分离|分离人声)|(?:压低|降低)[^，,。；;]{0,8}(?:背景音乐|配乐)|音乐压低", affirmative):
        unsupported.append("background_music_separation")
    if abs(gain) > 24:
        unsupported.append("gain_out_of_range")
    normalize = bool(re.search(r"响度|音频优化|人声增强|声音增强|爆音|削波", affirmative))
    # Explicit gain is relative to the current master, not an instruction to
    # first normalize it back to a fixed loudness.
    return {"noiseReduction": denoise, "normalizeLoudness": normalize and not (gain or mute),
            "gainDb": gain, "mute": bool(mute), "unsupported": unsupported}


def audio_filters(operations: dict) -> list[str]:
    if operations.get("unsupported"):
        raise ValueError("当前音频处理不支持该分离/混音要求或音量范围，未用降噪代替")
    gain = float(operations.get("gainDb") or 0)
    if not math.isfinite(gain) or abs(gain) > 24:
        raise ValueError("音量调整必须在 -24 到 24 dB 之间")
    filters = ["afftdn"] if operations.get("noiseReduction") else []
    if operations.get("normalizeLoudness", operations.get("voiceFirst", False)):
        filters += ["loudnorm=I=-16:LRA=11:TP=-1.5", "alimiter=limit=0.95"]
    if gain:
        filters.append(f"volume={gain:g}dB")
    if operations.get("mute"):
        filters.append("volume=0")
    return filters or ["anull"]


DEFAULT_COVER_INTRO_SECONDS = 1.0


def cover_intro_seconds(brief: dict) -> float:
    """本次成片是否带封面片头、片头多少秒。

    产品默认合入：只要本次要求了封面(coverRequested)，成片就把已确认封面合成到开头。
    用户明确要求片头(coverIntroRequested)时尊重其指定时长，否则用统一默认值
    （此前导出 1.0、样片 1.5 两处不一致，统一为 DEFAULT_COVER_INTRO_SECONDS）。

    注意：coverIntroRequested 的「原语义」（用户明确要求片头）仍用于 agent_platform
    的 cover_intro_only_request 识别纯片头任务 —— 那里绝不能默认 True，
    否则正常剪辑需求会被误判为纯片头任务而不生成时间轴。本函数不改动那个判定。
    """
    if not isinstance(brief, dict) or not brief.get("coverRequested"):
        return 0.0
    if brief.get("coverIntroRequested"):
        return float(brief.get("coverIntroDurationSeconds") or DEFAULT_COVER_INTRO_SECONDS)
    return DEFAULT_COVER_INTRO_SECONDS


def duration_budget(brief: dict) -> dict:
    target = brief.get("targetSeconds")
    cover_intro = cover_intro_seconds(brief)
    motion = float(brief.get("motionIntroDurationSeconds") or 1.5) if brief.get("motionIntroRequested") else 0.0
    intro = cover_intro + motion
    # 产品默认合入：封面片头占用用户要求的总时长（正文相应缩短，成片不超过要求时长）。
    # 动态图文片头是附加项，仍加在正文之外 —— 只有封面片头才触发「计入总时长」。
    inclusive = bool(re.search(r"总时长|总长|包含片头|含片头|包含封面", str(brief.get("goal") or ""))) or cover_intro > 0
    if target is None:
        return {"bodySeconds": None, "finalSeconds": None, "introSeconds": intro}
    target = float(target)
    if cover_intro > 0:
        # 封面片头吃掉一部分预算：正文 = 要求时长 - 封面片头；动态片头仍附加在外。
        body = target - cover_intro
        final = body + cover_intro + motion
    elif inclusive:
        body = target - intro
        final = target
    else:
        body = target
        final = target + intro
    if not math.isfinite(target) or body <= 0:
        raise ValueError("总时长不足以容纳片头和正文，请增加时长或缩短片头")
    return {"bodySeconds": round(body, 6), "finalSeconds": round(final, 6),
            "introSeconds": intro, "toleranceSeconds": float(brief.get("durationToleranceSeconds") or 0)}
