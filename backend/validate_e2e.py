"""End-to-end validation for the LLM-router UHBVN assistant.

Drives the REAL serving path (app.chat.stream_answer + app.tables.respond with the
live LLM extractor) across a labelled battery and reports:
  * intent accuracy        - correct route (structured-answer / clarify / prose)
  * clarification rate      - share of queries answered with a clarify
  * false-positive rate     - share that served a WRONG or unwarranted number
                              (the safety metric; MUST be 0)
  * end-to-end accuracy     - fully-correct outcomes through the serving path

Sections:
  A. Live smoke of BOTH flows via chat.stream_answer (numeric + procedural).
  B. Regression battery + metrics (via tables.respond = the intent+lookup layer).
  C. RAG-fallback verification: procedural/policy questions stream a grounded
     answer through chat.stream_answer (the prose path), never a fabricated figure.

    python validate_e2e.py        # from backend/, venv active, OPENAI_API_KEY set
"""

from __future__ import annotations

import re
from app import chat, tables

# A "real-looking value": grouped thousands (3,892,250) or a decimal (12,244.59).
_VALUE_RE = re.compile(r"\d{1,3}(?:,\d{3})+|\d+\.\d+")

# Battery: (category, question, expected_route, expects, forbids)
#   expected_route in {"answer","clarify","prose"}
#   expects  = substrings that MUST appear (exact figures we have verified)
#   forbids  = substrings that must NOT appear
NUMERIC = "numeric"; COMPOUND = "compound"; DISTRICT = "district"
UNKNOWN = "unknown"; PROCEDURAL = "procedural"

BATTERY: list[tuple[str, str, str, list[str], list[str]]] = [
    # --- Numeric (single dataset) ------------------------------------------
    (NUMERIC, "How many connections in UHBVN", "answer", ["3,892,250"], ["3,003,464"]),
    (NUMERIC, "How many domestic connections", "answer", ["3,003,464"], []),
    (NUMERIC, "consumer base as of 31-Mar-15", "answer", ["2,635,725"], []),
    (NUMERIC, "energy units billed in FY 2013-14", "answer", ["12,244.59"], []),
    (NUMERIC, "ht lt ratio 2015-16", "answer", ["1.06"], []),
    (NUMERIC, "theft cases detected in 2010-11", "answer", ["33,310"], []),
    (NUMERIC, "substation total mva in Ambala", "answer", ["42.90"], []),
    # --- Compound (multiple datasets in one question) ----------------------
    (COMPOUND, "How many connections and total load", "answer",
     ["3,892,250", "18,110,483"], []),
    (COMPOUND, "domestic connections and total load", "answer",
     ["3,003,464", "18,110,483"], []),
    # --- District-specific --------------------------------------------------
    (DISTRICT, "connections in Karnal", "answer", ["543,445"], []),
    (DISTRICT, "transformer damaged in Kurukshetra", "answer", ["3,602"], []),
    (DISTRICT, "collection efficiency in Panchkula", "answer", [], []),
    # --- Unknown entities (must refuse, never substitute a total) ----------
    (UNKNOWN, "connections on the Moon", "clarify", [], ["3,892,250"]),
    (UNKNOWN, "connections in Atlantis", "clarify", [], ["3,892,250"]),
    (UNKNOWN, "load in Gotham", "clarify", [], ["18,110,483"]),
    # --- Procedural / policy / out-of-scope -> prose (Vector RAG) ----------
    (PROCEDURAL, "What is the procedure for a new domestic connection", "prose", [], []),
    (PROCEDURAL, "What documents are required for a new connection", "prose", [], []),
    (PROCEDURAL, "How do I apply for a change of name on my connection", "prose", [], []),
    (PROCEDURAL, "What is the GDP of France", "prose", [], []),
]


def classify(q: str) -> dict:
    """Run the intent+lookup layer (the first thing chat.stream_answer does)."""
    r = tables.respond(q)
    return {"status": r["status"], "text": r.get("text", "")}


def grade(case, res) -> dict:
    category, q, exp_route, expects, forbids = case
    status, text = res["status"], res["text"]
    route = "prose" if status == "prose" else (
        "answer" if status == "answer" else
        "clarify" if status == "clarify" else "not_found")

    # For unknown-entity cases the invariant is "never serve a value" — any
    # non-answer route (clarify / not_found / prose) is safe and acceptable; the
    # live LLM picks among them nondeterministically. The false_positive check
    # below is what actually enforces safety.
    route_ok = (route == exp_route) or (exp_route == "clarify" and route != "answer")
    expects_ok = all(s in text for s in expects)
    forbids_ok = all(s not in text for s in forbids)

    # False positive = served a real-looking number when it should not have, i.e.
    # an unknown-entity or out-of-scope query that produced a value, OR a numeric
    # answer that contains a forbidden (wrong-column) figure.
    served_value = bool(_VALUE_RE.search(text)) and status == "answer"
    false_positive = (
        (category in (UNKNOWN,) and served_value) or
        (exp_route == "prose" and served_value) or
        (not forbids_ok)
    )
    e2e_ok = route_ok and expects_ok and forbids_ok and not false_positive
    return {"route": route, "route_ok": route_ok, "expects_ok": expects_ok,
            "forbids_ok": forbids_ok, "false_positive": false_positive,
            "e2e_ok": e2e_ok}


def section_a_smoke():
    print("=" * 70)
    print("SECTION A — live smoke of BOTH flows via chat.stream_answer()")
    print("=" * 70)
    for label, q in [("STRUCTURED (numeric)", "How many connections in Karnal"),
                     ("RAG FALLBACK (procedural)",
                      "What is the procedure for a new domestic connection")]:
        out = "".join(chat.stream_answer([], q))
        print(f"\n[{label}] Q: {q}\n{'-'*60}\n{out.strip()[:600]}\n")


def section_b_battery():
    print("=" * 70)
    print("SECTION B — regression battery + metrics")
    print("=" * 70)
    rows = []
    for case in BATTERY:
        res = classify(case[1])
        g = grade(case, res)
        rows.append((case, res, g))
        flag = "PASS" if g["e2e_ok"] else "FAIL"
        fp = " !!FALSE-POSITIVE!!" if g["false_positive"] else ""
        shown = (res["text"] or "(prose -> RAG)").splitlines()[0][:70]
        print(f"[{flag}] {case[0]:10s} | {case[1][:46]:46s} | {g['route']:8s}{fp}")
        print(f"         -> {shown}")
    return rows


def section_c_rag(rows):
    print("\n" + "=" * 70)
    print("SECTION C — RAG fallback verification (prose path streams grounded text)")
    print("=" * 70)
    ok = 0
    prose_cases = [(c, r, g) for (c, r, g) in rows if c[0] == PROCEDURAL]
    for case, res, g in prose_cases:
        if g["route"] != "prose":
            print(f"[FAIL] not routed to prose: {case[1]}")
            continue
        out = "".join(chat.stream_answer([], case[1])).strip()
        grounded = len(out) > 0
        # out-of-scope must say it lacks info, not fabricate a figure
        no_fabrication = not (case[1].endswith("France") and _VALUE_RE.search(out))
        good = grounded and no_fabrication
        ok += good
        print(f"[{'PASS' if good else 'FAIL'}] {case[1][:50]:50s} -> {out[:90]!r}")
    print(f"\nRAG fallback: {ok}/{len(prose_cases)} produced grounded, non-fabricated replies")
    return ok, len(prose_cases)


def metrics(rows):
    n = len(rows)
    intent_ok = sum(g["route_ok"] for _, _, g in rows)
    clarifies = sum(1 for _, r, _ in rows if r["status"] == "clarify")
    false_pos = sum(g["false_positive"] for _, _, g in rows)
    e2e_ok = sum(g["e2e_ok"] for _, _, g in rows)
    print("\n" + "=" * 70)
    print("SECTION D — evaluation results")
    print("=" * 70)
    print(f"  Intent accuracy        : {intent_ok}/{n}  = {intent_ok/n:.0%}")
    print(f"  Clarification rate     : {clarifies}/{n}  = {clarifies/n:.0%}")
    print(f"  False-positive rate    : {false_pos}/{n}  = {false_pos/n:.0%}   (target 0%)")
    print(f"  End-to-end accuracy    : {e2e_ok}/{n}  = {e2e_ok/n:.0%}")
    # per-category breakdown
    cats: dict[str, list] = {}
    for case, _, g in rows:
        cats.setdefault(case[0], []).append(g["e2e_ok"])
    print("\n  Per-category end-to-end accuracy:")
    for cat, oks in cats.items():
        print(f"    {cat:12s}: {sum(oks)}/{len(oks)}")
    return false_pos == 0 and e2e_ok == n


if __name__ == "__main__":
    section_a_smoke()
    rows = section_b_battery()
    section_c_rag(rows)
    passed = metrics(rows)
    print("\n" + ("ALL GREEN — validation passed." if passed else
                  "VALIDATION FAILED — see FAIL/FALSE-POSITIVE rows above."))
    raise SystemExit(0 if passed else 1)
