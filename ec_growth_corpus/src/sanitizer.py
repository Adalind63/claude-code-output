"""
PII sanitization module.
Removes personally identifiable information from corpus text.
"""

import re
from config.settings import PII_PATTERNS


def sanitize_pii(text: str) -> str:
    """
    Remove PII from full text content.
    Returns sanitized text.
    """
    if not text:
        return text

    result = text

    # Email addresses → [EMAIL]
    result = re.sub(
        r'[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}',
        '[EMAIL]',
        result,
    )

    # Phone numbers (EU format) → [PHONE]
    result = re.sub(
        r'\+?[0-9]{1,4}[\s.-]?\(?[0-9]{1,4}\)?[\s.-]?[0-9]{2,4}[\s.-]?[0-9]{2,4}[\s.-]?[0-9]{2,4}',
        '[PHONE]',
        result,
    )

    # EU personal names in metadata (DG staff, contact persons)
    # Pattern: "Contact: Name Surname, email" → remove
    result = re.sub(
        r'(Contact|Responsible)\s*:\s*[A-Z][a-z]+(?:\s[A-Z][a-z]+)+',
        r'\1: [REDACTED]',
        result,
    )

    # Remove DG-specific personal office numbers
    result = re.sub(
        r'Office\s*:\s*[A-Z]+\d*[-/]\d+',
        'Office: [REDACTED]',
        result,
    )

    return result


def sanitize_title(title: str) -> str:
    """Light sanitization for titles — preserve meaning, remove personal info."""
    if not title:
        return title
    # Strip personal name prefixes like "Statement by Commissioner X on ..."
    # We keep the title but just redact personal names
    return sanitize_pii(title)
