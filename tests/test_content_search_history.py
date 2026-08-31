from pathlib import Path
from unittest.mock import patch

import pytest

from app import main


def test_public_content_search_records_keep_all_queries_in_order() -> None:
    job = main.new_job_record(
        job_id="history-records", source=Path("/tmp/source.mp4"), filename="source.mp4",
        size=100, count="auto", target_seconds="auto", theme="做饭", source_hash="history-hash",
    )
    job.update({
        "taskMode": "content_extract", "status": "awaiting_content_confirmation",
        "contentSearchHistory": [{
            "id": "search-cooking", "createdAt": "2026-08-19T10:00:00Z",
            "instruction": "找做饭的片段", "candidates": [{
                "id": "cooking-1", "start": 1, "end": 3, "duration": 2,
                "title": "做饭", "score": 90, "evidenceRefs": [{"id": "e1"}],
            }],
        }],
        "contentSearch": {
            "id": "search-watermelon", "createdAt": "2026-08-19T10:01:00Z",
            "instruction": "找切西瓜的片段", "candidates": [{
                "id": "watermelon-1", "start": 4, "end": 6, "duration": 2,
                "title": "切西瓜", "score": 91, "evidenceRefs": [{"id": "e2"}],
            }],
        },
    })

    visible = main.public_job(job)
    records = visible["contentSearchRecords"]
    assert [record["id"] for record in records] == ["search-cooking", "search-watermelon"]
    assert records[0]["candidates"] == []
    assert records[0]["candidateCount"] == 1
    assert records[0]["candidateDetailsLoaded"] is False
    assert records[0]["timelineCandidates"] == [{
        "id": "cooking-1", "title": "做饭", "start": 1, "end": 3, "duration": 2,
    }]
    assert visible["contentSearch"]["id"] == "search-watermelon"


def test_legacy_pending_search_is_active_and_gets_current_request_scope() -> None:
    job = main.new_job_record(
        job_id="legacy-pending", source=Path("/tmp/source.mp4"), filename="source.mp4",
        size=100, count="auto", target_seconds="auto", theme="洗衣机", source_hash="legacy-pending-hash",
    )
    job.update({
        "taskMode": "content_extract", "status": "running", "stage": "content_search",
        "videoInfo": {"duration": 643.0},
        "request": {
            **job.get("request", {}), "contentInstruction": "找冰箱", "searchScopeKind": "all",
            "searchScopeStart": 0.0, "searchScopeEnd": 643.0,
            "contentSearchScopeOrigin": "fresh_default",
        },
        "contentSearch": {"id": "search-washer", "instruction": "找洗衣机", "candidates": []},
        "pendingContentSearch": {"id": "search-fridge", "instruction": "找冰箱", "status": "queued", "candidates": []},
    })
    visible = main.public_job(job)
    assert visible["contentSearchSession"]["activeSearchId"] == "search-fridge"
    pending = next(item for item in visible["contentSearchRecords"] if item["id"] == "search-fridge")
    assert pending["scope"]["start"] == 0.0
    assert pending["scope"]["end"] == 643.0
    assert pending["scope"]["origin"] == "fresh_default"


def test_history_detail_endpoint_returns_full_record_without_switching_current_search() -> None:
    job_id = "history-detail"
    job = main.new_job_record(
        job_id=job_id, source=Path("/tmp/source.mp4"), filename="source.mp4",
        size=100, count="auto", target_seconds="auto", theme="切西瓜", source_hash="detail-hash",
    )
    job.update({
        "taskMode": "content_extract",
        "contentSearchHistory": [{
            "id": "old-search", "instruction": "找做饭", "candidates": [{
                "id": "old-match", "start": 1, "end": 2, "evidenceRefs": [{"id": "old-evidence"}],
            }],
        }],
        "contentSearch": {"id": "new-search", "instruction": "找切西瓜", "candidates": []},
    })
    main.jobs[job_id] = job
    try:
        response = main.get_content_search_history(job_id, "old-search")
        assert response["search"]["id"] == "old-search"
        assert response["search"]["candidates"][0]["evidenceRefs"] == [{"id": "old-evidence"}]
        assert main.jobs[job_id]["contentSearch"]["id"] == "new-search"
    finally:
        main.jobs.pop(job_id, None)


def test_confirming_history_search_keeps_latest_search_state() -> None:
    job_id = "history-confirm"
    job = main.new_job_record(
        job_id=job_id, source=Path("/tmp/source.mp4"), filename="source.mp4",
        size=100, count="auto", target_seconds="auto", theme="切西瓜", source_hash="confirm-hash",
    )
    job.update({
        "taskMode": "content_extract", "status": "completed",
        "contentSearchHistory": [{
            "id": "old-search", "instruction": "找做饭", "candidates": [{
                "id": "old-match", "start": 1, "end": 2, "duration": 1,
                "title": "做饭", "score": 90,
            }],
        }],
        "contentSearch": {
            "id": "new-search", "instruction": "找切西瓜", "candidates": [{
                "id": "new-match", "start": 4, "end": 5, "duration": 1,
                "title": "切西瓜", "score": 90,
            }],
        },
    })
    main.jobs[job_id] = job
    try:
        request = main.ContentSearchConfirmRequest(
            searchId="old-search", matchIds=["old-match"], outputMode="single_reel", orderMode="source",
        )
        with patch.object(main, "save_job"), patch.object(main, "append_message"), patch.object(main, "submit_render_task"):
            response = main.confirm_content_search(job_id, request)
        assert response["job"]["contentSearch"]["id"] == "new-search"
        assert response["job"]["contentSearchHistory"][0]["status"] == "confirmed"
        assert response["job"]["contentSearchHistory"][0]["confirmedMatchIds"] == ["old-match"]
    finally:
        main.jobs.pop(job_id, None)


def test_followup_keeps_current_result_without_auto_seeding_merge_selection() -> None:
    job_id = "pending-keeps-current"
    job = main.new_job_record(
        job_id=job_id, source=Path("/tmp/source.mp4"), filename="source.mp4",
        size=100, count="auto", target_seconds="auto", theme="做饭", source_hash="pending-hash",
    )
    job.update({
        "taskMode": "content_extract", "status": "completed",
        "contentSearch": {
            "id": "search-cooking", "instruction": "找做饭", "defaultSelectedIds": ["cook-1"],
            "candidates": [{"id": "cook-1", "start": 1, "end": 2, "title": "做饭"}],
        },
    })
    main.jobs[job_id] = job
    try:
        with patch.object(main, "save_job"), patch.object(main, "append_message"), patch.object(main, "submit_analysis_task"):
            response = main.queue_content_followup(job_id, "找切西瓜")
        assert response["job"]["contentSearch"]["id"] == "search-cooking"
        assert response["job"]["pendingContentSearch"]["instruction"] == "找切西瓜"
        assert response["job"]["contentSearchSession"] == {
            "schemaVersion": 1,
            "activeSearchId": response["job"]["pendingContentSearch"]["id"],
            "usableSearchId": "search-cooking",
            "previousUsableSearchId": "search-cooking",
            "state": "running",
        }
        basket = response["job"].get("contentSelectionBasket") or {}
        assert basket.get("items") in (None, [])
    finally:
        main.jobs.pop(job_id, None)


def test_cross_search_basket_persists_ordered_references() -> None:
    job_id = "cross-search-basket"
    job = main.new_job_record(
        job_id=job_id, source=Path("/tmp/source.mp4"), filename="source.mp4",
        size=100, count="auto", target_seconds="auto", theme="做饭", source_hash="basket-hash",
    )
    job.update({
        "taskMode": "content_extract", "status": "awaiting_content_confirmation",
        "contentSearchHistory": [{
            "id": "search-a", "instruction": "找做饭", "candidates": [{"id": "a-1", "start": 1, "end": 3, "title": "做饭"}],
        }],
        "contentSearch": {
            "id": "search-b", "instruction": "找切西瓜", "candidates": [{"id": "b-1", "start": 5, "end": 7, "title": "切西瓜"}],
        },
    })
    main.jobs[job_id] = job
    try:
        request = main.ContentSelectionBasketRequest(items=[
            {"searchId": "search-b", "matchId": "b-1"},
            {"searchId": "search-a", "matchId": "a-1"},
        ])
        with patch.object(main, "save_job"):
            response = main.update_content_selection_basket(job_id, request)
        assert [(item["searchId"], item["matchId"]) for item in response["basket"]["items"]] == [
            ("search-b", "b-1"), ("search-a", "a-1"),
        ]
        assert response["basket"]["items"][0]["sourceQuery"] == "找切西瓜"
        assert response["basket"]["revision"] == 1
        assert response["basket"]["schemaVersion"] == "content-selection-basket-v2"
        assert response["basket"]["entryMode"] == "explicit"
        assert response["basket"]["uniqueDuration"] == 4.0
        assert response["basket"]["overlapCount"] == 0
    finally:
        main.jobs.pop(job_id, None)


def test_source_project_basket_accepts_matches_from_sibling_tasks() -> None:
    first_id, second_id = "project-basket-a", "project-basket-b"
    first = main.new_job_record(
        job_id=first_id, source=Path("/tmp/source-a.mp4"), filename="source.mp4",
        size=100, count="auto", target_seconds="auto", theme="冰箱", source_hash="shared-project-hash",
    )
    second = main.new_job_record(
        job_id=second_id, source=Path("/tmp/source-b.mp4"), filename="source.mp4",
        size=100, count="auto", target_seconds="auto", theme="洗衣机", source_hash="shared-project-hash",
    )
    first.update({
        "taskMode": "content_extract", "status": "awaiting_content_confirmation",
        "contentSearch": {"id": "search-fridge", "instruction": "找冰箱", "candidates": [
            {"id": "fridge-1", "start": 4, "end": 8, "title": "冰箱画面"},
        ]},
    })
    second.update({"taskMode": "content_extract", "status": "awaiting_content_confirmation"})
    main.jobs[first_id], main.jobs[second_id] = first, second
    try:
        with patch.object(main, "save_job"):
            response = main.update_content_selection_basket(second_id, main.ContentSelectionBasketRequest(items=[
                {"originJobId": first_id, "searchId": "search-fridge", "matchId": "fridge-1"},
            ]))
        assert response["basket"]["scope"] == "source_project"
        assert response["basket"]["items"][0]["originJobId"] == first_id
        assert main.jobs[first_id]["contentSelectionBasket"] == main.jobs[second_id]["contentSelectionBasket"]
    finally:
        main.jobs.pop(first_id, None)
        main.jobs.pop(second_id, None)


def test_running_content_job_rejects_history_restore_without_changing_active_search() -> None:
    job_id = "running-history-restore-guard"
    job = main.new_job_record(
        job_id=job_id, source=Path("/tmp/source.mp4"), filename="source.mp4",
        size=100, count="auto", target_seconds="auto", theme="运行中恢复", source_hash="running-restore-guard-hash",
    )
    job.update({
        "taskMode": "content_extract", "status": "running", "stage": "content_search",
        "contentSearchHistory": [{"id": "search-old", "instruction": "旧检索", "candidates": []}],
        "contentSearch": {"id": "search-current", "instruction": "当前检索", "candidates": []},
    })
    main.jobs[job_id] = job
    try:
        with patch.object(main, "save_job"), pytest.raises(Exception, match="完成后再恢复历史检索"):
            main.restore_content_search(job_id, "search-old")
        assert main.jobs[job_id]["contentSearch"]["id"] == "search-current"
        assert main.jobs[job_id]["status"] == "running"
    finally:
        main.jobs.pop(job_id, None)


def test_running_source_project_rejects_basket_update_and_confirm_before_snapshot_write() -> None:
    job_id = "running-basket-mutation-guard"
    job = main.new_job_record(
        job_id=job_id, source=Path("/tmp/source.mp4"), filename="source.mp4",
        size=100, count="auto", target_seconds="auto", theme="运行中清单", source_hash="running-basket-guard-hash",
    )
    job.update({
        "taskMode": "content_extract", "status": "running", "stage": "rendering",
        "contentSearchHistory": [],
        "contentSearch": {
            "id": "search-current", "instruction": "当前检索",
            "candidates": [{"id": "match-1", "start": 1, "end": 3, "title": "片段"}],
        },
        "contentSelectionBasket": {
            "schemaVersion": "content-selection-basket-v2", "entryMode": "explicit", "revision": 1,
            "items": [{
                "originJobId": job_id, "searchId": "search-current", "matchId": "match-1",
                "start": 1, "end": 3, "duration": 2, "title": "片段", "sourceQuery": "当前检索",
            }],
        },
    })
    main.jobs[job_id] = job
    try:
        with patch.object(main, "save_job"), pytest.raises(Exception, match="完成后再修改成片清单"):
            main.update_content_selection_basket(job_id, main.ContentSelectionBasketRequest(items=[]))
        with patch.object(main, "save_job"), pytest.raises(Exception, match="完成后再生成成片清单"):
            main.confirm_content_selection_basket(job_id, main.ContentSelectionBasketConfirmRequest())
        assert main.jobs[job_id]["contentSearchHistory"] == []
        assert "renderContentSearch" not in main.jobs[job_id]
        assert main.jobs[job_id]["contentSelectionBasket"]["revision"] == 1
    finally:
        main.jobs.pop(job_id, None)


def test_natural_language_assembly_builds_reviewable_cross_search_preview() -> None:
    job_id = "natural-language-assembly"
    job = main.new_job_record(
        job_id=job_id, source=Path("/tmp/source.mp4"), filename="source.mp4",
        size=100, count="auto", target_seconds="auto", theme="做饭", source_hash="assembly-hash",
    )
    job.update({
        "taskMode": "content_extract", "status": "awaiting_content_confirmation",
        "contentSearchHistory": [{
            "id": "search-eggs", "instruction": "找煎鸡蛋", "createdAt": "2026-01-01T00:00:00Z",
            "defaultSelectedIds": ["egg-1"],
            "candidates": [{"id": "egg-1", "start": 10, "end": 14, "title": "煎鸡蛋"}],
        }],
        "contentSearch": {
            "id": "search-watermelon", "instruction": "找切西瓜", "createdAt": "2026-01-01T00:01:00Z",
            "defaultSelectedIds": ["melon-1"],
            "candidates": [{"id": "melon-1", "start": 30, "end": 36, "title": "切西瓜"}],
        },
    })
    main.jobs[job_id] = job
    try:
        with patch.object(main, "save_job"), patch.object(main, "append_message") as append:
            response = main.prepare_content_assembly_preview(job_id, "把所有检索结果合并", {
                "assemblyRequest": {
                    "includeAllSearches": True, "includeBasket": False,
                    "outputMode": "single_reel", "orderMode": "selection",
                    "subtitleMode": "none", "targetSeconds": 30,
                },
            })
        basket = response["job"]["contentSelectionBasket"]
        assert response["action"] == "content-assembly-preview"
        assert [(item["searchId"], item["matchId"]) for item in basket["items"]] == [
            ("search-eggs", "egg-1"), ("search-watermelon", "melon-1"),
        ]
        assert basket["orderMode"] == "selection"
        assert basket["targetSeconds"] == 30
        assert response["job"]["pendingContentAssembly"]["itemCount"] == 2
        assert append.call_count == 2
    finally:
        main.jobs.pop(job_id, None)


def test_cancelling_followup_restores_last_usable_search() -> None:
    job_id = "cancel-followup-only"
    job = main.new_job_record(
        job_id=job_id, source=Path("/tmp/source.mp4"), filename="source.mp4",
        size=100, count="auto", target_seconds="auto", theme="做饭", source_hash="cancel-followup-hash",
    )
    job.update({
        "taskMode": "content_extract", "status": "running", "stage": "content_search",
        "contentSearch": {
            "id": "search-cooking", "instruction": "找做饭", "candidates": [],
            "intent": {"query": "找做饭", "searchScope": {"kind": "all", "start": 0, "end": 60, "videoDuration": 60}},
        },
        "pendingContentSearch": {
            "id": "search-watermelon", "instruction": "找切西瓜", "status": "queued",
            "conversationTurnId": "turn-watermelon", "candidates": [],
        },
    })
    main.jobs[job_id] = job
    main.cancel_events[job_id] = main.threading.Event()
    try:
        with patch.object(main, "save_job"), patch.object(main, "append_message") as append:
            response = main.cancel_content_search(job_id, "search-watermelon")
        assert response["job"]["status"] == "awaiting_content_confirmation"
        assert response["job"]["contentSearch"]["id"] == "search-cooking"
        assert response["job"]["pendingContentSearch"] is None
        assert response["job"]["request"]["contentInstruction"] == "找做饭"
        assert any(item["id"] == "search-watermelon" and item["status"] == "cancelled" for item in response["job"]["contentSearchHistory"])
        append.assert_called_once()
    finally:
        main.jobs.pop(job_id, None)
        main.cancel_events.pop(job_id, None)
