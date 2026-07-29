"""
Full production crawl — DG GROW + DG TRADE
2017-2026 timeframe, POLIANNA methodology, DSM TDM compliant.

Supports checkpoint/resume: if interrupted (Ctrl+C, network loss, power failure),
re-run the same command to continue from where it left off.
Progress is saved to progress.json after each batch.
"""
import json
import logging
import os
import re
import sys
import time
import warnings
from datetime import datetime

# Suppress pdfplumber FontBBox warnings
warnings.filterwarnings("ignore", message=".*FontBBox.*")
logging.getLogger("pdfplumber").setLevel(logging.ERROR)
logging.getLogger("pdfminer").setLevel(logging.ERROR)

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from src.dg_grow_crawler import (
    _get_session, _fetch, crawl_page, generate_doc_id,
    check_keywords, parse_sitemap, SITEMAP_URLS,
)
from src.storage import save_documents, get_corpus_stats
from src.classifier import classify_document
from src.logger import log
from config.settings import BASE_DIR, TXT_DIR, CSV_DIR, LOG_DIR, REQUEST_DELAY, VALID_YEARS

# ============================================================================
# CHECKPOINT / RESUME
# ============================================================================

PROGRESS_FILE = os.path.join(BASE_DIR, "progress.json")
CHECKPOINT_INTERVAL_CRAWLED = 50    # Save progress every N crawled URLs (even if no match)
CHECKPOINT_INTERVAL_MATCHED = 20    # Save progress every N matched docs


def load_progress():
    """Load crawl progress from disk. Returns dict or None."""
    if not os.path.exists(PROGRESS_FILE):
        return None
    try:
        with open(PROGRESS_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
        # Convert crawled_urls list back to set
        data["crawled_urls"] = set(data.get("crawled_urls", []))
        log.info("📂 Loaded progress: %d URLs crawled, %d matched (phase %d)",
                 data.get("total_crawled", 0), data.get("matched_count", 0),
                 data.get("phase", 1))
        return data
    except (json.JSONDecodeError, KeyError, OSError) as e:
        log.warning("⚠️  Progress file corrupt, starting fresh: %s", str(e)[:80])
        return None


def save_progress(crawled_urls, matched_count, total_crawled, phase, news_done=False):
    """Save crawl progress to disk atomically."""
    data = {
        "crawled_urls": sorted(list(crawled_urls)),  # Sort for diff-friendly JSON
        "matched_count": matched_count,
        "total_crawled": total_crawled,
        "phase": phase,
        "news_done": news_done,
        "last_updated": datetime.now().isoformat(),
    }
    tmp = PROGRESS_FILE + ".tmp"
    try:
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        os.replace(tmp, PROGRESS_FILE)  # Atomic on Windows
    except OSError as e:
        log.warning("⚠️  Failed to save progress: %s", str(e)[:80])


# ============================================================================
# MAIN
# ============================================================================

def main():
    # Ensure dirs
    for d in [TXT_DIR, CSV_DIR, LOG_DIR]:
        os.makedirs(d, exist_ok=True)

    log.info("=" * 60)
    log.info("FULL PRODUCTION CRAWL — DG GROW + DG TRADE")
    log.info("Time range: %d-%d", VALID_YEARS[0], VALID_YEARS[-1])
    log.info("DSM TDM Art.3-4 Compliant | %.0fs delay | Single-thread", REQUEST_DELAY)
    log.info("Checkpoint: %s", PROGRESS_FILE)
    log.info("=" * 60)

    # Load previous progress (if any)
    progress = load_progress()
    crawled_urls = progress["crawled_urls"] if progress else set()
    total_matched = progress["matched_count"] if progress else 0
    total_crawled = progress["total_crawled"] if progress else 0
    start_phase = progress["phase"] if progress else 1

    if progress and total_crawled > 0:
        skipped_pct = total_crawled / max(total_crawled + 1, 1) * 100
        log.info("🔄 RESUME MODE: %d URLs already done, skipping...", total_crawled)

    session = _get_session()
    all_docs = []  # Only holds current unsaved batch
    save_batch_size = 20
    last_checkpoint_crawled = total_crawled  # For periodic checkpoint regardless of matches

    # ============================================================
    # PHASE 1: SITEMAP CRAWL
    # ============================================================
    if start_phase <= 1:
        log.info("\nPHASE 1: SITEMAP CRAWL")

        # Parse sitemaps (always — fast compared to crawling)
        all_entries = []
        for sm_url in SITEMAP_URLS:
            entries = parse_sitemap(sm_url, session)
            log.info("  %s: %d URLs", sm_url[:80], len(entries))
            all_entries.extend(entries)
            time.sleep(REQUEST_DELAY)

        # Deduplicate + year filter preparation
        seen_urls = set()
        unique_entries = []
        for e in all_entries:
            url = e["url"]
            if url not in seen_urls:
                seen_urls.add(url)
                year = None
                if e["lastmod"]:
                    ym = re.search(r'(\d{4})', e["lastmod"])
                    if ym:
                        year = int(ym.group(1))
                unique_entries.append({"url": url, "lastmod": e["lastmod"], "year": year})

        log.info("  Total unique: %d URLs", len(unique_entries))

        # Count already-crawled for display
        already_done = sum(1 for e in unique_entries if e["url"] in crawled_urls)
        if already_done > 0:
            log.info("  ⏭️  Already crawled: %d URLs (will skip)", already_done)
        log.info("")

        # Crawl loop
        for i, entry in enumerate(unique_entries):
            url = entry["url"]
            entry_year = entry["year"]

            # Skip already crawled
            if url in crawled_urls:
                continue

            # Skip if year is known and outside range
            if entry_year and entry_year not in VALID_YEARS:
                crawled_urls.add(url)
                continue

            total_crawled += 1

            # Progress every 50 pages
            if total_crawled % 50 == 0:
                stats = get_corpus_stats()
                remaining = len(unique_entries) - total_crawled + already_done
                log.info("  [%d/%d] crawled | matched: %d docs | remaining: ~%d | corpus: %d TXT, %d CSV",
                         total_crawled, len(unique_entries), total_matched,
                         remaining, stats["txt_count"], stats["csv_rows"])

            # Crawl the page
            doc = crawl_page(url, session)
            crawled_urls.add(url)

            if doc:
                doc["doc_id"] = generate_doc_id(url, doc["title"], doc["date"])
                all_docs.append(doc)
                total_matched += 1
                log.info("    ✓ [%d] %s", total_matched, doc["title"][:90])

                # Incremental save + checkpoint every N matched docs
                if len(all_docs) >= save_batch_size:
                    saved = save_documents(all_docs)
                    log.info("    💾 Saved batch: %d TXT, %d CSV",
                             saved["txt_count"], saved["csv_count"])
                    all_docs = []
                    save_progress(crawled_urls, total_matched, total_crawled, phase=1)
                    last_checkpoint_crawled = total_crawled

            # Periodic checkpoint even without matches (every 100 crawled)
            if total_crawled - last_checkpoint_crawled >= CHECKPOINT_INTERVAL_CRAWLED:
                # Flush any unsaved docs first
                if all_docs:
                    saved = save_documents(all_docs)
                    log.info("    💾 Periodic save: %d TXT, %d CSV",
                             saved["txt_count"], saved["csv_count"])
                    all_docs = []
                save_progress(crawled_urls, total_matched, total_crawled, phase=1)
                last_checkpoint_crawled = total_crawled

            # DSM TDM compliance
            time.sleep(REQUEST_DELAY)

        # Final save for remaining docs in Phase 1
        if all_docs:
            saved = save_documents(all_docs)
            log.info("  💾 Phase 1 final batch: %d TXT, %d CSV",
                     saved["txt_count"], saved["csv_count"])
            all_docs = []
        save_progress(crawled_urls, total_matched, total_crawled, phase=1)

        log.info("\nPhase 1 complete: %d docs from sitemap", total_matched)

    # ============================================================
    # PHASE 2: NEWS PAGES
    # ============================================================
    if start_phase <= 2:
        log.info("\nPHASE 2: NEWS PAGES")

        from src.dg_grow_crawler import crawl_news_pages

        # News phase tracking
        news_done = progress.get("news_done", False) if progress else False

        if news_done:
            log.info("  ⏭️  News phase already completed, skipping")
        else:
            news_docs = crawl_news_pages(max_pages=30)
            if news_docs:
                saved = save_documents(news_docs)
                total_matched += saved["csv_count"]
                log.info("  News: %d docs | Saved: %d TXT, %d CSV",
                         len(news_docs), saved["txt_count"], saved["csv_count"])

            # Mark news as done in progress
            save_progress(crawled_urls, total_matched, total_crawled, phase=2, news_done=True)

    # ============================================================
    # FINAL SUMMARY
    # ============================================================
    stats = get_corpus_stats()
    log.info("\n" + "=" * 60)
    log.info("FULL CRAWL COMPLETE")
    log.info("=" * 60)
    log.info("  Pages crawled:    %d", total_crawled)
    log.info("  Documents matched: %d", total_matched)
    log.info("  Corpus TXT files:  %d", stats["txt_count"])
    log.info("  Corpus CSV rows:   %d", stats["csv_rows"])
    log.info("  Output:            %s", TXT_DIR)
    log.info("  CSV:               %s", os.path.join(CSV_DIR, "ec_china_corpus.csv"))
    log.info("  Progress:          %s", PROGRESS_FILE)
    log.info("=" * 60)

    # Clean up progress file on successful completion
    if os.path.exists(PROGRESS_FILE):
        os.remove(PROGRESS_FILE)
        log.info("✓ Progress file removed — crawl complete.")


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        log.info("\n⏸️  Interrupted by user. Progress saved — re-run to continue.")
        sys.exit(130)
    except Exception as e:
        log.error("💥 Fatal error: %s", str(e))
        log.info("Progress saved — re-run to continue from checkpoint.")
        import traceback
        traceback.print_exc()
        sys.exit(1)
