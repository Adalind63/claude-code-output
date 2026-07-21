#!/usr/bin/env python3
"""
EU-China Trade Policy English Corpus Collection System
SPARQL Endpoint + CELLAR REST API + EUR-Lex Legal-Content API
Complete modular system for collecting EU legal documents on China trade policy
"""

import os
import sys
import time
import json
import hashlib
import csv
import re
from pathlib import Path
from datetime import datetime
from collections import defaultdict
import requests
from lxml import etree
import difflib

# ============================================================
# GLOBAL CONSTANTS — Customize here
# ============================================================
BASE_DIR = os.path.join("D:", os.sep, "项目流程", "eu_corpus")
XML_DIR = os.path.join(BASE_DIR, "xml")
PDF_DIR = os.path.join(BASE_DIR, "pdf")
TXT_DIR = os.path.join(BASE_DIR, "txt")
CSV_DIR = os.path.join(BASE_DIR, "csv")

SPARQL_ENDPOINT = "https://publications.europa.eu/webapi/rdf/sparql"
CELLAR_BASE = "https://publications.europa.eu/resource/celex/"

# Document retrieval: official EUR-Lex legal-content API
# HTML endpoint contains full text (XML endpoint is metadata-only)
LEGAL_CONTENT_HTML = "https://eur-lex.europa.eu/legal-content/EN/TXT/HTML/"
LEGAL_CONTENT_PDF = "https://eur-lex.europa.eu/legal-content/EN/TXT/PDF/"

# Also keep XML endpoint for metadata
LEGAL_CONTENT_XML = "https://eur-lex.europa.eu/legal-content/EN/TXT/XML/"

HEADERS = {
    "Accept-Language": "eng",
    "User-Agent": "EU-Corpus-Collector/1.0 (Research; Academic Use)"
}

REQUEST_INTERVAL = 1.5       # seconds between requests
MAX_RETRIES = 3               # max retry attempts
MIN_FILE_SIZE = 500           # bytes, files below this are considered corrupt
TEXT_MIN_CHARS = 200          # minimum characters for valid TXT
SIMILARITY_THRESHOLD = 0.92   # XML-PDF text similarity threshold

YEAR_START = 2017
YEAR_END = 2026

# Trade policy keywords for filtering
TRADE_KEYWORDS = [
    "trade", "critical raw material", "semiconductor", "electric vehicle",
    "renewable energy", "steel", "market access", "digital trade",
    "subsidy", "anti-subsidy", "anti-dumping", "tariff",
    "investment screening", "fdi", "intellectual property", "ip",
    "carbon border adjustment", "cbam", "industrial policy"
]

# China-related patterns
CHINA_PATTERNS = ["china", "chinese"]

# Exclusion patterns (Hong Kong, Macau, Taiwan standalone docs)
EXCLUDE_PATTERNS = [
    r"\bhong\s*kong\b", r"\bmacau\b", r"\bmacao\b", r"\btaiwan\b",
    r"\btaipei\b", r"\bchinese\s*taipei\b"
]

# EU institutions mapping
INSTITUTION_MAP = {
    "commission": "欧委会",
    "council": "欧盟理事会",
    "parliament": "欧洲议会",
    "trade": "DG TRADE",
    "eeas": "EEAS",
    "external action": "EEAS",
    "committee": "欧委会",
    "directorate": "欧委会",
}

# Document type mapping
DOCTYPE_MAP = {
    "regulation": "条例",
    "decision": "决议",
    "report": "报告",
    "white paper": "白皮书",
    "declaration": "声明",
    "communication": "报告",
    "recommendation": "决议",
    "directive": "条例",
    "notice": "声明",
    "proposal": "报告",
    "opinion": "报告",
}

# Topic classification mapping
TOPIC_KEYWORDS = {
    "半导体": ["semiconductor", "chip", "microchip", "processor", "microelectronics"],
    "新能源": ["renewable energy", "solar", "wind", "hydrogen", "clean energy", "photovoltaic", "battery", "electric vehicle", "ev"],
    "钢铁": ["steel", "aluminium", "aluminum", "metal"],
    "市场准入": ["market access", "public procurement", "government procurement"],
    "数字贸易": ["digital trade", "data flow", "data localisation", "digital economy", "e-commerce"],
    "补贴调查": ["subsidy", "anti-subsidy", "state aid", "foreign subsidy", "countervailing", "anti-dumping"],
    "关税": ["tariff", "duty", "mfn", "gsp", "generalised scheme", "countervailing"],
    "投资审查": ["investment screening", "fdi", "foreign direct investment", "investment control"],
    "知识产权": ["intellectual property", "patent", "trademark", "copyright", "trade secret", "technology transfer"],
}


# ============================================================
# UTILITY FUNCTIONS
# ============================================================
def ensure_dirs():
    """Create all required directories."""
    for d in [XML_DIR, PDF_DIR, TXT_DIR, CSV_DIR]:
        os.makedirs(d, exist_ok=True)
    print(f"[INIT] Base directory: {BASE_DIR}")


def sha256_file(filepath):
    """Compute SHA256 hash of a file."""
    h = hashlib.sha256()
    try:
        with open(filepath, "rb") as f:
            while True:
                chunk = f.read(65536)
                if not chunk:
                    break
                h.update(chunk)
        return h.hexdigest()
    except Exception:
        return ""


def safe_request(url, method="GET", timeout=60):
    """Make HTTP request with retry and exponential backoff."""
    last_error = None
    for attempt in range(MAX_RETRIES):
        try:
            time.sleep(REQUEST_INTERVAL)
            if method == "GET":
                resp = requests.get(url, headers=HEADERS, timeout=timeout)
            else:
                resp = requests.post(url, headers=HEADERS, timeout=timeout)
            if resp.status_code == 200:
                return resp
            elif resp.status_code == 404:
                return resp
            else:
                last_error = f"HTTP {resp.status_code}"
        except Exception as e:
            last_error = str(e)
        if attempt < MAX_RETRIES - 1:
            wait = (2 ** attempt) * REQUEST_INTERVAL
            time.sleep(wait)
    print(f"  [WARN] Request failed: {url[:100]} — {last_error}")
    return None


def classify_by_map(text, mapping, default="其他"):
    """Classify text by keyword mapping, return first match."""
    text_lower = text.lower()
    for key, label in mapping.items():
        if key.lower() in text_lower:
            return label
    return default


def classify_by_keywords(text, topic_dict, default="其他"):
    """Classify text by multi-keyword dictionary."""
    text_lower = text.lower()
    for label, keywords in topic_dict.items():
        for kw in keywords:
            if kw in text_lower:
                return label
    return default


# ============================================================
# MODULE 1: SPARQL RETRIEVAL & FILTERING
# ============================================================

def build_sparql_query_simple():
    """Build a simple, fast SPARQL query: China/Chinese + English + date range.
    Trade keyword filtering is done locally in Python for speed.
    """
    query = f"""
    PREFIX cdm: <http://publications.europa.eu/ontology/cdm#>
    PREFIX xsd: <http://www.w3.org/2001/XMLSchema#>

    SELECT DISTINCT ?celex ?title ?publish_date ?institution ?doc_type
    WHERE {{
      ?work cdm:resource_legal_id_celex ?celex .
      ?work cdm:work_title ?title .
      ?work cdm:work_date_document ?publish_date .

      OPTIONAL {{
        ?work cdm:work_created_by_agent ?agent .
        ?agent <http://purl.org/dc/elements/1.1/title> ?institution .
      }}

      OPTIONAL {{
        ?work cdm:resource_legal_type ?type_uri .
        ?type_uri <http://purl.org/dc/elements/1.1/title> ?doc_type .
      }}

      FILTER(LANG(?title) = "en")
      FILTER(CONTAINS(LCASE(STR(?title)), "china") || CONTAINS(LCASE(STR(?title)), "chinese"))
      FILTER(?publish_date >= "{YEAR_START}-01-01"^^xsd:date)
      FILTER(?publish_date <= "{YEAR_END}-12-31"^^xsd:date)
    }}
    ORDER BY DESC(?publish_date)
    LIMIT 3000
    """
    return query


def execute_sparql(query):
    """Execute a single SPARQL query against EU Publications endpoint."""
    headers = {
        "Accept": "application/sparql-results+json",
        "Content-Type": "application/sparql-query",
        "User-Agent": "EU-Corpus-Collector/1.0"
    }

    try:
        time.sleep(REQUEST_INTERVAL)
        resp = requests.post(SPARQL_ENDPOINT, data=query.encode('utf-8'),
                            headers=headers, timeout=180)
        if resp.status_code == 200:
            return resp.json()
        else:
            print(f"  [SPARQL] HTTP {resp.status_code}: {resp.text[:200]}")
            return None
    except Exception as e:
        print(f"  [SPARQL] Exception: {e}")
        return None


def parse_sparql_results(data):
    """Parse SPARQL JSON results into list of deduplicated dicts."""
    if not data or "results" not in data:
        return []

    records = []
    for binding in data["results"]["bindings"]:
        record = {
            "celex": binding.get("celex", {}).get("value", ""),
            "title": binding.get("title", {}).get("value", ""),
            "publish_date": binding.get("publish_date", {}).get("value", ""),
            "institution": binding.get("institution", {}).get("value", ""),
            "doc_type": binding.get("doc_type", {}).get("value", ""),
        }
        if record["celex"]:
            records.append(record)

    # Deduplicate by celex
    seen = set()
    unique = []
    for r in records:
        if r["celex"] not in seen:
            seen.add(r["celex"])
            unique.append(r)

    return unique


def local_trade_filter(records):
    """Filter records locally: must contain at least one trade keyword in title."""
    filtered = []
    for r in records:
        title_lower = r["title"].lower()
        matched = False
        for kw in TRADE_KEYWORDS:
            if kw in title_lower:
                matched = True
                break
        if matched:
            filtered.append(r)
    return filtered


def apply_exclusion_filter(records):
    """Exclude documents about HK/Macau/Taiwan standalone."""
    filtered = []
    for r in records:
        title_lower = r["title"].lower()
        if any(re.search(p, title_lower) for p in EXCLUDE_PATTERNS):
            continue
        filtered.append(r)
    return filtered


def run_sparql_collection(csv_path):
    """Run SPARQL query and filter results locally."""
    print(f"\n[MODULE 1] SPARQL Retrieval — EU-China trade documents (2017-2026, EN)")
    print(f"[SPARQL] Strategy: Broad SPARQL → local Python filtering")
    print(f"[SPARQL] Trade keywords for local filter: {len(TRADE_KEYWORDS)}")

    query = build_sparql_query_simple()
    print(f"[SPARQL] Executing query (China + EN + date)...")

    data = execute_sparql(query)

    if not data:
        print("[SPARQL] ERROR: No response from endpoint.")
        return {}

    raw_records = parse_sparql_results(data)
    print(f"[SPARQL] Raw results (China in title): {len(raw_records)}")

    # Local trade keyword filtering
    trade_filtered = local_trade_filter(raw_records)
    print(f"[SPARQL] After trade keyword filter: {len(trade_filtered)}")

    # Exclusion filter
    final_records = apply_exclusion_filter(trade_filtered)
    print(f"[SPARQL] After exclusion filter: {len(final_records)}")

    if not final_records:
        print("[SPARQL] WARNING: No records after filtering!")
        return {}

    # Build CSV
    records = build_celex_csv(final_records, csv_path)
    return records


def build_celex_csv(records, csv_path):
    """Build or update the main CELEX CSV manifest."""
    fieldnames = [
        "celex", "title", "publish_date", "institution", "doc_type",
        "original_url", "year_label", "topic_label", "institution_label",
        "doc_type_label", "download_status", "file_hash",
        "txt_export_status", "document_relevance_score", "parent_celex"
    ]

    # Load existing records if any
    existing = {}
    if os.path.exists(csv_path):
        with open(csv_path, "r", encoding="utf-8-sig", newline="") as f:
            reader = csv.DictReader(f)
            for row in reader:
                existing[row["celex"]] = row

    # Merge new records
    new_count = 0
    for r in records:
        celex = r["celex"]
        if celex not in existing:
            year = r["publish_date"][:4] if r.get("publish_date") else ""
            row = {
                "celex": celex,
                "title": r.get("title", ""),
                "publish_date": r.get("publish_date", ""),
                "institution": r.get("institution", ""),
                "doc_type": r.get("doc_type", ""),
                "original_url": f"{CELLAR_BASE}{celex}",
                "year_label": year if year.isdigit() and YEAR_START <= int(year) <= YEAR_END else "",
                "topic_label": "",
                "institution_label": classify_by_map(r.get("institution", ""), INSTITUTION_MAP),
                "doc_type_label": classify_by_map(r.get("doc_type", ""), DOCTYPE_MAP),
                "download_status": "unfinished",
                "file_hash": "",
                "txt_export_status": "",
                "document_relevance_score": "",
                "parent_celex": "",
            }
            existing[celex] = row
            new_count += 1

    # Write back
    with open(csv_path, "w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for celex in sorted(existing.keys()):
            writer.writerow(existing[celex])

    print(f"[CSV] Total: {len(existing)}, New this run: {new_count}")
    return existing


# ============================================================
# MODULE 2: AMENDMENT/CORRIGENDUM LINKAGE
# ============================================================

def query_amendments(celex):
    """Query SPARQL for amendments and corrigenda linked to a CELEX."""
    query = f"""
    PREFIX cdm: <http://publications.europa.eu/ontology/cdm#>

    SELECT DISTINCT ?amended_celex ?title ?date WHERE {{
      ?work cdm:resource_legal_id_celex "{celex}" .

      {{ ?work cdm:amended_by ?amended . }}
      UNION
      {{ ?work cdm:corrected_by ?amended . }}
      UNION
      {{ ?work cdm:amends ?amended . }}

      ?amended cdm:resource_legal_id_celex ?amended_celex .
      OPTIONAL {{ ?amended cdm:work_title ?title . FILTER(LANG(?title) = "en") }}
      OPTIONAL {{ ?amended cdm:work_date_document ?date }}
    }}
    LIMIT 50
    """

    headers = {
        "Accept": "application/sparql-results+json",
        "Content-Type": "application/sparql-query",
    }

    try:
        time.sleep(REQUEST_INTERVAL)
        resp = requests.post(SPARQL_ENDPOINT, data=query.encode('utf-8'),
                            headers=headers, timeout=60)
        if resp.status_code == 200:
            data = resp.json()
            results = []
            for b in data.get("results", {}).get("bindings", []):
                results.append({
                    "celex": b.get("amended_celex", {}).get("value", ""),
                    "title": b.get("title", {}).get("value", ""),
                    "publish_date": b.get("date", {}).get("value", ""),
                })
            return results
    except Exception as e:
        pass

    return []


def collect_amendments(records, csv_path):
    """Collect amendments for all main records and append to CSV."""
    print(f"\n[MODULE 2] Collecting amendments/corrigenda...")

    fieldnames = [
        "celex", "title", "publish_date", "institution", "doc_type",
        "original_url", "year_label", "topic_label", "institution_label",
        "doc_type_label", "download_status", "file_hash",
        "txt_export_status", "document_relevance_score", "parent_celex"
    ]

    # Ensure parent_celex column exists in existing records
    existing = {}
    if os.path.exists(csv_path):
        with open(csv_path, "r", encoding="utf-8-sig", newline="") as f:
            reader = csv.DictReader(f)
            for row in reader:
                if "parent_celex" not in row:
                    row["parent_celex"] = ""
                existing[row["celex"]] = row

    main_records = {k: v for k, v in existing.items() if not v.get("parent_celex", "")}

    new_amendments = 0
    for i, (celex, record) in enumerate(main_records.items()):
        if (i + 1) % 50 == 0:
            print(f"  [AMEND] Progress: {i+1}/{len(main_records)}")

        amendments = query_amendments(celex)
        for amd in amendments:
            amd_celex = amd["celex"]
            if amd_celex and amd_celex not in existing:
                row = {
                    "celex": amd_celex,
                    "title": amd.get("title", f"Amendment to {celex}"),
                    "publish_date": amd.get("publish_date", ""),
                    "institution": record.get("institution", ""),
                    "doc_type": "Amendment",
                    "original_url": f"{CELLAR_BASE}{amd_celex}",
                    "year_label": "",
                    "topic_label": "",
                    "institution_label": record.get("institution_label", ""),
                    "doc_type_label": "其他",
                    "download_status": "unfinished",
                    "file_hash": "",
                    "txt_export_status": "",
                    "document_relevance_score": "",
                    "parent_celex": celex,
                }
                existing[amd_celex] = row
                new_amendments += 1

    with open(csv_path, "w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames, extrasaction='ignore')
        writer.writeheader()
        for c in sorted(existing.keys()):
            writer.writerow(existing[c])

    print(f"[AMEND] Added {new_amendments} amendment/corrigendum records")
    return existing


# ============================================================
# MODULE 3: BATCH DOCUMENT DOWNLOAD (NOTICE XML + PDF)
# ============================================================

def download_document_html(celex):
    """Download official HTML (full text) for a CELEX via legal-content API."""
    url = f"{LEGAL_CONTENT_HTML}?uri=CELEX:{celex}"
    resp = safe_request(url, timeout=120)
    if resp is None or resp.status_code != 200:
        return None, f"HTTP {resp.status_code if resp else 'error'}"

    content = resp.content
    if len(content) < MIN_FILE_SIZE:
        return None, f"File too small ({len(content)} bytes)"

    # Save as HTML in xml/ folder (reusing xml/ for raw source files)
    filepath = os.path.join(XML_DIR, f"{celex}.html")
    with open(filepath, "wb") as f:
        f.write(content)

    file_hash = sha256_file(filepath)
    return filepath, file_hash


def download_pdf(celex):
    """Download official PDF for a CELEX via legal-content API."""
    url = f"{LEGAL_CONTENT_PDF}?uri=CELEX:{celex}"
    resp = safe_request(url, timeout=120)
    if resp is None or resp.status_code != 200:
        return None

    content = resp.content
    if len(content) < MIN_FILE_SIZE:
        return None

    filepath = os.path.join(PDF_DIR, f"{celex}.pdf")
    with open(filepath, "wb") as f:
        f.write(content)

    return filepath


def batch_download(csv_path, max_downloads=None):
    """Batch download XML for all unfinished items in CSV."""
    print(f"\n[MODULE 3] Batch downloading HTML full-text documents...")

    records = {}
    fieldnames = []
    with open(csv_path, "r", encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f)
        fieldnames = reader.fieldnames or []
        for row in reader:
            records[row["celex"]] = row

    unfinished = {k: v for k, v in records.items()
                  if v.get("download_status") not in ("success",)}

    # Limit downloads if specified (for testing)
    if max_downloads and len(unfinished) > max_downloads:
        unfinished_items = list(unfinished.items())[:max_downloads]
        unfinished = dict(unfinished_items)

    print(f"[DOWNLOAD] {len(unfinished)} items to download (out of {len(records)} total)")

    success_count = 0
    fail_count = 0
    corrupted = []

    for i, (celex, record) in enumerate(unfinished.items()):
        if (i + 1) % 10 == 0:
            print(f"  [DOWNLOAD] Progress: {i+1}/{len(unfinished)} (OK:{success_count} FAIL:{fail_count})")

        # Skip if XML already exists and is valid
        xml_path = os.path.join(XML_DIR, f"{celex}.html")
        if os.path.exists(xml_path) and os.path.getsize(xml_path) >= MIN_FILE_SIZE:
            file_hash = sha256_file(xml_path)
            records[celex]["file_hash"] = file_hash
            records[celex]["download_status"] = "success"
            success_count += 1
            continue

        # Download
        result_path, result = download_document_html(celex)

        if result_path:
            records[celex]["file_hash"] = result
            records[celex]["download_status"] = "success"
            success_count += 1
        else:
            records[celex]["download_status"] = "failed"
            fail_count += 1
            if "small" in str(result).lower() or "corrupt" in str(result).lower():
                corrupted.append(celex)
                records[celex]["download_status"] = "corrupted"

    # Save progress
    if fieldnames:
        with open(csv_path, "w", encoding="utf-8-sig", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames, extrasaction='ignore')
            writer.writeheader()
            for c in sorted(records.keys()):
                writer.writerow(records[c])

    print(f"[DOWNLOAD] Complete: {success_count} success, {fail_count} failed, {len(corrupted)} corrupted")
    if corrupted:
        corrupt_path = os.path.join(CSV_DIR, "corrupted_files.csv")
        with open(corrupt_path, "w", encoding="utf-8-sig", newline="") as f:
            writer = csv.writer(f)
            writer.writerow(["celex"])
            for c in corrupted:
                writer.writerow([c])

    return records


# ============================================================
# MODULE 4: XML PARSING & TEXT EXTRACTION
# ============================================================

def parse_html_document(filepath):
    """Parse EUR-Lex HTML document and extract full text + structure."""
    try:
        # Read raw HTML
        with open(filepath, "rb") as f:
            raw = f.read()

        # Use lxml.html for proper HTML parsing
        from lxml import html as lhtml
        doc = lhtml.fromstring(raw)

        # Get all text from body
        body = doc.find('.//body')
        if body is None:
            body = doc

        full_text = body.text_content()

        # Clean up whitespace
        full_text = re.sub(r'[\r\n]+', '\n', full_text)
        full_text = re.sub(r'[ \t]{2,}', ' ', full_text)
        full_text = re.sub(r'\n{3,}', '\n\n', full_text)

        result = {
            "body_text": full_text.strip(),
            "structure": {
                "article_count": 0,
                "annex_count": 0,
                "footnote_count": 0,
                "corrigendum_count": 0,
                "amendment_count": 0,
            }
        }

        # Count structural elements from text patterns
        html_str = lhtml.tostring(doc, encoding='unicode')

        result["structure"]["article_count"] = len(re.findall(
            r'Article\s+\d+', html_str))
        result["structure"]["annex_count"] = len(re.findall(
            r'ANNEX\s+[IVX\d]|Annex\s+[IVX\d]', html_str))
        result["structure"]["footnote_count"] = len(re.findall(
            r'class="[^"]*footnote|[^"]*ftn', html_str, re.IGNORECASE))

        return result

    except Exception as e:
        print(f"  [PARSE] {os.path.basename(filepath)}: {e}")
        return None


def extract_full_text(source_path):
    """Extract clean continuous text from downloaded HTML document."""
    parsed = parse_html_document(source_path)
    if not parsed:
        return ""

    text = parsed["body_text"]
    # Normalize whitespace
    text = re.sub(r'\n\s*\n', '\n\n', text)
    text = re.sub(r'[ \t]+', ' ', text)
    return text.strip()


# ============================================================
# MODULE 5: PDF TEXT EXTRACTION
# ============================================================

def extract_pdf_text(pdf_path):
    """Extract text from PDF using PyPDF2."""
    try:
        from PyPDF2 import PdfReader
        reader = PdfReader(pdf_path)
        texts = []
        for page in reader.pages:
            page_text = page.extract_text()
            if page_text:
                texts.append(page_text)
        return "\n".join(texts)
    except Exception as e:
        return ""


# ============================================================
# MODULE 6: DOUBLE-LAYER INTEGRITY VERIFICATION
# ============================================================

def verify_xml_structure(records):
    """Layer 1: Statistical verification of XML tag structure."""
    print(f"\n[MODULE 6] Layer 1: XML structure verification...")

    results = []
    for celex, record in records.items():
        if record.get("download_status") != "success":
            continue

        xml_path = os.path.join(XML_DIR, f"{celex}.html")
        if not os.path.exists(xml_path):
            continue

        parsed = parse_html_document(xml_path)
        if not parsed:
            results.append({
                "celex": celex,
                "article_count": 0, "annex_count": 0, "footnote_count": 0,
                "corrigendum_count": 0, "amendment_count": 0,
                "structure_complete": "PARSE_ERROR"
            })
            continue

        s = parsed["structure"]
        total = sum(s.values())
        is_complete = "YES" if total > 0 else "LOW_CONTENT"

        results.append({
            "celex": celex,
            "article_count": s["article_count"],
            "annex_count": s["annex_count"],
            "footnote_count": s["footnote_count"],
            "corrigendum_count": s["corrigendum_count"],
            "amendment_count": s["amendment_count"],
            "structure_complete": is_complete
        })

    struct_path = os.path.join(CSV_DIR, "xml_structure_check.csv")
    with open(struct_path, "w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=[
            "celex", "article_count", "annex_count", "footnote_count",
            "corrigendum_count", "amendment_count", "structure_complete"
        ])
        writer.writeheader()
        for r in results:
            writer.writerow(r)

    print(f"[STRUCT] {len(results)} records checked → {struct_path}")
    return results


def verify_xml_pdf_similarity(records, sample_size=20):
    """Layer 2: XML-PDF text similarity verification (sampled)."""
    print(f"\n[MODULE 6] Layer 2: XML-PDF text similarity (sample={sample_size})...")

    success_records = {k: v for k, v in records.items()
                       if v.get("download_status") == "success"}
    sample_keys = list(success_records.keys())[:sample_size]

    abnormal = []
    checked = 0

    for celex in sample_keys:
        xml_path = os.path.join(XML_DIR, f"{celex}.html")
        pdf_path = os.path.join(PDF_DIR, f"{celex}.pdf")

        if not os.path.exists(xml_path):
            continue

        # Download PDF if needed
        if not os.path.exists(pdf_path):
            result = download_pdf(celex)

        if not os.path.exists(pdf_path):
            continue

        xml_text = extract_full_text(xml_path)
        pdf_text = extract_pdf_text(pdf_path)

        if not xml_text or not pdf_text:
            continue

        xml_clean = re.sub(r'\s+', ' ', xml_text).strip().lower()
        pdf_clean = re.sub(r'\s+', ' ', pdf_text).strip().lower()

        similarity = difflib.SequenceMatcher(
            None, xml_clean[:8000], pdf_clean[:8000]
        ).ratio()

        checked += 1

        if similarity < SIMILARITY_THRESHOLD:
            abnormal.append({
                "celex": celex,
                "title": records.get(celex, {}).get("title", ""),
                "similarity_score": round(similarity, 4),
                "xml_chars": len(xml_clean),
                "pdf_chars": len(pdf_clean),
                "status": "ABNORMAL"
            })

    abnorm_path = os.path.join(CSV_DIR, "abnormal_document_list.csv")
    with open(abnorm_path, "w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=[
            "celex", "title", "similarity_score", "xml_chars", "pdf_chars", "status"
        ])
        writer.writeheader()
        for a in abnormal:
            writer.writerow(a)

    print(f"[SIMILARITY] Checked: {checked}, Abnormal (<{SIMILARITY_THRESHOLD}): {len(abnormal)}")
    return abnormal


# ============================================================
# MODULE 7: SEMANTIC RELEVANCE FILTERING
# ============================================================

def check_relevance(xml_text):
    """Check if document is genuinely about China trade policy."""
    text_lower = xml_text.lower()

    has_china = any(p in text_lower for p in CHINA_PATTERNS)
    if not has_china:
        return 0.0, False

    trade_matches = sum(1 for kw in TRADE_KEYWORDS if kw in text_lower)

    if trade_matches < 2:
        return 0.2, False

    words = len(text_lower.split()) if text_lower.split() else 1
    keyword_count = sum(text_lower.count(kw) for kw in TRADE_KEYWORDS)
    china_count = sum(text_lower.count(p) for p in CHINA_PATTERNS)

    density = (keyword_count + china_count) / words
    score = min(1.0, density * 100 + 0.3)

    if trade_matches >= 4:
        score = min(1.0, score + 0.2)

    return round(score, 4), True


def run_relevance_filter(records, csv_path):
    """Run semantic relevance filtering on all downloaded documents."""
    print(f"\n[MODULE 7] Semantic relevance filtering...")

    invalid_docs = []

    with open(csv_path, "r", encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f)
        fieldnames = reader.fieldnames or []
        for row in reader:
            records[row["celex"]] = row

    for celex, record in records.items():
        if record.get("download_status") != "success":
            continue

        xml_path = os.path.join(XML_DIR, f"{celex}.html")
        if not os.path.exists(xml_path):
            continue

        xml_text = extract_full_text(xml_path)
        score, is_valid = check_relevance(xml_text)

        records[celex]["document_relevance_score"] = str(score)

        if not is_valid:
            records[celex]["txt_export_status"] = "invalid"
            invalid_docs.append({
                "celex": celex,
                "title": record.get("title", ""),
                "relevance_score": score,
                "reason": "Low China-trade relevance"
            })

    with open(csv_path, "w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames, extrasaction='ignore')
        writer.writeheader()
        for c in sorted(records.keys()):
            writer.writerow(records[c])

    invalid_path = os.path.join(CSV_DIR, "invalid_document.csv")
    with open(invalid_path, "w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=["celex", "title", "relevance_score", "reason"])
        w.writeheader()
        for d in invalid_docs:
            w.writerow(d)

    print(f"[RELEVANCE] Invalid (low relevance): {len(invalid_docs)}")
    return records


# ============================================================
# MODULE 8: AUTO CLASSIFICATION
# ============================================================

def auto_classify(records, csv_path):
    """Auto-classify documents by topic, institution, doc type."""
    print(f"\n[MODULE 8] Auto-classification...")

    with open(csv_path, "r", encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f)
        fieldnames = reader.fieldnames or []
        for row in reader:
            records[row["celex"]] = row

    for celex, record in records.items():
        xml_path = os.path.join(XML_DIR, f"{celex}.html")

        text = record.get("title", "")
        if os.path.exists(xml_path):
            xml_text = extract_full_text(xml_path)
            text = record.get("title", "") + " " + xml_text[:5000]

        records[celex]["topic_label"] = classify_by_keywords(text, TOPIC_KEYWORDS)

        if not records[celex].get("institution_label"):
            records[celex]["institution_label"] = classify_by_map(
                record.get("institution", ""), INSTITUTION_MAP)

        if not records[celex].get("doc_type_label"):
            records[celex]["doc_type_label"] = classify_by_map(
                record.get("doc_type", ""), DOCTYPE_MAP)

        pub_date = record.get("publish_date", "")
        if pub_date and len(pub_date) >= 4:
            y = pub_date[:4]
            if y.isdigit() and YEAR_START <= int(y) <= YEAR_END:
                records[celex]["year_label"] = y

    with open(csv_path, "w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames, extrasaction='ignore')
        writer.writeheader()
        for c in sorted(records.keys()):
            writer.writerow(records[c])

    # Topic distribution
    topic_counts = defaultdict(int)
    for r in records.values():
        if r.get("download_status") == "success":
            topic_counts[r.get("topic_label", "其他")] += 1
    print(f"[CLASSIFY] Topic distribution: {dict(topic_counts)}")

    # Save "其他" for review
    other_docs = [
        {"celex": k, "title": v.get("title", ""), "topic_label": v.get("topic_label", "")}
        for k, v in records.items()
        if v.get("topic_label") == "其他" and v.get("download_status") == "success"
    ]
    if other_docs:
        other_path = os.path.join(CSV_DIR, "other_topic_review.csv")
        with open(other_path, "w", encoding="utf-8-sig", newline="") as f:
            w = csv.DictWriter(f, fieldnames=["celex", "title", "topic_label"])
            w.writeheader()
            for d in other_docs:
                w.writerow(d)
        print(f"[CLASSIFY] {len(other_docs)} 'other' topic docs → {other_path}")

    return records


# ============================================================
# MODULE 9: TXT EXPORT
# ============================================================

def export_txt_files(records, csv_path):
    """Export one TXT file per CELEX with main + amendments merged text."""
    print(f"\n[MODULE 9] Exporting TXT files...")

    success = 0
    failed = 0

    # Parent-child mapping
    parent_of = defaultdict(list)
    for celex, record in records.items():
        parent = record.get("parent_celex", "")
        if parent:
            parent_of[parent].append(celex)

    for celex, record in records.items():
        if record.get("parent_celex", ""):
            continue  # Amendment docs merged into parent

        try:
            score = float(record.get("document_relevance_score", "1"))
        except ValueError:
            score = 1.0

        if score < 0.3:
            records[celex]["txt_export_status"] = "invalid_low_score"
            continue

        xml_path = os.path.join(XML_DIR, f"{celex}.html")
        if not os.path.exists(xml_path):
            records[celex]["txt_export_status"] = "failed"
            failed += 1
            continue

        combined = [extract_full_text(xml_path)]

        for child_celex in parent_of.get(celex, []):
            child_xml = os.path.join(XML_DIR, f"{child_celex}.xml")
            if os.path.exists(child_xml):
                child_text = extract_full_text(child_xml)
                if child_text:
                    combined.append(f"\n--- Amendment/Corrigendum: {child_celex} ---\n")
                    combined.append(child_text)

        full_text = "\n".join(combined)
        full_text = re.sub(r'\n{3,}', '\n\n', full_text).strip()

        if len(full_text) < TEXT_MIN_CHARS:
            records[celex]["txt_export_status"] = "too_short"
            failed += 1
            continue

        txt_path = os.path.join(TXT_DIR, f"{celex}_full_text.txt")
        try:
            with open(txt_path, "w", encoding="utf-8") as f:
                f.write(full_text)
            records[celex]["txt_export_status"] = "success"
            success += 1
        except Exception:
            records[celex]["txt_export_status"] = "failed"
            failed += 1

    # Save updated CSV
    with open(csv_path, "r", encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f)
        fieldnames = reader.fieldnames or []

    with open(csv_path, "w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames, extrasaction='ignore')
        writer.writeheader()
        for c in sorted(records.keys()):
            writer.writerow(records[c])

    print(f"[TXT] Export: {success} success, {failed} failed")
    return records, success, failed


# ============================================================
# MODULE 10: FINAL SUMMARY & AUDIT
# ============================================================

def generate_summary(records):
    """Generate final summary and missing items check."""
    print(f"\n{'='*60}")
    print(f"  FINAL SUMMARY")
    print(f"{'='*60}")

    total_sparql = len(records)
    total_downloaded = sum(1 for r in records.values() if r.get("download_status") == "success")
    total_txt = sum(1 for r in records.values() if r.get("txt_export_status") == "success")
    total_failed = sum(1 for r in records.values() if r.get("download_status") == "failed")
    total_corrupted = sum(1 for r in records.values() if r.get("download_status") == "corrupted")

    # Missing items
    missing = []
    for celex, r in records.items():
        if r.get("download_status") != "success":
            missing.append({"celex": celex, "title": r.get("title", ""),
                          "status": r.get("download_status", "")})

    missing_path = os.path.join(CSV_DIR, "missing_celex.csv")
    with open(missing_path, "w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=["celex", "title", "status"])
        w.writeheader()
        for m in missing:
            w.writerow(m)

    # Topic distribution
    topic_dist = defaultdict(int)
    for r in records.values():
        if r.get("download_status") == "success":
            topic_dist[r.get("topic_label", "unclassified")] += 1

    # Year distribution
    year_dist = defaultdict(int)
    for r in records.values():
        y = r.get("year_label", "")
        if y:
            year_dist[y] += 1

    # Institution distribution
    inst_dist = defaultdict(int)
    for r in records.values():
        inst_dist[r.get("institution_label", "其他")] += 1

    print(f"  SPARQL total records:   {total_sparql}")
    print(f"  XML downloaded (OK):    {total_downloaded}")
    print(f"  TXT exported (OK):      {total_txt}")
    print(f"  Download failed:        {total_failed}")
    print(f"  Corrupted:              {total_corrupted}")
    print(f"  Missing/Incomplete:     {len(missing)}")
    print(f"{'='*60}")
    print(f"  Year distribution:")
    for year in sorted(year_dist.keys()):
        print(f"    {year}: {year_dist[year]}")
    print(f"{'='*60}")
    print(f"  Topic distribution:")
    for topic, count in sorted(topic_dist.items(), key=lambda x: -x[1]):
        print(f"    {topic}: {count}")
    print(f"{'='*60}")
    print(f"  Institution distribution:")
    for inst, count in sorted(inst_dist.items(), key=lambda x: -x[1]):
        print(f"    {inst}: {count}")
    print(f"{'='*60}")
    print(f"  Missing list: {missing_path}")
    print(f"{'='*60}")

    summary = {
        "sparql_total": total_sparql,
        "downloaded_xml": total_downloaded,
        "exported_txt": total_txt,
        "failed_download": total_failed,
        "corrupted": total_corrupted,
        "missing": len(missing),
        "topic_distribution": dict(topic_dist),
        "year_distribution": dict(year_dist),
        "institution_distribution": dict(inst_dist),
    }

    summary_path = os.path.join(CSV_DIR, "collection_summary.json")
    with open(summary_path, "w", encoding="utf-8") as f:
        json.dump(summary, f, indent=2, default=str, ensure_ascii=False)
    print(f"\n[SUMMARY] JSON: {summary_path}")

    return summary


# ============================================================
# MAIN PIPELINE
# ============================================================

def main():
    """Main pipeline: SPARQL → Download → Amendments → Parse → Verify → Export."""
    print("=" * 60)
    print("  EU-China Trade Policy English Corpus Collection System")
    print(f"  Started: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("=" * 60)

    ensure_dirs()
    csv_path = os.path.join(CSV_DIR, "eu_china_celex_list.csv")

    # STEP 1: SPARQL Retrieval
    print("\n" + "=" * 60)
    print("  STEP 1/8: SPARQL RETRIEVAL")
    print("=" * 60)
    records = run_sparql_collection(csv_path)

    if not records:
        print("[ERROR] No records from SPARQL. Cannot continue.")
        return

    # STEP 2: Amendment Collection (skipped - slow, returns 0 results for this dataset)
    print("\n" + "=" * 60)
    print("  STEP 2/8: AMENDMENT COLLECTION (SKIPPED)")
    print("=" * 60)

    # STEP 3: Batch Download
    print("\n" + "=" * 60)
    print("  STEP 3/8: BATCH HTML FULL-TEXT DOWNLOAD")
    print("=" * 60)
    records = batch_download(csv_path)

    # STEP 4: Semantic Relevance
    print("\n" + "=" * 60)
    print("  STEP 4/8: SEMANTIC RELEVANCE FILTERING")
    print("=" * 60)
    records = run_relevance_filter(records, csv_path)

    # STEP 5: Auto Classification
    print("\n" + "=" * 60)
    print("  STEP 5/8: AUTO CLASSIFICATION")
    print("=" * 60)
    records = auto_classify(records, csv_path)

    # STEP 6: XML Structure Verification (Layer 1)
    print("\n" + "=" * 60)
    print("  STEP 6/8: XML STRUCTURE VERIFICATION")
    print("=" * 60)
    verify_xml_structure(records)

    # STEP 7: XML-PDF Similarity (Layer 2, sampled)
    print("\n" + "=" * 60)
    print("  STEP 7/8: XML-PDF SIMILARITY (SAMPLED)")
    print("=" * 60)
    verify_xml_pdf_similarity(records, sample_size=15)

    # STEP 8: TXT Export
    print("\n" + "=" * 60)
    print("  STEP 8/8: TXT EXPORT")
    print("=" * 60)
    records, txt_ok, txt_fail = export_txt_files(records, csv_path)

    # Final Summary
    summary = generate_summary(records)

    print(f"\n[COMPLETE] Finished: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    return summary


if __name__ == "__main__":
    main()
