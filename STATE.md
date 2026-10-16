# STATE — n8n-ai-lead-qualifier

n8n AI lead qualifier with human review in Slack; Upwork portfolio build (Q-116) to support winning a first client.
**Classification:** PROJECT · T0
**Plan:** Build is done when all five quality-bar items hold (owner-agreed 2026-10-16, no fixed date): (1) form → website enrichment → AI score → HubSpot; (2) hard cases handled and visible: unsure leads to Slack approval, broken input / invalid AI output never reach the CRM, duplicates skipped, API errors retried and alerted; (3) AI drafts the first reply to good leads, a person approves in Slack before it is sent; (4) 30-40 realistic test leads with expected routes, real recorded numbers, simulated failures marked as such; (5) 2-3 minute Loom + client-language README.
**Stack (owner choices 2026-10-16):** local n8n (npm, Node 24 LTS) · HubSpot free · Anthropic Claude · Slack demo workspace, new channel.
**Open decisions:** none
**Decisions:** adr/001-human-review-gate.md (Proposed)

## Change Log
*(New entries on top. Phase closes require evidence: exit codes,
commit hashes, eval numbers.)*

- **2026-10-16** — Scaffold (new-project, standard). Separate repo per automation (owner decision 2026-10-16).
