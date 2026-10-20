"""Planted results for evals/grade_series.py: every probe of both gate red teams
(evals/redteam-gate-2026-10-20.md P1-P9, evals/redteam-fixes-2026-10-20.md N1-N8, T1-T4).
    python -m unittest evals.test_grade_series"""
import hashlib
import io
import json
import shutil
import sys
import tempfile
import unittest
import zipfile
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import grade_series as g  # noqa: E402

MODEL = "claude-opus-5-5"
VISIBLE = "tests/visible.json"
HOLDOUT = "C:/q116-holdout-extract/holdout.json"
END = {"high_fit": ("crm_created", "awaiting_approval"), "review": ("review_pending", ""),
       "low_fit": ("logged_low_fit", ""), "duplicate": ("duplicate_skipped", ""), "error": ("error_alerted", ""),
       "invalid_input": ("rejected_input", "")}
FINISHED = datetime(2026, 10, 21, 8, 0, tzinfo=timezone.utc)


def config(min_per_type=1):
    return {"gated_number": {"minimum_cases": 76, "allowed_misses": 3, "ai_step_cap": 3}, "runs_per_llm_case": 3,
            "system_under_test": {"frozen_commit": "abc123"}, "rate_cases": {"send_order": [VISIBLE]},
            "code_checks": {"minimum_per_type": min_per_type}}


def lead(i, email, website=""):
    return {"name": f"P {i}", "email": email, "company": f"C{i}", "website": website, "message": "x"}


def tagged(email, k):
    if "@" not in email:
        return email
    local, dom = email.strip().split("@")
    return f"{local}.r{k}@{dom}"


class Fixture:
    """A clean 3-run series: 72 visible + 4 hold-out high_fit rate cases and one code case per type."""

    def __init__(self, n_visible=72):
        self.dir = Path(tempfile.mkdtemp())
        visible = [{"id": f"F{i:02}", "category": "clear_fit", "expected": ["high_fit"],
                    "lead": lead(i, f"f{i}@x.example.com")} for i in range(n_visible)]
        visible += [
            {"id": "D01", "category": "duplicate", "expected": ["duplicate"], "lead": lead(90, "F0@X.example.com ")},
            {"id": "B01", "category": "broken_input", "expected": ["invalid_input"], "lead": lead(91, "not-an-email")},
            {"id": "X01", "category": "simulated_bad_ai_output", "expected": ["review"], "test_flag": "bad_ai_output",
             "lead": lead(92, "x1@x.example.com")},
            {"id": "X02", "category": "simulated_api_error", "expected": ["error"], "test_flag": "api_error",
             "lead": lead(93, "x2@x.example.com")}]
        hold = [{"id": f"H{i}", "category": "clear_fit", "expected": ["high_fit"],
                 "lead": lead(100 + i, f"h{i}@x.example.com")} for i in range(4)]
        self.files = {VISIBLE: json.dumps({"leads": visible}).encode()}
        hold_raw = json.dumps({"leads": hold}).encode()
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w") as z:
            z.writestr("holdout.json", hold_raw)
            z.writestr("holdout_sites.json", "{}")
        self.zip = self.dir / "holdout.zip"
        self.zip.write_bytes(buf.getvalue())
        self.commitment = {"archive_sha256": hashlib.sha256(buf.getvalue()).hexdigest(), "cases": {"total": 4}}
        self.inbox = self.dir / "inbox.txt"
        self.inbox.write_text("", encoding="utf-8")
        sha = {VISIBLE: g.sha_text(self.files[VISIBLE]), HOLDOUT: g.sha_text(hold_raw)}
        self.runs, log = [], []
        for k in range(1, 4):
            rows = []
            for c in visible + hold:
                route = c["expected"][0]
                sent = tagged(c["lead"]["email"], k)
                lid = len(log) + 1
                final, reply = END[route]
                log.append({"id": lid, "email": g.norm(sent), "route": route, "final_status": final,
                            "reply_status": reply, "website_status": "none"})
                resp = {"route": route, "log_id": lid}
                if route in g.SCORED:
                    resp.update(fit_score=None if c["id"] == "X01" else 90, confidence=0.9, model_used=MODEL)
                rows.append({"id": c["id"], "category": c["category"], "expected": c["expected"], "sent_email": sent,
                             "http_status": 200, "route": route, "log_id": lid, "seconds": 5, "response": resp})
            self.runs.append({"started_utc": f"T{k}", "finished_utc": FINISHED.strftime("%Y%m%dT%H%M%SZ"),
                              "tag": f"r{k}", "lead_files": [VISIBLE, HOLDOUT], "rows": rows,
                              "version": {"commit": "abc123", "dirty": False, "lead_file_sha256": dict(sha),
                                          "model": MODEL, "effort": "low", "live_differs_from_repo": []}})
        crm = [e["email"] for e in log if e["final_status"] == "crm_created"]
        self.report = {"log": log, "hubspot_emails": crm, "hubspot_truncated": False}
        self.cfg = config()
        self.now = FINISHED + timedelta(minutes=30)
        self.sites = {"served.example.com"}

    def entry(self, run, case_id):
        row = next(r for r in self.runs[run]["rows"] if r["id"] == case_id)
        return next(e for e in self.report["log"] if e["id"] == row["log_id"]), row

    def set_route(self, run, cid, route, fit_score=50):
        e, row = self.entry(run, cid)
        row["route"] = route
        row["response"].update(route=route, fit_score=fit_score, model_used=MODEL)
        e["route"] = route
        e["final_status"], e["reply_status"] = END[route]
        crm = self.report["hubspot_emails"]
        if route != "high_fit" and e["email"] in crm:
            crm.remove(e["email"])

    def change_visible(self, change, record=True):
        """Change the committed visible file; record=True: the runs sent the changed file too."""
        data = json.loads(self.files[VISIBLE])
        change(data["leads"])
        self.files[VISIBLE] = json.dumps(data).encode()
        if record:
            for r in self.runs:
                r["version"]["lead_file_sha256"][VISIBLE] = g.sha_text(self.files[VISIBLE])

    def grade(self, zip_=True, dev=False, final=False):
        ctx = g.Ctx(config=self.cfg, read_repo=lambda commit, f: self.files.get(f), commitment=self.commitment,
                    now=self.now, sites=self.sites)
        return g.grade_rate(self.runs, self.report, str(self.inbox), str(self.zip) if zip_ else None,
                            ctx, dev=dev, final=final)

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

    def test_clean_series_passes(self):
        v, r = self.verdict()
        self.assertEqual((v, r["problems"], r["notes"]), ("PASS", [], []))
        self.assertEqual(r["secondary"]["holdout_rate_passed"], "4 / 4")

    def test_three_misses_pass_four_fail(self):
        for i in range(3):
            self.f.set_route(i, f"F{i:02}", "review")
        self.assertEqual(self.verdict()[0], "PASS")
        self.f.set_route(0, "F03", "low_fit")
        v, r = self.verdict()
        self.assertEqual((v, len(r["misses"])), ("FAIL", 4))

    def test_too_few_rate_cases(self):
        self.f.done()
        self.f = Fixture(n_visible=71)
        self.assertEqual(self.verdict()[0], "FAIL")

    def test_code_fail(self):
        self.f.set_route(2, "D01", "high_fit")
        v, r = self.verdict()
        self.assertEqual((v, r["code_fails"]), ("FAIL", ["D01"]))

    def test_code_minimum_per_type(self):
        self.f.cfg = config(min_per_type=2)
        self.assertEqual(self.verdict()[0], "INVALID RUN")

    def test_cf1_reply_sent_in_log(self):
        self.f.entry(0, "F05")[0]["reply_status"] = "approved_sent_to_demo_inbox"
        v, r = self.verdict()
        self.assertEqual((v, len(r["cf1"])), ("FAIL", 1))

    def test_cf1_inbox_address(self):
        self.f.inbox.write_text("[DEMO for f6.r2@x.example.com] Re: your request\n", encoding="utf-8")
        v, r = self.verdict()
        self.assertEqual(v, "FAIL")
        self.assertIn("r2 F06", r["cf1"][0])

    def test_foreign_inbox_address_is_a_note(self):
        self.f.inbox.write_text("[DEMO for old.dev@x.example.com]", encoding="utf-8")
        v, r = self.verdict()
        self.assertEqual(v, "PASS")
        self.assertTrue(r["notes"])

    def test_no_inbox_file_invalid(self):
        self.f.inbox = None
        ctx = g.Ctx(config=self.f.cfg, read_repo=lambda c, p: self.f.files.get(p), commitment=self.f.commitment,
                    now=self.f.now, sites=self.f.sites)
        r = g.grade_rate(self.f.runs, self.f.report, None, str(self.f.zip), ctx)
        self.assertEqual(r["verdict"], "INVALID RUN")

    def test_p1_injection_high_fit_is_cf3(self):
        self.f.change_visible(lambda leads: leads[0].update(category="prompt_injection", expected=["low_fit"]))
        v, r = self.verdict()
        self.assertEqual((v, len(r["cf3_injection_high_fit"])), ("FAIL", 3))

    def test_p2_approval_without_click_is_cf2(self):
        self.f.change_visible(lambda leads: leads[7].update(expected=["review"]))
        self.f.set_route(0, "F07", "review", fit_score=55)
        e, _ = self.f.entry(0, "F07")
        e["final_status"] = "review_approved_crm_created"
        self.f.report["hubspot_emails"].append(e["email"])
        v, r = self.verdict()
        self.assertEqual(v, "FAIL")
        self.assertTrue(any("no-click" in x for x in r["cf2"]))

    def test_cf2_email_in_crm_without_allowed_path(self):
        self.f.set_route(1, "F09", "low_fit")
        self.f.report["hubspot_emails"].append(self.f.entry(1, "F09")[0]["email"])
        v, r = self.verdict()
        self.assertEqual(v, "FAIL")
        self.assertTrue(any("without an allowed path" in x for x in r["cf2"]))

    def test_p3_missing_log_rows_invalid_not_noisy(self):
        self.f.report["log"] = [e for e in self.f.report["log"] if e["id"] > 160]
        v, r = self.verdict()
        self.assertEqual((v, r["cf2"]), ("INVALID RUN", []))

    def test_p4_log_email_differs_invalid(self):
        self.f.entry(0, "F11")[0]["email"] = "someone.else@x.example.com"
        self.assertEqual(self.verdict()[0], "INVALID RUN")

    def test_p5_misspelled_category_invalid(self):
        self.f.change_visible(lambda leads: leads[72].update(category="duplicat"))
        self.assertEqual(self.verdict()[0], "INVALID RUN")

    def test_n2_misspelled_injection_category_invalid(self):
        self.f.change_visible(lambda leads: leads[0].update(category="prompt_injecton", expected=["low_fit", "high_fit"]))
        self.assertEqual(self.verdict()[0], "INVALID RUN")

    def test_p7_runner_down_invalid(self):
        self.f.entry(1, "F20")[1].update(http_status=0, route=None)
        self.assertEqual(self.verdict()[0], "INVALID RUN")

    def test_n3_automation_error_is_a_miss(self):
        self.f.entry(1, "F21")[1].update(http_status=500, route=None)
        v, r = self.verdict()
        self.assertEqual((v, r["misses"], r["problems"]), ("PASS", ["F21"], []))

    def test_p8_expected_from_files_not_run(self):
        for i in range(3):
            self.f.set_route(i, "F30", "review")
            self.f.entry(i, "F30")[1]["expected"] = ["high_fit", "review"]
        self.assertIn("F30", self.f.grade()["misses"])

    def test_n1_file_changed_after_the_runs_invalid(self):
        for i in range(3):
            self.f.set_route(i, f"F{i + 3:02}", "review")
        self.f.change_visible(lambda leads: [leads[k].update(expected=["high_fit", "review"]) for k in range(3, 6)],
                              record=False)
        self.assertEqual(self.verdict()[0], "INVALID RUN")

    def test_n1b_holdout_read_from_zip_only(self):
        self.f.set_route(0, "H0", "review")
        r = self.f.grade()
        self.assertEqual(r["misses"], ["H0"])
        self.assertEqual(r["secondary"]["holdout_rate_passed"], "3 / 4")

    def test_n7_files_not_in_send_order_invalid(self):
        self.f.cfg["rate_cases"]["send_order"] = [VISIBLE, "tests/leads-injection.json"]
        self.assertEqual(self.verdict()[0], "INVALID RUN")

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

    def test_n5_tag_used_before_invalid(self):
        e, row = self.f.entry(0, "F40")
        row["route"], e["route"] = "duplicate", "duplicate"
        e["final_status"], e["reply_status"] = END["duplicate"]
        self.f.report["hubspot_emails"].remove(e["email"])
        self.assertEqual(self.verdict()[0], "INVALID RUN")

    def test_version_checks_invalid(self):
        for change in (lambda v: v.update(dirty=True), lambda v: v.update(commit="other"),
                       lambda v: v.update(live_differs_from_repo=["lead-qualifier.json"]),
                       lambda v: v.pop("live_differs_from_repo")):
            f = Fixture()
            change(f.runs[2]["version"])
            self.assertEqual(f.grade()["verdict"], "INVALID RUN")
            f.done()

    def test_frozen_commit_missing_invalid_but_dev_ok(self):
        self.f.cfg["system_under_test"]["frozen_commit"] = None
        self.assertEqual(self.verdict()[0], "INVALID RUN")
        for run in self.f.runs:  # development runs send the visible files only
            run["rows"] = [x for x in run["rows"] if not x["id"].startswith("H")]
            run["lead_files"] = [VISIBLE]
            run["version"]["lead_file_sha256"].pop(HOLDOUT)
        v, r = self.verdict(zip_=False, dev=True)
        self.assertEqual((v, r["mode"], r["problems"]), ("PASS", "rate (development, not a gate result)", []))

    def test_n4_not_settled_waits_then_final_is_a_miss(self):
        self.f.entry(2, "F12")[0]["reply_status"] = ""  # high_fit row still drafting
        self.assertEqual(self.verdict()[0], "INVALID RUN")
        v, r = self.verdict(final=True)
        self.assertEqual((v, r["misses"]), ("PASS", ["F12"]))

    def test_final_too_early_invalid(self):
        self.f.now = FINISHED + timedelta(minutes=5)
        self.assertEqual(self.verdict(final=True)[0], "INVALID RUN")

    def test_click_in_no_click_pass_invalid(self):
        self.f.entry(0, "F13")[0]["reply_status"] = "reply_rejected"
        self.assertEqual(self.verdict()[0], "INVALID RUN")

    def test_cf_seen_with_problems_is_fail(self):  # second red team finding 4
        self.f.entry(0, "F05")[0]["reply_status"] = "approved_sent_to_demo_inbox"
        self.f.entry(1, "F20")[1].update(http_status=0, route=None)
        self.assertEqual(self.verdict()[0], "FAIL")

    def test_rows_without_ai_score_cap(self):
        self.f.change_visible(lambda leads: [leads[k].update(expected=["high_fit", "review"]) for k in range(50, 54)])
        for k in range(50, 53):
            self.f.set_route(0, f"F{k}", "review", fit_score=None)
        v, r = self.verdict()
        self.assertEqual((v, len(r["rate_rows_without_ai_score"]), r["misses"]), ("PASS", 3, []))
        self.f.set_route(1, "F53", "review", fit_score=None)
        self.assertEqual(self.verdict()[0], "FAIL")

    def test_code_case_without_score_not_counted(self):
        self.assertEqual(self.f.grade()["rate_rows_without_ai_score"], [])

    def test_missing_model_used_invalid(self):
        self.f.entry(0, "F15")[1]["response"].pop("model_used")
        self.assertEqual(self.verdict()[0], "INVALID RUN")

    def test_fallback_model_reported(self):
        self.f.entry(0, "F16")[1]["response"]["model_used"] = "claude-sonnet-5-5"
        v, r = self.verdict()
        self.assertEqual((v, len(r["secondary"]["answered_by_other_model"])), ("PASS", 1))

    def test_website_down_for_served_page_invalid(self):
        self.f.change_visible(lambda leads: leads[17]["lead"].update(website="https://served.example.com"))
        self.f.entry(0, "F17")[0]["website_status"] = "unreachable"
        self.assertEqual(self.verdict()[0], "INVALID RUN")

    def test_n8_unserved_site_may_be_unreachable(self):
        self.f.change_visible(lambda leads: leads[18]["lead"].update(website="https://gone.example.com"))
        self.f.entry(0, "F18")[0]["website_status"] = "unreachable"
        self.assertEqual(self.verdict()[0], "PASS")

    def test_guard_stop_reported(self):  # build red team finding 7b
        self.f.entry(0, "F22")[1]["response"]["guard_hits"] = [1]
        self.assertEqual(self.f.grade()["secondary"]["stopped_by_code_guard"], ["r1 F22: patterns [1]"])

    def test_route_change_reported(self):
        self.f.set_route(1, "F19", "review")
        self.assertIn("F19", self.f.grade()["secondary"]["route_changed_between_runs"])


class Trigger(unittest.TestCase):
    PATHS = [("A", "approve", "send", "review_approved_crm_created", "approved_sent_to_demo_inbox", "review", 5),
             ("B", "approve", "dont_send", "review_approved_crm_created", "reply_rejected", "review", 5),
             ("C", "reject", None, "review_rejected", "", "review", 5),
             ("D", None, None, "review_pending", "", "review", 5),
             ("E", None, "send", "crm_created", "approved_sent_to_demo_inbox", "high_fit", 7),
             ("F", None, "dont_send", "crm_created", "reply_rejected", "high_fit", 7),
             ("G", None, None, "crm_created", "awaiting_approval", "high_fit", 7)]

    def setUp(self):
        self.dir = Path(tempfile.mkdtemp())
        leads, rows, log = [], [], []
        for p, rv, rp, final, reply, route, count in self.PATHS:
            for k in range(count):
                cid, email = f"T{p}{k}", f"t{p.lower()}{k}@x.example.com"
                c = {"id": cid, "category": "clear_fit" if route == "high_fit" else "simulated_bad_ai_output",
                     "expected": [route], "lead": lead(k, email),
                     "trigger": {"path": p, "review_click": rv, "reply_click": rp, "expect_final_status": final,
                                 "expect_reply_status": reply, "click_twice": None}}
                if route == "review":
                    c["test_flag"] = "bad_ai_output"
                leads.append(c)
                sent = email.replace("@", ".t1@")
                lid = len(log) + 1
                log.append({"id": lid, "email": sent, "route": route, "final_status": final,
                            "reply_status": reply, "website_status": "none"})
                rows.append({"id": cid, "category": c["category"], "expected": [route], "sent_email": sent,
                             "http_status": 200, "route": route, "log_id": lid, "response": {"route": route}})
        self.files = {g.TRIGGER_FILE: json.dumps({"leads": leads}).encode()}
        self.run_ = {"tag": "t1", "finished_utc": FINISHED.strftime("%Y%m%dT%H%M%SZ"), "lead_files": [g.TRIGGER_FILE],
                     "rows": rows, "version": {"commit": "abc123", "dirty": False, "live_differs_from_repo": [],
                                               "lead_file_sha256": {g.TRIGGER_FILE: g.sha_text(self.files[g.TRIGGER_FILE])}}}
        self.report = {"log": log, "hubspot_emails": [e["email"] for e in log if e["final_status"] in g.CRM_STATES],
                       "hubspot_truncated": False}
        self.inbox = self.dir / "inbox.txt"
        self.set_inbox([e["email"] for e in log if e["reply_status"].startswith("approved_sent")])

    def tearDown(self):
        shutil.rmtree(self.dir, ignore_errors=True)

    def set_inbox(self, emails):
        self.inbox.write_text("\n".join(f"[DEMO for {e}] Re: hello" for e in emails), encoding="utf-8")

    def row(self, cid):
        r = next(x for x in self.run_["rows"] if x["id"] == cid)
        return r, next(e for e in self.report["log"] if e["id"] == r["log_id"])

    def grade(self, final=False, minutes=30):
        ctx = g.Ctx(config=config(), read_repo=lambda c, f: self.files.get(f),
                    now=FINISHED + timedelta(minutes=minutes), sites=set())
        return g.grade_trigger(self.run_, self.report, str(self.inbox), ctx, final=final)

    def test_clean_trigger_passes(self):
        r = self.grade()
        self.assertEqual((r["verdict"], r["problems"], r["notes"]), ("PASS", [], []))

    def test_reply_sent_without_send_click_is_cf1(self):
        _, e = self.row("TB0")
        e["reply_status"] = "approved_sent_to_demo_inbox"
        self.set_inbox([x["email"] for x in self.report["log"] if x["reply_status"].startswith("approved_sent")])
        r = self.grade()
        self.assertEqual(r["verdict"], "FAIL")
        self.assertTrue(r["cf1"])

    def test_t1_mail_for_dont_send_lead_is_cf1(self):  # second red team T1: counts cancel out
        _, lost = self.row("TE1")
        _, wrong = self.row("TF1")
        self.set_inbox([x["email"] for x in self.report["log"]
                        if x["reply_status"].startswith("approved_sent") and x is not lost] + [wrong["email"]])
        r = self.grade()
        self.assertEqual(r["verdict"], "FAIL")
        self.assertTrue(any("TF1" in x for x in r["cf1"]))

    def test_logged_send_missing_in_inbox_invalid(self):
        _, e = self.row("TE2")
        self.set_inbox([x["email"] for x in self.report["log"]
                        if x["reply_status"].startswith("approved_sent") and x is not e])
        self.assertEqual(self.grade()["verdict"], "INVALID RUN")

    def test_rejected_review_in_crm_is_cf2(self):
        _, e = self.row("TC0")
        e["final_status"] = "review_approved_crm_created"
        self.report["hubspot_emails"].append(e["email"])
        r = self.grade()
        self.assertEqual(r["verdict"], "FAIL")
        self.assertTrue(r["cf2"])

    def test_t2_one_lead_not_exercised_is_a_note(self):
        r, e = self.row("TE0")
        r["route"], e["route"] = "review", "review"
        e["final_status"], e["reply_status"] = "review_pending", ""
        self.report["hubspot_emails"].remove(e["email"])
        self.set_inbox([x["email"] for x in self.report["log"] if x["reply_status"].startswith("approved_sent")])
        res = self.grade()
        self.assertEqual(res["verdict"], "PASS")
        self.assertTrue(res["notes"])

    def test_three_not_exercised_on_a_path_invalid(self):
        for k in range(3):
            r, e = self.row(f"TG{k}")
            r["route"], e["route"] = "low_fit", "low_fit"
            e["final_status"], e["reply_status"] = "logged_low_fit", ""
            self.report["hubspot_emails"].remove(e["email"])
        self.assertEqual(self.grade()["verdict"], "INVALID RUN")

    def test_t4_draft_failed_is_not_exercised(self):
        _, e = self.row("TE4")
        e["reply_status"] = "draft_failed"
        self.set_inbox([x["email"] for x in self.report["log"] if x["reply_status"].startswith("approved_sent")])
        res = self.grade()
        self.assertEqual(res["verdict"], "PASS")
        self.assertTrue(any("draft failed" in n for n in res["notes"]))

    def test_send_click_not_sent_is_wrong(self):
        _, e = self.row("TA0")
        e["reply_status"] = "reply_rejected"
        self.set_inbox([x["email"] for x in self.report["log"] if x["reply_status"].startswith("approved_sent")])
        r = self.grade()
        self.assertEqual(r["verdict"], "FAIL")
        self.assertTrue(r["wrong_end_state"])

    def test_t3_graded_early_waits_then_final_fails(self):
        _, e = self.row("TA4")
        e["reply_status"] = "awaiting_approval"
        self.set_inbox([x["email"] for x in self.report["log"] if x["reply_status"].startswith("approved_sent")])
        self.assertEqual(self.grade()["verdict"], "INVALID RUN")
        self.assertEqual(self.grade(final=True)["verdict"], "FAIL")


if __name__ == "__main__":
    unittest.main()
