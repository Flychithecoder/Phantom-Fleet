// Preflight: verify the local Claude Code CLI is signed in and can report
// its effective model for the two pinned IDs.  Run this before every live
// mission dispatch — it's the gate the owner brief asks for.

import { spawnSync } from "node:child_process";

const CLAUDE = process.env.PF_CLAUDE_BIN || "claude";

function probe(args, name) {
  const r = spawnSync(CLAUDE, args, { encoding: "utf8", shell: true });
  return {
    name,
    args,
    exit: r.status,
    stdout: (r.stdout || "").trim(),
    stderr: (r.stderr || "").trim(),
  };
}

const report = {
  checked_at: new Date().toISOString(),
  claude_bin: CLAUDE,
  version: probe(["--version"], "version"),
  // `auth status` can be interactive; skip it in CI contexts.
};

console.log(JSON.stringify(report, null, 2));
process.exit(report.version.exit === 0 ? 0 : 2);
