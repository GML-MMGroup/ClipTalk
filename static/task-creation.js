(function createTaskCreation(global) {
  function escapeHtml(value) {
    const node = document.createElement("span");
    node.textContent = String(value || "");
    return node.innerHTML;
  }

  function briefMarkup(filename) {
    return `
      <article class="chat-message user"><span class="avatar">你</span><div class="bubble"><small>你</small><p>已选择 ${escapeHtml(filename)}</p></div></article>
      <article class="chat-message assistant brief-message"><span class="avatar">AI</span><div class="brief-wrap">
        <div class="bubble"><small>视频剪辑助手</small><p>视频已就绪。请在任务设置中选择处理方式并确认范围。</p></div>
        <section class="brief-card brief-card-redesign">
          <header class="brief-card-header"><div><small>选择剪辑方式</small><strong>这次想怎么处理视频？</strong><p>四种任务共享视频与分析缓存，但结果和对话互不覆盖。</p></div><span class="brief-ready-badge" id="briefReadyBadge">视频已就绪</span></header>
          <div class="workflow-entry-grid" role="radiogroup" aria-label="选择剪辑方式">
            <button type="button" class="workflow-entry-card" data-workflow-choice="highlight" aria-pressed="false"><i>01</i><span><strong>高光剪辑</strong><small>通看全片，发现事件并生成多个高光版本</small></span><b>自动编排</b></button>
            <button type="button" class="workflow-entry-card" data-workflow-choice="content_search" aria-pressed="false"><i>02</i><span><strong>内容探索</strong><small>按描述查找动作、场景、对白、文字或声音</small></span><b>按需检索</b></button>
            <button type="button" class="workflow-entry-card" data-workflow-choice="person_edit" aria-pressed="false"><i>03</i><span><strong>按人物剪辑</strong><small>从人物卡选择目标，提取所有出镜片段</small></span><b>依据画面</b></button>
            <button type="button" class="workflow-entry-card" data-workflow-choice="speaker_edit" aria-pressed="false"><i>04</i><span><strong>按说话人剪辑</strong><small>区分不同声音，试听后提取对应发言</small></span><b>依据声音</b></button>
          </div>
          <section class="brief-section brief-core-settings" aria-label="本次任务核心设置">
            <label class="brief-core-field"><span>素材范围</span><select id="briefSourceScope"><option value="all" selected>全片</option><option value="opening">开头</option><option value="front_half">前半段</option><option value="middle">中段</option><option value="back_half">后半段</option><option value="ending">结尾</option><option value="custom">自定义</option></select><small id="briefScopeSummary" class="brief-field-help">使用完整源视频</small></label>
            <div id="briefCustomScope" class="brief-custom-scope hidden"><label><span>开始</span><input id="briefScopeStart" type="text" inputmode="numeric" placeholder="00:00" aria-label="素材范围开始时间"></label><b>→</b><label><span>结束</span><input id="briefScopeEnd" type="text" inputmode="numeric" placeholder="00:00" aria-label="素材范围结束时间"></label></div>
            <div id="briefWorkflowHelp" class="brief-workflow-help"><div><strong>先选择一种处理方式</strong><p>选择后只展示该流程需要的设置，确认完成才会上传并开始分析。</p></div><label class="brief-auto-query" for="briefAutoInstruction"><span>不确定用哪种？直接描述结果</span><textarea id="briefAutoInstruction" rows="2" placeholder="例如：帮我剪一下这个视频，重点保留产品介绍"></textarea></label><div class="brief-auto-submit"><small>AI 只负责判断处理方式；存在歧义时会先让你确认，不会直接开始。</small><button type="button" data-start-auto-workflow>让 AI 判断</button></div></div>
            <div id="briefHighlightSettings" class="brief-special-settings brief-highlight-settings hidden"><div><strong>自动发现并生成高光</strong><p>不填写文字要求也可以直接开始；系统会通看所选素材并生成多个不同编排版本。</p></div><label class="brief-highlight-query" for="briefHighlightInstruction"><span>高光主题或重点（可选）</span><textarea id="briefHighlightInstruction" rows="2" placeholder="例如：重点保留产品演示和观众反应" aria-describedby="briefHighlightInstructionHelp"></textarea><small id="briefHighlightInstructionHelp">只作为高光筛选与编排偏好，不填写则由系统自动发现。</small></label><div class="brief-highlight-options"><label><span>目标成片时长（秒）</span><input id="briefHighlightTargetSeconds" type="number" min="4" step="1" placeholder="自动" aria-describedby="briefHighlightDurationHelp"></label><label><span>生成版本数</span><select id="briefHighlightVariantCount"><option value="1">1 个版本</option><option value="2">2 个版本</option><option value="3" selected>3 个版本</option><option value="4">4 个版本</option></select></label></div><button type="button" class="primary" data-start-workflow="highlight">开始高光分析</button><small id="briefHighlightDurationHelp">目标时长留空则由系统根据素材自动确定，最短为 4 秒。</small></div>
            <div id="briefContentSettings" class="brief-special-settings brief-content-settings hidden"><div><strong>描述想找的内容</strong><p>输入动作、物品、场景、对白或屏幕文字，系统会自动选择所需证据。</p></div><label class="brief-content-query" for="briefContentInstruction"><span>检索要求</span><textarea id="briefContentInstruction" rows="3" placeholder="例如：找出煎鸡蛋的画面" aria-describedby="briefContentInstructionHelp"></textarea></label><div class="brief-content-submit"><small id="briefContentInstructionHelp">也可以查找采访问题、提到冰箱的对白或特定屏幕文字。按 Ctrl/⌘ + Enter 开始检索。</small><button type="button" class="primary" data-start-content-search>开始检索</button></div></div>
            <div id="briefSpeakerSettings" class="brief-special-settings hidden"><label><span>预计说话人数</span><select id="briefExpectedVoiceCount"><option value="0">自动判断</option><option value="1">1 人</option><option value="2">2 人</option><option value="3">3 人</option><option value="4">4 人</option><option value="5">5 人</option><option value="6">6 人</option><option value="7">7 人</option><option value="8">8 人</option><option value="9">9 人</option><option value="10">10 人</option><option value="11">11 人</option><option value="12">12 人</option></select></label><button type="button" class="primary" data-start-workflow="speaker_edit">开始识别说话人</button><small>知道人数时可直接指定；不确定时由系统自动判断。</small></div>
            <div id="briefPersonSettings" class="brief-special-settings hidden"><div><strong>默认提取所有出镜片段</strong><p>识别后可选择一个或多个人物，并切换“任一人物出现”或“所有人物同时同框”。</p></div><button type="button" class="primary" data-start-workflow="person_edit">开始识别画面人物</button></div>
            <div id="briefIntentClarification" class="brief-intent-clarification hidden" role="alert"><strong>需要确认剪辑方向</strong><p>请选择最接近你目标的处理方式。</p><div><button type="button" data-intent-choice="highlight">自动生成高光</button><button type="button" data-intent-choice="content_search">查找并截取内容</button><button type="button" data-intent-choice="person_edit">按画面人物剪辑</button><button type="button" data-intent-choice="speaker_edit">按说话人剪辑</button></div></div>
            <p id="briefCreateError" class="brief-create-error hidden" role="alert"></p>
          </section>
          <footer class="brief-submit-row"><span id="briefSubmitHint">先选择一种剪辑方式，再在对应设置中开始处理</span></footer>
        </section>
      </div></article>`;
  }

  function buildForm({
    file, uploadSessionId = "", instruction, taskMode = "auto", sourceScope = {}, entryWorkflow = "", workflowKind = "",
    targetSeconds = "", variantCount = "",
  }) {
    const form = new FormData();
    const scopeKind = String(sourceScope.kind || "all");
    const scopeStart = sourceScope.start ?? "";
    const scopeEnd = sourceScope.end ?? "";
    const values = {
      expected_size_bytes: String(file.size), task_mode: taskMode, intent_mode: taskMode,
      storage_mode: "editable", instruction, theme: instruction,
      parameter_context: "adaptive_v1", force_reanalyze: "false",
      source_scope_kind: scopeKind, source_scope_start: String(scopeStart), source_scope_end: String(scopeEnd),
      search_scope_kind: scopeKind, search_scope_start: String(scopeStart), search_scope_end: String(scopeEnd),
    };
    if (targetSeconds !== "") {
      values.target_seconds = String(targetSeconds);
      values.total_target_seconds = String(targetSeconds);
    }
    if (variantCount !== "") values.auto_variant_count = String(variantCount);
    if (entryWorkflow) values.entry_workflow = entryWorkflow;
    if (workflowKind) values.workflow_kind = workflowKind;
    if (uploadSessionId) form.append("upload_session_id", uploadSessionId);
    else form.append("video", file);
    Object.entries(values).forEach(([key, value]) => form.append(key, value));
    return form;
  }

  global.ClipTalkTaskCreation = Object.freeze({ briefMarkup, buildForm });
})(window);
