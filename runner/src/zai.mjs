// Z.ai CLI bridge — scaffolding only.
//
// Mirrors the shape of mcp.mjs so the runner can spawn a z.ai coding agent
// subprocess with the same Staffroom MCP wiring and token-hash audit line.
// The actual CLI name, args, and auth flow are pending research; this
// module validates env, surfaces a typed spec, and refuses to activate
// until PF_ZAI_CLI_BIN is set.
//
// Env contract:
//   PF_ZAI_CLI_BIN       path to z.ai CLI binary (e.g. z-cli, glm, zai)
//   PF_ZAI_CLI_AUTH_MODE "api_key" (reads PF_ZAI_API_KEY) or "plan" (signed-in CLI)
//   PF_ZAI_API_KEY       z.ai API key — never written to logs; only token hash

import { createHash } from "node:crypto";
import { existsSync } from "node:fs";

function tokenHash(t) {
  return createHash("sha256").update(t || "").digest("hex").slice(0, 8);
}

export function zaiCliSpec() {
  const bin = process.env.PF_ZAI_CLI_BIN;
  if (!bin) return null;
  const authMode = process.env.PF_ZAI_CLI_AUTH_MODE || "api_key";
  if (!["api_key", "plan"].includes(authMode)) {
    throw new Error(`PF_ZAI_CLI_AUTH_MODE must be api_key or plan, got: ${authMode}`);
  }
  if (authMode === "api_key" && !process.env.PF_ZAI_API_KEY) {
    throw new Error("PF_ZAI_CLI_AUTH_MODE=api_key but PF_ZAI_API_KEY is unset.");
  }
  // When bin is an absolute path, verify it exists. A bare name resolves
  // against PATH at spawn time, which is deferred to the runner.
  if (/[\\\/]/.test(bin) && !existsSync(bin)) {
    throw new Error(`PF_ZAI_CLI_BIN does not exist: ${bin}`);
  }
  return {
    bin,
    authMode,
    tokenHash: authMode === "api_key" ? tokenHash(process.env.PF_ZAI_API_KEY) : null,
    env: authMode === "api_key"
      ? { Z_AI_API_KEY: process.env.PF_ZAI_API_KEY }
      : {},
  };
}

export function zaiSummary() {
  try {
    const s = zaiCliSpec();
    if (!s) return { configured: false };
    return {
      configured: true,
      bin: s.bin,
      auth_mode: s.authMode,
      token_hash: s.tokenHash,
    };
  } catch (err) {
    return { configured: false, error: String(err.message || err) };
  }
}
