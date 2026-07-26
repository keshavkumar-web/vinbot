"""Retrieval layer: embeddings, cosine similarity and knowledge lookup.

This is the same logic as the original CLI ``chat_bot.py`` retrieval, refactored
into reusable functions with the knowledge base loaded lazily (so importing the
module never crashes when ``knowledge_db.pkl`` is missing).
"""

import os
import pickle
import re

import numpy as np
from openai import OpenAI

from . import config

# A single shared client for the whole process.
client = OpenAI(api_key=config.OPENAI_API_KEY)

# Lazily-loaded knowledge base. None = "not loaded yet".
_knowledge_db = None

# Cached embedding matrix + row norms for fast vectorised scoring across many
# sub-question queries in one turn. Invalidated whenever the DB is (re)loaded.
_emb_matrix = None
_emb_norms = None


def load_knowledge(path: str | None = None) -> list:
    """(Re)load the pickled knowledge base into memory.

    Returns an empty list (and logs a warning) when the file does not exist, so
    the API can still start and answer with "no information" instead of crashing.
    """
    global _knowledge_db, _emb_matrix, _emb_norms
    path = path or config.KNOWLEDGE_DB_PATH
    _emb_matrix = _emb_norms = None  # invalidate the cached matrix

    if not os.path.exists(path):
        print(f"[rag] WARNING: knowledge DB not found at {path}. "
              f"Running with an empty knowledge base.")
        _knowledge_db = []
        return _knowledge_db

    with open(path, "rb") as f:
        _knowledge_db = pickle.load(f)
    print(f"[rag] Loaded {len(_knowledge_db)} knowledge chunks from {path}.")
    return _knowledge_db


def get_knowledge_db() -> list:
    """Return the in-memory knowledge base, loading it on first use."""
    if _knowledge_db is None:
        load_knowledge()
    return _knowledge_db


def create_embedding(text: str) -> list[float]:
    """Embed a piece of text with the configured embedding model."""
    response = client.embeddings.create(model=config.EMBED_MODEL, input=text)
    return response.data[0].embedding


def create_embeddings(texts: list[str]) -> list[list[float]]:
    """Embed several texts in ONE API call (used for sub-question retrieval)."""
    response = client.embeddings.create(model=config.EMBED_MODEL, input=texts)
    # The API preserves input order in response.data.
    return [d.embedding for d in response.data]


def _ensure_matrix():
    """Build (and cache) the (N x dim) embedding matrix and per-row norms."""
    global _emb_matrix, _emb_norms
    if _emb_matrix is None:
        db = get_knowledge_db()
        if not db:
            _emb_matrix = np.zeros((0, 0), dtype=np.float32)
            _emb_norms = np.zeros((0,), dtype=np.float32)
        else:
            _emb_matrix = np.asarray([it["embedding"] for it in db], dtype=np.float32)
            _emb_norms = np.linalg.norm(_emb_matrix, axis=1)
    return _emb_matrix, _emb_norms


def _scores_for(query_embedding) -> np.ndarray:
    """Cosine similarity of one query against every chunk, vectorised."""
    mat, norms = _ensure_matrix()
    if mat.shape[0] == 0:
        return np.zeros((0,), dtype=np.float32)
    q = np.asarray(query_embedding, dtype=np.float32)
    qn = np.linalg.norm(q)
    if qn == 0:
        return np.zeros((mat.shape[0],), dtype=np.float32)
    return (mat @ q) / (norms * qn + 1e-9)


# Split a turn into sub-questions. First on hard boundaries (newlines and '?'),
# then on a conjunction/comma that PRECEDES an interrogative cue — so an inline
# "...for a new connection, and what is the surcharge?" splits into two, while
# "terms and conditions" (no cue after "and") stays whole.
_QSPLIT_RE = re.compile(r"[\n?]+")
_QMARKER_RE = re.compile(r"^\s*(?:\d+\s*[.)]|[-*•]|follow[\s-]*up)\s*", re.I)
_CUE = (r"what|how|why|when|where|which|who|whom|whose|can|could|would|should|"
        r"do|does|did|is|are|please|explain|list|tell|describe|define")
_SPLIT_BEFORE_CUE = re.compile(
    rf"(?:\s*[,;]\s*(?:and\s+)?|\s+and\s+)(?=(?:{_CUE})\b)", re.I)


def _clean_segment(raw: str) -> str | None:
    s = _QMARKER_RE.sub("", raw).strip()
    s = _QMARKER_RE.sub("", s).strip()  # a second marker like "4.And"
    if len(s) >= 12 and re.search(r"[a-zA-Z]{4,}", s):
        return s
    return None


def split_questions(text: str) -> list[str]:
    """Return the distinct sub-questions in ``text`` (>=1; [] only if all noise).

    Prefer HARD boundaries (newlines / '?' / list markers): each numbered line in
    a pasted list is already a complete, context-rich question, so we keep it
    whole — splitting "…how can I get it tested and what are the charges?" would
    strip "what are the charges" of its subject and wreck its retrieval. Only when
    the turn is a single run-on line do we fall back to conjunction splitting to
    break an inline "…connection, and what is the surcharge?" into two.
    """
    hard = [s for raw in _QSPLIT_RE.split(text) if (s := _clean_segment(raw))]
    if len(hard) > 1:
        return hard

    conj = [s for raw in _QSPLIT_RE.split(text)
            for piece in _SPLIT_BEFORE_CUE.split(raw)
            if (s := _clean_segment(piece))]
    return conj if len(conj) > 1 else hard


def cosine_similarity(a, b) -> float:
    """Cosine similarity between two vectors, guarded against zero vectors."""
    a = np.array(a)
    b = np.array(b)
    denom = np.linalg.norm(a) * np.linalg.norm(b)
    if denom == 0:
        return 0.0
    return float(np.dot(a, b) / denom)


# A circular / sales-instruction identifier, e.g. "U-01/2024", "U- 22/2017",
# "I-04/2017". Embeddings match *meaning*, not opaque ID codes, so a query naming
# a circular by number never retrieves its chunk by similarity. We add a lexical
# lookup for these.
_CIRCULAR_ID_RE = re.compile(r"\b([UI])\s*[-–]?\s*(\d{1,3})\s*/\s*((?:19|20)\d{2})\b", re.I)


def _extract_circular_ids(text: str) -> list[tuple[str, str, str]]:
    return _CIRCULAR_ID_RE.findall(text)


def find_id_chunks(user_input: str, db: list, limit: int = 4) -> list[tuple[float, dict]]:
    """Chunks that literally contain a circular/instruction ID named in the query.

    Tolerates the spacing/leading-zero variants seen in the source text
    ("U-01/2024" vs "U- 1/2024" vs "U -  01/2024"). Generic — matches whatever ID
    the user typed; no specific circular is hardcoded.
    """
    ids = _extract_circular_ids(user_input)
    if not ids:
        return []
    patterns = [re.compile(rf"{letter}\s*[-–]?\s*0*{int(num)}\s*/\s*{year}", re.I)
                for letter, num, year in ids]
    hits: list[tuple[float, dict]] = []
    for item in db:
        text = item.get("text", "")
        if any(p.search(text) for p in patterns):
            hits.append((1.0, item))
            if len(hits) >= limit:
                break
    return hits


# The RTS notified-services rows (designated officer / time limit per service) are
# short labelled chunks that don't always out-rank compendium prose; a lexical
# lookup guarantees the right service row is in context for these queries.
_RTS_TRIGGER = re.compile(
    r"designated officer|who is (?:responsible|concerned)|concerned officer|"
    r"who (?:handles|deals with)|in[- ]?charge of|right to service|\brts\b", re.I)
_RTS_SERVICE_WORDS = ("shifting", "meter", "new connection", "additional load",
                      "reconnection", "reduction of load", "change of name",
                      "temporary connection")


def find_rts_chunks(user_input: str, db: list, limit: int = 3) -> list[tuple[float, dict]]:
    """RTS_Act rows whose service matches the query — only for officer/RTS
    questions that name a service (a bare "designated officer?" injects nothing,
    so it still asks which service)."""
    if not _RTS_TRIGGER.search(user_input):
        return []
    ql = user_input.lower()
    words = [w for w in _RTS_SERVICE_WORDS if w in ql]
    if not words:
        return []
    hits: list[tuple[float, dict]] = []
    for item in db:
        if item.get("source") != "RTS_Act.pdf":
            continue
        if any(w in (item.get("text") or "").lower() for w in words):
            hits.append((1.0, item))
            if len(hits) >= limit:
                break
    return hits


def _inject_id_chunks(user_input: str, db: list,
                      vec: list[tuple[float, dict]]) -> list[tuple[float, dict]]:
    """Prepend lexical (circular-ID + RTS-service) chunks to the vector results."""
    id_hits = find_id_chunks(user_input, db) + find_rts_chunks(user_input, db)
    if not id_hits:
        return vec
    out: list[tuple[float, dict]] = []
    seen: set[tuple] = set()
    for score, item in id_hits + vec:
        key = (item.get("source"), (item.get("text") or "")[:80])
        if key not in seen:
            seen.add(key)
            out.append((score, item))
    return out[: config.RAG_MAX_CONTEXT_CHUNKS]


# Domain glossary: dense embeddings match words, not opaque abbreviations, so a
# question about "SDO"/"XEN"/"FGRA" doesn't retrieve the chunks that spell the role
# out. We append the expansions to the query BEFORE embedding so the role's
# definition surfaces. Generic vocabulary — not tied to any district/dataset.
_ABBREV_EXPANSIONS = {
    "sdo": "Sub Divisional Officer", "xen": "Executive Engineer",
    "aee": "Assistant Executive Engineer", "je": "Junior Engineer",
    "se": "Superintending Engineer", "ce": "Chief Engineer",
    "fgra": "First Grievance Redressal Authority",
    "sgra": "Second Grievance Redressal Authority",
    "cgrf": "Consumer Grievance Redressal Forum", "rts": "Right to Service",
    "acd": "Advance Consumption Deposit", "lps": "Late Payment Surcharge",
    "oa": "Open Access", "dtr": "Distribution Transformer",
    "nds": "Non Domestic Supply",
}
_ABBREV_RE = {a: re.compile(rf"\b{re.escape(a)}\b", re.I) for a in _ABBREV_EXPANSIONS}

# Consumer phrasing -> the exact term the figure sits under in the source, so the
# amount chunk (often a table) surfaces, not just the descriptive paragraph. A
# customer asks "how much security deposit", but the figure lives under "Advance
# Consumption Deposit"; "meter tested … cost" -> the "Meter Inspection and Testing
# Charges" table.
_METER_FEE = "Meter Inspection and Testing Charges Single Phase Rs per meter"
_PHRASE_SYNONYMS = {
    "designated officer": "Right to Service Act notified service Designated Officer "
                          "First Grievances Redressal Authority given time limit",
    "who is responsible": "Right to Service Act notified service Designated Officer",
    "security deposit": "Advance Consumption Deposit",
    "meter test": _METER_FEE,
    "meter tested": _METER_FEE,
    "testing fee": _METER_FEE,
    "test the meter": _METER_FEE,
    "reconnection": "reconnection charges",
    "name change": "change of name transfer of title",
}


def expand_query(query: str) -> str:
    """Append full forms of abbreviations and consumer-phrase synonyms so the
    chunk that actually holds the figure surfaces during retrieval."""
    ql = query.lower()
    extra: list[str] = [full for a, full in _ABBREV_EXPANSIONS.items()
                        if _ABBREV_RE[a].search(query) and full.lower() not in ql]
    extra += [full for phrase, full in _PHRASE_SYNONYMS.items()
              if phrase in ql and full.lower() not in ql]
    # de-dup, preserve order
    seen: set[str] = set()
    uniq = [e for e in extra if not (e.lower() in seen or seen.add(e.lower()))]
    return f"{query} {' '.join(uniq)}" if uniq else query


def retrieve_context(question: str) -> list[tuple[float, dict]]:
    """Return the top matching knowledge chunks as ``(score, item)`` tuples.

    Only chunks scoring at least ``MIN_SIMILARITY`` are considered, and at most
    ``TOP_K`` are returned, highest score first.
    """
    db = get_knowledge_db()
    if not db:
        return []

    question_embedding = create_embedding(expand_query(question))

    scored: list[tuple[float, dict]] = []
    for item in db:
        score = cosine_similarity(question_embedding, item["embedding"])
        if score >= config.MIN_SIMILARITY:
            scored.append((score, item))

    # Sort by score only (sorting the raw tuples would try to compare dicts on ties).
    scored.sort(key=lambda pair: pair[0], reverse=True)
    return scored[: config.TOP_K]


def retrieve_context_multi(user_input: str) -> list[tuple[float, dict]]:
    """Retrieval that survives multi-part prompts.

    A single embedding of "documents required? AND how is the deposit
    calculated? AND net metering rules?" is an *average* of all three topics and
    ranks generic chunks above any specific answer — so the bot wrongly says "I
    don't have it" for facts that ARE in the KB. We instead split the turn into
    sub-questions, retrieve each separately, and round-robin-merge so EVERY
    sub-question contributes its best chunks (breadth), capped for prompt size.

    Falls back to plain ``retrieve_context`` for a single question.
    """
    db = get_knowledge_db()
    if not db:
        return []
    subs = split_questions(user_input)
    if len(subs) <= 1:
        return _inject_id_chunks(user_input, db, retrieve_context(user_input))
    subs = subs[: config.RAG_MAX_SUBQUESTIONS]

    embeddings = create_embeddings([expand_query(s) for s in subs])
    per_sub = config.RAG_SUBQ_TOPK
    ranked_per_sub: list[list[tuple[int, float]]] = []
    for emb in embeddings:
        sims = _scores_for(emb)
        picks: list[tuple[int, float]] = []
        for i in np.argsort(-sims):
            score = float(sims[i])
            if score < config.MIN_SIMILARITY or len(picks) >= per_sub:
                break
            picks.append((int(i), score))
        ranked_per_sub.append(picks)

    # Round-robin by rank: every sub-question's #1 chunk first, then #2, ...
    merged: list[tuple[float, dict]] = []
    seen: set[int] = set()
    for rank in range(per_sub):
        for picks in ranked_per_sub:
            if rank < len(picks):
                idx, score = picks[rank]
                if idx not in seen:
                    seen.add(idx)
                    merged.append((score, db[idx]))
        if len(merged) >= config.RAG_MAX_CONTEXT_CHUNKS:
            break
    return _inject_id_chunks(user_input, db, merged[: config.RAG_MAX_CONTEXT_CHUNKS])


def format_context(scored: list[tuple[float, dict]]) -> str:
    """Render retrieved chunks into the text block injected into the prompt."""
    return "\n\n".join(
        f"[Source: {item['source']}]\n{item['text']}" for _, item in scored
    )
