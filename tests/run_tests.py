"""Send the test leads to the n8n workflow and summarise what happened.

Step 1 - send all leads (needs n8n and the mock sites running):
    python tests/run_tests.py send

Step 2 - after the Slack reviews are done, build the result report:
    python tests/run_tests.py report tests/results/<run-file>.json

Only the Python standard library is used. Nothing secret is read or written:
the report endpoint returns the workflow's own lead log and the e-mails
found in HubSpot, which n8n fetches with the credential stored in n8n.
"""
import json
import sys
import time
import urllib.error
import urllib.request
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent
LEADS_FILE = ROOT / "leads.json"
RESULTS_DIR = ROOT / "results"
BASE = "http://localhost:5678"
LEAD_PATH = "/webhook/lead"
REPORT_PATH = "/webhook/lead-report"


def build_payload(case):
    lead = dict(case["lead"])
    msg = lead.get("message")
    if isinstance(msg, dict):  # generated long text
        lead["message"] = msg["repeat"] * msg["times"]
    if case.get("test_flag"):
        lead["test_flag"] = case["test_flag"]
    lead["source"] = "test-run"
    return lead


def post(url, payload, timeout=120):
    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(url, data=data, headers={"Content-Type": "application/json"})
    start = time.time()
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            body = resp.read().decode("utf-8")
            status = resp.status
    except urllib.error.HTTPError as err:
        body, status = err.read().decode("utf-8", "replace"), err.code
    except Exception as err:  # connection problems are a result too
        body, status = json.dumps({"runner_error": str(err)}), 0
    seconds = round(time.time() - start, 2)
    try:
        parsed = json.loads(body)
    except ValueError:
        parsed = {"raw": body[:500]}
    return status, parsed, seconds


def cmd_send(base):
    cases = json.loads(LEADS_FILE.read_text(encoding="utf-8"))["leads"]
    started = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    rows = []
    for case in cases:
        status, body, seconds = post(base + LEAD_PATH, build_payload(case))
        route = body.get("route") if isinstance(body, dict) else None
        rows.append({"id": case["id"], "category": case["category"], "expected": case["expected"],
                     "http_status": status, "route": route, "log_id": body.get("log_id"),
                     "seconds": seconds, "response": body})
        mark = "OK " if route in case["expected"] else "-- "
        print(f"{mark}{case['id']:4} {case['category']:24} -> {route} ({seconds}s)")
    RESULTS_DIR.mkdir(exist_ok=True)
    out = RESULTS_DIR / f"run-{started}.json"
    out.write_text(json.dumps({"started_utc": started, "base": base, "rows": rows}, indent=2), encoding="utf-8")
    print(f"\nSaved {out.relative_to(ROOT.parent)}")
    print("Now do the Slack reviews, then run: python tests/run_tests.py report", out.relative_to(ROOT.parent))


def get(url, timeout=60):
    with urllib.request.urlopen(url, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8"))


def cmd_report(run_file, base):
    run = json.loads(Path(run_file).read_text(encoding="utf-8"))
    report = get(base + REPORT_PATH)
    log = {str(r["id"]): r for r in report.get("log", [])}
    crm_emails = {e.strip().lower() for e in report.get("hubspot_emails", [])}

    rows = run["rows"]
    n = len(rows)
    route_counts = Counter(r["route"] for r in rows)
    matched = [r for r in rows if r["route"] in r["expected"]]
    missed = [r for r in rows if r["route"] not in r["expected"]]

    allowed_in_crm, unsafe = set(), []
    final = Counter()
    replies = Counter()
    for r in rows:
        entry = log.get(str(r["log_id"]), {})
        r["final_status"] = entry.get("final_status", "not_logged")
        r["reply_status"] = entry.get("reply_status", "")
        final[r["final_status"]] += 1
        if r["reply_status"]:
            replies[r["reply_status"]] += 1
        email = (entry.get("email") or "").lower()
        ok_for_crm = r["final_status"] in ("crm_created", "review_approved_crm_created")
        if ok_for_crm and email:
            allowed_in_crm.add(email)
    # Any test e-mail in HubSpot that no allowed path put there is a safety failure.
    test_emails = {(log.get(str(r["log_id"]), {}).get("email") or "").lower() for r in rows} - {""}
    for email in sorted((crm_emails & test_emails) - allowed_in_crm):
        unsafe.append(email)

    by_cat = {}
    for r in rows:
        c = by_cat.setdefault(r["category"], [0, 0])
        c[1] += 1
        c[0] += r["route"] in r["expected"]

    lines = [
        f"# Test run {run['started_utc']}",
        "",
        "Numbers below come only from this run (send file + n8n lead log + HubSpot lookup).",
        "",
        f"- Leads sent: **{n}**",
        f"- Routed as expected: **{len(matched)} / {n}**",
        f"- Leads in HubSpot that should not be there: **{len(unsafe)}**" + (f" ({', '.join(unsafe)})" if unsafe else ""),
        f"- Test leads found in HubSpot: **{len(crm_emails & test_emails)}** (allowed: {len(allowed_in_crm)})",
        "",
        "## First routing decision",
        "",
        "| Route | Leads |",
        "|---|---|",
    ] + [f"| {k} | {v} |" for k, v in sorted(route_counts.items(), key=lambda kv: str(kv[0]))] + [
        "",
        "## By test category (routed as expected / total)",
        "",
        "| Category | Result |",
        "|---|---|",
    ] + [f"| {k} | {v[0]} / {v[1]} |" for k, v in by_cat.items()] + [
        "",
        "## Final status after human review",
        "",
        "| Final status | Leads |",
        "|---|---|",
    ] + [f"| {k} | {v} |" for k, v in sorted(final.items())] + [
        "",
        "## AI-drafted replies",
        "",
        "| Reply status | Count |",
        "|---|---|",
    ] + [f"| {k} | {v} |" for k, v in sorted(replies.items())] + [
        "",
        "## Not as expected",
        "",
    ] + ([f"- {r['id']} ({r['category']}): expected {r['expected']}, got {r['route']}" for r in missed] or ["- none"]) + [
        "",
        "## Per lead",
        "",
        "| Lead | Category | Expected | Route | Final status | Reply | Seconds |",
        "|---|---|---|---|---|---|---|",
    ] + [f"| {r['id']} | {r['category']} | {', '.join(r['expected'])} | {r['route']} | {r['final_status']} | {r['reply_status']} | {r['seconds']} |" for r in rows]

    out = Path(run_file).with_suffix(".report.md")
    out.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print("\n".join(lines[:9]))
    print(f"\nSaved {out}")


if __name__ == "__main__":
    args = sys.argv[1:]
    base = BASE
    if "--base" in args:
        i = args.index("--base")
        base = args[i + 1].rstrip("/")
        del args[i:i + 2]
    if args[:1] == ["send"]:
        cmd_send(base)
    elif args[:1] == ["report"] and len(args) == 2:
        cmd_report(args[1], base)
    else:
        print(__doc__)
        sys.exit(2)
