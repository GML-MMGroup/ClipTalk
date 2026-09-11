import { existsSync, mkdirSync } from "node:fs";
import { createServer } from "node:http";
import { resolve } from "node:path";
import { pathToFileURL } from "node:url";
import { spawn } from "node:child_process";
import { authorized, serviceToken, validatePlugin } from "./security.mjs";
import { OperationStore } from "./operation-store.mjs";

import {
  createAgentSession,
  DefaultResourceLoader,
  ModelRuntime,
  SessionManager,
  SettingsManager,
} from "@earendil-works/pi-coding-agent";
import { Type } from "typebox";

const host = process.env.CLIPTALK_AGENT_HOST || "127.0.0.1";
const port = Number.parseInt(process.env.CLIPTALK_AGENT_PORT || "5190", 10);
const defaultDataRoot = resolve(process.env.HIGHLIGHT_DATA_ROOT || resolve(process.cwd(), "../data"), "agent");
const agentDir = resolve(defaultDataRoot, "pi-runtime");
mkdirSync(agentDir, { recursive: true });
const agentServiceToken = serviceToken(resolve(defaultDataRoot, "service-token"));
const operationStore = new OperationStore(resolve(defaultDataRoot, "tool-operations.sqlite3"));

const activePlugins = new Map();
const requestLimit = 4 * 1024 * 1024;

function jsonResponse(response, status, value) {
  const body = JSON.stringify(value);
  response.writeHead(status, {
    "Content-Type": "application/json; charset=utf-8",
    "Content-Length": Buffer.byteLength(body),
    "Cache-Control": "no-store",
  });
  response.end(body);
}

async function readJson(request) {
  const chunks = [];
  let length = 0;
  for await (const chunk of request) {
    length += chunk.length;
    if (length > requestLimit) throw new Error("request_too_large");
    chunks.push(chunk);
  }
  if (!chunks.length) return {};
  const parsed = JSON.parse(Buffer.concat(chunks).toString("utf8"));
  if (!parsed || typeof parsed !== "object" || Array.isArray(parsed)) throw new Error("invalid_json_object");
  return parsed;
}

function normalizedModelConfig(value) {
  const config = value && typeof value === "object" ? value : {};
  const apiKey = String(config.apiKey || "").trim();
  const model = String(config.model || "").trim();
  const baseUrl = String(config.baseUrl || "").trim().replace(/\/$/, "");
  if (!apiKey || !model || !baseUrl) throw new Error("Agent 模型尚未配置完整");
  const protocol = String(config.protocol || "openai").toLowerCase();
  return {
    apiKey,
    model,
    baseUrl,
    api: protocol.includes("anthropic") ? "anthropic-messages" : "openai-completions",
    reasoning: String(config.thinkingType || "").toLowerCase() !== "disabled",
  };
}

async function createRuntime(config) {
  const modelRuntime = await ModelRuntime.create({ modelsPath: null, allowModelNetwork: false });
  modelRuntime.registerProvider("cliptalk-agent", {
    baseUrl: config.baseUrl,
    apiKey: config.apiKey,
    api: config.api,
    compat: config.api === "openai-completions" ? {
      supportsDeveloperRole: false,
      supportsReasoningEffort: false,
    } : undefined,
    models: [{
      id: config.model,
      name: config.model,
      reasoning: config.reasoning,
      input: ["text"],
      cost: { input: 0, output: 0, cacheRead: 0, cacheWrite: 0 },
      contextWindow: 128000,
      maxTokens: 16384,
    }],
  });
  const model = modelRuntime.getModel("cliptalk-agent", config.model);
  if (!model) throw new Error("无法注册 Agent 模型");
  return { modelRuntime, model };
}

async function sessionManagerFor(workspaceId, sessionDir, cwd) {
  const directory = resolve(sessionDir || resolve(defaultDataRoot, "sessions"));
  mkdirSync(directory, { recursive: true });
  const sessions = await SessionManager.list(cwd, directory);
  const existing = sessions.find((item) => item.id === workspaceId);
  return existing
    ? SessionManager.open(existing.path, directory, cwd)
    : SessionManager.create(cwd, directory, { id: workspaceId });
}

function resourceLoader(systemPrompt, cwd) {
  return new DefaultResourceLoader({
    cwd,
    agentDir,
    settingsManager: SettingsManager.inMemory(),
    noExtensions: true,
    noSkills: true,
    noPromptTemplates: true,
    noThemes: true,
    noContextFiles: true,
    systemPromptOverride: () => systemPrompt,
    appendSystemPromptOverride: () => [],
  });
}

function piEvents(session, emit) {
  const events = [];
  const unsubscribe = session.subscribe((event) => {
    let normalized;
    if (event.type === "message_update") {
      const update = event.assistantMessageEvent;
      if (update.type === "text_delta") {
        normalized = { type: "message.text_delta", delta: update.delta };
      } else if (update.type === "thinking_start") {
        normalized = { type: "message.thinking" };
      } else if (update.type === "thinking_end") {
        normalized = { type: "message.thinking_end" };
      } else if (update.type === "toolcall_end") {
        normalized = { type: "message.toolcall", tool: update.toolCall?.name || "" };
      }
    } else if (event.type === "tool_execution_start") {
      normalized = { type: "tool.started", tool: event.toolName };
    } else if (event.type === "tool_execution_end") {
      normalized = { type: "tool.completed", tool: event.toolName, isError: Boolean(event.isError) };
    }
    if (normalized) {
      events.push(normalized);
      emit?.(normalized);
    }
  });
  return { events, unsubscribe };
}

function planSystemPrompt(payload) {
  const managed = payload.profile?.managed !== false && String(payload.profile?.kind || "") !== "custom";
  const replanContext = payload.replan
    ? `\n\n这是失败后的重新规划。已完成步骤是不可重复的事实；针对失败原因给出替代路径。\n${JSON.stringify(payload.replan, null, 2)}`
    : "";
  return `你是 ClipTalk 智能剪辑 Planner。你的职责是解释目标、命名剪辑结构并调用 submit_plan；平台会依据事实快照与 Skill 能力档案编译最终可执行步骤。\n\n硬性规则：\n- 当前是规划阶段，禁止执行媒体分析、渲染、导出、删除或身份绑定。\n- 只能引用组合 Skill 能力档案允许的真实工具；不得绕过 allowed-tools。\n- 当前执行器一次只运行一个步骤，计划不得声称并行。\n- 使用 brief 的 targetSeconds 与 durationToleranceSeconds，不得自行套用固定时长默认。\n- 身份选择仅在 brief 明确限定人物/声音或 planningContext 表明置信度不足时出现一次。\n- 时间线必须先作为未应用草案提出，再经 confirm_timeline_edit 由用户确认已应用。字幕审核和审阅样片必须在时间线确认之后；正式导出不属于本计划。\n- 对主题访谈，把主题、回答、必要提问、转场、重复与可删内容合并为一次语义检索。\n- 对短视频 Hook 目标：无指定主题时优先高光证据；指定主题、观点或引用时优先语义检索。目标未给出时默认 30 秒；开头 1–3 秒必须进入明确 Hook。\n- summary 中解释结构、删重策略和必要人工边界；不得输出计划 JSON 文本，必须且只调用一次 submit_plan。\n${managed ? "- 这是平台托管 Skill：不要编写 DAG 或步骤，只提交检索扩展、时间线策略和多版本差异；平台负责确定步骤与确认点。" : "- 这是自定义 Skill：提交 1–24 个仅使用授权工具的串行 DAG 步骤。"}\n\n当前 Skill：\n${payload.skill.markdown}\n\n组合 Skill：\n${JSON.stringify(payload.skills || [], null, 2)}\n\n能力档案：\n${JSON.stringify(payload.profile || {}, null, 2)}\n\n剪辑 Brief：\n${JSON.stringify(payload.brief || {}, null, 2)}\n\n素材事实快照：\n${JSON.stringify(payload.planningContext || {}, null, 2)}\n\n可用工具：\n${JSON.stringify(payload.toolCatalog, null, 2)}\n\n工作区：${JSON.stringify(payload.workspace)}${replanContext}\n`;
}

const planStepSchema = Type.Object({
  id: Type.String({ minLength: 1, maxLength: 64 }),
  title: Type.String({ minLength: 1, maxLength: 160 }),
  tool: Type.String({ minLength: 1, maxLength: 100 }),
  arguments: Type.Record(Type.String(), Type.Unknown()),
  dependencies: Type.Array(Type.String({ maxLength: 64 }), { maxItems: 24 }),
  expectedOutput: Type.String({ maxLength: 500 }),
  sideEffect: Type.Union([
    Type.Literal("read"), Type.Literal("analysis"), Type.Literal("preview"),
    Type.Literal("identity"), Type.Literal("review"), Type.Literal("export"), Type.Literal("delete"),
  ]),
  estimatedSeconds: Type.Integer({ minimum: 0, maximum: 86400 }),
  optional: Type.Boolean(),
});

async function planWithPi(payload, emit) {
  if (!payload.skill?.markdown || !Array.isArray(payload.toolCatalog)) throw new Error("规划上下文不完整");
  const config = normalizedModelConfig(payload.model);
  emit?.({
    type: "planning.progress", phase: "skill_selected",
    title: "已选择剪辑 Skill",
    detail: `使用 ${String(payload.skill.id || "智能剪辑 Skill")}`,
  });
  emit?.({
    type: "planning.progress", phase: "context_loading",
    title: "正在核对素材范围与可用工具",
    detail: "此阶段只准备计划上下文，不会分析视频或开始渲染。",
  });
  const { modelRuntime, model } = await createRuntime(config);
  let submittedPlan;
  const managed = payload.profile?.managed !== false && String(payload.profile?.kind || "") !== "custom";
  const submitPlan = {
    name: "submit_plan",
    label: "提交剪辑计划",
    description: "提交完整的、尚未执行的剪辑任务 DAG，等待用户确认。",
    parameters: managed ? Type.Object({
      summary: Type.String({ minLength: 1, maxLength: 1000 }),
      strategy: Type.Object({
        searchQuery: Type.Optional(Type.String({ maxLength: 500 })),
        timelineInstruction: Type.Optional(Type.String({ maxLength: 500 })),
        orderingPolicy: Type.Optional(Type.String({ maxLength: 120 })),
        preserveContext: Type.Optional(Type.Boolean()),
        removeRepetition: Type.Optional(Type.Boolean()),
        variantDirections: Type.Optional(Type.Array(Type.String({ maxLength: 240 }), { maxItems: 4 })),
      }),
    }) : Type.Object({
      summary: Type.String({ minLength: 1, maxLength: 1000 }),
      steps: Type.Array(planStepSchema, { minItems: 1, maxItems: 24 }),
    }),
    executionMode: "sequential",
    execute: async (_toolCallId, params) => {
      const stepCount = managed ? Number(payload.brief?.variantCount || 1) : Array.isArray(params.steps) ? params.steps.length : 0;
      emit?.({
        type: "planning.progress", phase: "validating_plan",
        title: "正在校验计划步骤与人工确认点",
        detail: stepCount ? `已拆解为 ${stepCount} 个待确认步骤。` : "正在校验待确认步骤。",
      });
      submittedPlan = {
        ...params,
        steps: managed ? [] : params.steps,
        skillChain: (payload.skills || [payload.skill]).map((item, index) => ({
          id: item.id, version: item.version, contentHash: item.contentHash,
          role: item.role || (index === 0 ? "primary" : "addon"),
          workflowProfile: item.workflowProfile || "",
        })),
      };
      return {
        content: [{ type: "text", text: "计划已提交，正在等待用户确认。" }],
        details: { accepted: true },
        terminate: true,
      };
    },
  };
  const cwd = resolve(defaultDataRoot);
  const loader = resourceLoader(planSystemPrompt(payload), cwd);
  await loader.reload();
  const manager = await sessionManagerFor(String(payload.workspaceId), payload.sessionDir, cwd);
  const { session } = await createAgentSession({
    cwd,
    agentDir,
    modelRuntime,
    model,
    thinkingLevel: config.reasoning ? "medium" : "off",
    sessionManager: manager,
    settingsManager: SettingsManager.inMemory(),
    resourceLoader: loader,
    noTools: "builtin",
    customTools: [submitPlan],
  });
  emit?.({
    type: "planning.progress", phase: "decomposing_goal",
    title: "正在构建可确认的剪辑方案",
    detail: "正在把目标、素材范围和交付要求整理成可审核步骤。",
  });
  const stream = piEvents(session, emit);
  const planningStartedAt = Date.now();
  const progressHeartbeat = setInterval(() => {
    const elapsedSeconds = Math.max(1, Math.floor((Date.now() - planningStartedAt) / 1000));
    emit?.({
      type: "planning.progress", phase: "decomposing_goal",
      title: "正在等待规划结果",
      detail: `已等待 ${elapsedSeconds} 秒，计划返回后即可确认。`,
    });
  }, 6000);
  try {
    await session.prompt(`为以下目标生成完整执行计划：\n${String(payload.goal || "").slice(0, 4000)}`);
  } finally {
    clearInterval(progressHeartbeat);
    stream.unsubscribe();
    session.dispose();
  }
  if (!submittedPlan) throw new Error("Agent 未调用 submit_plan；请确认模型支持 Tool Calling");
  return {
    plan: {
      ...submittedPlan,
      agent: { provider: "cliptalk-agent", model: config.model, runtime: "pi", version: "0.84.4" },
    },
    events: stream.events,
  };
}

function skillSystemPrompt(payload) {
  return `你是 ClipTalk Skill Creator。根据用户描述创建一个精确、可复用的智能剪辑 Skill，然后调用 submit_skill。\n\n要求：\n- 遵循 Agent Skills 标准，生成带 name、description、allowed-tools 和 workflow-profile frontmatter 的 SKILL.md。\n- workflow-profile 只能是 highlight、content、interview、person、speaker、revision、shortform、delivery-qc、social-reframe 之一；它让平台接管步骤顺序、确认点和安全约束。\n- 选择 workflow-profile 后，allowed-tools 必须完整包含该档案所需工具；涉及时间线的 Skill 必须包含 confirm_timeline_edit。\n- name 使用小写字母、数字、连字符，最多 64 字符。\n- description 必须清楚说明何时适用，避免吸引无关任务。\n- 正文只包含会改变 Agent 决策的任务拆解、质量标准和真实约束。\n- Skill 不得要求 Bash、任意文件读写、直接导出、删除或绕过用户确认。\n- 只能使用下列工具，不得声称不存在的能力：\n${JSON.stringify(payload.toolCatalog, null, 2)}\n- 必须调用 submit_skill，不要只输出 Markdown。`;
}

async function generateSkillWithPi(payload) {
  const config = normalizedModelConfig(payload.model);
  const { modelRuntime, model } = await createRuntime(config);
  let submittedSkill;
  const submitSkill = {
    name: "submit_skill",
    label: "提交 Skill 草稿",
    description: "提交尚未启用的标准 SKILL.md 与模拟规划结论。",
    parameters: Type.Object({
      skillMarkdown: Type.String({ minLength: 40, maxLength: 16000 }),
      simulationSummary: Type.String({ minLength: 1, maxLength: 1000 }),
      requiredTools: Type.Array(Type.String({ maxLength: 100 }), { maxItems: 24 }),
    }),
    execute: async (_toolCallId, params) => {
      submittedSkill = params;
      return {
        content: [{ type: "text", text: "Skill 草稿已提交审核。" }],
        details: { accepted: true },
        terminate: true,
      };
    },
  };
  const cwd = resolve(defaultDataRoot);
  const loader = resourceLoader(skillSystemPrompt(payload), cwd);
  await loader.reload();
  const { session } = await createAgentSession({
    cwd,
    agentDir,
    modelRuntime,
    model,
    thinkingLevel: config.reasoning ? "medium" : "off",
    sessionManager: SessionManager.inMemory(),
    settingsManager: SettingsManager.inMemory(),
    resourceLoader: loader,
    noTools: "builtin",
    customTools: [submitSkill],
  });
  try {
    await session.prompt(String(payload.request || "").slice(0, 4000));
  } finally {
    session.dispose();
  }
  if (!submittedSkill) throw new Error("Agent 未调用 submit_skill；请确认模型支持 Tool Calling");
  const available = new Set(payload.toolCatalog.map((item) => item.name));
  const missing = submittedSkill.requiredTools.filter((name) => !available.has(name));
  return {
    skillMarkdown: submittedSkill.skillMarkdown,
    simulation: {
      valid: missing.length === 0,
      summary: submittedSkill.simulationSummary,
      requiredTools: submittedSkill.requiredTools,
      missingTools: missing,
    },
  };
}

async function routeSkillWithPi(payload) {
  if (!Array.isArray(payload.skills) || !payload.skills.length) throw new Error("没有可路由的 Skill");
  const config = normalizedModelConfig(payload.model);
  const { modelRuntime, model } = await createRuntime(config);
  let selection;
  const selectSkill = {
    name: "select_skill",
    label: "选择剪辑 Skill",
    description: "选择最适合当前目标的一个已安装 Skill。",
    parameters: Type.Object({
      skillId: Type.String({ minLength: 1, maxLength: 64 }),
      reason: Type.String({ minLength: 1, maxLength: 500 }),
    }),
    execute: async (_toolCallId, params) => {
      selection = params;
      return {
        content: [{ type: "text", text: "Skill 已选择。" }],
        details: { accepted: true },
        terminate: true,
      };
    },
  };
  const cwd = resolve(defaultDataRoot);
  const loader = resourceLoader(
    `你是 ClipTalk Skill Router。根据用户目标与 description 选择唯一最合适的 Skill，并调用 select_skill。不得选择目录之外的 ID。\n\n路由约束（必须遵守）：\n${JSON.stringify(payload.routingHints || {}, null, 2)}\n\nSkill 目录：\n${JSON.stringify(payload.skills, null, 2)}`,
    cwd,
  );
  await loader.reload();
  const { session } = await createAgentSession({
    cwd,
    agentDir,
    modelRuntime,
    model,
    thinkingLevel: "off",
    sessionManager: SessionManager.inMemory(),
    settingsManager: SettingsManager.inMemory(),
    resourceLoader: loader,
    noTools: "builtin",
    customTools: [selectSkill],
  });
  try {
    await session.prompt(String(payload.goal || "").slice(0, 4000));
  } finally {
    session.dispose();
  }
  const allowed = new Set(payload.skills.map((item) => item.id));
  if (!selection || !allowed.has(selection.skillId)) throw new Error("Agent 未选择有效的 Skill");
  return selection;
}

async function probeWithPi(payload) {
  const config = normalizedModelConfig(payload.model);
  const { modelRuntime, model } = await createRuntime(config);
  const challenge = `probe-${Date.now()}`;
  let observed = "";
  const probeTool = {
    name: "agent_capability_probe",
    label: "Agent 能力探测",
    description: "回传指定 challenge，用于验证模型确实支持 Tool Calling。",
    parameters: Type.Object({ challenge: Type.String({ minLength: 1, maxLength: 100 }) }),
    execute: async (_toolCallId, params) => {
      observed = params.challenge;
      return {
        content: [{ type: "text", text: "probe accepted" }],
        details: { accepted: true },
        terminate: true,
      };
    },
  };
  const cwd = resolve(defaultDataRoot);
  const loader = resourceLoader(
    `你正在执行模型能力探测。必须调用 agent_capability_probe，并将 challenge 设置为 ${challenge}。不要输出其他内容。`,
    cwd,
  );
  await loader.reload();
  const { session } = await createAgentSession({
    cwd,
    agentDir,
    modelRuntime,
    model,
    thinkingLevel: "off",
    sessionManager: SessionManager.inMemory(),
    settingsManager: SettingsManager.inMemory(),
    resourceLoader: loader,
    noTools: "builtin",
    customTools: [probeTool],
  });
  try {
    await session.prompt(`调用工具并回传 challenge：${challenge}`);
  } finally {
    session.dispose();
  }
  if (observed !== challenge) throw new Error("模型没有完成结构化 Tool Calling 探测");
  return { ok: true, toolCalling: true, streaming: true, model: config.model, piVersion: "0.84.4" };
}

function runNpmInstall(pluginPath) {
  if (!existsSync(resolve(pluginPath, "package.json"))) return Promise.resolve();
  return new Promise((resolvePromise, reject) => {
    const operation = existsSync(resolve(pluginPath, "package-lock.json")) ? "ci" : "install";
    const child = spawn("npm", [operation, ...(operation === "install" ? ["--package-lock=false"] : []), "--ignore-scripts", "--omit=dev", "--no-audit", "--no-fund"], {
      cwd: pluginPath,
      stdio: ["ignore", "pipe", "pipe"],
      shell: false,
      timeout: 120000,
    });
    let errorOutput = "";
    child.stderr.on("data", (chunk) => { errorOutput += chunk.toString("utf8").slice(0, 4000); });
    child.on("error", reject);
    child.on("close", (code) => {
      if (code === 0) resolvePromise();
      else reject(new Error(`Plugin 依赖安装失败：${errorOutput || `npm exited ${code}`}`));
    });
  });
}

async function activatePlugin(payload) {
  const allowedRoot = resolve(defaultDataRoot, "plugins");
  const { pluginPath, entrypoint } = validatePlugin(payload, allowedRoot);
  const active = activePlugins.get(String(payload.pluginId));
  if (active?.contentHash === payload.contentHash && active?.treeHash === payload.treeHash && active?.version === String(payload.version || "")) {
    return { status: "enabled", toolNames: [...active.tools.keys()] };
  }
  await runNpmInstall(pluginPath);
  validatePlugin(payload, allowedRoot);
  const imported = await import(`${pathToFileURL(entrypoint).href}?v=${encodeURIComponent(payload.contentHash)}`);
  const exported = imported.default || imported.plugin || imported;
  const instance = typeof exported === "function" ? await exported() : exported;
  if (!instance || !Array.isArray(instance.tools)) throw new Error("Plugin 必须导出 { tools: [...] }");
  const declared = new Set((payload.tools || []).map((item) => item.name));
  const tools = new Map();
  for (const tool of instance.tools) {
    if (!tool || typeof tool.name !== "string" || typeof tool.execute !== "function") continue;
    if (!declared.has(tool.name)) throw new Error(`Plugin 运行时注册了未声明工具：${tool.name}`);
    tools.set(tool.name, tool);
  }
  if (!tools.size) throw new Error("Plugin 没有注册可执行工具");
  activePlugins.set(String(payload.pluginId), {
    version: String(payload.version || ""),
    contentHash: String(payload.contentHash || ""),
    treeHash: String(payload.treeHash || ""),
    validation: { path: pluginPath, entrypoint: payload.entrypoint, treeHash: payload.treeHash },
    tools,
  });
  return { status: "enabled", toolNames: [...tools.keys()] };
}

async function executePluginTool(payload) {
  const plugin = activePlugins.get(String(payload.pluginId));
  if (!plugin) throw new Error("Plugin 尚未在当前 Agent 服务中激活");
  if (payload.pluginVersion && String(payload.pluginVersion) !== plugin.version) throw new Error("Plugin 版本与已批准计划不一致");
  if (!payload.contentHash || !payload.treeHash || payload.contentHash !== plugin.contentHash || payload.treeHash !== plugin.treeHash) throw new Error("Plugin 内容与批准记录不一致，请重新审批");
  validatePlugin(plugin.validation, resolve(defaultDataRoot, "plugins"));
  const tool = plugin.tools.get(String(payload.tool));
  if (!tool) throw new Error("Plugin 工具不存在");
  const operation = await operationStore.execute(payload.operationId, payload, () => tool.execute(payload.arguments || {}, Object.freeze({ ...(payload.context || {}) })));
  return { ...operation, result: operation.result };
}

const server = createServer(async (request, response) => {
  try {
    const url = new URL(request.url || "/", `http://${request.headers.host || "localhost"}`);
    if (request.method === "GET" && url.pathname === "/health") {
      jsonResponse(response, 200, {
        status: "ok",
        service: "cliptalk-agent-service",
        piVersion: "0.84.4",
      });
      return;
    }
    if (request.method !== "POST") {
      jsonResponse(response, 404, { error: "not_found" });
      return;
    }
    if (!authorized(request, agentServiceToken)) {
      jsonResponse(response, 401, { error: "unauthorized" });
      return;
    }
    if (url.pathname === "/v1/operations/get") {
      const payload = await readJson(request);
      const operation = operationStore.get(String(payload.operationId || ""));
      jsonResponse(response, operation ? 200 : 404, operation || { error: "not_found" });
      return;
    }
    const payload = await readJson(request);
    if (url.pathname === "/v1/plan/stream") {
      response.writeHead(200, {
        "Content-Type": "text/event-stream; charset=utf-8",
        "Cache-Control": "no-cache, no-transform",
        "Connection": "keep-alive",
        "X-Accel-Buffering": "no",
      });
      const send = (eventType, value) => {
        response.write(`event: ${eventType}\ndata: ${JSON.stringify(value)}\n\n`);
      };
      try {
        const result = await planWithPi(payload, (event) => send(event.type, event));
        send("plan", result);
      } catch (error) {
        send("error", { message: error instanceof Error ? error.message : String(error) });
      }
      response.end();
      return;
    }
    if (url.pathname === "/v1/plan") {
      jsonResponse(response, 200, await planWithPi(payload));
      return;
    }
    if (url.pathname === "/v1/skills/generate") {
      jsonResponse(response, 200, await generateSkillWithPi(payload));
      return;
    }
    if (url.pathname === "/v1/skills/route") {
      jsonResponse(response, 200, await routeSkillWithPi(payload));
      return;
    }
    if (url.pathname === "/v1/probe") {
      jsonResponse(response, 200, await probeWithPi(payload));
      return;
    }
    if (url.pathname === "/v1/plugins/activate") {
      jsonResponse(response, 200, await activatePlugin(payload));
      return;
    }
    if (url.pathname === "/v1/plugins/deactivate") {
      activePlugins.delete(String(payload.pluginId || ""));
      jsonResponse(response, 200, { status: "disabled" });
      return;
    }
    if (url.pathname === "/v1/tools/execute") {
      jsonResponse(response, 200, await executePluginTool(payload));
      return;
    }
    jsonResponse(response, 404, { error: "not_found" });
  } catch (error) {
    const message = error instanceof Error ? error.message : String(error);
    jsonResponse(response, message === "request_too_large" ? 413 : message === "operation_content_conflict" ? 409 : 400, { error: "agent_error", message });
  }
});

server.listen(port, host, () => {
  process.stdout.write(`ClipTalk agent service listening on http://${host}:${server.address().port}\n`);
});

function shutdown() {
  server.close(() => { operationStore.close(); process.exit(0); });
  setTimeout(() => process.exit(1), 5000).unref();
}

process.on("SIGINT", shutdown);
process.on("SIGTERM", shutdown);
