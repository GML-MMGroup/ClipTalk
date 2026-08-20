from __future__ import annotations

import copy
import json
import math
import re
import uuid
from typing import Any, Iterable


DIALOGUE_INDEX_VERSION = "dialogue-index-v1"
DIALOGUE_BOUNDARY_VERSION = "dialogue-boundary-v1"
DIALOGUE_ACTS = frozenset({
    "question", "answer", "explanation", "instruction", "backchannel",
    "greeting", "transition", "closing", "statement", "unknown",
})
DIALOGUE_ROLES = frozenset({"questioner", "answerer", "instructor", "student", "speaker"})


def _number(value: Any, default: float = 0.0) -> float:
    try:
        result = float(value)
    except (TypeError, ValueError):
        return default
    return result if math.isfinite(result) else default


def source_dialogue_turns(segments: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    """Create grounded turns without assigning any semantic dialogue role."""
    turns: list[dict[str, Any]] = []
    for position, source in enumerate(segments):
        if not isinstance(source, dict):
            continue
        start = max(0.0, _number(source.get("start")))
        end = max(start, _number(source.get("end"), start))
        text = str(source.get("text") or "").strip()
        if end <= start or not text:
            continue
        speakers = [
            str(value).strip() for value in source.get("speakers") or []
            if str(value).strip()
        ]
        speaker = str(source.get("speaker") or (speakers[0] if speakers else "")).strip()
        source_id = str(source.get("id") or f"segment_{position:05d}")
        words = [
            copy.deepcopy(item) for item in source.get("words") or []
            if isinstance(item, dict)
            and _number(item.get("end")) > _number(item.get("start"))
        ]
        turns.append({
            "id": f"turn_{position:05d}",
            "sourceSegmentId": source_id,
            "sourceSegmentIds": [source_id],
            "start": round(start, 3),
            "end": round(end, 3),
            "duration": round(end - start, 3),
            "speaker": speaker or None,
            "text": text[:1200],
            "words": words,
            "dialogueAct": "unknown",
            "dialogueRole": "speaker",
            "backchannel": False,
            "respondsToIds": [],
            "semanticConfidence": 0.0,
        })
    turns.sort(key=lambda item: (item["start"], item["end"], item["id"]))
    return turns


def dialogue_graph_prompt(turns: list[dict[str, Any]]) -> str:
    payload = [{
        "id": item.get("id"),
        "start": item.get("start"),
        "end": item.get("end"),
        "speaker": item.get("speaker"),
        "text": str(item.get("text") or "")[:500],
    } for item in turns]
    return f"""你是访谈、课堂和多人对话的语义分析器。只分析下列已经带源时间的说话轮次，不得改写时间码或创造 ID。

说话轮次：{json.dumps(payload, ensure_ascii=False)}

为每个轮次判断：
- dialogueAct：question、answer、explanation、instruction、backchannel、greeting、transition、closing、statement、unknown；
- dialogueRole：questioner、answerer、instructor、student、speaker；
- backchannel：是否只是“嗯、对、好的”等不改变主发言结构的短附和；
- respondsToIds：该轮直接回应的已有 question 轮次 ID；无法确认时为空；
- responseBlockId：属于同一个完整回答的 answer/explanation 轮次使用同一个块 ID。新问题、换回答者或话题结束必须开始新块。

语义由上下文决定，不能按某个固定 Speaker 编号假定主持人或回答者。问题后的实质回应标为 answer；回答者对同一问题的连续补充可标为 explanation 并放进同一 responseBlockId。不要把提问本身放进回答块。

仅返回 JSON：
{{"turns":[{{"id":"真实轮次ID","dialogueAct":"answer","dialogueRole":"answerer","backchannel":false,"respondsToIds":["真实问题ID"],"responseBlockId":"response_1","confidence":0.0}}]}}"""


def normalize_dialogue_graph(
    transcript_segments: Iterable[dict[str, Any]],
    model_results: Iterable[dict[str, Any]],
) -> dict[str, Any]:
    """Ground model dialogue semantics to immutable transcript turn IDs."""
    turns = source_dialogue_turns(transcript_segments)
    lookup = {str(item["id"]): item for item in turns}
    annotations: dict[str, dict[str, Any]] = {}
    model_calls = 0
    for result in model_results:
        if not isinstance(result, dict):
            continue
        model_calls += 1
        for source in result.get("turns") or []:
            if not isinstance(source, dict):
                continue
            turn_id = str(source.get("id") or "")
            if turn_id not in lookup:
                continue
            confidence = max(0.0, min(1.0, _number(source.get("confidence"))))
            if confidence < _number((annotations.get(turn_id) or {}).get("confidence"), -1.0):
                continue
            act = str(source.get("dialogueAct") or "unknown").strip().lower()
            role = str(source.get("dialogueRole") or "speaker").strip().lower()
            annotations[turn_id] = {
                "dialogueAct": act if act in DIALOGUE_ACTS else "unknown",
                "dialogueRole": role if role in DIALOGUE_ROLES else "speaker",
                "backchannel": bool(source.get("backchannel")) or act == "backchannel",
                "respondsToIds": [
                    str(value) for value in source.get("respondsToIds") or []
                    if str(value) in lookup and str(value) != turn_id
                ][:8],
                "responseBlockId": re.sub(
                    r"[^A-Za-z0-9_-]+", "_", str(source.get("responseBlockId") or "").strip(),
                )[:64],
                "confidence": confidence,
            }
    for turn in turns:
        annotation = annotations.get(str(turn["id"]))
        if not annotation:
            continue
        turn.update({
            "dialogueAct": annotation["dialogueAct"],
            "dialogueRole": annotation["dialogueRole"],
            "backchannel": annotation["backchannel"],
            "respondsToIds": annotation["respondsToIds"],
            "responseBlockId": annotation["responseBlockId"] or None,
            "semanticConfidence": round(annotation["confidence"], 4),
        })

    order = {str(item["id"]): position for position, item in enumerate(turns)}
    for turn in turns:
        turn["respondsToIds"] = [
            value for value in turn.get("respondsToIds") or []
            if order.get(value, len(turns)) < order[str(turn["id"])]
            and lookup[value].get("dialogueAct") == "question"
        ]

    blocks = _response_blocks(turns)
    edges = [{
        "id": f"edge_{question_id}_{turn['id']}",
        "type": "responds_to",
        "from": str(turn["id"]),
        "to": question_id,
    } for turn in turns for question_id in turn.get("respondsToIds") or []]
    classified = sum(item.get("dialogueAct") != "unknown" for item in turns)
    return {
        "schemaVersion": DIALOGUE_INDEX_VERSION,
        "status": "ready" if turns and classified == len(turns) else "partial" if classified else "degraded",
        "coverageComplete": bool(turns) and classified == len(turns),
        "classifiedTurnCount": classified,
        "turnCount": len(turns),
        "modelCalls": model_calls,
        "turns": turns,
        "edges": edges,
        "responseBlocks": blocks,
    }


def _response_blocks(turns: list[dict[str, Any]]) -> list[dict[str, Any]]:
    def short_backchannel(turn: dict[str, Any]) -> bool:
        if not turn.get("backchannel") or _number(turn.get("duration")) > 1.2:
            return False
        text = re.sub(r"[^\w\u3400-\u9fff]+", "", str(turn.get("text") or ""))
        chinese = re.findall(r"[\u3400-\u9fff]", text)
        token_count = len(chinese) if chinese else len(re.findall(r"[A-Za-z0-9_]+", text))
        return 0 < token_count <= (6 if chinese else 3)

    blocks: list[dict[str, Any]] = []
    by_id: dict[str, dict[str, Any]] = {}
    for position, turn in enumerate(turns):
        if turn.get("dialogueAct") not in {"answer", "explanation"} and turn.get("dialogueRole") != "answerer":
            continue
        raw_block_id = str(turn.get("responseBlockId") or "").strip()
        block: dict[str, Any] | None = by_id.get(raw_block_id) if raw_block_id else None
        if block is not None:
            previous_position = int(block["lastTurnPosition"])
            intervening = turns[previous_position + 1:position]
            same_speaker = str(block.get("speaker") or "") == str(turn.get("speaker") or "")
            has_new_question = any(item.get("dialogueAct") == "question" for item in intervening)
            bridgeable = all(short_backchannel(item) for item in intervening)
            if not same_speaker or has_new_question or (intervening and not bridgeable):
                block = None
        if block is None:
            block_id = f"response_{len(blocks):05d}"
            block = {
                "id": block_id,
                "speaker": turn.get("speaker"),
                "start": turn["start"],
                "end": turn["end"],
                "answerTurnIds": [],
                "promptTurnIds": [],
                "bridgedBackchannelTurnIds": [],
                "lastTurnPosition": position,
                "semanticConfidence": 1.0,
            }
            blocks.append(block)
            if raw_block_id:
                by_id[raw_block_id] = block
        previous_position = int(block["lastTurnPosition"])
        for item in turns[previous_position + 1:position]:
            if short_backchannel(item):
                block["bridgedBackchannelTurnIds"].append(str(item["id"]))
        block["answerTurnIds"].append(str(turn["id"]))
        block["promptTurnIds"].extend(str(value) for value in turn.get("respondsToIds") or [])
        block["promptTurnIds"] = list(dict.fromkeys(block["promptTurnIds"]))
        block["end"] = turn["end"]
        block["lastTurnPosition"] = position
        block["semanticConfidence"] = min(
            _number(block.get("semanticConfidence"), 1.0),
            _number(turn.get("semanticConfidence")),
        )
    for block in blocks:
        block.pop("lastTurnPosition", None)
        block["start"] = round(_number(block.get("start")), 3)
        block["end"] = round(_number(block.get("end")), 3)
        block["duration"] = round(block["end"] - block["start"], 3)
        block["semanticConfidence"] = round(_number(block.get("semanticConfidence")), 4)
    return blocks


def dialogue_role_matches(
    graph: dict[str, Any], predicate: dict[str, Any],
) -> list[dict[str, Any]]:
    """Materialize grounded answer/question ranges from a typed dialogue graph."""
    role = str(predicate.get("role") or (predicate.get("attributes") or {}).get("role") or "answerer").lower()
    dialogue_mode = str(
        predicate.get("dialogueMode") or (predicate.get("attributes") or {}).get("dialogueMode") or ""
    ).lower()
    if dialogue_mode == "question_only":
        role = "questioner"
        segment_unit = "turn"
    elif dialogue_mode in {"answer_only", "qa_pair", "qa_split"}:
        role = "answerer"
        segment_unit = "response_block"
    segment_unit = str(
        predicate.get("segmentUnit") or (predicate.get("attributes") or {}).get("segmentUnit")
        or ("response_block" if role == "answerer" else "turn")
    ).lower()
    if dialogue_mode == "question_only":
        segment_unit = "turn"
    elif dialogue_mode in {"answer_only", "qa_pair", "qa_split"}:
        segment_unit = "response_block"
    include_prompt = bool(predicate.get("includePrompt") or dialogue_mode == "qa_pair")
    speaker_ref = str(predicate.get("speakerRef") or predicate.get("speaker") or "").strip().casefold()
    turns = [item for item in graph.get("turns") or [] if isinstance(item, dict)]
    lookup = {str(item.get("id") or ""): item for item in turns}
    candidates: list[dict[str, Any]] = []
    if role == "answerer" and segment_unit == "response_block":
        rows = [item for item in graph.get("responseBlocks") or [] if isinstance(item, dict)]
        if bool(predicate.get("requirePromptRelation", True)):
            rows = [item for item in rows if item.get("promptTurnIds")]
        if speaker_ref:
            rows = [
                item for item in rows
                if any(
                    str(lookup.get(str(turn_id), {}).get("speaker") or "").strip().casefold() == speaker_ref
                    for turn_id in item.get("answerTurnIds") or []
                )
            ]
    else:
        act = "question" if role == "questioner" else ""
        selected = [
            item for item in turns
            if (act and item.get("dialogueAct") == act)
            or (not act and str(item.get("dialogueRole") or "") == role)
        ]
        if speaker_ref:
            selected = [
                item for item in selected
                if str(item.get("speaker") or "").strip().casefold() == speaker_ref
            ]
        rows = [{
            "id": f"response_{item['id']}",
            "speaker": item.get("speaker"), "start": item.get("start"), "end": item.get("end"),
            "answerTurnIds": [str(item["id"])],
            "promptTurnIds": list(item.get("respondsToIds") or []),
            "bridgedBackchannelTurnIds": [],
            "semanticConfidence": item.get("semanticConfidence"),
        } for item in selected]
    for position, row in enumerate(rows, 1):
        answer_ids = [str(value) for value in row.get("answerTurnIds") or [] if str(value) in lookup]
        prompt_ids = [str(value) for value in row.get("promptTurnIds") or [] if str(value) in lookup]
        answer_turns = [lookup[value] for value in answer_ids]
        prompt_turns = [lookup[value] for value in prompt_ids]
        if not answer_turns:
            continue
        start = min(_number(item.get("start")) for item in answer_turns)
        end = max(_number(item.get("end")) for item in answer_turns)
        if include_prompt and prompt_turns:
            start = min(start, min(_number(item.get("start")) for item in prompt_turns))
        target_ranges = [{
            "start": round(_number(item.get("start")), 3),
            "end": round(_number(item.get("end")), 3),
            "turnId": str(item.get("id") or ""),
            "speaker": item.get("speaker"),
        } for item in answer_turns]
        confidence = min(
            (_number(item.get("semanticConfidence")) for item in answer_turns), default=0.0,
        )
        has_words = all(bool(item.get("words")) for item in answer_turns)
        evidence_refs = [{
            "type": "dialogue_turn", "id": str(item["id"]),
            "start": item["start"], "end": item["end"],
        } for item in answer_turns]
        pair_id = str(row.get("responseBlockId") or row.get("id") or answer_ids[0])
        base_candidate = {
            "id": f"match_{uuid.uuid4().hex[:12]}",
            "unitId": str(row.get("id") or answer_ids[0]),
            "matchedUnitIds": answer_ids,
            "matchedSegmentIds": [
                str(segment_id) for item in answer_turns
                for segment_id in item.get("sourceSegmentIds") or [] if segment_id
            ],
            "start": round(start, 3), "end": round(end, 3),
            "duration": round(end - start, 3),
            "title": ("完整回答" if role == "answerer" else "提问") + f" · 第 {position} 段",
            "score": round(max(.55, confidence) * 100, 1),
            "retrievalScore": round(max(.55, confidence), 3),
            "evidenceConfidence": round(confidence, 3),
            "boundaryConfidence": .94 if has_words else .84,
            "scoreVersion": "content-score-v2-separated",
            "calibrated": bool(has_words and confidence >= .8),
            "reason": "LLM 对话图确认该轮次属于完整回答" if role == "answerer" else "LLM 对话图确认该轮次属于提问",
            "matchedEvidence": "回答轮次与前置问题通过对话关系落地" if prompt_ids else "对话角色已落地到逐字稿轮次",
            "evidenceType": "speech", "matchedModalities": ["speech"],
            "recallChannels": ["dialogue_graph", "speech_timestamps"],
            "evidenceRefs": evidence_refs,
            "evidenceTimes": [round((_number(item.get("start")) + _number(item.get("end"))) / 2, 3) for item in answer_turns],
            "transcriptExcerpt": " ".join(str(item.get("text") or "") for item in answer_turns)[:1200],
            "speaker": str(row.get("speaker") or "") or None,
            "speechUnits": copy.deepcopy(answer_turns),
            "targetSpeechRanges": target_ranges,
            "promptTurnIds": prompt_ids,
            "answerTurnIds": answer_ids,
            "dialogueTurnIds": [*prompt_ids, *answer_ids],
            "bridgedBackchannelTurnIds": list(row.get("bridgedBackchannelTurnIds") or []),
            "boundaryStatus": "complete_response" if role == "answerer" else "dialogue_turn",
            "boundarySource": "dialogue_word_timestamps" if has_words else "dialogue_turn_timestamps",
            "boundaryRevision": DIALOGUE_BOUNDARY_VERSION,
            "boundaryDiagnostics": {
                "includePrompt": include_prompt,
                "interruptionPolicy": str(predicate.get("interruptionPolicy") or "bridge_backchannel"),
                "targetRangeCount": len(target_ranges),
                "bridgedBackchannelCount": len(row.get("bridgedBackchannelTurnIds") or []),
            },
            "matchType": "dialogue_response_block" if role == "answerer" else "dialogue_role_turn",
            "dialoguePairId": pair_id,
            "responseBlockId": pair_id,
            "questionTurnIds": prompt_ids,
            "pairRole": "answer" if role == "answerer" else "question",
            "dialogueMode": dialogue_mode or ("answer_only" if role == "answerer" else "question_only"),
            "confidence": round(confidence, 3),
            "requiresReview": confidence < .8 or not bool(graph.get("coverageComplete")),
            "selected": confidence >= .82 and bool(graph.get("coverageComplete")),
        }
        if dialogue_mode == "qa_split" and prompt_turns:
            question_start = min(_number(item.get("start")) for item in prompt_turns)
            question_end = max(_number(item.get("end")) for item in prompt_turns)
            question_ranges = [{
                "start": round(_number(item.get("start")), 3),
                "end": round(_number(item.get("end")), 3),
                "turnId": str(item.get("id") or ""),
                "speaker": item.get("speaker"),
            } for item in prompt_turns]
            question_candidate = copy.deepcopy(base_candidate)
            question_candidate.update({
                "id": f"match_{uuid.uuid4().hex[:12]}",
                "unitId": f"question_{pair_id}",
                "matchedUnitIds": prompt_ids,
                "matchedSegmentIds": [
                    str(segment_id) for item in prompt_turns
                    for segment_id in item.get("sourceSegmentIds") or [] if segment_id
                ],
                "start": round(question_start, 3),
                "end": round(question_end, 3),
                "duration": round(question_end - question_start, 3),
                "title": f"提问 · 第 {position} 段",
                "transcriptExcerpt": " ".join(str(item.get("text") or "") for item in prompt_turns)[:1200],
                "speaker": str(prompt_turns[0].get("speaker") or "") or None,
                "speechUnits": copy.deepcopy(prompt_turns),
                "targetSpeechRanges": question_ranges,
                "evidenceRefs": [{
                    "type": "dialogue_turn", "id": str(item["id"]),
                    "start": item["start"], "end": item["end"],
                } for item in prompt_turns],
                "evidenceTimes": [round((_number(item.get("start")) + _number(item.get("end"))) / 2, 3) for item in prompt_turns],
                "questionTurnIds": prompt_ids,
                "answerTurnIds": answer_ids,
                "dialogueTurnIds": prompt_ids,
                "pairRole": "question",
                "dialogueMode": "qa_split",
                "matchType": "dialogue_question_pair",
                "boundaryStatus": "dialogue_turn",
                "boundarySource": "dialogue_word_timestamps" if all(bool(item.get("words")) for item in prompt_turns) else "dialogue_turn_timestamps",
            })
            base_candidate["dialogueMode"] = "qa_split"
            candidates.append(question_candidate)
        if dialogue_mode == "qa_pair":
            base_candidate["pairRole"] = "pair"
            base_candidate["matchType"] = "dialogue_qa_pair"
            base_candidate["title"] = f"完整问答 · 第 {position} 段"
        candidates.append(base_candidate)
    return candidates
