"""Live router eval: exercises the REAL LLM intent extraction end-to-end.

Unlike eval_tables.py (which injects the expected intent via a stub so it can run
offline and deterministically), this hits the configured OpenAI model so you can
see how well the router maps natural phrasing to dataset+metric+entity. Needs
OPENAI_API_KEY. It asserts the same correctness invariants — exact figures and
safe routing — but through the live model.

    python eval_intent_live.py        # from backend/, venv active, key set
"""

from __future__ import annotations

from app import tables

# Reuse the natural questions + expected outcomes from the offline suite.
from eval_tables import CASES

# Count-vs-load routing is a FRESH-path-only guard (skipped for injected stubs), so
# it can't live in the shared CASES — assert it here against the live router.
# (question, expected_substring, must_not_substring | None)
LIVE_EXTRA = [
    ("lift irrigation in ambala", "16", "KW"),          # bare category -> COUNT default
    ("lift irrigation load in ambala", "KW", None),     # "load" word -> connected_load (kW)
    ("ecs count in ambala", "45", "KW"),                # count -> connection
    ("domestic load in panipat", "KW", None),           # load -> connected_load
]


def run() -> int:
    passed = 0
    for question, expected, _intent in CASES:
        r = tables.respond(question)  # default (live) extractor
        if isinstance(expected, tuple):
            want = expected[1]
            # Unknown-entity cases must never ANSWER; the live LLM picks among the
            # safe non-answer routes (clarify/not_found/prose) nondeterministically.
            ok = (r["status"] != "answer") if want == "clarify" else (r["status"] == want)
            shown = f"status={r['status']}"
        else:
            ok = expected in r.get("text", "")
            shown = (r.get("text") or "(prose path)").splitlines()[0]
        passed += ok
        print(f"[{'PASS' if ok else 'FAIL'}] {question}\n        -> {shown}\n")

    for question, want, must_not in LIVE_EXTRA:
        text = tables.respond(question).get("text", "")
        ok = want in text and (must_not is None or must_not not in text)
        passed += ok
        print(f"[{'PASS' if ok else 'FAIL'}] {question}\n        -> {text.splitlines()[0] if text else '(no answer)'}\n")

    total = len(CASES) + len(LIVE_EXTRA)
    print(f"{passed}/{total} passed (live LLM router)")
    return 0 if passed == total else 1


if __name__ == "__main__":
    raise SystemExit(run())
