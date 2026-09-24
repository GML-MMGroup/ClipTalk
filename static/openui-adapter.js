/* ClipTalk × OpenUI：确定性转译层
 *
 * 把宿主侧已有的结构化数据转成 OpenUI Lang 文本，交给 iframe 里的 Renderer 渲染。
 *
 * 设计原则：
 *   1. 纯函数 —— 无网络、无 DOM、无副作用，可单元测试
 *   2. 不让 LLM 生成 UI —— ClipTalk 的 VLM 负责看视频，不该兼职输出布局
 *   3. 参数顺序按组件 Zod schema 的 key 顺序（OpenUI Lang 是位置化参数）
 *
 * 组件签名（读自 openui/packages/react-ui/src/genui-lib/）：
 *   ListItem(title, subtitle?, image?, actionLabel?, action?)
 *   ListBlock(items, variant?, size?)        variant: "number" | "image"
 *   Card(children, variant?, direction?, gap?, align?, justify?, wrap?)
 *   TextContent(text, size?)
 *
 * ⚠️ 实测校正（2026-09-17，openui 0.1.4）：
 *   官方文档写 "以 root = Stack(...) 开头"，但该库实际 root 是 Card，
 *   且 components 中**不存在 Stack**（已 probe 确认，共 84 个组件）。
 */
(function (global) {
  "use strict";

  // OpenUI Lang 的字符串字面量放在双引号内，值里的反斜杠/双引号/换行必须转义
  function quote(value) {
    return String(value === null || value === undefined ? "" : value)
      .replace(/\\/g, "\\\\")
      .replace(/"/g, '\\"')
      .replace(/\r?\n/g, " ")
      .replace(/\s+/g, " ")
      .trim();
  }

  function clip(value, max) {
    var text = quote(value);
    return text.length > max ? text.slice(0, Math.max(0, max - 1)) + "…" : text;
  }

  /* 活动流 → OpenUI Lang
   * items: [{ time, title, detail }]，宿主侧已用现有 activityCopy() 算好文案
   */
  function activityToOpenUILang(items) {
    var rows = Array.isArray(items) ? items.filter(Boolean) : [];
    if (!rows.length) {
      return 'root = Card([empty])\nempty = TextContent("还没有活动记录")';
    }

    var lines = [];
    var refs = [];
    rows.slice(0, 80).forEach(function (row, index) {
      var ref = "i" + index;
      var prefix = row.time ? row.time + " · " : "";
      var title = clip(prefix + row.title, 120);
      var subtitle = clip(row.detail, 200);
      lines.push(ref + ' = ListItem("' + title + '", "' + subtitle + '")');
      refs.push(ref);
    });

    lines.push('items = ListBlock([' + refs.join(", ") + '], "number", "small")');
    lines.unshift("root = Card([items])");
    return lines.join("\n");
  }

  global.ClipTalkOpenUIAdapter = {
    quote: quote,
    activityToOpenUILang: activityToOpenUILang,
  };
})(window);
