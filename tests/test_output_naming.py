from app.output_naming import apply_output_naming, build_output_naming


def test_content_output_combines_subject_variant_version_and_aspect() -> None:
    job = {"filename": "小米产品.mp4", "outputVersions": []}
    version = {
        "id": "v002", "number": 2,
        "contentSearchInstruction": "出现小米 Logo",
        "displayName": "AI · 叙事完整版",
    }
    output = {"filename": "v002-01-AI_·_叙事完整版.mp4", "width": 540, "height": 960}

    naming = build_output_naming(job, version, output)

    assert naming == {
        "namingVersion": 2,
        "nameSubject": "出现小米 Logo",
        "nameVariant": "叙事完整版",
        "displayTitle": "出现小米 Logo · 叙事完整版",
        "aspectLabel": "9:16",
        "downloadFilename": "小米产品_出现小米_Logo-叙事完整版_V2_9x16.mp4",
    }
    assert output["filename"] == "v002-01-AI_·_叙事完整版.mp4"


def test_source_subject_is_not_duplicated_and_engine_name_is_removed() -> None:
    naming = build_output_naming(
        {"filename": "小米产品.mp4"},
        {"number": 1, "displayName": "AI · 演示结果版"},
        {"filename": "internal.mp4", "width": 1920, "height": 1080},
    )

    assert naming["displayTitle"] == "小米产品 · 演示结果版"
    assert naming["downloadFilename"] == "小米产品_演示结果版_V1_16x9.mp4"
    assert "AI" not in naming["downloadFilename"]


def test_generic_goal_falls_back_to_source_and_old_preview_wording_is_normalized() -> None:
    naming = build_output_naming(
        {"filename": "产品宣传.mp4", "brief": {"objective": "事件高光合集"}},
        {"number": 1, "displayName": "1:1 虚化背景审核预览"},
        {"filename": "internal.mp4", "title": "二次精剪成片"},
    )

    assert naming["displayTitle"] == "产品宣传 · 虚化背景版"
    assert naming["downloadFilename"] == "产品宣传_虚化背景版_V1_1x1.mp4"


def test_multi_output_review_sample_adds_only_required_disambiguators() -> None:
    naming = build_output_naming(
        {"filename": "访谈.mp4", "request": {"contentInstruction": "主持人与嘉宾交谈"}},
        {"number": 3, "displayName": "内容视频", "previewOnly": True},
        {"filename": "internal.mp4", "title": "内容视频", "previewOnly": True},
        position=2, output_count=3,
    )

    assert naming["displayTitle"] == "主持人与嘉宾交谈"
    assert naming["downloadFilename"] == "访谈_主持人与嘉宾交谈_V3_02_审核样片.mp4"


def test_derived_portrait_version_inherits_parent_semantics() -> None:
    parent_output = {
        "filename": "parent.mp4", "namingVersion": 2,
        "nameSubject": "产品功能演示", "nameVariant": "叙事完整版",
        "displayTitle": "产品功能演示 · 叙事完整版",
    }
    parent = {"id": "v001", "number": 1, "outputs": [parent_output]}
    derived = {
        "id": "v002", "number": 2, "parentVersionId": "v001",
        "variantKind": "social_reframe_export", "displayName": "9:16竖屏正式成片",
        "outputs": [{
            "filename": "parent-9x16-final.mp4", "outputKind": "social_reframe_final",
            "reframe": {"aspect": "9:16"},
        }],
    }
    job = {"filename": "发布会.mp4", "outputVersions": [parent, derived], "currentOutputVersionId": "v002"}

    apply_output_naming(job)

    output = derived["outputs"][0]
    assert output["displayTitle"] == "产品功能演示 · 叙事完整版"
    assert output["downloadFilename"] == "发布会_产品功能演示-叙事完整版_V2_9x16.mp4"
    assert job["outputs"] is derived["outputs"]


def test_delivery_and_companion_artifacts_share_a_safe_stem() -> None:
    naming = build_output_naming(
        {"filename": "产品/宣传 最终版.mp4"},
        {"number": 4, "variantKind": "delivery_master"},
        {
            "filename": "delivery.mp4", "outputKind": "delivery_master",
            "delivery": {"platform": "douyin", "aspect": "9:16"},
        },
        extension="srt",
    )

    assert naming["displayTitle"].endswith("抖音交付版")
    assert naming["downloadFilename"].endswith("_V4_9x16.srt")
    assert "/" not in naming["downloadFilename"]
