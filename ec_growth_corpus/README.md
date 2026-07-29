# EC Growth Corpus — EU-China Trade Policy Crawler

POLIANNA methodology (PMC, 2026) crawler for collecting EU-China trade policy documents from DG GROW and DG TRADE websites.

## Sources
- DG GROW: https://single-market-economy.ec.europa.eu/
- DG TRADE: https://policy.trade.ec.europa.eu/
- Time range: 2017–2026

## Quick Start

```bash
pip install -r requirements.txt
python run_full.py
```

## Features
- **Dual-keyword filter**: trade keywords + China overlay (strict mode)
- **Checkpoint/resume**: interrupt-safe — re-run to continue from where it left off
- **Auto-classification**: topic (9 categories), year, institution, document type
- **DSM TDM Art.3-4 compliant**: academic research exemption

## Output
- `txt/` — one `.txt` per document (YYYYMMDD_docID.txt)
- `csv/` — `ec_china_corpus.csv` with all metadata + full text
- `progress.json` — auto-saved checkpoint (deleted on completion)

## Configuration
- Keywords: `config/keywords.py`
- Settings: `config/settings.py` (delay, timeout, output paths)

## Expected Results
~200–400 China-related trade policy documents from ~3,600 sitemap URLs.
