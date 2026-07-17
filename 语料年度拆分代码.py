#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
CSV语料按年份拆分脚本
功能：读取多个CSV语料文件，按"年份 (Year)"字段分组，
     剔除脏数据后，各年份数据存入独立CSV文件。
"""

import os
import sys
import csv
from collections import defaultdict

# 提高CSV字段大小限制（语料全文较长，默认131072字节不够）
csv.field_size_limit(sys.maxsize)

# ============================================================
# 【用户配置区 —— 修改这里的路径即可】
# ============================================================

# 输入文件列表（支持单个或多个CSV文件）
INPUT_FILES = [
    r"C:\Users\admin\Desktop\项目流程\eu_corpus\csv\eu_china_docs.csv",
    r"C:\Users\admin\Desktop\项目流程\欧盟理事会\csv\consilium_docs.csv",
]

# 输出根目录（会在该目录下自动创建 output_year 子文件夹）
OUTPUT_ROOT = r"C:\Users\admin\Desktop\项目流程\语料预处理"

# 年份列名（请根据实际CSV表头填写）
YEAR_COLUMN = "年份 (Year)"

# 年份有效范围（闭区间）
YEAR_MIN = 2017
YEAR_MAX = 2026

# 输出文件名格式：corpus_YYYY.csv
OUTPUT_FILENAME_TEMPLATE = "corpus_{year}.csv"

# CSV输出编码
OUTPUT_ENCODING = "utf-8-sig"

# ============================================================
# 以下为脚本逻辑，一般无需修改
# ============================================================


def validate_year(value):
    """
    校验年份字段是否合法。
    返回 (is_valid: bool, year_int: int or None)
    合法条件：
      1. 非空
      2. 可解析为4位整数年份
      3. 在 YEAR_MIN ~ YEAR_MAX 范围内
    """
    if value is None:
        return False, None

    # 去除首尾空白
    raw = str(value).strip()

    if not raw:
        return False, None

    # 尝试提取整数（容忍小数形式如 "2020.0"）
    try:
        # 先尝试直接转整数
        year_int = int(raw)
    except ValueError:
        # 尝试转为浮点数再转整数
        try:
            year_int = int(float(raw))
        except (ValueError, OverflowError):
            return False, None

    # 检查是否在合理年份范围内
    if year_int < YEAR_MIN or year_int > YEAR_MAX:
        return False, None

    return True, year_int


def read_csv_safe(filepath, encoding="utf-8-sig"):
    """
    安全读取CSV文件，自动尝试多种编码。
    返回 (headers: list, rows: list of dict) 或 (None, None)
    """
    encodings_to_try = [encoding, "utf-8", "gbk", "gb2312", "latin-1"]

    for enc in encodings_to_try:
        try:
            with open(filepath, "r", encoding=enc, newline="") as f:
                reader = csv.DictReader(f)
                headers = reader.fieldnames
                if headers is None:
                    print(f"  [WARN] 文件 {filepath} 表头为空，跳过")
                    return None, None
                rows = [row for row in reader]
            print(f"  [OK] 成功读取，编码={enc}，共 {len(rows)} 行数据")
            return headers, rows
        except UnicodeDecodeError:
            continue
        except Exception as e:
            print(f"  [FAIL] 读取失败 ({enc}): {e}")
            continue

    print(f"  [FAIL] 所有编码尝试均失败，跳过文件: {filepath}")
    return None, None


def main():
    print("=" * 60)
    print("CSV语料按年份拆分工具")
    print("=" * 60)

    # ---- 1. 准备输出目录 ----
    output_dir = os.path.join(OUTPUT_ROOT, "output_year")
    os.makedirs(output_dir, exist_ok=True)
    print(f"\n[INFO] 输出目录: {output_dir}")

    # ---- 2. 读取所有输入文件 ----
    all_rows = []
    unified_headers = []        # 合并去重后的所有列名（保持首个出现的顺序）
    seen_columns = set()
    total_read = 0

    print(f"\n[INFO] 开始读取 {len(INPUT_FILES)} 个输入文件...")
    for filepath in INPUT_FILES:
        print(f"\n  读取: {filepath}")
        if not os.path.exists(filepath):
            print(f"  [FAIL] 文件不存在，跳过: {filepath}")
            continue

        headers, rows = read_csv_safe(filepath)
        if headers is None:
            continue

        # 检查年份列是否存在
        if YEAR_COLUMN not in headers:
            print(f"  [FAIL] 文件中未找到年份列 '{YEAR_COLUMN}'，可用列: {headers}")
            continue

        # 记录新增的列名
        new_cols = [h for h in headers if h not in seen_columns]
        if new_cols:
            print(f"  [INFO] 新增列: {new_cols}")
        unified_headers.extend(new_cols)
        seen_columns.update(new_cols)

        all_rows.extend(rows)
        total_read += len(rows)

    if not unified_headers:
        print("\n[FAIL] 错误：没有成功读取任何文件，退出。")
        sys.exit(1)

    print(f"\n[INFO] 统一表头共 {len(unified_headers)} 列: {unified_headers}")
    print(f"[INFO] 总计读入: {total_read} 行")

    # ---- 3. 按年份分组 & 过滤脏数据 ----
    year_groups = defaultdict(list)  # {year_int: [row_dict, ...]}
    invalid_count = 0
    invalid_reasons = defaultdict(int)

    for idx, row in enumerate(all_rows):
        raw_value = row.get(YEAR_COLUMN, "")

        if raw_value is None or str(raw_value).strip() == "":
            invalid_count += 1
            invalid_reasons["空值"] += 1
            continue

        raw_str = str(raw_value).strip()

        # 检查是否可解析为有效年份
        is_valid, year_int = validate_year(raw_value)

        if not is_valid:
            invalid_count += 1
            # 进一步分类无效原因
            try:
                int(float(raw_str))
                # 能解析但超出范围
                invalid_reasons[f"年份超出范围({YEAR_MIN}-{YEAR_MAX})"] += 1
            except (ValueError, OverflowError):
                invalid_reasons["非数字值"] += 1
            continue

        year_groups[year_int].append(row)

    # ---- 4. 输出日志：各年份数据条数 ----
    valid_total = sum(len(rows) for rows in year_groups.values())
    print(f"\n[INFO] 有效数据: {valid_total} 行")
    print(f"[INFO] 过滤无效数据: {invalid_count} 行")
    if invalid_reasons:
        print(f"  无效原因分布:")
        for reason, count in sorted(invalid_reasons.items(), key=lambda x: -x[1]):
            print(f"    - {reason}: {count} 行")

    print(f"\n[INFO] 各年份数据分布:")
    sorted_years = sorted(year_groups.keys())
    for y in sorted_years:
        print(f"    {y}年: {len(year_groups[y])} 行")

    if not sorted_years:
        print("\n[FAIL] 没有有效数据可写入，退出。")
        sys.exit(0)

    # ---- 5. 写入各年份CSV ----
    print(f"\n[INFO] 开始写入各年份文件...")
    written_total = 0

    for year in sorted_years:
        rows = year_groups[year]
        filename = OUTPUT_FILENAME_TEMPLATE.format(year=year)
        filepath = os.path.join(output_dir, filename)

        try:
            with open(filepath, "w", encoding=OUTPUT_ENCODING, newline="") as f:
                writer = csv.DictWriter(f, fieldnames=unified_headers, extrasaction='ignore')
                writer.writeheader()
                writer.writerows(rows)
            print(f"  [OK] {filename}: {len(rows)} 行")
            written_total += len(rows)
        except Exception as e:
            print(f"  [FAIL] 写入 {filename} 失败: {e}")

    # ---- 6. 最终汇总 ----
    print(f"\n{'=' * 60}")
    print(f"[DONE] 拆分完成！")
    print(f"  输入文件数: {len(INPUT_FILES)}")
    print(f"  总读入行数: {total_read}")
    print(f"  有效行数:   {valid_total}")
    print(f"  过滤行数:   {invalid_count}")
    print(f"  写入行数:   {written_total}")
    print(f"  生成文件数: {len(sorted_years)}")
    print(f"  输出目录:   {output_dir}")
    print(f"{'=' * 60}")


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\n[WARN] 用户中断")
        sys.exit(1)
    except Exception as e:
        print(f"\n[FAIL] 未预期的错误: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
