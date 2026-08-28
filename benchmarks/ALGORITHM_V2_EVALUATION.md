# editing-algorithm-v2 真实素材评测格式

每行是一个人工标注案例。`sourceVideo` 必须是当前机器上真实存在的视频，
`annotationSource` 必须说明标注人或标注批次；评测器会拒绝 synthetic、generated、canned。

```json
{"caseId":"content-001","workflow":"content_search","algorithmVersion":"editing-algorithm-v2","sourceVideo":"/dataset/video-001.mp4","annotationSource":"reviewer-a/round-2","groundTruth":[{"start":12.1,"end":18.4,"speaker":"host"}],"predictions":[{"start":12.2,"end":18.1,"speaker":"host","confidenceTier":"reliable"}],"baselineLatencySeconds":20.0,"v2LatencySeconds":34.0}
```

人物和说话人案例在每个范围增加 `identity`；预测身份必须在单个视频内保持稳定。
人物评测使用全局一对一身份匹配，同时统计错误合并和错误拆分。说话人评测按时间原子区间
计算漏检、误检、混淆、DER 与 JER，不接受预先填写的 `wrongIdentity` 代替计算。
高光案例增加 `abWinner`（`v2`、`baseline` 或 `tie`）和 `criticalTruncations`。运行：

```bash
python3 tools/evaluate_algorithm_v2.py /path/to/annotations.jsonl --check --require-input
```
