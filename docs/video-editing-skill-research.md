# 视频剪辑 Skill 调研与 ClipTalk 落地建议

日期：2026-09-02

实施状态：`cliptalk-cover-director` 本地源帧版 v1 已接入；`cliptalk-smart-reframe` 仍为待实现提案。

## 结论

第三方 Skill 适合作为工作流和边界设计参考，但不应原样成为 ClipTalk 的核心编辑能力。ClipTalk 已经有多模态证据、人物发现、时间线和 FFmpeg 媒体内核，最有价值的增量是：

1. 用封面导演把已有高光证据转为可审核的封面候选，而不是只截取首个非黑帧。
2. 用时间连续的主体轨迹替代固定 `focusX/focusY`，把社媒裁剪升级为逐镜头智能重构图。
3. 把 Remotion 保留为可选包装层，用于动态标题、栏目包装和复杂字幕，不替代 ClipTalk 的编辑决策与 FFmpeg 主链路。

## 值得吸收的外部 Skill

| Skill | 可吸收能力 | 不直接采用的原因 |
|---|---|---|
| [Remotion Agent Skills](https://github.com/remotion-dev/skills) | 动态标题、字幕、节目包装、组合式视频组件与渲染规范 | 更擅长代码化包装，不负责从长视频中做可靠的语义剪辑与主体追踪 |
| [n0an/ffmpeg-skill](https://github.com/n0an/ffmpeg-skill) | FFmpeg 裁剪、缩放、拼接、字幕、水印、缩略图、兼容性与 `faststart` 经验 | 是命令配方集合，没有 ClipTalk 的证据、审核和版本语义 |
| [Higgsfield YouTube Thumbnail](https://github.com/higgsfield-ai/skills/blob/main/higgsfield-youtube-thumbnail/SKILL.md) | 封面概念、主体身份引用、比例变体、真实性约束、多个方向对比 | 依赖外部付费生成服务；不能作为本地、可复现的默认能力 |
| [Hermes Video Editing](https://github.com/argus-metis/hermes-video-editing) | 本地视频处理工作流与智能重构图原型 | 当前智能重构图主要依赖 Haar 正脸检测、最大脸和移动平均，难以处理侧脸、物体、群像、遮挡与镜头切换 |
| [FFmpeg Analyse Video](https://github.com/fabriqaai/ffmpeg-analyse-video-skill/blob/main/SKILL.md) | 按视频时长切换采样策略、控制候选帧预算、失败降级 | ClipTalk 现有多模态分析更丰富，只应复用采样预算和降级思想 |
| [Video Automation Skill](https://github.com/officialwhitebird/video-automation-skill/blob/main/SKILL.md) | 预览先行、不覆盖源文件、付费或长任务前确认、字幕审核后烧录 | 主要价值是安全流程，不是新的编辑算法 |
| [VideoDB Skill](https://github.com/nous-hermeshub/hermes-community-hub/blob/main/skills/media/videodb/SKILL.md) | 云端索引、搜索和服务端智能重构图 | 引入上传、API Key、隐私和供应商依赖，且与 ClipTalk 已有能力重复 |

## ClipTalk 内部能力拆分

### `cliptalk-cover-director`

- 从已确认时间线、高光候选、人物反应和动作峰值中提取 10–20 张源帧。
- 用用户目标、主体可读性、情绪或动作、清晰度、标题安全区和差异性评分。
- 默认给出 3 个有明确差异的方向：纪实源帧、源帧加标题、生成式概念图。
- 生成式模式必须显式选择，保留来源与模型信息，不得虚构人物、事件、成绩或引语。
- 封面只能在用户确认后成为当前封面，不自动发布。

设计契约见 [封面导演 Skill 提案](skill-proposals/cliptalk-cover-director/SKILL.md)，运行版本见 [`skills/cliptalk-cover-director/SKILL.md`](../skills/cliptalk-cover-director/SKILL.md)。

### `cliptalk-smart-reframe`

- 以已接受的成片或审核样片为输入，输出独立的重构图预览。
- 复用人物轨迹、说话人、镜头边界和对象证据，生成随时间变化的裁剪轨迹。
- 限制中心点速度、加速度和缩放变化；镜头切换时允许重新取景，镜头内部避免追脸抖动。
- 群像、无可靠主体、快速遮挡和字幕冲突时降级为完整画面加虚化背景。
- 所有自动裁剪都必须提供关键帧调整与质量报告。

完整提案见 [智能重构图 Skill](skill-proposals/cliptalk-smart-reframe/SKILL.md)。

## 推荐实施顺序

1. 先实现封面候选提取、评分、源帧加标题和审核闭环；生成式封面作为可选适配器后置。
2. 再实现人物轨迹驱动的单主体重构图，随后支持当前说话人、群像和对象目标。
3. 最后增加 Remotion 包装插件，只消费已经确认的 Editing Program 或成片，不改变源素材选择。

外部 Skill 可安装到开发 Agent 环境作为参考，但安装不会自动变成 ClipTalk 产品内 Skill，也不应绕过产品的预览、确认与溯源机制。

## 已实现的封面 v1

- `app/cover_art.py`：证据时间采样、黑帧与近重复抑制、六维评分、三种本地构图和内容哈希。
- `app/agent_platform.py`：封面工具目录、managed profile、确定性五步计划和强制人工审核。
- `app/main.py`：后台候选与预览任务、选择验证、历史版本、当前封面激活和预览媒体接口。
- `static/agent-workspace.js` / `.css`：Agent 计划抽屉内的三图单选审核。
- `tests/test_cover_art.py` / `tests/test_cover_agent.py`：算法、计划、工具链、审核与确认回归。

本版只生成源帧派生封面，不调用外部生成服务，不做人脸修饰，也不发布到外部平台。
