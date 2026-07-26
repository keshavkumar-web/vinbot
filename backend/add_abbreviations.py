"""Ingest Haryana_DISCOM_Abbreviations.txt into the prose knowledge base —
incremental & idempotent.

Each glossary entry (abbreviation + full form + category + description + example)
becomes ONE self-contained chunk, so "what is SDO?", "full form of RTS", "what
does FGRA stand for" retrieve the exact entry with high precision.

APPENDS to `knowledge_db.pkl` WITHOUT re-embedding the existing corpus. Safe to
re-run: prior entries from this source are removed first and the pkl is backed up
to `*.bak`. Each machine has its OWN pkl (dev and prod differ — never copy one
over the other; run this on each). Restart the service afterwards (KB loads at
startup).

    python add_abbreviations.py      # from backend/, venv active, OPENAI_API_KEY set
"""

from __future__ import annotations

import os
import pickle
import re
import shutil
import sys

from app import config, rag

SRC = os.getenv(
    "ABBREV_TXT",
    os.path.join(config.BACKEND_DIR, "Haryana_DISCOM_Abbreviations.txt"))
SOURCE_NAME = "Haryana_DISCOM_Abbreviations.txt"
_BATCH = 100  # embeddings per API call


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
    """One chunk per glossary entry: a blank-line-separated block that carries a
    'Full Form:' line (skips the title, table of contents, section headers, notes)."""
    blocks = re.split(r"\r?\n[ \t]*\r?\n", text)
    out = []
    for b in blocks:
        if "Full Form:" not in b:
            continue
        chunk = re.sub(r"[ \t]+(\r?\n)", r"\1", b.strip())  # trim trailing spaces
        chunk = re.sub(r"\r\n", "\n", chunk)
        if chunk:
            out.append(chunk)
    return out


def main() -> int:
    if not os.path.exists(SRC):
        print(f"Abbreviations file not found at {SRC} (set ABBREV_TXT=... to override).")
        return 1
    pkl = config.KNOWLEDGE_DB_PATH
    if not os.path.exists(pkl):
        print(f"knowledge_db.pkl not found at {pkl}.")
        return 1

    chunks = _chunks(_read(SRC))
    if not chunks:
        print("No glossary entries parsed; aborting.")
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
