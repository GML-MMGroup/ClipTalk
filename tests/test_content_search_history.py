from pathlib import Path
from unittest.mock import patch

from app import main


def test_public_content_search_records_keep_all_queries_in_order() -> None:
    job = main.new_job_record(
        job_id="history-records", source=Path("/tmp/source.mp4"), filename="source.mp4",
        size=100, count="auto", target_seconds="auto", theme="做饭", source_hash="history-hash",
    )
    job.update({
        "taskMode": "content_extract",
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
    assert visible["contentSearch"]["id"] == "search-watermelon"


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
        "taskMode": "content_extract",
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
    finally:
        main.jobs.pop(job_id, None)
