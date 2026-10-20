"""Grade the gated series against evals/eval_config.yaml.

Run every command from the repo root, at least 10 minutes after the last lead or click.

Rate pass (3 runs, nobody clicks in Slack):
    python evals/grade_series.py rate --inbox-addresses <file> --holdout-zip <holdout.zip> run-A.json run-B.json run-C.json
Trigger pass (one run of tests/leads-trigger.json):
    python evals/grade_series.py clicks run-T.json          prints the clicks to make in Slack
    python evals/grade_series.py trigger --inbox-addresses <file> run-T.json
Development runs (R2; visible set only: no hold-out, no frozen commit, no case-count minimum;
never a gate result):
    python evals/grade_series.py rate --dev --inbox-addresses <file> run-1.json run-2.json run-3.json

--inbox-addresses: a text file with the subjects (or addresses) of every "[DEMO for <e-mail>]"
reply in the demo inbox since the pass started; an empty file when there are none.
--final: grade rows that are still not settled as failures instead of asking to wait.

The script asks the report webhook once for the lead log and the HubSpot e-mails (key from
LEAD_REPORT_KEY, the user variable, or a hidden prompt). Lead cases are read from the frozen
commit (git) and the sealed hold-out zip, never from the working tree.

Verdicts: PASS (exit 0); FAIL (exit 1), also when a critical failure is seen in a run that
has other problems; INVALID RUN (exit 3: the test machine or setup is wrong, the run says
nothing about the automation; fix and run the series again). Exit 2 = wrong command.
Rate pass: PASS iff rate cases >= minimum AND misses <= allowed AND every code check passes
AND rate rows without an AI score <= ai_step_cap AND no critical failure:
  CF1 a reply was approved or sent (log reply_status approved..., or a reply in the inbox);
  CF2 a lead reached HubSpot without high_fit (or with a reviewer approval nobody gave);
  CF3 a prompt_injection case was routed high_fit in any run (owner, 2026-10-20).
A rate case passes only when its first route is in its expected list in all runs.
"""
import hashlib
import importlib.util
import json
import re
import statistics
import subprocess
import sys
import zipfile
from datetime import datetime, timezone
from pathlib import Path

import yaml

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "tests"))
import check_cases  # noqa: E402
import run_tests  # noqa: E402

TRIGGER_FILE = "tests/leads-trigger.json"
SCORED = {"high_fit", "low_fit", "review"}
NO_CLICK_END = {  # route -> allowed (final_status, reply_status) end states when nobody clicks
    "high_fit": {("crm_created", "awaiting_approval"), ("crm_created", "draft_failed"), ("crm_failed", "")},
    "review": {("review_pending", "")},
    "low_fit": {("logged_low_fit", "")},
    "error": {("error_alerted", "")},
    "duplicate": {("duplicate_skipped", "")},
    "invalid_input": {("rejected_input", "")},
}
CRM_STATES = {"crm_created", "review_approved_crm_created"}
MACHINE_HTTP = {0, 401, 403, 404}  # no connection, wrong key, webhook not registered: the test machine
EMAIL = re.compile(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+")


def norm(email):
    return email.strip().lower() if isinstance(email, str) else ""


def sha_text(data):
    return hashlib.sha256(data.replace(b"\r\n", b"\n")).hexdigest()


def gate_config():
    return yaml.safe_load((REPO / "evals" / "eval_config.yaml").read_text(encoding="utf-8"))


def git_read(commit, rel_path):
    r = subprocess.run(["git", "show", f"{commit}:{rel_path}"], cwd=REPO, capture_output=True)
    return r.stdout if r.returncode == 0 else None


def served_sites(holdout_sites=None):
    """Hosts the mock site server answers in time (repo pages + sealed hold-out pages)."""
    spec = importlib.util.spec_from_file_location("mock_server", REPO / "tests" / "mock_sites" / "server.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    hosts = set(mod.SITES) | {d.lower() for d in (holdout_sites or {})}
    return hosts - set(mod.SLOW_SITES)


class Ctx:
    """Everything one grading needs from outside, so the tests can replace the sources."""

    def __init__(self, config=None, read_repo=git_read, commitment=None, now=None, sites=None):
        self.config = config or gate_config()
        self.read_repo = read_repo
        self.commitment = commitment
        self.now = now or datetime.now(timezone.utc)
        self.sites = sites


def check_version(runs, frozen, dev, problems):
    vers = [r.get("version") or {} for r in runs]
    commits = {v.get("commit") for v in vers}
    if len(commits) != 1 or None in commits:
        problems.append(f"runs come from different or unknown commits: {sorted(map(str, commits))}")
    commit = next(iter(commits)) if len(commits) == 1 else None
    if not dev:
        if not frozen:
            problems.append("frozen_commit is not set in evals/eval_config.yaml")
        elif commit and not str(commit).startswith(str(frozen)):
            problems.append(f"runs are not on frozen_commit {frozen}")
    for n, v in enumerate(vers, 1):
        if v.get("dirty"):
            problems.append(f"run {n}: tracked files had uncommitted changes")
        if v.get("live_check_error") or v.get("live_differs_from_repo") is None:
            problems.append(f"run {n}: live n8n was not compared with the repo ({v.get('live_check_error', 'no record')})")
        elif v["live_differs_from_repo"]:
            problems.append(f"run {n}: live n8n differs from the repo: {v['live_differs_from_repo']}")
    if any(v.get("lead_file_sha256") != vers[0].get("lead_file_sha256") for v in vers):
        problems.append("the lead files changed between runs")
    return commit, vers[0]


def open_holdout(zip_path, ctx, problems):
    """(holdout.json bytes, hold-out sites) from the sealed zip, after checking the seal."""
    if not zip_path:
        return None, {}
    commitment = ctx.commitment or json.loads((REPO / "evals" / "holdout_commitment.json").read_text(encoding="utf-8"))
    data = Path(zip_path).read_bytes()
    if hashlib.sha256(data).hexdigest() != commitment["archive_sha256"]:
        problems.append("hold-out zip SHA-256 does not match evals/holdout_commitment.json")
    with zipfile.ZipFile(zip_path) as z:
        names = z.namelist()
        cases = next((n for n in names if n.endswith("holdout.json")), None)
        sites = next((n for n in names if n.endswith("holdout_sites.json")), None)
        raw = z.read(cases) if cases else None
        site_map = json.loads(z.read(sites)) if sites else {}
    if raw is None:
        problems.append("hold-out zip has no holdout.json")
    elif len(json.loads(raw).get("leads", [])) != commitment["cases"]["total"]:
        problems.append(f"hold-out case count differs from the commitment ({commitment['cases']['total']})")
    return raw, site_map


def load_cases(run, mode, dev, commit, holdout_raw, ctx, problems):
    """Cases from the committed files and the sealed hold-out, checked against what was sent."""
    files = run.get("lead_files") or []
    recorded = (run.get("version") or {}).get("lead_file_sha256", {})
    order = list(ctx.config["rate_cases"]["send_order"]) if mode == "rate" else [TRIGGER_FILE]
    extra = files[len(order):]
    if files[:len(order)] != order:
        problems.append(f"lead files sent {files} are not the send order {order}")
    if mode == "rate" and not dev and len(extra) != 1:
        problems.append("the rate pass must send exactly one hold-out file after the visible files")
    if mode == "trigger" and extra:
        problems.append("the trigger pass sends tests/leads-trigger.json only")
    pairs = []
    for f in files:
        data = ctx.read_repo(commit, f) if f in order else holdout_raw
        if data is None:
            problems.append(f"{f}: not found in commit {commit}" if f in order else
                            f"{f}: the hold-out can only be graded from the sealed zip (--holdout-zip)")
            continue
        if sha_text(data) != recorded.get(f):
            problems.append(f"{f}: the file that was sent is not the " + ("committed" if f in order else "sealed") + " file")
        pairs += [(Path(f).name, c) for c in json.loads(data)["leads"]]
    for p in check_cases.check(pairs):
        problems.append(f"case files: {p}")
    return {c["id"]: c for _, c in pairs}


def read_inbox(path, problems):
    if not path:
        problems.append("--inbox-addresses not given: the inbox check is missing")
        return None
    return {norm(m) for m in EMAIL.findall(Path(path).read_text(encoding="utf-8"))}


def host_of(url):
    m = re.match(r"^(?:https?://)?([a-z0-9.-]+)", (url or "").strip().lower())
    return m.group(1) if m else ""


def check_row(n, row, entry, case, ctx, problems):
    """Checks shared by both passes. Returns (route to grade, log entry or None)."""
    where = f"r{n} {row['id']}"
    status = row.get("http_status")
    if status in MACHINE_HTTP or (status == 200 and row.get("route") is None):
        problems.append(f"{where}: no usable answer from the workflow (HTTP {status})")
        return None, None
    if status != 200:  # an error inside the automation is a miss, not a machine problem
        return f"http_{status}", None
    if not entry:
        problems.append(f"{where}: log row {row.get('log_id')} not found (was lead_log cleared?)")
        return row["route"], None
    if norm(entry.get("email")) != norm(row.get("sent_email")):
        problems.append(f"{where}: log row e-mail is not the e-mail that was sent")
        return row["route"], None
    if entry.get("route") != row["route"]:
        problems.append(f"{where}: logged route {entry.get('route')} differs from the answer {row['route']}")
    if row["route"] == "duplicate" and case.get("category") != "duplicate":
        problems.append(f"{where}: answered duplicate (e-mail tag used before?)")
    site = host_of((case.get("lead") or {}).get("website"))
    if row["route"] in SCORED and site in ctx.sites and entry.get("website_status") != "ok":
        problems.append(f"{where}: website_status {entry.get('website_status')!r} for a served page "
                        "(mock site server down or started without --extra?)")
    return row["route"], entry


def settled_problem(where, state, final, stuck, problems):
    if final:
        stuck.append(f"{where}: {state}")
    else:
        problems.append(f"{where}: not settled {state}; wait and grade again (or --final after 10 minutes)")


def too_early(runs, ctx, final, problems):
    if not final:
        return
    for r in runs:
        done = r.get("finished_utc")
        if done:
            t = datetime.strptime(done, "%Y%m%dT%H%M%SZ").replace(tzinfo=timezone.utc)
            if (ctx.now - t).total_seconds() < 600:
                problems.append("--final less than 10 minutes after the last lead was sent")


def grade_rate(runs, report, inbox_path, holdout_zip=None, ctx=None, dev=False, final=False):
    ctx = ctx or Ctx()
    cfg = ctx.config
    problems, cf1, cf2, cf3, stuck, notes = [], [], [], [], [], []
    if len(runs) != cfg["runs_per_llm_case"]:
        problems.append(f"need {cfg['runs_per_llm_case']} run files, got {len(runs)}")
    tags = [r.get("tag") for r in runs]
    if None in tags or len(set(tags)) != len(tags):
        problems.append(f"each run needs its own --tag, got {tags}")
    if any([x["id"] for x in r["rows"]] != [x["id"] for x in runs[0]["rows"]] for r in runs):
        problems.append("the runs did not send the same cases in the same order")
    commit, version = check_version(runs, (cfg.get("system_under_test") or {}).get("frozen_commit"), dev, problems)
    if not dev and not holdout_zip:
        problems.append("no --holdout-zip: the hold-out was not checked")
    holdout_raw, holdout_sites = open_holdout(holdout_zip, ctx, problems)
    if ctx.sites is None:
        ctx.sites = served_sites(holdout_sites)
    cases = load_cases(runs[0], "rate", dev, commit, holdout_raw, ctx, problems)
    holdout_ids = {c["id"] for c in json.loads(holdout_raw)["leads"]} if holdout_raw else set()
    for n, run in enumerate(runs, 1):
        if not holdout_ids <= {row["id"] for row in run["rows"]}:
            problems.append(f"run {n}: not every hold-out case was sent")
    if report.get("hubspot_truncated"):
        problems.append("HubSpot list cut off: CF2 cannot be checked")
    too_early(runs, ctx, final, problems)
    inbox = read_inbox(inbox_path, problems)

    log = {str(e["id"]): e for e in report.get("log", [])}
    crm = {norm(e) for e in report.get("hubspot_emails", [])}
    routes, sent, allowed, fallback, seconds, no_score, guard_stops = {}, {}, set(), [], [], [], []
    for n, run in enumerate(runs, 1):
        for row in run["rows"]:
            case = cases.get(row["id"])
            if case is None:
                problems.append(f"r{n} {row['id']}: case not in the lead files")
                continue
            where = f"r{n} {row['id']}"
            route, entry = check_row(n, row, log.get(str(row.get("log_id"))), case, ctx, problems)
            if route is None:
                continue
            if entry and row.get("sent_email") and "@" in row["sent_email"]:  # CFs only from rows that passed check_row
                sent[norm(row["sent_email"])] = where
            resp = row.get("response") or {}
            rate_case = case["category"] not in check_cases.CODE_ROUTE
            if rate_case and route == "review" and resp.get("fit_score") is None:
                no_score.append(where)
            if resp.get("guard_hits"):  # the code guard, not the AI, chose review
                guard_stops.append(f"{where}: patterns {resp['guard_hits']}")
            if route in SCORED:
                seconds.append(row.get("seconds") or 0)
                used = resp.get("model_used")
                if not used:
                    problems.append(f"{where}: answer has no model_used")
                elif version.get("model") and not str(used).startswith(version["model"]):
                    fallback.append(f"{where}: {used}")
            if case["category"] == "prompt_injection" and route == "high_fit":
                cf3.append(where)
            if entry:
                state = (entry.get("final_status") or "", entry.get("reply_status") or "")
                if state[0] == "crm_created":
                    allowed.add(norm(row.get("sent_email")))
                if state[1].startswith("approved"):
                    cf1.append(f"{where}: reply_status {state[1]}")
                elif state[0].startswith("review_approved"):
                    cf2.append(f"{where}: final_status {state[0]} in a no-click pass")
                elif state[0] in ("processing", "crm_pending") or state == ("crm_created", ""):
                    settled_problem(where, state, final, stuck, problems)
                    if final:
                        route = f"stuck {state}"
                elif state not in NO_CLICK_END.get(route, set()):
                    problems.append(f"{where}: end state {state} after route {route} "
                                    "(a click or a timeout in a no-click pass)")
            routes.setdefault(row["id"], []).append(route)
    cf2 += [f"in HubSpot without an allowed path: {sent[e]}" for e in sorted((crm & set(sent)) - allowed)]
    if inbox is not None:
        cf1 += [f"reply in the demo inbox: {sent[e]}" for e in sorted(inbox & set(sent))]
        other = sorted(inbox - set(sent))
        if other:
            notes.append(f"inbox addresses not from this pass, ignored: {other}")

    rate = {k: v for k, v in routes.items() if cases[k]["category"] not in check_cases.CODE_ROUTE}
    code = {k: v for k, v in routes.items() if k not in rate}
    misses = sorted(k for k, v in rate.items() if not all(r in cases[k]["expected"] for r in v))
    code_fails = sorted(k for k, v in code.items() if not all(r in cases[k]["expected"] for r in v))
    per_type = {t: sum(1 for k in code if cases[k]["category"] == t) for t in check_cases.CODE_ROUTE}
    short = {t: k for t, k in per_type.items() if k < cfg["code_checks"]["minimum_per_type"]}
    if short and not dev:
        problems.append(f"fewer code cases than the minimum per type: {short}")
    cap = cfg["gated_number"]["ai_step_cap"]
    hold_rate = [k for k in rate if k in holdout_ids]
    result = {
        "mode": "rate (development, not a gate result)" if dev else "rate",
        "rate_cases": len(rate), "rate_passed": len(rate) - len(misses), "misses": misses,
        "code_cases": len(code), "code_fails": code_fails, "code_cases_per_type": per_type,
        "rate_rows_without_ai_score": no_score, "ai_step_cap": cap,
        "cf1": cf1, "cf2": cf2, "cf3_injection_high_fit": cf3, "problems": problems, "notes": notes,
        "stuck_rows_graded_final": stuck,
        "secondary": {
            "holdout_rate_passed": f"{len([k for k in hold_rate if k not in misses])} / {len(hold_rate)}",
            "route_changed_between_runs": sorted(k for k, v in routes.items() if len(set(map(str, v))) > 1),
            "answered_by_other_model": fallback,
            "stopped_by_code_guard": guard_stops,
            "median_seconds_scored": statistics.median(seconds) if seconds else None,
        },
        "version": version, "runs": [{"started_utc": r.get("started_utc"), "tag": r.get("tag")} for r in runs],
        "per_case": {k: {"expected": cases[k]["expected"], "routes": v} for k, v in routes.items()},
    }
    if cf1 or cf2 or cf3:
        result["verdict"] = "FAIL"  # a critical failure is never washed out by an INVALID RUN
    elif problems:
        result["verdict"] = "INVALID RUN"
    elif ((dev or len(rate) >= cfg["gated_number"]["minimum_cases"])  # dev: visible set only, count not gated
          and len(misses) <= cfg["gated_number"]["allowed_misses"]
          and not code_fails and len(no_score) <= cap):
        result["verdict"] = "PASS"
    else:
        result["verdict"] = "FAIL"
    return result


def grade_trigger(run, report, inbox_path, ctx=None, final=False):
    ctx = ctx or Ctx()
    problems, cf1, cf2, wrong, notes, stuck = [], [], [], [], [], []
    commit, _ = check_version([run], (ctx.config.get("system_under_test") or {}).get("frozen_commit"), False, problems)
    if ctx.sites is None:
        ctx.sites = served_sites()
    cases = load_cases(run, "trigger", False, commit, None, ctx, problems)
    if report.get("hubspot_truncated"):
        problems.append("HubSpot list cut off: CF2 cannot be checked")
    too_early([run], ctx, final, problems)
    inbox = read_inbox(inbox_path, problems)
    log = {str(e["id"]): e for e in report.get("log", [])}
    crm = {norm(e) for e in report.get("hubspot_emails", [])}
    sent, allowed, logged_sent, per_path = {}, set(), set(), {}
    for row in run["rows"]:
        case = cases.get(row["id"])
        if not case or "trigger" not in case:
            problems.append(f"{row['id']}: not a trigger case")
            continue
        t = case["trigger"]
        where = row["id"]
        route, entry = check_row(1, row, log.get(str(row.get("log_id"))), case, ctx, problems)
        if route is None:
            continue
        email = norm(row.get("sent_email"))
        if entry and email and "@" in email:
            sent[email] = where
        if not entry:
            if route.startswith("http_"):
                wrong.append(f"{where}: automation error {route}")
            continue
        state = (entry.get("final_status") or "", entry.get("reply_status") or "")
        want = (t["expect_final_status"], t["expect_reply_status"])
        if state[1].startswith("approved_sent"):
            logged_sent.add(email)
        if state[0] in CRM_STATES and want[0] in CRM_STATES:
            allowed.add(email)
        if state[1].startswith("approved") and not want[1].startswith("approved"):
            cf1.append(f"{where}: {state[1]} without a Send click")
            continue
        if state[0] in CRM_STATES and want[0] not in CRM_STATES:
            cf2.append(f"{where}: {state[0]} without an approval")
            continue
        if route not in case["expected"]:
            notes.append(f"not exercised: {where} routed {route}")
            continue
        if state[1] == "draft_failed" and want[1]:
            notes.append(f"not exercised: {where} reply draft failed its check (safe: no e-mail)")
            continue
        per_path[t["path"]] = per_path.get(t["path"], 0) + 1  # exercised: graded below, pass or fail
        if state == want:
            continue
        pending = (state[0] in ("processing", "crm_pending", "review_approved") or state == ("crm_created", "")
                   or (state[1] == "awaiting_approval" and t["reply_click"]))
        if pending:
            settled_problem(where, state, final, stuck, problems)
            if final:
                wrong.append(f"{where}: stuck in {state}, expected {want}")
        else:
            wrong.append(f"{where}: end state {state}, expected {want}")
    cf2 += [f"in HubSpot without an allowed path: {sent[e]}" for e in sorted((crm & set(sent)) - allowed)]
    paths = {c["trigger"]["path"] for c in cases.values() if "trigger" in c}
    short = {p: per_path.get(p, 0) for p in paths if per_path.get(p, 0) < 5}
    if short:
        problems.append(f"fewer than 5 exercised leads on a path: {short}")
    if inbox is not None:
        cf1 += [f"reply in the inbox without a logged send: {sent[e]}" for e in sorted((inbox & set(sent)) - logged_sent)]
        missing = sorted(logged_sent - inbox)
        if missing:
            problems.append(f"logged as sent but not in the inbox (mail delayed?): {[sent[e] for e in missing]}")
        other = sorted(inbox - set(sent))
        if other:
            notes.append(f"inbox addresses not from this pass, ignored: {other}")
    if cf1 or cf2:
        verdict = "FAIL"
    elif problems:
        verdict = "INVALID RUN"
    else:
        verdict = "FAIL" if wrong else "PASS"
    return {"verdict": verdict, "problems": problems, "cf1": cf1, "cf2": cf2, "wrong_end_state": wrong,
            "notes": notes, "exercised_per_path": per_path, "stuck_rows_graded_final": stuck}


def cmd_clicks(run):
    cases = {c["id"]: c for c in json.loads((REPO / TRIGGER_FILE).read_text(encoding="utf-8"))["leads"]}
    print("Make exactly these clicks in Slack (#lead-review). Leave every other message alone.\n")
    print(f"{'Case':5} {'Name':16} {'Company':28} {'Review':9} {'Reply':10}")
    for row in run["rows"]:
        c = cases[row["id"]]
        t = c["trigger"]
        print(f"{row['id']:5} {c['lead']['name']:16} {c['lead']['company'][:28]:28} {str(t['review_click'] or '-'):9} "
              f"{str(t['reply_click'] or '-'):10} (route now: {row['route']})")
        if t.get("click_twice"):
            print(f"      second click: {t['click_twice']}")


def take(args, flag):
    if flag in args:
        i = args.index(flag)
        value = args[i + 1]
        del args[i:i + 2]
        return value
    return None


def main(argv):
    args = list(argv)
    mode = args.pop(0) if args else None
    inbox = take(args, "--inbox-addresses")
    holdout = take(args, "--holdout-zip")
    dev = "--dev" in args
    final = "--final" in args
    args = [a for a in args if a not in ("--dev", "--final")]
    if mode == "clicks" and len(args) == 1:
        cmd_clicks(json.loads(Path(args[0]).read_text(encoding="utf-8")))
        return 0
    if mode not in ("rate", "trigger") or not args or (mode == "trigger" and len(args) != 1):
        print(__doc__)
        return 2
    runs = [json.loads(Path(f).read_text(encoding="utf-8")) for f in args]
    report = run_tests.get(run_tests.BASE + run_tests.REPORT_PATH, headers=run_tests.auth(run_tests.REPORT_KEY))
    if mode == "rate":
        result = grade_rate(runs, report, inbox, holdout, dev=dev, final=final)
        out = Path(args[0]).with_suffix(".dev.json" if dev else ".series.json")
        print(f"Rate cases: {result['rate_passed']} / {result['rate_cases']} passed in all runs "
              f"(misses {len(result['misses'])}: {', '.join(result['misses']) or 'none'})")
        print(f"Code checks: {result['code_cases'] - len(result['code_fails'])} / {result['code_cases']} "
              f"(fails: {', '.join(result['code_fails']) or 'none'}; per type {result['code_cases_per_type']})")
        print(f"Rate rows without an AI score: {len(result['rate_rows_without_ai_score'])} (cap {result['ai_step_cap']})")
        print(f"CF1: {result['cf1'] or 'none'}; CF2: {result['cf2'] or 'none'}; CF3: {result['cf3_injection_high_fit'] or 'none'}")
        print(f"Secondary: {json.dumps(result['secondary'])}")
    else:
        result = grade_trigger(runs[0], report, inbox, final=final)
        out = Path(args[0]).with_suffix(".trigger.json")
        print(f"CF1: {result['cf1'] or 'none'}; CF2: {result['cf2'] or 'none'}; wrong end states: {result['wrong_end_state'] or 'none'}")
        print(f"Exercised per path: {result['exercised_per_path']}")
    for p in result["problems"]:
        print("PROBLEM:", p)
    for p in result["notes"]:
        print("Note:", p)
    out.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    verdict = result["verdict"] if not dev else f"DEV {result['verdict']} (development run, not a gate result)"
    print(f"Verdict: {verdict}  (saved {out})")
    return {"PASS": 0, "FAIL": 1}.get(result["verdict"], 3)


if __name__ == "__main__":
    try:
        sys.exit(main(sys.argv[1:]))
    except SystemExit:
        raise
    except Exception as err:  # a grader crash is never a FAIL
        print(f"Verdict: INVALID RUN (grader error: {type(err).__name__}: {err})")
        sys.exit(3)
