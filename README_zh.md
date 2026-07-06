<div align="center">

<!-- 👇 在这里替换成你的封面 Banner 图（就用我们之前设计的那张海报） -->
<img src="./assets/banner_zh.png" alt="ClipTalk Banner" width="100%" />

# ClipTalk ✂️

### 通过对话完成视频剪辑的 AI Agent

**说句话，片子就剪好了。**

[![License](https://img.shields.io/badge/license-GPL%20v3-blue)](./LICENSE)
[![Stars](https://img.shields.io/github/stars/GML-MMGroup/ClipTalk?style=social)](https://github.com/GML-MMGroup/ClipTalk)
[![Version](https://img.shields.io/badge/version-1.0.0-brightgreen)](https://github.com/GML-MMGroup/ClipTalk/releases)
[![Discord](https://img.shields.io/badge/Discord-Join-5865f2)](https://discord.gg/yourlink)

[English](./README.md) · **简体中文** · [在线体验](#) · [使用文档](#)

</div>

---

## 🎥 效果演示

<!-- 👇 在这里放核心演示 GIF：用户输入一句话 → Agent 执行 → 成片输出 -->
<div align="center">
  <img src="./assets/demo.gif" alt="ClipTalk Demo" width="90%" />
</div>

<br/>

> 上传一段 1 小时的直播视频，然后只需输入一句话：*"把男生说话的画面
> 合并"*、*"把王总的画面剪出来"*、*"剪出讲新品的片段"*、*"剪一个
> 60 秒高光切片"* —— ClipTalk 会理解素材内容、规划剪辑方案、调用
> 相应工具，直接交付剪好的成片。

---

## 📰 最新动态

- **[2026-XX-XX]** 🎉 ClipTalk 正式开源！
- **[2026-XX-XX]** 🚀 发布声纹识别功能 —— 在数小时的素材中按人名精准定位任意说话人。
- **[2026-XX-XX]** ✨ 新增直播高光一键生成能力。

<!-- 后续更新持续追加到这里 -->

---

## 🌟 案例展示 —— 一句话，一次剪辑

> 以下均为 ClipTalk 通过单条指令完成的真实剪辑任务。
> <!-- 在这里放不同场景的剪辑案例，建议用 GIF 对比：原始素材 → 指令 → 成片 -->

<table>
  <tr>
    <td align="center"><b>📺 直播高光</b><br/><img src="./assets/cases/livestream.gif" width="240"/></td>
    <td align="center"><b>🎤 访谈剪辑</b><br/><img src="./assets/cases/interview.gif" width="240"/></td>
    <td align="center"><b>📦 产品讲解</b><br/><img src="./assets/cases/product.gif" width="240"/></td>
  </tr>
  <tr>
    <td align="center"><b>🏢 会议录像</b><br/><img src="./assets/cases/meeting.gif" width="240"/></td>
    <td align="center"><b>🎓 课程录播</b><br/><img src="./assets/cases/lecture.gif" width="240"/></td>
    <td align="center"><b>➕ 持续更新中</b><br/><img src="./assets/cases/more.gif" width="240"/></td>
  </tr>
</table>

---

## 💡 ClipTalk 是什么？

ClipTalk 是一个**视频剪辑 AI Agent**。你不需要在时间轴上拖拽素材，
也不需要在几小时的录像里反复拉进度条 —— 只需用自然语言描述需求，
Agent 会完成全部流程：**理解素材 → 定位目标内容 → 规划剪辑方案 →
执行剪切 → 输出成片。**

它不是简单的字幕关键词检索。ClipTalk 能真正**理解画面里是谁、
谁在说话、在聊什么** —— 综合运用语音识别、声纹识别、人脸检测和
话题分割 —— 所以哪怕是多人出镜的 1 小时录像，*"把王总的画面剪
出来"* 这样的指令也能直接生效。

---

## ✨ 核心特性

### 1. 💬 对话式剪辑
描述任务，直接拿结果。不需要任何时间轴操作技能 —— *"把他说话的
画面合并"* 一句话就是一次完整的剪辑流程。还可以持续追加指令：
*"再剪短一点"*、*"从讲价格的部分开始"*。

### 2. 🧠 素材内容理解
剪辑开始前，ClipTalk 会先对视频建立结构化理解：
- **语音转写** —— 带时间戳的完整字幕
- **声纹识别** —— 不只是"有人在说话"，而是"*谁*在说话"
- **人脸检测与追踪** —— 定位每个人的全部出镜片段
- **话题分割** —— 找到"新品讲解"从哪一秒开始、到哪一秒结束

### 3. 🎯 指定人物剪辑
说出一个名字，就能拿到 TA 的全部片段。*"把王总的画面剪出来"* 会
结合人脸与声纹双重识别，从整段素材中提取目标人物所有出镜和发言
的片段。

### 4. 🗣️ 说话片段合并
自动检测并合并指定说话人的全部发言片段，去除静音、口水词和其他
人的发言 —— 把散落在各处的片段拼成一条连贯的成片。

### 5. ⚡ 一句话生成高光
*"剪一个 60 秒高光切片"* —— Agent 会对素材的情绪能量、金句和
观众反应打分，自动拼出一条节奏紧凑、带字幕、可直接发布的高光
视频。

### 6. 🤖 Agent 驱动的多步剪辑
每条指令背后，Agent 会**自动规划并执行一条工具流水线** —— 读取
字幕、识别声纹、定位片段、执行剪辑 —— 并把工作日志实时逐步展示
给你，全程透明，没有黑箱。

### 7. 🎞️ 可编辑的时间轴输出
结果不会消失在黑箱里。每次剪辑都会落到一条**多轨时间轴**上
（视频 / 音频 / 字幕），你可以检查每一处剪切点、微调边界、重新
渲染 —— AI 干重活，最终决定权在你手里。

### 8. 🔄 持续迭代优化
对结果不满意？继续说就行。每条指令都基于上一步的结果 —— *"删掉
第二段"*、*"加上字幕"*、*"导出竖屏版"* —— 不需要从头再来。

### 9. 📚 为长素材而生
专治难啃的素材：1 小时直播、多人圆桌、全天活动录像。素材越长
越乱，ClipTalk 帮你省下的时间就越多。

### 10. 🔌 模块化工具系统
语音转写、声纹识别、人脸检测、渲染合成都是统一 Agent 接口下的
可插拔工具 —— 可以替换成你偏好的模型，也可以自行扩展工具箱。

---

## 🛠️ Agent 的工具箱

| 工具 | 能力 |
|------|------|
| 📝 **语音转写** | 语音转文字，精确到词级时间戳 |
| 🔊 **声纹识别** | 通过声纹识别并追踪每一位说话人 |
| 👤 **人脸追踪** | 检测并追踪每个人的全部出镜片段 |
| 🧭 **话题分割** | 将素材切分为语义段落与话题 |
| ⭐ **高光打分** | 按情绪能量、金句、观众反应为片段打分排序 |
| ✂️ **剪辑执行** | 帧级精度的剪切与合并 |
| 🎞️ **合成渲染** | 将片段、字幕、音频合成为最终成片 |

---

## 🏗️ 工作原理
💬 "把王总的画面剪出来"
↓
🤖 Agent 规划剪辑方案
↓
📝 读取字幕 → 🔊 识别声纹 → 👤 人脸追踪 → 🧭 定位片段
↓
✂️ 执行剪辑 → 🎞️ 合成渲染 → ✅ 完成


一句指令进，成片出 —— 每一步都在 Agent 工作日志中清晰可见。

---

## 🚀 快速开始

```bash
git clone https://github.com/yourorg/ClipTalk.git
cd ClipTalk
# 安装与启动步骤，待补充
配置项与 API Key 设置请参阅使用文档。

🤝 参与贡献
欢迎任何形式的贡献！请先阅读贡献指南。

📄 开源协议
本项目基于 GNU General Public License v3.0 开源。

你可以自由地运行、研究、分享和修改本软件。任何分发的衍生作品也必须
以 GPL v3 协议发布，以保证软件对所有用户保持自由。完整条款请见
LICENSE 文件。

💬 社区交流
Discord · Twitter/X · 微信群
<div align="center">

⭐ 如果 ClipTalk 对你有帮助，欢迎点一个 Star！

Made with ❤️ by the ClipTalk Team

</div>
```