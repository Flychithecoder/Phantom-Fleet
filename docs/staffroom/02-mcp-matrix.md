# Role × MCP-tool permission matrix

The Staffroom MCP catalog (from `STAFFROOM_MCP.md`) has 13 tools. This matrix
pins which roles may **R**ead, **P**ropose, **A**pprove, or **E**xecute each
one. Only the owner has `A` on anything that touches a computer. The agents'
own tool access can propose permission changes through the owner workflow but
can never grant themselves authority.

Legend: **R** read-only · **P** may propose (shows in Staffroom "Needs you") ·
**A** may approve (owner only) · **E** may execute without approval (tightly
scoped, only on standing-permission items).

## MCP tool catalog in scope

1. `staffroom_workspace` — workspace identity and grants
2. `staffroom_list_projects` — projects in scope
3. `staffroom_get_project` — project brief, roster, linked chats
4. `staffroom_list_bots` — bots in scope
5. `staffroom_list_chats` — conversations in scope
6. `staffroom_read_chat` — recent messages of one chat
7. `staffroom_list_pending_decisions` — pending approvals in scope
8. `staffroom_propose_work` — new work proposal (approval card)
9. `staffroom_get_run` — run status and artifact references
10. `staffroom_read_artifact` — saved deliverable
11. `staffroom_list_computers` — granted computers
12. `staffroom_request_computer_action` — propose one computer operation
13. `staffroom_get_computer_action` — status + approved result of an action

## Matrix

| Role | ws | list_projects | get_project | list_bots | list_chats | read_chat | list_pending | propose_work | get_run | read_artifact | list_computers | request_action | get_action |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| **Opus COO** | R | R | R | R | R | R | R | P | R | R | R | — | — |
| Operations Coordinator | — | R | R | — | R | — | R | — | R | R | — | — | — |
| Device Inventory Specialist | — | — | — | — | — | — | — | P | R | R | R | — | — |
| Fleet Health Specialist | — | — | — | — | — | — | — | — | R | R | — | — | — |
| Maintenance Coordinator | — | — | — | — | — | — | — | P | R | R | — | — | — |
| Incident Triage Lead | — | R | R | — | R | R | R | P | R | R | R | — | R |
| Recovery Specialist | — | — | — | — | — | — | — | P | — | R | — | — | — |
| Product Operations Lead | — | R | R | — | — | — | — | — | — | R | — | — | — |
| Engineering Specialist | — | — | — | — | — | — | — | P | — | R | — | — | — |
| QA Lead | — | — | — | — | — | — | — | P | — | R | — | — | — |
| Release Coordinator | — | — | — | — | — | — | — | P | — | R | — | — | — |
| Data Quality Specialist | — | — | — | — | — | — | — | — | — | R | — | — | — |
| Operations Analyst | — | — | — | — | — | — | — | P | R | R | — | — | — |
| Executive Reporting Worker | — | — | — | — | — | — | — | — | R | R | — | — | — |
| Access Reviewer | R | R | R | R | — | — | — | — | — | R | R | — | — |
| Compliance Reviewer | — | — | — | — | — | — | R | — | — | R | — | — | — |
| Onboarding Specialist | — | — | — | — | — | — | — | P | — | R | — | — | — |
| Support Triage Specialist | — | — | — | — | — | R | — | P | — | — | — | — | — |
| Customer Success Specialist | — | — | — | — | — | — | — | — | — | R | — | — | — |
| Cost Analyst | — | — | — | — | — | — | — | — | — | R | — | — | — |
| Reconciliation Specialist | — | — | — | — | — | — | — | — | — | R | — | — | — |
| **Owner (you)** | A | A | A | A | A | A | A | A | A | A | A | A | A |

## Standing-permission (E) tools

None during pilot. All `staffroom_propose_work`, `staffroom_request_computer_action`,
and anything that touches the fleet goes to owner approval. This matches the
brief's "pilot is read-only against Fleet".

## Fleet-side REST access by role

Staffroom MCP is one axis; Fleet's own REST surface is the other. Roles with
`staffroom_propose_work` can also hit scoped Fleet read endpoints while
drafting their proposals.

| Role | Fleet routes (read) | Fleet routes (write) |
|---|---|---|
| Opus COO | all | none (only through owner approval) |
| Fleet Health Specialist | `/api/platforms/instagram/health/*`, `/api/platforms/threads/health/*`, `/api/fleet/cluster/collisions`, `/api/platforms/instagram/{proxy,drift,session}/*` | none |
| Device Inventory Specialist | `/api/fleet/*`, `/api/fleet_mirror/*` | none |
| Maintenance Coordinator | `/api/platforms/instagram/{proxy,session,executor}/*` | none during pilot |
| Incident Triage Lead | `/api/platforms/instagram/{checkpoint,recovery}/*`, `/api/activity-log` | none |
| QA Lead | `/api/platforms/threads/audit/*` | none |
| Operations Analyst | `/api/activity-log`, `/api/platforms/*/summary` | none |
| Executive Reporting Worker | `/api/briefing`, aggregated summaries | none |
| Cost Analyst | `/api/platforms/staffroom/missions/*` (runner evidence) | none |
| Access Reviewer | `/api/platforms/staffroom/grants` (to build) | none |

## Permission-change workflow

An agent that needs a permission it does not have **must**:

1. Call `staffroom_propose_work` with `request_key = "role-grant:<role>:<tool>"` and a brief naming the tool and justification.
2. Wait for the proposal to appear in owner's "Needs you".
3. Owner approves in Staffroom.
4. Access Reviewer re-generates the matrix artifact.

Agents cannot bypass this. The Fleet-side admission check mirrors the
Staffroom check: `/api/platforms/staffroom/grants/can?role=X&tool=Y` returns
the current cell in this matrix.

## Explicit prohibitions

- No agent has `A` on any cell. Only the owner approves.
- No agent has `E` during pilot.
- The two fleet-destructive CLAUDE.md gates — "never flash a phone without owner confirmation" and "never factory-reset without owner confirmation" — are enforced in code at the Fleet backend, not just in prompt. The matrix above never grants write access to those routes to any role.
