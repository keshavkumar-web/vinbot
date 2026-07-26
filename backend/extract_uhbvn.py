"""Extract text from the UHBVN PDFs into backend/knowledge/*.txt.

Per-page hybrid strategy:
  - If a page has an extractable text layer (pypdf), use it.
  - If a page is a scanned image (little/no text), render it with PyMuPDF and
    OCR it via the OpenAI vision model.

Resumable: a PDF whose output .txt already exists (non-empty) is skipped, so a
re-run does not repeat expensive OCR. Delete a .txt to force re-extraction.

Run from the backend/ directory:
    python extract_uhbvn.py
"""

import base64
import concurrent.futures as cf
import os
import re
import sys
from pathlib import Path

import fitz  # PyMuPDF
from pypdf import PdfReader

from app import config
from app.rag import client

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------
UHBVN_DIR = Path(os.getenv(
    "UHBVN_DIR", os.path.join(os.path.dirname(config.BACKEND_DIR), "UHBVN")
))
OUT_DIR = Path(config.KNOWLEDGE_FOLDER)
OCR_MODEL = os.getenv("OCR_MODEL", "gpt-4o-mini")
OCR_DPI = int(os.getenv("OCR_DPI", "200"))
MIN_PAGE_TEXT = 50          # below this many chars, treat a page as scanned
OCR_WORKERS = int(os.getenv("OCR_WORKERS", "6"))

OCR_PROMPT = (
    "You are an OCR engine. Transcribe ALL text from this scanned document page "
    "exactly as it appears, preserving reading order and line breaks. Render "
    "tables as plain text using spaces/pipes to keep columns aligned. Do NOT "
    "summarize, translate, explain, or add any commentary. Output only the "
    "transcribed text. If the page is blank, output nothing."
)


def clean_text(s: str) -> str:
    """Light cleanup of common PDF-extraction artifacts."""
    if not s:
        return ""
    s = s.replace("\x00", "")          # strip null bytes
    s = s.replace("�", "'")       # U+FFFD where PDF used a non-standard quote
    s = s.replace("\r\n", "\n").replace("\r", "\n")
    # Trim trailing spaces on each line; collapse 3+ blank lines to 2.
    s = "\n".join(line.rstrip() for line in s.split("\n"))
    s = re.sub(r"\n{3,}", "\n\n", s)
    return s.strip()


def ocr_page(doc: "fitz.Document", index: int) -> str:
    """Render a page to PNG and OCR it with the OpenAI vision model."""
    page = doc[index]
    pix = page.get_pixmap(dpi=OCR_DPI)
    png = pix.tobytes("png")
    b64 = base64.b64encode(png).decode("ascii")
    resp = client.chat.completions.create(
        model=OCR_MODEL,
        temperature=0,
        messages=[
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": OCR_PROMPT},
                    {
                        "type": "image_url",
                        "image_url": {
                            "url": f"data:image/png;base64,{b64}",
                            "detail": "high",
                        },
                    },
                ],
            }
        ],
    )
    out = (resp.choices[0].message.content or "").strip()
    # The model sometimes wraps OCR output in a markdown code fence; strip it.
    if out.startswith("```"):
        out = re.sub(r"^```[a-zA-Z]*\n?", "", out)
        out = re.sub(r"\n?```$", "", out).strip()
    return out


def extract_pdf(path: Path) -> str:
    """Return the full text of a PDF, OCR-ing image-only pages as needed."""
    reader = PdfReader(str(path))
    n = len(reader.pages)

    # First pass: pull whatever text layer exists, mark pages needing OCR.
    page_text: list[str] = [""] * n
    ocr_needed: list[int] = []
    for i, page in enumerate(reader.pages):
        try:
            t = (page.extract_text() or "").strip()
        except Exception:
            t = ""
        if len(t) < MIN_PAGE_TEXT:
            ocr_needed.append(i)
        else:
            page_text[i] = t

    # Second pass: OCR the image pages concurrently.
    if ocr_needed:
        doc = fitz.open(str(path))
        print(f"    OCR-ing {len(ocr_needed)} page(s) of {n}...", flush=True)
        with cf.ThreadPoolExecutor(max_workers=OCR_WORKERS) as pool:
            futures = {pool.submit(ocr_page, doc, i): i for i in ocr_needed}
            for fut in cf.as_completed(futures):
                i = futures[fut]
                try:
                    page_text[i] = fut.result()
                except Exception as exc:
                    print(f"    page {i} OCR failed: {exc}", flush=True)
                    page_text[i] = ""
        doc.close()

    body = "\n\n".join(t for t in page_text if t.strip())
    header = f"Source document: {path.name}\n\n"
    return clean_text(header + body)


def main() -> None:
    if not UHBVN_DIR.is_dir():
        sys.exit(f"UHBVN source folder not found: {UHBVN_DIR}")
    OUT_DIR.mkdir(parents=True, exist_ok=True)

    pdfs = sorted(UHBVN_DIR.glob("*.pdf"))
    print(f"Found {len(pdfs)} PDFs in {UHBVN_DIR}")
    print(f"Writing .txt to {OUT_DIR}\n")

    done = skipped = failed = 0
    for idx, pdf in enumerate(pdfs, 1):
        out = OUT_DIR / (pdf.stem + ".txt")
        if out.exists() and out.stat().st_size > 0:
            print(f"[{idx}/{len(pdfs)}] skip (exists): {pdf.name}", flush=True)
            skipped += 1
            continue
        print(f"[{idx}/{len(pdfs)}] {pdf.name}", flush=True)
        try:
            text = extract_pdf(pdf)
            out.write_text(text, encoding="utf-8")
            print(f"    -> {out.name} ({len(text):,} chars)", flush=True)
            done += 1
        except Exception as exc:
            print(f"    FAILED: {exc}", flush=True)
            failed += 1

    print(f"\nDone. extracted={done} skipped={skipped} failed={failed}")


if __name__ == "__main__":
    main()
