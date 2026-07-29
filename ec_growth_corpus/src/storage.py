"""
Storage module — writes TXT files and CSV with incremental append.
Implements POLIANNA naming convention: YYYYMMDD_docID.txt
"""

import csv
import os
import re
import sys
from typing import Any, Dict, List, Optional

# Increase CSV field size limit for large full-text documents (300K+ chars)
csv.field_size_limit(sys.maxsize)

from config.settings import TXT_DIR, CSV_DIR, CSV_FILE, CSV_COLUMNS
from src.classifier import classify_document
from src.logger import log
from src.sanitizer import sanitize_pii, sanitize_title


def _ensure_dirs():
    """Ensure output directories exist."""
    os.makedirs(TXT_DIR, exist_ok=True)
    os.makedirs(CSV_DIR, exist_ok=True)


def _sanitize_filename(text: str) -> str:
    """Sanitize a string for use in a filename."""
    # Remove characters unsafe for Windows filenames
    text = re.sub(r'[<>:"/\\|?*]', '', text)
    text = re.sub(r'\s+', '_', text)
    return text[:100]  # Truncate


def _format_date_for_filename(date_str: str) -> str:
    """Extract YYYYMMDD from a date string for filename prefix."""
    if not date_str:
        return "00000000"

    # YYYY-MM-DD
    match = re.match(r'(\d{4})-(\d{2})-(\d{2})', str(date_str))
    if match:
        return f"{match.group(1)}{match.group(2)}{match.group(3)}"

    # YYYY/MM/DD
    match = re.match(r'(\d{4})/(\d{2})/(\d{2})', str(date_str))
    if match:
        return f"{match.group(1)}{match.group(2)}{match.group(3)}"

    # Just YYYY
    match = re.match(r'(\d{4})', str(date_str))
    if match:
        return f"{match.group(1)}0000"

    return "00000000"


def write_txt_file(doc: Dict[str, Any]) -> str:
    """
    Write a single document as a TXT file.
    Naming: YYYYMMDD_docID.txt
    File content: metadata header + full text.
    Returns the file path.
    """
    _ensure_dirs()

    doc_id = doc.get("doc_id", "unknown")
    date_str = doc.get("date", "")
    title = doc.get("title", "Untitled")
    institution = doc.get("authors", doc.get("authors_from_xml", ""))
    doc_type = doc.get("doc_type", doc.get("resource_type", ""))
    full_text = doc.get("full_text", "")
    url = doc.get("url", "")

    # Classification
    classification = classify_document(
        title=title,
        full_text=full_text,
        date_str=date_str,
        raw_institution=institution,
        raw_doc_type=doc_type,
    )

    # Build filename
    date_prefix = _format_date_for_filename(date_str)
    safe_id = _sanitize_filename(doc_id)
    filename = f"{date_prefix}_{safe_id}.txt"
    filepath = os.path.join(TXT_DIR, filename)

    # Build file content
    content_lines = []
    content_lines.append("=" * 80)
    content_lines.append(f"DOCUMENT ID:    {doc_id}")
    content_lines.append(f"TITLE:          {sanitize_title(title)}")
    content_lines.append(f"DATE:           {date_str}")
    content_lines.append(f"INSTITUTION:    {institution}")
    content_lines.append(f"DOCUMENT TYPE:  {doc_type}")
    content_lines.append(f"SOURCE URL:     {url}")
    content_lines.append(f"YEAR (AUTO):    {classification['year']}")
    content_lines.append(f"TOPIC (AUTO):   {classification['topic']}")
    content_lines.append(f"INST (AUTO):    {classification['institution']}")
    content_lines.append(f"DOCTYPE (AUTO): {classification['doc_type']}")
    content_lines.append("=" * 80)
    content_lines.append("")
    content_lines.append(sanitize_pii(full_text))

    full_content = "\n".join(content_lines)

    try:
        with open(filepath, "w", encoding="utf-8") as f:
            f.write(full_content)
        log.debug("  TXT written: %s", filename)
    except Exception as e:
        log.error("  TXT write error (%s): %s", filename, str(e)[:100])

    return filepath


def _load_existing_csv_ids() -> set:
    """Load existing document IDs from CSV (if any) to prevent duplicates."""
    existing_ids = set()
    if os.path.exists(CSV_FILE):
        try:
            with open(CSV_FILE, "r", encoding="utf-8-sig") as f:
                reader = csv.DictReader(f)
                for row in reader:
                    doc_id = row.get("文档ID", "")
                    if doc_id:
                        existing_ids.add(doc_id)
        except Exception as e:
            log.warning("Error reading existing CSV: %s", str(e)[:100])
    return existing_ids


def _csv_file_exists_and_has_header() -> bool:
    """Check if CSV file exists and has the correct header."""
    if not os.path.exists(CSV_FILE):
        return False
    try:
        with open(CSV_FILE, "r", encoding="utf-8-sig") as f:
            first_line = f.readline().strip()
            return "文档ID" in first_line
    except Exception:
        return False


def append_to_csv(docs: List[Dict[str, Any]]) -> int:
    """
    Append documents to CSV file. Incremental — never overwrites.
    Automatically deduplicates by document ID.
    Returns number of new documents added.
    """
    _ensure_dirs()

    existing_ids = _load_existing_csv_ids()
    file_has_header = _csv_file_exists_and_has_header()

    new_count = 0

    try:
        with open(CSV_FILE, "a", newline="", encoding="utf-8-sig") as f:
            writer = csv.DictWriter(f, fieldnames=CSV_COLUMNS)

            # Write header if file is new or empty
            if not file_has_header:
                writer.writeheader()
                file_has_header = True  # Prevent re-writing header

            for doc in docs:
                doc_id = doc.get("doc_id", "")
                if doc_id in existing_ids:
                    continue  # Skip duplicates

                title = sanitize_title(doc.get("title", ""))
                date_str = doc.get("date", "")
                url = doc.get("url", "")
                institution = doc.get("authors", "")
                doc_type = doc.get("doc_type", doc.get("resource_type", ""))
                full_text = sanitize_pii(doc.get("full_text", ""))

                # Auto-classification
                classification = classify_document(
                    title=title,
                    full_text=full_text,
                    date_str=date_str,
                    raw_institution=institution,
                    raw_doc_type=doc_type,
                )

                row = {
                    "文档ID": doc_id,
                    "标题": title,
                    "发布日期": date_str,
                    "原文链接": url,
                    "发布机构": classification["institution"],
                    "文件类型": classification["doc_type"],
                    "年份": classification["year"],
                    "议题领域": classification["topic"],
                    "完整正文": full_text,
                }

                writer.writerow(row)
                existing_ids.add(doc_id)
                new_count += 1

    except Exception as e:
        log.error("CSV write error: %s", str(e)[:200])

    return new_count


def save_documents(docs: List[Dict[str, Any]]) -> Dict[str, int]:
    """
    Save a batch of documents: TXT files + CSV append.
    Returns counts: {txt_count, csv_count, skipped}.
    """
    tx_count = 0
    csv_docs_to_write = []
    existing_ids = _load_existing_csv_ids()

    for doc in docs:
        doc_id = doc.get("doc_id", "")
        if not doc_id:
            continue

        # Write TXT
        try:
            write_txt_file(doc)
            tx_count += 1
        except Exception as e:
            log.error("TXT save error for %s: %s", doc_id, str(e)[:100])

        # Collect for CSV (dedup)
        if doc_id not in existing_ids:
            csv_docs_to_write.append(doc)

    # Append to CSV
    csv_new = append_to_csv(csv_docs_to_write) if csv_docs_to_write else 0

    log.info("Saved: %d TXT files, %d new CSV rows", tx_count, csv_new)
    return {"txt_count": tx_count, "csv_count": csv_new, "skipped": len(docs) - tx_count}


def get_corpus_stats() -> Dict[str, Any]:
    """Get current corpus statistics."""
    _ensure_dirs()

    txt_files = [f for f in os.listdir(TXT_DIR) if f.endswith(".txt")]
    csv_rows = 0
    if os.path.exists(CSV_FILE):
        try:
            with open(CSV_FILE, "r", encoding="utf-8-sig") as f:
                reader = csv.DictReader(f)
                csv_rows = sum(1 for _ in reader)
        except Exception:
            pass

    return {
        "txt_count": len(txt_files),
        "csv_rows": csv_rows,
        "txt_dir": TXT_DIR,
        "csv_path": CSV_FILE,
    }
