# STATE — n8n-ai-lead-qualifier

n8n AI lead qualifier with human review in Slack; Upwork portfolio build (Q-116) to support winning a first client.
**Classification:** PROJECT · T0
**Plan:** Build is done when all five quality-bar items hold (owner-agreed 2026-10-16, no fixed date): (1) form → website enrichment → AI score → HubSpot; (2) hard cases handled and visible: unsure leads to Slack approval, broken input / invalid AI output never reach the CRM, duplicates skipped, API errors retried and alerted; (3) AI drafts the first reply to good leads, a person approves in Slack before it is sent; (4) 30-40 realistic test leads with expected routes, real recorded numbers, simulated failures marked as such; (5) 2-3 minute Loom + client-language README.
**Stack (owner choices 2026-10-16/17):** local n8n 2.43.7 (npm, Node 24.20.0) · HubSpot free demo account "Portfolio Demo" (service key; separate from the owner's real HubSpot) · Claude Opus 5.5 via Anthropic workspace `lead-qualifier` · Slack demo workspace `#lead-review` · Gmail SMTP, demo mode (replies only to the owner's test inbox).
**Status:** quality-bar items 1-4 met (evidence below); item 5 README done, Loom not recorded. Remote: private GitHub repo kobescak-kristian/n8n-ai-lead-qualifier (created by owner 2026-10-17; first push 68966ba). Public release is a separate owner decision.
**Open decisions:** none
**Decisions:** adr/001-human-review-gate.md (Accepted 2026-10-17)

## Change Log
*(New entries on top. Phase closes require evidence: exit codes,
commit hashes, eval numbers.)*

- **2026-10-17** — Build + test run. Workflows exported from live n8n into `workflows/` (credentials and e-mail settings stripped). Test run `tests/results/run-20261017T000614Z.json` (runner exit 0), report `tests/results/run-20261017T000614Z.report.md`: 39 leads, 38/39 routed as expected (miss: U01 unsure -> low_fit), 0 leads in HubSpot that should not be there, 16 test contacts in HubSpot all via allowed path (9 high fit + 7 reviewer-approved), 4/4 invalid inputs stopped, 3/3 duplicates skipped, 2/2 injection attempts low fit, simulated bad AI output -> review, simulated API error -> alert; 16 replies drafted, 9 approved and sent to demo inbox, 7 rejected (owner note 2026-10-17: review and reply clicks alternated to test both buttons; draft quality not measured). Median 4.9 s form-to-route (n=32 AI-scored). Fixes found in smoke tests: Code-node sandbox has no `URL` class (website never read), runner `source` field caused a false red flag, HubSpot rejects `.example` e-mails (test domains moved to example.com), HubSpot failure branch added. ADR-001 accepted. Commits: b8ae6c0, 3741da2, 60b9340, + close commit.
- **2026-10-16** — Scaffold (new-project, standard). Separate repo per automation (owner decision 2026-10-16).
