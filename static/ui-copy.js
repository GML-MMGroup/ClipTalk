(function createClipTalkCopy(global) {
  const WORKFLOWS = Object.freeze({
    highlight: Object.freeze({
      label: "高光剪辑",
      output: "高光成片",
      outputPlural: "高光版本",
      candidate: "事件镜头",
      candidatePlural: "事件镜头",
      timeline: "事件与镜头时间线",
      phases: Object.freeze({ brief: "需求确认", analysis: "高光发现", events: "事件审核", compose: "生成版本" }),
      navigation: Object.freeze([
        ["准备", "确认要求并准备媒体"],
        ["高光发现", "发现并组织精彩事件"],
        ["事件审核", "确认事件与内部镜头"],
        ["生成版本", "合成、预览并下载"],
      ]),
    }),
    content_search: Object.freeze({
      label: "内容探索",
      output: "内容视频",
      outputPlural: "内容视频版本",
      candidate: "匹配片段",
      candidatePlural: "匹配片段",
      timeline: "匹配片段来源时间线",
      phases: Object.freeze({ brief: "需求确认", analysis: "内容探索", events: "片段确认", compose: "生成结果" }),
      navigation: Object.freeze([
        ["准备", "描述要查找的内容"],
        ["内容探索", "识别并检索目标内容"],
        ["片段确认", "预览并选择匹配片段"],
        ["生成结果", "合成、预览并下载"],
      ]),
    }),
    person_edit: Object.freeze({
      label: "按人物剪辑",
      output: "人物剪辑",
      outputPlural: "人物剪辑版本",
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
      label: "按说话人剪辑",
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
    exportVersion: "导出新版本",
    download: "下载",
  });

  function workflow(kind) {
    return WORKFLOWS[String(kind || "")] || WORKFLOWS.highlight;
  }

  global.ClipTalkCopy = Object.freeze({ WORKFLOWS, ACTIONS, workflow });
})(window);
