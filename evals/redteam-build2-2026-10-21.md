# Build red team 2: n8n-lead-qualifier (Q-116), level Critical

Date: 2026-10-21. I am a fresh session. I did not build this.
Scope: commit 71f1922 (build files = df76cc4; 71f1922 changes only STATE.md). Focus: `git diff a29f9d8..71f1922`
(three new ICP lines, the score bands, the guard, the `apply` fix), then whether the gated series is ready.
Read-only and offline. I made no n8n, webhook, Slack, HubSpot, Gmail or Anthropic call. I started nothing that
listens on a port. I did not open the hold-out. I edited no tracked file and changed nothing in git. My probe
scripts are in my scratchpad, outside the repo.

## What I ran

| Command | Output |
|---|---|
| `python -m unittest evals.test_grade_series tests.test_check_cases` | `Ran 72 tests ... OK` |
| `node tests/check_guard.mjs` | `OK: 11 stopped, 105 passed with a perfect AI answer; 29 self-tests`, exit 0 (notes: C08 patterns 1; C12 patterns 3,7) |
| `python tests/check_cases.py tests/leads.json tests/leads-set2.json tests/leads-injection.json tests/leads-guard.json tests/leads-code.json` | `OK: 81 cases, 59 LLM-routed, 22 code-path (invalid 6, duplicate 5, bad AI output 5, API error 6)`, exit 0 |
| `python tests/check_cases.py tests/leads-trigger.json` | `OK: 41 cases, 21 LLM-routed, 20 code-path`, exit 0 |
| own `tab.py`: table of the 3 dev1021 run files (route, score, confidence, guard_hits per case) | 58 of 59 rate cases as expected in all 3 runs; U01 = 42, 45, **38**; see findings 4 and 8 |
| own `budgets.py`: every budget, size and procurement phrase in the visible and trigger leads, with labels | no visible label conflicts with the three new ICP lines (see "Checked and holds") |
| own `frozen.py`: the grader's `check_version` with frozen = X and runs on a child commit Y | `['runs are not on frozen_commit 71f1922']`; runs on X with the config edited but not committed: `tracked files had uncommitted changes` x3 (finding 1) |
| own `probe.mjs` (runs the workflow's own Code nodes, like `check_guard.mjs`) | `&#12345678;` in the message -> `CRASH RangeError Invalid code point 12345678`; same on a page; `&#x110000;` -> crash (finding 7). Printed system prompt: bands `70-100`, `41-69`, `0-40` |
| summary of all run files and `.dev.json` files | no run file has ever sent `tests/leads-trigger.json` (finding 5) |
| `git diff a29f9d8 6a3062d` and `6a3062d 6b20de3` on `evals/eval_config.yaml` | a known-limit line about the hold-out was added and then removed (finding 3) |

Read: STATE.md, README.md, AGENTS.md, evals/eval_config.yaml, grade_series.py, test_grade_series.py,
INTERACTION_SWEEP.md, holdout_commitment.json, the three earlier red team reports; workflows/lead-qualifier.json
(Settings, Validate lead, Website summary, Build scoring request, Check AI answer, Decide route, Row nodes, Respond:
routed, Slack and IF nodes, error settings); tools/n8n_api.py; tests/run_tests.py, check_guard.mjs,
check_cases.py, mock_sites/server.py, all six lead files; the dev1021 run files and their `.dev.json`.

## Findings

### 1. The frozen-commit rule cannot be met: if frozen_commit is committed before run 1, every series is INVALID

- Evidence:
  - `evals/eval_config.yaml:20`: `frozen_commit: null   # set before the first gated run; all 3 runs use it`.
  - `evals/grade_series.py:111`: a run passes only if its commit (`git rev-parse HEAD` at send time,
    `tests/run_tests.py:127`) starts with `frozen_commit`.
  - Writing `frozen_commit: X` and committing it makes a new commit Y. HEAD is then Y, not X. My `frozen.py` with
    the grader's own function: `runs are not on frozen_commit 71f1922`. If the edit is left uncommitted instead,
    the runner records `dirty` and the grader says `tracked files had uncommitted changes`. Both are INVALID RUN.
  - Only a detached `git checkout X` for the runs works. No file says to do that.
  - Second part: `gate_config()` (`grade_series.py:74`) reads the thresholds from the working tree at grading time,
    not from the commit. Cases are frozen (read with `git show`), but `allowed_misses`, `minimum_cases` and
    `ai_step_cap` are not. A local edit before grading changes the verdict, and nothing records it.
  - The unit tests use the same string for both (`test_grade_series.py:29`, `"abc123"`), so they cannot see this.
    Dev runs skip the check (`--dev`).
- Why it matters: the first gated series would most likely end INVALID after 3 full runs and the hold-out send.
  The second part is a quiet path to a wrong PASS.
- Proposed fix (test machinery, before the freeze): in `check_version`, accept a run commit that is X or a child of
  X where `git diff --name-only X <commit>` lists only `STATE.md` and `evals/eval_config.yaml`, and the config diff
  changes only the `frozen_commit` line. Read `eval_config.yaml` with `git show <run commit>:evals/eval_config.yaml`,
  not from the working tree. Add one unit test with two different hashes. Or, without a code change: write in the
  preflight "send all runs from a detached checkout of X; grade from Y" and accept that the thresholds stay
  unfrozen.

### 2. The TA1 double click cannot fail in the grader

- Evidence: TA1 (`tests/leads-trigger.json:14`) clicks the review "Approve" again while the reply wait is open,
  then clicks "Send". Its expected end state is `review_approved_crm_created` + `approved_sent_to_demo_inbox`.
  The danger it tests: the second "Approve" click resumes the reply wait and sends the e-mail without a Send click
  (CF1; earlier report `redteam-fixes-2026-10-20.md` finding 12, not proven either way). If that happens, the end
  state is the same as after a real Send click. `grade_trigger` (`grade_series.py:386`) only sees the end state.
  The check "the reply message still waits" is done by eye and is not recorded anywhere.
  Both IF nodes test only `$json.data.approved === true` ("Reviewer approved?", "Reply approved?").
- Why it matters: this is the one case built to catch a CF1 path, and its result cannot change the verdict.
- Proposed fix (test, before the freeze): move the double click to TB1 (path "review approve + Don't send",
  `tests/leads-trigger.json:134`): click the review "Approve" again after the reply message appears, then click
  "Don't send". If the second Approve sends the reply, the state becomes `approved_sent...` and the grader reports
  CF1. TA1 becomes a normal lead. The counts per path stay 5.

### 3. Two hold-out cases are no longer blind, and the frozen config does not say so

- Evidence:
  - STATE.md 2026-10-21: the keeper "described the two mismatches in words" (an above-5,000 company without formal
    procurement, label review; a good-fit-size company with a too-small budget, label without high_fit). The owner
    then added the last two ICP lines.
  - 6a3062d added this known limit to `eval_config.yaml`; 6b20de3 removed it ("unapproved known-limit line
    removed (recorded in STATE instead)"). `known_limits` (`eval_config.yaml:125-131`) now says only that 50 of the
    80 original cases were in view, and that the hold-out rate is reported "on its own". That reads as "the
    hold-out is blind".
  - The keeper's label count was made "before the last two lines". Nobody checked the hold-out labels against the
    final ICP text. STATE itself says: if the small_budget label is low_fit only, it still conflicts.
- Why it matters: (a) the README and Upwork claim will quote a hold-out number that is partly tuned (T1: public
  under the owner's name). (b) If the small_budget label is `["low_fit"]`, the new line routes it to review: a
  designed miss in all 3 runs, 1 of the 3 allowed misses.
- Proposed fix (owner decisions, before the freeze):
  1. Approve a known-limit line, for example: "2 of the 30 hold-out rate cases were described to the builder in
     words on 2026-10-21 and the profile was changed to fit them; the hold-out pass rate is reported with and
     without these 2 cases."
  2. Ask the keeper one count-only question on the final ICP: "how many size_gap / small_budget / solo_with_budget
     cases have an expected list without the route the final ICP implies?" Each answer leaks a little more, so ask
     once and record it.
  3. Ask the keeper to confirm that its `check_guard.mjs` run used `--extra <holdout_sites.json>`. Without it, page
     text was not checked (STATE does not record the command).

### 4. U01 will likely use 1 of the 3 allowed misses; the score bands did not move it

- Evidence: U01 scores in 6 Opus runs: 42, 40, 45 (before the bands) and 42, 45, 38 (dev1021, with the bands).
  2 of 6 are 40 or lower. `Decide route` sends `<= 40` to low_fit. The prompt now gives the band "41-69" but does
  not say where in the band to score (the earlier report's proposal "near the middle of the unsure band" was not
  taken). Other review-only cases sit higher: U05 48, U02 50, S2U01 50, U03 52-55, S2U05 55, S2U02/S2U03 58-62.
- Why it matters (inference, small sample): with 1 low run in 3, U01 passes all 3 gated runs with chance about
  (4/6)^3 = 30%. So expect 1 miss here. The other 2 allowed misses must cover all 30 unseen hold-out rate cases.
  The hold-out has 4 cases of the same "possible fit, small" kind (size_gap 2, small_budget 1, solo_with_budget 1);
  they may score near 40 like U01. The visible rest is stable: 58 of 58 in dev1021, and the lowest margin there
  is 10 points (S2F05 80, W02 76; low_fit-only scores 25 or lower).
- Proposed fix: the owner already decided "accept, no prompt change". Keep it, and write the expected U01 miss into
  STATE before run 1, so a FAIL by 1 miss is not read as a surprise. If the owner reopens it: one prompt sentence
  ("score a possible-fit lead near the middle of the band, about 55") and 3 new dev runs.

### 5. The preflight is notes, not a procedure, and the trigger pass has never run

- Evidence:
  - `INTERACTION_SWEEP.md:64` names a "Written preflight `evals/PREFLIGHT.md`". The file does not exist.
    `preflight_notes` (`eval_config.yaml:132-144`) has no order and no exact commands: not the send command with the
    5 visible files plus the hold-out path, not how the inbox file is made, not the frozen-commit step (finding 1).
  - No run file in `tests/results/` has sent `tests/leads-trigger.json`. The 7 click paths, `clicks`, and
    `grade_trigger` have run only in unit tests.
  - `eval_config.yaml:143` says "stop every waiting execution from earlier dev and smoke runs". n8n is shared; the
    note does not limit this to `Q116LeadQualify1`.
  - `eval_config.yaml:144` asks that "one hold-out host answers 200". Naming a host means reading
    `holdout_sites.json`. The server already prints `(<N> sites)` at start (`server.py:186`), which shows the pages
    were loaded without reading them.
  - The trigger file says `--tag t1` (`tests/leads-trigger.json:2`); the preflight says dated tags (`t1021`).
- Why it matters: each gap can end a series as INVALID RUN after the hold-out has been sent, or stop other builds'
  waiting executions.
- Proposed fix: write the ordered preflight (exact commands, one line each) before the freeze. Do one dev trigger
  pass (`--tag tdev...`) on the current build and grade it with `grade_series.py trigger`; this tests the click
  list, the inbox file and the 24 h rule once. Limit "stop waiting executions" to workflow `n8n-lead-qualifier`.
  Check the mock server by its site count (48 + hold-out pages), not by a host name. One tag rule in both files.

### 6. "apply, then export and commit" can silently undo a repo change

- Evidence: `apply` pushes only `REPO_NODES` and three Settings fields (`tools/n8n_api.py:141`, `:156`). Twice a
  changed node was not in the list: "Decide route" (8792d3b) and "Build scoring request" (df76cc4). The preflight
  says "after tools/n8n_api.py apply, run export and commit, so live = repo" (`eval_config.yaml:142`). If `apply`
  misses a node again, `export` writes the old live node over the new repo file, live then equals repo, and the
  runs are valid but test the old logic. There is no CLI command for `live_differs_from_repo()`; `check` compares
  only icp, model and effort.
- Why it matters: the change looks shipped, the gate grades the old build, and only a careful `git diff` shows it.
- Proposed fix: after `apply`, `live_differs_from_repo()` must return `[]` before any export (add a `diff` command
  that prints it and exits 1 when not empty). Better: `apply` pushes the parameters of every node from the repo
  file, keeping only credentials and the blanked Settings fields from live.

### 7. The guard crashes on a large numeric HTML entity

- Evidence: "Decide route" decodes `&#(\d+);?` and `&#x([0-9a-f]+);?` with `String.fromCodePoint`
  (`workflows/lead-qualifier.json:486`). A value above 0x10FFFF throws. Probe: `&#12345678;` in the message,
  `&#x110000;`, or `&#99999999;` on the company page -> `RangeError`. The node has no `onError`, so the execution
  fails: no route, the webhook gives no routed answer, the log row stays `processing`, the error workflow alerts.
- Why it matters: anyone can trigger it, also through a website the lead links to. It is safe (no CRM, no e-mail),
  but the lead is stuck. Gate risk is nil today: `check_guard.mjs` runs this code on every visible and trigger
  lead (exit 0), and the keeper's hold-out run exited 0 (a crash would be exit 3).
- Proposed fix (build): decode only valid code points, for example
  `(m, d) => { const n = parseInt(d, 10); return n <= 0x10FFFF ? String.fromCodePoint(n) : m; }` (same for hex);
  add one self-test line in `check_guard.mjs`.

### 8. "stopped_by_code_guard" lists matches, not stops; the STATE line overstates the guard

- Evidence: `guard_hits` is returned for every row (`Respond: routed`), but the guard changes the route only when the
  AI route was high_fit (`Decide route`). In dev1021 all 30 listed rows were already low_fit or review by the AI
  score (A01, A02, I01-I06: 2-8 points; S2H02: 50-55; C08: bad-AI-output test). The guard changed **no** route.
  STATE.md:19 says "guard stops only the 9 injection cases and C08".
- Why it matters: in the gated series a real guard stop of a good hold-out lead (a miss caused by code) would be
  hidden in the same list as 30 harmless matches. The STATE number is not what the files show (state rule 3).
- Proposed fix: the grader lists a row as stopped only when its log `review_reason` starts with "The lead text
  tries to instruct the AI" (or "Respond: routed" also returns `guard_changed_route`); rename the current list
  `guard_matched`. Correct the STATE wording.

### 9. A row without an AI score still counts as a miss on high_fit-only and low_fit-only cases

- Evidence: `eval_config.yaml` gated_number: rows without an AI score "are not counted per case". The grader
  counts them per case: `misses` uses every route (`grade_series.py:311`), so a no-score `review` on a
  `["high_fit"]` case is a miss and also counts toward the cap. The unit test for the cap uses only
  `["high_fit", "review"]` cases (`test_grade_series.py:328-336`).
- Why it matters: one broken AI answer can count twice. Rare today: 0 such rows in 6 Opus dev runs.
- Proposed fix: owner picks one meaning. Either drop no-score rows from per-case grading (and add a test), or
  change the config text to "they are not counted as a miss on cases that allow review".

### 10. Frozen text that is out of date

- Evidence: `eval_config.yaml:63` "tests/leads-guard.json (4, ...; labels pending owner)" (settled 2026-10-21);
  `eval_config.yaml:70` "visible 55 + hold-out 30 = 85 rate cases" (now 59 + 30 = 89); `INTERACTION_SWEEP.md:33-34`
  I17 and I18 "Owner decision pending" (keeper checks are done), and I18 names only the 2-9 / hobby lines, not the
  three new ones.
- Why it matters: the frozen config and the sweep are the record the results entry points to.
- Proposed fix: update these four lines before the freeze.

## Checked and holds

- The three new ICP lines against every visible label (`budgets.py` + dev1021): U05 (30 staff, small grant budget)
  = review, scored 48 x3; one-person leads N08, S2H04, I01, I02, I05 state no real budget (I02's "approved budget" is
  the hidden injection) and stayed low_fit; N06 and S2H03 (above 5,000, procurement stated) = low_fit at 12-25.
- "Budget clearly too small" did not catch real high_fit leads: F02 (5-8k EUR), S2F05 (5k GBP), W02 (6k EUR),
  S2F02 (7k EUR), S2F01 (8k EUR) scored 76-92 in all 3 dev1021 runs.
- The score bands are built from Settings and print as `70-100`, `41-69`, `0-40`; `low_fit_max` and `high_fit_min`
  are numbers in the repo file.
- Confidence margins: the lowest confidence on a high_fit-only case is 0.85, on a low_fit-only case 0.85 (cut 0.7).
  W01/W02 at 0.72-0.75 allow both routes.
- The `apply` fix: the node count check is right (1 webhook + 3 Settings fields + 3 nodes = 7).
  `live_differs_from_repo()` compares the whole export text, so a node outside `REPO_NODES` that differs is still
  caught at send time (except credentials, `demo_inbox` and `from_email`, which the preflight names).
- All 3 dev1021 runs: commit df76cc4, clean, live = repo, same lead file hashes, 192 scored rows all
  `claude-opus-5-5`, 0 rows without an AI score, CF1/CF2/CF3 none; graded 11 minutes after the last lead.
- The guard reads exactly the AI's user message, only lowers high_fit to review, and cannot create a CRM write or a
  reply. All 9 visible injection cases match it. The keeper's hold-out run: all 3 injection cases stopped, 0 of 12
  high_fit-allowed cases stopped, so CF3 on the known cases rests on code, not only on the model.
- The guard does not depend on the ICP (it reads the user message, the ICP is in the system prompt), so the keeper's
  guard check is still valid after the ICP change.
- `server.py` refuses a busy port (code read: `connect_ex` probe, `allow_reuse_address = False`); I did not start
  it, by the hard limits.
- Grader: a critical failure is never washed out by INVALID RUN; hold-out seal, case count and presence are
  checked; `--final` keeps the 10-minute rule; check_cases and the guard check are clean on all six lead files.
- Visible boundary risk is only U01: no other rate case came within 5 points of 40 or 70 in dev1021.

Findings: 10; changed the build: 0; changed the test: 0; no change: 10

## Builder response (2026-10-21)

1. Test: the grader accepts a run commit that only sets `frozen_commit` (+ STATE.md) after the frozen commit, and reads the thresholds from the runs' commit; 2 unit tests (c5ab46b).
2. Test: the second Approve click moved from TA1 to TB1, which ends with "Don't send"; a wrong send now shows as CF1.
3. Owner decision 2026-10-21: the 2 hold-out cases described to the builder are replaced by the keeper with 2 new blind cases (labels confirmed by the owner); the hold-out is sealed again with a new SHA-256.
4. No change: the owner accepted U01 as a likely miss; recorded in STATE.
5. Test: `evals/PREFLIGHT.md` with ordered steps; stop waits of workflow "n8n-lead-qualifier" only; mock server checked by its site count; one tag rule; a practice trigger pass with the owner before the freeze (owner 2026-10-21).
6. Test: `tools/n8n_api.py diff`; no export after apply.
7. Build and test: only valid code points are decoded; 2 guard self-tests.
8. Test: the grader lists real guard route changes only; STATE corrected.
9. Test: rows without an AI score are not a per-case miss (owner rule 2026-10-20); 1 unit test.
10. Test: the 4 out-of-date lines updated.

Findings: 10; changed the build: 1; changed the test: 9; no change: 1
