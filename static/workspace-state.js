(function createWorkspaceState(global) {
  const STATES = Object.freeze({
    HOME: "home",
    PREPARING: "preparing",
    UPLOADING: "uploading",
    ROUTING_CONFIRMATION: "routing_confirmation",
    ANALYSING: "analysing",
    REVIEWING: "reviewing",
    COMPOSING: "composing",
    COMPLETED: "completed",
    REVISING: "revising",
    FAILED: "failed",
  });

  function derive({ job = null, hasUpload = false, uploading = false, routingConfirmation = false, home = false } = {}) {
    if (home) return STATES.HOME;
    if (uploading) return STATES.UPLOADING;
    if (routingConfirmation) return STATES.ROUTING_CONFIRMATION;
    if (!job) return hasUpload ? STATES.PREPARING : STATES.HOME;
    const execution = job.execution && Number(job.execution.schemaVersion) >= 1 ? job.execution : null;
    const workflow = job.presentation || job.workflow || null;
    const status = String(execution?.status || job.status || "");
    if (["failed", "cancelled"].includes(status)) return STATES.FAILED;
    if (job.reediting) return STATES.REVISING;
    if (status === "completed" || execution?.outcome === "output_ready" || workflow?.phase === "complete") return STATES.COMPLETED;
    if (["render", "auto_composition", "quality_review"].includes(String(execution?.operation || ""))
      || ["render", "complete"].includes(String(workflow?.phase || ""))) return STATES.COMPOSING;
    if (status === "waiting_user" || workflow?.state === "action_required" || workflow?.phase === "review") return STATES.REVIEWING;
    if (execution?.active || ["queued", "running", "cancelling", "awaiting_model_decision"].includes(status)) return STATES.ANALYSING;
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

  global.ClipTalkWorkspaceState = Object.freeze({
    STATES, WORKFLOWS, PHASES, PANELS, MEDIA_KINDS, SELECTION_PURPOSES,
    derive, deriveView, create,
  });
})(window);
