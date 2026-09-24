import assert from "node:assert/strict";
import { test } from "node:test";

test("Node runtime supports immutable plugin contexts", () => {
  const context = Object.freeze({ workspaceId: "ws_test", jobId: "job_test" });
  assert.equal(context.workspaceId, "ws_test");
  assert.equal(Object.isFrozen(context), true);
});
