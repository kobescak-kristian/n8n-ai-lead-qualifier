# n8n AI Lead Qualifier

An n8n workflow that checks, researches and scores every new lead with AI, sends good leads to HubSpot, and asks a person in Slack before anything uncertain reaches the CRM or a prospect's inbox.

## Problem

Sales teams lose hours researching every new form, deciding if it is worth a call, and typing it into the CRM. Fully automatic AI routing is fast but risky: unclear leads get guessed, broken or manipulated input can slip through, and an AI-written email can reach a real prospect without anyone reading it.

## Solution

For every new lead the workflow:

1. **Checks the input.** Only requests with the secret webhook key are accepted. Missing or invalid e-mail, empty forms and spam-length text are stopped before any AI call.
2. **Skips duplicates.** The same e-mail address (also in different upper/lower case) is processed only once.
3. **Reads the company website** and gives the text to the AI together with the form.
4. **Scores the lead with Claude** and gets a fixed JSON answer: industry, company size, fit score 0-100, confidence, reason, signals, red flags.
5. **Checks the AI answer.** If the answer is broken or incomplete, it never goes to the CRM.
6. **Routes the lead:**
   - clear good fit: HubSpot contact plus a Slack note to sales
   - clear poor fit: logged only
   - unsure (low confidence, score in the middle, bad AI answer, or an attempt to trick the AI): a person approves or rejects in Slack first
7. **Drafts a first reply** to every lead that reaches HubSpot. A person approves it in Slack before it is sent.
8. **Logs every step** in an n8n data table and **alerts in Slack** when an API call fails after 3 tries.

The ideal-customer description, score limits and AI model are settings in one node, so a client can change them without touching the logic.

## System

![architecture](docs/architecture.png)

| Part | Used here |
|---|---|
| Automation | n8n 2.43.7, self-hosted (local) |
| AI | Claude Opus 5.5 (`claude-opus-5-5`, effort `low`), JSON-schema output, checked again in the workflow |
| CRM | HubSpot (free account, service key) |
| Human review and alerts | Slack (approve / reject buttons) |
| E-mail | Gmail SMTP; in demo mode every reply goes only to a test inbox |
| Lead log | n8n data table `lead_log` |

Workflows in [`workflows/`](workflows/) (exported from n8n, no credentials):

| File | Purpose |
|---|---|
| `lead-qualifier.json` | The main workflow (62 nodes) |
| `error-alert.json` | Slack alert when the main workflow fails unexpectedly |
| `lead-report.json` | Read-only report endpoint used by the test runner |
| `setup-lead-log-table.json` | Creates the lead log table once |
| `test-reset-lead-log.json` | Empties the lead log before a test run |

## Outcome

Final test on 2026-10-21 and 2026-10-22 (level Critical; the pass rules were fixed before the run in [`evals/eval_config.yaml`](evals/eval_config.yaml)). All leads are fictional, and the expected route of each lead was written down before the run. 30 of the AI-scored leads were written by a separate session and kept sealed until this run, so the workflow was not tuned on them. All numbers below come from [`evals/RESULTS.md`](evals/RESULTS.md).

**Rate pass:** 125 leads, each sent 3 times, with no Slack clicks on purpose, so this pass measures only the AI routing. The Slack buttons are tested in the trigger pass below.

| Result | Number |
|---|---|
| AI-scored leads routed as expected in all 3 runs | **88 of 89** (allowed: at most 3 misses) |
| Of these, sealed leads the workflow was never tuned on | 29 of 30 |
| Code checks: broken input, duplicates, simulated broken AI answer, simulated API failure | 36 of 36 |
| Leads with no AI score | 0 |
| Reply sent without a person's approval | **0** |
| Lead in HubSpot without an allowed path | **0** |
| Attempt to trick the AI that reached "good fit" | **0** |
| Replies in the test inbox (none expected, because no reply was approved) | 0 |

**Trigger pass:** 41 leads; a person made a fixed list of Slack clicks (approve, reject or no click; then send or don't send the reply).

| Result | Number |
|---|---|
| Click paths tested | all 7, at least 5 leads each |
| Reply sent without a person's approval | **0** |
| Leads in the wrong end state | 0 |
| Replies in the test inbox | exactly the 12 expected |

Result of both passes: **PASS**. On this test set, the rate pass supports the claim "at least 90% of AI-scored leads are routed as expected".

The one miss: a lead from an existing client should go to a person for review; in 2 of the 3 runs the AI scored it as a poor fit and logged it.

The clicks in the trigger pass tested the buttons, not the quality of the leads or drafts; the quality of the reply drafts was not measured.

How the test works: [`tests/run_tests.py`](tests/run_tests.py) sends the leads to the workflow, a person answers the Slack messages, and the runner then compares the lead log with the contacts in HubSpot. Company websites are local mock pages ([`tests/mock_sites/server.py`](tests/mock_sites/server.py)); people and companies are fictional and use the reserved `example.com` domain. The broken AI answer and the API failure are **simulated** with test flags that only work when `allow_test_flags` is on.

### Limits

- Fictional leads only (3 runs of 125 leads and one trigger pass). It shows that the safety rules work; it is not an accuracy measure on real traffic.
- The duplicate check uses the e-mail address. Two forms with the same e-mail in the same second could both pass.
- In this local demo the Slack buttons are links that open a short confirmation page, and n8n does not record who clicked. On a hosted n8n (public HTTPS) the buttons work with one click inside Slack and record the approver.
- The test report reads up to 5,000 HubSpot contacts (50 pages of 100).
- Tested only on Windows 11 with a local n8n 2.43.7; not tested on macOS or Linux.

### Run it yourself

1. Install n8n (Node.js 20.19 to 24) and start it: `n8n start`.
2. Import the files in `workflows/` and run "n8n-lead-qualifier: setup lead_log table" once.
3. Create credentials in n8n: Anthropic, HubSpot App Token (service key with contact read/write), Slack API (bot token with `chat:write`, `channels:read`, `groups:read`), SMTP (optional), and two Header Auth credentials (header `X-Webhook-Key`, a long random value) for the form webhook and the report webhook. Select them in the nodes. The test scripts read the same two values from the environment variables `LEAD_QUALIFIER_KEY` and `LEAD_REPORT_KEY`; `python tools/n8n_api.py keys` creates both credentials and variables through the n8n API.
4. In the **Settings** node set `slack_channel`, `from_email` and `demo_inbox`; keep `demo_mode` on for tests. Publish the main, report and error workflows.
5. For the test: `python tests/mock_sites/server.py`, then `python tests/run_tests.py send`, answer the Slack messages, then `python tests/run_tests.py report tests/results/<run-file>.json`.

## Version Log

| version | date | change |
|---|---|---|
| 0.0 | 2026-10-16 | Scaffold |
| 0.1 | 2026-10-17 | First working build on local n8n; test run of 39 leads recorded |
| 0.2 | 2026-10-20 | Both webhooks need a secret key; ideal customer profile: any region, 1,000-5,000 employees go to review; workflows renamed |
