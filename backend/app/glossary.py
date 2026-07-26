"""Deterministic glossary lookup for abbreviation / definition queries.

The two ingested glossaries (Haryana_DISCOM_Abbreviations.txt,
Electricity_Department_Abbreviations.txt) live in the RAG knowledge base as
chunks. For a DEFINITION request ("what is AT&C Loss?", "full form of SAIFI", or a
bare distinctive abbreviation like "AT&C Loss") we answer straight from the
matching chunk — deterministic and reliable, so a known term never falls through
to a numeric clarify or a nondeterministic RAG "could not find".

Used only as a FALLBACK (after the structured numeric path and inside the
prose-continuation branch), so it never overrides a genuine data answer such as
"what is the collection efficiency?" (which has its own dataset).
"""

from __future__ import annotations

import re

_SOURCES = {"Haryana_DISCOM_Abbreviations.txt",
            "Electricity_Department_Abbreviations.txt"}
_index: dict[str, list[tuple[str, str]]] | None = None

# Definitional phrasing: "what is X", "full form of X", "define X", "who is X"
# (a designation), "what about X" (a follow-up).
_DEF_PREFIX = re.compile(
    r"^\s*(?:"
    r"what(?:'s|\s+is|\s+are|\s+does|\s+do)?\s+(?:the\s+)?"
    r"(?:full\s*form|meaning|abbreviation|expansion|long\s*form)\s+(?:of\s+)?"
    r"|(?:full\s*form|meaning|expansion|definition)\s+of\s+"
    r"|define\s+|expand\s+"
    r"|what(?:'s|\s+is|\s+are|\s+does|\s+do)\s+"
    r"|who(?:'s|\s+is|\s+are)\s+"
    r"|what\s+about\s+"
    r")", re.I)
_DEF_SUFFIX = re.compile(
    r"\s*(?:mean|means|meaning|stand[s]?\s+for|full\s*form|abbreviation)\s*$", re.I)


def _norm(s: str) -> str:
    return re.sub(r"\s+", " ", (s or "").strip()).strip(" ?.!:").lower()


def _field(lines: list[str], label: str) -> str:
    for ln in lines:
        if ln.startswith(label):
            return ln.split(":", 1)[1].strip()
    return ""


def _build_index() -> dict[str, list[tuple[str, str]]]:
    from . import rag
    idx: dict[str, list[tuple[str, str]]] = {}
    for item in rag.get_knowledge_db():
        if item.get("source") not in _SOURCES:
            continue
        text = item.get("text") or ""
        if "Full Form:" in text:                       # Haryana 4-field block
            lines = text.splitlines()
            abbr = lines[0].strip() if lines else ""
            definition = ". ".join(x for x in (_field(lines, "Full Form:"),
                                               _field(lines, "Description:")) if x)
        else:                                          # "ABBR - description"
            m = re.match(r"^(.{1,28}?)\s*[-–—]\s+(.+)$", text)
            if not m:
                continue
            abbr, definition = m.group(1).strip(), m.group(2).strip()
        key = _norm(abbr)
        if key and definition:
            idx.setdefault(key, []).append((abbr, definition))
    return idx


def _get_index() -> dict[str, list[tuple[str, str]]]:
    global _index
    if _index is None:
        _index = _build_index()
    return _index


def _sig(definition: str) -> str:
    """Signature of a meaning = first 3 words of the full-form head, normalised so
    trivial differences ('&' vs 'and', hyphens) collapse but genuine meanings
    (Power vs Potential, Average vs Aggregate) stay distinct."""
    head = re.split(r"[.(,/]", definition)[0].replace("&", " and ")
    return " ".join(re.findall(r"[a-z0-9]+", head.lower())[:3])


def _distinct(hits: list[tuple[str, str]]) -> list[tuple[str, str]]:
    """Collapse duplicate meanings (same term in both glossaries), keeping the
    richer (longer) definition; preserve genuinely different meanings."""
    best: dict[str, tuple[str, str]] = {}
    order: list[str] = []
    for abbr, d in hits:
        sig = _sig(d)
        if not sig:
            continue
        if sig not in best:
            best[sig] = (abbr, d)
            order.append(sig)
        elif len(d) > len(best[sig][1]):               # prefer the fuller definition
            best[sig] = (abbr, d)
    return [best[s] for s in order]


def define(query: str) -> str | None:
    """Return the definition(s) for a glossary-term query, else None. Genuinely
    ambiguous terms (PT, REC, GIS) return all their meanings."""
    q = (query or "").strip()
    if not q:
        return None
    idx = _get_index()
    m = _DEF_PREFIX.match(q)
    if m:
        term = _DEF_SUFFIX.sub("", q[m.end():])        # "what is AT&C Loss?" -> term
        allow = True
    else:
        term = q                                       # bare term
        # Only a distinctive bare term — avoid hijacking short numeric follow-ups
        # ("HT", "DS", "Total"); require length or a symbol/space (e.g. "AT&C Loss").
        # EXCEPTION: a genuinely AMBIGUOUS abbreviation with >=2 distinct meanings
        # (PT, GIS, REC) is safe to answer bare — those aren't slot dimensions, and a
        # user typing just "PT" wants exactly that disambiguation.
        preview = idx.get(_norm(q))
        multi = bool(preview) and len(_distinct(preview)) >= 2
        allow = multi or len(_norm(q)) >= 5 or bool(re.search(r"[&/]| ", q))
    hits = idx.get(_norm(term))
    if not hits or not allow:
        return None
    uniq = _distinct(hits)
    if len(uniq) == 1:
        abbr, definition = uniq[0]
        return f"{abbr} — {definition}"
    abbr = uniq[0][0]
    return f"{abbr} can refer to:\n" + "\n".join(f"• {d}" for _, d in uniq)


# "List metering terms", "Show safety abbreviations", "Show consumer categories".
_CATLIST_RE = re.compile(
    r"^\s*(?:list|show|give(?:\s+me)?|display|what\s+are\s+(?:the\s+)?)?\s*"
    r"(?:all\s+)?(?P<cat>.+?)\s+"
    r"(?:terms|abbreviations|abbrs?|acronyms|codes|categories|category)"
    r"\s*[.?!]?\s*$", re.I)
_CAT_STOP = {"the", "all", "of", "and", "list", "show", "give", "me", "display",
             "what", "are", "a", "an", "some"}
_category_index: dict[str, list[tuple[str, str]]] | None = None


def _stem(words: set[str]) -> set[str]:
    return {w[:-1] if w.endswith("s") and len(w) > 3 else w for w in words}


def _build_category_index() -> dict[str, list[tuple[str, str]]]:
    from . import rag
    idx: dict[str, list[tuple[str, str]]] = {}
    for item in rag.get_knowledge_db():
        if item.get("source") not in _SOURCES:
            continue
        text = item.get("text") or ""
        if "Category:" not in text:            # only the Haryana chunks carry Category
            continue
        lines = text.splitlines()
        abbr = lines[0].strip() if lines else ""
        cat = _field(lines, "Category:")
        ff = _field(lines, "Full Form:")
        if abbr and cat:
            idx.setdefault(cat, []).append((abbr, ff))
    return idx


def _get_category_index() -> dict[str, list[tuple[str, str]]]:
    global _category_index
    if _category_index is None:
        _category_index = _build_category_index()
    return _category_index


def list_category(query: str) -> str | None:
    """Deterministically list every abbreviation in a glossary CATEGORY ("show safety
    abbreviations" -> the Safety entries). Returns None when the phrasing isn't a
    category-list request or no category matches, so nothing else is affected."""
    m = _CATLIST_RE.match((query or "").strip())
    if not m:
        return None
    want = _stem({w for w in re.findall(r"[a-z]+", m.group("cat").lower())
                  if w not in _CAT_STOP})
    if not want:
        return None
    idx = _get_category_index()
    best, best_score = None, 0
    for cat in idx:
        have = _stem({w for w in re.findall(r"[a-z]+", cat.lower())
                      if w not in _CAT_STOP})
        score = len(want & have)
        if score > best_score:
            best_score, best = score, cat
    if not best or best_score < 1:
        return None
    entries = idx[best]
    body = "\n".join(f"• {a} — {ff}" if ff else f"• {a}" for a, ff in entries)
    return f"{best}:\n{body}"


def _split_segments(query: str) -> list[str]:
    """Break a batch message ("What is ACS?\\nWhat is ARR?" or "What is A? What is
    B?") into individual questions."""
    lines = [ln.strip() for ln in query.splitlines() if ln.strip()]
    if len(lines) >= 2:
        return lines
    parts = [p.strip() for p in re.split(r"(?<=\?)\s+", query.strip()) if p.strip()]
    return parts if len(parts) >= 2 else [query.strip()]


def define_multi(query: str) -> str | None:
    """Resolve a PURE batch of definition questions deterministically ("What is
    ACS?\\nWhat is ARR?\\n…"). Fires only when EVERY segment is a known glossary term,
    so a mixed batch ("What is HES? How does it work?") or a numeric multi-part
    prompt is left to the RAG/normal path, which handles the extra parts."""
    segments = _split_segments(query)
    if len(segments) < 2:
        return None
    resolved = [define(seg) for seg in segments]
    if all(resolved):
        return "\n\n".join(resolved)
    return None
