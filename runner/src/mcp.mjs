// Phantom Fleet runner — Staffroom MCP bridge wiring.
//
// Does NOT mint tokens or drive the Staffroom owner UI. That is a one-time
// step the owner performs in Staffroom Settings → MCP (see the owner
// runbook, phase D). Once a token is pasted into the runner's env, this
// module builds the --mcp-config args + env the claude subprocess needs to
// reach Staffroom through the documented stdio bridge.
//
// Env contract (all three required to enable; any missing = disabled):
//   PF_STAFFROOM_MCP_BRIDGE   absolute path to staffroom-mcp-stdio.mjs
//   PF_STAFFROOM_MCP_URL      Staffroom MCP HTTPS endpoint (loopback OK)
//   PF_STAFFROOM_MCP_TOKEN    scoped `sr_mcp_...` token (43-char suffix)
//
// Scope: the runner never writes the token to the audit log. It is held in
// the subprocess env only; the token hash (first 8 chars of sha256) is the
// only form that ever lands in a log line.

import { createHash } from "node:crypto";
import { existsSync, readFileSync, writeFileSync, mkdirSync } from "node:fs";
import { tmpdir } from "node:os";
import path from "node:path";
import { fileURLToPath } from "node:url";

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const CONFIG_PATH = path.resolve(__dirname, "..", "mcp", "staffroom.json");

function tokenHash(t) {
  return createHash("sha256").update(t || "").digest("hex").slice(0, 8);
}

/** Resolve env → spawn args/env for the claude subprocess.
 *  Returns null if MCP is not configured; the caller then runs claude
 *  without MCP, as before.
 */
export function staffroomMcpSpawn() {
  const bridge = process.env.PF_STAFFROOM_MCP_BRIDGE;
  const url = process.env.PF_STAFFROOM_MCP_URL;
  const token = process.env.PF_STAFFROOM_MCP_TOKEN;
  if (!bridge || !url || !token) return null;
  if (!existsSync(bridge)) {
    throw new Error(`PF_STAFFROOM_MCP_BRIDGE does not exist: ${bridge}`);
  }
  if (!/^sr_mcp_[\w-]{43}$/.test(token)) {
    throw new Error("PF_STAFFROOM_MCP_TOKEN must be a scoped sr_mcp_ token");
  }
  if (!existsSync(CONFIG_PATH)) {
    throw new Error(`runner/mcp/staffroom.json missing at ${CONFIG_PATH}`);
  }
  // claude --mcp-config accepts a JSON *string*. Resolve placeholders here
  // so the bridge path and token travel together through one argument, and
  // the claude process never sees raw ${VAR} syntax.
  const template = JSON.parse(readFileSync(CONFIG_PATH, "utf8"));
  const server = template.mcpServers.staffroom;
  const resolved = {
    mcpServers: {
      staffroom: {
        command: server.command,
        args: server.args.map((a) => a.replace("${PF_STAFFROOM_MCP_BRIDGE}", bridge)),
        env: {
          STAFFROOM_MCP_URL: url,
          STAFFROOM_MCP_TOKEN: token,
        },
      },
    },
  };
  // The runner spawns claude with shell:true on Windows, which breaks when
  // the JSON config travels as a quoted CLI arg (braces/colons are chewed
  // by cmd.exe and claude reads the garbled text as a filename). Write the
  // JSON to a per-process temp file and pass the path instead.
  const dir = path.join(tmpdir(), "phantom-fleet-mcp");
  mkdirSync(dir, { recursive: true });
  const configFile = path.join(dir, `staffroom-${process.pid}.json`);
  writeFileSync(configFile, JSON.stringify(resolved), "utf8");
  // Non-interactive claude (--print) silently refuses MCP tool calls that
  // aren't on --allowedTools. Pin the read-safe Staffroom tool surface
  // and the one write that only drafts a proposal for owner approval; no
  // tool here executes real work. Anything outside this list still
  // requires an owner approval round-trip.
  const allowedTools = [
    "mcp__staffroom__staffroom_workspace",
    "mcp__staffroom__staffroom_list_projects",
    "mcp__staffroom__staffroom_get_project",
    "mcp__staffroom__staffroom_list_bots",
    "mcp__staffroom__staffroom_list_chats",
    "mcp__staffroom__staffroom_read_chat",
    "mcp__staffroom__staffroom_list_pending_decisions",
    "mcp__staffroom__staffroom_get_run",
    "mcp__staffroom__staffroom_read_artifact",
    "mcp__staffroom__staffroom_recall_similar",
    "mcp__staffroom__staffroom_recall_contradictions",
    "mcp__staffroom__staffroom_recall_lineage",
    "mcp__staffroom__phantom_fleet_simulate_shape",
    "mcp__staffroom__phantom_fleet_simulate_actions",
    "mcp__staffroom__phantom_fleet_ghost_preview",
    "mcp__staffroom__staffroom_time_machine_snapshot",
    "mcp__staffroom__staffroom_time_machine_snapshots",
    "mcp__staffroom__staffroom_fork_from",
    "mcp__staffroom__staffroom_time_machine_forks",
    "mcp__staffroom__staffroom_propose_tool",
    "mcp__staffroom__staffroom_list_tool_proposals",
    "mcp__staffroom__staffroom_discover_tool_proposals",
    "mcp__staffroom__staffroom_owner_brief",
    "mcp__staffroom__staffroom_route_recommendation",
    "mcp__staffroom__staffroom_list_computers",
    "mcp__staffroom__staffroom_discover_tools",
    "mcp__staffroom__staffroom_tool_details",
    "mcp__staffroom__staffroom_tool_status",
    "mcp__staffroom__staffroom_propose_work",
  ].join(",");
  return {
    cliArgs: [
      "--mcp-config", configFile,
      "--strict-mcp-config",
      "--allowedTools", allowedTools,
    ],
    tokenHash: tokenHash(token),
    bridge,
    url,
    configFile,
  };
}

/** Classify a prompt so we only attach MCP when the model actually needs
 *  Staffroom tool access.  Attaching on every call would be safe but
 *  wasteful — the bridge spawns a node subprocess per claude call. */
export function needsStaffroomMcp(messages) {
  const text = (messages || [])
    .filter((m) => m && (m.role === "user" || m.role === "system"))
    .map((m) => String(m.content || "").toLowerCase())
    .join("\n");
  return (
    text.includes("staffroom_get_project") ||
    text.includes("staffroom_list_artifacts") ||
    text.includes("staffroom_get_artifact") ||
    text.includes("use the staffroom mcp") ||
    text.includes("via staffroom mcp")
  );
}

export function mcpSummary() {
  const spec = (() => {
    try { return staffroomMcpSpawn(); } catch (e) { return { error: String(e.message || e) }; }
  })();
  if (!spec) return { configured: false };
  if (spec.error) return { configured: false, error: spec.error };
  return {
    configured: true,
    url: spec.url,
    bridge: spec.bridge,
    token_hash: spec.tokenHash,
  };
}
