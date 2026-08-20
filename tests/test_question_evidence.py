import unittest

from app.content_search import fallback_content_intent, parse_content_intent
from app.question_evidence import question_evidence_matches


class QuestionEvidenceTests(unittest.TestCase):
    def setUp(self):
        self.graph = {
            "coverageComplete": True,
            "turns": [{
                "id": "turn_1", "start": 1.0, "end": 2.0,
                "speaker": "Speaker 1", "text": "你为什么来这里？",
                "dialogueAct": "question", "dialogueRole": "questioner",
                "semanticConfidence": .92,
                "words": [{"start": 1.0, "end": 2.0, "text": "你为什么来这里？"}],
            }],
            "responseBlocks": [], "edges": [],
        }

    def test_all_sources_are_returned_and_duplicate_is_marked_both(self):
        rows = question_evidence_matches(self.graph, [
            {"id": "ocr_1", "start": 1.2, "end": 1.8, "text": "你为什么来这里？", "evidenceTimes": [1.2, 1.6]},
            {"id": "ocr_2", "start": 4.0, "end": 5.0, "text": "您怎么看这个行业？", "evidenceTimes": [4.0, 4.5]},
        ], [], {"kind": "question.evidence", "source": "all"})

        self.assertEqual(len(rows), 2)
        self.assertEqual(rows[0]["questionSource"], "both")
        self.assertEqual(rows[0]["matchedModalities"], ["speech", "ocr"])
        self.assertEqual(rows[1]["questionSource"], "screen")

    def test_source_filter_does_not_return_the_other_modality(self):
        spoken = question_evidence_matches(self.graph, [
            {"id": "ocr_1", "start": 4.0, "end": 5.0, "text": "您怎么看这个行业？", "evidenceTimes": [4.0, 4.5]},
        ], [], {"kind": "question.evidence", "source": "spoken"})
        screen = question_evidence_matches(self.graph, [], [], {"kind": "question.evidence", "source": "screen"})

        self.assertEqual([row["questionSource"] for row in spoken], ["spoken"])
        self.assertEqual(screen, [])

    def test_screen_question_card_collapses_repeated_header_samples(self):
        rows = question_evidence_matches({}, [
            {"id": "card", "start": 8.69, "end": 8.69,
             "text": "当初是什么吸引了你加入itc", "box": [205, 187, 568, 243],
             "evidenceTimes": [8.69]},
            {"id": "header_1", "start": 8.99, "end": 8.99,
             "text": "当初是什么吸引了你加入itc?", "box": [8, 32, 202, 45],
             "evidenceTimes": [8.99]},
            {"id": "header_2", "start": 36.01, "end": 36.01,
             "text": "当初是什么吸引了你加入itc？", "box": [8, 32, 202, 45],
             "evidenceTimes": [36.01]},
            {"id": "header_3", "start": 63.18, "end": 63.18,
             "text": "当初是什么吸引了你加入itc？", "box": [8, 32, 202, 45],
             "evidenceTimes": [63.18]},
            {"id": "subtitle", "start": 63.18, "end": 63.18,
             "text": "普通回答字幕", "box": [180, 334, 460, 352],
             "evidenceTimes": [63.18]},
        ], [
            {"id": "shot_card", "start": 0.0, "end": 8.84},
            {"id": "shot_answer", "start": 8.84, "end": 117.52},
        ], {"kind": "question.evidence", "source": "screen"},
           {"width": 1024, "height": 576})

        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["boundarySource"], "screen_question_card_shot")
        self.assertEqual(rows[0]["end"], 8.84)
        self.assertGreaterEqual(rows[0]["duration"], 2.2)
        self.assertEqual(rows[0]["screenOccurrenceCount"], 4)
        self.assertEqual(set(rows[0]["matchedUnitIds"]), {"card", "header_1", "header_2", "header_3"})

    def test_adjacent_title_fragment_and_full_header_form_one_question(self):
        rows = question_evidence_matches({}, [
            {"id": "fragment", "start": 12.4, "end": 12.4,
             "text": "你觉得自己身上哪些", "box": [134, 235, 465, 289],
             "evidenceTimes": [12.4]},
            {"id": "full_1", "start": 13.1, "end": 13.1,
             "text": "回顾过去三年的工作，你觉得自己身上有哪些变化？",
             "box": [9, 35, 347, 49], "evidenceTimes": [13.1]},
            {"id": "full_2", "start": 30.0, "end": 30.0,
             "text": "回顾过去三年的工作，你觉得自己身上有哪些变化？",
             "box": [9, 35, 347, 49], "evidenceTimes": [30.0]},
            {"id": "canvas", "start": 30.0, "end": 30.0,
             "text": "普通字幕", "box": [100, 334, 620, 352], "evidenceTimes": [30.0]},
        ], [
            {"id": "shot_card", "start": 10.0, "end": 13.0},
            {"id": "shot_answer", "start": 13.0, "end": 40.0},
        ], {"kind": "question.evidence", "source": "screen"},
           {"width": 1024, "height": 576})

        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["start"], 10.0)
        self.assertEqual(rows[0]["end"], 13.0)
        self.assertIn("回顾过去三年的工作", rows[0]["questionText"])

    def test_multiline_title_card_is_linked_from_following_question_header(self):
        rows = question_evidence_matches({}, [
            {"id": "line_1", "start": 12.0, "end": 12.8,
             "text": "如果用一个词形容itc", "box": [126, 195, 447, 248],
             "evidenceTimes": [12.0, 12.8]},
            {"id": "line_2", "start": 12.8, "end": 12.8,
             "text": "你第一个想到的词是", "box": [168, 240, 463, 285],
             "evidenceTimes": [12.8]},
            {"id": "header", "start": 13.1, "end": 13.1,
             "text": "如果用一个词形容itc，你第一个想到的词是？",
             "box": [6, 35, 306, 49], "evidenceTimes": [13.1]},
            {"id": "canvas", "start": 13.1, "end": 13.1,
             "text": "普通字幕", "box": [100, 334, 620, 352], "evidenceTimes": [13.1]},
        ], [
            {"id": "shot_card", "start": 10.0, "end": 13.0},
            {"id": "shot_answer", "start": 13.0, "end": 40.0},
        ], {"kind": "question.evidence", "source": "screen"},
           {"width": 1024, "height": 576})

        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["start"], 10.0)
        self.assertEqual(rows[0]["end"], 13.0)
        self.assertEqual(rows[0]["boundarySource"], "screen_question_card_shot")
        self.assertIn("line_1", rows[0]["matchedUnitIds"])
        self.assertIn("line_2", rows[0]["matchedUnitIds"])

    def test_answer_subtitles_are_not_screen_questions(self):
        rows = question_evidence_matches({}, [
            {"id": "answer_1", "start": 10.0, "end": 10.0,
             "text": "更多呢也看到了自己工作上的价值",
             "box": [150, 334, 486, 352], "evidenceTimes": [10.0]},
            {"id": "answer_2", "start": 12.0, "end": 12.0,
             "text": "我们应该如何的去赋能于我们的客户",
             "box": [150, 333, 486, 351], "evidenceTimes": [12.0]},
        ], [{"id": "shot_1", "start": 0.0, "end": 20.0}],
           {"kind": "question.evidence", "source": "screen"},
           {"width": 640, "height": 360})

        self.assertEqual(rows, [])

    def test_same_speaker_self_question_is_not_an_interview_prompt(self):
        graph = {
            "coverageComplete": True,
            "turns": [
                {"id": "q", "start": 1.0, "end": 2.0, "speaker": "Speaker 1",
                 "text": "怎么又是考试？", "dialogueAct": "question",
                 "dialogueRole": "questioner", "semanticConfidence": .9, "words": [{"start": 1.0}]},
                {"id": "a", "start": 2.1, "end": 4.0, "speaker": "Speaker 1",
                 "text": "因为刚开始有培训。", "dialogueAct": "answer",
                 "dialogueRole": "answerer", "semanticConfidence": .9, "respondsToIds": ["q"]},
            ],
            "responseBlocks": [{"id": "r", "promptTurnIds": ["q"], "answerTurnIds": ["a"]}],
        }
        rows = question_evidence_matches(
            graph, [], [], {"kind": "question.evidence", "source": "spoken"},
        )
        self.assertEqual(rows, [])

    def test_different_speaker_response_verifies_spoken_interview_prompt(self):
        graph = {
            "coverageComplete": True,
            "turns": [
                {"id": "q", "start": 1.0, "end": 2.0, "speaker": "Speaker 1",
                 "text": "你为什么来这里？", "dialogueAct": "question",
                 "dialogueRole": "questioner", "semanticConfidence": .9, "words": [{"start": 1.0}]},
                {"id": "a", "start": 2.1, "end": 4.0, "speaker": "Speaker 2",
                 "text": "因为我喜欢这里。", "dialogueAct": "answer",
                 "dialogueRole": "answerer", "semanticConfidence": .9, "respondsToIds": ["q"]},
            ],
            "responseBlocks": [{"id": "r", "promptTurnIds": ["q"], "answerTurnIds": ["a"]}],
        }
        rows = question_evidence_matches(
            graph, [], [], {"kind": "question.evidence", "source": "spoken"},
        )
        self.assertEqual(len(rows), 1)
        self.assertTrue(rows[0]["interviewPromptRelationVerified"])

    def test_natural_language_fallback_requests_both_modalities_and_exhaustive(self):
        fallback = fallback_content_intent("找出所有采访问题")
        parsed = parse_content_intent("找出所有采访问题", {})

        self.assertEqual(fallback["modalities"], ["speech", "ocr"])
        self.assertEqual(parsed["modalities"], ["speech", "ocr"])
        self.assertEqual(parsed["resultMode"], "exhaustive")
        self.assertEqual(parsed["queryPlan"]["requiredOperations"], [
            "dialogue.turn_graph", "screen_text.question_detect",
        ])

    def test_question_request_strips_stale_dialogue_pair_shape(self):
        parsed = parse_content_intent("找出所有采访问题的片段", {
            "action": "extract_content",
            "query": "采访问题",
            "predicates": [
                {"id": "q", "kind": "question.evidence", "source": "all"},
                {"id": "qa", "kind": "speech.dialogue_role", "role": "answerer",
                 "dialogueMode": "qa_pair", "includePrompt": True},
            ],
            "dialogueMode": "qa_pair",
        })
        self.assertEqual([item["kind"] for item in parsed["predicates"]], ["question.evidence"])
        self.assertNotIn("dialogueMode", parsed)
        self.assertNotIn("dialogueMode", parsed["queryPlan"]["predicates"][0])

    def test_answer_question_is_not_misclassified_as_question_evidence(self):
        fallback = fallback_content_intent("找出回答问题的人的片段")
        self.assertEqual(fallback["predicates"][0]["kind"], "speech.dialogue_role")
        self.assertEqual(fallback["predicates"][0]["dialogueMode"], "answer_only")
        self.assertEqual(fallback["modalities"], ["speech"])

    def test_dialogue_fallback_keeps_explicit_answer_and_pair_requests(self):
        answer = parse_content_intent("找出回答问题的人的片段", {})
        pair = parse_content_intent("找出问题及对应回答的片段", {})
        self.assertEqual(answer["predicates"][0]["kind"], "speech.dialogue_role")
        self.assertEqual(answer["predicates"][0]["dialogueMode"], "answer_only")
        self.assertEqual(pair["predicates"][0]["dialogueMode"], "qa_pair")
        self.assertTrue(pair["predicates"][0]["includePrompt"])


if __name__ == "__main__":
    unittest.main()
