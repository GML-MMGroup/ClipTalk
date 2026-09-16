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
        <div class="bubble"><small>智能剪辑 Agent</small><p>视频已添加。请描述想保留的内容，或选择下方剪辑方式。我会先整理一份可确认的剪辑计划。</p></div>
        <section class="brief-card brief-card-redesign">
          <header class="brief-card-header"><div><small>剪辑目标</small><strong>描述你要得到的成片</strong><p>写下内容、时长和发布用途，下一步确认剪辑方案。</p></div><span class="brief-ready-badge" id="briefReadyBadge">视频已就绪</span></header>
          <section id="briefWorkflowHelp" class="brief-workflow-help brief-auto-route brief-agent-launch" aria-label="智能 Agent 任务">
            <div class="brief-agent-heading"><span>智能剪辑</span><strong>说明你想得到什么</strong><p>自动选择会根据描述组合能力；手动选择可锁定主要处理方式。</p></div>
            <div id="briefCapabilitySelection" class="brief-capability-selection" data-mode="auto"><small>当前方式</small><strong>自动选择</strong><span>系统会在方案中说明使用了哪些能力</span></div>
            <label class="brief-auto-query brief-agent-goal" for="briefAgentGoal"><span>剪辑目标</span><textarea id="briefAgentGoal" rows="3" maxlength="4000" placeholder="例如：剪成 3 分钟访谈精华，按主题组织回答，删除重复表达并生成字幕预览"></textarea></label>
            <div class="brief-agent-controls"><details><summary>高级选项</summary><label for="briefAgentSkillSelect"><span>本次使用的 Skill</span><select id="briefAgentSkillSelect" aria-label="为新任务指定 Skill"><option value="">自动选择</option></select></label><label for="briefAgentExecutionMode"><span>执行方式</span><select id="briefAgentExecutionMode" aria-label="选择 Agent 执行方式"><option value="autonomous_review" selected>自动执行到审核样片</option><option value="stepwise_review">分步审核</option></select></label><button type="button" data-open-agent-registry>管理 Skills</button><small>自动模式确认计划后执行到样片审核。</small></details><button type="button" class="primary" data-start-agent>生成剪辑计划</button></div>
          </section>
          <details class="brief-template-picker" open>
            <summary><span><strong>选择处理方式</strong><small>保留自动选择，也可以查看并指定具体能力</small></span><b>9 类能力</b></summary>
            <div class="workflow-entry-grid" role="radiogroup" aria-label="选择剪辑能力类别">
            <button type="button" class="workflow-entry-card capability-auto selected" data-capability-category="auto" aria-pressed="true"><i><svg viewBox="0 0 24 24" aria-hidden="true"><circle cx="5" cy="6" r="1.8"/><circle cx="19" cy="6" r="1.8"/><circle cx="12" cy="18" r="1.8"/><path d="M6.8 6h4.3a3 3 0 0 1 3 3v2M17.2 6h-.7a2.5 2.5 0 0 0-2.5 2.5V11M12 16.2V11"/></svg></i><span><strong>自动选择</strong><small>描述结果，由系统组合适合的能力</small></span><b>推荐</b></button>
            <button type="button" class="workflow-entry-card highlight" data-workflow-choice="highlight" data-capability-category="highlight" aria-pressed="false"><i><svg viewBox="0 0 24 24" aria-hidden="true"><path d="M4 8.5h16v11H4zM4 8.5 6 4h15l-2 4.5M9 4 7 8.5M15 4l-2 4.5"/><path d="m10 12 4 2.3-4 2.2v-4.5Z"/></svg></i><span><strong>智能高光</strong><small>通看全片，发现事件并生成多个高光版本</small></span><b>推荐</b></button>
            <button type="button" class="workflow-entry-card content_search" data-workflow-choice="content_search" data-capability-category="content_search" aria-pressed="false"><i><svg viewBox="0 0 24 24" aria-hidden="true"><circle cx="10.5" cy="10.5" r="5.5" /><path d="m15 15 4.5 4.5" /></svg></i><span><strong>内容检索</strong><small>按描述查找动作、场景、对白、文字或声音</small></span><b>检索</b></button>
            <button type="button" class="workflow-entry-card person_edit" data-workflow-choice="person_edit" data-capability-category="person_edit" aria-pressed="false"><i><svg viewBox="0 0 24 24" aria-hidden="true"><path d="M8 3H4v4M16 3h4v4M8 21H4v-4M16 21h4v-4"/><circle cx="12" cy="9" r="2.7"/><path d="M7.5 17c.6-2.7 2.1-4 4.5-4s3.9 1.3 4.5 4"/></svg></i><span><strong>人物聚焦</strong><small>从人物卡选择目标，提取所有出镜片段</small></span><b>人物</b></button>
            <button type="button" class="workflow-entry-card speaker_edit" data-workflow-choice="speaker_edit" data-capability-category="speaker_edit" aria-pressed="false"><i><svg viewBox="0 0 24 24" aria-hidden="true"><rect x="9" y="3.5" width="6" height="11" rx="3"/><path d="M6.5 11.5a5.5 5.5 0 0 0 11 0M12 17v3M9 20h6"/></svg></i><span><strong>发言剪辑</strong><small>区分不同声音，试听后提取对应发言</small></span><b>声音</b></button>
            <button type="button" class="workflow-entry-card capability-revision" data-capability-category="revision" aria-pressed="false"><i><svg viewBox="0 0 24 24" aria-hidden="true"><path d="M4 6h7M15 6h5M4 12h3M11 12h9M4 18h9M17 18h3"/><circle cx="13" cy="6" r="2"/><circle cx="9" cy="12" r="2"/><circle cx="15" cy="18" r="2"/></svg></i><span><strong>剪辑调整</strong><small>调整已有视频或样片的结构与节奏</small></span><b>编辑</b></button>
            <button type="button" class="workflow-entry-card capability-format" data-capability-category="format" aria-pressed="false"><i><svg viewBox="0 0 24 24" aria-hidden="true"><rect x="5" y="3" width="14" height="18" rx="2" /><path d="M8 8h8M8 12h8M9 17h6" /></svg></i><span><strong>版式适配</strong><small>修改字幕并适配横屏、竖屏或方形</small></span><b>适配</b></button>
            <button type="button" class="workflow-entry-card capability-package" data-capability-category="package" aria-pressed="false"><i><svg viewBox="0 0 24 24" aria-hidden="true"><rect x="3" y="5" width="18" height="14" rx="2" /><path d="m7 15 3-3 2 2 3-4 3 5M8 9h.01" /></svg></i><span><strong>视觉包装</strong><small>制作封面、片头、图文和补充画面</small></span><b>包装</b></button>
            <button type="button" class="workflow-entry-card capability-delivery" data-capability-category="delivery" aria-pressed="false"><i><svg viewBox="0 0 24 24" aria-hidden="true"><path d="M12 3v12M8 11l4 4 4-4" /><path d="M5 19h14" /></svg></i><span><strong>导出交付</strong><small>按平台导出、交付草稿或检查成片</small></span><b>交付</b></button>
            </div>
            <section id="briefCapabilityDetail" class="brief-capability-detail hidden" aria-live="polite"></section>
          </details>
          <section class="brief-section brief-core-settings" aria-label="本次任务核心设置">
            <label class="brief-core-field"><span>素材范围</span><select id="briefSourceScope"><option value="all" selected>全片</option><option value="opening">开头</option><option value="front_half">前半段</option><option value="middle">中段</option><option value="back_half">后半段</option><option value="ending">结尾</option><option value="custom">自定义</option></select><small id="briefScopeSummary" class="brief-field-help">使用完整源视频</small></label>
            <div id="briefCustomScope" class="brief-custom-scope hidden"><label><span>开始</span><input id="briefScopeStart" type="text" inputmode="numeric" placeholder="00:00" aria-label="素材范围开始时间"></label><b>→</b><label><span>结束</span><input id="briefScopeEnd" type="text" inputmode="numeric" placeholder="00:00" aria-label="素材范围结束时间"></label></div>
            <div id="briefHighlightSettings" class="brief-special-settings brief-highlight-settings hidden"><div><strong>自动发现并生成高光</strong><p>不填写文字要求也可以直接开始；系统会通看所选素材并生成多个不同编排版本。</p></div><label class="brief-highlight-query" for="briefHighlightInstruction"><span>高光主题或重点（可选）</span><textarea id="briefHighlightInstruction" rows="2" placeholder="例如：重点保留产品演示和观众反应" aria-describedby="briefHighlightInstructionHelp"></textarea><small id="briefHighlightInstructionHelp">只作为高光筛选与编排偏好，不填写则由系统自动发现。</small></label><div class="brief-highlight-options"><label><span>目标成片时长（秒）</span><input id="briefHighlightTargetSeconds" type="number" min="4" step="1" placeholder="自动" aria-describedby="briefHighlightDurationHelp"></label><label><span>生成版本数</span><select id="briefHighlightVariantCount"><option value="1">1 个版本</option><option value="2">2 个版本</option><option value="3" selected>3 个版本</option><option value="4">4 个版本</option></select></label></div><small id="briefHighlightDurationHelp">目标时长留空则由系统根据素材自动确定，最短为 4 秒。</small><button type="button" class="primary brief-mode-start" data-start-workflow="highlight">开始智能高光</button></div>
            <div id="briefContentSettings" class="brief-special-settings brief-content-settings hidden"><div><strong>描述想找的内容</strong><p>输入动作、物品、场景、对白或屏幕文字，系统会自动选择所需证据。</p></div><label class="brief-content-query" for="briefContentInstruction"><span>检索要求</span><textarea id="briefContentInstruction" rows="3" placeholder="例如：找出煎鸡蛋的画面" aria-describedby="briefContentInstructionHelp"></textarea></label><small id="briefContentInstructionHelp">也可以查找采访问题、提到冰箱的对白或特定屏幕文字。</small><button type="button" class="primary brief-mode-start" data-start-content-search>开始内容检索</button></div>
            <div id="briefSpeakerSettings" class="brief-special-settings hidden"><label><span>预计说话人数</span><select id="briefExpectedVoiceCount"><option value="0">自动判断</option><option value="1">1 人</option><option value="2">2 人</option><option value="3">3 人</option><option value="4">4 人</option><option value="5">5 人</option><option value="6">6 人</option><option value="7">7 人</option><option value="8">8 人</option><option value="9">9 人</option><option value="10">10 人</option><option value="11">11 人</option><option value="12">12 人</option></select></label><small>知道人数时可直接指定；不确定时由系统自动判断。</small><button type="button" class="primary brief-mode-start" data-start-workflow="speaker_edit">开始识别说话人</button></div>
            <div id="briefPersonSettings" class="brief-special-settings hidden"><div><strong>默认提取所有出镜片段</strong><p>识别后可选择一个或多个人物，并切换“任一人物出现”或“所有人物同时同框”。</p></div><button type="button" class="primary brief-mode-start" data-start-workflow="person_edit">开始识别人物</button></div>
            <div id="briefIntentClarification" class="brief-intent-clarification hidden" role="alert"><strong>需要确认剪辑方向</strong><p>请选择最接近你目标的处理方式。</p><div><button type="button" data-intent-choice="highlight">智能高光</button><button type="button" data-intent-choice="content_search">内容检索</button><button type="button" data-intent-choice="person_edit">人物聚焦</button><button type="button" data-intent-choice="speaker_edit">发言剪辑</button></div></div>
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
