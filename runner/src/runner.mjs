// Phantom Fleet owner runner.
//
// Exposes an OpenAI-compatible `POST /v1/chat/completions` on 127.0.0.1 so
// Staffroom (which does `fetch(MODEL_BASE_URL + "/chat/completions")` with a
// Bearer key — see _staffroom/server/providers.js) can route jobs through
// `claude` CLI on this box, using the user's signed-in subscription.
//
// Routing: the Bearer token picks the pinned model.
//     Bearer pf-opus   -> claude-opus-4-7     (COO plan + final review)
//     Bearer pf-sonnet -> claude-sonnet-4-6   (worker specialists)
//
// Guard rails:
//   * one in-flight call at a time (the brief asks for this)
//   * no paid fallback — if `claude` exits non-zero we return 502 with the
//     exit text, no silent reroute
//   * refuse to start unless `claude auth status` reports a logged-in CLI
//   * every call is audit-logged to logs/runner-audit.ndjson
//
// This is not a general LLM proxy; it accepts only two tokens and only the
// two pinned model ids.

import http from "node:http";
import { spawn, spawnSync } from "node:child_process";
import { mkdirSync, appendFileSync } from "node:fs";
import { createHash } from "node:crypto";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { staffroomMcpSpawn, needsStaffroomMcp, mcpSummary } from "./mcp.mjs";

const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);
const LOG_DIR = path.resolve(__dirname, "..", "logs");
const AUDIT = path.join(LOG_DIR, "runner-audit.ndjson");
try { mkdirSync(LOG_DIR, { recursive: true }); } catch {}

const HOST = process.env.PF_RUNNER_HOST || "127.0.0.1";
const PORT = Number(process.env.PF_RUNNER_PORT || 4330);
const CLAUDE_BIN = process.env.PF_CLAUDE_BIN || "claude";

const MODEL_MAP = {
  "pf-opus":   "claude-opus-4-7",
  "pf-sonnet": "claude-sonnet-4-6",
  // GLM Coding Plan — same `claude` binary, but ANTHROPIC_BASE_URL +
  // ANTHROPIC_AUTH_TOKEN swapped to z.ai's Anthropic-shape endpoint. Uses
  // the owner's plan credits (flat-rate), not pay-as-you-go API billing.
  // The model id is what z.ai accepts on its Anthropic endpoint — GLM-5.4
  // once plan allows, GLM-5.3 today.
  "pf-glm-plan":      "glm-5.3",
  "pf-glm-plan-max":  "glm-5.4",
  // 'local' is what Staffroom sends when LOCAL_MODEL_BASE_URL/LOCAL_MODEL_NAME
  // are the configured provider — all missions share one engine-level
  // connection.  We auto-route COO vs worker by inspecting the prompt: the
  // chief-of-staff / plan / review turns go to opus, everything else to
  // sonnet.  The effective_model is still captured and audit-logged, so the
  // pin can be verified from the log at run time.
  "local":     "auto",
};

const GLM_BEARERS = new Set(["pf-glm-plan", "pf-glm-plan-max"]);

// Env-var swap for the claude subprocess so the same binary talks to z.ai
// instead of Anthropic. Only applied for pf-glm-* bearers.
function glmEnv() {
  const base = process.env.PF_ZAI_ANTHROPIC_BASE_URL
    || "https://api.z.ai/api/anthropic";
  const token = process.env.PF_ZAI_PLAN_TOKEN
    || process.env.PF_ZAI_API_KEY
    || "";
  if (!token) {
    throw new Error("PF_ZAI_PLAN_TOKEN (or PF_ZAI_API_KEY) must be set for pf-glm-plan bearers");
  }
  return {
    ANTHROPIC_BASE_URL: base,
    ANTHROPIC_AUTH_TOKEN: token,
    // Strip any inherited Anthropic creds so there's no cross-wire risk.
    ANTHROPIC_API_KEY: "",
  };
}

// Staffroom builds worker prompts as `Original request: <brief>\n
// Assignment: <task>\nPeer evidence: ...` (see server/engine.js line 700),
// which means the Fleet brief text IS visible in worker user messages too.
// The only reliable in-prompt distinguisher is the literal `Assignment:` /
// `Peer evidence:` scaffolding Staffroom adds for team-mode workers — the
// COO's planning call and the chief's final review turn do not carry
// those keys.
const WORKER_MARKERS = [
  "\nassignment:",
  "\npeer evidence:",
];

function autoPickModel(messages) {
  const userText = messages
    .filter((m) => m && m.role === "user")
    .map((m) => "\n" + String(m.content || "").toLowerCase())
    .join("\n");
  for (const marker of WORKER_MARKERS) {
    if (userText.includes(marker)) return "claude-sonnet-4-6";
  }
  return "claude-opus-4-7";
}

// Simple mutex — one claude subprocess at a time.
let busy = false;
const waiters = [];
function acquire() {
  if (!busy) { busy = true; return Promise.resolve(); }
  return new Promise((resolve) => waiters.push(resolve));
}
function release() {
  const next = waiters.shift();
  if (next) next();
  else busy = false;
}

function sha(s) { return createHash("sha256").update(s).digest("hex").slice(0, 16); }

function audit(entry) {
  try {
    appendFileSync(AUDIT, JSON.stringify({ t: new Date().toISOString(), ...entry }) + "\n");
  } catch {}
}

function readBody(req) {
  return new Promise((resolve, reject) => {
    const chunks = [];
    req.on("data", (c) => chunks.push(c));
    req.on("end", () => resolve(Buffer.concat(chunks).toString("utf8")));
    req.on("error", reject);
  });
}

function bearerFrom(req) {
  const h = req.headers["authorization"] || "";
  const m = h.match(/^Bearer\s+(\S+)$/i);
  return m ? m[1].trim() : "";
}

function doctor() {
  // Cheap check: `claude --version` should exit 0.  A proper `auth status`
  // call is slow and may spawn a browser; we accept the version probe for
  // boot and let the first real call surface a stale-session error.
  const probe = spawnSync(CLAUDE_BIN, ["--version"], { encoding: "utf8", shell: true });
  if (probe.status !== 0) {
    throw new Error(`claude CLI not runnable (exit ${probe.status}): ${probe.stderr || probe.stdout || "no output"}`);
  }
  return (probe.stdout || "").trim();
}

function messagesToPrompt(messages) {
  // claude --print takes a single prompt string.  Join the conversation into
  // a role-tagged transcript the model can read as instructions + prior turns.
  // System messages lead; the rest keep their order.
  const sys = messages.filter((m) => m.role === "system").map((m) => m.content).join("\n\n");
  const rest = messages.filter((m) => m.role !== "system");
  const lines = rest.map((m) => `${(m.role || "user").toUpperCase()}:\n${m.content}`);
  return [sys, ...lines].filter(Boolean).join("\n\n");
}

async function callClaude(model, prompt, mcpSpec, extraEnv, maxTokens) {
  return new Promise((resolve, reject) => {
    const args = ["--print", "--model", model, "--output-format", "json"];
    if (mcpSpec) args.push(...mcpSpec.cliArgs);
    // Hard output cap — mandatory for GLM bearers to prevent the
    // "marathon thinking" failure mode noted in z.ai's own GLM-5.4 docs.
    // Also serves as a defense-in-depth gate for any runaway Claude call.
    if (Number.isFinite(maxTokens) && maxTokens > 0) {
      args.push("--max-tokens", String(Math.floor(maxTokens)));
    }
    const spawnEnv = extraEnv ? { ...process.env, ...extraEnv } : process.env;
    const child = spawn(CLAUDE_BIN, args, { shell: true, env: spawnEnv });
    let stdout = "";
    let stderr = "";
    const t0 = Date.now();
    child.stdout.on("data", (c) => { stdout += c.toString("utf8"); });
    child.stderr.on("data", (c) => { stderr += c.toString("utf8"); });
    child.on("error", reject);
    child.on("close", (code) => {
      const ms = Date.now() - t0;
      // claude --output-format json emits one JSON object on stdout even on
      // auth / rate / model failures (it sets is_error and api_error_status
      // inside the object). Parse first, then classify, so our audit log and
      // 502 body carry the real reason rather than a bare exit code.
      let parsed = null;
      try { parsed = JSON.parse(stdout); } catch {}
      if (code !== 0 || (parsed && parsed.is_error)) {
        const detail = parsed?.result || stderr.trim() || stdout.trim() || `exit ${code}`;
        reject(Object.assign(new Error(`claude ${parsed?.api_error_status ?? code}: ${String(detail).slice(0, 500)}`),
                             { code, parsed, stderr, stdout, ms }));
        return;
      }
      if (parsed) { resolve({ parsed, ms, raw: stdout }); return; }
      resolve({ parsed: { result: stdout }, ms, raw: stdout });
    });
    child.stdin.write(prompt);
    child.stdin.end();
  });
}

function sendJson(res, status, body) {
  const text = JSON.stringify(body);
  res.writeHead(status, {
    "Content-Type": "application/json; charset=utf-8",
    "Content-Length": Buffer.byteLength(text),
    "Cache-Control": "no-store",
  });
  res.end(text);
}

// Keep the response socket alive during long claude runs so intermediate
// proxies / Node's undici don't drop the idle connection. Short calls use
// sendJson with a proper status; long calls (>HEARTBEAT_GRACE_MS) get a
// chunked response whose leading whitespace is ignored by JSON.parse. The
// body appended at close carries the real payload.
const HEARTBEAT_GRACE_MS = 8_000;
const KEEPALIVE_MS = 10_000;
function keepaliveSender(res) {
  let opened = false;
  let closed = false;
  let timer = null;
  const open = () => {
    if (opened || closed) return;
    opened = true;
    res.writeHead(200, {
      "Content-Type": "application/json; charset=utf-8",
      "Transfer-Encoding": "chunked",
      "Cache-Control": "no-store",
      "Connection": "keep-alive",
    });
    timer = setInterval(() => {
      if (closed || res.writableEnded) return;
      try { res.write(" "); } catch { /* client gone */ }
    }, KEEPALIVE_MS);
    timer.unref?.();
  };
  const grace = setTimeout(open, HEARTBEAT_GRACE_MS);
  grace.unref?.();
  return {
    isOpen() { return opened; },
    send(status, body) {
      if (closed) return;
      closed = true;
      clearTimeout(grace);
      if (timer) clearInterval(timer);
      if (opened) {
        try { res.end(JSON.stringify(body)); } catch { /* already closed */ }
      } else {
        sendJson(res, status, body);
      }
    },
  };
}

async function handleChat(req, res) {
  const bearer = bearerFrom(req);
  let pinnedModel = MODEL_MAP[bearer];
  if (!pinnedModel) {
    audit({ event: "reject", reason: "unknown_bearer", bearer_tail: bearer.slice(-4) });
    return sendJson(res, 401, { error: { message: "unknown owner-runner token", type: "unauthorized" } });
  }
  const raw = await readBody(req);
  let payload;
  try { payload = JSON.parse(raw || "{}"); }
  catch { return sendJson(res, 400, { error: { message: "bad json body" } }); }
  const messages = Array.isArray(payload.messages) ? payload.messages : [];
  if (!messages.length) return sendJson(res, 400, { error: { message: "messages[] required" } });

  const prompt = messagesToPrompt(messages);
  const promptHash = sha(prompt);
  if (pinnedModel === "auto") pinnedModel = autoPickModel(messages);

  // Attach the Staffroom MCP bridge only when (a) the owner has configured
  // it in the runner env AND (b) the prompt actually references a
  // Staffroom tool name.  Otherwise this call runs without MCP, exactly as
  // phase A did.
  let mcpSpec = null;
  let mcpAttached = false;
  try {
    const canAttach = staffroomMcpSpawn();
    if (canAttach && needsStaffroomMcp(messages)) {
      mcpSpec = canAttach;
      mcpAttached = true;
    }
  } catch (err) {
    audit({ event: "mcp_config_error", error: String(err.message || err).slice(0, 300) });
  }

  await acquire();
  const t0 = Date.now();
  // Short claude calls (auth probe, fast replies) get a plain Content-Length
  // response with the real status code. Calls that exceed the grace window
  // flip to chunked + whitespace heartbeat to keep intermediate sockets
  // alive. The branch is transparent to the Staffroom engine.
  const stream = keepaliveSender(res);
  // GLM-plan bearers swap the claude subprocess env to point at z.ai's
  // Anthropic-shape endpoint. MCP wiring is unchanged — tool defs ride
  // in the Anthropic message format, which z.ai's endpoint accepts.
  let subprocessEnv = null;
  let maxTokens = null;
  if (GLM_BEARERS.has(bearer)) {
    try { subprocessEnv = glmEnv(); }
    catch (err) {
      audit({ event: "reject", reason: "glm_env_missing", error: String(err.message).slice(0, 200) });
      return sendJson(res, 500, { error: { message: String(err.message), type: "glm_env_missing" } });
    }
    // Hard thinking-budget cap for GLM. 12K worker / 24K COO by default —
    // sized to fit ~5K thinking + deliverable + citations for workers and
    // ~10K thinking + plan + executive report for the COO. Well under
    // GLM-5.4's 128K output ceiling and far below "marathon thinking"
    // territory (40K+). Overridable per bearer via env.
    const defaultCap = Number(process.env.PF_GLM_MAX_TOKENS || 12000);
    const maxCap = Number(process.env.PF_GLM_MAX_TOKENS_COO || 24000);
    maxTokens = bearer === "pf-glm-plan-max" ? maxCap : defaultCap;
  }

  try {
    const { parsed, ms } = await callClaude(pinnedModel, prompt, mcpSpec, subprocessEnv, maxTokens);
    const content = typeof parsed.result === "string"
      ? parsed.result
      : (typeof parsed.content === "string" ? parsed.content : JSON.stringify(parsed));
    const effectiveModel = parsed.model || pinnedModel;
    const usage = parsed.usage || {};
    const responseHash = sha(content);
    audit({
      event: "ok",
      bearer_tail: bearer.slice(-4),
      requested_model: payload.model || null,
      pinned_model: pinnedModel,
      effective_model: effectiveModel,
      prompt_hash: promptHash,
      prompt_chars: prompt.length,
      response_hash: responseHash,
      response_chars: content.length,
      duration_ms: ms,
      session_id: parsed.session_id || null,
      cost_usd: parsed.total_cost_usd ?? null,
      mcp_attached: mcpAttached,
      mcp_token_hash: mcpSpec?.tokenHash || null,
    });
    stream.send(200, {
      id: `pf-${Date.now()}-${promptHash}`,
      object: "chat.completion",
      created: Math.floor(Date.now() / 1000),
      model: effectiveModel,
      choices: [{ index: 0, message: { role: "assistant", content }, finish_reason: "stop" }],
      usage: {
        prompt_tokens: usage.input_tokens ?? 0,
        completion_tokens: usage.output_tokens ?? 0,
        total_tokens: (usage.input_tokens ?? 0) + (usage.output_tokens ?? 0),
      },
      phantom_fleet: {
        pinned_model: pinnedModel,
        vendor: GLM_BEARERS.has(bearer) ? "zai" : "anthropic",
        bearer_role: bearer === "pf-opus" ? "coo" : "worker",
        runner_version: "0.2.0",
        duration_ms: ms,
        session_id: parsed.session_id || null,
        cost_usd: parsed.total_cost_usd ?? null,
      },
    });
    return;
  } catch (err) {
    const ms = Date.now() - t0;
    audit({
      event: "fail",
      bearer_tail: bearer.slice(-4),
      pinned_model: pinnedModel,
      prompt_hash: promptHash,
      error: String(err.message || err).slice(0, 500),
      duration_ms: ms,
    });
    // Fast failures (before the grace window) still return a proper 502
    // with Content-Length. Late failures after the stream has opened must
    // close with status 200 (committed) carrying the error shape in the
    // body; Staffroom will surface it as "Model returned no usable text"
    // which is accurate — the model produced nothing to work with.
    stream.send(502, {
      error: {
        message: `claude CLI failed; no paid fallback by policy. ${String(err.message || err).slice(0, 300)}`,
        type: "upstream_error",
      },
    });
    return;
  } finally {
    release();
  }
}

const server = http.createServer(async (req, res) => {
  const url = req.url || "";
  if (req.method === "GET" && (url === "/health" || url === "/")) {
    return sendJson(res, 200, {
      ok: true,
      runner: "phantom-fleet-runner",
      version: "0.2.0",
      host: HOST,
      port: PORT,
      models: MODEL_MAP,
      busy,
      staffroom_mcp: mcpSummary(),
    });
  }
  if (req.method === "POST" && (url === "/v1/chat/completions" || url === "/chat/completions")) {
    return handleChat(req, res);
  }
  sendJson(res, 404, { error: { message: "not found" } });
});

try {
  const version = doctor();
  console.log(`[runner] claude CLI OK: ${version}`);
} catch (e) {
  console.error(`[runner] FATAL: ${e.message}`);
  process.exit(2);
}

server.listen(PORT, HOST, () => {
  console.log(`[runner] listening on http://${HOST}:${PORT}`);
  console.log(`[runner] POST /v1/chat/completions   (Bearer pf-opus | pf-sonnet)`);
  console.log(`[runner] audit log: ${AUDIT}`);
});
