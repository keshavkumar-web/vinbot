"""Regression for multi-part RAG recall (the per-sub-question retrieval fix).

Guards hard-requirement #2: if a fact IS in the knowledge base, a multi-part turn
must still surface it. The old whole-turn retrieval embedded all sub-questions
together, smeared the query, and returned 5 generic chunks that covered none of
the specific answers (ACD, Late Payment Surcharge, net metering, ...). This eval
asserts the facts now appear in the retrieved context.

Needs OPENAI_API_KEY (embeddings).   python eval_rag.py
"""

from __future__ import annotations

from app import rag

BLOB9 = """1. What documents are required to apply for a new domestic electricity connection in UHBVN?
2. How is the security deposit (Advance Consumption Deposit) for a new connection calculated?
3. Explain the step-by-step procedure to transfer an electricity connection to a new owner.
4. And what happens if the previous owner has unpaid dues?
5. What is the procedure and what charges apply for enhancing the sanctioned load of an existing connection?
6. What are the rules for rooftop solar net metering for a domestic consumer?
7. What is the Late Payment Surcharge and how is it applied to a pending electricity bill?
8. My electricity meter seems to be running fast. How can I get it tested and what are the charges?
9. How can a consumer file a complaint with the CGRF, and what are the timelines for resolution?"""

# (multi-part question, substrings that MUST appear in the retrieved context)
CASES: list[tuple[str, list[str]]] = [
    (BLOB9, ["1.25", "advance consumption deposit", "net metering",
             "sanctioned load", "45 days", "100"]),
    ("What documents are required for a new connection, and what is the Late "
     "Payment Surcharge rate?", ["ownership", "1.25"]),
    ("How is the security deposit calculated and how do I enhance my sanctioned "
     "load?", ["security", "sanctioned load"]),
    # Lexical circular-ID retrieval: a query naming a circular/instruction by its
    # ID code must surface that document's chunk (embeddings can't match IDs).
    ("please explain sales instruction no u-01/2024", ["independent feeder"]),
    # Figure recall via consumer phrasing (customer-reported): the amount chunk,
    # not just the descriptive paragraph, must surface.
    ("how much security deposit will i have to pay?", ["750"]),
    ("how can i get my meter tested and what's the cost?", ["rs. 100"]),
    # RTS designated-officer schedule (requires add_rts_act.py to have run):
    # shifting-of-meter's Designated Officer is JE, not the SDO appellate column.
    ("who is the designated officer for shifting of meter?", ["je [in charge]"]),
]


def run() -> int:
    passed = 0
    for question, needles in CASES:
        ctx = rag.format_context(rag.retrieve_context_multi(question)).lower()
        missing = [n for n in needles if n.lower() not in ctx]
        ok = not missing
        passed += ok
        n_subs = len(rag.split_questions(question))
        print(f"[{'PASS' if ok else 'FAIL'}] {n_subs} sub-qs | "
              f"{question[:45].replace(chr(10), ' ')}...")
        if missing:
            print(f"        MISSING from context: {missing}")
    print(f"\n{passed}/{len(CASES)} passed")
    return 0 if passed == len(CASES) else 1


if __name__ == "__main__":
    raise SystemExit(run())
