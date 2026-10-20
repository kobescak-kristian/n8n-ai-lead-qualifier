"""Send the test leads to the n8n workflow and summarise what happened.

Step 1 - send all leads (needs n8n and the mock sites running):
    python tests/run_tests.py send
    python tests/run_tests.py send --leads tests/leads.json --leads <other.json> --tag r1
  --leads (repeatable) picks the lead files, default tests/leads.json.
  --tag adds ".<tag>" to every e-mail, so a repeat run is not stopped by the
  duplicate check; duplicate cases inside one run keep matching each other.

Step 2 - after the Slack reviews are done, build the result report:
    python tests/run_tests.py report tests/results/<run-file>.json

Only the Python standard library is used. Both webhooks are protected by
n8n Header Auth: the keys are read from the environment variables
LEAD_QUALIFIER_KEY and LEAD_REPORT_KEY, or asked for once (hidden input).
They are never written to a file. The report endpoint returns the
workflow's own lead log and the e-mails found in HubSpot, which n8n
fetches with the credential stored in n8n.
"""
import getpass
import json
import os
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
KEY_HEADER = "X-Webhook-Key"
LEAD_KEY = ("LEAD_QUALIFIER_KEY", "Lead form webhook")
REPORT_KEY = ("LEAD_REPORT_KEY", "Lead report webhook")
_keys = {}


def user_variable(var):
    """A Windows user variable set after this shell started (registry), else None."""
    if sys.platform != "win32":
        return None
    import winreg
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, "Environment") as k:
            return winreg.QueryValueEx(k, var)[0]
    except OSError:
        return None


def auth(key):
    """Header for a protected webhook. Read from the environment, the user variable, or asked once."""
    var, label = key
    if var not in _keys:
        _keys[var] = (os.environ.get(var) or user_variable(var)
                      or getpass.getpass(f"{label} key ({var}, input hidden): "))
    return {KEY_HEADER: _keys[var]}


def tagged(email, tag):
    if not tag or "@" not in str(email):
        return email
    local, domain = email.split("@", 1)
    return f"{local}.{tag}@{domain}"


def build_payload(case, tag=None):
    lead = dict(case["lead"])
    lead["email"] = tagged(lead.get("email"), tag)
    msg = lead.get("message")
    if isinstance(msg, dict):  # generated long text
        lead["message"] = msg["repeat"] * msg["times"]
    if case.get("test_flag"):
        lead["test_flag"] = case["test_flag"]
    lead["source"] = "test-run"
    return lead


def post(url, payload, timeout=400, headers=None):  # scoring can take 3 tries x 120 s
    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(url, data=data, headers={"Content-Type": "application/json", **(headers or {})})
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


def file_sha256(path):
    """SHA-256 of a text file with line endings made LF (same on every checkout)."""
    import hashlib
    return hashlib.sha256(Path(path).read_bytes().replace(b"\r\n", b"\n")).hexdigest()


def file_key(path):
    """Repo-relative POSIX path for a file in the repo (same text from any shell), else the absolute POSIX path."""
    full = Path(path).resolve()
    try:
        return full.relative_to(ROOT.parent).as_posix()
    except ValueError:
        return full.as_posix()


def version_info(files):
    """What this run tests: repo commit, tracked changes or not, lead file hashes, model, live n8n = repo files."""
    import subprocess
    repo = ROOT.parent

    def git(*a):
        r = subprocess.run(["git", *a], cwd=repo, capture_output=True, text=True)
        return r.stdout.strip() if r.returncode == 0 else None
    # Only tracked files count: the run files written by this runner are untracked.
    info = {"commit": git("rev-parse", "HEAD"), "dirty": bool(git("status", "--porcelain", "--untracked-files=no")),
            "lead_file_sha256": {file_key(f): file_sha256(f) for f in files}}
    try:
        sys.path.insert(0, str(repo / "tools"))
        import n8n_api
        settings = n8n_api.repo_settings()
        info.update(model=settings["model"], effort=settings["effort"],
                    live_differs_from_repo=n8n_api.live_differs_from_repo())
    except (SystemExit, Exception) as err:  # recorded, the grader treats it as not checked
        info["live_check_error"] = str(err)[:300]
    return info


def cmd_send(base, files, tag):
    cases = []
    for f in files:
        cases += json.loads(Path(f).read_text(encoding="utf-8"))["leads"]
    started = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    version = version_info(files)
    rows = []
    for case in cases:
        payload = build_payload(case, tag)
        status, body, seconds = post(base + LEAD_PATH, payload, headers=auth(LEAD_KEY))
        route = body.get("route") if isinstance(body, dict) else None
        rows.append({"id": case["id"], "category": case["category"], "expected": case["expected"],
                     "sent_email": payload.get("email"), "http_status": status, "route": route,
                     "log_id": body.get("log_id"), "seconds": seconds, "response": body})
        mark = "OK " if route in case["expected"] else "-- "
        print(f"{mark}{case['id']:4} {case['category']:24} -> {route} ({seconds}s)")
    RESULTS_DIR.mkdir(exist_ok=True)
    out = RESULTS_DIR / f"run-{started}.json"
    finished = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    out.write_text(json.dumps({"started_utc": started, "finished_utc": finished, "base": base,
                                "lead_files": [file_key(f) for f in files],
                                "tag": tag, "version": version, "rows": rows}, indent=2), encoding="utf-8")
    print(f"\nSaved {out.relative_to(ROOT.parent)}")
    print("Now do the Slack reviews, then run: python tests/run_tests.py report", out.relative_to(ROOT.parent))


def get(url, timeout=60, headers=None):
    req = urllib.request.Request(url, headers=headers or {})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8"))


def cmd_report(run_file, base):
    run = json.loads(Path(run_file).read_text(encoding="utf-8"))
    report = get(base + REPORT_PATH, headers=auth(REPORT_KEY))
    log = {str(r["id"]): r for r in report.get("log", [])}
    crm_emails = {e.strip().lower() for e in report.get("hubspot_emails", [])}
    if report.get("hubspot_truncated"):
        print("WARNING: the HubSpot list was cut off; 'should not be there' is not complete.")

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
    files, tag = [], None
    while "--leads" in args:
        i = args.index("--leads")
        files.append(args[i + 1])
        del args[i:i + 2]
    if "--tag" in args:
        i = args.index("--tag")
        tag = args[i + 1]
        del args[i:i + 2]
    if args[:1] == ["send"]:
        cmd_send(base, files or [LEADS_FILE], tag)
    elif args[:1] == ["report"] and len(args) == 2:
        cmd_report(args[1], base)
    else:
        print(__doc__)
        sys.exit(2)
