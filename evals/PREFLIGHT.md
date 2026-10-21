# Preflight: gated series (level Critical)

Ordered steps for the final gated series under `evals/eval_config.yaml`. One line per step, in this order.
Run every command from the repo root. A step that fails stops the series: fix it first.
Source: eval-gate build checks; build red team 2 (`evals/redteam-build2-2026-10-21.md`, finding 5).

## A. Before the freeze (no n8n)

1. Owner decisions for the open red team findings are recorded in STATE.md.
   Optional, before step 3 (owner decision 2026-10-21, build red team 2 finding 5): a practice trigger pass on the
   current build with the owner's Slack clicks (a `tdev<date>` tag; steps 18-21 without the gate), graded with
   `grade_series.py trigger`. It tests the click path before the freeze; its result does not count for the gate.
2. Offline checks, all OK:
   - `python -m unittest evals.test_grade_series tests.test_check_cases`
   - `node tests/check_guard.mjs` (exit 0)
   - `python tests/check_cases.py tests/leads.json tests/leads-set2.json tests/leads-injection.json tests/leads-guard.json tests/leads-code.json`
   - `python tests/check_cases.py tests/leads-trigger.json`
   - `python .githooks/validate_artifacts.py .`
3. The build commit X is committed and has a checkpoint review; the owner says "commit".

## B. Freeze

4. Write `frozen_commit: <X, 7 characters>` in `evals/eval_config.yaml` and one STATE line, and commit (commit Y).
   Y may change only that line and STATE.md: the grader accepts Y and reads the thresholds from Y.
5. `git status --porcelain --untracked-files=no` prints nothing (run files are untracked on purpose).

## C. n8n slot (exclusive)

6. Book n8n: an IN USE line in the shared `n8n-usage.md`, start messages to the other builds (session list at the top
   of that file). Exclusive for the whole series.
7. `python tools/n8n_api.py apply`, then `python tools/n8n_api.py diff` must say "live = repo" (exit 0).
   Do not run `export` after `apply`: if `apply` missed a node, an export would write the old live node over the repo.
8. Live Settings `demo_inbox` and `from_email` are filled (the export blanks them, so `diff` cannot see them):
   open the Settings node of workflow "n8n-lead-qualifier" once in the n8n editor.
9. Stop old waits: n8n Executions, filter workflow **"n8n-lead-qualifier" only**, status Waiting, stop them all.
   Never touch other builds' executions. Note the time.
10. Mock server: `netstat -ano | findstr :8099`; stop every listed PID (`Stop-Process -Id <pid>`).
11. Unzip the sealed hold-out (`holdout.zip`, owner's q116-holdout folder) into a new temporary folder. The builder
    passes only the paths and does not read the files.
12. Start `python tests/mock_sites/server.py --extra <tmp>\holdout_sites.json` in the background. It prints
    "(N sites)": N must be above 48 (48 repo pages + the hold-out pages). `netstat -ano | findstr :8099` shows
    exactly one LISTENING line.
13. Dry run: `python tests/run_tests.py send --leads tests/leads-guard.json --tag dry<date>`. The run file shows
    commit Y, `dirty: false`, `live_differs_from_repo: []`, model `claude-opus-5-5`, 4 rows, each with a route. Not graded.

## D. Rate pass (3 runs, nobody clicks in Slack)

14. Note the time (start of the inbox window). Nobody clicks any Slack button until step 18.
15. Three runs, each with a new dated tag (for example g1021a, g1021b, g1021c), all within 24 hours of the first lead:
    `python tests/run_tests.py send --leads tests/leads.json --leads tests/leads-set2.json --leads tests/leads-injection.json --leads tests/leads-guard.json --leads tests/leads-code.json --leads <tmp>\holdout.json --tag g1021a`
16. At least 10 minutes after the last lead: the owner searches the demo inbox for "[DEMO for" replies since step 14
    and writes one subject per line into an inbox file (an empty file when there are none).
17. `python evals/grade_series.py rate --inbox-addresses <file> --holdout-zip <zip> <run A> <run B> <run C>`.
    The numbers go to the owner before anything records them.

## E. Trigger pass (one run, a person clicks)

18. Stop the rate-pass waits (step 9 again, workflow "n8n-lead-qualifier" only). Note the time.
19. `python tests/run_tests.py send --leads tests/leads-trigger.json --tag t1021` (a new dated tag).
20. `python evals/grade_series.py clicks <run T>` prints the clicks. The owner makes exactly these clicks in Slack,
    including the second clicks of TB1 and TC1.
21. At least 10 minutes after the last click: inbox file for the window since step 18; then, within 24 hours of the send:
    `python evals/grade_series.py trigger --inbox-addresses <file> <run T>`.

## F. Close

22. Stop the mock server; send "n8n free" and mark the IN USE line DONE.
23. Delete the temporary hold-out folder after both passes are graded.
24. Results entry in `evals/RESULTS.md`, pass or fail, and STATE, with owner-approved wording.
