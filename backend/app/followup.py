"""Conversational context: rewrite the latest user message into a standalone one.

The router (numeric via ``tables.respond``, prose via vector RAG) is stateless —
it only understands a fully-specified question. Real conversations aren't:

    User: Count in Ambala
    Bot:  Which count?
    User: Domestic                 -> means "Domestic count in Ambala"

    User: Who is the designated officer?
    User: And for shifting of meter? -> "Who is the designated officer for
                                         shifting of meter?"

Rather than a brittle, entity-specific slot machine, we do one generic step:
given the recent conversation, an LLM condenses the new message into a
self-contained question. That single mechanism covers clarification answers,
follow-ups and short replies ("Domestic", "Rural", "Zone-I", "Yes"), for ANY
entity/zone/dataset — nothing is hardcoded. A genuinely new or already-complete
message is returned unchanged, so context expires on a topic change.

Crucially this ONLY rewrites the question text. The rewritten query still flows
through the same router, so numbers still come from SQLite and prose from RAG —
this layer never produces an answer, a value, or an entity that wasn't asked for.

Kept free of ``config``/``rag`` at import time (OpenAI client imported lazily in
``default_rewriter``), mirroring ``intent.py``, so importing this module never
requires a key. The rewriter is injectable for offline testing.
"""

from __future__ import annotations

import re
from collections import Counter
from typing import Callable

# A rewriter maps (history, user_input) -> standalone question string.
Rewriter = Callable[[list[dict], str], str]


CONTEXTUALIZE_PROMPT = """\
You rewrite the user's LATEST message into a single, standalone question, using
ONLY the recent conversation for context. You do NOT answer it.

Rules:
1. Only borrow context from earlier turns when the latest message is ELLIPTICAL —
   it starts with a conjunction/preposition ("and for …", "what about …"), is a
   bare value/metric/category ("Domestic", "Total", "Rural", "Zone-I", "Yes"), or
   uses a pronoun. Then write the FULL question the user means. Carry over the
   SUBJECT — WHAT is being asked about (e.g. "connections", "connected load",
   "transformers damaged", "consumer base") — plus whichever of the
   district / period / metric the latest message does NOT itself provide; swap in
   the value it does provide and DROP the value it replaces. Keeping the subject
   is essential: a bare "total?" after a CONNECTIONS answer means "total
   CONNECTIONS in <that district>", never the total of some other dataset.
   Examples: after "domestic connections in Ambala", "and for Jhajjar?" ->
   "domestic connections in Jhajjar"; after "Zone-I domestic connections",
   "total?" -> "total connections in Zone-I".
2. If the latest message is ALREADY a complete question that states its own
   subject/metric, return it UNCHANGED — even if earlier turns named a district.
   Do NOT inject a district/period from earlier turns into a self-contained
   question (after discussing Kurukshetra, "how many connections and total load?"
   stays utility-wide, NOT "...in Kurukshetra"). A different topic is likewise
   returned unchanged.
3. Preserve the user's own wording and entities. Do NOT invent, translate, or
   guess any district, zone, category, dataset, figure, or fact. Only carry over
   words that actually appear in the conversation.
4. Never answer the question, never add information, never output a number.
5. Output ONLY the rewritten question as plain text — no quotes, no preamble,
   no explanation.

Examples:
Conversation:
User: Count in Ambala
Assistant: Which count? (e.g. Domestic, Non-domestic, Agriculture)
Latest: Domestic
Rewritten: Domestic count in Ambala

Conversation:
User: DS connections in Ambala
Assistant: Ambala — Domestic: 295,224
Latest: and for jhajjar?
Rewritten: Domestic connections in Jhajjar

Conversation:
User: How many domestic connections in Zone-I?
Assistant: Zone-I — Domestic: 1,314,372
Latest: total?
Rewritten: total connections in Zone-I

Conversation:
User: Transformer damaged in Kurukshetra
Assistant: Rural or Urban?
Latest: Rural
Rewritten: Transformer damaged in Kurukshetra Rural

Conversation:
User: Transformer damaged in Kurukshetra
Assistant: Kurukshetra Rural — 3,602
Latest: how many connections and total load?
Rewritten: how many connections and total load?

Conversation:
User: Who is the designated officer?
Assistant: The SDO.
Latest: And for shifting of meter?
Rewritten: Who is the designated officer for shifting of meter?

Conversation:
User: How many domestic connections in Panchkula?
Assistant: Panchkula — Domestic: 123456
Latest: What is the procedure for a new connection?
Rewritten: What is the procedure for a new connection?

Conversation:
User: How much security deposit will I pay?
Assistant: The security deposit (ACD) is 750 Rs/KW for domestic supply, 1000 Rs/KW for industrial...
Latest: For domestic?
Rewritten: security deposit for domestic
"""


# A message that begins like a follow-up (a connector) is never self-contained.
_FOLLOWUP_START_RE = re.compile(
    r"^\s*(?:and|or|but|also|then|plus|&|what about|how about|for)\b", re.I)
# Question cues that signal a message carries its own request.
_INTERROGATIVE_RE = re.compile(
    r"\b(?:how many|how much|number of|no\.?\s*of|what|which|who|whom|whose|"
    r"list|show|give)\b", re.I)
# Back-references to a prior answer ("how many of THOSE…", "what about them") —
# grammatically complete but they must be resolved against the conversation.
_BACKREF_RE = re.compile(
    r"\b(?:those|them|these|it|they|of\s+(?:those|them|these|it|that)|that\s+one|"
    r"the\s+(?:previous|last|above|earlier)\s+\w+)\b", re.I)


# Cues that the user is asking ABOUT the conversation / our own prior answer,
# rather than posing a new data or policy question. Conservative — it matches
# back-references ("is that…", "that number") and explicit self-references
# ("you said", "the source", "repeat that"), but NOT ordinary follow-ups
# ("and for Jhajjar?", "domestic?", "what about Karnal?").
_META_CUE_RE = re.compile(
    r"\byou\s+(?:said|mentioned|gave|showed|told|reported)\b"
    r"|\byour\s+(?:last\s+)?(?:answer|reply|response|figure|number|result)\b"
    r"|\brepeat\s+(?:that|it|this)\b|\bsay\s+(?:that|it|this)\s+again\b"
    r"|\bwhere\s+(?:did|does)\s+(?:this|that|it)\s+come\s+from\b"
    r"|\bwhat(?:'s|\s+is|\s+was)?\s+the\s+source\b"
    r"|\bwhat\s+does\s+(?:this|that|it)\b.*\b(?:mean|refer)\b"
    r"|\bwhich\s+\w+\s+(?:is|was)\s+(?:this|that)\b"
    r"|\bis\s+(?:this|that)\b"
    r"|\b(?:this|that)\s+(?:number|figure|count|value|reading|amount|answer|result)\b",
    re.I)


# Comparison/ranking follow-ups that reason over values ALREADY shown ("which is
# higher?", "which one is bigger?", "what's the difference?"). Conservative: it
# matches anaphoric "which is/one …" comparisons, NOT a broad new data question
# like "which district has the most connections?" ("which district …" is skipped).
_COMPARE_RE = re.compile(
    r"\bwhich\s+(?:one\s+)?(?:is|are|has|of\s+(?:them|these|those))\b"
    r"|\bwhich\s+(?:is|one)\b.{0,40}\b(?:higher|lower|bigger|smaller|greater|"
    r"larger|less|more|highest|lowest|biggest|smallest|greatest|largest|most|"
    r"maximum|minimum)\b"
    r"|\bwhat(?:'s|\s+is|\s+was)?\s+the\s+difference\b"
    r"|\bhow\s+much\s+(?:more|less|higher|lower|bigger|greater)\b",
    re.I)


def is_meta_question(message: str) -> bool:
    """True if the message asks about the conversation / our own previous answer,
    including a comparison/ranking of values already given."""
    return bool(_META_CUE_RE.search(message) or _COMPARE_RE.search(message))


# A bare "Difference?" / "gap?" / "how much more?" follow-up is a comparison of
# the two values already given — even without the "what is the" framing.
_DIFF_RE = re.compile(
    r"\b(?:difference|diff|gap)\b|\bhow\s+much\s+(?:more|less|higher|lower|"
    r"bigger|greater|difference)\b", re.I)


def is_comparison_question(message: str) -> bool:
    """True for a 'which is higher / what's the difference' style follow-up."""
    return bool(_COMPARE_RE.search(message) or _DIFF_RE.search(message))


# A formatted fact line from a prior answer, plus its "(Source: …)" line:
#   Ambala — Total: 394,560 KW (as of …)
#   (Source: 2_Connected_Load.pdf, Row: Ambala, Column: Total)
_FACT_LINE_RE = re.compile(
    r"(?m)^\s*(.+?)\s+[—-]\s+(.+?):\s+([\d,]+(?:\.\d+)?)\s*([A-Za-z%]*)"
    r"[^\n]*(?:\n\s*\(Source:\s*([^,)\n]+))?")
_LOWER_WORDS = ("lower", "less", "smaller", "lowest", "smallest", "minimum", "least")
# Words that frame a comparison but don't identify the SUBJECT to compare.
_CMP_STOP = {
    "which", "what", "whats", "is", "are", "was", "were", "the", "between", "and",
    "or", "for", "of", "in", "to", "by", "be", "do", "does", "did", "than", "has",
    "have", "had", "one", "ones", "them", "these", "those", "more", "less", "most",
    "least", "higher", "lower", "bigger", "smaller", "greater", "larger", "highest",
    "lowest", "biggest", "smallest", "largest", "greatest", "maximum", "minimum",
    "difference", "compare", "vs",
    # quantity-framing words — they frame "how much / how many" but never name the
    # subject, so they must not be mistaken for a mismatching subject token.
    "how", "much", "many",
}
# The utility-wide aggregate row — comparing a district to the grand total is
# meaningless (the whole always beats a part), so it's dropped from a comparison
# whenever specific rows are present.
_AGG_ENTITY_RE = re.compile(
    r"^(?:grand\s+total|total(?:\s*\(r\+u\))?(?:\s+uhbvn)?|uhbvn|overall)$", re.I)


def _recent_facts(history: list[dict], max_msgs: int = 8) -> list[dict]:
    """Pull the (entity, metric, value, unit) facts our OWN recent answers stated.

    Walks newest-first and STOPS once two distinct entities have been collected, so
    "which is greater?" compares the two rows the user just discussed — not a third
    row mentioned several turns earlier. These came from SQLite; comparing them is
    deterministic and grounded — the numbers are never re-generated by the LLM."""
    facts: list[dict] = []
    entities: set[str] = set()
    for msg in reversed(history[-max_msgs:]):
        if msg.get("role") != "assistant":
            continue
        msg_facts: list[dict] = []
        for m in _FACT_LINE_RE.finditer(msg.get("content", "")):
            try:
                value = float(m.group(3).replace(",", ""))
            except ValueError:
                continue
            msg_facts.append({"entity": m.group(1).strip(), "metric": m.group(2).strip(),
                              "num": m.group(3), "unit": m.group(4).strip(), "value": value,
                              "source": (m.group(5) or "").strip()})
        facts = msg_facts + facts  # keep chronological order overall
        entities |= {f["entity"] for f in msg_facts}
        if len(entities) >= 2:  # enough context for a comparison; stop looking back
            break
    return facts


def _subject_tokens(question: str) -> set[str]:
    """Content words (de-pluralised) that identify WHICH quantity to compare.

    De-pluralising, not truncating, keeps the token discriminative: "connections"
    -> "connection" matches 1_Connection.pdf but NOT 2_Connected_Load.pdf.
    """
    toks = set()
    for w in re.findall(r"[a-z]+", question.lower()):
        if len(w) >= 3 and w not in _CMP_STOP:
            toks.add(w[:-1] if w.endswith("s") and len(w) > 4 else w)
    return toks


def _fmt_num(value: float) -> str:
    v = float(value)
    return f"{int(v):,}" if v.is_integer() else f"{v:,.2f}"


def _norm_unit(unit: str | None) -> str:
    u = (unit or "").strip()
    return "" if u.lower() == "count" else u


def compare_facts(facts: list[dict], question: str) -> str | None:
    """Compare/rank grounded facts deterministically. ``facts`` may come from prior
    answers (``_recent_facts``) or from a fresh SQLite lookup (``tables.respond``).

    Returns None when there aren't at least two comparable values (same metric +
    unit), so the caller says "not found" rather than letting an LLM invent
    numbers. The utility-wide total is dropped when specific rows are present.
    """
    norm: list[dict] = []
    for f in facts:
        if f.get("value") is None:
            continue
        ctx = f"{f.get('metric','')} {f.get('unit','')} {f.get('source','')} " \
              f"{f.get('dataset','')}".lower()
        norm.append({
            "entity": f["entity"], "metric": f["metric"], "value": float(f["value"]),
            "unit": _norm_unit(f.get("unit")),
            "num": f.get("num") or _fmt_num(f["value"]), "ctx": ctx,
        })
    if len(norm) < 2:
        return None

    # If the question names a subject ("...more LOAD?"), keep only the facts whose
    # metric/unit/source/dataset matches it — so "load" compares the KW figures,
    # not the connection counts that happen to share the metric name "Total".
    subject = _subject_tokens(question)
    if subject:
        matched = [f for f in norm if any(s in f["ctx"] for s in subject)]
        if len({f["entity"] for f in matched}) >= 2:
            norm = matched

    metric_unit = Counter((f["metric"], f["unit"]) for f in norm).most_common(1)[0][0]
    by_entity: dict[str, dict] = {}
    for f in norm:
        if (f["metric"], f["unit"]) == metric_unit:
            by_entity[f["entity"]] = f  # keep the latest value per entity
    group = list(by_entity.values())
    specific = [f for f in group if not _AGG_ENTITY_RE.match(f["entity"].strip())]
    if len(specific) >= 2:
        group = specific
    if len(group) < 2:
        return None

    ql = question.lower()
    low = any(w in ql for w in _LOWER_WORDS)
    ranked = sorted(group, key=lambda f: f["value"], reverse=not low)
    metric = ranked[0]["metric"]

    def label(f: dict) -> str:
        unit = f" {f['unit']}" if f["unit"] else ""
        return f"{f['entity']} ({f['num']}{unit})"

    if "difference" in ql:
        diff = abs(ranked[0]["value"] - ranked[-1]["value"])
        ds = f"{int(diff):,}" if float(diff).is_integer() else f"{diff:,.2f}"
        unit = f" {ranked[0]['unit']}" if ranked[0]["unit"] else ""
        return (f"The difference in {metric} between {label(ranked[0])} and "
                f"{label(ranked[-1])} is {ds}{unit}.")

    word = "lower" if low else "higher"
    superlative = "lowest" if low else "highest"
    if len(ranked) == 2:
        return f"{label(ranked[0])} has a {word} {metric} than {label(ranked[1])}."
    others = ", ".join(label(f) for f in ranked[1:])
    return f"{label(ranked[0])} has the {superlative} {metric}. Others: {others}."


def compare_from_history(history: list[dict], question: str) -> str | None:
    """Comparison answered from the values in our own recent answers."""
    return compare_facts(_recent_facts(history), question)


def _fact_ctx(f: dict) -> str:
    return (f"{f.get('metric', '')} {f.get('unit', '')} {f.get('source', '')} "
            f"{f.get('dataset', '')}").lower()


def _subject_matches(subject: set[str], facts: list[dict]) -> bool:
    return any(any(s in _fact_ctx(f) for s in subject) for f in facts)


def _ordered_entities(facts: list[dict]) -> list[str]:
    """Distinct non-aggregate entities in first-seen order."""
    seen, out = set(), []
    for f in facts:
        e = f["entity"].strip()
        if _AGG_ENTITY_RE.match(e) or e in seen:
            continue
        seen.add(e)
        out.append(f["entity"])
    return out


def _subject_phrase(question: str) -> str:
    """The subject words of a comparison question ("which has more DOMESTIC
    CONSUMERS?" -> "domestic consumers"), used to re-query a different metric."""
    words = [w for w in re.findall(r"[A-Za-z]+", question)
             if w.lower() not in _CMP_STOP]
    return " ".join(words)


def compare_answer(history: list[dict], question: str,
                   db_path: str | None = None) -> str | None:
    """Deterministic comparison. Prefers the grounded history, but if the question
    names a SUBJECT that the recent facts DON'T match ("which has more
    CONNECTIONS?" right after a LOAD comparison), it RE-FETCHES that subject for
    the same entities from SQLite instead of reusing the wrong (load) values.
    """
    from . import tables

    recent = _recent_facts(history)
    subject = _subject_tokens(question)
    entities = _ordered_entities(recent)

    # The question names a SUBJECT that the recent facts don't cover ("...more
    # CONNECTIONS?" after a LOAD comparison, or a conceptual "difference between SLDC
    # and RLDC" while the history holds HT-Lines figures).
    subject_mismatch = bool(subject) and not _subject_matches(subject, recent)

    # Subject mismatch -> re-fetch that subject for the same entities.
    if subject_mismatch and len(entities) >= 2:
        query = f"{_subject_phrase(question)} in {' and '.join(entities[:4])}"
        routed = tables.respond(query, db_path)
        if routed.get("status") == "answer":
            fresh = compare_facts(routed.get("facts", []), question)
            if fresh:
                return fresh

    # Compare the grounded history ONLY when it's about the subject asked. If the
    # question named a DIFFERENT subject that we couldn't re-fetch, do NOT compare the
    # unrelated numbers (that invents a nonsense "difference in HT Lines" for two
    # glossary terms) — fall through so the caller can explain it conceptually.
    if not subject_mismatch:
        result = compare_facts(recent, question)
        if result:
            return result

    # Self-contained comparison with nothing usable in history -> fresh lookup.
    routed = tables.respond(question, db_path)
    if routed.get("status") == "answer":
        return compare_facts(routed.get("facts", []), question)
    return None


# Patterns that mark a NUMERIC-path answer/clarify, so a following elliptical
# message is NOT mistaken for a prose continuation.
_NUMERIC_CLARIFY_RE = re.compile(
    r"please name the (?:metric|circle|year|period)"
    r"|I have .*? data, but"
    r"|I found .*? data \("
    r"|Data not found in the provided tables"
    r"|pick one of those", re.I)
# A deterministic COMPARISON result — derived from numeric facts, not prose. A
# follow-up after it belongs to the numeric/slot path, NOT RAG (else a numeric
# query like "Total load in Karnal" gets pushed to RAG and can be fabricated).
_COMPARISON_RESULT_RE = re.compile(
    r"\bhas a (?:higher|lower)\b.*\bthan\b"
    r"|\bhas the (?:highest|lowest)\b"
    r"|\bThe difference in\b.*\bis\b"
    r"|\bhas more\b.*\bcompared to\b", re.I)


def _last_answer_was_prose(history: list[dict]) -> bool:
    """True if our most recent substantive answer was a PROSE/RAG reply (not a
    grounded numeric fact, numeric clarify, comparison result, or not-found line)."""
    for msg in reversed(history):
        if msg.get("role") != "assistant":
            continue
        content = (msg.get("content") or "").strip()
        if not content:
            return False
        if (_PROVENANCE_RE.search(content) or _NUMERIC_CLARIFY_RE.search(content)
                or _COMPARISON_RESULT_RE.search(content)):
            return False
        if content == "I could not find this information in the knowledge base.":
            return False
        if "?" in content:  # a clarifying QUESTION ("Which count?"), not prose
            return False
        return len(content) >= 80  # substantive prose answer, not a short clarify
    return False


def is_prose_followup(history: list[dict], user_input: str) -> bool:
    """True when the last substantive answer was PROSE and this message is an
    elliptical follow-up, so we CONTINUE in prose instead of letting the numeric
    path hijack a shared word. E.g. after "security deposit" rates, "for domestic?"
    must give the domestic DEPOSIT (Rs.750/KW), not the domestic connection count."""
    if is_self_contained(user_input):
        return False
    return _last_answer_was_prose(history)


def is_self_contained(message: str) -> bool:
    """A clearly complete question that must NOT be rewritten with prior context.

    Conservative on purpose: True only when the message does not start like a
    follow-up, is reasonably long, and reads as its own question. This stops the
    rewriter from injecting stale context into a fresh question ("how many
    connections in Karnal?" after a domestic-Panchkula turn) — deterministically,
    not at the LLM's whim — while genuinely elliptical replies ("Domestic",
    "and for Jhajjar?", "Rural") still go to the rewriter.
    """
    m = message.strip()
    if _FOLLOWUP_START_RE.match(m):
        return False
    if _BACKREF_RE.search(m):  # "how many of THOSE…" needs the conversation
        return False
    if len(re.findall(r"\w+", m)) < 4:
        return False
    return bool(_INTERROGATIVE_RE.search(m)) or m.endswith("?")


# --------------------------------------------------------------------------- #
# Deterministic conversational slots: active_dataset / active_entity /
# active_metric.
#
# The LLM rewriter (above) resolves most follow-ups, but it is non-deterministic
# and occasionally loses the pinned dataset or metric across a chain
# ("Domestic → Total → Load → Breakup"). This layer recovers the three slots
# from the LAST grounded answer (its provenance lines) and updates ONLY the
# dimension the new message actually names, keeping the rest — then routes the
# result deterministically. It is deliberately conservative: if it cannot map the
# follow-up cleanly onto a single slot change it returns None and the LLM path
# runs unchanged, so this can only ADD correct answers, never regress.
# --------------------------------------------------------------------------- #
_PROVENANCE_RE = re.compile(
    r"\(Source:\s*([^,]+?),\s*Row:\s*(.+?),\s*Column:\s*([^)]+?)\)")

# Generic / ambiguous tokens in dataset keys that must NOT trigger a dataset
# switch: they are either filler ("year wise") or sub-labels that are really
# ENTITY words ("urban"/"rural" = Kurukshetra Urban), or shared by >1 dataset.
_DS_STOP = {
    "year", "wise", "yearly", "circle", "total", "name", "month", "end", "new",
    "line", "lines", "ratio", "abstract", "received", "billed", "losses", "loss",
    "feeder", "urban", "rural", "ror", "arr", "atc", "rds", "2021", "2015",
    "2016", "2020",
}


def _last_answer_slots(history: list[dict], con, trusted: set[str]) -> dict | None:
    """Recover (dataset, entity, metric) from the most recent grounded answer.

    entity/metric are set only when the whole answer used a SINGLE row / column;
    a list answer (segregation, circle-wise) leaves the ambiguous slot as None."""
    smap = {src: ds for ds, src in
            con.execute("SELECT DISTINCT dataset, source FROM facts")}
    for msg in reversed(history):
        if msg.get("role") != "assistant":
            continue
        prov = _PROVENANCE_RE.findall(msg.get("content", ""))
        if not prov:
            continue
        datasets = {smap.get(s.strip()) for s, _, _ in prov} & trusted
        if len(datasets) != 1:
            return None
        rows = {r.strip() for _, r, _ in prov}
        cols = {c.strip() for _, _, c in prov}
        return {
            "dataset": next(iter(datasets)),
            "entity": next(iter(rows)) if len(rows) == 1 else None,
            "metric": next(iter(cols)) if len(cols) == 1 else None,
        }
    return None


def _agg_column(cols: list[str], tables) -> str | None:
    for c in cols:
        if c.lower() in tables._AGG_NAMES:
            return c
    return None


# Domain words that indicate a dataset beyond the raw key tokens. "count/number"
# means the connection COUNT report; "load/kw" means the connected-LOAD report —
# this is how the user distinguishes 1_Connection from 2_Connected_Load.
_DS_HINT = {
    "count": "connection", "counts": "connection", "number": "connection",
    "load": "connected_load", "kw": "connected_load",
}


def _switch_dataset(msg: str, trusted: set[str], active: str) -> str | None:
    """The dataset the message explicitly switches to, or None when it names none /
    only the active one / is ambiguous. Scores by how many distinctive key tokens
    match, so "damaged transformers" (2 hits) beats "distribution transformer" (1)."""
    ql = f" {msg.lower()} "

    def _hit(tok: str) -> bool:
        # Match singular/plural: the query word "transformer" must match BOTH the
        # "transformers" key token (damaged_transformers) and "transformer"
        # (distribution_transformer) — else a plural-only match wrongly wins.
        stem = tok[:-1] if tok.endswith("s") and len(tok) > 4 else tok
        return bool(re.search(rf"\b{re.escape(stem)}s?\b", ql))

    scored: dict[str, int] = {}
    for ds in trusted:
        n = sum(1 for t in re.split(r"[_\s&]+", ds)
                if len(t) >= 4 and t not in _DS_STOP and _hit(t))
        if n:
            scored[ds] = n
    for word, ds in _DS_HINT.items():
        if ds in trusted and re.search(rf"\b{word}\b", ql):
            scored[ds] = scored.get(ds, 0) + 1
    # Switch only to a dataset matching STRICTLY BETTER than the active one, so
    # re-stating the active subject ("damaged transformers circle wise" while
    # already on damaged_transformers) does NOT get pulled to a weaker match
    # (distribution_transformer, which shares only "transformer").
    active_score = scored.get(active, 0)
    candidates = {ds: n for ds, n in scored.items()
                  if ds != active and n > active_score}
    if not candidates:
        return None
    best = max(candidates.values())
    top = [ds for ds, n in candidates.items() if n == best]
    return top[0] if len(top) == 1 else None


def _entity_in(msg: str, rows: list[str], tables) -> str | None:
    """The single row the message names, else None. Scores each row by the total
    LENGTH of its distinctive tokens that appear in the message, so "Zone-I total"
    picks Zone-I (matches "zone-i"+"zone") over Zone-II (only "zone"), while a bare
    sub-label like "Urban" (equal-length match on many rows) stays ambiguous ->
    None and defers to the LLM."""
    ql = msg.lower()
    qn = tables._canon(msg)
    scored = [(sum(len(t) for t in tables._entity_tokens(e) if t in ql or t in qn), e)
              for e in rows]
    best = max((s for s, _ in scored), default=0)
    if best == 0:
        return None
    top = [e for s, e in scored if s == best]
    return top[0] if len(top) == 1 else None


def _mentions_unknown_place(msg: str, rows: list[str], cols: list[str],
                            con, tables) -> bool:
    """True if the message names a location we don't have (e.g. "on moon"), so the
    slot path must defer and let ``find_entity``'s guard refuse rather than
    inheriting a stale row. Mirrors that guard's vocabulary."""
    known = {t for e in rows for t in tables._entity_tokens(e)}
    known |= {t for c in cols for t in tables._col_tokens(c)}
    known |= tables._UTILITY_SYNS | tables._MONTHS | tables._global_vocab(con)
    for m in tables._LOC_RE.finditer(msg):
        words = [w for w in re.findall(r"[a-z]+", m.group(1).lower())
                 if w not in tables._LOC_FILLER]
        if words and all(not tables._fuzzy_member(w, known) for w in words):
            return True
    return False


def _metric_in(msg: str, cols: list[str], tables) -> str | None:
    """The single column the message names, else None. Handles the aggregate
    'Total' explicitly (its only token is a stop-word, so it never surfaces via
    the generic column matcher)."""
    named = tables._top_scoring(tables.explicit_columns(cols, msg), msg)
    if named:
        return named[0]
    if re.search(r"\b(total|overall|aggregate)\b", msg, re.I):
        return _agg_column(cols, tables)
    return None


def resolve_followup(history: list[dict], user_input: str,
                     db_path: str | None = None) -> dict | None:
    """Merge an elliptical follow-up onto the active slots and return a routing
    plan ``{"query", "intent"}`` for deterministic lookup — or None to defer to
    the LLM rewriter. Updates ONLY the dimension the message names.
    """
    from . import tables

    msg = user_input.strip().rstrip("?!. ").strip()
    if not msg:
        return None
    con = tables._connect(db_path)
    try:
        trusted = tables.trusted_datasets(con)
        prior = _last_answer_slots(history, con, trusted) if trusted else None
        if not prior:
            return None

        new_ds = _switch_dataset(msg, trusted, prior["dataset"])
        ds = new_ds or prior["dataset"]
        if ds not in trusted:
            return None
        cols = tables.columns_of(con, ds)
        rows = [r[0] for r in con.execute(
            "SELECT DISTINCT entity FROM facts WHERE dataset=?", (ds,))]

        seg = bool(tables._SEGREGATION_RE.search(user_input))
        rowwise = bool(tables._ROWWISE_RE.search(user_input))
        ent = _entity_in(msg, rows, tables)

        # Safety: the message names a place we don't have ("on moon", "in Delhi").
        # Defer so the normal path's find_entity guard REFUSES, instead of
        # inheriting the stale prior entity and serving a wrong row.
        if ent is None and _mentions_unknown_place(msg, rows, cols, con, tables):
            return None

        metric_named = _metric_in(msg, cols, tables)
        # Nothing recognisable to inherit-onto -> let the LLM handle it.
        if not (ent or new_ds or seg or rowwise or metric_named):
            return None

        # A message that re-states a multi-word subject ("connected load",
        # "damaged transformers") is a FRESH scope: don't drag the old entity in.
        strong = bool(new_ds) and sum(
            1 for t in re.split(r"[_\s&]+", new_ds)
            if len(t) >= 4 and t not in _DS_STOP
            and re.search(rf"\b{re.escape(t)}s?\b", msg.lower())) >= 2

        # Fill the metric slot, changing it ONLY when the message named one (or a
        # dataset switch invalidated the old column).
        if seg:
            metric = "Total"                       # placeholder; expands to all columns
        elif rowwise:
            # Honour a named column; on a fresh dataset with none named use the
            # aggregate ("load circle wise" -> Total load per circle, not the prior
            # dataset's Domestic); otherwise inherit the active metric.
            metric = (metric_named or (_agg_column(cols, tables) if new_ds
                      else prior["metric"]) or _agg_column(cols, tables) or "Total")
        elif metric_named:
            metric = metric_named
        elif new_ds:
            metric = (prior["metric"] if prior["metric"] in cols
                      else _agg_column(cols, tables))
        else:
            metric = prior["metric"]
        if not rowwise and not metric:
            return None

        # Fill the entity slot: the named row, else (for a fresh subject) none, else
        # inherit the active row for a pure dimension swap.
        entity = ent if ent else (None if strong else prior["entity"])
        intent = {"status": "answer", "confidence": 1.0, "selections": [
            {"dataset": ds, "metric": metric, "entity": entity, "period": None}]}
        return {"query": user_input, "intent": intent}
    finally:
        con.close()


# A previous answer that RANKED rows ("X has the highest/lowest <metric>").
_SUPERLATIVE_ANSWER_RE = re.compile(
    r"\bhas the (highest|lowest|most|least|maximum|minimum|greatest|largest|"
    r"smallest|fewest|top)\b", re.I)
_SUPERLATIVE_MIN_WORDS = ("lowest", "least", "minimum", "smallest", "fewest")


def superlative_refinement(history: list[dict], user_input: str,
                           db_path: str | None = None) -> str | None:
    """After a ranking answer ("which circle has the highest damaged transformers?"
    -> Karnal Rural), a follow-up naming a SUB-GROUP ("what about rural?", "and
    urban?") re-runs the SAME ranking restricted to rows matching that group —
    e.g. the top rural circle (Karnal Rural 5,193), NOT the aggregate Total Rural.
    Returns the formatted answer, or None when it doesn't apply."""
    from . import tables

    msg = user_input.strip().rstrip("?!. ").strip().lower()
    if not msg:
        return None
    last = next((m.get("content", "") for m in reversed(history)
                 if m.get("role") == "assistant"), "")
    if not last or not _SUPERLATIVE_ANSWER_RE.search(last):
        return None

    con = tables._connect(db_path)
    try:
        trusted = tables.trusted_datasets(con)
        slots = _last_answer_slots(history, con, trusted) if trusted else None
        if not slots or not slots.get("metric"):
            return None
        ds, metric = slots["dataset"], slots["metric"]

        rows = [r[0] for r in con.execute(
            "SELECT DISTINCT entity FROM facts WHERE dataset=?", (ds,))]
        # The message must name a QUALIFIER that cross-cuts MANY rows (a sub-label
        # like rural/urban, ~11 rows each), NOT a single district name (which
        # matches just its 2 Rural+Urban rows) — so "and urban?" re-ranks but
        # "in Ambala?" does not.
        qualifier = None
        for tok in re.findall(r"[a-z]+", msg):
            if len(tok) < 4:
                continue
            hits = [e for e in rows if tok in e.lower()
                    and not tables._is_aggregate_entity(e)]
            if len(hits) >= 3:
                qualifier = tok
                break
        if not qualifier:
            return None

        want_min = any(w in last.lower() for w in _SUPERLATIVE_MIN_WORDS)
        cells = [r for r in con.execute(
            "SELECT entity, value, unit, period, source FROM facts "
            "WHERE dataset=? AND metric_l=?", (ds, metric.lower()))
            if r[1] is not None and qualifier in r[0].lower()
            and not tables._is_aggregate_entity(r[0])]
        if len(cells) < 2:
            return None
        r = min(cells, key=lambda x: x[1]) if want_min else max(cells, key=lambda x: x[1])
        sup = "lowest" if want_min else "highest"
        return (f"{r[0]} has the {sup} {metric} ({tables._fmt_value(r[1], r[2])})"
                + (f" (as of {r[3]})" if r[3] else "")
                + f"\n(Source: {r[4]}, Row: {r[0]}, Column: {metric})")
    finally:
        con.close()


# A follow-up that switches to the TRANSFORMER domain ("DT / transformer / damage
# rate / failure rate") while the active grounded context is a DIFFERENT dataset.
# Inheriting the old metric would return an unrelated connection value, so instead
# we route to the transformer dataset — answering a clear metric, or ASKING when
# the metric is ambiguous. Safety: never serve a connection figure for a
# transformer question.
_TRANSFORMER_RE = re.compile(
    r"\bdt\b|\btransformers?\b|\bdamaged?\s+transformers?\b"
    r"|\b(?:damage|failure)\s+rate\b|\btransformer\s+(?:damage|failure)\b", re.I)
_TRANSFORMER_CLARIFY = (
    "This looks like a transformer question. Please clarify which figure you want:\n"
    "• Damaged transformer count\n"
    "• Damage rate (%) excluding warranty period\n"
    "• Damage rate (%) including warranty period")


_TRANSFORMER_CLARIFY_MARK = "This looks like a transformer question"


def _clarify_trigger_query(history: list[dict]) -> str:
    """The user message immediately preceding the last (clarification) bot message —
    it still holds the district for a bare option reply like "count"."""
    seen = False
    for msg in reversed(history):
        if not seen:
            if (msg.get("role") == "assistant"
                    and (msg.get("content") or "").startswith(_TRANSFORMER_CLARIFY_MARK)):
                seen = True
            continue
        if msg.get("role") == "user":
            return msg.get("content") or ""
    return ""


def pending_transformer_reply(history: list[dict], user_input: str,
                              db_path: str | None = None) -> str | None:
    """PENDING-CLARIFICATION resolver: if the LAST bot message was the transformer
    clarification, treat this message as the user PICKING an option and answer it,
    remembering the entity from the clarified query. Fires ONLY immediately after
    that clarification (detected from history), so it never affects other follow-up
    logic. Returns the answer text, or None to fall through to normal handling."""
    from . import tables

    last = next((m.get("content", "") for m in reversed(history)
                 if m.get("role") == "assistant"), "")
    if not last.startswith(_TRANSFORMER_CLARIFY_MARK):
        return None  # no pending transformer clarification

    ql = user_input.lower()
    if re.search(r"includ", ql):
        metric = "% Damage rate including warranty period Total"
    elif re.search(r"exclud", ql):
        metric = "% Damage rate excluding warranty period Total"
    elif re.search(r"\b(?:rate|percent\w*)\b", ql):
        metric = "% Damage rate excluding warranty period Total"  # default % figure
    elif re.search(r"\b(?:count|counts|number|damaged?|transformers?)\b", ql):
        metric = "Transformers damaged Total"
    else:
        return None  # not a recognisable pick -> let normal handling run

    intent = {"status": "answer", "confidence": 1.0, "selections": [
        {"dataset": "damaged_transformers", "metric": metric,
         "entity": None, "period": None}]}
    # Resolve the entity from THIS reply, else from the clarify-triggering query
    # (which named the district). The chosen metric is forced above.
    for q in (user_input, _clarify_trigger_query(history)):
        if not q:
            continue
        r = tables.respond(q, extractor=lambda qq, s: intent)
        if r.get("status") == "answer":
            return r["text"]
    return _TRANSFORMER_CLARIFY  # couldn't recover the district -> ask again


def transformer_domain_switch(history: list[dict], user_input: str,
                              db_path: str | None = None) -> str | None:
    """If an elliptical follow-up switches to the transformer domain while the last
    grounded answer was a DIFFERENT dataset, do NOT inherit the old metric: route to
    the transformer dataset (answer a clear metric like the damaged count) or ASK
    when it's ambiguous ("damage/failure rate"). Returns the reply text, or None to
    leave normal handling untouched. Fires only on the connection→transformer style
    domain switch, so all non-transformer follow-ups are unaffected."""
    from . import tables

    if not _TRANSFORMER_RE.search(user_input):
        return None
    con = tables._connect(db_path)
    try:
        trusted = tables.trusted_datasets(con)
        prior = _last_answer_slots(history, con, trusted) if trusted else None
        if not prior or "damaged_transformers" not in trusted:
            return None
        if "transformer" in (prior.get("dataset") or ""):
            return None  # already in the transformer domain -> normal slot handling
        # Pick the transformer metric. A bare "damage/failure rate" is ambiguous
        # (excl vs incl warranty) -> ASK; but a rate WITH a warranty specifier, or a
        # "count"/"damage" request, is concrete -> answer. (This also resolves the
        # user PICKING an option from a previous clarification.)
        ql = user_input.lower()
        has_rate = bool(re.search(r"\b(?:rate|failure)\b", ql))
        has_warranty = bool(re.search(r"\b(?:exclud\w*|includ\w*|warranty)\b", ql))
        if has_rate and not has_warranty:
            return _TRANSFORMER_CLARIFY
        if has_rate:
            metric = ("% Damage rate including warranty period Total"
                      if "includ" in ql
                      else "% Damage rate excluding warranty period Total")
        else:
            metric = "Transformers damaged Total"

        def _answer(entity):
            intent = {"status": "answer", "confidence": 1.0, "selections": [
                {"dataset": "damaged_transformers", "metric": metric,
                 "entity": entity, "period": None}]}
            r = tables.respond(user_input, extractor=lambda q, s: intent)
            return r.get("text") if r.get("status") == "answer" else None

        # Entity from THIS message, else inherit the context row — a clarification
        # reply ("Damaged transformer count") carries no district of its own.
        return (_answer(None) or (_answer(prior["entity"]) if prior.get("entity") else None)
                or _TRANSFORMER_CLARIFY)
    finally:
        con.close()


def _format_history(history: list[dict], max_turns: int) -> str:
    """Render the last ``max_turns`` messages as a plain transcript."""
    recent = history[-max_turns:] if max_turns > 0 else history
    lines = []
    for msg in recent:
        role = "User" if msg.get("role") == "user" else "Assistant"
        content = (msg.get("content") or "").strip()
        if content:
            lines.append(f"{role}: {content}")
    return "\n".join(lines)


def rewrite(client, model: str, history: list[dict], user_input: str,
            *, max_turns: int = 6) -> str:
    """Ask the model for the standalone form of ``user_input``.

    Returns ``user_input`` unchanged on any empty/degenerate result, so the
    caller can always route *something* and never blocks on this step.
    """
    transcript = _format_history(history, max_turns)
    if not transcript:
        return user_input
    user_msg = (f"Conversation:\n{transcript}\n\nLatest: {user_input}\n\n"
                f"Rewritten:")
    resp = client.chat.completions.create(
        model=model,
        temperature=0,
        messages=[
            {"role": "system", "content": CONTEXTUALIZE_PROMPT},
            {"role": "user", "content": user_msg},
        ],
    )
    out = (resp.choices[0].message.content or "").strip().strip('"').strip()
    # Guard against a model that returns nothing useful.
    return out or user_input


def default_rewriter(history: list[dict], user_input: str) -> str:
    from . import config
    from .rag import client

    return rewrite(client, config.CHAT_MODEL, history, user_input,
                   max_turns=config.FOLLOWUP_HISTORY_TURNS)
