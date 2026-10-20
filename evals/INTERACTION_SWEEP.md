# Interaction sweep — n8n-lead-qualifier

Eval-gate build check (a), level Critical, done 2026-10-20 before the first gated
run, on the workflow in `workflows/lead-qualifier.json` (d3088ca). Question asked
for every check and route: "what if a second item or a second field touches this?"
Each real interaction is a visible case (expected result committed before any run)
or is named here as out of scope or a known limit.

How the workflow decides (from the code): `Validate lead` runs first; an invalid
form is logged with an empty `lead_key`, so it does not take the e-mail. A valid
form is looked up by e-mail (`Find earlier lead`); the first valid form writes its
`lead_key` before the AI call (`Log: new lead`), so every later form with that
e-mail is a duplicate, whatever happened to the first one.

| # | Interaction | Expected behaviour | Covered by |
|---|---|---|---|
| I1 | Invalid form, then a corrected form with the same e-mail | Second form is processed, not a duplicate | Case C02 then C03 (`tests/leads-code.json`) |
| I2 | Duplicate e-mail that is also invalid | `invalid_input` (validation runs first) | B02/B03 pattern; no extra case needed |
| I3 | Resend after the first form hit an AI error | Processed again: `Row: AI call failed` clears `lead_key` (first draft of this sweep said "duplicate"; corrected after gate red team finding 13) | Case C03 then C04 (C04 also flagged, so it ends in `error`, not `duplicate`) |
| I4 | Same e-mail, different case and spaces | Duplicate | D02, C05, C13 |
| I5 | Two errors in one form (bad e-mail and empty message) | `invalid_input`, all errors in the reason | B03 |
| I6 | Prompt injection on a lead the AI scores 70+ | `review`, never straight to HubSpot | A01, A02, S2H02, C08 (with broken AI answer), hold-out |
| I7 | Broken AI answer or AI error on any kind of lead (fit, low fit, injection, non-English) | Broken answer -> `review`; AI error -> `error` + Slack alert; the score never decides | X01, C06-C09; X02, C03, C04, C10-C12 |
| I8 | Same company, different e-mails | Two separate leads (the key is the e-mail) | By design; out of scope for the gate |
| I9 | Two forms with the same e-mail at the same moment (double click on submit) | Both can pass the lookup before either is logged, so both are processed | **Known limit**, out of scope: the runner sends one lead at a time; n8n data tables have no lock |
| I10 | A Slack button clicked twice, or approve then reject | n8n resumes a waiting step once; the second click changes nothing | Trigger pass (see below), by hand |
| I11 | No click for 24 hours | The wait ends (`limitWaitTime` 24 h); the code writes `review_timeout` / `reply_timeout` on the "not approved" branch: nothing sent, nothing in HubSpot. Not run end to end | **Out of scope** for the series (24 h wait); check once before go-live |
| I12 | Reviewer approves, then HubSpot fails | `crm_failed` + Slack alert, no reply drafted | Not simulated (no HubSpot fault flag); **out of scope**, shown once on 2026-10-17 smoke tests |
| I13 | Reply draft fails the check | `draft_failed` + Slack alert, no e-mail | Not simulated; **out of scope** |
| I14 | Lead already in HubSpot (existing contact) | Not tested: test e-mails are new in every run (`--tag`) | **Out of scope** |

## Trigger pass (CF1, CF2)

Committed as `tests/leads-trigger.json` (gate red team finding 12): 35 leads, 7 click
paths x 5 (review approve + Send, review approve + Don't send, review reject, review no
click, high_fit + Send, high_fit + Don't send, high_fit + no click), I10 double clicks on
TA1 and TC1. `python evals/grade_series.py clicks <run>` prints the clicks;
`python evals/grade_series.py trigger --inbox-replies N <run>` grades them.

## Code-check minimums

With `tests/leads-code.json` the visible set alone has invalid 6, duplicate 5,
broken AI answer 5, AI error 6 (`python tests/check_cases.py tests/leads.json
tests/leads-set2.json tests/leads-injection.json tests/leads-code.json`), so the gate minimum of 5 each does not
depend on the sealed hold-out.

## Still to do before the series (not part of this sweep)

- Done 2026-10-20: `evals/grade_series.py` (rate and trigger pass, INVALID RUN), hardened
  after the gate red team (`evals/redteam-gate-2026-10-20.md`); HubSpot paging.
- Model choice (llm-bench study), applied with `tools/n8n_api.py apply` together with
  the `model_used` change; then a build red team (level Critical).
- R2: the visible set passes 3 full development runs in a row at gate thresholds.
- Written preflight `evals/PREFLIGHT.md`, dry run of the frozen commit.
