#!/usr/bin/env node
// Smoke test: does z.ai's Anthropic-shape endpoint preserve MCP tool
// round-trips through the stock `claude` CLI?
//
// The test spawns `claude --print` with:
//   ANTHROPIC_BASE_URL  = https://api.z.ai/api/anthropic
//   ANTHROPIC_AUTH_TOKEN = <GLM Coding Plan key>
//   --mcp-config pointing at a throwaway MCP server exposing one tool
// Then checks that the model actually called the tool. If it did, MCP
// through z.ai works and the GLM team can run the full Causal Fleet
// Memory tool chain. If not, we need an adapter layer.
//
// Env (required):
//   PF_ZAI_PLAN_TOKEN     GLM Coding Plan key (NOT a PAYG API key)
// Env (optional):
//   PF_CLAUDE_BIN         claude binary (default: "claude")
//   PF_ZAI_ANTHROPIC_BASE_URL  (default: https://api.z.ai/api/anthropic)
//   PF_GLM_MODEL          model id to pin (default: glm-5.3)

import { spawn, spawnSync } from "node:child_process";
import { mkdirSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import path from "node:path";

const CLAUDE = process.env.PF_CLAUDE_BIN || "claude";
const TOKEN = process.env.PF_ZAI_PLAN_TOKEN || "";
const BASE = process.env.PF_ZAI_ANTHROPIC_BASE_URL
  || "https://api.z.ai/api/anthropic";
const MODEL = process.env.PF_GLM_MODEL || "glm-5.3";

if (!TOKEN) {
  console.error("PF_ZAI_PLAN_TOKEN must be set (GLM Coding Plan key).");
  process.exit(2);
}

// A one-tool MCP server: `smoke_echo` just returns what it was given.
// If GLM reads the tools field and emits a tool_use block, the stdio
// bridge will see the request and respond; the model's final text will
// reference the echoed value.
const serverScript = `#!/usr/bin/env node
import { stdin, stdout } from "node:process";
let buf = "";
stdin.on("data", (c) => {
  buf += c.toString("utf8");
  let nl;
  while ((nl = buf.indexOf("\\n")) >= 0) {
    const line = buf.slice(0, nl); buf = buf.slice(nl + 1);
    if (!line.trim()) continue;
    let msg; try { msg = JSON.parse(line); } catch { continue; }
    if (msg.method === "initialize") {
      stdout.write(JSON.stringify({ jsonrpc:"2.0", id: msg.id,
        result: { protocolVersion: "2024-11-05", capabilities: { tools: {} },
          serverInfo: { name: "smoke", version: "0.1" } } }) + "\\n");
    } else if (msg.method === "tools/list") {
      stdout.write(JSON.stringify({ jsonrpc:"2.0", id: msg.id,
        result: { tools: [{ name: "smoke_echo",
          description: "Echo the input back verbatim.",
          inputSchema: { type:"object", properties: { msg: { type:"string" } },
                         required: ["msg"] } }] } }) + "\\n");
    } else if (msg.method === "tools/call") {
      const m = msg.params?.arguments?.msg || "";
      stdout.write(JSON.stringify({ jsonrpc:"2.0", id: msg.id,
        result: { content: [{ type: "text", text: "ECHO:" + m }] } }) + "\\n");
    } else if (msg.id != null) {
      stdout.write(JSON.stringify({ jsonrpc:"2.0", id: msg.id, result: {} }) + "\\n");
    }
  }
});
`;

const dir = path.join(tmpdir(), "pf-smoke-glm-mcp");
mkdirSync(dir, { recursive: true });
const serverPath = path.join(dir, "smoke-mcp-server.mjs");
writeFileSync(serverPath, serverScript, "utf8");
const configPath = path.join(dir, "smoke-mcp.json");
writeFileSync(configPath, JSON.stringify({
  mcpServers: { smoke: { command: process.execPath, args: [serverPath] } }
}), "utf8");

const prompt =
  "Call smoke_echo with msg=\"glm-mcp-works\" and quote the exact return value in your answer.";

// Probe the claude CLI first.
const probe = spawnSync(CLAUDE, ["--version"], { encoding: "utf8", shell: true });
if (probe.status !== 0) {
  console.error(`claude CLI not runnable: ${probe.stderr || probe.stdout}`);
  process.exit(3);
}

console.log(`[smoke] claude: ${probe.stdout.trim()}  endpoint: ${BASE}  model: ${MODEL}`);

const t0 = Date.now();
const child = spawn(CLAUDE, [
  "--print", "--model", MODEL, "--output-format", "json",
  "--mcp-config", configPath,
  "--strict-mcp-config",
  "--allowedTools", "mcp__smoke__smoke_echo",
], {
  shell: true,
  env: {
    ...process.env,
    ANTHROPIC_BASE_URL: BASE,
    ANTHROPIC_AUTH_TOKEN: TOKEN,
    ANTHROPIC_API_KEY: "",
  },
});

let out = "", err = "";
child.stdout.on("data", (c) => out += c);
child.stderr.on("data", (c) => err += c);
child.stdin.write(prompt);
child.stdin.end();

child.on("close", (code) => {
  const ms = Date.now() - t0;
  let parsed = null;
  try { parsed = JSON.parse(out); } catch {}
  const result = parsed?.result || out;
  const tookTool = /ECHO:glm-mcp-works/.test(result);
  console.log(`\n[smoke] exit=${code} duration=${ms}ms is_error=${parsed?.is_error ?? "?"}`);
  console.log(`[smoke] model echoed back: ${tookTool ? "YES" : "NO"}`);
  console.log(`[smoke] --- response head ---`);
  console.log(String(result).slice(0, 600));
  if (err) {
    console.log(`[smoke] --- stderr ---`);
    console.log(err.slice(0, 400));
  }
  process.exit(tookTool ? 0 : 1);
});
