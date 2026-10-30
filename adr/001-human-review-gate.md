# ADR-001 — Human review gate before CRM writes and outbound replies

**Status:** Accepted (2026-10-17); proposed 2026-10-16
**Date:** 2026-10-16
**Author:** Kristian Kobescak

## Context
An earlier Make.com lead-enrichment build
routes every lead automatically into High / Medium / Low. Its README lists
the gap: no review option for uncertain cases, so a lead with mixed signals
gets routed instead of flagged. Demand research
(2026-10-16) shows AI lead qualification into a CRM is the most
common automation request, and buyers ask for an approval step before AI
messages are sent. This build exists to win a first client with zero
reviews, so the demo must show that unclear cases and bad AI output are
handled safely, not only the happy path.

## Decision
A lead is routed automatically only when the input is valid, the AI output
passes schema validation, confidence is high, and the fit score is clearly
above or below the cut-off; every other lead, and every AI-drafted first
reply, waits for a person's approve / reject in Slack before anything is
written to HubSpot or sent to the lead.

## Alternatives rejected
- **Fully automatic routing (as in P1).** Fastest, but guesses on unclear
  leads and lets a wrong AI result reach the CRM. This is the exact gap P1
  documented.
- **Review every lead.** Safe, but removes most of the time saving, which
  is the reason a client buys the automation.
- **Auto-send AI replies without approval.** Buyers explicitly ask for an
  approval step; an unreviewed AI email to a real prospect is the most
  visible way this kind of system fails.

## Consequences
- Some leads wait for a person; response time for those depends on the
  reviewer.
- The cut-off band and confidence threshold must be tuned on the test set;
  the band width decides how much work goes to the reviewer.
- Local n8n uses Slack link-button approvals (signed link opens n8n in the
  browser). n8n does not record who clicked in this mode; the one-click
  in-Slack mode needs a public HTTPS URL.

## Review
Status moves to Accepted only after the recorded test run shows zero
invalid AI outputs and zero unapproved unsure leads reaching HubSpot.
Reopen when a client deployment needs approver identity (move to the
in-Slack interactive mode on a public instance) or when the review rate
on real traffic is too high to be practical.

## Verification (2026-10-17)
Implementation: `workflows/lead-qualifier.json`, nodes "Check AI answer"
(schema and range checks), "Decide route" (routing rules), "Ask reviewer in
Slack" and "Approve reply in Slack" (send-and-wait approvals before the
HubSpot write and before the e-mail send). Evidence:
`tests/results/run-20261017T000614Z.report.md`, produced by
`python tests/run_tests.py report` against the live n8n lead log and HubSpot:
0 leads in HubSpot that should not be there; 16 test contacts in HubSpot,
all through an allowed path (9 high fit + 7 approved by the reviewer);
simulated invalid AI output routed to review; 9 replies sent, all after
approval.
