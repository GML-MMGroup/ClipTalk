import copy
from unittest.mock import MagicMock, patch

import pytest

from app.ark_client import AnthropicCompatibleClient, JsonResponseError, OpenAICompatibleVisionClient, parse_json_object


def test_only_trailing_commas_outside_strings_are_removed():
    assert parse_json_object('{"text":"literal ,} and ,]", "ranges":[1,2,],}') == {
        "text": "literal ,} and ,]", "ranges": [1, 2],
    }


@pytest.mark.parametrize("text", ['{"start": 10, "end":', '{"reason":"unescaped "quote""}', '{"start":1 "end":2}'])
def test_ambiguous_or_truncated_evidence_is_rejected(text):
    with pytest.raises(JsonResponseError):
        parse_json_object(text)


def test_invalid_json_retries_with_correction_and_larger_budget():
    calls = []
    def respond(*args, **kwargs):
        calls.append(copy.deepcopy(kwargs["json"]))
        response = MagicMock(status_code=200)
        response.json.return_value = {"choices": [{"message": {"content":
            '{"start":1 "end":2}' if len(calls) == 1 else '{"start":1,"end":2}'}}]}
        return response
    transport = MagicMock()
    transport.__enter__.return_value.post.side_effect = respond
    with patch("app.ark_client.httpx.Client", return_value=transport):
        client = OpenAICompatibleVisionClient(api_key="test", model="test", base_url="http://invalid")
        client._cancelled.wait = lambda seconds: False
        result = client.complete_json("original evidence", maximum_tokens=1000)
    assert result["end"] == 2
    assert len(calls) == 2
    assert calls[1]["messages"][0] == calls[0]["messages"][0]
    assert "JSON" in calls[1]["messages"][-1]["content"]
    assert calls[1]["max_tokens"] == 2000


@pytest.mark.parametrize("provider", ["openai", "anthropic"])
@pytest.mark.parametrize("budget", [1000, 20000])
def test_length_stop_retries_without_reducing_original_budget(provider, budget):
    calls = []

    def respond(*args, **kwargs):
        calls.append(copy.deepcopy(kwargs["json"]))
        response = MagicMock(status_code=200)
        first = len(calls) == 1
        if provider == "openai":
            response.json.return_value = {"choices": [{
                "finish_reason": "length" if first else "stop",
                "message": {"content": '{"ok":true}'},
            }]}
        else:
            response.json.return_value = {
                "stop_reason": "max_tokens" if first else "end_turn",
                "content": [{"type": "text", "text": '{"ok":true}'}],
            }
        return response

    transport = MagicMock()
    transport.__enter__.return_value.post.side_effect = respond
    with patch("app.ark_client.httpx.Client", return_value=transport):
        if provider == "openai":
            client = OpenAICompatibleVisionClient(api_key="test", model="test", base_url="http://invalid")
        else:
            client = AnthropicCompatibleClient(auth_token="test", model="test", base_url="http://invalid")
        client._cancelled.wait = lambda seconds: False
        assert client.complete_json("original evidence", maximum_tokens=budget)["ok"] is True
    assert len(calls) == 2
    assert calls[1]["max_tokens"] == max(budget, min(16384, budget * 2))
    assert calls[1]["messages"][0] == calls[0]["messages"][0]
    assert "JSON" in calls[1]["messages"][-1]["content"]
