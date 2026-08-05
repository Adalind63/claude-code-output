# -*- coding: utf-8 -*-
r"""
欧盟对华贸易英文语料合并预处理脚本
功能：递归遍历 D:\项目流程\ 下所有 CSV，标准化列名 -> 去重 -> 按年份排序 -> 输出总文件
适配：BERT 批评性话语分析（CDA）建模
"""

import pandas as pd
import os
import glob

# ============================================================
# 1. 路径配置
# ============================================================
INPUT_DIR = r"D:\项目流程"
OUTPUT_PATH = r"D:\项目流程\all_corpus_total.csv"

# ============================================================
# 2. 列名标准化映射表（原始列名 -> 统一字段）
#    覆盖所有已发现的 CSV 列名变体
# ============================================================
COLUMN_MAP = {
    # ---- 正文列 ----
    "完整正文": "text",
    "完整正文文本": "text",
    "全文": "text",
    "全文 (Full Text)": "text",
    "正文": "text",
    "内容": "text",
    "全文内容": "text",
    "sentence": "text",
    "text": "text",
    "content": "text",
    "body": "text",
    "article": "text",
    # ---- 年份列 ----
    "年份": "year",
    "年份 (Year)": "year",
    "发布年份": "year",
    "年": "year",
    "year": "year",
    "date": "year",
    "pub_year": "year",
    # ---- 来源列 ----
    "发布机构": "source",
    "发布机构_EN (Institution EN)": "source",
    "发布机构_ZH (Institution ZH)": "source",
    "来源": "source",
    "机构": "source",
    "source": "source",
    "publisher": "source",
    "org": "source",
    "organization": "source",
    "website": "source",
    # ---- 议题列 ----
    "议题领域": "theme",
    "主题_EN (Topic EN)": "theme",
    "主题_ZH (Topic ZH)": "theme",
    "议题": "theme",
    "领域": "theme",
    "主题": "theme",
    "theme": "theme",
    "topic": "theme",
    "subject": "theme",
    "category": "theme",
}

# 四个建模核心字段
CORE_FIELDS = ["text", "year", "source", "theme"]

# 排除的非语料文件名（日志/元数据/备份/质检结果）
EXCLUDE_NAMES = {
    "clean_log.csv",
    "metadata.csv",
    "search_results.csv",
    "abnormal_document_list.csv",
    "invalid_document.csv",
    "missing_celex.csv",
    "other_topic_review.csv",
    "xml_structure_check.csv",
    "all_corpus_total.csv",
}


def is_excluded(file_path: str) -> bool:
    """根据文件名或路径特征排除非语料文件。"""
    name = os.path.basename(file_path)
    if name in EXCLUDE_NAMES:
        return True
    # 排除备份文件
    if "backup" in name.lower():
        return True
    # 排除 _ds_store 等系统文件
    if name.startswith(".") or name.startswith("~"):
        return True
    return False


def standardize_columns(df: pd.DataFrame, file_name: str):
    """
    将 DataFrame 列名按 COLUMN_MAP 映射到统一字段。
    同一统一字段出现多次时，取第一个非空值合并。
    返回标准化后的 DataFrame，若无法匹配则返回 None。
    """
    # 去除列名首尾空格及不可见字符
    df.columns = [str(c).strip() for c in df.columns]

    # 当前文件能匹配的 原始列名 -> 统一字段
    file_map = {}
    for col in df.columns:
        if col in COLUMN_MAP:
            file_map[col] = COLUMN_MAP[col]

    if not file_map:
        print(f"  [警告] {file_name} 列名无法匹配映射表，跳过。")
        print(f"         实际列名: {list(df.columns)}")
        return None

    # 重命名
    df = df.rename(columns=file_map)

    # 处理合并后可能出现的重复统一字段（同名列）
    for field in CORE_FIELDS:
        cols = [c for c in df.columns if c == field]
        if len(cols) > 1:
            first_col = cols[0]
            for dup_col in cols[1:]:
                df[first_col] = df[first_col].fillna(df[dup_col])
            df = df.drop(columns=cols[1:])

    return df


def main():
    # ============================================================
    # 3. 递归遍历所有子目录下的 CSV 文件
    # ============================================================
    csv_files = glob.glob(os.path.join(INPUT_DIR, "**", "*.csv"), recursive=True)
    print(f"递归搜索发现 {len(csv_files)} 个 CSV 文件")

    # 过滤非语料文件
    corpus_files = [f for f in csv_files if not is_excluded(f)]
    excluded = len(csv_files) - len(corpus_files)
    if excluded > 0:
        print(f"排除 {excluded} 个非语料文件（日志/元数据/备份）\n")
    else:
        print("")

    if not corpus_files:
        print("未发现语料 CSV 文件，脚本终止。")
        return

    print(f"待处理语料文件 {len(corpus_files)} 个：")
    for f in corpus_files:
        print(f"  - {os.path.relpath(f, INPUT_DIR)}")
    print("")

    # ============================================================
    # 4. 逐个读取并标准化列名
    # ============================================================
    dfs = []
    skipped = 0
    total_rows_in = 0

    for file_path in corpus_files:
        rel_path = os.path.relpath(file_path, INPUT_DIR)
        print(f"处理: {rel_path}")

        # 多编码尝试读取
        df = None
        for enc in ["utf-8-sig", "utf-8", "gbk", "gb18030", "latin-1"]:
            try:
                df = pd.read_csv(file_path, encoding=enc)
                print(f"  编码: {enc}, 行数: {len(df):,}, 列数: {len(df.columns)}")
                break
            except (UnicodeDecodeError, UnicodeError):
                continue
            except Exception as e:
                print(f"  读取异常 ({enc}): {e}")
                continue

        if df is None or len(df) == 0:
            print(f"  [跳过] 无法读取或文件为空")
            skipped += 1
            continue

        # 列名标准化
        df = standardize_columns(df, rel_path)
        if df is None:
            skipped += 1
            continue

        # ============================================================
        # 5. 只保留四个核心字段，缺失的补空字符串
        # ============================================================
        for field in CORE_FIELDS:
            if field not in df.columns:
                df[field] = ""

        df = df[CORE_FIELDS].copy()

        # NaN -> 空字符串，去首尾空格
        for field in CORE_FIELDS:
            df[field] = df[field].fillna("").astype(str).str.strip()

        # 剔除 text 为空的行
        before = len(df)
        df = df[df["text"] != ""]
        empty_dropped = before - len(df)
        if empty_dropped > 0:
            print(f"  剔除 text 为空: {empty_dropped} 行")

        if len(df) == 0:
            print(f"  [跳过] 处理后无有效数据")
            skipped += 1
            continue

        total_rows_in += len(df)
        dfs.append(df)
        print(f"  OK 有效行数: {len(df):,}")

    if not dfs:
        print(f"\n所有文件均无效，已跳过 {skipped} 个，无数据可合并。")
        return

    print(f"\n{'='*60}")
    print(f"共读取 {len(dfs)} 个文件，跳过了 {skipped} 个")

    # ============================================================
    # 6. pd.concat 纵向合并所有表格，重置索引
    # ============================================================
    merged = pd.concat(dfs, axis=0, ignore_index=True)
    print(f"合并后总行数（去重前）: {len(merged):,}")

    # ============================================================
    # 7. 按 text 字段去重，剔除重复政策文档
    # ============================================================
    before_dedup = len(merged)
    merged = merged.drop_duplicates(subset=["text"], keep="first")
    dedup_removed = before_dedup - len(merged)
    print(f"去重后总行数: {len(merged):,} （剔除 {dedup_removed:,} 条重复，{dedup_removed/before_dedup*100:.1f}%）")

    # ============================================================
    # 8. 按 year 升序排序，年份未知的沉底
    # ============================================================
    merged["_year_num"] = pd.to_numeric(merged["year"], errors="coerce")
    merged = merged.sort_values(by="_year_num", ascending=True, na_position="last")
    merged = merged.drop(columns=["_year_num"])
    merged = merged.reset_index(drop=True)

    # ============================================================
    # 9. 输出总文件
    # ============================================================
    merged.to_csv(OUTPUT_PATH, encoding="utf-8-sig", index=False)
    print(f"\n{'='*60}")
    print(f"输出文件: {OUTPUT_PATH}")
    print(f"总行数: {len(merged):,}")
    print(f"字段: {CORE_FIELDS}")

    # 统计摘要
    valid_year = merged.loc[merged["year"] != "", "year"]
    if len(valid_year) > 0:
        print(f"年份范围: {valid_year.min()} ~ {valid_year.max()}")
    valid_source = merged.loc[merged["source"] != "", "source"]
    print(f"有来源信息的行: {len(valid_source):,} / {len(merged):,}")
    print(f"唯一来源数: {valid_source.nunique()}")
    valid_theme = merged.loc[merged["theme"] != "", "theme"]
    print(f"有议题标签的行: {len(valid_theme):,} / {len(merged):,}")

    # 每年行数分布
    print(f"\n年份分布:")
    year_counts = merged["year"].replace("", "未知").value_counts().sort_index()
    for y, c in year_counts.items():
        bar = "#" * max(1, c // max(1, year_counts.max() // 40))
        print(f"  {y:>6s}: {c:>8,}  {bar}")

    print(f"\n全部完成。")


if __name__ == "__main__":
    main()
