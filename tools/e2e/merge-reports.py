"""Merge Playwright results from an unchanged candidate and scoped reruns."""
from __future__ import annotations

import argparse
from collections import Counter
import json
from pathlib import Path


def iter_results(suite, parents=()):
    path = (*parents, suite.get("title", ""))
    for spec in suite.get("specs", []):
        for test in spec.get("tests", []):
            yield (path, spec["title"], test["projectName"]), spec, test
    for child in suite.get("suites", []):
        yield from iter_results(child, path)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("output", type=Path)
    parser.add_argument("reports", nargs="+", type=Path)
    args = parser.parse_args()
    cases = {}
    for report in args.reports:
        for suite in json.loads(report.read_text())["suites"]:
            for identity, spec, test in iter_results(suite):
                cases[identity] = (spec, test)
    args.output.mkdir(parents=True, exist_ok=True)
    summary = {}
    for browser in ("chromium", "firefox", "webkit"):
        counts = Counter()
        specs = []
        for (_, _, project), (spec, test) in cases.items():
            if project != browser:
                continue
            specs.append({**spec, "tests": [test]})
            statuses = {result["status"] for result in test.get("results", [])}
            if test.get("status") == "expected" and statuses == {"passed"}:
                counts["passed"] += 1
            elif not statuses or statuses == {"skipped"}:
                counts["unverified"] += 1
            else:
                counts["failed"] += 1
        summary[browser] = dict(counts)
        (args.output / (browser + ".json")).write_text(json.dumps({"suites": [{"specs": specs}]}))
    (args.output / "browser-summary.json").write_text(json.dumps(summary, indent=2))
    print(json.dumps(summary))


if __name__ == "__main__":
    main()
