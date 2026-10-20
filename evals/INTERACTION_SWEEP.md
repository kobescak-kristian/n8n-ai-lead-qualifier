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
| I3 | Resend after the first form hit an AI error | Skipped as duplicate; the lead is recovered from the Slack alert | Case C04. **Known limit**: a resend does not retry |
| I4 | Same e-mail, different case and spaces | Duplicate | D02, C05 |
| I5 | Two errors in one form (bad e-mail and empty message) | `invalid_input`, all errors in the reason | B03 |
| I6 | Prompt injection on a lead the AI scores 70+ | `review`, never straight to HubSpot | A01, A02, S2H02, C08 (with broken AI answer), hold-out |
| I7 | Broken AI answer or AI error on any kind of lead (fit, low fit, injection, non-English) | Broken answer -> `review`; AI error -> `error` + Slack alert; the score never decides | X01, C06-C09; X02, C03, C10-C12 |
| I8 | Same company, different e-mails | Two separate leads (the key is the e-mail) | By design; out of scope for the gate |
| I9 | Two forms with the same e-mail at the same moment (double click on submit) | Both can pass the lookup before either is logged, so both are processed | **Known limit**, out of scope: the runner sends one lead at a time; n8n data tables have no lock |
| I10 | A Slack button clicked twice, or approve then reject | n8n resumes a waiting step once; the second click changes nothing | Trigger pass (see below), by hand |
| I11 | No click for 24 hours | The wait ends (`limitWaitTime` 24 h); expected: the "not approved" branch, nothing sent, nothing in HubSpot. Not verified in n8n 2.43.7 | **Out of scope** for the series (24 h wait); check once before go-live |
| I12 | Reviewer approves, then HubSpot fails | `crm_failed` + Slack alert, no reply drafted | Not simulated (no HubSpot fault flag); **out of scope**, shown once on 2026-10-17 smoke tests |
| I13 | Reply draft fails the check | `draft_failed` + Slack alert, no e-mail | Not simulated; **out of scope** |
| I14 | Lead already in HubSpot (existing contact) | Not tested: test e-mails are new in every run (`--tag`) | **Out of scope** |

## Trigger pass (CF1, CF2), by hand after the rate pass

The gate (`critical_failures.trigger_cases`) needs at least 5 leads per button path.
Planned, owner clicks in Slack:
- approve review + approve reply (5): lead in HubSpot, one e-mail each in the demo inbox;
- approve review + "Don't send" (5): lead in HubSpot, no e-mail;
- reject review (5): not in HubSpot, no e-mail;
- no click (5): not in HubSpot, no e-mail, still waiting at report time;
- I10: on 2 of these, click the same button again after the first click: nothing changes.

## Code-check minimums

With `tests/leads-code.json` the visible set alone has invalid 6, duplicate 5,
broken AI answer 5, AI error 5 (`python tests/check_cases.py tests/leads.json
tests/leads-set2.json tests/leads-code.json`), so the gate minimum of 5 each does not
depend on the sealed hold-out.

## Still to do before the series (not part of this sweep)

- A grader that reads the 3 run files and applies the gate formula (case passes only
  if routed as expected in all 3 runs; CF1/CF2 from the report); today
  `tests/run_tests.py report` grades one run.
- Written preflight `evals/PREFLIGHT.md` (build-checks (c)).
- Red teams: gate red team and build red team by fresh sessions (level Critical).
