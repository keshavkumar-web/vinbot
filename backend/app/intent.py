"""LLM intent extraction for the structured (numeric) UHBVN path.

This replaces the hardcoded ``DATASET_CATALOG`` keyword map in ``tables.py``.
Instead of matching the user's words against curated keyword lists, we hand the
LLM a *catalog built live from SQLite* (every trusted dataset, its exact column
names, and a sample of its row labels) and ask it to pick which
dataset / metric / entity the question refers to.

Contract — and the single most important safety property of this module:
    The LLM NEVER produces a value. It only selects identifiers (a dataset key,
    a column name copied verbatim, an entity label). Every number is looked up
    deterministically from SQLite afterwards (see ``tables.resolve``/``respond``).

Kept deliberately free of ``app.config`` / ``app.rag`` at import time so that
``app.tables`` (and the ingestion pipeline) still import without an OpenAI key.
The OpenAI client is imported lazily, only when ``default_extractor`` actually
runs.
"""

from __future__ import annotations

import json
from typing import Callable

# An extractor is any callable mapping (query, schema) -> intent-dict. Injecting
# it keeps ``tables.respond`` testable offline (eval passes a deterministic stub)
# and lets the OpenAI dependency stay lazy.
Extractor = Callable[[str, dict], dict]

# How many sample row labels to show the model per dataset. Columns (metrics)
# are always shown in full because they are the critical disambiguator; entities
# are mostly district/year labels that the deterministic resolver re-checks, so
# a sample is enough to ground the model's spelling.
_MAX_ENTITIES_SHOWN = 40


INTENT_PROMPT = """\
You are the INTENT ROUTER for the UHBVN (Uttar Haryana Bijli Vitran Nigam)
electricity-board DATA assistant. Your ONLY job is to map the user's question to
identifiers taken from a catalog of database tables that is given to you.

You DO NOT answer questions and you NEVER output any number, value, count,
amount, percentage or statistic. The real figures are looked up from the
database AFTER you reply. You output ONLY *which* table / column / row to read.

You are given a CATALOG: a JSON object of available datasets. For each dataset
you get its `title`, the EXACT list of `metrics` (columns), and a sample of
`entities` (rows — districts/circles, years or periods).

Return ONE JSON object, no markdown, with exactly this shape:
{
  "status": "answer" | "clarify" | "prose",
  "confidence": <number between 0 and 1>,
  "selections": [
    {
      "dataset": "<exact dataset key from the catalog>",
      "metric":  "<a metric string copied VERBATIM from that dataset's metrics>",
      "entity":  "<the district/circle/year/period the user named, or null>",
      "period":  "<a year/period the user named, or null>"
    }
  ],
  "clarify_reason": "<one short sentence; only when status is 'clarify'>"
}

Rules:
1. Choose the dataset whose title/metrics best fit the question. Use its EXACT key.
   - The SAME category (Domestic, ECS, HT Industry, Bulk, …) exists BOTH in the
     number-of-connections report and the connected-load report. Disambiguate by
     the UNIT the user asked for: "count", "number", "how many", "connections" ->
     the CONNECTION-count dataset; "load", "kW", "KW", "connected load",
     "sanctioned load" -> the CONNECTED-LOAD dataset. So "ECS count in Ambala"
     uses the connection dataset (a count), "ECS load in Ambala" the connected_load
     dataset (kW). When neither word appears, default to the connection dataset.
2. Choose the metric by copying one of that dataset's `metrics` strings EXACTLY,
   character for character (capitalisation and punctuation included).
   - For a BARE quantity question ("how many connections", "total load") pick the
     aggregate column named "Total" (or the nearest total/aggregate column).
   - Pick a specific breakdown column (e.g. "Domestic", "HT Industry") ONLY when
     the user explicitly names that category. Fix obvious typos ("domastic" ->
     "Domestic").
   - Expand common UHBVN abbreviations to whichever REAL column they match:
     DS = Domestic (Supply), NDS = Non-Domestic Supply, AP = Agricultural Pumpset,
     HT / LT = High / Low Tension, DTR = Distribution Transformer. Only use an
     expansion if a matching column actually exists in the chosen dataset.
   - A category only exists as a column in SOME datasets; choose the dataset that
     actually HAS that column (e.g. "domestic" is a column of the connection
     dataset, not of the year-wise consumers series).
   - If several columns differ only by reporting period/window (e.g. "April-23 to
     September-23 ..." vs "April-24 ...") and the user named NO period, pick the
     column for the MOST RECENT period. Do not clarify just for this.
3. entity: copy the place or period the user named (e.g. "Karnal", "2015-16",
   "31-Mar-15"). A MISSING place/period is NOT a problem and NOT a reason to
   clarify — set entity to null and the lookup will default to the utility-wide
   total (or the full series). Never invent or guess a district.
4. If the user asks about several things at once, return one object per thing in
   `selections`. "How many connections and total load" -> TWO selections
   (connection/Total and connected_load/Total).
   - A comparison or list of entities — "Compare A and B", "which is greater
     between A and B", "A vs B", "A and B for domestic" — is a request for EACH
     entity's value: return ONE selection per named entity. Use the metric the
     user named ("for domestic" -> the Domestic column); if none is named, use the
     aggregate "Total". Do NOT clarify for the metric in this case.
   - A SUPERLATIVE — "which district/circle/location has the highest / most /
     lowest / least / maximum / minimum <X>" — asks to rank ALL rows. Return ONE
     selection: the dataset, the metric for <X> (the aggregate/Total column when
     <X> is a bare quantity, e.g. "damaged transformers" -> "Transformers damaged
     Total"; "connections" -> "Total"), and entity = null. Do NOT clarify — the
     system finds the top/bottom row.
   - A SEGREGATION / breakup / category-wise / by-type / split / bifurcation
     request asks for ALL category columns of a dataset ("segregation on
     connection type" -> every connection category, not the Total). Return ONE
     selection: the dataset, entity = the named district or null (utility-wide),
     metric = "Total" (a placeholder — the system expands to every category column
     except Total). Do NOT clarify.
5. status:
   - "answer"  -> you identified the dataset(s) and metric(s). Use this whenever a
     catalog dataset fits, EVEN IF the user named no district/period.
   - "clarify" -> a catalog dataset fits but you genuinely cannot tell WHICH
     metric the user means (several unrelated metrics could be intended). Put a
     short question in clarify_reason and set selections to []. Do NOT clarify
     merely because a district or period was not named. Do NOT clarify when the
     user has named a category that maps to a real column (directly, via an
     abbreviation, or from the conversation) — answer with that column and the
     utility-wide default entity. Prefer answering over clarifying whenever a
     column is identifiable.
     Write clarify_reason in PLAIN consumer language — NEVER use the words
     "dataset", "metric", or "column". Instead name concrete examples, e.g.
     "Did you mean domestic connections, or connected load?".
   - "prose"   -> the question is procedural/explanatory/definitional, OR NO
     dataset in the catalog fits it (e.g. "procedure for a new connection", "what
     does AT&C loss mean", "APPC year wise", "GDP of France"). When unsure between
     clarify and prose for an unfamiliar topic, choose prose. Set selections to [].
6. confidence = how sure you are about the dataset+metric mapping (0..1).
7. NEVER output a figure. Only identifiers copied from the catalog or the user's
   wording.

EXAMPLES (catalog abbreviated; copy real metric strings from the actual catalog):
Q: "How many connections in Karnal?"
A: {"status":"answer","confidence":0.95,"selections":[{"dataset":"connection","metric":"Total","entity":"Karnal","period":null}]}
Q: "How many domestic connections?"
A: {"status":"answer","confidence":0.95,"selections":[{"dataset":"connection","metric":"Domestic","entity":null,"period":null}]}
Q: "How many connections and total load?"
A: {"status":"answer","confidence":0.9,"selections":[{"dataset":"connection","metric":"Total","entity":null,"period":null},{"dataset":"connected_load","metric":"Total","entity":null,"period":null}]}
Q: "What is the collection efficiency?"
A: {"status":"answer","confidence":0.8,"selections":[{"dataset":"circle_collection_efficiency","metric":"<most-recent-period Collection efficiency column>","entity":null,"period":null}]}
Q: "What is the procedure for a new connection?"
A: {"status":"prose","confidence":0.9,"selections":[]}
Q: "What is the APPC year wise?"
A: {"status":"prose","confidence":0.8,"selections":[]}

Reply with ONLY the JSON object.
"""


def render_catalog(schema: dict, *, max_entities: int = _MAX_ENTITIES_SHOWN) -> str:
    """Render the SQLite-derived schema into the compact JSON shown to the LLM."""
    catalog = {
        ds: {
            "title": info.get("title") or ds.replace("_", " "),
            "metrics": info["metrics"],
            "entities": info["entities"][:max_entities],
        }
        for ds, info in schema.items()
    }
    return json.dumps(catalog, ensure_ascii=False)


def normalise(raw: dict | None) -> dict:
    """Coerce a model response into the intent contract with safe defaults.

    Anything malformed degrades to a low-confidence 'clarify' so the caller asks
    the user rather than guessing — never to a fabricated answer.
    """
    raw = raw or {}
    status = raw.get("status")
    if status not in ("answer", "clarify", "prose"):
        status = "clarify"
    try:
        confidence = float(raw.get("confidence", 0.0))
    except (TypeError, ValueError):
        confidence = 0.0

    selections: list[dict] = []
    for sel in raw.get("selections") or []:
        if not isinstance(sel, dict) or not sel.get("dataset"):
            continue
        selections.append({
            "dataset": str(sel["dataset"]).strip(),
            "metric": (str(sel["metric"]).strip() if sel.get("metric") else None),
            "entity": (str(sel["entity"]).strip() if sel.get("entity") else None),
            "period": (str(sel["period"]).strip() if sel.get("period") else None),
        })

    return {
        "status": status,
        "confidence": confidence,
        "selections": selections,
        "clarify_reason": raw.get("clarify_reason") or None,
    }


def extract(client, model: str, query: str, schema: dict, *,
            temperature: float = 0.0) -> dict:
    """Call the chat model in JSON mode and return a normalised intent dict."""
    catalog = render_catalog(schema)
    resp = client.chat.completions.create(
        model=model,
        temperature=temperature,  # deterministic routing
        response_format={"type": "json_object"},
        messages=[
            {"role": "system", "content": INTENT_PROMPT},
            {"role": "user",
             "content": f"CATALOG:\n{catalog}\n\nUSER QUESTION:\n{query}"},
        ],
    )
    content = resp.choices[0].message.content or "{}"
    try:
        parsed = json.loads(content)
    except json.JSONDecodeError:
        parsed = None
    return normalise(parsed)


def default_extractor(query: str, schema: dict) -> dict:
    """Production extractor: uses the shared OpenAI client and configured model.

    Imports of ``config``/``rag`` are deferred to here so that importing this
    module (and ``app.tables``) never requires an OpenAI key — only actually
    routing a live query does.
    """
    from . import config
    from .rag import client

    return extract(client, config.CHAT_MODEL, query, schema)
