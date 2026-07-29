"""
Project-level settings for EC GROWTH China Corpus Crawler.
DSM TDM Academic Exemption compliant configuration.
Reference: POLIANNA Dataset (PMC, 2026)
"""

import os
from datetime import datetime

# ============================================================================
# PATHS — Auto-created by main.py on startup
# ============================================================================
BASE_DIR = r"D:\项目流程\ec_growth_corpus"
TXT_DIR = os.path.join(BASE_DIR, "txt")
CSV_DIR = os.path.join(BASE_DIR, "csv")
LOG_DIR = os.path.join(BASE_DIR, "logs")

CSV_FILE = os.path.join(CSV_DIR, "ec_china_corpus.csv")

# ============================================================================
# EUR-Lex SPARQL Endpoint
# ============================================================================
SPARQL_ENDPOINT = "https://publications.europa.eu/webapi/rdf/sparql"

# CELLAR REST API base (for Formex XML retrieval)
CELLAR_API_BASE = "https://publications.europa.eu/webapi/cellar"

# EUR-Lex document portal (for constructing display URLs)
EURLEX_PORTAL = "https://eur-lex.europa.eu/legal-content/EN/TXT/?uri=celex:"

# ============================================================================
# DG GROW & Related Sitemap URLs
# ============================================================================
SITEMAP_URLS = [
    # DG GROW — Internal Market, Industry, Entrepreneurship
    "https://single-market-economy.ec.europa.eu/sitemap.xml",

    # DG TRADE — Trade policy
    "https://policy.trade.ec.europa.eu/sitemap.xml",

    # EU Trade news & events
    "https://policy.trade.ec.europa.eu/news_en/sitemap.xml",
]

# Direct search/browse pages for supplementary crawling
SEED_URLS = [
    # DG GROW — Industry policy sections
    "https://single-market-economy.ec.europa.eu/industry/strategy_en",
    "https://single-market-economy.ec.europa.eu/industry/industrial-alliances_en",
    "https://single-market-economy.ec.europa.eu/smes/sme-strategy_en",
    "https://single-market-economy.ec.europa.eu/single-market_en",

    # DG TRADE — Policy sections
    "https://policy.trade.ec.europa.eu/eu-trade-relationships-country-and-region/countries-and-regions/china_en",
    "https://policy.trade.ec.europa.eu/analysis-and-assessment/trade-defence_en",
    "https://policy.trade.ec.europa.eu/enforcement-and-protection/trade-defence_en",
    "https://policy.trade.ec.europa.eu/access-markets_en",

    # European Commission — China
    "https://commission.europa.eu/strategy-and-policy/priorities-2019-2024/europe-fit-digital-age/eu-china-relations_en",
]

# ============================================================================
# TIME RANGE
# ============================================================================
YEAR_START = 2017
YEAR_END = 2026
VALID_YEARS = list(range(YEAR_START, YEAR_END + 1))

# ============================================================================
# DSM TDM ACADEMIC COMPLIANCE SETTINGS
# ============================================================================

# Academic User-Agent (POLIANNA-compliant)
USER_AGENT = (
    "EC-Growth-Corpus-Bot/1.0 "
    "(Academic Research; Corpus Linguistics; "
    "mailto:researcher@university.edu; "
    "DSM-TDM-Art.3-4-Academic-Exemption)"
)

# Polite delay between requests (seconds)
# Reduced from 10s to 1s — EU Commission servers handle this rate without issue
REQUEST_DELAY = 1.0

# Single-thread only (no concurrent requests)
MAX_WORKERS = 1

# Request timeout (seconds)
REQUEST_TIMEOUT = 15

# Max retries on failure
MAX_RETRIES = 2

# Retry backoff factor (seconds)
RETRY_BACKOFF = 5.0

# ============================================================================
# PDF PROCESSING
# ============================================================================
# Download PDFs for text extraction? (Disabled for speed — HTML text is sufficient)
DOWNLOAD_PDFS = False

# Max PDF file size (bytes) — skip larger files
MAX_PDF_SIZE = 50 * 1024 * 1024  # 50 MB

# PDF text extraction: use pdfplumber if available, else fallback to PyPDF2
PDF_BACKEND = "pdfplumber"  # "pdfplumber" | "pypdf2"

# ============================================================================
# PII SANITIZATION
# ============================================================================
# Regex patterns for PII to redact from logs and stored text
PII_PATTERNS = {
    "email": r'[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}',
    "phone_eu": r'\+?[0-9]{1,4}[\s-]?[0-9]{2,4}[\s-][0-9]{3,4}[\s-][0-9]{3,4}',
    "phone_us": r'\+?1?[\s.-]?\(?[0-9]{3}\)?[\s.-]?[0-9]{3}[\s.-]?[0-9]{4}',
}

# ============================================================================
# CSV SCHEMA
# ============================================================================
CSV_COLUMNS = [
    "文档ID",
    "标题",
    "发布日期",
    "原文链接",
    "发布机构",
    "文件类型",
    "年份",
    "议题领域",
    "完整正文",
]

# ============================================================================
# LOGGING
# ============================================================================
LOG_FILE = os.path.join(
    LOG_DIR,
    f"crawl_{datetime.now().strftime('%Y%m%d_%H%M%S')}.log"
)

LOG_FORMAT = (
    "%(asctime)s | %(levelname)-8s | %(module)-20s | %(message)s"
)

LOG_DATE_FORMAT = "%Y-%m-%d %H:%M:%S"
