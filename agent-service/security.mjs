import { createHash, randomBytes, timingSafeEqual } from "node:crypto";
import { existsSync, mkdirSync, readFileSync, writeFileSync, linkSync, unlinkSync, readdirSync, realpathSync, lstatSync } from "node:fs";
import { dirname, join, resolve, relative, sep } from "node:path";

export function serviceToken(file, configured = process.env.CLIPTALK_AGENT_SERVICE_TOKEN || "") {
  if (configured.trim()) {
    if (configured.trim().length < 32) throw new Error("CLIPTALK_AGENT_SERVICE_TOKEN must contain at least 32 characters");
    return configured.trim();
  }
  mkdirSync(dirname(file), { recursive: true });
  if (!existsSync(file)) {
    const temporary = `${file}.${randomBytes(12).toString("hex")}.tmp`;
    writeFileSync(temporary, randomBytes(32).toString("hex"), { flag: "wx", mode: 0o600 });
    try { linkSync(temporary, file); }
    catch (error) { if (error.code !== "EEXIST") throw error; }
    finally { unlinkSync(temporary); }
  }
  const token = readFileSync(file, "utf8").trim();
  if (token.length < 32) throw new Error("Invalid Agent service credential");
  return token;
}

export function authorized(request, token) {
  const actual = Buffer.from(String(request.headers.authorization || ""));
  const expected = Buffer.from(`Bearer ${token}`);
  return actual.length === expected.length && timingSafeEqual(actual, expected);
}

export function pluginTreeHash(root) {
  const files = [];
  function visit(directory) {
    for (const entry of readdirSync(directory, { withFileTypes: true })) {
      if (entry.name === "node_modules") continue;
      const file = join(directory, entry.name);
      if (entry.isSymbolicLink()) throw new Error("Plugin source cannot contain symlinks");
      if (entry.isDirectory()) visit(file);
      else if (entry.isFile()) files.push([relative(root, file).split(sep).join("/"), file]);
    }
  }
  visit(root);
  const digest = createHash("sha256");
  for (const [name, file] of files.sort((a, b) => Buffer.compare(Buffer.from(a[0]), Buffer.from(b[0])))) {
    digest.update(`${name}\0${createHash("sha256").update(readFileSync(file)).digest("hex")}\0`);
  }
  return digest.digest("hex");
}

export function validatePlugin(payload, allowedRoot) {
  const root = realpathSync(allowedRoot);
  const pluginPath = realpathSync(resolve(String(payload.path || "")));
  if (!pluginPath.startsWith(`${root}${sep}`)) throw new Error("Plugin path outside managed directory");
  const candidate = resolve(pluginPath, String(payload.entrypoint || "index.mjs"));
  const entrypoint = realpathSync(candidate);
  if (!entrypoint.startsWith(`${pluginPath}${sep}`) || lstatSync(candidate).isSymbolicLink()
      || relative(pluginPath, entrypoint).split(sep).includes("node_modules")) throw new Error("Invalid Plugin entrypoint");
  if (!payload.treeHash || pluginTreeHash(pluginPath) !== payload.treeHash) throw new Error("Plugin source changed; inspect and approve it again");
  return { pluginPath, entrypoint };
}
