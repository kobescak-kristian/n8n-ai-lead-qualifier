# Bench tasks: lead routing

`lead-route.jsonl` is the task file for the lead-qualifier model study. It is
consumed by a separate benchmark tool
(session 3 of the study) with `--tasks` pointing at this file:

```
python bench.py quality --config config.yaml --tasks <this repo>/tests/bench/lead-route.jsonl --runs 3
```

## What is in the file

One line per lead that reaches the AI: 50 tasks, 30 from `tests/leads.json`
(set 1) and 20 from `tests/leads-set2.json` (set 2). Leads that never reach
the AI are left out: broken input, duplicates and the two simulated failures.

Each task has:

| Field | Content |
|---|---|
| `id` | lead id from the test set |
| `set`, `category`, `website_status` | for analysis only; the benchmark ignores them |
| `system` | the exact system prompt the workflow's "Build scoring request" node builds, with the Settings node's values (company name, ICP) substituted |
| `prompt` | the exact user message that node builds: the cleaned lead form as JSON (without the internal `source` field) and the website block with its status and the mock site's text |
| `check` | `{"type": "route", "value": [...]}`: the expected route(s); the benchmark applies the workflow's "Decide route" rule to the model's JSON answer |

`system` and `prompt` were not retyped. They were produced by running the
workflow's own Code nodes ("Validate lead", "Website summary", "Build scoring
request") from `workflows/lead-qualifier.json` on each test lead, with the
website fetched from `tests/mock_sites/server.py` the same way the workflow
fetches it (same base URL, same 8-second timeout). Unreachable sites (W01,
W02) therefore show `status="unreachable"` exactly as the live run saw them.

`output-schema.json` holds the JSON schema the workflow passes to the
Anthropic API as `output_config.format`, plus the model, effort and routing
thresholds from the Settings node. The system prompt does not describe the
output format; the workflow relies on that schema. A fair benchmark run must
enforce the same schema (the benchmark's per-model `extra` body fields can carry
it), or a model may answer in prose and fail the format check for the wrong
reason.

## Labels

Every expected route was reviewed one lead at a time and settled by the
owner on 2026-10-19. Before that date the set 1 labels were a Claude draft
(2026-10-16) that the owner had not reviewed. Set 2 was drafted and settled
in the same session, before any run. The review changed four set 1 labels
(B05, A01, A02, B07, each narrowed from two acceptable routes to one); the
reasons are in the `note` fields of the test sets.

## Rebuilding

The file is regenerated, not edited by hand. If a test set, the Settings
node or a Code node changes, rebuild it with the mock sites running:

```
python tests/mock_sites/server.py
node tests/bench/build_tasks.mjs
```

`build_tasks.mjs` loads the Code nodes from the exported workflow and runs
them; it contains no copy of the prompt text.
