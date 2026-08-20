# 访谈与课堂真实质量集

`interview-content-search.jsonl` 不允许填写模拟预测。每一行必须来自可回放的真实源视频，并符合 `interview-content-search.schema.json`。

- 数据集至少包含 30 个视频、600 个人工说话轮次和 200 个问答对；20 个视频用于开发，10 个视频固定为盲测集。
- 人工标注问题轮次、完整回答范围、视频内匿名 Speaker、短附和、插话和重叠说话。
- “回答者片段”默认不包含问题；不超过 1.2 秒且被标为 backchannel 的附和可以留在播放范围，但不能计入目标说话证据。
- `predicted` 必须由一次真实管线运行导出；`wrongSpeakerSeconds` 和 `predictedSpeechSeconds` 根据逐帧/逐词人工复核填写。
- 严格门禁通过 `npm run benchmark:interview-quality` 执行。缺少真实文件、样例数量不足或标注数量不足都会失败，避免用合成数据冒充上线质量。

真实媒体和含隐私的标注不提交到公开仓库；部署方应在本地放置 `benchmarks/interview-content-search.jsonl`。
