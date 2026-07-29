"""
Auto-classification module — improved context-aware version.
Assigns Year, Topic, Institution, Document Type labels.
"""

import re
from typing import List, Optional

from config.keywords import (
    TIER2_SECTOR,
    TOPIC_CATEGORIES,
    INSTITUTION_MAP,
    DOC_TYPE_MAP,
)
from config.settings import VALID_YEARS


# Strong signal keywords per topic (highly indicative, weighted 3x)
STRONG_SIGNALS = {
    "semiconductor": ["semiconductor", "chip manufacturing", "microelectronics",
                       "wafer", "foundry", "integrated circuit", "advanced chip"],
    "new_energy": ["solar panel", "photovoltaic", "wind turbine", "electric vehicle",
                    "lithium battery", "energy storage", "renewable energy",
                    "clean energy", "green hydrogen", "electrolyser", "rare earth",
                    "critical mineral", "solar cell"],
    "steel": ["steel overcapacity", "steel safeguard", "steel tariff",
              "steel import", "steel sector", "aluminium", "ferrous",
              "metal industry", "steel production", "non-ferrous"],
    "market_access": ["market access", "public procurement", "government procurement",
                       "forced technology transfer", "localization requirement",
                       "joint venture requirement", "reciprocal access",
                       "market openness", "licensing regime"],
    "digital_trade": ["digital trade", "cross-border data flow", "data localisation",
                       "digital sovereignty", "e-commerce", "electronic commerce",
                       "Digital Services Act", "Digital Markets Act",
                       "artificial intelligence", "5G", "6G", "cybersecurity",
                       "cloud computing", "digital platform", "data governance"],
    "subsidy_investigation": ["anti-subsidy", "countervailing duty", "CVD",
                               "foreign subsidy regulation", "FSR",
                               "foreign subsidies instrument", "subsidy probe",
                               "distortive subsidy", "state aid",
                               "subsidy investigation"],
    "tariffs": ["anti-dumping duty", "trade defence instrument", "tariff rate",
                "safeguard measure", "trade remedy", "dumping investigation",
                "definitive duty", "provisional duty", "import duty",
                "countervailing", "MFN tariff"],
    "investment_review": ["FDI screening", "investment screening",
                           "foreign direct investment", "inward investment",
                           "export control", "dual-use", "strategic asset",
                           "critical infrastructure", "investment review"],
    "intellectual_property": ["intellectual property right", "IPR enforcement",
                               "standard essential patent", "trade secret",
                               "counterfeit", "IP theft", "geographical indication",
                               "patent protection", "technology leakage",
                               "know-how protection", "IP protection"],
}


def extract_year(date_str: str) -> Optional[int]:
    """Extract year from date string."""
    if not date_str:
        return None
    match = re.search(r'(\d{4})[-/]\d{2}[-/]\d{2}', str(date_str))
    if match:
        year = int(match.group(1))
        if year in VALID_YEARS:
            return year
    match = re.search(r'(\d{4})', str(date_str))
    if match:
        year = int(match.group(1))
        if year in VALID_YEARS:
            return year
    return None


def classify_topic(title: str, body_text: str) -> str:
    """
    Improved topic classification:
    1. Strong signals weighted 3x
    2. Title matches weighted 2x
    3. Generic keywords weighted 1x
    4. Minimum score threshold to avoid false positives
    5. Returns '其他' if no clear topic emerges
    """
    if not body_text:
        return "其他"

    body_lower = body_text.lower()
    title_lower = title.lower()
    scores = {}

    for category in TOPIC_CATEGORIES:
        all_keywords = TIER2_SECTOR.get(category, [])
        strong_keywords = STRONG_SIGNALS.get(category, [])

        score = 0

        for kw in all_keywords:
            kw_lower = kw.lower()
            # Check body
            body_count = body_lower.count(kw_lower)
            if body_count > 0:
                weight = 3 if kw in strong_keywords else 1
                # Cap per-keyword contribution
                score += min(body_count, 5) * weight

            # Title bonus (2x)
            if kw_lower in title_lower:
                score += 2 * (3 if kw in strong_keywords else 1)

        if score > 0:
            scores[category] = score

    if not scores:
        return "其他"

    # Require minimum signal strength
    best_category = max(scores, key=scores.get)
    best_score = scores[best_category]

    # Require at least 5 points for classification (avoids single-keyword false matches)
    # 5 = one strong keyword + one regular mention, or 2 strong body mentions
    if best_score < 5:
        return "其他"

    return TOPIC_CATEGORIES.get(best_category, "其他")


def classify_institution(text: str) -> str:
    """Identify issuing institution."""
    if not text:
        return "其他"
    for patterns, label in INSTITUTION_MAP:
        for pat in patterns:
            if pat.lower() in text.lower():
                return label
    return "其他"


def classify_doc_type(text: str, url: str = "") -> str:
    """
    Identify document type. Checks first 800 chars + URL clues.
    """
    if not text and not url:
        return "其他"

    header = (text[:800] if text else "").lower()
    url_lower = (url or "").lower()

    # URL-based clues
    if "/news/" in url_lower or "-news-" in url_lower:
        return "声明"

    for patterns, label in DOC_TYPE_MAP:
        for pat in patterns:
            if pat.lower() in header:
                return label

    return "其他"


def classify_document(
    title: str,
    full_text: str,
    date_str: str,
    raw_institution: str = "",
    raw_doc_type: str = "",
    url: str = "",
) -> dict:
    """Full document classification."""
    year = extract_year(date_str)
    year_str = str(year) if year else "未知"

    topic = classify_topic(title, full_text)

    classify_text = f"{title}\n{full_text[:2000]}"
    institution = classify_institution(raw_institution) if raw_institution else classify_institution(classify_text)
    doc_type = classify_doc_type(raw_doc_type, url) if raw_doc_type else classify_doc_type(full_text, url)

    return {
        "year": year_str,
        "topic": topic,
        "institution": institution,
        "doc_type": doc_type,
    }
