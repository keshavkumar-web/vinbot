#!/usr/bin/env python3
"""Generate the Vinbot Test Execution Dashboard from REAL report files.

Reads:
    ../reports/junit.xml          (pytest --junitxml)
    ../reports/coverage.xml       (pytest-cov, Cobertura format)
    ../reports/newman-junit.xml   (optional — Postman/Newman run, if present)

Writes:
    ../reports/dashboard.html
    ../reports/dashboard.md

Every number in the dashboard comes from parsing these files at run time —
nothing is hardcoded. If junit.xml or coverage.xml don't exist yet, this
script exits with an error telling you to run pytest first, rather than
producing a dashboard with fabricated numbers.

Usage (from backend/, after running pytest):
    python tests/generate_dashboard.py
"""
from __future__ import annotations

import sys
import time
import xml.etree.ElementTree as ET
from pathlib import Path

TESTS_DIR = Path(__file__).resolve().parent
BACKEND_DIR = TESTS_DIR.parent
REPORTS_DIR = BACKEND_DIR.parent / "reports"

JUNIT_PATH = REPORTS_DIR / "junit.xml"
COVERAGE_PATH = REPORTS_DIR / "coverage.xml"
NEWMAN_JUNIT_PATH = REPORTS_DIR / "newman-junit.xml"


def _sum_testsuites(root: ET.Element) -> dict:
    suites = root.findall(".//testsuite")
    if not suites and root.tag == "testsuite":
        suites = [root]
    totals = {"tests": 0, "failures": 0, "errors": 0, "skipped": 0, "time": 0.0}
    for suite in suites:
        for key in ("tests", "failures", "errors", "skipped"):
            totals[key] += int(suite.attrib.get(key, 0) or 0)
        totals["time"] += float(suite.attrib.get("time", 0) or 0.0)
    return totals


def parse_junit(path: Path) -> dict:
    root = ET.parse(path).getroot()
    totals = _sum_testsuites(root)
    passed = totals["tests"] - totals["failures"] - totals["errors"] - totals["skipped"]
    return {
        "total": totals["tests"],
        "passed": passed,
        "failed": totals["failures"] + totals["errors"],
        "skipped": totals["skipped"],
        "time_seconds": totals["time"],
    }


def parse_coverage(path: Path) -> float:
    root = ET.parse(path).getroot()
    line_rate = float(root.attrib.get("line-rate", 0.0))
    return round(line_rate * 100, 2)


def build_dashboard() -> dict:
    if not JUNIT_PATH.exists():
        sys.exit(
            f"ERROR: {JUNIT_PATH} not found.\n"
            f"Run the test suite first: cd backend && pytest -v\n"
            f"(pytest.ini is configured to write it automatically)"
        )
    if not COVERAGE_PATH.exists():
        sys.exit(
            f"ERROR: {COVERAGE_PATH} not found.\n"
            f"Run the test suite first: cd backend && pytest -v"
        )

    pytest_results = parse_junit(JUNIT_PATH)
    coverage_pct = parse_coverage(COVERAGE_PATH)

    newman_results = None
    if NEWMAN_JUNIT_PATH.exists():
        newman_results = parse_junit(NEWMAN_JUNIT_PATH)

    return {
        "generated_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        "pytest": pytest_results,
        "coverage_pct": coverage_pct,
        "newman": newman_results,
    }


def render_markdown(data: dict) -> str:
    p = data["pytest"]
    lines = [
        "# Vinbot — Test Execution Dashboard",
        "",
        f"_Generated: {data['generated_at']}_",
        "",
        "Source: real `reports/junit.xml` + `reports/coverage.xml` "
        "(and `reports/newman-junit.xml` if present) from the most recent run.",
        "",
        "## pytest (unit + integration)",
        "",
        "| Metric | Value |",
        "|---|---|",
        f"| Total Tests | {p['total']} |",
        f"| Passed | {p['passed']} |",
        f"| Failed | {p['failed']} |",
        f"| Skipped | {p['skipped']} |",
        f"| Coverage % (line rate) | {data['coverage_pct']}% |",
        f"| Execution Time | {p['time_seconds']:.2f}s |",
    ]
    if data["newman"]:
        n = data["newman"]
        lines += [
            "",
            "## Newman (Postman API integration suite)",
            "",
            "| Metric | Value |",
            "|---|---|",
            f"| Total Tests | {n['total']} |",
            f"| Passed | {n['passed']} |",
            f"| Failed | {n['failed']} |",
            f"| Skipped | {n['skipped']} |",
            f"| Execution Time | {n['time_seconds']:.2f}s |",
        ]
    else:
        lines += ["", "## Newman (Postman API integration suite)", "",
                  "_Not run yet — see postman/README.md._"]
    return "\n".join(lines) + "\n"


def render_html(data: dict) -> str:
    p = data["pytest"]
    status_color = "#1f9d55" if p["failed"] == 0 else "#c53030"
    newman_block = ""
    if data["newman"]:
        n = data["newman"]
        newman_block = f"""
    <h2>Newman (Postman API integration suite)</h2>
    <table>
      <tr><th>Total Tests</th><td>{n['total']}</td></tr>
      <tr><th>Passed</th><td>{n['passed']}</td></tr>
      <tr><th>Failed</th><td>{n['failed']}</td></tr>
      <tr><th>Skipped</th><td>{n['skipped']}</td></tr>
      <tr><th>Execution Time</th><td>{n['time_seconds']:.2f}s</td></tr>
    </table>
"""
    else:
        newman_block = "<h2>Newman (Postman API integration suite)</h2><p>Not run yet — see postman/README.md.</p>"

    return f"""<!doctype html>
<html><head><meta charset="utf-8"><title>Vinbot Test Execution Dashboard</title>
<style>
  body {{ font-family: system-ui, sans-serif; margin: 2rem; color: #1a1a1a; }}
  table {{ border-collapse: collapse; margin: 1rem 0; }}
  th, td {{ border: 1px solid #ccc; padding: 0.4rem 0.8rem; text-align: left; }}
  th {{ background: #f2f2f2; }}
  .status {{ font-weight: bold; color: {status_color}; }}
  h1 {{ margin-bottom: 0.2rem; }}
  .meta {{ color: #666; margin-bottom: 1.5rem; }}
</style></head>
<body>
  <h1>Vinbot — Test Execution Dashboard</h1>
  <p class="meta">Generated: {data['generated_at']} — source: real reports/junit.xml + coverage.xml</p>
  <p class="status">{'ALL TESTS PASSED' if p['failed'] == 0 else str(p['failed']) + ' TEST(S) FAILED'}</p>
  <h2>pytest (unit + integration)</h2>
  <table>
    <tr><th>Total Tests</th><td>{p['total']}</td></tr>
    <tr><th>Passed</th><td>{p['passed']}</td></tr>
    <tr><th>Failed</th><td>{p['failed']}</td></tr>
    <tr><th>Skipped</th><td>{p['skipped']}</td></tr>
    <tr><th>Coverage % (line rate)</th><td>{data['coverage_pct']}%</td></tr>
    <tr><th>Execution Time</th><td>{p['time_seconds']:.2f}s</td></tr>
  </table>
  {newman_block}
</body></html>
"""


def main():
    data = build_dashboard()
    REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    (REPORTS_DIR / "dashboard.md").write_text(render_markdown(data), encoding="utf-8")
    (REPORTS_DIR / "dashboard.html").write_text(render_html(data), encoding="utf-8")
    print(f"Wrote {REPORTS_DIR / 'dashboard.md'}")
    print(f"Wrote {REPORTS_DIR / 'dashboard.html'}")
    p = data["pytest"]
    print(f"pytest: {p['passed']}/{p['total']} passed, {data['coverage_pct']}% coverage")


if __name__ == "__main__":
    main()
