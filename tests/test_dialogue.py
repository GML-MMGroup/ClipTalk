from __future__ import annotations

from app.content_query import QUERY_PLAN_VERSION, compile_query_plan, predicate_modality, temporal_join_matches
from app.dialogue import dialogue_role_matches, normalize_dialogue_graph
from unittest.mock import patch


def _segments() -> list[dict]:
    return [
        {"id": "s0", "start": 0.0, "end": 1.8, "speaker": "Speaker 1", "text": "你最大的改变是什么？",
         "words": [{"text": "你", "start": 0.0, "end": .2}, {"text": "什么", "start": 1.3, "end": 1.7}]},
        {"id": "s1", "start": 2.0, "end": 5.0, "speaker": "Speaker 2", "text": "我变得更加自信了。",
         "words": [{"text": "我", "start": 2.05, "end": 2.2}, {"text": "自信", "start": 4.4, "end": 4.9}]},
        {"id": "s2", "start": 5.1, "end": 5.5, "speaker": "Speaker 1", "text": "嗯。",
         "words": [{"text": "嗯", "start": 5.15, "end": 5.4}]},
        {"id": "s3", "start": 5.6, "end": 8.0, "speaker": "Speaker 2", "text": "也更愿意主动交流。",
         "words": [{"text": "也", "start": 5.65, "end": 5.8}, {"text": "交流", "start": 7.5, "end": 7.9}]},
    ]


def _model_result() -> dict:
    return {"turns": [
        {"id": "turn_00000", "dialogueAct": "question", "dialogueRole": "questioner", "confidence": .98},
        {"id": "turn_00001", "dialogueAct": "answer", "dialogueRole": "answerer",
         "respondsToIds": ["turn_00000"], "responseBlockId": "r1", "confidence": .96},
        {"id": "turn_00002", "dialogueAct": "backchannel", "dialogueRole": "questioner",
         "backchannel": True, "confidence": .94},
        {"id": "turn_00003", "dialogueAct": "explanation", "dialogueRole": "answerer",
         "respondsToIds": ["turn_00000"], "responseBlockId": "r1", "confidence": .93},
    ]}


def test_dialogue_role_query_plan_is_first_class() -> None:
    plan = compile_query_plan({
        "predicates": [{
            "id": "answer", "kind": "speech.dialogue_role", "value": "完整回答",
            "role": "answerer", "segmentUnit": "response_block", "includePrompt": False,
            "interruptionPolicy": "bridge_backchannel",
        }],
    })
    assert plan["schemaVersion"] == QUERY_PLAN_VERSION
    assert plan["requiredOperations"] == ["dialogue.turn_graph"]
    assert plan["predicates"][0]["role"] == "answerer"
    assert predicate_modality(plan["predicates"][0]) == "speech"


def test_complete_answer_excludes_question_and_bridges_short_backchannel() -> None:
    graph = normalize_dialogue_graph(_segments(), [_model_result()])
    assert graph["coverageComplete"] is True
    assert len(graph["responseBlocks"]) == 1
    matches = dialogue_role_matches(graph, {
        "kind": "speech.dialogue_role", "role": "answerer",
        "segmentUnit": "response_block", "includePrompt": False,
        "interruptionPolicy": "bridge_backchannel",
    })
    assert len(matches) == 1
    assert (matches[0]["start"], matches[0]["end"]) == (2.0, 8.0)
    assert matches[0]["promptTurnIds"] == ["turn_00000"]
    assert matches[0]["answerTurnIds"] == ["turn_00001", "turn_00003"]
    assert matches[0]["bridgedBackchannelTurnIds"] == ["turn_00002"]
    assert "你最大的改变" not in matches[0]["transcriptExcerpt"]
    assert len(matches[0]["targetSpeechRanges"]) == 2


def test_full_qa_request_may_include_prompt_in_playback_only() -> None:
    graph = normalize_dialogue_graph(_segments(), [_model_result()])
    match = dialogue_role_matches(graph, {
        "kind": "speech.dialogue_role", "role": "answerer",
        "segmentUnit": "response_block", "includePrompt": True,
    })[0]
    assert (match["start"], match["end"]) == (0.0, 8.0)
    assert all(item["start"] >= 2.0 for item in match["targetSpeechRanges"])


def test_dialogue_modes_materialize_question_answer_pair_and_split() -> None:
    graph = normalize_dialogue_graph(_segments(), [_model_result()])
    question = dialogue_role_matches(graph, {
        "kind": "speech.dialogue_role", "dialogueMode": "question_only",
    })
    answer = dialogue_role_matches(graph, {
        "kind": "speech.dialogue_role", "dialogueMode": "answer_only",
    })
    pair = dialogue_role_matches(graph, {
        "kind": "speech.dialogue_role", "dialogueMode": "qa_pair",
    })
    split = dialogue_role_matches(graph, {
        "kind": "speech.dialogue_role", "dialogueMode": "qa_split",
    })
    assert len(question) == len(answer) == len(pair) == 1
    assert (question[0]["start"], question[0]["end"]) == (0.0, 1.8)
    assert (answer[0]["start"], answer[0]["end"]) == (2.0, 8.0)
    assert (pair[0]["start"], pair[0]["end"]) == (0.0, 8.0)
    assert {item["pairRole"] for item in split} == {"question", "answer"}
    assert len({item["dialoguePairId"] for item in split}) == 1
    assert split[0]["questionTurnIds"] == ["turn_00000"]


def test_dialogue_mode_can_bind_answerer_to_exact_speaker() -> None:
    graph = normalize_dialogue_graph(_segments(), [_model_result()])
    assert len(dialogue_role_matches(graph, {
        "kind": "speech.dialogue_role", "dialogueMode": "answer_only", "speakerRef": "Speaker 2",
    })) == 1
    assert dialogue_role_matches(graph, {
        "kind": "speech.dialogue_role", "dialogueMode": "answer_only", "speakerRef": "Speaker 1",
    }) == []


def test_answerer_requires_a_grounded_question_relation_by_default() -> None:
    graph = normalize_dialogue_graph([
        {"id": "intro", "start": 0.0, "end": 3.0, "speaker": "Speaker 1", "text": "大家好，我是本次嘉宾。"},
    ], [{"turns": [{
        "id": "turn_00000", "dialogueAct": "answer", "dialogueRole": "answerer",
        "responseBlockId": "r1", "respondsToIds": [], "confidence": .95,
    }]}])
    assert dialogue_role_matches(graph, {
        "kind": "speech.dialogue_role", "role": "answerer", "segmentUnit": "response_block",
    }) == []


def test_responds_to_relation_uses_dialogue_edges_not_time_proximity() -> None:
    plan = compile_query_plan({
        "predicates": [
            {"id": "q", "kind": "speech.semantic", "value": "最大的改变"},
            {"id": "a", "kind": "speech.dialogue_role", "value": "完整回答", "role": "answerer"},
        ],
        "relations": [{"type": "responds_to", "left": "q", "right": "a"}],
    })
    question = {
        "id": "mq", "start": 0.0, "end": 1.8, "score": 95, "confidence": .95,
        "boundaryConfidence": .9, "matchedModalities": ["speech"],
        "dialogueTurnIds": ["turn_00000"], "evidenceRefs": [{"type": "dialogue_turn", "id": "turn_00000"}],
    }
    answer = dialogue_role_matches(normalize_dialogue_graph(_segments(), [_model_result()]), {
        "kind": "speech.dialogue_role", "role": "answerer",
    })[0]
    joined = temporal_join_matches(plan, {"q": [question], "a": [answer]})
    assert len(joined) == 1
    unrelated = {**answer, "promptTurnIds": ["turn_other"]}
    assert temporal_join_matches(plan, {"q": [question], "a": [unrelated]}) == []


def test_boundary_feedback_refines_dialogue_match_without_user_time_input() -> None:
    from app import main as main_app

    graph = normalize_dialogue_graph(_segments(), [_model_result()])
    match = dialogue_role_matches(graph, {
        "kind": "speech.dialogue_role", "role": "answerer",
    })[0]
    match.update({"start": 1.8, "end": 8.2, "duration": 6.4})
    target = {
        "feedbackId": "feedback_1", "matchId": match["id"], "start": 1.8, "end": 8.2,
        "status": "pending", "refinementVersion": "boundary-refinement-v2",
    }
    job_id = "dialogue_boundary_refinement"
    job = {
        "id": job_id, "contentSearchFeedback": {
            "entries": [{"id": "feedback_1"}], "boundaryRefinementTargets": [target],
        },
    }
    main_app.jobs[job_id] = job
    try:
        with patch.object(main_app, "save_job"):
            refined = main_app._apply_boundary_refinement_feedback(
                job_id, job, {"dialogueGraph": graph}, [match],
                main_app.threading.Event(), {},
            )
        assert (refined[0]["start"], refined[0]["end"]) == (2.0, 8.0)
        assert refined[0]["boundaryRevision"] == "boundary-refinement-v2"
        resolution = main_app.jobs[job_id]["contentSearchFeedback"]["entries"][0]["resolution"]
        assert resolution["status"] == "changed"
        assert resolution["previousRange"] == {"start": 1.8, "end": 8.2}
    finally:
        main_app.jobs.pop(job_id, None)
