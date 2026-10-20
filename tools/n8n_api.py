"""Change and export the live lead-qualifier workflows through the n8n public API (no restart).

    python tools/n8n_api.py keys      creates the two webhook credentials in n8n with new random
                                       keys and stores the same keys in the Windows user variables
                                       LEAD_QUALIFIER_KEY and LEAD_REPORT_KEY (never printed)
    python tools/n8n_api.py check     the two webhook credentials (names and ids only)
                                       and the state of the lead-qualifier workflows
    python tools/n8n_api.py apply     live lead qualifier: ICP text from the repo file, Header Auth
                                       on the "New lead" webhook; live report: Header Auth on
                                       "Report request"; all five renamed (NAMES); published
                                       workflows are published again
    python tools/n8n_api.py export    live lead-qualifier workflows -> workflows/*.json, credentials and
                                       personal e-mail settings stripped

The API key is read from the environment variable N8N_API_KEY_LEAD_QUALIFIER (or the same
user variable in the Windows registry). It is never printed or written to a file.
Shared-n8n rules: only the five lead-qualifier workflows (ids start with "Q116") are read or changed.
"""
import json
import os
import re
import sys
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
BASE = "http://localhost:5678/api/v1"
KEY_VAR = "N8N_API_KEY_LEAD_QUALIFIER"
FILES = {"Q116LeadQualify1": "lead-qualifier.json", "Q116ErrorAlert01": "error-alert.json",
         "Q116LeadReport01": "lead-report.json", "Q116SetupTable01": "setup-lead-log-table.json",
         "Q116ResetTable01": "test-reset-lead-log.json"}
NAMES = {"Q116LeadQualify1": "n8n-lead-qualifier",
         "Q116ErrorAlert01": "n8n-lead-qualifier: error alert",
         "Q116LeadReport01": "n8n-lead-qualifier: report (test runner)",
         "Q116SetupTable01": "n8n-lead-qualifier: setup lead_log table",
         "Q116ResetTable01": "n8n-lead-qualifier: test reset lead_log"}
WEBHOOKS = {"Q116LeadQualify1": ("New lead", "n8n-lead-qualifier-webhook"),
            "Q116LeadReport01": ("Report request", "n8n-lead-qualifier-report-webhook")}
SETTINGS_ALLOWED = {"saveExecutionProgress", "saveManualExecutions", "saveDataErrorExecution",
                    "saveDataSuccessExecution", "executionTimeout", "errorWorkflow", "timezone",
                    "executionOrder", "binaryMode", "callerPolicy", "callerIds", "timeSavedMode",
                    "timeSavedPerExecution", "redactionPolicy"}


def api_key():
    key = os.environ.get(KEY_VAR)
    if not key and sys.platform == "win32":  # set after this shell started
        import winreg
        try:
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, "Environment") as k:
                key = winreg.QueryValueEx(k, KEY_VAR)[0]
        except OSError:
            key = None
    if not key:
        sys.exit(f"{KEY_VAR} is not set (n8n Settings > n8n API, then the user variable).")
    return key.strip()


def call(method, path, body=None, params=None):
    url = BASE + path + ("?" + urllib.parse.urlencode(params) if params else "")
    data = json.dumps(body).encode("utf-8") if body is not None else None
    req = urllib.request.Request(url, data=data, method=method)
    req.add_header("X-N8N-API-KEY", api_key())
    req.add_header("Accept", "application/json")
    if data is not None:
        req.add_header("Content-Type", "application/json")
    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            raw = resp.read().decode("utf-8")
            return json.loads(raw) if raw else {}
    except urllib.error.HTTPError as e:
        sys.exit(f"{method} {path} -> HTTP {e.code}: {e.read().decode('utf-8', 'replace')[:600]}")


def list_all(path):
    items, cursor = [], None
    while True:
        page = call("GET", path, params=dict({"limit": 100}, **({"cursor": cursor} if cursor else {})))
        items += page.get("data", [])
        cursor = page.get("nextCursor")
        if not cursor:
            return items


def get_wf(wid):
    assert wid.startswith("Q116"), wid
    return call("GET", f"/workflows/{wid}")


def webhook_credentials():
    names = {cred for _, cred in WEBHOOKS.values()}
    creds = [c for c in list_all("/credentials") if c.get("name") in names]
    return {c["name"]: c for c in creds}


def cmd_check():
    for name, c in sorted(webhook_credentials().items()):
        print(f"credential: {name}  type={c.get('type')}  id={c.get('id')}")
    for wid in FILES:
        w = get_wf(wid)
        hooks = [f"{n['name']}: auth={n['parameters'].get('authentication', 'none')}"
                 for n in w["nodes"] if n["type"] == "n8n-nodes-base.webhook"]
        print(f"workflow: {wid}  active={w.get('active')}  {'; '.join(hooks)}")


KEY_VARS = {"n8n-lead-qualifier-webhook": "LEAD_QUALIFIER_KEY",
            "n8n-lead-qualifier-report-webhook": "LEAD_REPORT_KEY"}
KEY_HEADER = "X-Webhook-Key"


def cmd_keys():
    import ctypes
    import secrets
    import winreg
    existing = webhook_credentials()
    for cred_name, var in KEY_VARS.items():
        if cred_name in existing:
            print(f"exists, left as is: {cred_name}")
            continue
        key = secrets.token_hex(32)
        call("POST", "/credentials", {"name": cred_name, "type": "httpHeaderAuth",
                                      "data": {"name": KEY_HEADER, "value": key}})
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, "Environment", 0, winreg.KEY_SET_VALUE) as k:
            winreg.SetValueEx(k, var, 0, winreg.REG_SZ, key)
        print(f"created: {cred_name} in n8n, same key in user variable {var}")
    # Tell Windows the user variables changed, so new terminals see them.
    ctypes.windll.user32.SendMessageTimeoutW(0xFFFF, 0x001A, 0, "Environment", 0x0002, 5000, None)


def repo_icp():
    w = json.loads((ROOT / "workflows" / "lead-qualifier.json").read_text(encoding="utf-8"))
    for n in w["nodes"]:
        if n["name"] == "Settings":
            for a in n["parameters"]["assignments"]["assignments"]:
                if a["name"] == "icp":
                    return a["value"]
    sys.exit("icp not found in workflows/lead-qualifier.json")


def cmd_apply():
    creds = webhook_credentials()
    for _, cred_name in WEBHOOKS.values():
        c = creds.get(cred_name)
        if not c or c.get("type") != "httpHeaderAuth":
            sys.exit(f"missing Header Auth credential named '{cred_name}' in n8n")
    for wid, new_name in NAMES.items():
        w = get_wf(wid)
        was_active = bool(w.get("active"))
        node_name, cred_name = WEBHOOKS.get(wid, (None, None))
        c = creds.get(cred_name)
        found = 0
        for n in w["nodes"]:
            if n["name"] == node_name and n["type"] == "n8n-nodes-base.webhook":
                n["parameters"]["authentication"] = "headerAuth"
                n["credentials"] = {"httpHeaderAuth": {"id": c["id"], "name": c["name"]}}
                found += 1
            if wid == "Q116LeadQualify1" and n["name"] == "Settings":
                for a in n["parameters"]["assignments"]["assignments"]:
                    if a["name"] == "icp":
                        a["value"] = repo_icp()
                        found += 1
        if found != {"Q116LeadQualify1": 2, "Q116LeadReport01": 1}.get(wid, 0):
            sys.exit(f"{wid}: expected nodes not found ({found})")
        settings = {k: v for k, v in (w.get("settings") or {}).items() if k in SETTINGS_ALLOWED}
        call("PUT", f"/workflows/{wid}", {"name": new_name, "nodes": w["nodes"],
                                          "connections": w["connections"], "settings": settings})
        if was_active:
            call("POST", f"/workflows/{wid}/publish", {})
        print(f"applied: {wid} -> '{new_name}'" + (" (published)" if was_active else ""))


def cmd_export():
    for wid, fname in FILES.items():
        wf = get_wf(wid)
        out = {k: wf[k] for k in ("name", "id", "nodes", "connections", "settings") if k in wf}
        out.update(pinData={}, tags=[], active=False)
        # Same field order as the earlier CLI exports, so diffs show real changes only.
        first = ["parameters", "id", "name", "type", "typeVersion", "position", "retryOnFail",
                 "maxTries", "waitBetweenTries", "alwaysOutputData", "onError", "webhookId"]
        out["nodes"] = [{k: n[k] for k in first + sorted(set(n) - set(first)) if k in n}
                        for n in out["nodes"]]
        for node in out["nodes"]:
            node.pop("credentials", None)
            if node["name"] == "Settings":
                for a in node["parameters"]["assignments"]["assignments"]:
                    if a["name"] in ("from_email", "demo_inbox"):
                        a["value"] = ""
        text = json.dumps(out, indent=2, ensure_ascii=False) + "\n"
        # Safety net: any e-mail left that is not a fictional example.com address stops the export.
        left = {m for m in re.findall(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+", text) if not m.endswith("example.com")}
        if left:
            sys.exit(f"{wid}: unexpected e-mail-like strings {sorted(left)}")
        (ROOT / "workflows" / fname).write_text(text, encoding="utf-8", newline="\n")
        print(f"exported: {fname} ({len(out['nodes'])} nodes)")


if __name__ == "__main__":
    cmds = {"keys": cmd_keys, "check": cmd_check, "apply": cmd_apply, "export": cmd_export}
    if sys.argv[1:2] and sys.argv[1] in cmds:
        cmds[sys.argv[1]]()
    else:
        print(__doc__)
        sys.exit(2)
