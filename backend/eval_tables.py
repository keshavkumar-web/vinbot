"""Evaluation for the structured UHBVN fact store.

Tests BOTH requirements:
  * never serve false data  (precision)
  * answer whatever IS in the trusted store  (recall)

Intent extraction is now done by the LLM (app.intent). To keep this suite
deterministic and runnable offline (no OpenAI key), each case carries the intent
the LLM is expected to produce, and we inject it via a STUB extractor. That
exercises the part that actually guarantees correctness — schema lookup, metric
snapping, entity resolution, exact SQLite read and formatting — without a live
model. Run the live router separately with eval_intent_live.py when a key is set.

    python eval_tables.py        # from backend/, venv active
"""

from __future__ import annotations

from app import tables

# Each case: (question, expected, intent)
#   expected: "<substring>" answer must contain it, or ("status", s) status match
#   intent:   the JSON the LLM router is expected to return (None => let the
#             real prose pre-filter / empty-selection path handle it)
A = "answer"
CASES: list[tuple[str, object, dict | None]] = [
    # --- Precision: the customer's wrong-column bug -------------------------
    ("How many connections in UHBVN", "3,892,250",
     {"status": A, "confidence": 0.95, "selections": [
         {"dataset": "connection", "metric": "Total", "entity": "UHBVN"}]}),
    ("How many domestic connections", "3,003,464",
     {"status": A, "confidence": 0.95, "selections": [
         {"dataset": "connection", "metric": "Domestic", "entity": None}]}),
    # --- Recall: compound (two datasets in one question) -------------------
    ("How many connections and total load", "18,110,483",
     {"status": A, "confidence": 0.9, "selections": [
         {"dataset": "connection", "metric": "Total", "entity": None},
         {"dataset": "connected_load", "metric": "Total", "entity": None}]}),
    ("Transformer damaged in Kurukshetra", "3,602",
     {"status": A, "confidence": 0.9, "selections": [
         {"dataset": "damaged_transformers",
          "metric": "Transformers damaged Total", "entity": "Kurukshetra"}]}),
    ("connections in Karnal", "543,445",
     {"status": A, "confidence": 0.9, "selections": [
         {"dataset": "connection", "metric": "Total", "entity": "Karnal"}]}),
    # --- Recall: a metric reachable only via generic column matching -------
    ("collection efficiency in Panchkula", ("status", A),
     {"status": A, "confidence": 0.8, "selections": [
         {"dataset": "circle_collection_efficiency",
          "metric": "April-23 to September-23 Collection efficiency",
          "entity": "Panchkula"}]}),
    # --- No circle named -> return the full district breakdown (capped) ----
    ("what is the collection efficiency", ("status", A),
     {"status": A, "confidence": 0.75, "selections": [
         {"dataset": "circle_collection_efficiency",
          "metric": "April-23 to September-23 Collection efficiency",
          "entity": None}]}),
    # --- Safety: unknown place named -> must NOT serve the Grand Total -----
    ("connections on the Moon", ("status", "clarify"),
     {"status": A, "confidence": 0.6, "selections": [
         {"dataset": "connection", "metric": "Total", "entity": "Moon"}]}),
    # --- Routing: procedural -> prose RAG (handled by pre-filter) ----------
    ("What is the procedure for a new domestic connection", ("status", "prose"),
     None),
    # --- Safety: out of scope -> LLM returns prose -------------------------
    ("What is the GDP of France", ("status", "prose"),
     {"status": "prose", "confidence": 0.9, "selections": []}),
    # --- Typo tolerance (LLM normalises 'domastic' -> 'Domestic') ----------
    ("How many connections for domastic", "3,003,464",
     {"status": A, "confidence": 0.85, "selections": [
         {"dataset": "connection", "metric": "Domestic", "entity": None}]}),
    # --- Expanded year-wise / series coverage ------------------------------
    ("consumer base as of 31-Mar-15", "2,635,725",
     {"status": A, "confidence": 0.9, "selections": [
         {"dataset": "consumers", "metric": "Consumer Base",
          "entity": "31-Mar-15"}]}),
    ("new consumers added in 2015-16", "117,235",
     {"status": A, "confidence": 0.9, "selections": [
         {"dataset": "consumers", "metric": "New Consumers Added",
          "entity": "2015-16"}]}),
    ("energy units billed in FY 2013-14", "12,244.59",
     {"status": A, "confidence": 0.9, "selections": [
         {"dataset": "year_wise_received_billed",
          "metric": "Energy units Billed in the year MUs",
          "entity": "FY 2013-14"}]}),
    ("ht lt ratio 2015-16", "1.06",
     {"status": A, "confidence": 0.9, "selections": [
         {"dataset": "ht_lt__ratio", "metric": "HT-LT Ratio",
          "entity": "2015-16"}]}),
    ("theft cases detected in 2010-11", "33,310",
     {"status": A, "confidence": 0.9, "selections": [
         {"dataset": "progress_power_theft", "metric": "Theft cases detected",
          "entity": "2010-11"}]}),
    ("substation total mva in Ambala", "42.90",
     {"status": A, "confidence": 0.9, "selections": [
         {"dataset": "abstract_substations_2021", "metric": "Total MVA",
          "entity": "Ambala"}]}),
    # --- Safety: a topic with no trusted dataset never serves a number -----
    ("what is the APPC year wise", ("status", "prose"),
     {"status": "prose", "confidence": 0.8, "selections": []}),
    # --- Superlative / argmax across all rows (deterministic; aggregates excluded)
    ("which circle has the maximum damaged transformers", "Karnal Rural",
     {"status": A, "confidence": 0.9, "selections": [
         {"dataset": "damaged_transformers", "metric": "Transformers damaged Total",
          "entity": None}]}),
    # --- Segregation / breakup -> every category column, NOT the inherited Total.
    ("segregation on connection type", "Domestic",
     {"status": A, "confidence": 0.9, "selections": [
         {"dataset": "connection", "metric": "Total", "entity": None}]}),
    # --- Superlative names a CATEGORY -> rank by that column, not the aggregate the
    #     router defaulted to (Sonipat Domestic 404,304, not Karnal Total 543,445).
    ("which district has the maximum domestic consumers", "404,304",
     {"status": A, "confidence": 0.9, "selections": [
         {"dataset": "connection", "metric": "Total", "entity": None}]}),
    # --- "ECS count" -> connection dataset (45), and the duplicate 'ECS' column
    #     (parse artifact: 45 + an empty 0) collapses to one clean value.
    ("what is ecs count in ambala", "45",
     {"status": A, "confidence": 0.9, "selections": [
         {"dataset": "connection", "metric": "ECS", "entity": "Ambala"}]}),
    # --- "LT Industry" must NOT collapse to "HT Industry" (the 2-char LT/HT is the
    #     only distinguisher). Metric resolved from the query, not a verbatim hint.
    ("panchkula lt industry", "2,301",
     {"status": A, "confidence": 0.9, "selections": [
         {"dataset": "connection", "metric": None, "entity": "Panchkula"}]}),
    # --- explicitly-named category beats a defaulted aggregate: "other count for
    #     Zone-II" -> the "Other" column (350), not Total.
    ("other count for zone 2", "350",
     {"status": A, "confidence": 0.9, "selections": [
         {"dataset": "connection", "metric": "Total", "entity": "Zone-II"}]}),
    # --- Row-wise: "circle wise" -> every circle, NOT the collapsed Grand Total.
    ("circle wise number of connection at the end of march 2026", "543,445",
     {"status": A, "confidence": 0.9, "selections": [
         {"dataset": "connection", "metric": "Total", "entity": None}]}),
    # --- Row-wise "zone wise" -> the zone subtotal rows only.
    ("zone wise total connections", "2,141,145",
     {"status": A, "confidence": 0.9, "selections": [
         {"dataset": "connection", "metric": "Total", "entity": None}]}),
    # --- Safety: unknown city + a trailing month must NOT serve the Grand Total.
    ("connections in Mumbai as of march 2026", ("status", "clarify"),
     {"status": A, "confidence": 0.7, "selections": [
         {"dataset": "connection", "metric": "Total", "entity": None,
          "period": "march 2026"}]}),
]


def _stub_extractor(intent: dict | None):
    """Return an extractor that ignores the schema and replays a fixed intent."""
    return lambda query, schema: tables_normalise(intent)


def tables_normalise(intent: dict | None) -> dict:
    # Mirror app.intent.normalise without importing it (avoids any key import).
    intent = intent or {"status": "clarify", "confidence": 0.0, "selections": []}
    intent.setdefault("confidence", 0.0)
    intent.setdefault("selections", [])
    intent.setdefault("clarify_reason", None)
    return intent


def run() -> int:
    passed = 0
    for question, expected, intent in CASES:
        r = tables.respond(question, extractor=_stub_extractor(intent))
        if isinstance(expected, tuple):  # status assertion
            ok = r["status"] == expected[1]
            shown = f"status={r['status']}"
        else:
            ok = expected in r.get("text", "")
            shown = (r.get("text") or "(prose path)").splitlines()[0]
        passed += ok
        print(f"[{'PASS' if ok else 'FAIL'}] {question}\n        -> {shown}\n")

    print(f"{passed}/{len(CASES)} passed")
    return 0 if passed == len(CASES) else 1


if __name__ == "__main__":
    raise SystemExit(run())
