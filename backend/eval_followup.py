"""Regression for conversational follow-up handling (app/followup.py).

Two parts, both LIVE (need OPENAI_API_KEY):
  A. the contextualiser: scripted histories -> the standalone rewrite carries the
     right context (clarification answer, follow-up, short reply), and a topic
     change is returned WITHOUT stale context.
  B. end-to-end multi-turn through chat.stream_answer: a short follow-up resolves
     to the correct SQLite value; context expires on a topic change.

Nothing here is entity-specific — the same mechanism is exercised with different
districts/zones/categories.

    python eval_followup.py        # from backend/, venv active, key set
"""

from __future__ import annotations

from app import chat


def converse(user_messages: list[str]) -> str:
    """Replay a conversation the way main.py does; return the final answer."""
    history: list[dict] = []
    final = ""
    for msg in user_messages:
        final = "".join(chat.stream_answer(history, msg))
        history.append({"role": "user", "content": msg})
        history.append({"role": "assistant", "content": final})
    return final


# --- Part A: contextualiser ------------------------------------------------- #
# (history, latest, must_contain[], must_not_contain[])
A_CASES: list[tuple[list[dict], str, list[str], list[str]]] = [
    ([{"role": "user", "content": "Count in Ambala"},
      {"role": "assistant", "content": "Which count? (Domestic, Non-domestic, ...)"}],
     "Domestic", ["ambala", "domestic"], []),
    ([{"role": "user", "content": "Transformer damaged in Kurukshetra"},
      {"role": "assistant", "content": "Rural or Urban?"}],
     "Rural", ["kurukshetra", "rural"], []),
    ([{"role": "user", "content": "Who is the designated officer?"},
      {"role": "assistant", "content": "The SDO."}],
     "And for shifting of meter?", ["designated officer"], []),
    ([{"role": "user", "content": "How many connections?"},
      {"role": "assistant", "content": "Which circle or zone?"}],
     "Zone-I", ["zone", "connection"], []),
    # Topic change: a fresh, self-contained question must drop the old context.
    ([{"role": "user", "content": "How many domestic connections in Panchkula?"},
      {"role": "assistant", "content": "Panchkula — Domestic: 123456"}],
     "how many connections in Karnal?", ["karnal"], ["panchkula", "domestic"]),
]


def part_a() -> tuple[int, int]:
    print("== Part A: contextualiser rewrite ==")
    passed = 0
    for history, latest, must, must_not in A_CASES:
        out = chat.contextualize(history, latest)
        low = out.lower()
        ok = all(s in low for s in must) and all(s not in low for s in must_not)
        passed += ok
        print(f"[{'PASS' if ok else 'FAIL'}] {latest!r} -> {out!r}")
    return passed, len(A_CASES)


# --- Part B: end-to-end multi-turn ------------------------------------------ #
# (turns, must_contain[], must_not_contain[])
B_CASES: list[tuple[list[str], list[str], list[str]]] = [
    # clarification answer -> exact SQLite value (Ambala Domestic = 295,224)
    (["Count in Ambala", "Domestic"], ["295,224"], []),
    # short reply narrows the row: Kurukshetra Rural = 3,602, and NOT Urban 118
    (["Transformer damaged in Kurukshetra", "Rural"], ["3,602", "Rural"], ["118"]),
    # topic change: must answer Karnal (543,445), not drag Panchkula/Domestic in
    (["How many domestic connections in Panchkula",
      "how many connections in Karnal"], ["543,445"], ["Panchkula"]),
    # metric-only follow-up must keep the DATASET/subject: "total?" after a
    # CONNECTIONS answer = Zone-I Total connections (1,751,105), NOT connected
    # load (7,395,321 KW).
    (["how many domestic connections in Zone-I", "total?"],
     ["1,751,105"], ["7,395,321"]),
    # back-reference follow-up (customer-reported): "how many of those are
    # domestic?" must inherit "connections" -> Grand Total Domestic 3,003,464.
    (["how many connections does uhbvn have in total?",
      "how many of those are domestic?"], ["3,003,464"], []),
    # segregation follow-up (customer-reported): after the Total, "segregation on
    # connection type" must return the CATEGORY breakup (Domestic 3,003,464, LT
    # NDS 449,105, ...) and NOT repeat the Total (3,892,250).
    (["Total connection count", "Segregation on connection type"],
     ["3,003,464", "449,105"], ["3,892,250"]),
    # slot chain (customer-reported): only the named dimension changes. End state
    # is Zone-I TOTAL (1,751,105) — the metric stays "Total" from the prior turn,
    # not the "Domestic" the chain started with.
    (["Domestic count in Ambala", "And for Karnal?", "Total?", "Zone-I?"],
     ["1,751,105"], ["Domestic"]),
    # slot chain across DATASETS: Domestic -> Total -> Load (KW) -> Breakup. The
    # breakup must be of connected LOAD (Domestic 591,257 KW), NOT of the
    # connection counts (295,224) — the dataset slot must survive into segregation.
    (["Domestic connections in Ambala", "Total?", "Load?", "Breakup?"],
     ["591,257", "KW"], ["295,224"]),
    # customer-reported: a bare "Domestic?" must pick the "Domestic" column, NOT the
    # longer "Bulk Supply Domestic" (both contain "domestic").
    (["Load in Sonipat", "Domestic?"], ["644,882"], ["6,176"]),
    # customer-reported: "Zone-I total" must resolve the ENTITY Zone-I (extra word
    # "total" must not defeat the match), not stay on the prior circle.
    (["circle wise connections", "Zone-I total"], ["1,751,105"], []),
    # SAFETY (customer-reported): an unknown place after a grounded answer must NOT
    # inherit the prior row — "Connections on moon" must refuse/clarify (either is
    # fine), never SERVE a real number (no 543,445 grand-total / 5,193 transformer).
    (["Which circle has maximum damaged transformers?", "Connections on moon"],
     [], ["543,445", "5,193", "3,892,250", "2,922,112"]),
    # residual-1 (prose->numeric): after a prose deposit answer, "for domestic?"
    # must continue in prose -> domestic DEPOSIT rate (750), NOT the domestic
    # connection COUNT (3,003,464).
    (["What is the security deposit?", "For domestic?"], ["750"], ["3,003,464"]),
    # residual-2 (comparison metric switch): "which has more connections?" after a
    # LOAD comparison must RE-FETCH connection counts (Karnal 543,445), not reuse
    # the load KW values.
    (["Total load in Karnal", "Total load in Panipat", "Which has more connections?"],
     ["543,445"], ["KW"]),
    # customer-reported: after a superlative, "what about rural?" re-ranks WITHIN
    # rural circles (Karnal Rural 5,193), not the aggregate Total Rural (24,076).
    (["Which circle has maximum damaged transformers?", "What about rural?"],
     ["Karnal Rural", "5,193"], ["24,076"]),
    # customer-reported DT domain-switch: a transformer follow-up after a CONNECTION
    # answer must NOT inherit Domestic. Ambiguous "failure rate" -> clarify; a clear
    # "DT count" -> the damaged-transformer count. Never the connection value.
    (["DS connection in Ambala", "DT failure rate in Ambala"],
     ["transformer"], ["295,224"]),
    (["DS connection in Ambala", "DT count in Ambala"],
     ["Transformers damaged"], ["295,224", "394,560"]),
    # customer-reported: a single-term DEFINITION question after a numeric turn must
    # NOT be hijacked by the contextualiser into the numeric "name the circle"
    # clarify. A known abbr -> its definition; an unknown one -> a clean not-found.
    (["Damaged transformer count in Ambala", "what is PT?"],
     ["Potential Transformer"], ["circle"]),
    (["Damaged transformer count in Ambala", "What is ABCXYZ?"],
     ["could not find"], ["circle"]),
    # customer-reported: a CONCEPTUAL "difference between X and Y" (glossary terms)
    # must NOT reuse stale numeric facts left in the chat by an earlier numeric
    # comparison — it must explain the terms, never invent a "difference in HT Lines".
    (["Compare HT and LT", "Difference between SLDC and RLDC"],
     ["SLDC"], ["HT Lines"]),
    # customer-reported: a bare AMBIGUOUS abbreviation returns ALL its meanings.
    (["What is ABCXYZ?", "REC"],
     ["can refer to"], []),
]


def part_b() -> tuple[int, int]:
    print("\n== Part B: end-to-end multi-turn ==")
    passed = 0
    for turns, must, must_not in B_CASES:
        final = converse(turns)
        ok = all(s in final for s in must) and all(s not in final for s in must_not)
        passed += ok
        shown = final.splitlines()[0] if final else "(empty)"
        print(f"[{'PASS' if ok else 'FAIL'}] {turns} -> {shown}")
    return passed, len(B_CASES)


# --- Part C: meta-questions about our OWN previous answer ------------------- #
# (turns, substrings the final answer MUST contain)
C_CASES: list[tuple[list[str], list[str]]] = [
    # "which count is this?" -> explained from history, not "not found"
    (["Count in Ambala.", "Which count is this?"], ["Total", "Ambala"]),
    (["how many domestic connections in Karnal?", "is that domestic or total?"],
     ["domestic"]),
    (["how many connections in UHBVN?", "where did that come from?"],
     ["1_Connection.pdf"]),
    # comparison over prior values -> deterministic, grounded (Karnal > Ambala)
    (["Compare Ambala and Karnal.", "Which is higher?"], ["Karnal", "higher"]),
    # subject-aware comparison: "more load" compares the KW figures (Panipat),
    # not the connection counts that share the metric name "Total".
    (["how many total connections and load?", "for ambala and panipat",
      "which has more load?"], ["Panipat", "KW"]),
]


def part_c() -> tuple[int, int]:
    print("\n== Part C: meta-questions about our own prior answer ==")
    passed = 0
    for turns, must in C_CASES:
        final = converse(turns)
        ok = all(s.lower() in final.lower() for s in must)
        passed += ok
        print(f"[{'PASS' if ok else 'FAIL'}] {turns[-1]!r} -> {final.splitlines()[0][:70]}")
    return passed, len(C_CASES)


def run() -> int:
    pa, na = part_a()
    pb, nb = part_b()
    pc, nc = part_c()
    total, n = pa + pb + pc, na + nb + nc
    print(f"\n{total}/{n} passed  (Part A {pa}/{na}, Part B {pb}/{nb}, Part C {pc}/{nc})")
    return 0 if total == n else 1


if __name__ == "__main__":
    raise SystemExit(run())
