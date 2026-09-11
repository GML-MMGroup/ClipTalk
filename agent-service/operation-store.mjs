import { DatabaseSync } from "node:sqlite";
import { createHash, randomUUID } from "node:crypto";

function canonical(value) {
  if (Array.isArray(value)) return value.map(canonical);
  if (value && typeof value === "object") return Object.fromEntries(Object.keys(value).sort().map(key => [key, canonical(value[key])]));
  return value;
}

export class OperationStore {
  constructor(path) {
    this.db = new DatabaseSync(path);
    this.db.exec("PRAGMA journal_mode=WAL; PRAGMA busy_timeout=15000; CREATE TABLE IF NOT EXISTS operations (id TEXT PRIMARY KEY, fingerprint TEXT NOT NULL, status TEXT NOT NULL, result TEXT, error TEXT)");
    this.owner = randomUUID();
    this.db.exec("CREATE TABLE IF NOT EXISTS service_owner (id INTEGER PRIMARY KEY CHECK(id=1), owner TEXT NOT NULL, lease_until INTEGER NOT NULL)");
    this.db.exec("BEGIN IMMEDIATE");
    try {
      const active = this.db.prepare("SELECT lease_until FROM service_owner WHERE id=1").get();
      if (active?.lease_until > Date.now()) throw new Error("Agent operation journal is owned by another live service");
      this.db.prepare("INSERT INTO service_owner VALUES(1,?,?) ON CONFLICT(id) DO UPDATE SET owner=excluded.owner,lease_until=excluded.lease_until").run(this.owner, Date.now() + 30000);
    // A crash cannot prove whether host-side effects occurred. Never replay it.
    this.db.exec("UPDATE operations SET status='uncertain', error='服务重启，执行结果待核实' WHERE status='running'");
      this.db.exec("COMMIT");
    } catch (error) { this.db.exec("ROLLBACK"); this.db.close(); throw error; }
    this.timer = setInterval(() => this.db.prepare("UPDATE service_owner SET lease_until=? WHERE id=1 AND owner=?").run(Date.now() + 30000, this.owner), 5000);
    this.timer.unref();
  }

  get(id) {
    const row = this.db.prepare("SELECT * FROM operations WHERE id=?").get(id);
    if (!row) return null;
    return { operationId: id, status: row.status, result: row.result ? JSON.parse(row.result) : null, error: row.error, retryable: false };
  }

  async execute(id, request, target) {
    const lease = this.db.prepare("SELECT owner,lease_until FROM service_owner WHERE id=1").get();
    if (lease?.owner !== this.owner || lease.lease_until < Date.now()) throw new Error("Agent operation journal lease lost");
    if (!id || typeof id !== "string" || id.length > 200) throw new Error("operation_id_required");
    const fingerprint = createHash("sha256").update(JSON.stringify(canonical(request))).digest("hex");
    const existing = this.db.prepare("SELECT fingerprint FROM operations WHERE id=?").get(id);
    if (existing) {
      if (existing.fingerprint !== fingerprint) throw new Error("operation_content_conflict");
      return this.get(id);
    }
    this.db.prepare("INSERT INTO operations(id,fingerprint,status) VALUES(?,?,'running')").run(id, fingerprint);
    try {
      const result = await target();
      this.db.prepare("UPDATE operations SET status='succeeded',result=? WHERE id=?").run(JSON.stringify(result ?? null), id);
    } catch (error) {
      this.db.prepare("UPDATE operations SET status='uncertain',error=? WHERE id=?").run(String(error.message || error).slice(0, 2000), id);
    }
    return this.get(id);
  }

  close() {
    clearInterval(this.timer);
    this.db.prepare("DELETE FROM service_owner WHERE id=1 AND owner=?").run(this.owner);
    this.db.close();
  }
}
