"""
Logging module — writes to both file and console.
Includes PII sanitization for log output.
"""

import logging
import os
import re
import sys

from config.settings import LOG_FILE, LOG_FORMAT, LOG_DATE_FORMAT, PII_PATTERNS


def sanitize_for_log(text: str) -> str:
    """Strip PII (emails, phone numbers) from log messages."""
    if not text:
        return text
    result = text
    for pattern_name, pattern in PII_PATTERNS.items():
        result = re.sub(pattern, "[REDACTED]", result)
    return result


class PIISafeFormatter(logging.Formatter):
    """Logging formatter that auto-sanitizes PII from messages."""

    def format(self, record):
        record.msg = sanitize_for_log(str(record.msg))
        return super().format(record)


def setup_logger(
    name: str = "ec_corpus",
    level: int = logging.INFO,
) -> logging.Logger:
    """Configure and return a logger with file + console handlers."""

    # Ensure log directory exists
    log_dir = os.path.dirname(LOG_FILE)
    os.makedirs(log_dir, exist_ok=True)

    logger = logging.getLogger(name)
    logger.setLevel(level)
    logger.handlers.clear()

    # File handler
    fh = logging.FileHandler(LOG_FILE, encoding="utf-8")
    fh.setLevel(level)
    fh.setFormatter(PIISafeFormatter(LOG_FORMAT, LOG_DATE_FORMAT))
    logger.addHandler(fh)

    # Console handler
    ch = logging.StreamHandler(sys.stdout)
    ch.setLevel(level)
    ch.setFormatter(PIISafeFormatter("%(levelname)-8s | %(message)s"))
    logger.addHandler(ch)

    return logger


# Module-level logger
log = setup_logger()
