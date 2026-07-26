"""Structured retrieval for UHBVN tabular reports.

The numeric reports under ``UHBVN_new/`` are positional tables (e.g. the
connection report has 23 columns where the value 3,003,464 only means
"Domestic" because of its *column position*). Linearising them to text and
char-chunking destroys that mapping, which is why the old RAG path returned the
Domestic figure for "how many connections" instead of the Total.

This module avoids that entirely:

  PDF  --PyMuPDF find_tables-->  (header, rows)  --normalise-->  long-format
  facts  --> SQLite (dataset, entity, metric, value, unit, period, source)

Every fact is a single self-describing cell, so a lookup returns the *exact*
column for the *exact* row, with provenance. No similarity, no guessing.
"""

from __future__ import annotations

import os
import re
import sqlite3
from difflib import SequenceMatcher
from pathlib import Path

# NOTE: PyMuPDF (``fitz``) is imported lazily inside extract_facts() so the
# serving app (chat.py -> tables.py) does not require it at runtime — only the
# build/ingest step does. This keeps PyMuPDF an ingest-only dependency
# (requirements-ingest.txt), matching the project's existing split.

# Resolve paths locally (no dependency on app.config, so ingestion runs without
# an OpenAI key configured).
BACKEND_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PROJECT_DIR = os.path.dirname(BACKEND_DIR)

DB_PATH = os.getenv("TABLES_DB_PATH", os.path.join(BACKEND_DIR, "uhbvn_tables.db"))
SOURCE_DIR = os.getenv("TABLES_SOURCE_DIR", os.path.join(PROJECT_DIR, "UHBVN_new"))
# Fallback to a sibling checkout layout if needed.
if not os.path.isdir(SOURCE_DIR):
    SOURCE_DIR = os.path.join(PROJECT_DIR, "Generic_bot", "UHBVN_new")

_MONTHS = ("January|February|March|April|May|June|July|August|September|"
           "October|November|December")
_PERIOD_RE = re.compile(rf"(?:{_MONTHS})\s+\d{{4}}", re.I)
_YEAR_RANGE_RE = re.compile(r"\b(20\d{2})\s*[-_to]+\s*(20\d{2})\b", re.I)


# --------------------------------------------------------------------------- #
# Normalisation helpers
# --------------------------------------------------------------------------- #
def _clean_header(cell: str | None) -> str:
    """Collapse the wrapped, multi-line header cells into one tidy label."""
    if not cell:
        return ""
    return re.sub(r"\s+", " ", str(cell).replace("\n", " ")).strip()


def parse_number(cell: str | None) -> tuple[float | None, str | None]:
    """Return (value, leading_text). Handles '3,003,464', '5.23', 'r 330656'.

    The connection table occasionally leaks a letter from the circle name into
    the first numeric cell ('Yamuna Naga' | 'r 330656'); we strip and return
    that stray text so the caller can repair the entity label.
    """
    if cell is None:
        return None, None
    s = str(cell).strip()
    if not s:
        return None, None
    m = re.match(r"^([^\d\-]*?)\s*(-?[\d,]+(?:\.\d+)?)\s*%?$", s)
    if not m:
        return None, None
    lead = m.group(1).strip() or None
    num = m.group(2).replace(",", "")
    try:
        return float(num), lead
    except ValueError:
        return None, lead


def _is_data_row(row: list, entity_cols: int) -> bool:
    """A data row has mostly numeric cells after the entity column(s)."""
    tail = row[entity_cols:]
    nums = sum(1 for c in tail if parse_number(c)[0] is not None)
    return tail and nums >= max(1, len(tail) // 2)


def _dataset_of(stem: str) -> str:
    """Derive a stable dataset key from the filename (e.g. '1_Connection')."""
    return re.sub(r"^\d+[_\-]?", "", stem).strip().lower().replace(" ", "_")


def _page_unit(page_text: str, dataset: str) -> str:
    """Default unit for plain numeric columns on this page."""
    t = page_text.lower()
    if "figure in kw" in t or dataset == "connected_load":
        return "KW"
    if "figure in mw" in t:
        return "MW"
    return "count"


def column_unit(metric: str, page_unit: str) -> str:
    """Per-column unit: a '% Damage rate' column is %, not the page default."""
    m = metric.lower()
    if "%" in metric or "rate" in m or "percent" in m or "efficiency" in m:
        return "%"
    return page_unit


def _period_of(page_text: str) -> str:
    m = _PERIOD_RE.search(page_text)
    if m:
        return m.group(0).title()
    m = _YEAR_RANGE_RE.search(page_text)
    if m:
        return f"{m.group(1)}-{m.group(2)}"
    return ""


def _title_of(page_text: str) -> str:
    """Pick the most title-like line (UHBVN reports use an all-caps caption)."""
    for line in page_text.splitlines():
        s = line.strip()
        if len(s) > 15 and sum(c.isupper() for c in s) >= len(s.replace(" ", "")) * 0.6:
            if "NIGAM" not in s:  # skip the company name banner
                return s
    return ""


# --------------------------------------------------------------------------- #
# Header reconstruction (handles merged / multi-row headers)
# --------------------------------------------------------------------------- #
def build_columns(rows: list[list], entity_cols: int) -> tuple[list[str], int]:
    """Return (column_names, first_data_row_index).

    Header band = the leading rows before the first real data row. Merged parent
    cells arrive as ``None``; we forward-fill them left-to-right, then join each
    column's header parts top-to-bottom so a split header like
    ['Transformers damaged', 'Total'] becomes 'Transformers damaged Total'.
    """
    first_data = next(
        (i for i, r in enumerate(rows) if _is_data_row(r, entity_cols)), 1
    )
    header_rows = rows[:first_data] or [rows[0]]
    width = max(len(r) for r in rows)

    filled: list[list[str]] = []
    for hr in header_rows:
        out, last = [], ""
        for j in range(width):
            val = _clean_header(hr[j] if j < len(hr) else "")
            if val:
                last = val
            out.append(val or last)  # forward-fill merged parent across blanks
        filled.append(out)

    columns = []
    for j in range(width):
        parts, seen = [], set()
        for hr in filled:
            p = hr[j]
            if p and p not in seen:
                parts.append(p)
                seen.add(p)
        columns.append(" ".join(parts) or f"col{j}")
    return columns, first_data


# --------------------------------------------------------------------------- #
# Ingestion
# --------------------------------------------------------------------------- #
def _entity_col_count(header_first: list) -> int:
    """How many leading columns are textual labels (Sr.No / Circle / Category)."""
    n = 0
    for cell in header_first:
        h = _clean_header(cell).lower()
        if any(k in h for k in ("sr.", "sr ", "s.no", "no.", "circle", "name",
                                "category", "zone", "district", "particular")):
            n += 1
        else:
            break
    return max(1, n)


def _extract_consumers(doc, pdf_path: Path) -> list[dict]:
    """Targeted parser for consumers.pdf (two side-by-side key/value series that
    PyMuPDF mis-aligns). Reads the ordered text: a date row is followed by its
    Consumer Base; an FY-range row is followed by New Consumers Added."""
    text = "\n".join(p.get_text() for p in doc)
    period = _period_of(text)
    facts, pending = [], None
    for tok in (t.strip() for t in text.splitlines() if t.strip()):
        if re.match(r"^\d{1,2}-[A-Za-z]{3}-\d{2}$", tok):
            pending = ("Consumer Base", tok)
        elif re.match(r"^\d{4}-\d{2}$", tok):
            pending = ("New Consumers Added", tok)
        elif pending and re.match(r"^[\d,]+$", tok):
            metric, ent = pending
            facts.append({
                "dataset": "consumers", "source": pdf_path.name,
                "title": "Year Wise Consumer Base and New Consumer Added (UHBVN)",
                "period": period, "unit": "count",
                "entity": ent, "metric": metric, "value": float(tok.replace(",", "")),
            })
            pending = None
    return facts


def extract_facts(pdf_path: Path) -> list[dict]:
    """Extract every (entity, metric) -> value fact from one report PDF."""
    import fitz  # PyMuPDF — ingest-only dependency, imported lazily

    doc = fitz.open(str(pdf_path))
    dataset = _dataset_of(pdf_path.stem)
    if dataset == "consumers":  # irregular side-by-side layout -> targeted parser
        facts = _extract_consumers(doc, pdf_path)
        doc.close()
        return facts
    facts: list[dict] = []

    for page in doc:
        page_text = page.get_text()
        period = _period_of(page_text)
        page_unit = _page_unit(page_text, dataset)
        title = _title_of(page_text)

        try:
            found = page.find_tables()
        except Exception:
            continue
        for table in found.tables:
            rows = table.extract()
            if not rows or len(rows) < 2:
                continue

            entity_cols = _entity_col_count(rows[0])
            columns, first_data = build_columns(rows, entity_cols)

            # Keep every label column except a pure serial-number column
            # ('Sr. No.'); a 'Category' (Rural/Urban) column is folded into the
            # entity so each row stays unambiguous, e.g. 'Kurukshetra Rural'.
            label_idxs = [
                i for i in range(entity_cols)
                if not re.search(r"\b(sr|s\.?no|no)\b", columns[i].lower())
            ] or [entity_cols - 1]

            # Per-label-column vertical fill (merged cells are blank below).
            last_label = {i: "" for i in label_idxs}
            for r in rows[first_data:]:
                # Repair a stray letter leaked from the entity into the 1st value.
                _, lead0 = parse_number(r[entity_cols]) if len(r) > entity_cols else (None, None)
                parts = []
                for i in label_idxs:
                    v = _clean_header(r[i]) if i < len(r) else ""
                    if i == label_idxs[0] and lead0 and v:
                        v = f"{v}{lead0}"
                    if v:
                        last_label[i] = v
                    if last_label[i]:
                        parts.append(last_label[i])
                entity = " ".join(parts)
                if not entity:
                    continue

                for j in range(entity_cols, min(len(r), len(columns))):
                    val, _ = parse_number(r[j])
                    if val is None:
                        continue
                    facts.append({
                        "dataset": dataset, "source": pdf_path.name, "title": title,
                        "period": period, "unit": column_unit(columns[j], page_unit),
                        "entity": entity, "metric": columns[j], "value": val,
                    })
    doc.close()
    return facts


def build(db_path: str | None = None, source_dir: str | None = None) -> int:
    """(Re)build the SQLite fact store from every PDF in the source folder."""
    db_path = db_path or DB_PATH
    source_dir = source_dir or SOURCE_DIR
    pdfs = sorted(Path(source_dir).glob("*.pdf"))
    if not pdfs:
        raise SystemExit(f"No PDFs found in {source_dir}")

    con = sqlite3.connect(db_path)
    con.execute("DROP TABLE IF EXISTS facts")
    con.execute("""
        CREATE TABLE facts(
            dataset TEXT, source TEXT, title TEXT, period TEXT, unit TEXT,
            entity TEXT, metric TEXT, value REAL,
            entity_l TEXT, metric_l TEXT
        )""")
    con.execute("CREATE INDEX idx_lookup ON facts(dataset, entity_l, metric_l)")

    total = 0
    for pdf in pdfs:
        try:
            facts = extract_facts(pdf)
        except Exception as exc:  # noqa: BLE001
            print(f"  ! {pdf.name}: {exc}")
            continue
        con.executemany(
            "INSERT INTO facts VALUES (?,?,?,?,?,?,?,?,?,?)",
            [(f["dataset"], f["source"], f["title"], f["period"], f["unit"],
              f["entity"], f["metric"], f["value"],
              f["entity"].lower(), f["metric"].lower()) for f in facts],
        )
        total += len(facts)
        print(f"  {pdf.name:38s} dataset={_dataset_of(pdf.stem):20s} facts={len(facts)}")

    _build_meta(con)
    con.commit()
    con.close()
    print(f"\n[tables] {total} facts written to {db_path}")
    return total


def _build_meta(con: sqlite3.Connection) -> None:
    """Quality-gate each dataset so only cleanly-extracted ones are answerable.

    A trustworthy report has *labelled* rows (district names), so most of its
    distinct entities are NON-numeric. Reports we mis-parse end up with numeric
    'entities' (e.g. '0.00', '10186.17'); those are quarantined (trusted=0) so
    the bot will never serve a wrong value from them — it says "Data not found"
    instead. Re-enable a dataset only after its extraction is validated.
    """
    con.execute("DROP TABLE IF EXISTS datasets")
    con.execute("""
        CREATE TABLE datasets(
            dataset TEXT PRIMARY KEY, n_facts INT, n_entities INT,
            pct_numeric_entity REAL, has_total INT, trusted INT, title TEXT
        )""")
    rows = con.execute("SELECT DISTINCT dataset FROM facts").fetchall()
    for (ds,) in rows:
        ents = [r[0] for r in con.execute(
            "SELECT DISTINCT entity FROM facts WHERE dataset=?", (ds,))]
        n_facts = con.execute(
            "SELECT COUNT(*) FROM facts WHERE dataset=?", (ds,)).fetchone()[0]
        numeric = sum(1 for e in ents if parse_number(e)[0] is not None)
        pct = numeric / len(ents) if ents else 1.0
        has_total = con.execute(
            "SELECT COUNT(*) FROM facts WHERE dataset=? AND metric_l='total'",
            (ds,)).fetchone()[0] > 0
        title = con.execute(
            "SELECT title FROM facts WHERE dataset=? AND title<>'' LIMIT 1",
            (ds,)).fetchone()
        # Column-quality: a column name longer than 80 chars means the whole
        # table got dumped into the header (e.g. ss_mva) -> the dataset is
        # mis-parsed and must not answer.
        cols = [r[0] for r in con.execute(
            "SELECT DISTINCT metric FROM facts WHERE dataset=?", (ds,))]
        bad_columns = any(len(c) > 80 for c in cols)
        # Trust = mostly-labelled rows AND a sane number of distinct entities
        # AND clean column labels.
        trusted = int(pct <= 0.34 and 2 <= len(ents) <= 60 and n_facts > 0
                      and not bad_columns)
        con.execute(
            "INSERT INTO datasets VALUES (?,?,?,?,?,?,?)",
            (ds, n_facts, len(ents), round(pct, 3), int(has_total), trusted,
             title[0] if title else ""))

    print("\n[tables] dataset trust report (trusted = safe to answer):")
    for ds, n, ne, pct, ht, tr in con.execute(
            "SELECT dataset,n_facts,n_entities,pct_numeric_entity,has_total,"
            "trusted FROM datasets ORDER BY trusted DESC, dataset"):
        flag = "TRUSTED " if tr else "quarant."
        print(f"    [{flag}] {ds:30s} facts={n:5d} entities={ne:4d} "
              f"num_ent={pct:.0%} total={'Y' if ht else '-'}")


# --------------------------------------------------------------------------- #
# Query layer: intent -> (dataset, column), entity filter, exact lookup
# --------------------------------------------------------------------------- #
# Intent extraction is now done by the LLM (see ``app.intent``) instead of the
# old hand-curated DATASET_CATALOG keyword map. The LLM is handed a catalog built
# live from SQLite (every trusted dataset + its exact columns + sample rows) and
# returns which dataset / metric / entity the question refers to. It NEVER returns
# a value — every number is still looked up deterministically below, so a wrong
# or hallucinated selection can only ever yield an existing cell or a "clarify" /
# "not found", never a fabricated figure.

# Below this the model's confidence in its dataset+metric mapping, we don't trust
# the routing and ask the user to clarify instead of guessing a column.
MIN_CONFIDENCE = 0.5

# Column names that denote a row/utility-wide aggregate. Used (a) as the safety-net
# "default" column for a bare quantity question when the model gives no usable
# metric, and (b) to collapse sibling sub-columns to their total.
_AGG_NAMES = {"total", "grand total", "total (r+u)", "overall"}

DATA_NOT_FOUND = "Data not found in the provided tables."
_MAX_FACTS = 24  # cap a single answer so a series query can't dump a huge list

# If the question is procedural/explanatory, it belongs to the prose RAG path,
# not the numeric fact store — even if it mentions 'domestic connection'.
_PROCEDURAL_RE = re.compile(
    r"\b(procedure|process|how to|how do|how can|how should|apply|applic|"
    r"eligib|documents?|required|needed|paperwork|proof|affidavit|form|"
    r"rule|regulation|clause|circular|explain|define|meaning|why|"
    r"deposit|acd|advance consumption|tariff|rate of|charges?)\b", re.I)

# Cues that the user wants a number/quantity (used only for diagnostics).
_NUMERIC_RE = re.compile(
    r"\b(how many|how much|number of|no\.? of|total|count|amount|figure|value|"
    r"load|losses?|efficiency|rate|percent|connections?|transformers?|consumers?|"
    r"substations?|feeders?|length|ratio|mva|recovery|collection|billed)\b", re.I)

# Default utility-wide entity to use when the user names no district.
_DEFAULT_ENTITIES = ("grand total", "total (r+u) uhbvn", "uhbvn", "total")

# Words that carry no disambiguating signal in a column name.
_COL_STOP = {"in", "the", "of", "to", "at", "end", "month", "as", "on", "name",
             "circle", "sr", "no", "figure", "lus", "lakh", "nos", "fy", "year",
             "and", "for", "total"}


def _connect(db_path: str | None = None) -> sqlite3.Connection:
    return sqlite3.connect(db_path or DB_PATH)


def _norm(s: str) -> str:
    return re.sub(r"\s+", "", s.lower())


# Canonicalise district spelling variants so a question and the table row match
# regardless of which spelling each uses (the connection report says 'Sonipat',
# the transformer report says 'Sonepat'; 'Yamuna Nagar' vs 'Yamunanagar').
_SPELLING = [("sonepat", "sonipat")]


def _canon(s: str) -> str:
    s = _norm(s)
    for variant, canonical in _SPELLING:
        s = s.replace(variant, canonical)
    return s


def numeric_intent(query: str) -> bool:
    return bool(_NUMERIC_RE.search(query)) and not _PROCEDURAL_RE.search(query)


def trusted_datasets(con: sqlite3.Connection) -> set[str]:
    try:
        return {r[0] for r in con.execute(
            "SELECT dataset FROM datasets WHERE trusted=1")}
    except sqlite3.OperationalError:
        return set()  # meta table absent (old DB) -> nothing trusted


def columns_of(con: sqlite3.Connection, dataset: str) -> list[str]:
    return [r[0] for r in con.execute(
        "SELECT DISTINCT metric FROM facts WHERE dataset=?", (dataset,))]


def _col_tokens(name: str) -> list[str]:
    # Keep 2-char tokens: "LT"/"HT" are the ONLY thing distinguishing "LT Industry"
    # from "HT Industry" (and "LT NDS" from "HT NDS"). Noise 2-letter words are in
    # _COL_STOP. 1-char fragments ("T/Wells" -> "t") are still dropped.
    return [t for t in re.findall(r"[a-z0-9&]+", name.lower())
            if len(t) >= 2 and t not in _COL_STOP]


def _similar(a: str, b: str) -> float:
    return SequenceMatcher(None, a, b).ratio()


def _fuzzy_member(word: str, vocab: set[str], cutoff: float = 0.85) -> bool:
    """True if ``word`` is in vocab or a near-spelling of a vocab word.

    Tolerates typos like 'domastic' -> 'domestic'. Only words of length >= 5 are
    fuzzy-matched, to avoid short-word collisions.
    """
    if word in vocab:
        return True
    if len(word) < 5:
        return False
    return any(abs(len(v) - len(word)) <= 2 and _similar(word, v) >= cutoff
               for v in vocab)


def _token_match(token: str, qtok: set[str]) -> bool:
    """A column token matches a query token, allowing a 1-char typo."""
    return _fuzzy_member(token, qtok)


def explicit_columns(cols: list[str], query: str) -> list[str]:
    """Columns the user named explicitly (any informative token appears),
    tolerant of misspellings (e.g. 'domastic' matches the 'Domestic' column)."""
    qtok = set(re.findall(r"[a-z0-9&]+", query.lower()))
    return [c for c in cols
            if (ct := _col_tokens(c)) and any(_token_match(t, qtok) for t in ct)]


def _top_scoring(cols: list[str], query: str) -> list[str]:
    """Keep only the columns matching the MOST query tokens.

    'out of warranty' should land on 'Transformers damaged Out of warranty
    period' (3 tokens) and not also on '% Damage rate ... warranty period'
    (1 shared token) — the shared word 'warranty' must not drag in weaker
    matches when a more specific column exists.
    """
    qtok = set(re.findall(r"[a-z0-9&]+", query.lower()))

    def score(c: str) -> tuple[int, int]:
        ct = _col_tokens(c)
        exact = sum(1 for t in ct if t in qtok)
        fuzzy = sum(1 for t in ct if t not in qtok and _token_match(t, qtok))
        unmatched = len(ct) - exact - fuzzy  # extra words the query did NOT say
        # Primary: an exact hit always outranks a typo match. Tiebreak: prefer the
        # column whose OWN tokens are more fully covered, so a bare "Domestic"
        # picks the "Domestic" column, not "Bulk Supply Domestic" (both match the
        # single query token, but the latter carries two words the user never said).
        return (2 * exact + fuzzy, -unmatched)

    scored = [(score(c), c) for c in cols]
    best = max((s for s, _ in scored), default=(0, 0))
    return [c for s, c in scored if s == best and s[0] > 0]


def _prune_to_default(chosen: list[str], default: str | None, query: str) -> list[str]:
    """Collapse sibling sub-columns to the aggregate unless the user asked for them.

    'transformer damaged' matches the parent token 'damaged', which also appears
    in 'Out of warranty period' / 'With in warranty period'. If the aggregate
    ('Transformers damaged Total') is among the matches, keep it and drop a
    sibling only when the query contains one of that sibling's *distinguishing*
    tokens (e.g. 'warranty'). So a bare question returns the Total; an explicit
    'out of warranty' question still returns that breakdown.
    """
    if not default:
        return chosen
    deflt = [c for c in chosen if c.lower() == default.lower()]
    if not deflt:
        return chosen  # aggregate wasn't matched -> leave the explicit picks alone
    base = set(_col_tokens(default))
    qtok = set(re.findall(r"[a-z0-9&]+", query.lower()))
    kept = list(deflt)
    for c in chosen:
        if c.lower() == default.lower():
            continue
        if (set(_col_tokens(c)) - base) & qtok:  # a distinguishing token was asked for
            kept.append(c)
    return kept


_UTILITY_SYNS = {"uhbvn", "haryana", "uttarharyana", "overall", "total",
                 "grandtotal", "nigam", "discom", "state", "whole", "entire"}
_MONTHS = {"january", "february", "march", "april", "may", "june", "july",
           "august", "september", "october", "november", "december"}
# Place is introduced by one of these; lets us spot an unknown named location.
_LOC_RE = re.compile(r"\b(?:in|at|for|across|of|on)\s+(?:the\s+)?([A-Za-z][\w .&-]*)", re.I)
# Time/grammar words that may trail a place phrase ("in Mumbai AS OF MARCH 2026").
# A place phrase is deemed unknown when EVERY remaining (non-time) word is
# unrecognised; stripping these first stops a trailing month/date from rescuing an
# unknown city, WITHOUT dropping domain words (e.g. "connection") that legitimately
# keep a phrase like "on connection type" from looking like an unknown place.
_LOC_FILLER = _MONTHS | {
    "as", "of", "the", "end", "month", "months", "year", "years", "fy", "in",
    "at", "for", "on", "to", "and", "period", "periods", "financial", "quarter",
    "quarterly", "annual", "annually", "date", "dated", "till", "upto", "until",
    "ending",
}


def _entity_tokens(entity: str) -> set[str]:
    """Distinctive tokens to match an entity: the whole canon form, year/date
    codes (2015-16, 31-Mar-15, 2017), and words of length >= 4 (district names,
    'connection', 'feedback'). Short filler words are ignored."""
    toks = {_canon(entity)}
    toks.update(re.findall(
        r"\d{4}-\d{2}|\d{1,2}-[a-z]{3}-\d{2}|[a-z]{4,}|\d{4}", entity.lower()))
    return {t for t in toks if t and t not in {"total", "grand", "grandtotal"}}


def find_entity(con: sqlite3.Connection, dataset: str, query: str) -> list[str]:
    """Row(s) the query targets: a named district / year / particular, else the
    utility-wide total row, else (for a small series with no total) every row.

    If the user names a place we DON'T have (e.g. 'on the Moon'), return nothing
    so the caller reports 'Data not found' — never silently substitute another row.
    """
    rows = [r[0] for r in con.execute(
        "SELECT DISTINCT entity FROM facts WHERE dataset=?", (dataset,))]
    qn = _canon(query)
    ql = query.lower()

    named = [e for e in rows
             if any(t in qn or t in ql for t in _entity_tokens(e))]
    if named:
        return sorted(set(named), key=len)

    # No row named explicitly. Did the user name an UNKNOWN place? If a location
    # phrase holds a word that isn't a district, utility synonym, month, or part
    # of this table's vocabulary, refuse rather than guess. We drop time/grammar
    # fillers first so a trailing period ("... as of March 2026") can't rescue an
    # unknown city — ANY remaining unrecognised content word means refuse.
    vocab = ({t for e in rows for t in _entity_tokens(e)} | _UTILITY_SYNS | _MONTHS
             | _global_vocab(con))
    for m in _LOC_RE.finditer(query):
        words = [w for w in re.findall(r"[a-z]+", m.group(1).lower())
                 if w not in _LOC_FILLER]
        if words and all(not _fuzzy_member(w, vocab) for w in words):
            return []  # unknown place named -> no fallback

    for default in _DEFAULT_ENTITIES:
        match = [e for e in rows if e.lower() == default]
        if match:
            return match

    # Small series with no utility-total row (e.g. year-wise tables): the user
    # asked for the metric across all periods -> return the whole series.
    if 2 <= len(rows) <= 20:
        return sorted(rows)
    return []


def _lookup_cells(con, dataset, metric, entity) -> list[dict]:
    return [
        {"dataset": dataset, "entity": r[0], "metric": r[1], "value": r[2],
         "unit": r[3], "period": r[4], "source": r[5]}
        for r in con.execute(
            "SELECT entity, metric, value, unit, period, source FROM facts "
            "WHERE dataset=? AND entity_l=? AND metric_l=?",
            (dataset, entity.lower(), metric.lower()))
    ]


def _fmt_value(v: float, unit: str) -> str:
    num = f"{int(v):,}" if float(v).is_integer() else f"{v:,.2f}"
    if unit in ("count", "") or unit is None:
        return num
    if unit == "%":
        return f"{num}%"
    return f"{num} {unit}"


def _dedupe_facts(facts: list[dict]) -> list[dict]:
    """Collapse duplicate cells the PDF parse produced under the SAME row + column
    + unit (e.g. the connection report's two 'ECS' columns — one populated, one
    empty). A (row, column) pair is unique in a real table, so identical labels are
    an artifact: keep the largest-magnitude value, preserving first-seen order."""
    best: dict[tuple, dict] = {}
    order: list[tuple] = []
    for f in facts:
        key = (f["entity"].lower(), f["metric"].lower(), f.get("unit"))
        cur = best.get(key)
        if cur is None:
            best[key] = f
            order.append(key)
        elif abs(f.get("value") or 0) > abs(cur.get("value") or 0):
            best[key] = f
    return [best[k] for k in order]


def _format_facts(facts: list[dict]) -> str:
    return "\n\n".join(
        f"{f['entity']} — {f['metric']}: {_fmt_value(f['value'], f['unit'])}"
        + (f" (as of {f['period']})" if f["period"] else "")
        + f"\n(Source: {f['source']}, Row: {f['entity']}, Column: {f['metric']})"
        for f in facts
    )


# --------------------------------------------------------------------------- #
# Schema for the LLM, and deterministic resolution of its selection
# --------------------------------------------------------------------------- #
def _global_vocab(con: sqlite3.Connection) -> set[str]:
    """Tokens from every trusted dataset's key + column names.

    Used by ``find_entity`` to recognise that a word following 'in'/'for' is a
    real domain term (e.g. 'load', 'connected') and not an unknown place. This
    replaces the vocabulary the old DATASET_CATALOG keywords used to supply.
    """
    vocab: set[str] = set()
    for ds in trusted_datasets(con):
        vocab.update(t for t in re.findall(r"[a-z]+", ds) if len(t) >= 3)
        vocab.update(t for c in columns_of(con, ds) for t in _col_tokens(c))
    return vocab


def build_schema(con: sqlite3.Connection,
                 datasets: set[str] | None = None) -> dict:
    """Catalog handed to the LLM: ``{dataset: {title, metrics, entities}}``.

    Only trusted datasets are included, so the model can never route to a
    quarantined (mis-parsed) table. Built fresh from SQLite — there is no curated
    keyword list to keep in sync.
    """
    trusted = datasets if datasets is not None else trusted_datasets(con)
    schema: dict[str, dict] = {}
    for ds in sorted(trusted):
        title_row = con.execute(
            "SELECT title FROM facts WHERE dataset=? AND title<>'' LIMIT 1",
            (ds,)).fetchone()
        schema[ds] = {
            "title": title_row[0] if title_row else ds.replace("_", " "),
            "metrics": sorted(columns_of(con, ds)),
            "entities": sorted(
                r[0] for r in con.execute(
                    "SELECT DISTINCT entity FROM facts WHERE dataset=?", (ds,))),
        }
    return schema


# A category (Domestic, ECS, Lift irrigation, …) exists in BOTH the connection-
# COUNT report and the connected-LOAD report. These words mean the user wants the
# LOAD (kW) figure; absence of them defaults to the connection COUNT.
_LOAD_WORD_RE = re.compile(
    r"\b(?:load|loads|kw|kva|kilowatt|mw|sanctioned)\b|\bconnected\s+load\b", re.I)


def _resolves_specifically(cols: list[str], hint: str | None, query: str) -> bool:
    """True only if the metric maps to a SPECIFIC column in ``cols`` (an exact hint
    or an explicit column named in the query) — NOT the aggregate fallback. Used so
    count/load routing never switches to a dataset that lacks the asked-for column
    (e.g. "Electric Crematorium" exists only in connected_load)."""
    if hint and any(c.lower() == hint.strip().lower() for c in cols):
        return True
    return bool(_top_scoring(explicit_columns(cols, query), query))


def snap_metric(cols: list[str], hint: str | None, query: str) -> list[str]:
    """Resolve the LLM's metric hint to REAL column name(s) in ``cols``.

    The LLM is told to copy a column verbatim; we still verify it. Order:
      1. exact (case-insensitive) match — the normal path;
      2. token match against the hint, then against the raw query (tolerates a
         paraphrase or typo, reusing the same fuzzy machinery as before);
      3. an aggregate column ("Total") as the safety net for a bare quantity
         question when the model gives no usable metric.
    Sibling sub-columns are collapsed to their aggregate unless the user asked
    for a distinguishing breakdown. Returns [] when nothing real matches, so the
    caller asks the user to name the metric instead of guessing.
    """
    if hint:
        exact = [c for c in cols if c.lower() == hint.strip().lower()]
        if exact:
            return exact

    src = hint or query
    chosen = _top_scoring(explicit_columns(cols, src), src)
    if not chosen and hint:  # hint was non-verbatim -> fall back to the question
        chosen = _top_scoring(explicit_columns(cols, query), query)
    if not chosen:
        return [c for c in cols if c.lower() in _AGG_NAMES]

    agg = next((c for c in chosen if c.lower().endswith("total")), None)
    if agg:
        chosen = _prune_to_default(chosen, agg, src)
    return chosen


def resolve_entity(con: sqlite3.Connection, dataset: str,
                   hint: str | None, query: str) -> list[str]:
    """Resolve the LLM's entity hint to real row(s), correctness first.

    If the hint names a row we hold (any spelling), use it. Otherwise defer to
    the deterministic ``find_entity`` over the raw question, which supplies the
    utility-wide default / whole-series behaviour AND refuses to substitute a row
    when the user named a place we don't have (e.g. 'on the Moon').
    """
    if hint:
        rows = [r[0] for r in con.execute(
            "SELECT DISTINCT entity FROM facts WHERE dataset=?", (dataset,))]
        htoks = _entity_tokens(hint)
        # Rank by how many hint tokens each row shares, and keep only the best.
        # A specific hint ("Kurukshetra Rural") shares 2 tokens with its own row
        # but only 1 ("rural") with "Total Rural" / "Ambala Rural", so it wins
        # uniquely; a bare "Kurukshetra" ties Rural+Urban (1 each) and returns
        # both — no district/zone is special-cased.
        scored = [(len(_entity_tokens(e) & htoks), e) for e in rows]
        best = max((s for s, _ in scored), default=0)
        if best > 0:
            named = [e for s, e in scored if s == best]
            return sorted(set(named), key=len)
    return find_entity(con, dataset, query)


def _metric_options(cols: list[str]) -> str:
    opts = sorted({c for c in cols if c.lower() not in _AGG_NAMES})[:12]
    return ", ".join(opts)


# --------------------------------------------------------------------------- #
# Query coverage validation: the resolved rows must satisfy the dimensions the
# user actually pinned (entity, period). Otherwise the model can pick a dataset
# that *sounds* right ("consumer count" -> the year-wise consumers table) and we
# return rows that answer neither the requested district nor the requested month.
# When a pinned dimension isn't covered, we clarify instead of serving unrelated
# rows. Generic — driven by the tokens the user gave, no entity is special-cased.
# --------------------------------------------------------------------------- #
def _is_specific_entity(hint: str | None) -> bool:
    """True if the hint names a concrete row (a district/year/date), not a
    utility-wide / default request."""
    if not hint:
        return False
    h = _canon(hint)
    if h in {_canon(s) for s in _UTILITY_SYNS} or h in {_canon(d) for d in _DEFAULT_ENTITIES}:
        return False
    return bool(_entity_tokens(hint))


def _entity_covered(hint: str | None, resolved: list[str]) -> bool:
    """Did resolution land on rows that actually match a specifically-named entity?"""
    if not _is_specific_entity(hint):
        return True
    htoks = _entity_tokens(hint)
    return any(_entity_tokens(e) & htoks for e in resolved)


# A concrete period the user might pin: 2015, 2015-16, FY 2013-14, March 2026,
# 31-Mar-15. (A vague window like "April-23 to September-23" is not enforced.)
_CONCRETE_PERIOD_RE = re.compile(
    r"\b(?:fy\s*)?20\d{2}(?:\s*-\s*\d{2,4})?\b|\b\d{1,2}-[a-z]{3}-\d{2}\b|"
    r"\b(?:jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)[a-z]*\.?\s*20\d{2}\b", re.I)


def _period_covered(req_period: str | None, facts: list[dict],
                    resolved: list[str]) -> bool:
    """If the user pinned a concrete period, do the resolved rows carry it?

    A period lives either in the fact's ``period`` field (e.g. connection
    "March 2026") or, in year-wise tables, is encoded as the entity ("2015-16").
    """
    if not req_period or not _CONCRETE_PERIOD_RE.search(req_period):
        return True
    rp = _norm(req_period)

    def hit(s: str | None) -> bool:
        s = _norm(s or "")
        return bool(s) and (rp in s or s in rp)

    return any(hit(f["period"]) for f in facts) or any(hit(e) for e in resolved)


def _coverage_clarify(dataset: str, hint: str | None, period: str | None,
                      resolved: list[str]) -> str:
    """Explain the dimension mismatch and show what the dataset DOES cover."""
    dims = []
    if _is_specific_entity(hint):
        dims.append(str(hint))
    if period:
        dims.append(str(period))
    want = " in ".join(dims) if dims else "that"
    covers = ", ".join(sorted(set(resolved))[:6])
    tail = f" (I have e.g. {covers})" if covers else ""
    return (f"I found {dataset.replace('_', ' ')} data{tail}, but not for {want}. "
            f"Could you rephrase, or pick one of those?")


# --------------------------------------------------------------------------- #
# Superlative / argmax across all rows: "which circle has the MOST damaged
# transformers?" — rank every district for a metric and return the top/bottom.
# --------------------------------------------------------------------------- #
_SUPERLATIVE_MIN = ("minimum", "lowest", "least", "smallest", "fewest", "min")
_SUPERLATIVE_MAX = ("maximum", "highest", "most", "greatest", "largest", "biggest",
                    "top", "max")
_SUPERLATIVE_RE = re.compile(
    r"\b(?:which|what|who|where)\b.*\b(?:" + "|".join(_SUPERLATIVE_MIN + _SUPERLATIVE_MAX) + r")\b",
    re.I)


def _is_aggregate_entity(entity: str) -> bool:
    """A utility-wide / zone-level subtotal row — excluded from a per-row ranking
    so "which circle/district has the most" returns a real circle, not the total."""
    e = entity.strip().lower()
    return (e in _DEFAULT_ENTITIES or e in _UTILITY_SYNS or "grand total" in e
            or e.startswith("total ") or e.startswith("total(") or e.startswith("zone"))


def _superlative_answer(con, schema: dict, sel: dict, query: str) -> dict | None:
    """Rank all non-aggregate rows for the selected dataset+metric and return the
    max (or min) — deterministically from SQLite, never via the LLM."""
    ds = sel.get("dataset")
    if ds not in schema:
        return None
    metrics = schema[ds]["metrics"]
    # If the question names a specific category ("maximum DOMESTIC consumers"),
    # rank by THAT column — not the aggregate the router may have defaulted to.
    explicit = _top_scoring(
        [c for c in explicit_columns(metrics, query) if c.lower() not in _AGG_NAMES],
        query)
    if explicit:
        metric = explicit[0]
    else:
        chosen = snap_metric(metrics, sel.get("metric"), query)
        if not chosen:
            return None
        metric = chosen[0]
    rows = [r for r in con.execute(
        "SELECT entity, value, unit, period, source FROM facts "
        "WHERE dataset=? AND metric_l=?", (ds, metric.lower()))
        if r[1] is not None and not _is_aggregate_entity(r[0])]
    if len(rows) < 2:
        return None
    want_min = any(w in query.lower() for w in _SUPERLATIVE_MIN)
    r = min(rows, key=lambda x: x[1]) if want_min else max(rows, key=lambda x: x[1])
    fact = {"dataset": ds, "entity": r[0], "metric": metric, "value": r[1],
            "unit": r[2], "period": r[3], "source": r[4]}
    sup = "lowest" if want_min else "highest"
    text = (f"{r[0]} has the {sup} {metric} ({_fmt_value(r[1], r[2])})"
            + (f" (as of {r[3]})" if r[3] else "")
            + f"\n(Source: {r[4]}, Row: {r[0]}, Column: {metric})")
    return {"status": "answer", "facts": [fact], "text": text}


# --------------------------------------------------------------------------- #
# Segregation / breakup: "segregation on connection type", "category-wise",
# "breakup", "split", "bifurcation" — the user wants EVERY category column of a
# dataset, NOT the aggregate Total (which a bare quantity would return). We list
# all non-aggregate columns for the resolved entity, deterministically.
# --------------------------------------------------------------------------- #
_SEGREGATION_RE = re.compile(
    r"\b(?:segregat\w*|break[\s-]?up|break[\s-]?down|categor(?:y|ies)"
    r"[\s-]?wise|category\s+wise|connection\s+type|type[\s-]?wise|split|"
    r"bifurcat\w*|by\s+(?:category|type))\b", re.I)


_ROWWISE_RE = re.compile(
    r"\b(?:circle|district|zone|region|division|sub[\s-]?division|location|area)"
    r"[\s-]?wise\b"
    r"|\b(?:each|every|all|per)\s+(?:circle|district|zone|region|division)s?\b"
    r"|\bby\s+(?:circle|district|zone|region|division)\b"
    r"|\bacross\s+(?:all\s+)?(?:circle|district|zone|region|division)s?\b"
    r"|\bfor\s+(?:each|all|every)\s+(?:circle|district|zone|region)s?\b", re.I)


def _rowwise_answer(con, schema: dict, sel: dict, query: str) -> dict | None:
    """List a metric for EVERY circle/district row (or every zone, when the user
    said "zone wise") — deterministically from SQLite. Used for "circle wise /
    district wise / each circle" requests so we return the full breakdown instead
    of collapsing to the single Grand Total row that a null entity defaults to."""
    ds = sel.get("dataset")
    if ds not in schema:
        return None
    chosen = snap_metric(schema[ds]["metrics"], sel.get("metric"), query)
    if not chosen:
        return None
    metric = chosen[0]
    all_rows = [r for r in con.execute(
        "SELECT entity, value, unit, period, source FROM facts "
        "WHERE dataset=? AND metric_l=?", (ds, metric.lower())) if r[1] is not None]
    # "zone wise" -> the zone subtotal rows; otherwise the individual circles
    # (drop grand total AND zones so a circle-wise list isn't polluted by totals).
    if re.search(r"\bzones?[\s-]?wise\b|\b(?:each|every|all|per|by)\s+zones?\b",
                 query, re.I):
        rows = [r for r in all_rows if r[0].strip().lower().startswith("zone")]
    else:
        rows = [r for r in all_rows if not _is_aggregate_entity(r[0])]
    if len(rows) < 2:
        return None
    rows.sort(key=lambda r: -(r[1] or 0))  # largest first
    facts = _dedupe_facts([
        {"dataset": ds, "entity": r[0], "metric": metric, "value": r[1],
         "unit": r[2], "period": r[3], "source": r[4]} for r in rows])
    truncated = len(facts) > _MAX_FACTS
    text = _format_facts(facts[:_MAX_FACTS])
    if truncated:
        text += (f"\n\n…({len(facts) - _MAX_FACTS} more — narrow by circle/zone "
                 f"to see the rest.)")
    return {"status": "answer", "facts": facts, "text": text}


def _segregation_answer(con, schema: dict, sel: dict, query: str) -> dict | None:
    """List every category column (all metrics except the aggregate Total) for the
    selected dataset+entity — deterministically from SQLite. Used for
    "segregation/breakup/category-wise" requests so the reply is the full split,
    not the Total the previous turn's metric would otherwise inherit."""
    ds = sel.get("dataset")
    if ds not in schema:
        return None
    entities = resolve_entity(con, ds, sel.get("entity"), query)
    if not entities:
        return None
    # Every real category column, dropping the aggregate(s) the user is splitting.
    cols = [c for c in schema[ds]["metrics"] if c.lower() not in _AGG_NAMES]
    facts = [f for c in cols for e in entities for f in _lookup_cells(con, ds, c, e)]
    facts = _dedupe_facts(facts)  # collapse duplicate parse-artifact columns
    if len(facts) < 2:  # nothing to break up -> let normal handling answer
        return None
    facts.sort(key=lambda f: (f["value"] is None, -(f["value"] or 0)))  # biggest first
    truncated = len(facts) > _MAX_FACTS
    text = _format_facts(facts[:_MAX_FACTS])
    if truncated:
        text += (f"\n\n…({len(facts) - _MAX_FACTS} more categories — narrow by "
                 f"category to see the rest.)")
    return {"status": "answer", "facts": facts, "text": text}


def respond(query: str, db_path: str | None = None, *,
            extractor: "intent.Extractor | None" = None) -> dict:
    """Route a query against the trusted fact store via LLM intent extraction.

    The LLM only *selects* a dataset/metric/entity (see ``app.intent``); every
    value below is read from SQLite, so numbers are always exact and never pass
    through the model. ``extractor`` is injectable for offline testing.

    Returns a dict with ``status`` in:
      answer    -> exact, column-grounded value(s); ``text`` is the reply.
      clarify   -> hit a table but need the metric/circle, or low confidence.
      not_found -> hit a table but that exact cell is absent (never guess).
      prose     -> not a trusted-table question; caller uses vector RAG instead.
    """
    # A transformer "failure rate" IS the damage rate — normalise so it routes to
    # the "% Damage rate" column deterministically (the router otherwise waffles
    # between that, the DT count, and could-not-find). "damage rate" already works.
    query = re.sub(r"\bfailure\s+rate\b", "damage rate", query, flags=re.I)
    path = db_path or DB_PATH
    # Fast, safe pre-filter: an obviously procedural/explanatory question belongs
    # to the prose RAG path and needn't cost an LLM call here.
    if not os.path.exists(path) or _PROCEDURAL_RE.search(query):
        return {"status": "prose"}

    con = _connect(path)
    try:
        schema = build_schema(con)
        if not schema:
            return {"status": "prose"}

        fresh = extractor is None  # a real LLM route (not a slot-forced intent)
        # Deterministic route for a transformer DAMAGE/FAILURE RATE query: force the
        # "% Damage rate" column of damaged_transformers instead of letting the LLM
        # waffle (it otherwise picks the DT count, clarifies, or says could-not-find
        # nondeterministically). "failure rate" was normalised to "damage rate" above.
        if (re.search(r"\b(?:transformer|dt|dtr)\b", query, re.I)
                and re.search(r"\bdamage rate\b", query, re.I)
                and "damaged_transformers" in schema):
            metric = ("% Damage rate including warranty period Total"
                      if re.search(r"\binclud", query, re.I)
                      else "% Damage rate excluding warranty period Total")
            parsed = {"status": "answer", "confidence": 1.0, "selections": [
                {"dataset": "damaged_transformers", "metric": metric,
                 "entity": None, "period": None}]}
        else:
            if extractor is None:
                from . import intent  # lazy: keeps OpenAI an answer-time dependency
                extractor = intent.default_extractor
            try:
                parsed = extractor(query, schema)
            except Exception as exc:  # noqa: BLE001 — never crash the chat turn
                print(f"[tables] intent extraction failed: {exc}")
                return {"status": "prose"}  # safe: vector RAG can't invent figures

        status = parsed.get("status", "clarify")
        if status == "prose":
            return {"status": "prose"}

        selections = parsed.get("selections") or []
        confidence = float(parsed.get("confidence", 0.0) or 0.0)
        if status == "clarify" or confidence < MIN_CONFIDENCE or not selections:
            reason = parsed.get("clarify_reason") or (
                "Could you specify the dataset, metric and district/period you need?")
            return {"status": "clarify", "text": reason}

        # Superlative ("which circle has the most X?") -> rank all rows and return
        # the top/bottom deterministically, rather than listing every row.
        if _SUPERLATIVE_RE.search(query):
            sup = _superlative_answer(con, schema, selections[0], query)
            if sup:
                return sup
            # else fall through to normal handling

        # Row-wise ("circle wise", "district wise", "each circle", "zone wise")
        # -> list the metric for every circle/zone row, not just the Grand Total.
        if _ROWWISE_RE.search(query):
            rw = _rowwise_answer(con, schema, selections[0], query)
            if rw:
                return rw
            # else fall through to normal handling

        # Segregation ("segregation on connection type", "breakup", "category-wise")
        # -> list every category column, not the inherited Total.
        if _SEGREGATION_RE.search(query):
            seg = _segregation_answer(con, schema, selections[0], query)
            if seg:
                return seg
            # else fall through to normal handling

        collected: list[dict] = []
        clarify: str | None = None
        for sel in selections:
            ds = sel.get("dataset")
            if ds not in schema:  # model named a table we don't trust/have
                continue
            # Deterministic count-vs-load routing for the connection/connected_load
            # pair (a category lives in both). Route by an explicit load word,
            # defaulting to the CONNECTION count when none is present — so "lift
            # irrigation in Ambala" is a count and "…load" is kW. Fresh single-
            # selection queries only, so slot chains and compound queries (whose
            # parts each carry their own metric) are left untouched.
            if (fresh and len(selections) == 1
                    and ds in ("connection", "connected_load")):
                want = "connected_load" if _LOAD_WORD_RE.search(query) else "connection"
                if (want != ds and want in schema
                        and _resolves_specifically(schema[want]["metrics"],
                                                   sel.get("metric"), query)):
                    ds = want
            cols = schema[ds]["metrics"]
            chosen = snap_metric(cols, sel.get("metric"), query)
            if not chosen:
                clarify = clarify or (
                    f"I have {ds.replace('_', ' ')} data, but please name the "
                    f"metric. Available: {_metric_options(cols)}.")
                continue
            # Single-selection override: a defaulted AGGREGATE yields to a specific
            # category the user explicitly named ("other count for Zone-II" -> the
            # "Other" column, not "Total"). Skipped for compound queries so a
            # category meant for one part ("domestic connections and total load")
            # can't leak into another part's metric.
            if len(selections) == 1 and chosen[0].lower() in _AGG_NAMES:
                spec = _top_scoring(
                    [c for c in explicit_columns(cols, query)
                     if c.lower() not in _AGG_NAMES], query)
                if spec:
                    chosen = spec
            entities = resolve_entity(con, ds, sel.get("entity"), query)
            if not entities:
                clarify = clarify or (
                    f"I have {ds.replace('_', ' ')} data, but please name the "
                    f"circle or year/period you want.")
                continue
            # Coverage: the resolved rows must satisfy the entity/period the user
            # pinned — otherwise clarify instead of serving unrelated rows.
            req_entity, req_period = sel.get("entity"), sel.get("period")
            if not _entity_covered(req_entity, entities):
                clarify = clarify or _coverage_clarify(ds, req_entity, req_period, entities)
                continue
            ds_facts = [f for c in chosen for e in entities
                        for f in _lookup_cells(con, ds, c, e)]
            if not _period_covered(req_period, ds_facts, entities):
                clarify = clarify or _coverage_clarify(ds, req_entity, req_period, entities)
                continue
            collected += ds_facts

        collected = _dedupe_facts(collected)
        if collected:
            truncated = len(collected) > _MAX_FACTS
            text = _format_facts(collected[:_MAX_FACTS])
            if truncated:
                text += (f"\n\n…({len(collected) - _MAX_FACTS} more rows — narrow "
                         f"by circle, year, or metric to see the rest.)")
            return {"status": "answer", "facts": collected, "text": text}
        if clarify:
            return {"status": "clarify", "text": clarify}
        return {"status": "not_found", "text": DATA_NOT_FOUND}
    finally:
        con.close()


def format_answer(query: str, db_path: str | None = None) -> str:
    """Convenience wrapper for CLI/eval: the reply text for any structured query."""
    r = respond(query, db_path)
    return r.get("text", DATA_NOT_FOUND)


if __name__ == "__main__":
    build()
