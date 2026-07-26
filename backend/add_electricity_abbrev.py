"""Ingest Electricity_Department_Abbreviations.txt into the prose knowledge base —
incremental & idempotent.

This glossary is a simple "ABBR - description" line format (one entry per line,
with a few wrapped continuation lines). Each entry becomes ONE chunk, so
"what is DT failure rate", "full form of SAIFI", "what is POSOCO" retrieve it.

APPENDS to `knowledge_db.pkl` WITHOUT re-embedding the existing corpus; safe to
re-run (prior entries from this source are removed first, pkl backed up to .bak).
Run on EACH machine (dev/prod pkls differ). Restart the service afterwards.

    python add_electricity_abbrev.py   # from backend/, venv active, OPENAI_API_KEY set
"""

from __future__ import annotations

import os
import pickle
import re
import shutil
import sys

from app import config, rag

SRC = os.getenv(
    "ELEC_ABBREV_TXT",
    os.path.join(config.BACKEND_DIR, "Electricity_Department_Abbreviations.txt"))
SOURCE_NAME = "Electricity_Department_Abbreviations.txt"
_BATCH = 100

# "UHBVN - Uttar Haryana...", "S/S - Sub-Station", "DT Failure Rate - ...".
_ENTRY = re.compile(r"^(?P<abbr>\S.{0,23}?)\s*-\s+(?P<desc>\S.*)$")
_SKIP = re.compile(r"^={3,}$|^-{3,}$|^\d+\.\s|^ELECTRICITY DEPARTMENT|^\(Focus|^Note:", re.I)


def _read(path: str) -> str:
    for enc in ("utf-8-sig", "cp1252"):
        try:
            with open(path, "r", encoding=enc) as f:
                return f.read()
        except UnicodeDecodeError:
            continue
    with open(path, "r", encoding="utf-8", errors="replace") as f:
        return f.read()


def _chunks(text: str) -> list[str]:
    entries: list[dict] = []
    cur: dict | None = None
    for raw in text.splitlines():
        if not raw.strip():
            cur = None
            continue
        if raw[0].isspace():                    # wrapped continuation line
            if cur is not None:
                cur["desc"] += " " + raw.strip()
            continue
        if _SKIP.match(raw.strip()):            # title / section / separator / note
            cur = None
            continue
        m = _ENTRY.match(raw)
        if m:
            cur = {"abbr": m.group("abbr").strip(),
                   "desc": re.sub(r"\s+", " ", m.group("desc").strip())}
            entries.append(cur)
        else:
            cur = None
    return [f"{e['abbr']} - {e['desc']}" for e in entries if e["abbr"] and e["desc"]]


def main() -> int:
    if not os.path.exists(SRC):
        print(f"File not found at {SRC} (set ELEC_ABBREV_TXT=... to override).")
        return 1
    pkl = config.KNOWLEDGE_DB_PATH
    if not os.path.exists(pkl):
        print(f"knowledge_db.pkl not found at {pkl}.")
        return 1

    chunks = _chunks(_read(SRC))
    if not chunks:
        print("No entries parsed; aborting.")
        return 1

    shutil.copy(pkl, pkl + ".bak")
    with open(pkl, "rb") as f:
        db = pickle.load(f)
    template = {k: None for k in db[0].keys()} if db else \
        {"source": None, "text": None, "embedding": None}
    db = [d for d in db if d.get("source") != SOURCE_NAME]  # idempotent refresh
    before = len(db)

    for i in range(0, len(chunks), _BATCH):
        batch = chunks[i:i + _BATCH]
        for c, emb in zip(batch, rag.create_embeddings(batch)):
            entry = dict(template)
            entry["source"], entry["text"], entry["embedding"] = SOURCE_NAME, c, emb
            db.append(entry)

    with open(pkl, "wb") as f:
        pickle.dump(db, f)
    print(f"{SOURCE_NAME} ingested: {len(chunks)} chunks | knowledge_db {before} -> {len(db)}")
    print(f"backup: {pkl}.bak  —  restart the service to load the new KB.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
