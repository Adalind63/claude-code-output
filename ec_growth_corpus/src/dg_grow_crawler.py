"""
DG GROW / Single Market Economy + DG TRADE website crawler.
POLIANNA methodology (PMC, 2026) — sitemap traversal + keyword filtering.

Target sites:
  - https://single-market-economy.ec.europa.eu/ (DG GROW)
  - https://policy.trade.ec.europa.eu/ (DG TRADE)
  - https://ec.europa.eu/commission/presscorner/ (Press releases)

DSM TDM Art.3-4 Academic Exemption compliant.
"""

import hashlib
import logging
import os
import re
import tempfile
import time
import warnings
from datetime import datetime
from typing import Any, Dict, List, Optional, Set, Tuple
from urllib.parse import urljoin, urlparse
from xml.etree import ElementTree as ET

import requests
from bs4 import BeautifulSoup

# Suppress pdfplumber/pdfminer noise
warnings.filterwarnings("ignore", category=UserWarning, module="pdfplumber")
logging.getLogger("pdfplumber").setLevel(logging.ERROR)
logging.getLogger("pdfminer").setLevel(logging.ERROR)

from config.settings import (
    USER_AGENT,
    REQUEST_DELAY,
    REQUEST_TIMEOUT,
    MAX_RETRIES,
    RETRY_BACKOFF,
    VALID_YEARS,
    DOWNLOAD_PDFS,
    MAX_PDF_SIZE,
)
from config.keywords import TIER1_GENERAL, TIER2_FLAT, CHINA_OVERLAY
from src.logger import log
from src.sanitizer import sanitize_pii, sanitize_title


# ============================================================================
# SESSION & HTTP
# ============================================================================

def _get_session() -> requests.Session:
    s = requests.Session()
    s.headers.update({
        "User-Agent": USER_AGENT,
        "Accept": "text/html,application/xhtml+xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.9",
    })
    return s


def _fetch(url: str, session: requests.Session) -> Optional[requests.Response]:
    """Fetch URL with retry. Returns Response or None."""
    for attempt in range(MAX_RETRIES):
        try:
            resp = session.get(url, timeout=REQUEST_TIMEOUT, allow_redirects=True)
            if resp.status_code == 200:
                return resp
            elif resp.status_code in (404, 410):
                return None
            elif resp.status_code == 429:
                wait = RETRY_BACKOFF * (2 ** attempt)
                log.debug("HTTP 429 for %s, waiting %ds", url[:80], wait)
                time.sleep(wait)
            else:
                log.debug("HTTP %d for %s", resp.status_code, url[:80])
        except Exception as e:
            log.debug("Fetch error %s: %s", url[:80], str(e)[:80])

        if attempt < MAX_RETRIES - 1:
            time.sleep(RETRY_BACKOFF * (attempt + 1))
    return None


# ============================================================================
# SITEMAP PARSING
# ============================================================================

SITEMAP_URLS = [
    "https://single-market-economy.ec.europa.eu/sitemap.xml",
    "https://policy.trade.ec.europa.eu/sitemap.xml",
]

SEED_URLS = [
    # DG TRADE — China
    "https://policy.trade.ec.europa.eu/eu-trade-relationships-country-and-region/countries-and-regions/china_en",
    # DG TRADE — Trade Defence
    "https://policy.trade.ec.europa.eu/enforcement-and-protection/trade-defence_en",
    # DG GROW — Industry
    "https://single-market-economy.ec.europa.eu/industry/strategy_en",
    "https://single-market-economy.ec.europa.eu/industry/industrial-alliances_en",
    "https://single-market-economy.ec.europa.eu/single-market_en",
    # Press Corner — China
    "https://ec.europa.eu/commission/presscorner/api/search?keyword=china+trade&language=en",
]


def parse_sitemap(url: str, session: requests.Session) -> List[Dict[str, str]]:
    """
    Parse a sitemap XML. Returns list of {url, lastmod} dicts.
    Handles sitemap indexes (nested sitemaps) 1 level deep.
    """
    entries = []
    resp = _fetch(url, session)
    if not resp:
        log.warning("Failed to fetch sitemap: %s", url)
        return entries

    try:
        root = ET.fromstring(resp.content)
        ns_match = re.match(r'\{(.*?)\}', root.tag)
        ns = ns_match.group(1) if ns_match else ""

        if ns:
            # Check for sitemap index
            sitemap_tags = root.findall(f"{{{ns}}}sitemap")
            if sitemap_tags:
                log.info("  Sitemap index: %d sub-sitemaps", len(sitemap_tags))
                for sm in sitemap_tags:
                    loc = sm.find(f"{{{ns}}}loc")
                    if loc is not None and loc.text:
                        time.sleep(REQUEST_DELAY)
                        sub = parse_sitemap(loc.text.strip(), session)
                        entries.extend(sub)
                return entries

            # Regular sitemap
            for url_tag in root.findall(f"{{{ns}}}url"):
                loc = url_tag.find(f"{{{ns}}}loc")
                lastmod = url_tag.find(f"{{{ns}}}lastmod")
                if loc is not None and loc.text:
                    entries.append({
                        "url": loc.text.strip(),
                        "lastmod": lastmod.text.strip() if lastmod is not None and lastmod.text else "",
                    })
    except ET.ParseError as e:
        log.warning("XML parse error for %s: %s", url, str(e)[:100])

    return entries


# ============================================================================
# HTML CONTENT EXTRACTION
# ============================================================================

def _extract_title(soup: BeautifulSoup) -> str:
    """Extract page title from EU Commission HTML."""
    # Priority: h1 > meta og:title > <title>
    h1 = soup.find("h1")
    if h1:
        return h1.get_text(strip=True)

    og = soup.find("meta", property="og:title")
    if og and og.get("content"):
        return og["content"].strip()

    if soup.title:
        t = soup.title.get_text(strip=True)
        t = re.sub(r'\s*[-|]\s*(European Commission|EU|European Union).*$', '', t)
        return t

    return ""


def _extract_date(soup: BeautifulSoup, url: str) -> str:
    """Extract publication date."""
    # Meta tags
    for meta in soup.find_all("meta"):
        name = (meta.get("name") or "").lower()
        content = meta.get("content", "")
        if name in ("dc.date", "dcterms.issued", "publication-date", "date"):
            m = re.match(r'(\d{4})-(\d{2})-(\d{2})', content)
            if m:
                return content[:10]

    # Time elements
    for time_tag in soup.find_all("time"):
        dt = time_tag.get("datetime", "")
        m = re.match(r'(\d{4})-(\d{2})-(\d{2})', str(dt))
        if m:
            return dt[:10]

    # EU news URL pattern: .../news/title-YYYY-MM-DD_en
    m = re.search(r'(\d{4})-(\d{2})-(\d{2})', url)
    if m:
        return m.group(0)

    return ""


def _extract_institution(soup: BeautifulSoup, url: str) -> str:
    """Identify issuing institution."""
    # Meta
    for meta in soup.find_all("meta"):
        name = (meta.get("name") or "").lower()
        content = meta.get("content", "")
        if name in ("dc.creator", "dcterms.creator", "author"):
            return content.strip()

    # URL-based
    u = url.lower()
    if "trade.ec.europa.eu" in u:
        return "Directorate-General for Trade (DG TRADE)"
    if "single-market-economy.ec.europa.eu" in u:
        return "Directorate-General for Internal Market, Industry, Entrepreneurship and SMEs (DG GROW)"
    if "commission.europa.eu" in u:
        return "European Commission"
    if "europarl.europa.eu" in u:
        return "European Parliament"

    return "European Commission"


def _extract_html_text(soup: BeautifulSoup) -> str:
    """Extract clean text from EU Commission HTML."""
    # Remove non-content
    for tag in soup(["script", "style", "nav", "footer", "noscript", "iframe", "svg",
                      "header", "button", "input", "select"]):
        tag.decompose()

    # Remove EU site chrome
    chrome_selectors = [
        ".ecl-site-header", ".ecl-site-footer", ".ecl-breadcrumb",
        ".cookie-consent", ".ecl-mega-menu", ".ecl-language-list",
        ".skip-link", "#skip-link", ".region-header", ".region-footer",
        ".site-header", ".site-footer", ".ecl-message",
    ]
    for sel in chrome_selectors:
        for el in soup.select(sel):
            el.decompose()

    # Get main content
    main = (soup.find("main") or soup.find(id="main-content") or
            soup.find(class_="main-content") or soup.find(role="main"))
    content = main if main else (soup.body if soup.body else soup)

    text = content.get_text(separator="\n", strip=True)
    text = re.sub(r'\n\s*\n\s*\n+', '\n\n', text)
    text = re.sub(r'[ \t]{2,}', ' ', text)
    return text.strip()


def _find_pdf_links(soup: BeautifulSoup, base_url: str) -> List[str]:
    """Extract PDF download links."""
    pdfs = set()
    for a in soup.find_all("a", href=True):
        href = a["href"].strip()
        lower = href.lower()

        # Direct PDF links
        if lower.endswith(".pdf"):
            pdfs.add(urljoin(base_url, href))
        # EU document download links
        elif "/document/download/" in lower and "filename=" in lower:
            pdfs.add(urljoin(base_url, href))
        # PDF language selector
        elif "_en.pdf" in lower or "en.pdf" in lower:
            pdfs.add(urljoin(base_url, href))

    return list(pdfs)


# ============================================================================
# PDF TEXT EXTRACTION
# ============================================================================

def extract_pdf_text(pdf_url: str, session: requests.Session) -> Optional[str]:
    """Download PDF and extract text."""
    if not DOWNLOAD_PDFS:
        return None

    resp = _fetch(pdf_url, session)
    if not resp or len(resp.content) < 100:
        return None

    content = resp.content
    if len(content) > MAX_PDF_SIZE:
        log.debug("  PDF too large (%d MB)", len(content) // (1024*1024))
        return None

    if not content[:5] == b'%PDF-':
        return None

    # Save to temp and extract
    try:
        fd, tmp = tempfile.mkstemp(suffix=".pdf")
        with os.fdopen(fd, "wb") as f:
            f.write(content)

        text = ""
        # Try pdfplumber
        try:
            import pdfplumber
            with pdfplumber.open(tmp) as pdf:
                for page in pdf.pages:
                    pt = page.extract_text()
                    if pt:
                        text += pt + "\n"
        except ImportError:
            pass

        # Fallback PyPDF2
        if not text.strip():
            try:
                from PyPDF2 import PdfReader
                reader = PdfReader(tmp)
                for page in reader.pages:
                    pt = page.extract_text()
                    if pt:
                        text += pt + "\n"
            except ImportError:
                pass

        os.unlink(tmp)
        return text if text.strip() else None
    except Exception as e:
        log.debug("  PDF extract error: %s", str(e)[:80])
        return None


# ============================================================================
# KEYWORD FILTERING
# ============================================================================

def check_keywords(text: str, title: str = "") -> bool:
    """
    POLIANNA dual-filter (strict mode):
    Phase 1: Tier1 general OR Tier2 sector keywords in text
    Phase 2: China overlay keywords — must appear in SUBSTANTIVE content,
             not just navigation. Title = stronger signal.

    Rules for China keyword validation:
    1. If China keyword appears in title → strong match, pass
    2. If 3+ distinct China mentions in body → pass
    3. If China keyword appears near (<500 chars) a Tier2 sector keyword → pass
    4. Otherwise → reject (likely nav/footer noise)
    """
    if not text or len(text) < 150:
        return False

    t = text.lower()

    # Phase 1: Tier check
    tier_ok = any(kw.lower() in t for kw in TIER1_GENERAL)
    if not tier_ok:
        tier_ok = any(kw.lower() in t for kw in TIER2_FLAT)
    if not tier_ok:
        return False

    # Phase 2: China overlay (strict)
    # Rule 1: China in title
    title_lower = (title or "").lower()
    if any(kw.lower() in title_lower for kw in CHINA_OVERLAY):
        return True

    # Rule 2: Count distinct China mentions in body
    china_mentions = 0
    for kw in CHINA_OVERLAY:
        count = t.count(kw.lower())
        if count > 0:
            china_mentions += count
    if china_mentions >= 3:
        return True

    # Rule 3: China keyword near a Tier2 sector keyword (<500 char window)
    for china_kw in CHINA_OVERLAY:
        china_kw_lower = china_kw.lower()
        china_pos = t.find(china_kw_lower)
        if china_pos >= 0:
            for sector_kw in TIER2_FLAT:
                sector_pos = t.find(sector_kw.lower())
                if sector_pos >= 0 and abs(china_pos - sector_pos) < 500:
                    return True

    # Rule 4: Page is specifically about China (URL/source signals)
    # (This is handled in crawl_page by checking URL patterns)

    return False


# ============================================================================
# PAGE CRAWLING
# ============================================================================

def generate_doc_id(url: str, title: str, date_str: str) -> str:
    raw = f"{url}|{title}|{date_str}"
    return hashlib.sha256(raw.encode()).hexdigest()[:12]


def crawl_page(url: str, session: requests.Session) -> Optional[Dict[str, Any]]:
    """
    Crawl a single page:
    1. Fetch HTML
    2. Extract metadata + text
    3. Download PDFs if any
    4. Apply keyword filter
    Returns document dict or None.
    """
    resp = _fetch(url, session)
    if not resp:
        return None

    ct = resp.headers.get("Content-Type", "").lower()

    # Handle direct PDF
    if "application/pdf" in ct or url.lower().endswith(".pdf"):
        pdf_text = extract_pdf_text(url, session)
        if pdf_text and check_keywords(pdf_text):
            return {
                "title": url.split("/")[-1].replace(".pdf", "").replace("_en", ""),
                "date": _extract_date(None, url),
                "authors": "European Commission",
                "full_text": sanitize_pii(pdf_text),
                "url": url,
                "source": "dg_grow_pdf",
            }
        return None

    if "text/html" not in ct:
        return None

    # Parse HTML
    try:
        soup = BeautifulSoup(resp.content, "lxml")
    except Exception:
        soup = BeautifulSoup(resp.content, "html.parser")

    title = _extract_title(soup)
    date_str = _extract_date(soup, url)
    institution = _extract_institution(soup, url)
    html_text = _extract_html_text(soup)

    # Year filter
    if date_str:
        ym = re.search(r'(\d{4})', date_str)
        if ym and int(ym.group(1)) not in VALID_YEARS:
            log.debug("  Year %s out of range, skip", ym.group(1))
            return None

    # PDF extraction
    pdf_text = ""
    pdf_links = _find_pdf_links(soup, url)
    for pdf_url in pdf_links[:3]:  # Max 3 PDFs
        time.sleep(REQUEST_DELAY)
        extracted = extract_pdf_text(pdf_url, session)
        if extracted:
            pdf_text += "\n" + extracted

    # Combine and filter
    combined = f"{title}\n{html_text}\n{pdf_text}"
    if not check_keywords(combined, title=title):
        log.debug("  KW rejected: %s", title[:80])
        return None

    # Use PDF text if it's substantial
    full_text = pdf_text if len(pdf_text) > len(html_text) * 0.5 else html_text
    if pdf_text and html_text:
        full_text = f"{html_text}\n\n--- PDF ---\n\n{pdf_text}"

    return {
        "title": sanitize_title(title),
        "date": date_str,
        "authors": institution,
        "full_text": sanitize_pii(full_text),
        "url": resp.url,  # Final URL after redirects
        "source": "dg_grow",
    }


# ============================================================================
# MAIN CRAWL ORCHESTRATION
# ============================================================================

def crawl_sitemaps(
    year_filter: Optional[int] = None,
    max_pages: int = 2000,
) -> List[Dict[str, Any]]:
    """Main entry: crawl all sitemap URLs."""
    session = _get_session()
    all_docs = []
    seen: Set[str] = set()
    crawled = 0

    # Collect URLs from all sitemaps
    all_urls: List[Dict[str, str]] = []
    for sitemap_url in SITEMAP_URLS:
        log.info("Parsing sitemap: %s", sitemap_url)
        entries = parse_sitemap(sitemap_url, session)
        log.info("  Got %d URLs", len(entries))
        all_urls.extend(entries)
        time.sleep(REQUEST_DELAY)

    # Deduplicate by URL
    unique = []
    seen_tmp = set()
    for e in all_urls:
        u = e["url"]
        if u not in seen_tmp:
            seen_tmp.add(u)
            unique.append(e)

    log.info("Total unique sitemap URLs: %d", len(unique))

    # Crawl
    for i, entry in enumerate(unique):
        if len(all_docs) >= max_pages:
            break

        url = entry["url"]
        lastmod = entry["lastmod"]

        if url in seen:
            continue
        seen.add(url)
        crawled += 1

        # Year filter from lastmod
        if year_filter and lastmod:
            m = re.search(r'(\d{4})', lastmod)
            if m and int(m.group(1)) != year_filter:
                continue

        if crawled % 100 == 0:
            log.info("  Progress: %d/%d crawled, %d matched",
                     crawled, len(unique), len(all_docs))

        doc = crawl_page(url, session)
        if doc:
            doc["doc_id"] = generate_doc_id(url, doc["title"], doc["date"])
            all_docs.append(doc)
            log.info("  ✓ [%d] %s", len(all_docs), doc["title"][:100])

        time.sleep(REQUEST_DELAY)

    log.info("Sitemap crawl done: %d pages, %d matched", crawled, len(all_docs))
    return all_docs


def crawl_seeds() -> List[Dict[str, Any]]:
    """Crawl seed URLs + 1 level of internal links."""
    session = _get_session()
    docs = []
    seen: Set[str] = set()

    log.info("Crawling %d seed URLs...", len(SEED_URLS))

    for seed_url in SEED_URLS:
        resp = _fetch(seed_url, session)
        if not resp:
            continue

        # Crawl seed page itself
        doc = crawl_page(seed_url, session)
        if doc:
            doc["doc_id"] = generate_doc_id(seed_url, doc["title"], doc["date"])
            docs.append(doc)
            log.info("  ✓ Seed: %s", doc["title"][:100])

        time.sleep(REQUEST_DELAY)

        # Extract internal links
        try:
            soup = BeautifulSoup(resp.content, "lxml")
        except Exception:
            soup = BeautifulSoup(resp.content, "html.parser")

        base_domain = urlparse(seed_url).netloc
        internal = set()
        for a in soup.find_all("a", href=True):
            href = a["href"].strip()
            if href.startswith("#") or href.startswith("javascript:"):
                continue
            full = urljoin(seed_url, href)
            p = urlparse(full)
            if p.netloc in (base_domain, "ec.europa.eu", "commission.europa.eu"):
                internal.add(full)

        log.info("  Found %d internal links", len(internal))

        # Crawl internal links (limited)
        for j, link in enumerate(sorted(internal)[:30]):
            if link in seen:
                continue
            seen.add(link)

            doc = crawl_page(link, session)
            if doc:
                doc["doc_id"] = generate_doc_id(link, doc["title"], doc["date"])
                docs.append(doc)
                log.info("    ✓ Link: %s", doc["title"][:80])

            time.sleep(REQUEST_DELAY)

    log.info("Seed crawl done: %d documents", len(docs))
    return docs


def crawl_news_pages(
    max_pages: int = 20,
) -> List[Dict[str, Any]]:
    """Crawl news listing pages with pagination."""
    session = _get_session()
    docs = []
    seen: Set[str] = set()

    log.info("Crawling news pages...")

    for page_num in range(max_pages):
        url = f"https://single-market-economy.ec.europa.eu/news_en"
        if page_num > 0:
            url += f"?page={page_num}"

        resp = _fetch(url, session)
        if not resp:
            break

        try:
            soup = BeautifulSoup(resp.content, "lxml")
        except Exception:
            soup = BeautifulSoup(resp.content, "html.parser")

        # Find article links
        article_links = set()
        for a in soup.select("article a[href], .listing-item a[href], .views-row a[href]"):
            href = a.get("href", "")
            full = urljoin(resp.url, href)
            # Only keep news detail pages
            if "/news/" in full and full not in seen:
                article_links.add(full)

        if not article_links:
            log.info("  No more articles at page %d", page_num)
            break

        log.info("  Page %d: %d articles", page_num, len(article_links))

        for link in sorted(article_links):
            if link in seen:
                continue
            seen.add(link)

            doc = crawl_page(link, session)
            if doc:
                doc["doc_id"] = generate_doc_id(link, doc["title"], doc["date"])
                docs.append(doc)
                log.info("    ✓ News: %s", doc["title"][:80])

            time.sleep(REQUEST_DELAY)

    log.info("News crawl done: %d matched documents", len(docs))
    return docs
