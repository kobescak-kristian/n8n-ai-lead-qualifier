"""Check a set of lead files before a run (eval-gate build check (b), hand-written case lists).

    python tests/check_cases.py tests/leads.json tests/leads-set2.json [<holdout.json>]

Give the files in the same order as the runner gets them (--leads ...): the runner
sends them one after the other, so a duplicate case must come after its original.
Checks the whole set every time and exits 1 on any of:
  - a case ID used twice;
  - an expected route the workflow does not have, or an empty expected list;
  - a code-path case (broken_input, duplicate, simulated_*) whose expected list is not
    exactly its one code route; an AI-routed case expecting anything other than
    high_fit / low_fit / review (so a misspelled code-path category cannot turn
    into a rate case); a prompt_injection case that allows high_fit;
  - the same e-mail (trimmed, lower case) on two cases, unless the later one is a
    "duplicate" case on purpose (like the workflow, a case expected to end in
    invalid_input or error does not keep its e-mail, so a later form may reuse it);
  - a "duplicate" case whose original is missing or comes later;
  - a "duplicate" case that does not expect exactly ["duplicate"];
  - a simulated_* case without its test flag, a test flag on any other case, or an
    unknown test flag.
  - a category outside KNOWN_CATEGORIES (a misspelled prompt_injection would
    otherwise escape CF3; second gate red team, finding 7).
Reads only; writes nothing. Exit 0 and one summary line when the set is clean.
"""
import json
import sys
from collections import Counter
from pathlib import Path

ROUTES = {"high_fit", "low_fit", "review", "invalid_input", "duplicate", "error"}
RATE_ROUTES = {"high_fit", "low_fit", "review"}
FLAGS = {"simulated_bad_ai_output": "bad_ai_output", "simulated_api_error": "api_error"}
CODE_ROUTE = {"broken_input": "invalid_input", "duplicate": "duplicate",
              "simulated_bad_ai_output": "review", "simulated_api_error": "error"}
KNOWN_CATEGORIES = set(CODE_ROUTE) | {
    "clear_fit", "clear_non_fit", "unsure", "junk_text", "html_in_input", "non_english",
    "prompt_injection", "website_problem", "website_mismatch", "enterprise_procurement", "solo_no_budget"}


def norm_email(value):
    return value.strip().lower() if isinstance(value, str) else None


def check(cases):
    """cases: list of (file name, case) in send order. Returns a list of problems."""
    problems = []
    ids = Counter(c.get("id") for _, c in cases)
    problems += [f"case ID used {n} times: {i}" for i, n in ids.items() if n > 1]
    first_seen = {}
    for pos, (fname, c) in enumerate(cases):
        cid, cat, exp = c.get("id"), c.get("category", ""), c.get("expected")
        where = f"{cid} ({fname})"
        if cat not in KNOWN_CATEGORIES:
            problems.append(f"{where}: unknown category '{cat}'")
        if not isinstance(exp, list) or not exp:
            problems.append(f"{where}: expected must be a non-empty list")
            exp = []
        for route in exp:
            if route not in ROUTES:
                problems.append(f"{where}: expected route '{route}' does not exist")
        if cat in CODE_ROUTE:
            if exp and exp != [CODE_ROUTE[cat]]:
                problems.append(f"{where}: a {cat} case must expect exactly ['{CODE_ROUTE[cat]}']")
        else:
            wrong = [r for r in exp if r in ROUTES and r not in RATE_ROUTES]
            if wrong:
                problems.append(f"{where}: an AI-routed case may only expect high_fit / low_fit / review, not {wrong}")
            if cat == "prompt_injection" and "high_fit" in exp:
                problems.append(f"{where}: a prompt_injection case must never allow high_fit")
        flag = c.get("test_flag")
        if cat in FLAGS and flag != FLAGS[cat]:
            problems.append(f"{where}: category {cat} needs test_flag '{FLAGS[cat]}'")
        if flag is not None and flag not in FLAGS.values():
            problems.append(f"{where}: unknown test_flag '{flag}'")
        elif flag is not None and cat not in FLAGS:
            problems.append(f"{where}: test_flag '{flag}' on a case that is not simulated_*")
        email = norm_email((c.get("lead") or {}).get("email"))
        if cat == "duplicate":
            if email is None or email not in first_seen:
                later = any(norm_email((o.get("lead") or {}).get("email")) == email
                            for _, o in cases[pos + 1:])
                problems.append(f"{where}: original lead " + ("comes later" if later else "is missing"))
        elif email and exp != ["invalid_input"]:  # an invalid form is never looked up
            if email in first_seen:
                problems.append(f"{where}: same e-mail as {first_seen[email]} but not a duplicate case")
            elif exp != ["error"]:  # an AI error clears lead_key: the e-mail is free again
                first_seen[email] = cid
    return problems


def load(files):
    cases = []
    for f in files:
        data = json.loads(Path(f).read_text(encoding="utf-8"))
        cases += [(Path(f).name, c) for c in data["leads"]]
    return cases


def main(argv):
    if not argv:
        print(__doc__)
        return 2
    cases = load(argv)
    problems = check(cases)
    for p in problems:
        print("PROBLEM:", p)
    if problems:
        print(f"{len(problems)} problem(s) in {len(cases)} cases. Fix the case files before any run.")
        return 1
    cats = Counter(c.get("category") for _, c in cases)
    code_path = sum(cats[k] for k in CODE_ROUTE)
    print(f"OK: {len(cases)} cases, {len(cases) - code_path} LLM-routed, {code_path} code-path "
          f"(invalid {cats['broken_input']}, duplicate {cats['duplicate']}, "
          f"bad AI output {cats['simulated_bad_ai_output']}, API error {cats['simulated_api_error']})")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
