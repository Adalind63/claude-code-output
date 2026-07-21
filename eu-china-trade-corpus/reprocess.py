"""Re-process already downloaded HTML files: relevance filter + classify + verify + export TXT"""
import os, sys
sys.path.insert(0, os.path.dirname(__file__))
from eu_china_corpus_collector import *

BASE_DIR = os.path.join("D:", os.sep, "项目流程", "eu_corpus")
CSV_DIR = os.path.join(BASE_DIR, "csv")
csv_path = os.path.join(CSV_DIR, "eu_china_celex_list.csv")

# Load records from CSV
records = {}
with open(csv_path, "r", encoding="utf-8-sig", newline="") as f:
    reader = csv.DictReader(f)
    fieldnames = reader.fieldnames or []
    for row in reader:
        records[row["celex"]] = row

print(f"Loaded {len(records)} records")

# Only process success records but reset their relevance/txt status
for celex in records:
    if records[celex]["download_status"] == "success":
        records[celex]["document_relevance_score"] = ""
        records[celex]["txt_export_status"] = ""

# STEP 4: Relevance
print("\n=== STEP 4: Relevance Filter ===")
records = run_relevance_filter(records, csv_path)

# STEP 5: Classification
print("\n=== STEP 5: Auto Classification ===")
records = auto_classify(records, csv_path)

# STEP 6: Structure check
print("\n=== STEP 6: XML Structure ===")
verify_xml_structure(records)

# STEP 7: PDF Similarity (sampled)
print("\n=== STEP 7: PDF Similarity ===")
verify_xml_pdf_similarity(records, sample_size=15)

# STEP 8: TXT Export
print("\n=== STEP 8: TXT Export ===")
records, txt_ok, txt_fail = export_txt_files(records, csv_path)

# Final summary
summary = generate_summary(records)
summary_path = os.path.join(CSV_DIR, "collection_summary.json")
with open(summary_path, "w", encoding="utf-8") as f:
    json.dump(summary, f, indent=2, default=str, ensure_ascii=False)

print(f"\n[DONE] Summary: {summary_path}")
