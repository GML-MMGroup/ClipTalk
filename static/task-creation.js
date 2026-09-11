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
        <div class="bubble"><small>智能剪辑 Agent</small><p>我已拿到这个视频。先告诉我你想剪成什么样；我会在确认需求后再生成计划。</p></div>
        <section class="brief-card brief-card-redesign">
          <header class="brief-card-header"><div><small>剪辑目标</small><strong>描述你要得到的成片</strong><p>写下内容、时长和发布用途，下一步确认剪辑方案。</p></div><span class="brief-ready-badge" id="briefReadyBadge">视频已就绪</span></header>
          <section id="briefWorkflowHelp" class="brief-workflow-help brief-auto-route brief-agent-launch" aria-label="智能 Agent 任务">
            <div class="brief-agent-heading"><span>PI AGENT · CONVERSATION FIRST</span><strong>先说目标，再让 Agent 拆解</strong><p>上传后先等待你的剪辑要求；确认需求后才会生成计划、调用分析或渲染工具。</p></div>
            <label class="brief-auto-query brief-agent-goal" for="briefAgentGoal"><span>剪辑目标</span><textarea id="briefAgentGoal" rows="3" maxlength="4000" placeholder="例如：剪成 3 分钟访谈精华，按主题组织回答，删除重复表达并生成字幕预览"></textarea></label>
            <div class="brief-agent-controls"><details><summary>高级选项</summary><label for="briefAgentSkillSelect"><span>本次使用的 Skill</span><select id="briefAgentSkillSelect" aria-label="为新任务指定 Skill"><option value="">自动选择</option></select></label><label for="briefAgentExecutionMode"><span>执行方式</span><select id="briefAgentExecutionMode" aria-label="选择 Agent 执行方式"><option value="autonomous_review" selected>自动执行到审核样片</option><option value="stepwise_review">分步审核</option></select></label><button type="button" data-open-agent-registry>管理 Skills</button><small>自动模式确认计划后执行到样片审核。</small></details><button type="button" class="primary" data-start-agent>生成剪辑计划</button></div>
          </section>
          <details class="brief-template-picker">
            <summary><span><strong>高级：手动选择工作流</strong><small>可选，通常描述目标即可</small></span></summary>
            <div class="workflow-entry-grid" role="radiogroup" aria-label="选择快速剪辑模板">
            <button type="button" class="workflow-entry-card highlight" data-workflow-choice="highlight" aria-pressed="false"><i><svg viewBox="0 0 24 24" aria-hidden="true"><path d="m12 3 1.6 5.4L19 10l-5.4 1.6L12 17l-1.6-5.4L5 10l5.4-1.6zM18.5 15.5l.7 2.3 2.3.7-2.3.7-.7 2.3-.7-2.3-2.3-.7 2.3-.7z" /></svg></i><span><strong>高光剪辑</strong><small>通看全片，发现事件并生成多个高光版本</small></span><b>推荐</b></button>
            <button type="button" class="workflow-entry-card content_search" data-workflow-choice="content_search" aria-pressed="false"><i><svg viewBox="0 0 24 24" aria-hidden="true"><circle cx="10.5" cy="10.5" r="5.5" /><path d="m15 15 4.5 4.5" /></svg></i><span><strong>内容探索</strong><small>按描述查找动作、场景、对白、文字或声音</small></span><b>检索</b></button>
            <button type="button" class="workflow-entry-card person_edit" data-workflow-choice="person_edit" aria-pressed="false"><i><svg viewBox="0 0 24 24" aria-hidden="true"><circle cx="12" cy="8" r="3.5" /><path d="M5.5 19c.8-3.4 3-5.2 6.5-5.2s5.7 1.8 6.5 5.2" /></svg></i><span><strong>按人物剪辑</strong><small>从人物卡选择目标，提取所有出镜片段</small></span><b>人物</b></button>
            <button type="button" class="workflow-entry-card speaker_edit" data-workflow-choice="speaker_edit" aria-pressed="false"><i><svg viewBox="0 0 24 24" aria-hidden="true"><path d="M4 12h2M8 8v8M12 5v14M16 8v8M20 10v4" /></svg></i><span><strong>按说话人剪辑</strong><small>区分不同声音，试听后提取对应发言</small></span><b>声音</b></button>
            </div>
          </details>
          <section class="brief-section brief-core-settings" aria-label="本次任务核心设置">
            <label class="brief-core-field"><span>素材范围</span><select id="briefSourceScope"><option value="all" selected>全片</option><option value="opening">开头</option><option value="front_half">前半段</option><option value="middle">中段</option><option value="back_half">后半段</option><option value="ending">结尾</option><option value="custom">自定义</option></select><small id="briefScopeSummary" class="brief-field-help">使用完整源视频</small></label>
            <div id="briefCustomScope" class="brief-custom-scope hidden"><label><span>开始</span><input id="briefScopeStart" type="text" inputmode="numeric" placeholder="00:00" aria-label="素材范围开始时间"></label><b>→</b><label><span>结束</span><input id="briefScopeEnd" type="text" inputmode="numeric" placeholder="00:00" aria-label="素材范围结束时间"></label></div>
            <div id="briefHighlightSettings" class="brief-special-settings brief-highlight-settings hidden"><div><strong>自动发现并生成高光</strong><p>不填写文字要求也可以直接开始；系统会通看所选素材并生成多个不同编排版本。</p></div><label class="brief-highlight-query" for="briefHighlightInstruction"><span>高光主题或重点（可选）</span><textarea id="briefHighlightInstruction" rows="2" placeholder="例如：重点保留产品演示和观众反应" aria-describedby="briefHighlightInstructionHelp"></textarea><small id="briefHighlightInstructionHelp">只作为高光筛选与编排偏好，不填写则由系统自动发现。</small></label><div class="brief-highlight-options"><label><span>目标成片时长（秒）</span><input id="briefHighlightTargetSeconds" type="number" min="4" step="1" placeholder="自动" aria-describedby="briefHighlightDurationHelp"></label><label><span>生成版本数</span><select id="briefHighlightVariantCount"><option value="1">1 个版本</option><option value="2">2 个版本</option><option value="3" selected>3 个版本</option><option value="4">4 个版本</option></select></label></div><small id="briefHighlightDurationHelp">目标时长留空则由系统根据素材自动确定，最短为 4 秒。</small><button type="button" class="primary brief-mode-start" data-start-workflow="highlight">开始高光剪辑</button></div>
            <div id="briefContentSettings" class="brief-special-settings brief-content-settings hidden"><div><strong>描述想找的内容</strong><p>输入动作、物品、场景、对白或屏幕文字，系统会自动选择所需证据。</p></div><label class="brief-content-query" for="briefContentInstruction"><span>检索要求</span><textarea id="briefContentInstruction" rows="3" placeholder="例如：找出煎鸡蛋的画面" aria-describedby="briefContentInstructionHelp"></textarea></label><small id="briefContentInstructionHelp">也可以查找采访问题、提到冰箱的对白或特定屏幕文字。</small><button type="button" class="primary brief-mode-start" data-start-content-search>开始内容探索</button></div>
            <div id="briefSpeakerSettings" class="brief-special-settings hidden"><label><span>预计说话人数</span><select id="briefExpectedVoiceCount"><option value="0">自动判断</option><option value="1">1 人</option><option value="2">2 人</option><option value="3">3 人</option><option value="4">4 人</option><option value="5">5 人</option><option value="6">6 人</option><option value="7">7 人</option><option value="8">8 人</option><option value="9">9 人</option><option value="10">10 人</option><option value="11">11 人</option><option value="12">12 人</option></select></label><small>知道人数时可直接指定；不确定时由系统自动判断。</small><button type="button" class="primary brief-mode-start" data-start-workflow="speaker_edit">开始识别说话人</button></div>
            <div id="briefPersonSettings" class="brief-special-settings hidden"><div><strong>默认提取所有出镜片段</strong><p>识别后可选择一个或多个人物，并切换“任一人物出现”或“所有人物同时同框”。</p></div><button type="button" class="primary brief-mode-start" data-start-workflow="person_edit">开始识别人物</button></div>
            <div id="briefIntentClarification" class="brief-intent-clarification hidden" role="alert"><strong>需要确认剪辑方向</strong><p>请选择最接近你目标的处理方式。</p><div><button type="button" data-intent-choice="highlight">自动生成高光</button><button type="button" data-intent-choice="content_search">查找并截取内容</button><button type="button" data-intent-choice="person_edit">按画面人物剪辑</button><button type="button" data-intent-choice="speaker_edit">按说话人剪辑</button></div></div>
            <p id="briefCreateError" class="brief-create-error hidden" role="alert"></p>
          </section>
          <footer class="brief-submit-row"><span id="briefSubmitHint">填写目标后生成计划；确认前不会分析或渲染</span></footer>
        </section>
      </div></article>`;
  }

  function buildForm({
    file, uploadSessionId = "", instruction, taskMode = "auto", sourceScope = {}, entryWorkflow = "", workflowKind = "",
    agentDraft = false, draftSessionId = "",
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
    if (agentDraft) values.agent_draft = "true";
    if (draftSessionId) values.draft_session_id = String(draftSessionId);
    if (uploadSessionId) form.append("upload_session_id", uploadSessionId);
    else form.append("video", file);
    Object.entries(values).forEach(([key, value]) => form.append(key, value));
    return form;
  }

  global.ClipTalkTaskCreation = Object.freeze({ briefMarkup, buildForm });
})(window);
