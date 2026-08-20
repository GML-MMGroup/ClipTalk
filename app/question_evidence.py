from __future__ import annotations

import copy
import re
import uuid
from typing import Any, Iterable


QUESTION_SOURCES = frozenset({"all", "spoken", "screen"})


def _number(value: Any, default: float = 0.0) -> float:
    try:
        result = float(value)
    except (TypeError, ValueError):
        return default
    return result if result == result and abs(result) != float("inf") else default


def _normal_text(value: Any) -> str:
    return re.sub(
        r"[^0-9a-z\u3400-\u9fff]+", "", str(value or "").casefold(),
    )


def _question_text(match: dict[str, Any]) -> str:
    return str(
        match.get("questionText") or match.get("transcriptExcerpt")
        or match.get("matchedEvidence") or ""
    ).strip()


def _text_similarity(left: str, right: str) -> float:
    a, b = _normal_text(left), _normal_text(right)
    if not a or not b:
        return 0.0
    if a in b or b in a:
        return min(len(a), len(b)) / max(len(a), len(b))
    left_grams = {a[index:index + 2] for index in range(max(0, len(a) - 1))}
    right_grams = {b[index:index + 2] for index in range(max(0, len(b) - 1))}
    return len(left_grams & right_grams) / max(1, len(left_grams | right_grams))


def _intervals_overlap(left: dict[str, Any], right: dict[str, Any], gap: float = 0.0) -> bool:
    left_start = _number(left.get("start"))
    left_end = max(left_start, _number(left.get("end"), left_start))
    right_start = _number(right.get("start"))
    right_end = max(right_start, _number(right.get("end"), right_start))
    return left_start <= right_end + gap and right_start <= left_end + gap


def _screen_canvas(
    ocr_units: Iterable[dict[str, Any]], video: dict[str, Any] | None,
) -> tuple[float, float]:
    boxes = [
        list(unit.get("box") or []) for unit in ocr_units
        if isinstance(unit, dict) and len(unit.get("box") or []) >= 4
    ]
    maximum_right = max((_number(box[2]) for box in boxes), default=1.0)
    maximum_bottom = max((_number(box[3]) for box in boxes), default=1.0)
    video = video if isinstance(video, dict) else {}
    video_width = _number(video.get("width"))
    video_height = _number(video.get("height"))
    aspect = video_width / video_height if video_width > 0 and video_height > 0 else 16 / 9
    if maximum_right <= 1.5 and maximum_bottom <= 1.5:
        return 1.0, 1.0
    width = max(1.0, maximum_right, maximum_bottom * aspect)
    height = max(1.0, maximum_bottom, width / max(.1, aspect))
    return width, height


def _box_geometry(
    box: Iterable[Any] | None, canvas: tuple[float, float],
) -> tuple[float, float, float, float]:
    values = list(box or [])
    if len(values) < 4:
        return 0.0, 0.0, .5, .5
    width, height = canvas
    x1, y1, x2, y2 = (_number(value) for value in values[:4])
    return (
        max(0.0, x2 - x1) / max(1.0, width),
        max(0.0, y2 - y1) / max(1.0, height),
        (x1 + x2) * .5 / max(1.0, width),
        (y1 + y2) * .5 / max(1.0, height),
    )


def _screen_question_score(
    text: str, unit: dict[str, Any], canvas: tuple[float, float],
) -> tuple[float, list[str], str]:
    value = str(text or "").strip()
    compact = _normal_text(value)
    if not compact:
        return 0.0, [], "question_text"
    score = 0.0
    signals: list[str] = []
    if "?" in value or "？" in value:
        score += .62
        signals.append("question_punctuation")
    if re.search(
        r"(?:吗|什么|为什么|为何|如何|怎么|是否|能否|可否|哪个|哪些|谁|哪里|哪儿|多少|几(?:个|次|年|月|天|种|位)?|怎样|请问|谈谈|介绍一下)",
        value,
    ):
        score += .52
        signals.append("interrogative_form")
    if re.search(r"(?:问题|提问|采访问题|Q\s*&?\s*A|Q\s*：|Q\s*:)" , value, re.I):
        score += .7
        signals.append("question_label")
    # A stable OCR track is stronger evidence than a one-frame subtitle hit.
    evidence_times = unit.get("evidenceTimes") or []
    if len(evidence_times) >= 2 or _number(unit.get("end")) - _number(unit.get("start")) >= .55:
        score += .12
        signals.append("stable_ocr_track")
    width, height, _, center_y = _box_geometry(unit.get("box"), canvas)
    is_bottom_subtitle = center_y >= .78 and height <= .1
    is_question_card = (
        not is_bottom_subtitle and .18 <= center_y <= .82
        and (height >= .075 or (width >= .42 and height >= .045))
    )
    is_top_overlay = center_y <= .28 and height <= .1
    screen_role = "question_card" if is_question_card else "question_overlay" if is_top_overlay else "question_text"
    if is_question_card:
        score += .25
        signals.append("prominent_question_card")
    elif is_top_overlay and "interrogative_form" in signals:
        score += .08
        signals.append("question_header_region")
    if is_bottom_subtitle and "question_punctuation" not in signals and "question_label" not in signals:
        score -= .4
        signals.append("subtitle_like_region")
    # Keep the threshold low enough for Chinese question cards without a
    # question mark, while still rejecting ordinary one-word OCR noise.
    if len(compact) < 3 and "question_label" not in signals:
        score = 0.0
    return max(0.0, min(1.0, score)), signals, screen_role


def _shot_ids(unit: dict[str, Any], shots: Iterable[dict[str, Any]]) -> list[str]:
    start, end = _number(unit.get("start")), _number(unit.get("end"), _number(unit.get("start")))
    return [
        str(shot.get("id")) for shot in shots
        if isinstance(shot, dict) and shot.get("id")
        and _number(shot.get("start")) < end + .02
        and _number(shot.get("end"), _number(shot.get("start"))) > start - .02
    ]


def _linked_question_card_matches(
    matches: list[dict[str, Any]], ocr_units: list[dict[str, Any]],
    shots: list[dict[str, Any]], canvas: tuple[float, float],
) -> list[dict[str, Any]]:
    ordered_shots = sorted(
        (item for item in shots if isinstance(item, dict) and item.get("id")),
        key=lambda item: (_number(item.get("start")), _number(item.get("end"))),
    )
    positions = {str(item["id"]): position for position, item in enumerate(ordered_shots)}
    linked: list[dict[str, Any]] = []
    linked_keys: set[tuple[str, str]] = set()
    for overlay in matches:
        if overlay.get("screenTextRole") != "question_overlay":
            continue
        overlay_positions = [
            positions[str(value)] for value in overlay.get("shotIds") or []
            if str(value) in positions
        ]
        if not overlay_positions or min(overlay_positions) <= 0:
            continue
        previous_shot = ordered_shots[min(overlay_positions) - 1]
        shot_start = _number(previous_shot.get("start"))
        shot_end = _number(previous_shot.get("end"), shot_start)
        if shot_end - shot_start > 8.0:
            continue
        card_units: list[dict[str, Any]] = []
        for unit in ocr_units:
            if not isinstance(unit, dict):
                continue
            unit_start = _number(unit.get("start"))
            unit_end = _number(unit.get("end"), unit_start)
            if unit_start >= shot_end + .02 or unit_end <= shot_start - .02:
                continue
            width, height, _, center_y = _box_geometry(unit.get("box"), canvas)
            if not (.12 <= center_y <= .84) or center_y >= .78 and height <= .1:
                continue
            if width < .07 or len(_normal_text(unit.get("text"))) < 2:
                continue
            card_units.append(unit)
        if not card_units:
            continue
        card_units.sort(key=lambda item: (
            _box_geometry(item.get("box"), canvas)[3],
            _box_geometry(item.get("box"), canvas)[2],
        ))
        card_text = "".join(str(item.get("text") or "").strip() for item in card_units)
        if _text_similarity(card_text, _question_text(overlay)) < .3:
            continue
        previous_id = str(previous_shot.get("id"))
        linked_key = (previous_id, _normal_text(_question_text(overlay)))
        if linked_key in linked_keys:
            continue
        if any(
            item.get("screenTextRole") == "question_card"
            and previous_id in {str(value) for value in item.get("shotIds") or []}
            and _text_similarity(_question_text(item), _question_text(overlay)) >= .3
            for item in matches
        ):
            continue
        unit_ids = [str(item.get("id") or "") for item in card_units if item.get("id")]
        evidence_times = sorted({
            round(_number(value), 3)
            for item in card_units for value in item.get("evidenceTimes") or [item.get("start")]
        })
        linked_keys.add(linked_key)
        linked.append({
            **copy.deepcopy(overlay),
            "id": f"match_{uuid.uuid4().hex[:12]}",
            "unitId": f"question_card_{previous_id}",
            "matchedUnitIds": unit_ids,
            "start": round(min((_number(item.get("start")) for item in card_units), default=shot_start), 3),
            "end": round(max((_number(item.get("end"), _number(item.get("start"))) for item in card_units), default=shot_end), 3),
            "matchedEvidence": card_text[:500],
            "questionText": _question_text(overlay)[:1000],
            "evidenceRefs": [{
                "type": "ocr", "id": str(item.get("id")),
                "start": round(_number(item.get("start")), 3),
                "end": round(_number(item.get("end"), _number(item.get("start"))), 3),
            } for item in card_units if item.get("id")],
            "evidenceTimes": evidence_times,
            "shotIds": [previous_id],
            "screenTextRole": "question_card",
            "recallChannels": list(dict.fromkeys([
                *(overlay.get("recallChannels") or []), "adjacent_question_card_text",
            ])),
            "reason": "相邻短镜头中的多行文字与后续问题标题一致",
            "confidence": round(max(.78, _number(overlay.get("confidence")) - .05), 3),
            "evidenceConfidence": round(max(.78, _number(overlay.get("evidenceConfidence")) - .05), 3),
        })
    return linked


def _screen_question_matches(
    ocr_units: Iterable[dict[str, Any]], shots: Iterable[dict[str, Any]],
    video: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    ocr_units = list(ocr_units)
    shots = list(shots)
    canvas = _screen_canvas(ocr_units, video)
    matches: list[dict[str, Any]] = []
    for unit in ocr_units:
        if not isinstance(unit, dict):
            continue
        text = str(unit.get("text") or "").strip()
        score, signals, screen_role = _screen_question_score(text, unit, canvas)
        if score < .55:
            continue
        start = _number(unit.get("start"))
        end = max(start + .2, _number(unit.get("end"), start))
        unit_id = str(unit.get("id") or f"ocr_question_{len(matches):05d}")
        shot_ids = _shot_ids(unit, shots)
        matches.append({
            "id": f"match_{uuid.uuid4().hex[:12]}",
            "unitId": unit_id,
            "matchedUnitIds": [unit_id],
            "matchedSegmentIds": [],
            "start": round(start, 3), "end": round(end, 3),
            "duration": round(end - start, 3),
            "title": f"画面问题 · {text[:54]}",
            "score": round(score * 100, 1),
            "retrievalScore": round(score, 3),
            "evidenceConfidence": round(score, 3),
            "boundaryConfidence": .86 if len(unit.get("evidenceTimes") or []) >= 2 else .7,
            "scoreVersion": "question-evidence-v1",
            "calibrated": False,
            "reason": "OCR 文字与问题结构/问题卡信号匹配",
            "matchedEvidence": text[:500],
            "questionText": text[:1000],
            "questionSource": "screen",
            "questionSources": ["screen"],
            "evidenceType": "screen_question",
            "matchedModalities": ["ocr"],
            "recallChannels": ["ocr_question_structure", *signals],
            "evidenceRefs": [{
                "type": "ocr", "id": unit_id, "start": round(start, 3), "end": round(end, 3),
            }],
            "evidenceTimes": [round(_number(value), 3) for value in unit.get("evidenceTimes") or [start]],
            "transcriptExcerpt": "",
            "speaker": None,
            "speechUnits": [],
            "shotIds": shot_ids,
            "screenTextRole": screen_role,
            "boundaryStatus": "screen_text_track",
            "matchType": "screen_question",
            "confidence": round(score, 3),
            "boundarySource": "ocr_stable_range",
            "requiresReview": score < .75,
            "selected": score >= .78,
        })
    matches.extend(_linked_question_card_matches(matches, ocr_units, shots, canvas))
    return _consolidate_screen_question_matches(matches, shots)


def _merge_question_match(left: dict[str, Any], right: dict[str, Any]) -> dict[str, Any]:
    result = copy.deepcopy(left)
    result["start"] = round(min(_number(left.get("start")), _number(right.get("start"))), 3)
    result["end"] = round(max(_number(left.get("end")), _number(right.get("end"))), 3)
    result["duration"] = round(result["end"] - result["start"], 3)
    result["matchedUnitIds"] = list(dict.fromkeys([
        *(left.get("matchedUnitIds") or [left.get("unitId")]),
        *(right.get("matchedUnitIds") or [right.get("unitId")]),
    ]))
    result["evidenceRefs"] = list({
        (str(ref.get("type") or ""), str(ref.get("id") or "")): copy.deepcopy(ref)
        for ref in [*(left.get("evidenceRefs") or []), *(right.get("evidenceRefs") or [])]
        if isinstance(ref, dict) and ref.get("id")
    }.values())
    result["evidenceTimes"] = sorted(set([
        *(_number(value) for value in left.get("evidenceTimes") or []),
        *(_number(value) for value in right.get("evidenceTimes") or []),
    ]))
    result["matchedModalities"] = list(dict.fromkeys([
        *(left.get("matchedModalities") or []), *(right.get("matchedModalities") or []),
    ]))
    result["questionSources"] = list(dict.fromkeys([
        *(left.get("questionSources") or [left.get("questionSource")]),
        *(right.get("questionSources") or [right.get("questionSource")]),
    ]))
    result["questionSource"] = "both" if len(result["questionSources"]) > 1 else result["questionSources"][0]
    result["evidenceType"] = "audiovisual_question" if result["questionSource"] == "both" else result.get("evidenceType")
    result["matchType"] = "multi_evidence" if result["questionSource"] == "both" else result.get("matchType")
    result["score"] = round(max(_number(left.get("score")), _number(right.get("score"))), 1)
    result["confidence"] = round(max(_number(left.get("confidence")), _number(right.get("confidence"))), 3)
    result["evidenceConfidence"] = round(max(_number(left.get("evidenceConfidence")), _number(right.get("evidenceConfidence"))), 3)
    result["boundaryConfidence"] = round(min(_number(left.get("boundaryConfidence"), .5), _number(right.get("boundaryConfidence"), .5)), 3)
    result["requiresReview"] = bool(left.get("requiresReview") or right.get("requiresReview"))
    result["selected"] = bool(left.get("selected") or right.get("selected"))
    if len(_normal_text(_question_text(right))) > len(_normal_text(_question_text(result))):
        result["questionText"] = _question_text(right)[:1000]
        result["matchedEvidence"] = str(
            right.get("matchedEvidence") or _question_text(right)
        )[:500]
    if not result.get("transcriptExcerpt") and right.get("transcriptExcerpt"):
        result["transcriptExcerpt"] = str(right.get("transcriptExcerpt"))[:800]
    result["recallChannels"] = list(dict.fromkeys([
        *(left.get("recallChannels") or []), *(right.get("recallChannels") or []), "question_evidence_union",
    ]))
    result["boundarySource"] = "question_evidence_union"
    return result


def _shot_positions(shots: Iterable[dict[str, Any]]) -> dict[str, int]:
    ordered = sorted(
        (item for item in shots if isinstance(item, dict) and item.get("id")),
        key=lambda item: (_number(item.get("start")), _number(item.get("end"))),
    )
    return {str(item["id"]): position for position, item in enumerate(ordered)}


def _same_screen_question_occurrence(
    left: dict[str, Any], right: dict[str, Any], shot_positions: dict[str, int],
) -> bool:
    similarity = _text_similarity(_question_text(left), _question_text(right))
    left_shots = {str(value) for value in left.get("shotIds") or []}
    right_shots = {str(value) for value in right.get("shotIds") or []}
    if left_shots & right_shots:
        return similarity >= .45
    adjacent_shots = any(
        abs(shot_positions[left_id] - shot_positions[right_id]) <= 1
        for left_id in left_shots if left_id in shot_positions
        for right_id in right_shots if right_id in shot_positions
    )
    if adjacent_shots and similarity >= .3:
        return True
    return _intervals_overlap(left, right, gap=4.0) and similarity >= .5


def _question_read_seconds(text: str) -> float:
    # Enough time to read a question card without extending through the
    # interview answer that may keep the same question as a small header.
    return max(2.2, min(5.5, 1.6 + len(_normal_text(text)) / 7.0))


def _screen_group_boundary(
    items: list[dict[str, Any]], shots: list[dict[str, Any]],
) -> tuple[float, float, str, str, float]:
    shot_lookup = {
        str(item.get("id")): item for item in shots
        if isinstance(item, dict) and item.get("id")
    }
    cards = [item for item in items if item.get("screenTextRole") == "question_card"]
    anchors = cards or items
    anchor = min(anchors, key=lambda item: _number(item.get("start")))
    evidence_times = sorted(
        _number(value) for item in anchors for value in item.get("evidenceTimes") or []
    )
    first_evidence = evidence_times[0] if evidence_times else _number(anchor.get("start"))
    last_evidence = evidence_times[-1] if evidence_times else _number(anchor.get("end"), first_evidence)
    reading_seconds = _question_read_seconds(max(
        (_question_text(item) for item in items), key=lambda value: len(_normal_text(value)), default="",
    ))
    anchor_shots = [
        shot_lookup[str(shot_id)] for item in anchors for shot_id in item.get("shotIds") or []
        if str(shot_id) in shot_lookup
    ]
    if anchor_shots:
        shot_start = min(_number(item.get("start")) for item in anchor_shots)
        shot_end = max(_number(item.get("end"), shot_start) for item in anchor_shots)
    else:
        shot_start = min(_number(item.get("start")) for item in anchors)
        shot_end = max(_number(item.get("end"), shot_start) for item in anchors)
    if cards:
        # Short, prominent title shots are the actual question clip. Sparse
        # OCR may only recognize the completed animation near the shot end.
        if shot_end - shot_start <= 8.0:
            end = shot_end
        else:
            end = min(shot_end, max(last_evidence + .5, first_evidence + 1.0))
        start = max(shot_start, min(first_evidence - .35, end - reading_seconds))
        if end - start < min(2.0, shot_end - shot_start):
            start = max(shot_start, end - min(reading_seconds, shot_end - shot_start))
        return start, end, "screen_question_card_shot", "screen_question_card", .9

    # If a video only uses a persistent question header, expose one readable
    # window at its first occurrence rather than the full answer or every OCR
    # sample in the shot.
    same_shot_evidence = [
        value for item in items
        if set(item.get("shotIds") or []) & set(anchor.get("shotIds") or [])
        for value in item.get("evidenceTimes") or []
    ]
    start = shot_start if len(same_shot_evidence) >= 2 else max(shot_start, first_evidence - .4)
    end = min(shot_end, start + reading_seconds)
    if end - start < 1.2:
        start = max(shot_start, end - min(reading_seconds, shot_end - shot_start))
    return start, end, "screen_question_readable_window", "screen_question_header", .76


def _consolidate_screen_question_matches(
    matches: Iterable[dict[str, Any]], shots: Iterable[dict[str, Any]],
) -> list[dict[str, Any]]:
    shots = list(shots)
    positions = _shot_positions(shots)
    groups: list[list[dict[str, Any]]] = []
    for source in sorted(matches, key=lambda item: (_number(item.get("start")), _number(item.get("end")))):
        current = copy.deepcopy(source)
        target = next((
            group for group in reversed(groups)
            if any(_same_screen_question_occurrence(item, current, positions) for item in group)
        ), None)
        if target is None:
            groups.append([current])
        else:
            target.append(current)

    consolidated: list[dict[str, Any]] = []
    for group in groups:
        canonical = max(
            group,
            key=lambda item: (
                sum(
                    _normal_text(_question_text(other)) == _normal_text(_question_text(item))
                    for other in group
                ),
                _number(item.get("score")),
                len(_normal_text(_question_text(item))),
            ),
        )
        merged = copy.deepcopy(canonical)
        for item in group:
            if item.get("id") != canonical.get("id"):
                merged = _merge_question_match(merged, item)
        start, end, boundary_source, boundary_status, boundary_confidence = _screen_group_boundary(group, shots)
        merged.update({
            "start": round(start, 3), "end": round(end, 3),
            "duration": round(max(0.0, end - start), 3),
            "questionText": _question_text(canonical)[:1000],
            "matchedEvidence": str(canonical.get("matchedEvidence") or _question_text(canonical))[:500],
            "shotIds": list(dict.fromkeys(
                str(value) for item in group for value in item.get("shotIds") or []
            )),
            "screenTextRoles": list(dict.fromkeys(
                str(item.get("screenTextRole") or "question_text") for item in group
            )),
            "screenOccurrenceCount": len(group),
            "boundarySource": boundary_source,
            "boundaryStatus": boundary_status,
            "boundaryConfidence": boundary_confidence,
            "scoreVersion": "question-evidence-v2",
            "reason": "同一问题的 OCR 轨迹已按文字、位置和镜头归并",
        })
        merged["requiresReview"] = bool(
            _number(merged.get("evidenceConfidence")) < .75 or boundary_confidence < .8
        )
        merged["selected"] = bool(
            _number(merged.get("evidenceConfidence")) >= .78 and boundary_confidence >= .8
        )
        consolidated.append(merged)
    return consolidated


def _deduplicate_question_matches(matches: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    for source in sorted(matches, key=lambda item: (_number(item.get("start")), _number(item.get("end")))):
        current = copy.deepcopy(source)
        merged = False
        for index, previous in enumerate(result):
            if not _intervals_overlap(previous, current, gap=4.0):
                continue
            similarity = _text_similarity(_question_text(previous), _question_text(current))
            same_visual_shot = bool(set(previous.get("shotIds") or []) & set(current.get("shotIds") or []))
            if similarity >= .5 or (same_visual_shot and similarity >= .25):
                result[index] = _merge_question_match(previous, current)
                merged = True
                break
        if not merged:
            result.append(current)
    for position, item in enumerate(result, 1):
        item["position"] = position
    return result


def _spoken_interview_prompt_status(
    match: dict[str, Any], graph: dict[str, Any],
) -> tuple[bool, bool]:
    """Return (keep, relation_verified) for a spoken interview prompt.

    A question immediately answered by the same speaker is usually a
    rhetorical/self-question inside an answer, not the interviewer's prompt.
    """
    turns = [item for item in graph.get("turns") or [] if isinstance(item, dict)]
    lookup = {str(item.get("id") or ""): item for item in turns}
    question_ids = {
        str(value) for value in match.get("matchedUnitIds") or [] if str(value)
    }
    question_turns = [lookup[value] for value in question_ids if value in lookup]
    question_speakers = {
        str(item.get("speaker") or "").strip().casefold()
        for item in question_turns if str(item.get("speaker") or "").strip()
    }
    linked_answer_ids = {
        str(value)
        for block in graph.get("responseBlocks") or [] if isinstance(block, dict)
        and question_ids & {str(item) for item in block.get("promptTurnIds") or []}
        for value in block.get("answerTurnIds") or []
    }
    linked_answers = [lookup[value] for value in linked_answer_ids if value in lookup]
    answer_speakers = {
        str(item.get("speaker") or "").strip().casefold()
        for item in linked_answers if str(item.get("speaker") or "").strip()
    }
    if linked_answers:
        different_speaker_answer = bool(
            answer_speakers and (
                not question_speakers or any(value not in question_speakers for value in answer_speakers)
            )
        )
        return different_speaker_answer, different_speaker_answer

    confidence = _number(match.get("confidence"), _number(match.get("evidenceConfidence")))
    if confidence < .86:
        return False, False
    question_end = max((_number(item.get("end")) for item in question_turns), default=_number(match.get("end")))
    following = [
        item for item in turns
        if _number(item.get("start")) >= question_end - .02
        and _number(item.get("start")) <= question_end + 12.0
        and item.get("dialogueAct") in {"answer", "explanation"}
    ]
    if question_speakers and following:
        following_speakers = {
            str(item.get("speaker") or "").strip().casefold()
            for item in following if str(item.get("speaker") or "").strip()
        }
        if following_speakers and not any(value not in question_speakers for value in following_speakers):
            return False, False
    return True, False


def question_evidence_matches(
    graph: dict[str, Any], ocr_units: Iterable[dict[str, Any]],
    shots: Iterable[dict[str, Any]], predicate: dict[str, Any],
    video: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    source = str(
        predicate.get("source") or predicate.get("questionSource")
        or (predicate.get("attributes") or {}).get("source") or "all"
    ).strip().lower()
    if source not in QUESTION_SOURCES:
        source = "all"
    matches: list[dict[str, Any]] = []
    if source in {"all", "spoken"}:
        from .dialogue import dialogue_role_matches

        spoken_predicate = {
            **copy.deepcopy(predicate),
            "kind": "speech.dialogue_role", "role": "questioner",
            "dialogueMode": "question_only", "segmentUnit": "turn",
        }
        for match in dialogue_role_matches(graph, spoken_predicate):
            keep, relation_verified = _spoken_interview_prompt_status(match, graph)
            if not keep:
                continue
            match["questionSource"] = "spoken"
            match["questionSources"] = ["spoken"]
            match["evidenceType"] = "spoken_question"
            match["scoreVersion"] = "question-evidence-v2"
            match["interviewPromptRelationVerified"] = relation_verified
            match["recallChannels"] = list(dict.fromkeys([
                *(match.get("recallChannels") or []),
                "different_speaker_response" if relation_verified else "high_confidence_spoken_prompt",
            ]))
            if not relation_verified:
                match["requiresReview"] = True
                match["selected"] = False
            matches.append(match)
    if source in {"all", "screen"}:
        matches.extend(_screen_question_matches(ocr_units, shots, video))
    return _deduplicate_question_matches(matches)
