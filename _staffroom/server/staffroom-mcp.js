// Staffroom MCP tool wiring for Phantom Fleet.
//
// Exposes tools that call the Phantom Fleet HTTP API. All write paths
// land in `needs_approval` queues — nothing in this file can approve
// a row or post a comment. Approval is always owner-gated.
//
// `fleetPost(path, body)` is the shared POST helper used by every
// tool here. It reads the Fleet URL from env and never leaks the
// Fleet token to the MCP transport.

"use strict";

const FLEET_URL =
  process.env.PF_FLEET_API_URL || "http://127.0.0.1:8000";
const FLEET_TOKEN = process.env.PF_FLEET_API_TOKEN || "";

/** POST JSON to the Fleet API, returning the parsed JSON body. */
async function fleetPost(path, body) {
  const url = `${FLEET_URL.replace(/\/$/, "")}${path}`;
  const headers = { "content-type": "application/json" };
  if (FLEET_TOKEN) headers["authorization"] = `Bearer ${FLEET_TOKEN}`;
  const res = await fetch(url, {
    method: "POST",
    headers,
    body: JSON.stringify(body || {}),
  });
  const text = await res.text();
  let data;
  try {
    data = text ? JSON.parse(text) : {};
  } catch {
    data = { raw: text };
  }
  if (!res.ok) {
    return {
      ok: false,
      status: res.status,
      error: data && data.detail ? data.detail : text || `HTTP ${res.status}`,
    };
  }
  return { ok: true, status: res.status, ...data };
}

/** staffroom_generate_comments — produce AI candidate comments that
 *  land in `comment_pool.status='needs_approval'` for owner review.
 *
 *  Input:  { niche: string, n: int, style_hints?: string[] }
 *  Output: the Fleet receipt from /api/comments/generate.
 *
 *  This tool cannot approve, activate, or post a comment. It only
 *  drafts candidates; the owner approves via the /approvals UI.
 */
const staffroom_generate_comments = {
  name: "staffroom_generate_comments",
  description:
    "Generate AI candidate comments for a niche. Lands rows as " +
    "needs_approval in comment_pool; owner approves via /approvals. " +
    "Cannot approve or post — admission gate is non-bypassable.",
  inputSchema: {
    type: "object",
    required: ["niche", "n"],
    properties: {
      niche: { type: "string", minLength: 1, maxLength: 40 },
      n: { type: "integer", minimum: 1, maximum: 200 },
      style_hints: {
        type: "array",
        items: { type: "string" },
        maxItems: 20,
      },
    },
    additionalProperties: false,
  },
  async handler(args) {
    const { niche, n, style_hints } = args || {};
    return fleetPost("/api/comments/generate", {
      niche,
      n,
      style_hints: style_hints || null,
    });
  },
};

module.exports = {
  fleetPost,
  tools: {
    staffroom_generate_comments,
  },
  staffroom_generate_comments,
};
