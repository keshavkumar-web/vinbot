"""Build the structured UHBVN fact store from the tabular report PDFs.

    python build_tables.py                       # uses ../UHBVN_new
    TABLES_SOURCE_DIR=/path python build_tables.py

Companion to ingest.py: ingest.py builds the vector store over the prose
circulars; this builds the SQLite fact store over the numeric report tables.
"""

from app import tables

if __name__ == "__main__":
    tables.build()
