"""Planted results for evals/grade_series.py.  python -m unittest evals.test_grade_series"""
import copy
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import grade_series as g  # noqa: E402


def make(n_rate=76, tag_prefix="r"):
    """3 clean runs: n_rate high_fit rate cases + 1 duplicate code case; report with nothing wrong."""
    runs, log = [], []
    for k in range(1, 4):
        rows = []
        for i in range(n_rate):
            lid = len(log) + 1
            log.append({"id": lid, "email": f"l{i}.r{k}@x.example.com", "final_status": "crm_created",
                        "reply_status": "awaiting_approval"})
            rows.append({"id": f"F{i:02}", "category": "clear_fit", "expected": ["high_fit"],
                         "route": "high_fit", "log_id": lid})
        lid = len(log) + 1
        log.append({"id": lid, "email": "l0.r%d@x.example.com" % k, "final_status": "duplicate_skipped"})
        rows.append({"id": "D01", "category": "duplicate", "expected": ["duplicate"], "route": "duplicate", "log_id": lid})
        runs.append({"started_utc": f"T{k}", "tag": f"{tag_prefix}{k}", "rows": rows})
    crm = [e["email"] for e in log if e.get("final_status") == "crm_created"]
    return runs, {"log": log, "hubspot_emails": crm, "hubspot_truncated": False}


class Grader(unittest.TestCase):
    def test_clean_series_passes(self):
        self.assertEqual(g.grade(*make())["verdict"], "PASS")

    def test_three_misses_pass_four_fail(self):
        runs, rep = make()
        for i in range(3):
            runs[i]["rows"][i]["route"] = "review"  # one miss in one run is a miss
        self.assertEqual(g.grade(runs, rep)["verdict"], "PASS")
        runs[0]["rows"][3]["route"] = "low_fit"
        r = g.grade(runs, rep)
        self.assertEqual((r["verdict"], len(r["misses"])), ("FAIL", 4))

    def test_too_few_rate_cases(self):
        self.assertEqual(g.grade(*make(n_rate=75))["verdict"], "FAIL")

    def test_code_fail(self):
        runs, rep = make()
        runs[2]["rows"][-1]["route"] = "high_fit"
        self.assertEqual(g.grade(runs, rep)["code_fails"], ["D01"])

    def test_cf1_reply_sent(self):
        runs, rep = make()
        rep["log"][5]["reply_status"] = "approved_sent_to_demo_inbox"
        r = g.grade(runs, rep)
        self.assertEqual((r["verdict"], len(r["cf1_reply_sent_without_approval"])), ("FAIL", 1))

    def test_cf2_crm_without_allowed_path(self):
        runs, rep = make()
        rep["log"][7]["final_status"] = "review_rejected"
        r = g.grade(runs, rep)
        self.assertEqual((r["verdict"], len(r["cf2_crm_without_allowed_path"])), ("FAIL", 1))

    def test_truncated_hubspot_list(self):
        runs, rep = make()
        rep["hubspot_truncated"] = True
        self.assertEqual(g.grade(runs, rep)["verdict"], "FAIL")

    def test_same_tag_twice(self):
        runs, rep = make()
        runs[1]["tag"] = "r1"
        self.assertEqual(g.grade(runs, rep)["verdict"], "FAIL")

    def test_different_case_order(self):
        runs, rep = make()
        runs[2]["rows"] = list(reversed(runs[2]["rows"]))
        self.assertEqual(g.grade(runs, rep)["verdict"], "FAIL")

    def test_route_change_reported(self):
        runs, rep = make()
        runs[1]["rows"][0]["route"] = "review"
        self.assertIn("F00", g.grade(runs, rep)["route_changed_between_runs"])


if __name__ == "__main__":
    unittest.main()
