import assert from "node:assert/strict";
import { mkdtempSync, rmSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import test from "node:test";
import { OperationStore } from "../../agent-service/operation-store.mjs";

test("operation journal serializes concurrent calls and preserves results across restart", async () => {
  const root = mkdtempSync(join(tmpdir(), "cliptalk-operations-"));
  let store = new OperationStore(join(root, "operations.db"));
  try {
    let calls = 0, release;
    const request = { arguments: { b: 2, a: 1 }, tool: "export" };
    const first = store.execute("one", request, async () => { calls++; await new Promise(resolve => { release = resolve; }); return { saved: true }; });
    const duplicate = await store.execute("one", { tool: "export", arguments: { a: 1, b: 2 } }, () => { calls++; });
    assert.equal(duplicate.status, "running");
    assert.throws(() => new OperationStore(join(root, "operations.db")), /another live service/);
    release();
    assert.equal((await first).status, "succeeded");
    await assert.rejects(store.execute("one", { tool: "delete" }, () => {}), /conflict/);
    store.close(); store = new OperationStore(join(root, "operations.db"));
    assert.deepEqual((await store.execute("one", request, () => { calls++; })).result, { saved: true });
    assert.equal(calls, 1);
  } finally { store.close(); rmSync(root, { recursive: true, force: true }); }
});

test("crashed or throwing operations remain uncertain and are not re-executed", async () => {
  const root = mkdtempSync(join(tmpdir(), "cliptalk-uncertain-"));
  let store = new OperationStore(join(root, "operations.db"));
  try {
    let effects = 0;
    const result = await store.execute("lost", {}, () => { effects++; throw new Error("response lost after effect"); });
    assert.equal(result.status, "uncertain");
    assert.equal(result.retryable, false);
    await store.execute("lost", {}, () => { effects++; });
    store.db.prepare("INSERT INTO operations(id,fingerprint,status) VALUES('crashed','fingerprint','running')").run();
    store.close(); store = new OperationStore(join(root, "operations.db"));
    assert.equal(store.get("crashed").status, "uncertain");
    assert.equal(effects, 1);
  } finally { store.close(); rmSync(root, { recursive: true, force: true }); }
});
