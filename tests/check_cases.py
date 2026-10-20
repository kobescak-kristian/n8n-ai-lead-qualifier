"""Check a set of lead files before a run (eval-gate build check (b), hand-written case lists).

    python tests/check_cases.py tests/leads.json tests/leads-set2.json [<holdout.json>]

Give the files in the same order as the runner gets them (--leads ...): the runner
sends them one after the other, so a duplicate case must come after its original.
Checks the whole set every time and exits 1 on any of:
  - a case ID used twice;
  - an expected route the workflow does not have, or an empty expected list;
  - the same e-mail (trimmed, lower case) on two cases, unless the later one is a
    "duplicate" case on purpose (like the workflow, a case expected to be
    invalid_input does not take its e-mail, so a corrected form may reuse it);
  - a "duplicate" case whose original is missing or comes later;
  - a "duplicate" case that does not expect exactly ["duplicate"];
  - a simulated_* case without its test flag, or an unknown test flag.
Reads only; writes nothing. Exit 0 and one summary line when the set is clean.
"""
import json
import sys
from collections import Counter
from pathlib import Path

ROUTES = {"high_fit", "low_fit", "review", "invalid_input", "duplicate", "error"}
FLAGS = {"simulated_bad_ai_output": "bad_ai_output", "simulated_api_error": "api_error"}


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
        if not isinstance(exp, list) or not exp:
            problems.append(f"{where}: expected must be a non-empty list")
            exp = []
        for route in exp:
            if route not in ROUTES:
                problems.append(f"{where}: expected route '{route}' does not exist")
        flag = c.get("test_flag")
        if cat in FLAGS and flag != FLAGS[cat]:
            problems.append(f"{where}: category {cat} needs test_flag '{FLAGS[cat]}'")
        if flag is not None and flag not in FLAGS.values():
            problems.append(f"{where}: unknown test_flag '{flag}'")
        email = norm_email((c.get("lead") or {}).get("email"))
        if cat == "duplicate":
            if exp != ["duplicate"]:
                problems.append(f"{where}: a duplicate case must expect exactly ['duplicate']")
            if email is None or email not in first_seen:
                later = any(norm_email((o.get("lead") or {}).get("email")) == email
                            for _, o in cases[pos + 1:])
                problems.append(f"{where}: original lead " + ("comes later" if later else "is missing"))
        elif email and exp != ["invalid_input"]:
            if email in first_seen:
                problems.append(f"{where}: same e-mail as {first_seen[email]} but not a duplicate case")
            else:
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
    code_path = sum(cats[k] for k in ("broken_input", "duplicate", *FLAGS))
    print(f"OK: {len(cases)} cases, {len(cases) - code_path} LLM-routed, {code_path} code-path "
          f"(invalid {cats['broken_input']}, duplicate {cats['duplicate']}, "
          f"bad AI output {cats['simulated_bad_ai_output']}, API error {cats['simulated_api_error']})")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
