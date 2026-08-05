# -*- coding: utf-8 -*-
r"""
欧盟对华贸易英文语料合并预处理脚本
功能：遍历 D:\项目流程\txt汇总\ 下所有 .txt，解析元数据 -> 去重 -> 按年份排序 -> 输出总 CSV
适配：BERT 批评性话语分析（CDA）建模
"""

import pandas as pd
import os
import glob
import re

# ============================================================
# 1. 路径配置
# ============================================================
TXT_DIR = r"D:\项目流程\txt汇总"
OUTPUT_PATH = r"D:\项目流程\all_corpus_total.csv"

# 四个建模核心字段
CORE_FIELDS = ["text", "year", "source", "theme"]


# ============================================================
# 2. txt 文件解析函数（兼容两种格式）
# ============================================================
def extract_year_from_filename(filename: str) -> str:
    """
    从文件名提取合理年份（2010-2030 范围），滑动窗口扫描避免 CELEX 编号误判。
    例: 32023R2120_full_text.txt -> 2023（非 3202，滑动窗口覆盖重叠部分）
         01997R0088-20200918.txt  -> 2020
    """
    # 滑动窗口：逐位检查每 4 个连续字符
    for i in range(len(filename) - 3):
        chunk = filename[i:i + 4]
        if chunk.isdigit():
            y = int(chunk)
            if 2017 <= y <= 2026:
                return str(y)
    # 无 2017-2026 范围内的年份，返回空字符串
    return ''


def parse_txt_file(filepath: str) -> dict | None:
    """
    解析单个 txt 文件，提取 text / year / source / theme。

    格式 A（标准，2654 个）：元数据头 + 分隔线 + 正文
      Title: ...
      Source: ...
      Topic (EN): ...
      Year: ...
      ======================================================================
      [正文]

    格式 B（full_text，221 个）：直接以正文开头，无元数据头
      从文件名推断年份（如 32023R2120_full_text.txt -> 2023）
    """
    try:
        with open(filepath, 'r', encoding='utf-8') as f:
            content = f.read()
    except Exception:
        return None

    basename = os.path.basename(filepath)

    # ---- 尝试匹配 ===== 分隔线 ----
    # 兼容行首无换行（分隔线在文件第一行的情况）
    sep_match = re.search(r'(?:^|\n)={30,}\s*\n', content)

    if sep_match:
        # ========== 格式 A：标准结构 ==========
        header = content[:sep_match.start()].strip()
        body = content[sep_match.end():].strip()

        if not body:
            return None

        # 解析头部字段（格式：Key: Value）
        meta = {}
        for line in header.split('\n'):
            line = line.strip()
            if ':' in line:
                key, value = line.split(':', 1)
                meta[key.strip()] = value.strip()

        # 字段映射：Source -> source, Topic (EN) -> theme, Year -> year
        source = meta.get('Source', '')
        theme = meta.get('Topic (EN)', '')
        year = meta.get('Year', '')

        # 补漏：如果头部缺 Year，从文件名推断（如 01997R0088-20200918.txt）
        if not year:
            year = extract_year_from_filename(basename)

    else:
        # ========== 格式 B：full_text，无元数据头 ==========
        body = content.strip()
        if not body:
            return None

        source = ''
        theme = ''
        year = extract_year_from_filename(basename)

    return {
        'text': body,
        'year': year,
        'source': source,
        'theme': theme,
    }


# ============================================================
# 3. 主流程
# ============================================================
def main():
    # ---- 3.1 遍历所有 txt 文件 ----
    txt_files = glob.glob(os.path.join(TXT_DIR, "*.txt"))
    print(f"在 {TXT_DIR} 下发现 {len(txt_files)} 个 txt 文件\n")

    if not txt_files:
        print("未发现任何 txt 文件，脚本终止。")
        return

    # ---- 3.2 逐个解析，收集记录 ----
    records = []
    ok_standard = 0    # 标准格式，有完整元数据
    ok_fulltext = 0    # full_text 格式，无元数据
    skipped = 0        # 解析失败或正文为空

    for i, filepath in enumerate(txt_files):
        if (i + 1) % 500 == 0:
            print(f"  解析进度: {i+1:,} / {len(txt_files):,}")

        record = parse_txt_file(filepath)
        if record is None or not record['text'].strip():
            skipped += 1
            continue

        records.append(record)
        if record['source']:
            ok_standard += 1
        else:
            ok_fulltext += 1

    print(f"解析完成: 标准格式 {ok_standard:,} / full_text {ok_fulltext:,} / 跳过 {skipped}\n")

    if not records:
        print("无有效数据，退出。")
        return

    # ---- 3.3 构建 DataFrame ----
    df = pd.DataFrame(records, columns=CORE_FIELDS)

    # 所有字段填充：NaN -> 空字符串，去首尾空格
    for field in CORE_FIELDS:
        df[field] = df[field].fillna("").astype(str).str.strip()

    # 剔除 text 为空的行（最后一道保险）
    before = len(df)
    df = df[df["text"] != ""]
    if len(df) < before:
        print(f"剔除 text 为空: {before - len(df)} 行")

    print(f"合并后总行数（去重前）: {len(df):,}")

    # ---- 3.4 按 text 字段去重 ----
    before_dedup = len(df)
    df = df.drop_duplicates(subset=["text"], keep="first")
    removed = before_dedup - len(df)
    print(f"去重后总行数: {len(df):,}（剔除 {removed:,} 条重复，{removed / before_dedup * 100:.1f}%）")

    # ---- 3.5 按 year 升序排序，年份未知沉底 ----
    df["_year_num"] = pd.to_numeric(df["year"], errors="coerce")
    df = df.sort_values(by="_year_num", ascending=True, na_position="last")
    df = df.drop(columns=["_year_num"])
    df = df.reset_index(drop=True)

    # ---- 3.6 输出 ----
    df.to_csv(OUTPUT_PATH, encoding="utf-8-sig", index=False)

    # ---- 3.7 汇总报告 ----
    valid_year = df.loc[df["year"] != "", "year"]
    valid_source = df.loc[df["source"] != "", "source"]
    valid_theme = df.loc[df["theme"] != "", "theme"]

    print(f"\n{'=' * 60}")
    print(f"输出文件: {OUTPUT_PATH}")
    print(f"总行数: {len(df):,}")
    print(f"字段: {CORE_FIELDS}")
    if len(valid_year) > 0:
        print(f"年份范围: {valid_year.min()} ~ {valid_year.max()}")
    print(f"有来源信息: {len(valid_source):,} / {len(df):,}（{len(valid_source)/len(df)*100:.1f}%）")
    print(f"有议题标签: {len(valid_theme):,} / {len(df):,}（{len(valid_theme)/len(df)*100:.1f}%）")

    # 年份分布
    print(f"\n年份分布:")
    year_counts = df["year"].replace("", "未知").value_counts().sort_index()
    for y, c in year_counts.items():
        bar = "#" * max(1, c // max(1, year_counts.max() // 40))
        print(f"  {y:>6s}: {c:>6,}  {bar}")

    print(f"\n全部完成。")


if __name__ == "__main__":
    main()
