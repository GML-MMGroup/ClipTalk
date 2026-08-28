from app.algorithm_contract import ALGORITHM_V1
from app.job_schema import CURRENT_JOB_SCHEMA_VERSION, normalize_job_schema


def test_legacy_job_keeps_historical_variant_default() -> None:
    job = {"taskMode": "content_extract", "request": {}}

    assert normalize_job_schema(job) is True
    assert job["schemaVersion"] == CURRENT_JOB_SCHEMA_VERSION
    assert job["resolvedTaskKind"] == "content_extract"
    assert job["routingSource"] == "legacy_migration"
    assert job["request"]["autoVariantCount"] == 3
    assert job["algorithmVersion"] == ALGORITHM_V1
    assert normalize_job_schema(job) is False


def test_current_job_keeps_single_primary_result() -> None:
    job = {
        "schemaVersion": CURRENT_JOB_SCHEMA_VERSION,
        "taskMode": "highlight",
        "request": {"autoVariantCount": 1},
    }

    assert normalize_job_schema(job) is False
    assert job["request"]["autoVariantCount"] == 1


def test_malformed_schema_version_is_recovered() -> None:
    job = {"schemaVersion": "unknown", "request": None}

    assert normalize_job_schema(job) is True
    assert job["schemaVersion"] == CURRENT_JOB_SCHEMA_VERSION
    assert job["request"]["autoVariantCount"] == 3


def test_workflow_migration_uses_durable_request_choice_and_syncs_aliases() -> None:
    job = {
        "schemaVersion": 2,
        "taskMode": "content_extract",
        "workflowKind": "content_search",
        "request": {
            "workflowKind": "person_edit",
            "entryWorkflow": "person_discovery",
            "autoVariantCount": 1,
        },
    }
    assert normalize_job_schema(job) is True
    assert job["workflowKind"] == "person_edit"
    assert job["taskMode"] == "content_extract"
    assert job["request"]["workflowKind"] == "person_edit"
    assert job["request"]["entryWorkflow"] == "person_discovery"


def test_highlight_summary_migration_replaces_legacy_composition_claim() -> None:
    job = {
        "schemaVersion": 3,
        "taskMode": "highlight",
        "request": {"autoVariantCount": 3, "workflowKind": "highlight"},
        "messages": [{
            "role": "user",
            "kind": "request",
            "text": (
                "分析 source.mp4，自动推荐事件数量，单条成片时长由系统推荐；"
                "每条由同一事件的多个镜头组成，允许复用相同要求的分析缓存；素材范围：全片"
            ),
        }],
    }

    assert normalize_job_schema(job) is True
    summary = job["messages"][0]["text"]
    assert "每条由同一事件的多个镜头组成" not in summary
    assert "系统将相关镜头按事件归组，并根据内容完整性自动编排" in summary
    assert "每条成片可包含一个或多个事件" in summary


def test_highlight_summary_migration_does_not_rewrite_user_authored_text() -> None:
    job = {
        "schemaVersion": 3,
        "taskMode": "highlight",
        "request": {"autoVariantCount": 3, "workflowKind": "highlight"},
        "messages": [{
            "role": "user",
            "kind": "request",
            "text": "我要求每条由同一事件的多个镜头组成",
        }],
    }

    assert normalize_job_schema(job) is True
    assert job["messages"][0]["text"] == "我要求每条由同一事件的多个镜头组成"
