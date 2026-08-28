from __future__ import annotations

import json
from pathlib import Path

from app import main
from app.api_schemas import SubtitleSuggestionsRequest
from app.subtitle_review import save_draft


class CorrectionClient:
    def __init__(self) -> None:
        self.prompts: list[str] = []
        self.cancelled = False

    def complete_json(self, prompt: str, **_kwargs: object) -> dict:
        self.prompts.append(prompt)
        if len(self.prompts) == 1:
            return {
                "summary": "厨房家电介绍",
                "terms": [{
                    "term": "冰箱", "variants": ["冰厢"], "confidence": .97,
                    "sources": ["transcript_repeat"], "evidence": "全文重复出现",
                }],
                "uncertainTerms": [],
            }
        payload = json.loads(prompt.splitlines()[-1])
        assert payload["contextProfile"]["terms"][0]["term"] == "冰箱"
        assert payload["targets"][0]["after"] == "然后把门关上。"
        return {"suggestions": [{
            "cueId": "cue_1", "text": "打开冰箱。", "confidence": .97,
            "reason": "完整逐字稿重复使用冰箱", "evidence": ["逐字稿重复"],
        }]}

    def cancel(self) -> None:
        self.cancelled = True


def test_subtitle_suggestions_use_global_context_before_local_correction(tmp_path: Path, monkeypatch) -> None:
    draft_id = "sub_1234567890abcdef"
    job_id = "job_subtitle_context"
    draft = {
        "id": draft_id, "jobId": job_id, "revision": 1, "status": "draft",
        "outputFingerprints": ["timeline"],
        "cues": [
            {"id": "cue_1", "outputIndex": 0, "start": 0, "end": 2, "sourceStart": 10, "sourceEnd": 12, "text": "打开冰厢。", "originalText": "打开冰厢。", "suggestionStatus": "none"},
            {"id": "cue_2", "outputIndex": 0, "start": 2, "end": 4, "sourceStart": 12, "sourceEnd": 14, "text": "然后把门关上。", "originalText": "然后把门关上。", "suggestionStatus": "none"},
        ],
    }
    save_draft(tmp_path, draft)
    job = {"id": job_id, "workDirectory": str(tmp_path), "sourcePath": str(tmp_path / "产品宣传.mp4"), "originalFilename": "产品宣传.mp4"}
    client = CorrectionClient()
    monkeypatch.setitem(main.jobs, job_id, job)
    monkeypatch.setattr(main, "create_llm_client_for_job", lambda _job: client)

    result = main.suggest_subtitle_corrections(job_id, draft_id, SubtitleSuggestionsRequest())

    assert len(client.prompts) == 2
    assert client.cancelled is True
    assert result["suggestionCount"] == 1
    assert result["riskCounts"] == {"low": 1, "medium": 0, "high": 0}
    corrected = result["draft"]["cues"][0]
    assert corrected["text"] == "打开冰厢。"
    assert corrected["originalText"] == "打开冰厢。"
    assert corrected["suggestedText"] == "打开冰箱。"
    assert corrected["suggestionStatus"] == "pending"
    assert result["draft"]["correctionContext"]["terms"][0]["term"] == "冰箱"
