"""Planted results for evals/grade_series.py, including every probe of the gate red team
(evals/redteam-gate-2026-10-20.md, P1-P9).  python -m unittest evals.test_grade_series"""
import copy
import hashlib
import io
import json
import shutil
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import grade_series as g  # noqa: E402

MODEL = "claude-opus-5-5"
CONFIG = {"gated_number": {"minimum_cases": 76, "allowed_misses": 3}, "runs_per_llm_case": 3,
          "system_under_test": {"frozen_commit": "abc123"}}
END = {"high_fit": ("crm_created", "awaiting_approval"), "review": ("review_pending", ""),
       "low_fit": ("logged_low_fit", ""), "duplicate": ("duplicate_skipped", ""), "error": ("error_alerted", "")}


def lead(i, email):
    return {"name": f"P {i}", "email": email, "company": f"C{i}", "website": "", "message": "x"}


class Fixture:
    """A clean 3-run series: 72 visible + 4 hold-out high_fit rate cases, 1 duplicate code case."""

    def __init__(self, n_visible=72):
        self.dir = Path(tempfile.mkdtemp())
        visible = [{"id": f"F{i:02}", "category": "clear_fit", "expected": ["high_fit"],
                    "lead": lead(i, f"f{i}@x.example.com")} for i in range(n_visible)]
        visible.append({"id": "D01", "category": "duplicate", "expected": ["duplicate"],
                        "lead": lead(99, "F0@X.example.com ")})
        hold = [{"id": f"H{i}", "category": "clear_fit", "expected": ["high_fit"],
                 "lead": lead(100 + i, f"h{i}@x.example.com")} for i in range(4)]
        self.vfile, self.hfile = self.dir / "visible.json", self.dir / "holdout.json"
        self.vfile.write_text(json.dumps({"leads": visible}), encoding="utf-8")
        self.hfile.write_text(json.dumps({"leads": hold}), encoding="utf-8")
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w") as z:
            z.writestr("holdout.json", self.hfile.read_bytes())
        self.zip = self.dir / "holdout.zip"
        self.zip.write_bytes(buf.getvalue())
        self.commitment = {"archive_sha256": hashlib.sha256(buf.getvalue()).hexdigest(), "cases": {"total": 4}}
        files = [str(self.vfile), str(self.hfile)]
        sha = {f: g.sha_text(Path(f).read_bytes()) for f in files}
        self.runs, log = [], []
        for k in range(1, 4):
            rows = []
            for c in visible + hold:
                route = c["expected"][0]
                email = c["lead"]["email"].strip()
                local, dom = email.split("@")
                sent = f"{local}.r{k}@{dom}"
                lid = len(log) + 1
                final, reply = END[route]
                log.append({"id": lid, "email": g.norm(sent), "route": route, "final_status": final,
                            "reply_status": reply, "website_status": "none"})
                resp = {"route": route, "log_id": lid}
                if route in g.SCORED:
                    resp.update(fit_score=90, confidence=0.9, model_used=MODEL)
                rows.append({"id": c["id"], "category": c["category"], "expected": c["expected"], "sent_email": sent,
                             "http_status": 200, "route": route, "log_id": lid, "seconds": 5, "response": resp})
            self.runs.append({"started_utc": f"T{k}", "tag": f"r{k}", "lead_files": files, "rows": rows,
                              "version": {"commit": "abc123", "dirty": False, "lead_file_sha256": sha,
                                          "model": MODEL, "effort": "low", "live_differs_from_repo": []}})
        crm = [e["email"] for e in log if e["final_status"] == "crm_created"]
        self.report = {"log": log, "hubspot_emails": crm, "hubspot_truncated": False}

    def entry(self, run, case_id):
        row = next(r for r in self.runs[run]["rows"] if r["id"] == case_id)
        return next(e for e in self.report["log"] if e["id"] == row["log_id"]), row

    def rewrite(self, path, change):
        data = json.loads(Path(path).read_text(encoding="utf-8"))
        change(data["leads"])
        Path(path).write_text(json.dumps(data), encoding="utf-8")
        for r in self.runs:
            r["version"]["lead_file_sha256"][str(path)] = g.sha_text(Path(path).read_bytes())

    def grade(self, inbox=0, zip_=True):
        return g.grade_rate(self.runs, self.report, inbox, str(self.zip) if zip_ else None, CONFIG, self.commitment)

    def done(self):
        shutil.rmtree(self.dir, ignore_errors=True)


class Rate(unittest.TestCase):
    def setUp(self):
        self.f = Fixture()

    def tearDown(self):
        self.f.done()

    def verdict(self, **kw):
        r = self.f.grade(**kw)
        return r["verdict"], r

    def set_route(self, run, cid, route, fit_score=50):
        e, row = self.f.entry(run, cid)
        row["route"] = route
        row["response"].update(route=route, fit_score=fit_score, model_used=MODEL)
        e["route"] = route
        e["final_status"], e["reply_status"] = END[route]
        crm = self.f.report["hubspot_emails"]
        if route != "high_fit" and e["email"] in crm:
            crm.remove(e["email"])
        elif route == "high_fit" and e["email"] not in crm:
            crm.append(e["email"])

    def test_clean_series_passes(self):
        v, r = self.verdict()
        self.assertEqual((v, r["problems"]), ("PASS", []))
        self.assertEqual(r["secondary"]["holdout_rate_passed"], "4 / 4")

    def test_three_misses_pass_four_fail(self):
        for i in range(3):
            self.set_route(i, f"F{i:02}", "review")
        self.assertEqual(self.verdict()[0], "PASS")
        self.set_route(0, "F03", "low_fit")
        v, r = self.verdict()
        self.assertEqual((v, len(r["misses"])), ("FAIL", 4))

    def test_too_few_rate_cases(self):
        self.f.done()
        self.f = Fixture(n_visible=71)
        self.assertEqual(self.verdict()[0], "FAIL")

    def test_code_fail(self):
        self.set_route(2, "D01", "high_fit")
        v, r = self.verdict()
        self.assertEqual((v, r["code_fails"]), ("FAIL", ["D01"]))

    def test_cf1_reply_sent_in_log(self):
        self.f.entry(0, "F05")[0]["reply_status"] = "approved_sent_to_demo_inbox"
        v, r = self.verdict()
        self.assertEqual((v, len(r["cf1"])), ("FAIL", 1))

    def test_cf1_inbox_count(self):
        self.assertEqual(self.verdict(inbox=1)[0], "FAIL")

    def test_p1_injection_high_fit_is_cf3(self):
        self.f.rewrite(self.f.vfile, lambda leads: leads[0].update(category="prompt_injection", expected=["low_fit"]))
        for i in range(3):
            self.f.entry(i, "F00")[1]["category"] = "prompt_injection"
        v, r = self.verdict()
        self.assertEqual((v, len(r["cf3_injection_high_fit"])), ("FAIL", 3))

    def test_p2_approval_without_click_is_cf2(self):
        self.set_route(0, "F07", "review", fit_score=55)
        self.f.rewrite(self.f.vfile, lambda leads: leads[7].update(expected=["review"]))
        e, row = self.f.entry(0, "F07")
        e["final_status"] = "review_approved_crm_created"
        self.f.report["hubspot_emails"].append(e["email"])
        v, r = self.verdict()
        self.assertEqual(v, "FAIL")
        self.assertTrue(any("no-click" in x for x in r["cf2"]))

    def test_cf2_email_in_crm_without_allowed_path(self):
        self.set_route(1, "F09", "low_fit")
        self.f.report["hubspot_emails"].append(self.f.entry(1, "F09")[0]["email"])
        v, r = self.verdict()
        self.assertEqual(v, "FAIL")
        self.assertTrue(any("without an allowed path" in x for x in r["cf2"]))

    def test_p3_missing_log_rows_invalid(self):
        self.f.report["log"] = [e for e in self.f.report["log"] if e["id"] > 80]
        self.assertEqual(self.verdict()[0], "INVALID RUN")

    def test_p4_log_email_differs_invalid(self):
        self.f.entry(0, "F11")[0]["email"] = "someone.else@x.example.com"
        self.assertEqual(self.verdict()[0], "INVALID RUN")

    def test_p5_misspelled_category_invalid(self):
        self.f.rewrite(self.f.vfile, lambda leads: leads[-1].update(category="duplicat"))
        self.assertEqual(self.verdict()[0], "INVALID RUN")

    def test_p7_runner_down_invalid(self):
        row = self.f.entry(1, "F20")[1]
        row.update(http_status=0, route=None)
        self.assertEqual(self.verdict()[0], "INVALID RUN")

    def test_p8_expected_from_files_not_run(self):
        for i in range(3):
            self.set_route(i, "F30", "review")
            self.f.entry(i, "F30")[1]["expected"] = ["high_fit", "review"]
        self.assertIn("F30", self.f.grade()["misses"])

    def test_p9_holdout_not_sent_invalid(self):
        for r in self.f.runs:
            r["rows"] = [x for x in r["rows"] if not x["id"].startswith("H")]
        self.assertEqual(self.verdict()[0], "INVALID RUN")

    def test_holdout_zip_changed_invalid(self):
        self.f.commitment["archive_sha256"] = "0" * 64
        self.assertEqual(self.verdict()[0], "INVALID RUN")

    def test_no_holdout_zip_invalid(self):
        self.assertEqual(self.verdict(zip_=False)[0], "INVALID RUN")

    def test_hubspot_truncated_invalid(self):
        self.f.report["hubspot_truncated"] = True
        self.assertEqual(self.verdict()[0], "INVALID RUN")

    def test_same_tag_invalid(self):
        self.f.runs[1]["tag"] = "r1"
        self.assertEqual(self.verdict()[0], "INVALID RUN")

    def test_version_checks_invalid(self):
        for change in (lambda v: v.update(dirty=True), lambda v: v.update(commit="other"),
                       lambda v: v.update(live_differs_from_repo=["lead-qualifier.json"]),
                       lambda v: v.pop("live_differs_from_repo")):
            f = Fixture()
            change(f.runs[2]["version"])
            self.assertEqual(f.grade()["verdict"], "INVALID RUN")
            f.done()

    def test_not_settled_invalid(self):
        self.f.entry(0, "F12")[0]["final_status"] = "crm_pending"
        self.assertEqual(self.verdict()[0], "INVALID RUN")

    def test_click_in_no_click_pass_invalid(self):
        self.f.entry(0, "F13")[0]["reply_status"] = "reply_rejected"
        self.assertEqual(self.verdict()[0], "INVALID RUN")

    def test_review_without_ai_score_is_miss(self):
        self.f.rewrite(self.f.vfile, lambda leads: leads[14].update(expected=["review"]))
        for i in range(3):
            self.set_route(i, "F14", "review", fit_score=None)
        self.assertIn("F14", self.f.grade()["misses"])

    def test_missing_model_used_invalid(self):
        self.f.entry(0, "F15")[1]["response"].pop("model_used")
        self.assertEqual(self.verdict()[0], "INVALID RUN")

    def test_fallback_model_reported(self):
        self.f.entry(0, "F16")[1]["response"]["model_used"] = "claude-sonnet-5-5"
        v, r = self.verdict()
        self.assertEqual((v, len(r["secondary"]["answered_by_other_model"])), ("PASS", 1))

    def test_website_down_invalid(self):
        self.f.rewrite(self.f.vfile, lambda leads: leads[17]["lead"].update(website="https://c17.example.com"))
        self.f.entry(0, "F17")[0]["website_status"] = "unreachable"
        self.assertEqual(self.verdict()[0], "INVALID RUN")

    def test_route_change_reported(self):
        self.set_route(1, "F18", "review")
        self.assertIn("F18", self.f.grade()["secondary"]["route_changed_between_runs"])


class Trigger(unittest.TestCase):
    PATHS = [("A", "approve", "send", "review_approved_crm_created", "approved_sent_to_demo_inbox", "review"),
             ("B", "approve", "dont_send", "review_approved_crm_created", "reply_rejected", "review"),
             ("C", "reject", None, "review_rejected", "", "review"),
             ("D", None, None, "review_pending", "", "review"),
             ("E", None, "send", "crm_created", "approved_sent_to_demo_inbox", "high_fit"),
             ("F", None, "dont_send", "crm_created", "reply_rejected", "high_fit"),
             ("G", None, None, "crm_created", "awaiting_approval", "high_fit")]

    def setUp(self):
        self.dir = Path(tempfile.mkdtemp())
        leads, rows, log = [], [], []
        for p, rv, rp, final, reply, route in self.PATHS:
            for k in range(5):
                cid, email = f"T{p}{k}", f"t{p.lower()}{k}@x.example.com"
                c = {"id": cid, "category": "clear_fit" if route == "high_fit" else "simulated_bad_ai_output",
                     "expected": [route], "lead": lead(k, email),
                     "trigger": {"path": p, "review_click": rv, "reply_click": rp, "expect_final_status": final,
                                 "expect_reply_status": reply, "click_twice": False}}
                if route == "review":
                    c["test_flag"] = "bad_ai_output"
                leads.append(c)
                lid = len(log) + 1
                log.append({"id": lid, "email": email.replace("@", ".t1@"), "route": route, "final_status": final,
                            "reply_status": reply, "website_status": "none"})
                rows.append({"id": cid, "category": c["category"], "expected": [route],
                             "sent_email": email.replace("@", ".t1@"), "http_status": 200, "route": route,
                             "log_id": lid, "response": {"route": route}})
        f = self.dir / "trigger.json"
        f.write_text(json.dumps({"leads": leads}), encoding="utf-8")
        self.run_ = {"tag": "t1", "lead_files": [str(f)], "rows": rows,
                     "version": {"commit": "abc123", "dirty": False, "live_differs_from_repo": [],
                                 "lead_file_sha256": {str(f): g.sha_text(f.read_bytes())}}}
        crm = [e["email"] for e in log if e["final_status"] in g.CRM_STATES]
        self.report = {"log": log, "hubspot_emails": crm, "hubspot_truncated": False}

    def tearDown(self):
        shutil.rmtree(self.dir, ignore_errors=True)

    def grade(self, inbox=10):
        return g.grade_trigger(self.run_, self.report, inbox, CONFIG)

    def test_clean_trigger_passes(self):
        r = self.grade()
        self.assertEqual((r["verdict"], r["problems"]), ("PASS", []))

    def test_reply_sent_without_send_click_is_cf1(self):
        self.report["log"][5]["reply_status"] = "approved_sent_to_demo_inbox"  # path B
        r = self.grade(inbox=11)
        self.assertEqual(r["verdict"], "FAIL")
        self.assertTrue(r["cf1"])

    def test_extra_inbox_mail_is_cf1(self):
        self.assertEqual(self.grade(inbox=11)["verdict"], "FAIL")

    def test_rejected_review_in_crm_is_cf2(self):
        e = self.report["log"][10]  # path C
        e["final_status"] = "review_approved_crm_created"
        self.report["hubspot_emails"].append(e["email"])
        r = self.grade()
        self.assertEqual(r["verdict"], "FAIL")
        self.assertTrue(r["cf2"])

    def test_not_exercised_makes_path_short(self):
        row = self.run_["rows"][20]  # path E
        row["route"] = "review"
        self.report["log"][20]["route"] = "review"
        self.assertEqual(self.grade()["verdict"], "INVALID RUN")

    def test_send_click_not_sent_is_wrong(self):
        self.report["log"][0]["reply_status"] = "reply_rejected"  # Send clicked, nothing sent
        r = self.grade(inbox=9)
        self.assertEqual(r["verdict"], "FAIL")
        self.assertTrue(r["wrong_end_state"])


if __name__ == "__main__":
    unittest.main()
