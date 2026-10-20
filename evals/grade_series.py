"""Grade a gated series (3 runs) against evals/eval_config.yaml.

    python evals/grade_series.py tests/results/run-A.json tests/results/run-B.json tests/results/run-C.json

Run it after the 3 rate passes, before anyone clicks a Slack button. It reads the
3 run files from tests/run_tests.py send and asks the report webhook once for the
lead log and the HubSpot e-mails (key from LEAD_REPORT_KEY, or a hidden prompt).

Gate formula: PASS iff rate cases >= 76 AND misses <= 3 AND no critical failure
AND every code check passes. A rate case (routed by the AI) passes only when its
first route is in its expected list in all 3 runs. Code-path cases must pass in
every run. Critical failures in a rate pass (no clicks):
  CF1 a reply was sent (reply_status approved_sent...) although nobody approved;
  CF2 a test lead is in HubSpot without high_fit or a reviewer approval.
The demo inbox count (0 replies expected) is checked by hand and noted in the
results entry. The script stops (exit 2) when the HubSpot list was cut off,
because then CF2 cannot be checked.
Writes tests/results/series-<first run>.json; exit 0 = PASS, 1 = FAIL.
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "tests"))
import run_tests  # noqa: E402

CODE_PATH = {"broken_input", "duplicate", "simulated_bad_ai_output", "simulated_api_error"}
MIN_RATE_CASES, MAX_MISSES, RUNS = 76, 3, 3
ALLOWED_CRM = {"crm_created", "review_approved_crm_created"}


def grade(runs, report):
    """runs: list of run dicts; report: dict from the report webhook. Returns the result dict."""
    problems = []
    if len(runs) != RUNS:
        problems.append(f"need {RUNS} run files, got {len(runs)}")
    tags = [r.get("tag") for r in runs]
    if None in tags or len(set(tags)) != len(tags):
        problems.append(f"each run needs its own --tag, got {tags}")
    id_lists = [[row["id"] for row in r["rows"]] for r in runs]
    if any(ids != id_lists[0] for ids in id_lists):
        problems.append("the runs did not send the same cases in the same order")
    if report.get("hubspot_truncated"):
        problems.append("HubSpot list cut off at one page: CF2 cannot be checked")

    log = {str(r["id"]): r for r in report.get("log", [])}
    crm = {e.strip().lower() for e in report.get("hubspot_emails", [])}
    cases = {}
    cf1, test_emails, allowed = [], {}, set()
    for n, run in enumerate(runs, 1):
        for row in run["rows"]:
            c = cases.setdefault(row["id"], {"category": row["category"], "expected": row["expected"], "routes": []})
            c["routes"].append(row["route"])
            entry = log.get(str(row.get("log_id")), {})
            if str(entry.get("reply_status", "")).startswith("approved_sent"):
                cf1.append(f"r{n} {row['id']}")
            email = (entry.get("email") or "").strip().lower()
            if email:
                test_emails.setdefault(email, f"r{n} {row['id']}")
                if entry.get("final_status") in ALLOWED_CRM:
                    allowed.add(email)
    # Same rule as tests/run_tests.py report: an e-mail in HubSpot is safe when one of its
    # log rows took an allowed path (a duplicate row of a high_fit lead shares its e-mail).
    cf2 = sorted(test_emails[e] for e in (crm & set(test_emails)) - allowed)
    rate = {k: v for k, v in cases.items() if v["category"] not in CODE_PATH}
    code = {k: v for k, v in cases.items() if v["category"] in CODE_PATH}
    misses = sorted(k for k, v in rate.items() if not all(r in v["expected"] for r in v["routes"]))
    code_fails = sorted(k for k, v in code.items() if not all(r in v["expected"] for r in v["routes"]))
    unstable = sorted(k for k, v in cases.items() if len(set(map(str, v["routes"]))) > 1)
    passed = (not problems and len(rate) >= MIN_RATE_CASES and len(misses) <= MAX_MISSES
              and not cf1 and not cf2 and not code_fails)
    return {
        "verdict": "PASS" if passed else "FAIL",
        "problems": problems,
        "rate_cases": len(rate), "rate_passed": len(rate) - len(misses), "misses": misses,
        "code_cases": len(code), "code_fails": code_fails,
        "cf1_reply_sent_without_approval": cf1, "cf2_crm_without_allowed_path": cf2,
        "route_changed_between_runs": unstable,
        "runs": [{"started_utc": r.get("started_utc"), "tag": r.get("tag"), "lead_files": r.get("lead_files")}
                 for r in runs],
        "per_case": {k: {"expected": v["expected"], "routes": v["routes"]} for k, v in cases.items()},
    }


def main(argv):
    base = run_tests.BASE
    if len(argv) != RUNS:
        print(__doc__)
        return 2
    runs = [json.loads(Path(f).read_text(encoding="utf-8")) for f in argv]
    report = run_tests.get(base + run_tests.REPORT_PATH, headers=run_tests.auth(run_tests.REPORT_KEY))
    result = grade(runs, report)
    out = Path(argv[0]).parent / f"series-{runs[0].get('started_utc')}.json"
    out.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    for p in result["problems"]:
        print("PROBLEM:", p)
    print(f"Rate cases: {result['rate_passed']} / {result['rate_cases']} passed in all {RUNS} runs "
          f"(misses {len(result['misses'])}: {', '.join(result['misses']) or 'none'})")
    print(f"Code checks: {result['code_cases'] - len(result['code_fails'])} / {result['code_cases']} "
          f"(fails: {', '.join(result['code_fails']) or 'none'})")
    print(f"CF1: {result['cf1_reply_sent_without_approval'] or 'none'}; "
          f"CF2: {result['cf2_crm_without_allowed_path'] or 'none'}")
    print(f"Route changed between runs: {', '.join(result['route_changed_between_runs']) or 'none'}")
    print(f"Verdict: {result['verdict']}  (saved {out})")
    if any("cut off" in p for p in result["problems"]):
        return 2
    return 0 if result["verdict"] == "PASS" else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
