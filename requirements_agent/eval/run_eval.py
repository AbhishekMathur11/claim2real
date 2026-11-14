#!/usr/bin/env python3
"""Generate checklists for fixture cases and score them."""

from __future__ import annotations

import sys
from pathlib import Path

import yaml

EVAL = Path(__file__).resolve().parent
ROOT = EVAL.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(EVAL))

from generate import DEFAULT_MODEL, generate_spec  # noqa: E402
from graders import grade  # noqa: E402

RESULTS = EVAL / "results"


def main() -> int:
    model = sys.argv[1] if len(sys.argv) > 1 else DEFAULT_MODEL
    cases = yaml.safe_load((EVAL / "cases.yaml").read_text())
    RESULTS.mkdir(exist_ok=True)
    failed = 0

    for case in cases:
        problem = (EVAL / case["problem_file"]).read_text()
        print(f"\n=== {case['id']} ({model}) ===\n")
        spec = generate_spec(problem, model=model)
        (RESULTS / f"{case['id']}.json").write_text(spec + "\n")
        print(spec)
        checks = grade(spec, case)
        for check in checks:
            mark = "PASS" if check["ok"] else "FAIL"
            print(f"  [{mark}] {check['name']}: {check['detail']}")
            if not check["ok"]:
                failed += 1

    print(f"\n{len(cases)} cases, {failed} failed checks")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
