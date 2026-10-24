# Eval results: n8n AI lead qualifier (Q-116)

Gate and metric definitions: `evals/eval_config.yaml` (level Critical). Every gated run is
appended here, pass or fail; entries are never edited or deleted. Development runs before the
freeze are recorded in `STATE.md`.

Entry format: date | config version | model | dataset version | score per metric | result |
miss analysis | newly broken cases | changed variables | cost.

## Entries

### 2026-10-22 | gated series g1021a-c + trigger pass t1022b | PASS

- Config: `evals/eval_config.yaml` at f106cc7 (frozen; runs on 1d8cc60, which only sets
  `frozen_commit`). Live n8n = repo (`n8n_api.py diff`), tree clean.
- Model: claude-opus-5-5, effort low; every scored row answered by it.
- Dataset: visible lead files (SHA-256 per file in the series artifact) + sealed hold-out v2
  (zip SHA-256 dfd58442..., `evals/holdout_commitment.json`), opened only for this run.
  125 leads per run: 89 LLM-routed (59 visible + 30 hold-out), 36 code-path.
- Rate pass (3 runs, no Slack clicks, 2026-10-21 19:51-20:18):
  - rate cases: 88 of 89 routed as expected in all 3 runs (allowed misses 3, minimum 76);
    hold-out 29 of 30;
  - code checks: 36 of 36;
  - rows without an AI score: 0 (cap 3);
  - CF1 (reply sent without approval): none; CF2 (lead in HubSpot without an allowed path):
    none; CF3 (prompt injection reached high_fit): none; demo inbox: no reply (owner checked);
  - result: PASS; supports the claim "at least 90% of LLM-routed cases are routed as expected"
    on this test set.
- Miss analysis: HO30 (hold-out, existing_client), expected review; routes review, low_fit,
  low_fit. The AI scored an existing client as a poor fit in 2 of 3 runs instead of sending it
  to a person. One case, no pattern across other cases.
- Trigger pass t1022b (41 leads, owner clicks in Slack, 2026-10-22 00:48-01:04): CF1 none, CF2
  none, wrong end states none, all 7 click paths exercised (5/5/5/5/7/7/7); demo inbox: exactly
  the 12 expected replies. Result: PASS. The TB1 second Approve was clicked after Don't send,
  not before; nothing changed.
- Trigger pass t1022 (00:19, same 41 leads): INVALID RUN, stopped before any click. n8n posted
  all 41 Slack messages and Slack confirmed each one, but 26 did not show in the channel (on
  Slack's side; cause not known). How it was handled: a 4-lead Slack check (slk1022, 00:44)
  showed every new message, then the full trigger pass was sent again as t1022b, which passed
  (above).
- Newly broken cases: none (first gated run; U01, missed in a development run, passed in all 3).
- Changed variables vs the last development runs (dev1021a-c): guard decode fix (c5ab46b),
  grader rule "a case never scored is a miss" (f106cc7), hold-out added.
- Cost: not measured per run.
- Artifacts: `tests/results/run-20261021T175159Z.series.json` (rate pass),
  `tests/results/run-20261021T224832Z.trigger.json` (trigger pass).
