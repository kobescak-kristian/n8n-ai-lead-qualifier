"""Plants each mistake that tests/check_cases.py must catch.  python -m unittest tests.test_check_cases"""
import copy
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import check_cases  # noqa: E402

GOOD = [
    {"id": "F01", "category": "clear_fit", "expected": ["high_fit"],
     "lead": {"email": "laura@northwind.example.com"}},
    {"id": "X01", "category": "simulated_api_error", "expected": ["error"], "test_flag": "api_error",
     "lead": {"email": "henry@copperfield.example.com"}},
    {"id": "D01", "category": "duplicate", "expected": ["duplicate"],
     "lead": {"email": "  Laura@Northwind.EXAMPLE.com "}},
]


def run(cases):
    return check_cases.check([("planted.json", c) for c in cases])


class PlantedMistakes(unittest.TestCase):
    def test_clean_set_passes(self):
        self.assertEqual(run(GOOD), [])

    def test_visible_set_passes(self):
        root = Path(__file__).resolve().parent
        files = [root / "leads.json", root / "leads-set2.json", root / "leads-code.json"]
        self.assertEqual(check_cases.check(check_cases.load(files)), [])

    def test_invalid_form_does_not_take_email(self):
        cases = copy.deepcopy(GOOD)
        cases.insert(0, {"id": "B01", "category": "broken_input", "expected": ["invalid_input"],
                         "lead": {"email": "laura@northwind.example.com"}})
        self.assertEqual(run(cases), [])

    def test_error_case_releases_email(self):  # workflow clears lead_key after an AI error
        cases = [{"id": "X1", "category": "simulated_api_error", "expected": ["error"], "test_flag": "api_error",
                  "lead": {"email": "a@b.example.com"}},
                 {"id": "X2", "category": "simulated_api_error", "expected": ["error"], "test_flag": "api_error",
                  "lead": {"email": "a@b.example.com"}}]
        self.assertEqual(run(cases), [])

    def test_duplicate_of_invalid_only(self):
        cases = [{"id": "B01", "category": "broken_input", "expected": ["invalid_input"],
                  "lead": {"email": "a@b.example.com"}},
                 {"id": "D01", "category": "duplicate", "expected": ["duplicate"], "lead": {"email": "a@b.example.com"}}]
        self.assertTrue(any("is missing" in p for p in run(cases)))

    def plant(self, change, expect):
        cases = copy.deepcopy(GOOD)
        change(cases)
        problems = run(cases)
        self.assertTrue(any(expect in p for p in problems), problems)

    def test_duplicate_id(self):
        self.plant(lambda c: c[1].update(id="F01"), "case ID used 2 times")

    def test_unknown_route(self):
        self.plant(lambda c: c[0].update(expected=["hot_lead"]), "does not exist")

    def test_empty_expected(self):
        self.plant(lambda c: c[0].update(expected=[]), "non-empty list")

    def test_same_email_not_duplicate(self):
        self.plant(lambda c: c[1]["lead"].update(email="LAURA@northwind.example.com"), "not a duplicate case")

    def test_duplicate_before_original(self):
        self.plant(lambda c: c.insert(0, c.pop()), "comes later")

    def test_duplicate_original_missing(self):
        self.plant(lambda c: c.pop(0), "is missing")

    def test_duplicate_wrong_expected(self):
        self.plant(lambda c: c[2].update(expected=["duplicate", "review"]), "exactly ['duplicate']")

    def test_misspelled_code_category(self):  # red team P5: would become a rate case
        self.plant(lambda c: c[1].update(category="simulated_api_eror"), "only expect high_fit / low_fit / review")

    def test_rate_case_allows_error(self):  # red team P6
        self.plant(lambda c: c[0].update(expected=["review", "error"]), "only expect high_fit / low_fit / review")

    def test_unknown_category(self):  # second red team N2: misspelled injection category escaped CF3
        self.plant(lambda c: c[0].update(category="prompt_injecton"), "unknown category")

    def test_flag_on_rate_case(self):  # red team P6
        self.plant(lambda c: c[0].update(test_flag="bad_ai_output"), "not simulated_*")

    def test_simulated_wrong_route(self):
        self.plant(lambda c: c[1].update(expected=["review"]), "exactly ['error']")

    def test_injection_allows_high_fit(self):
        self.plant(lambda c: c[0].update(category="prompt_injection", expected=["high_fit", "review"]),
                   "never allow high_fit")

    def test_simulated_without_flag(self):
        self.plant(lambda c: c[1].pop("test_flag"), "needs test_flag")

    def test_unknown_flag(self):
        self.plant(lambda c: c[0].update(test_flag="boom"), "unknown test_flag")


if __name__ == "__main__":
    unittest.main()
