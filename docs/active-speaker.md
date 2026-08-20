# 本地主动说话人检测

VideoPilot 将“某个已标记人物正在说话”作为独立的视听操作处理，不再把“人物在画面中”和“某个 Speaker 的时间段重合”当成同一件事。

## 执行顺序

1. 用户给匿名人物卡添加项目内标签；这个操作只改名，不启动检索。
2. 用户点击“设为本次检索人物”，或直接输入“剪出绿衣哥说话的全部片段”。
3. 查询编译为单个 `person.speaking` 条件和 `person.active_speaker_link` 操作。
4. `exhaustive` 模式扫描完整检索范围，并按源时间返回全部有证据的区间。
5. TalkNet 在隔离 Python 环境中运行。`shadow` 模式记录它与现有 VLM 口型复核的区间一致率；`primary` 模式直接采用 TalkNet 结果。
6. VLM 只看候选人物近景，不建立全局人物身份，也不把外观解释为真实性别或姓名。

## TalkNet 环境

TalkNet 官方实现使用较旧、独立的 Python/PyTorch 依赖，不能装进 Web 服务主环境。按官方仓库说明创建独立环境并下载 TalkSet 预训练权重，然后配置：

```dotenv
HIGHLIGHT_ACTIVE_SPEAKER_MODE=shadow
HIGHLIGHT_TALKNET_PYTHON=/absolute/path/to/talknet-env/bin/python
HIGHLIGHT_TALKNET_WORKER=/absolute/path/to/VideoPilot/new/tools/talknet_worker.py
HIGHLIGHT_TALKNET_REPOSITORY=/absolute/path/to/TalkNet-ASD
HIGHLIGHT_TALKNET_CHECKPOINT=/absolute/path/to/pretrain_TalkSet.model
HIGHLIGHT_TALKNET_DEVICE=cuda:0
HIGHLIGHT_TALKNET_TIMEOUT_SECONDS=900
```

官方代码与依赖说明：<https://github.com/TaoRuijie/TalkNet-ASD>。

## 隔离协议

主进程通过 `videopilot-asd-v1` JSON 文件向 worker 提供：

- 源视频和源时间检索范围；
- 匿名人物 ID、参考框和当前项目的人脸轨迹；
- 已有语音活动区间；
- checkpoint 与设备配置。

worker 调用官方 `demoTalkNet.py`，读取其 `tracks.pckl` 和 `scores.pckl`，用时间与框 IoU 将 TalkNet 人脸轨迹映射回用户确认的匿名人物，再输出逐帧证据合并后的区间。主进程会拒绝范围外时间、未知协议和未落盘响应。

## 上线门槛

默认保持 `shadow`。只有项目内真实视频验证集同时达到以下门槛，才把配置改为 `primary`：

- exhaustive 区间召回率不低于 92%；
- 区间精确率不低于 90%；
- 高置信度自动采用精确率不低于 97%；
- 起止边界平均绝对误差不高于 0.5 秒；
- 完整检索覆盖率为 100%；
- 其他检索类型相对基线下降不超过 2 个百分点。

TalkNet 对短于约一秒、很小、侧脸或遮挡人脸仍可能不稳定，因此中等置信结果保留“需复核”标记，不自动进入成片。
