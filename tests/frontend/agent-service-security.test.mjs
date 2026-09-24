import assert from "node:assert/strict";
import { mkdtempSync, mkdirSync, writeFileSync, symlinkSync, rmSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { createServer } from "node:http";
import { once } from "node:events";
import { spawn } from "node:child_process";
import { fileURLToPath } from "node:url";
import test from "node:test";
import { authorized, serviceToken, validatePlugin, pluginTreeHash } from "../../agent-service/security.mjs";

test("actual Agent routes enforce authentication before parsing or executing requests", { timeout: 20000 }, async () => {
  const directory = mkdtempSync(join(tmpdir(), "cliptalk-agent-http-"));
  const token = "b".repeat(64);
  const child = spawn(process.execPath, [fileURLToPath(new URL("../../agent-service/server.mjs", import.meta.url))], {
    env: { ...process.env, CLIPTALK_AGENT_HOST: "127.0.0.1", CLIPTALK_AGENT_PORT: "0", HIGHLIGHT_DATA_ROOT: directory, CLIPTALK_AGENT_SERVICE_TOKEN: token },
    stdio: ["ignore", "pipe", "pipe"],
  });
  try {
    const url = await new Promise((resolve, reject) => {
      let output = "";
      const timer = setTimeout(() => reject(new Error("Agent test startup timed out")), 12000);
      child.once("exit", code => { clearTimeout(timer); reject(new Error(`Agent exited: ${code}`)); });
      child.stdout.on("data", data => {
        output += data.toString();
        const match = output.match(/listening on (http:\/\/[^\s]+)/);
        if (match) { clearTimeout(timer); resolve(match[1]); }
      });
    });
    assert.equal((await fetch(`${url}/health`)).status, 200);
    for (const route of ["/v1/plan/stream", "/v1/plugins/activate", "/v1/tools/execute"]) {
      assert.equal((await fetch(`${url}${route}`, { method: "POST", body: "invalid-json" })).status, 401);
    }
    const response = await fetch(`${url}/v1/plugins/deactivate`, {
      method: "POST", headers: { Authorization: `Bearer ${token}`, "Content-Type": "application/json" }, body: JSON.stringify({ pluginId: "isolated-test" }),
    });
    assert.equal(response.status, 200);
    assert.equal((await response.json()).status, "disabled");
    const pluginPath = join(directory, "agent", "plugins", "isolated", "approved");
    mkdirSync(pluginPath, { recursive: true });
    writeFileSync(join(pluginPath, "index.mjs"), 'let calls = 0; export default { tools: [{ name: "once", execute: async () => ({ calls: ++calls }) }] };');
    const treeHash = pluginTreeHash(pluginPath);
    const post = (path, payload) => fetch(`${url}${path}`, { method: "POST",
      headers: { Authorization: `Bearer ${token}`, "Content-Type": "application/json" }, body: JSON.stringify(payload) });
    assert.equal((await post("/v1/plugins/activate", { pluginId: "isolated", version: "1.0.0", contentHash: "approved-content",
      path: pluginPath, entrypoint: "index.mjs", treeHash, tools: [{ name: "once" }] })).status, 200);
    const execution = { pluginId: "isolated", pluginVersion: "1.0.0", contentHash: "approved-content", treeHash,
      tool: "once", operationId: "stable-operation", arguments: {} };
    for (let attempt = 0; attempt < 2; attempt++) {
      const result = await (await post("/v1/tools/execute", execution)).json();
      assert.equal(result.status, "succeeded");
      assert.equal(result.result.calls, 1);
    }
    assert.equal((await post("/v1/tools/execute", { ...execution, arguments: { different: true } })).status, 409);
    const recorded = await (await post("/v1/operations/get", { operationId: "stable-operation" })).json();
    assert.equal(recorded.result.calls, 1);
    writeFileSync(join(pluginPath, "index.mjs"), "export default { changed: true }");
    assert.equal((await post("/v1/tools/execute", { ...execution, operationId: "tampered" })).status, 400);
  } finally {
    const stopped = once(child, "exit");
    child.kill("SIGTERM");
    if (child.exitCode === null) await stopped;
    rmSync(directory, { recursive: true, force: true });
  }
});

test("Agent HTTP boundary rejects absent/wrong credentials and accepts its independent token", async () => {
  const token = "a".repeat(64);
  const server = createServer((request, response) => {
    response.writeHead(authorized(request, token) ? 200 : 401); response.end();
  });
  server.listen(0, "127.0.0.1"); await once(server, "listening");
  try {
    const url = `http://127.0.0.1:${server.address().port}/v1/tools/execute`;
    for (const [authorization, status] of [["", 401], ["Bearer wrong", 401], [`Bearer ${token}`, 200]]) {
      const response = await fetch(url, { method: "POST", headers: { authorization } });
      assert.equal(response.status, status);
    }
  } finally { server.closeAllConnections(); await new Promise(resolve => server.close(resolve)); }
});

test("Agent source validation rejects changed files and symlink escapes", () => {
  const temporary = mkdtempSync(join(tmpdir(), "cliptalk-security-"));
  try {
    const root = join(temporary, "plugins"); const plugin = join(root, "p", "hash");
    mkdirSync(plugin, { recursive: true });
    writeFileSync(join(plugin, "index.mjs"), "export default {}");
    const payload = { path: plugin, entrypoint: "index.mjs", treeHash: pluginTreeHash(plugin) };
    assert.equal(validatePlugin(payload, root).pluginPath, plugin);
    writeFileSync(join(plugin, "index.mjs"), "export default {changed:true}");
    assert.throws(() => validatePlugin(payload, root), /source changed/);
    const outside = join(temporary, "outside"); mkdirSync(outside);
    writeFileSync(join(outside, "index.mjs"), "export default {}");
    symlinkSync(outside, join(root, "escape"));
    assert.throws(() => validatePlugin({ ...payload, path: join(root, "escape") }, root), /outside managed/);
    const file = join(temporary, "service-token");
    assert.equal(serviceToken(file, ""), serviceToken(file, ""));
    assert.throws(() => serviceToken(file, "short"), /at least 32/);
  } finally { rmSync(temporary, { recursive: true, force: true }); }
});
