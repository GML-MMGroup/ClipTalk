# ClipTalk Agent Platform

ClipTalk now uses Pi as the reasoning runtime while retaining the Python media kernel. The browser talks only to FastAPI. FastAPI persists workspaces, plans, approvals, runs, and events, then calls the internal Node service for Skill routing and planning.

For immutable export specifications, operation-journal semantics, plugin approval fingerprints, and upgrade behavior, see [transactional delivery](transactional-delivery.md).

## Local startup

Start the Agent service before FastAPI when not using Docker Compose:

```bash
cd agent-service
npm ci --ignore-scripts
npm start
```

Configure a separate Agent model with `AGENT_*` environment variables or in Settings. Saving from the UI performs a real Pi Tool Calling probe. A model that only returns JSON text is rejected.

Docker Compose starts both services and keeps port `5190` internal. Pi is pinned to `0.84.4`; upgrades should be contained inside `agent-service` and verified against the planning and streaming contracts.

## Service credentials and worker ownership

All Agent POST endpoints (including SSE planning, plugin activation and tool execution) require `Authorization: Bearer <CLIPTALK_AGENT_SERVICE_TOKEN>`. This is an independent service credential, not the browser access token. `/health` remains public and exposes no plugin inventory.

- Docker or remote deployment: configure the same random token of at least 32 characters on FastAPI and Agent. Compose refuses to start without it. Do not publish the Agent port to the public internet.
- Local shared-data deployment: when no token is configured, both services atomically create/read `data/agent/service-token`, with mode `0600`. Both must use the same `HIGHLIGHT_DATA_ROOT`. Do not commit, display or send this file to browsers.
- Rotate by setting a new token on both services and restarting both. Do not substitute the user access token.
- Run one FastAPI worker per data directory. A process lock is acquired before loading/recovering jobs; a second instance fails with an explicit error. Queue ownership uses leases and heartbeats; recovery cannot steal a live lease. Startup releases abandoned leases only after acquiring the exclusive process lock. Shutdown keeps the lock until background writers stop.

Plugin approval also binds a fingerprint of the extracted source tree. The Agent resolves real paths and checks this fingerprint before and after dependency installation. Old plugin records without `treeHash` must be inspected and explicitly approved again; they are not silently trusted on restart. Plugins still execute with host-process privileges once approved; this is not an execution sandbox.

## Output delivery and persistence

Formal export requests identify `outputFilename` and the opaque `outputRevision` returned with that output. An old request omitting the filename is accepted only for a single-output version. Confirmation freezes the selected edit and its own subtitle settings; unrelated task progress does not invalidate it. Identical export requests return the same durable `operationId`, including after completion. Failed/cancelled operations may be retried; different files can render independently.

Output `capabilities` are authoritative for keep/download/edit actions. Existing formal files remain saveable while other analysis runs. The UI consumes `presentation.journeyStage`, `attentionItems` and `availableActions` rather than mapping raw execution states again.

SQLite is authoritative for jobs. Saves use a revision check and transaction; JSON is a rebuildable backup written after commit. Startup imports JSON only when the database has no record, never because a backup has a later timestamp. JSON-backup failures are logged without reporting an already-committed save as failed.

## Execution contract

1. A source job is attached to one durable Agent workspace.
2. Pi selects an enabled Skill unless the user explicitly selects one.
3. Pi may only call `submit_plan` during planning. No analysis or rendering tool is available yet.
4. FastAPI validates the returned DAG, tool names, dependencies, side-effect classes, Skill/Plugin versions, and workspace revision.
5. Approval binds the plan hash and allowed tool set. Only then does the executor dispatch steps.
6. Person/speaker identity, deletion, and formal export remain structured user actions. Agent execution stops at review preview.

Long-running Python tools return an operation identifier and a durable `Future`. Completion advances the plan exactly once. The public event stream is available at `/api/agent/workspaces/{workspaceId}/events`; live Pi planning events are available from the POST SSE endpoint `/api/agent/workspaces/{workspaceId}/messages/stream`.

## Skills

Skills use the Agent Skills `SKILL.md` format. A ZIP may contain `SKILL.md` at its root or in one top-level directory. Uploaded Skills enter `validated`; generated Skills enter `draft` or `validated` after a simulated capability check. They cannot be used until enabled with the exact content hash.

Skill scripts are never executed directly. If a workflow requires code that is not a core ClipTalk tool, install a Plugin and reference its declared tool.

## Trusted Plugin contract

Plugins run inside the Node Agent process. They are not sandboxed and must be treated as fully trusted code. Activation requires a content-hash-bound confirmation in the UI. Dependency installation uses `npm ci --ignore-scripts --omit=dev` when a lockfile exists, otherwise `npm install --ignore-scripts --omit=dev`.

A Plugin ZIP contains `cliptalk-plugin.json`:

```json
{
  "id": "example-caption-tool",
  "version": "1.0.0",
  "entrypoint": "index.mjs",
  "permissions": {
    "networkHosts": [],
    "mediaRead": true,
    "mediaWrite": false
  },
  "tools": [
    {
      "name": "example_caption_check",
      "description": "Checks caption timing without exporting media.",
      "sideEffect": "analysis",
      "parameters": {
        "type": "object",
        "properties": {},
        "additionalProperties": false
      }
    }
  ]
}
```

The entrypoint default export is an object, or an async factory returning an object, with executable tools:

```js
export default {
  tools: [{
    name: "example_caption_check",
    async execute(argumentsValue, context) {
      return { ok: true, workspaceId: context.workspaceId };
    },
  }],
};
```

Runtime tool names must be a subset of the manifest. Approved plans pin the Plugin version; version mismatch fails the step instead of silently running changed code.
