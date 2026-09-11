(function createWorkspaceState(global) {
  const STATES = Object.freeze({
    HOME: "home",
    PREPARING: "preparing",
    AWAITING_INSTRUCTION: "awaiting_instruction",
    UPLOADING: "uploading",
    ROUTING_CONFIRMATION: "routing_confirmation",
    ANALYSING: "analysing",
    REVIEWING: "reviewing",
    COMPOSING: "composing",
    COMPLETED: "completed",
    REVISING: "revising",
    FAILED: "failed",
  });

  const PRESENTATION_STATES = Object.freeze({
    HOME: "home",
    WAITING_INSTRUCTION: "waiting_instruction",
    PLAN_PLANNING: "plan_planning",
    PLAN_CONFIRMATION: "plan_confirmation",
    RUNNING: "running",
    CONTENT_REVIEW: "content_review",
    PREVIEW_REVIEW: "preview_review",
    EXPORT_RUNNING: "export_running",
    EXPORTED: "exported",
    HANDED_OFF: "handed_off",
    NO_RESULT: "no_result",
    FAILED: "failed",
    CANCELLED: "cancelled",
  });

  const EMPTY_EXECUTION = Object.freeze({
    schemaVersion: 1,
    status: "idle",
    operation: "none",
    phase: "",
    active: false,
    background: false,
    outcome: "none",
    progress: {},
    result: {},
    capabilities: {},
  });

  const HOME_PRESENTATION = Object.freeze({
    schemaVersion: 3,
    key: PRESENTATION_STATES.HOME,
    group: "other",
    label: "等待创建任务",
    headline: "开始一个剪辑任务",
    detail: "上传视频后描述想保留的内容。",
    railTitle: "开始剪辑",
    running: false,
    tone: "neutral",
    primaryActionKey: "upload",
    outputCount: 0,
    previewCount: 0,
  });

  function execution(job = null) {
    const value = job?.execution;
    return value && Number(value.schemaVersion) >= 1
      ? Object.freeze({ ...value })
      : EMPTY_EXECUTION;
  }

  function derivePresentation(job = null) {
    if (!job) return HOME_PRESENTATION;
    const value = job.presentation;
    if (value && Number(value.schemaVersion) >= 2 && value.key) {
      return Object.freeze({ ...value });
    }
    // Presentation precedence belongs to the backend. A partial local job must
    // wait for its public snapshot instead of rebuilding a second rule model.
    return Object.freeze({
      schemaVersion: 3,
      key: PRESENTATION_STATES.RUNNING,
      group: "other",
      label: "正在同步任务状态",
      headline: "正在同步任务状态",
      detail: "正在读取统一任务状态，请稍候。",
      railTitle: "任务状态",
      running: false,
      tone: "neutral",
      primaryActionKey: null,
      outputCount: 0,
      previewCount: 0,
    });
  }

  function derive({ job = null, hasUpload = false, uploading = false, routingConfirmation = false, home = false } = {}) {
    if (home) return STATES.HOME;
    if (uploading) return STATES.UPLOADING;
    if (routingConfirmation) return STATES.ROUTING_CONFIRMATION;
    if (!job) return hasUpload ? STATES.PREPARING : STATES.HOME;
    if (job.reediting) return STATES.REVISING;

    const key = derivePresentation(job).key;
    if ([PRESENTATION_STATES.FAILED, PRESENTATION_STATES.CANCELLED].includes(key)) return STATES.FAILED;
    if (key === PRESENTATION_STATES.WAITING_INSTRUCTION) return STATES.AWAITING_INSTRUCTION;
    if (key === PRESENTATION_STATES.EXPORTED) return STATES.COMPLETED;
    if (key === PRESENTATION_STATES.EXPORT_RUNNING) return STATES.COMPOSING;
    if ([
      PRESENTATION_STATES.PLAN_CONFIRMATION,
      PRESENTATION_STATES.CONTENT_REVIEW,
      PRESENTATION_STATES.PREVIEW_REVIEW,
      PRESENTATION_STATES.NO_RESULT,
      PRESENTATION_STATES.HANDED_OFF,
    ].includes(key)) return STATES.REVIEWING;
    if ([PRESENTATION_STATES.PLAN_PLANNING, PRESENTATION_STATES.RUNNING].includes(key)) return STATES.ANALYSING;
    return STATES.PREPARING;
  }

  function create(onChange) {
    let current = STATES.HOME;
    return Object.freeze({
      get value() { return current; },
      update(context) {
        const next = derive(context);
        if (next !== current) {
          const previous = current;
          current = next;
          onChange?.(next, previous);
        }
        return current;
      },
    });
  }

  const WORKFLOWS = Object.freeze(["highlight", "content_search", "person_edit", "speaker_edit"]);
  const PHASES = Object.freeze(["brief", "analysis", "events", "compose"]);
  const PANELS = Object.freeze(["collapsed", "review", "timeline", "versions"]);
  const MEDIA_KINDS = Object.freeze(["source", "output", "material", "sequence"]);
  const SELECTION_PURPOSES = Object.freeze(["none", "include", "person_correction", "voice_correction"]);

  function deriveView(context = {}) {
    const workflow = WORKFLOWS.includes(String(context.workflow)) ? String(context.workflow) : "highlight";
    const phase = PHASES.includes(String(context.phase)) ? String(context.phase) : "brief";
    const panel = PANELS.includes(String(context.panel)) ? String(context.panel) : phase === "compose" ? "versions" : "collapsed";
    const mediaKind = MEDIA_KINDS.includes(String(context.mediaKind)) ? String(context.mediaKind) : "source";
    const selectionPurpose = SELECTION_PURPOSES.includes(String(context.selectionPurpose))
      ? String(context.selectionPurpose) : "none";
    const focusedId = String(context.focusedId || "");
    const selectedIds = [...new Set((context.selectedIds || []).map(String).filter(Boolean))];
    return Object.freeze({
      workflow,
      phase,
      subphase: String(context.subphase || ""),
      panel,
      mediaKind,
      focusedId,
      selectedIds,
      selectionPurpose,
      assistantExpanded: context.assistantExpanded !== false,
    });
  }

  // Group execution records only through explicit handoffs, never filenames.
  // Missing descendants remain navigable; pagination must not hide a task.
  function logicalTasks(jobs = []) {
    const records = new Map(jobs.map(job => [String(job.id), job]));
    const nextId = job => String(job?.latestHandoff?.toJobId || job?.handoff?.activeChildJobId
      || job?.agentHandoffJobId || job?.presentation?.handoffJobId || "");
    const groups = new Map();
    for (const job of records.values()) {
      let current = job;
      const visited = new Set();
      while (records.has(nextId(current)) && !visited.has(String(current.id))) {
        visited.add(String(current.id));
        current = records.get(nextId(current));
      }
      // Corrupt cycles are grouped deterministically, not silently discarded.
      if (visited.has(String(current.id))) current = records.get([...visited].sort()[0]);
      const key = String(current.id);
      if (!groups.has(key)) groups.set(key, { ...current, executionHistory: [], openJobId: visited.has(key) ? key : nextId(current) || key });
      if (String(job.id) !== key) groups.get(key).executionHistory.push(job);
    }
    return [...groups.values()].sort((a, b) => String(b.updatedAt || b.createdAt || "").localeCompare(String(a.updatedAt || a.createdAt || "")));
  }

  function formatTime(seconds) {
    const number = Number(seconds);
    const total = Number.isFinite(number) ? Math.max(0, Math.round(number * 10)) : 0;
    const hours = Math.floor(total / 36000);
    const minutes = Math.floor(total % 36000 / 600);
    const rest = (total % 600 / 10).toFixed(1).padStart(4, "0");
    return `${hours ? `${String(hours).padStart(2, "0")}:` : ""}${String(minutes).padStart(2, "0")}:${rest}`;
  }

  global.ClipTalkWorkspaceState = Object.freeze({
    STATES, PRESENTATION_STATES, WORKFLOWS, PHASES, PANELS, MEDIA_KINDS, SELECTION_PURPOSES,
    derive, derivePresentation, deriveView, execution, create, logicalTasks, formatTime,
  });
})(window);
