(function createClipTalkCopy(global) {
  const WORKFLOWS = Object.freeze({
    highlight: Object.freeze({
      label: "智能高光",
      output: "高光成片",
      outputPlural: "高光版本",
      candidate: "事件镜头",
      candidatePlural: "事件镜头",
      timeline: "事件与镜头时间线",
      phases: Object.freeze({ brief: "需求确认", analysis: "高光发现", events: "事件审核", compose: "生成版本" }),
      navigation: Object.freeze([
        ["准备", "确认要求并准备媒体"],
        ["高光发现", "发现并组织精彩事件"],
        ["事件审核", "确认事件与候选镜头"],
        ["生成版本", "合成、预览并下载"],
      ]),
    }),
    content_search: Object.freeze({
      label: "内容检索",
      output: "内容视频",
      outputPlural: "内容视频版本",
      candidate: "匹配片段",
      candidatePlural: "匹配片段",
      timeline: "匹配片段来源时间线",
      phases: Object.freeze({ brief: "需求确认", analysis: "内容检索", events: "片段确认", compose: "生成结果" }),
      navigation: Object.freeze([
        ["准备", "描述要查找的内容"],
        ["内容检索", "识别并检索目标内容"],
        ["片段确认", "预览并选择匹配片段"],
        ["生成结果", "合成、预览并下载"],
      ]),
    }),
    person_edit: Object.freeze({
      label: "人物聚焦",
      output: "人物聚焦成片",
      outputPlural: "人物聚焦版本",
      candidate: "出镜片段",
      candidatePlural: "出镜片段",
      timeline: "人物出镜时间线",
      phases: Object.freeze({ brief: "准备画面", analysis: "校正人物", events: "核对出镜", compose: "合成视频" }),
      navigation: Object.freeze([
        ["准备画面", "识别人物并建立连续轨迹"],
        ["校正人物", "合并或拆分不准确的人物分组"],
        ["选择与核对", "选择目标人物并确认出镜范围"],
        ["合成视频", "按确认范围合成并下载"],
      ]),
    }),
    speaker_edit: Object.freeze({
      label: "发言剪辑",
      output: "发言视频",
      outputPlural: "发言视频版本",
      candidate: "发言片段",
      candidatePlural: "发言片段",
      timeline: "说话人发言时间线",
      phases: Object.freeze({ brief: "准备声音", analysis: "校正声音", events: "核对发言", compose: "生成结果" }),
      navigation: Object.freeze([
        ["准备声音", "确认人数与识别范围"],
        ["校正声音", "试听并校正说话人分组"],
        ["选择与核对", "选择目标说话人并确认发言"],
        ["生成结果", "按确认范围合成并下载"],
      ]),
    }),
  });

  const ACTIONS = Object.freeze({
    select: "选择",
    addToBasket: "加入成片清单",
    addToEvent: "加入事件",
    insertTimeline: "插入时间线",
    preview: "生成预览",
    exportVersion: "导出成片",
    download: "下载成片",
  });

  // 历史消息文案归一：消息流是持久化的，早期版本同一个「封面已保存」事件在已存
  // 消息里留下了多种带从句的说法（还会把「不修改视频画面」「可继续绑定」这类约束与
  // 引导句重复播报一遍），代码改动不会回写历史数据。这里在渲染前把旧说法归一到当前
  // 口径（对应 app/copy_messages.py 的 STATUS / MSG 注册表），让历史任务与新建任务
  // 看到同一套文案。
  // 顺序敏感：更具体的说法排在前面。
  const LEGACY_REWRITES = Object.freeze([
    [/^封面已(?:保存|生成并保存为当前任务封面)[，,；;。].*$/, "封面已保存。"],
    [/^本次方案已执行完成[，,].*$/, "本次方案已执行完成。"],
    [/^本次要求已完成[，,].*$/, "本次要求已完成。"],
  ]);

  // 归一后属于「同一事件的重复播报」的状态文案：只保留最新一条，不再堆叠。
  const REPEATABLE_STATUS = Object.freeze(["封面已保存。", "本次方案已执行完成。", "本次要求已完成。"]);

  function normalizeLegacyCopy(value) {
    const text = String(value ?? "").trim();
    if (!text) return value;
    for (const [pattern, replacement] of LEGACY_REWRITES) {
      if (pattern.test(text)) return replacement;
    }
    return value;
  }

  function isRepeatedStatusCopy(value) {
    return REPEATABLE_STATUS.includes(String(value ?? "").trim());
  }

  function workflow(kind) {
    return WORKFLOWS[String(kind || "")] || WORKFLOWS.highlight;
  }

  // 操作前置守卫提示。此前同一句"请先保存或取消当前片段设置"在 app.js 里复制了 11 份。
  const GUARDS = Object.freeze({
    hotEditDirty: (suffix) => `请先保存或取消当前片段设置${suffix ? `，${suffix}` : ""}`,
    // 审核样片与当前时间线版本不一致时，导出前拦截的统一提示。此前散落在前端各处的
    // 说法是"该样片不是当前时间线的最新预览，请进入编辑并重新生成审核样片"，既硬编码又
    // 把一步动作拆成"进入编辑 + 重新生成"两步，且与编辑器"请先更新审核样片"口径不一。
    // 这里统一为与编辑器一致的"审核样片"叫法，并直接指向用户可见的"重新生成审核样片"按钮。
    reviewPreviewStale: "审核样片已过期，请重新生成后再导出。",
  });

  function taskTitle(job, customName = "") {
    if (String(customName || "").trim()) return String(customName).trim();
    const generic = new Set(["事件高光合集", "自动剪辑", "智能剪辑", "内容探索", "内容检索", "发言剪辑", "人物聚焦", "智能高光", "AI 剪辑"]);
    const objective = [job?.objective, job?.agent?.goal, job?.contentSearch?.instruction, job?.request?.contentInstruction, job?.contentInstruction, job?.brief?.objective, job?.request?.objective,
      job?.contentInstruction, job?.instruction, job?.agent?.goal, job?.theme]
      .map(value => String(value || "").trim()).find(value => value && !generic.has(value));
    if (objective) return objective;
    const filename = String(job?.filename || "").replace(/\.[a-z0-9]{2,5}$/i, "");
    return filename && !/^[0-9a-f]{24,}$/i.test(filename) ? filename
      : `未命名任务${job?.id ? ` · ${String(job.id).slice(-6)}` : ""}`;
  }

  function outputQuality(version = {}, output = {}) {
    // Only inspect this output/version. A different plan's report is not evidence.
    const gate = output.qualityGate || version.qualityGate || {};
    const fallback = gate.passed === true ? "passed" : gate.passed === false || output.manualReviewRequired || version.manualReviewRequired ? "needs_review"
      : ["degraded", "review_unavailable"].includes(output.reviewStatus || version.reviewStatus) ? "review_unavailable" : "not_run";
    const status = String(output.qualityStatus || version.qualityStatus || fallback);
    const label = ({ passed: "检查通过", warning: "有提醒待检查", needs_review: "有提醒待检查",
      failed: "检查未通过", unknown: "检查无法判断", unavailable: "检查未完成", review_unavailable: "检查未完成" })[status] || "未检查";
    return { status, label, attention: ["warning", "needs_review", "failed", "unknown", "unavailable", "review_unavailable"].includes(status) };
  }

  global.ClipTalkCopy = Object.freeze({ WORKFLOWS, ACTIONS, GUARDS, workflow, taskTitle, outputQuality, LEGACY_REWRITES, normalizeLegacyCopy, isRepeatedStatusCopy });
})(window);
