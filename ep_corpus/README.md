# EP Corpus — EU Delegation to China Trade News Crawler

Target: https://www.eeas.europa.eu/delegations/china_en
Purpose: Academic corpus linguistics research, EU-China economic relations

## Quick Start
```bash
pip install requests beautifulsoup4 pdfplumber python-dateutil
python main.py
```

## Features
- Sitemap-based URL discovery (985 China delegation pages)
- Multi-word trade phrase filter (must contain "trade policy", "supply chain", etc.)
- Black/white keyword filter for non-economic content (88% rejection rate)
- 6 metadata fields + 4 auto-classification dimensions
- TXT (YYYYMMDD_docID.txt) + CSV incremental append
- Checkpoint/resume via progress.json
- PII sanitization, PDF text extraction
- 5s delay, single-thread, academic UA

## Expected Output
~30-50 high-quality EU-China trade policy documents from the EEAS delegation site.
