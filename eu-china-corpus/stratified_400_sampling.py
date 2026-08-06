# -*- coding: utf-8 -*-
"""
=============================================================================
固定样本量三层分层抽样 — 人工盲标校验模板生成器（400 条）
=============================================================================
功能概述：
  1. 读取 AI 标注语料库 auto_labeled_corpus.csv
  2. 三层分层（stance → year → source），固定抽取 400 条，随机种子 42
  3. 多重强制约束（按优先级）：
     a) 每个 (stance, year, source) 组合至少 1 条（维度全覆盖）
     b) 每个年份至少 5 条
     c) tough / cooperate / neutral 三类立场各至少 120 条（类别均衡）
     d) 核心来源机构（全量 ≥ 50 条）至少 10 条
     e) 总样本量 = 400
  4. 生成盲标模板：移除 AI stance 列，新增 sample_id + 空白 human_stance 列
  5. 打印抽样分布统计
  6. 输出 CSV：D:\\项目流程\\manual_check_400.csv（utf-8-sig，无行索引）

依赖：pip install pandas
=============================================================================
"""

import pandas as pd
import numpy as np
import os
from datetime import datetime

# =============================================================================
# 0. 全局配置
# =============================================================================

# --- 文件路径（Windows 绝对路径）---
INPUT_FILE = r"D:\项目流程\auto_labeled_corpus.csv"
OUTPUT_FILE = r"D:\项目流程\manual_check_400.csv"

# --- 抽样参数 ---
TOTAL_SAMPLES = 400             # 固定总抽样量
RANDOM_SEED = 42                # 随机种子，保证可复现
STANCE_MIN = 120                # 每类立场最少条数
YEAR_MIN = 5                    # 每年份最少条数
CORE_SOURCE_THRESHOLD = 50      # 核心来源判定阈值（全量样本数 ≥ 此值）
CORE_SOURCE_MIN = 10            # 核心来源最少条数

# --- CSV 参数 ---
INPUT_ENCODING = "utf-8-sig"
OUTPUT_ENCODING = "utf-8-sig"

# --- 字段映射 ---
COL_TEXT = "text"
COL_YEAR = "year"
COL_SOURCE = "source"
COL_THEME = "theme"
COL_STANCE = "stance"

# 三层分层字段（优先级：stance > year > source）
STRATIFY_COLS = [COL_STANCE, COL_YEAR, COL_SOURCE]


# =============================================================================
# 1. 数据加载与预处理
# =============================================================================

def load_and_clean(filepath: str) -> pd.DataFrame:
    """
    读取 CSV 并做基础清洗。

    清洗步骤：
      - 校验 text / year / source / theme / stance 五列是否存在
      - 丢弃分层关键列为空的记录
      - 将 year 转为整数、source 填充缺失值

    参数
    ----
    filepath : str
        输入 CSV 的绝对路径。

    返回
    ----
    pd.DataFrame
        清洗后的全量数据。
    """
    if not os.path.exists(filepath):
        raise FileNotFoundError(f"❌ 输入文件不存在：{filepath}")

    df = pd.read_csv(filepath, encoding=INPUT_ENCODING)
    print(f"✅ 已加载数据：{len(df)} 条记录，{len(df.columns)} 个字段")

    # 校验必需列
    required = [COL_TEXT, COL_YEAR, COL_SOURCE, COL_THEME, COL_STANCE]
    missing = [c for c in required if c not in df.columns]
    if missing:
        raise ValueError(f"❌ 缺少必需列：{missing}\n   实际列名：{list(df.columns)}")

    # 丢弃分层关键列为空的记录
    before = len(df)
    df = df.dropna(subset=[COL_STANCE, COL_YEAR])
    # source 可能为 NaN，填充为 "Unknown"
    df[COL_SOURCE] = df[COL_SOURCE].fillna("Unknown")
    after_dropna = len(df)
    if before > after_dropna:
        print(f"⚠️  已丢弃 {before - after_dropna} 条记录（stance 或 year 为空）")

    # year 统一转为整数（去除小数点）
    df[COL_YEAR] = df[COL_YEAR].astype(float).astype(int)

    # stance 和 source 统一为字符串
    df[COL_STANCE] = df[COL_STANCE].astype(str).str.strip()
    df[COL_SOURCE] = df[COL_SOURCE].astype(str).str.strip()

    if len(df) == 0:
        raise ValueError("❌ 清洗后无有效数据。")

    print(f"   清洗后：{len(df)} 条记录")
    return df


# =============================================================================
# 2. 构建分层结构 & 分析
# =============================================================================

def build_stratum_index(df: pd.DataFrame) -> dict:
    """
    按 (stance, year, source) 三层分组，构建分层索引。

    返回
    ----
    dict
        strata[(stance, year, source)] = {
            "indices": list[int],   # 原始 df 的行索引
            "count": int,           # 该层总样本数
        }
    """
    strata = {}
    for (stance, year, source), group in df.groupby(STRATIFY_COLS):
        key = (stance, year, source)
        strata[key] = {
            "indices": group.index.tolist(),
            "count": len(group),
        }
    return strata


def print_data_summary(df: pd.DataFrame, strata: dict) -> None:
    """打印全量数据摘要：各维度分布及分层单元概况。"""
    print("\n" + "=" * 60)
    print("  全量数据摘要")
    print("=" * 60)

    print(f"\n📦 总样本数：{len(df)}")
    print(f"📦 分层单元数（stance×year×source）：{len(strata)}")

    print(f"\n📊 各立场 (stance) 分布：")
    for v, c in df[COL_STANCE].value_counts().items():
        print(f"    {v:<15s} {c:>8d}")

    print(f"\n📊 各年份 (year) 分布：")
    for v, c in sorted(df[COL_YEAR].value_counts().items()):
        print(f"    {v:<10} {c:>8d}")

    print(f"\n📊 各来源 (source) 分布：")
    for v, c in df[COL_SOURCE].value_counts().items():
        print(f"    {v:<40s} {c:>8d}")

    # 标注核心来源
    core_sources = {
        src for src, cnt in df[COL_SOURCE].value_counts().items()
        if cnt >= CORE_SOURCE_THRESHOLD
    }
    print(f"\n📌 核心来源机构（全量 ≥ {CORE_SOURCE_THRESHOLD} 条）：{len(core_sources)} 个")
    for src in core_sources:
        print(f"    {src}")


# =============================================================================
# 3. 配额分配算法
# =============================================================================

def allocate_quotas(
    strata: dict,
    total: int = TOTAL_SAMPLES,
    stance_min: int = STANCE_MIN,
    year_min: int = YEAR_MIN,
    core_source_min: int = CORE_SOURCE_MIN,
) -> dict:
    """
    贪心配额分配算法：在满足所有约束的前提下，将 400 个名额分配到各分层单元。

    约束优先级（从高到低）：
      1. 每个 (stance, year, source) 至少 1 条 —— 维度全覆盖
      2. 每个年份至少 5 条
      3. 每类立场至少 120 条 —— 类别均衡
      4. 核心来源机构至少 10 条
      5. 总计恰好 400 条

    算法思路：
      - 第一步：每个分层单元分配 1 条（满足约束 1）
      - 第二步：逐条追加，每次选择"当前对未满足约束贡献最大"的单元
      - 反复迭代直至所有约束满足且总额达到 400

    参数
    ----
    strata : dict
        分层索引，key=(stance, year, source)，value={"indices":..., "count":...}
    total : int
        目标总抽样量，默认 400。
    stance_min : int
        每类立场最少条数，默认 120。
    year_min : int
        每年份最少条数，默认 5。
    core_source_min : int
        核心来源最少条数，默认 10。

    返回
    ----
    dict
        quota[(stance, year, source)] = 分配条数
    """
    # ----- 3.1 提取元数据 -----
    all_keys = list(strata.keys())
    stances = sorted(set(k[0] for k in all_keys))
    years = sorted(set(k[1] for k in all_keys))
    sources = sorted(set(k[2] for k in all_keys))

    # 核心来源判定
    source_full_counts = {}
    for k, v in strata.items():
        src = k[2]
        source_full_counts[src] = source_full_counts.get(src, 0) + v["count"]
    core_sources = {src for src, cnt in source_full_counts.items()
                    if cnt >= CORE_SOURCE_THRESHOLD}

    # ----- 3.2 辅助函数 -----
    def stance_total(q, s):
        """某立场当前已分配总数。"""
        return sum(q.get(k, 0) for k in all_keys if k[0] == s)

    def year_total(q, y):
        """某年份当前已分配总数。"""
        return sum(q.get(k, 0) for k in all_keys if k[1] == y)

    def source_total(q, src):
        """某来源当前已分配总数。"""
        return sum(q.get(k, 0) for k in all_keys if k[2] == src)

    def grand_total(q):
        """当前已分配总数。"""
        return sum(q.values())

    def remaining(q, k):
        """该分层单元还剩多少可分配。"""
        return strata[k]["count"] - q.get(k, 0)

    def distribute_deficit(q, candidates, deficit):
        """
        在候选单元之间按剩余容量比例分配 deficit 个名额。
        每个单元至少分配 1，多的按比例追加，确保均匀覆盖。
        """
        if deficit <= 0 or not candidates:
            return 0

        # 每个候选单元先分配 1 个（满足"均匀覆盖"原则）
        added = 0
        for k in candidates:
            if added >= deficit:
                break
            if remaining(q, k) > 0:
                q[k] = q.get(k, 0) + 1
                added += 1

        # 如果还有剩余，按剩余容量比例分配
        if added < deficit:
            remaining_deficit = deficit - added
            # 只考虑还有剩余容量的单元
            eligible = {k: remaining(q, k) for k in candidates if remaining(q, k) > 0}
            if eligible:
                total_rem = sum(eligible.values())
                # 按比例分配（至少 1 个）
                for k, rem in eligible.items():
                    if remaining_deficit <= 0:
                        break
                    # 该单元应得的额外配额（按比例）
                    share = max(1, int(round(remaining_deficit * rem / total_rem)))
                    share = min(share, rem, remaining_deficit)
                    q[k] = q.get(k, 0) + share
                    added += share
                    remaining_deficit -= share

        return added

    # ----- 3.3 阶段一：每个分层单元至少 1 条（维度全覆盖）-----
    quota = {}
    for k in all_keys:
        if strata[k]["count"] > 0:
            quota[k] = 1

    print(f"   阶段1（每单元≥1）：{grand_total(quota)} 条")

    # ----- 3.4 阶段二：确保每个年份 ≥ 5 条 -----
    for y in years:
        deficit = year_min - year_total(quota, y)
        if deficit > 0:
            candidates = [k for k in all_keys if k[1] == y and remaining(quota, k) > 0]
            distribute_deficit(quota, candidates, deficit)
    print(f"   阶段2（每年份≥{year_min}）：{grand_total(quota)} 条")

    # ----- 3.5 阶段三：确保每类立场 ≥ 120 条 -----
    for s in stances:
        deficit = stance_min - stance_total(quota, s)
        if deficit > 0:
            # 在该立场下的所有单元中按剩余容量比例分配
            candidates = [k for k in all_keys if k[0] == s and remaining(quota, k) > 0]
            distribute_deficit(quota, candidates, deficit)
    print(f"   阶段3（每立场≥{stance_min}）：{grand_total(quota)} 条")

    # ----- 3.6 阶段四：确保核心来源机构 ≥ 10 条 -----
    for src in core_sources:
        deficit = core_source_min - source_total(quota, src)
        if deficit > 0:
            candidates = [k for k in all_keys if k[2] == src and remaining(quota, k) > 0]
            distribute_deficit(quota, candidates, deficit)
    print(f"   阶段4（核心来源≥{core_source_min}）：{grand_total(quota)} 条")

    # ----- 3.7 阶段五：补足至 400 条（按各单元剩余容量比例均匀分配）-----
    current_total = grand_total(quota)
    deficit = total - current_total

    if deficit > 0:
        # 找出所有还有剩余容量的单元
        eligible = [(k, remaining(quota, k)) for k in all_keys if remaining(quota, k) > 0]
        if eligible:
            # 按剩余容量比例分配
            total_rem = sum(rem for _, rem in eligible)
            for k, rem in eligible:
                if deficit <= 0:
                    break
                # 该单元应得的份额（按全量规模比例）
                share = max(1, int(round(deficit * rem / total_rem)))
                share = min(share, rem, deficit)
                quota[k] = quota.get(k, 0) + share
                deficit -= share

            # 处理因取整导致的少量残余：逐一追加到仍有容量的单元
            # 优先加到配额较少的单元，避免集中在少数单元
            while deficit > 0:
                residual_candidates = [(k, remaining(quota, k), quota[k])
                                       for k in all_keys if remaining(quota, k) > 0]
                if not residual_candidates:
                    break
                # 选当前配额最小的单元（均匀分配）
                best_key = min(residual_candidates, key=lambda x: x[2])[0]
                quota[best_key] += 1
                deficit -= 1

    elif deficit < 0:
        # 超出总额，从配额最多的非最小单元削减
        excess = -deficit
        while excess > 0:
            reducible = [(k, quota[k]) for k in all_keys if quota[k] > 1]
            if not reducible:
                break
            # 削减配额最大的单元
            worst_key = max(reducible, key=lambda x: x[1])[0]
            quota[worst_key] -= 1
            excess -= 1

    print(f"   阶段5（补足至{total}）：{grand_total(quota)} 条")

    # ----- 3.8 打印配额汇总与约束验证 -----
    print(f"\n📋 配额分配完成：")
    print(f"   总额：{grand_total(quota)} / {total}")
    print(f"\n   约束验证：")
    all_ok = True
    for s in stances:
        st = stance_total(quota, s)
        flag = "✓" if st >= stance_min else "✗ 未满足"
        if st < stance_min:
            all_ok = False
        print(f"      {s:<15s} → {st:>4d} 条（≥{stance_min}）{flag}")
    for y in years:
        yt = year_total(quota, y)
        flag = "✓" if yt >= year_min else "✗ 未满足"
        if yt < year_min:
            all_ok = False
        print(f"      {y:<10} → {yt:>4d} 条（≥{year_min}）{flag}")
    for src in core_sources:
        st_src = source_total(quota, src)
        flag = "✓" if st_src >= core_source_min else "✗ 未满足"
        if st_src < core_source_min:
            all_ok = False
        print(f"      {src:<40s} → {st_src:>4d} 条（≥{core_source_min}）{flag}")
    if all_ok:
        print(f"\n   ✅ 所有约束均已满足")

    return quota


# =============================================================================
# 4. 执行抽样
# =============================================================================

def sample_by_quota(
    df: pd.DataFrame,
    strata: dict,
    quota: dict,
    random_seed: int = RANDOM_SEED,
) -> pd.DataFrame:
    """
    按照配额从每个分层单元中随机抽取样本。

    参数
    ----
    df : pd.DataFrame
        全量数据。
    strata : dict
        分层索引。
    quota : dict
        各单元配额。
    random_seed : int
        随机种子。

    返回
    ----
    pd.DataFrame
        抽样结果（保留原始列）。
    """
    sampled_list = []
    rng = np.random.RandomState(random_seed)

    for key, n_sample in quota.items():
        if n_sample <= 0:
            continue
        indices = strata[key]["indices"]
        n_available = len(indices)

        if n_sample >= n_available:
            # 配额 ≥ 可用量：全取
            chosen = indices
        else:
            # 随机抽取（replace=False，不重复）
            chosen = rng.choice(indices, size=n_sample, replace=False).tolist()

        sampled_list.append(df.loc[chosen])

    df_sampled = pd.concat(sampled_list, ignore_index=True)
    print(f"\n✅ 抽样完成：实际抽取 {len(df_sampled)} 条")
    return df_sampled


# =============================================================================
# 5. 生成盲标校验模板
# =============================================================================

def build_blind_template(df_sampled: pd.DataFrame) -> pd.DataFrame:
    """
    生成人工盲标校验模板。

    处理步骤：
      1. 移除 AI 标注的 stance 列 —— 保证盲标客观性
      2. 保留 text / year / source / theme（theme 供标注员参考）
      3. 新增 sample_id 唯一编号（S0001 ~ S0400）
      4. 新增空白 human_stance 列供人工填写

    参数
    ----
    df_sampled : pd.DataFrame
        分层抽样结果。

    返回
    ----
    pd.DataFrame
        盲标模板，列顺序：
        sample_id, text, year, source, theme, human_stance
    """
    blind = df_sampled[[COL_TEXT, COL_YEAR, COL_SOURCE, COL_THEME]].copy()

    # sample_id：S + 4 位零填充序号
    blind.insert(0, "sample_id",
                 [f"S{i:04d}" for i in range(1, len(blind) + 1)])

    # 空白列，供人工标注立场
    blind["human_stance"] = ""

    return blind


# =============================================================================
# 6. 抽样分布统计
# =============================================================================

def print_distribution_stats(
    df_full: pd.DataFrame,
    df_sampled: pd.DataFrame,
) -> None:
    """
    打印抽样分布统计。

    统计维度：总样本数、各立场抽样数、各年份抽样数、各来源抽样数。

    参数
    ----
    df_full : pd.DataFrame
        全量数据。
    df_sampled : pd.DataFrame
        抽样结果。
    """
    n_full = len(df_full)
    n_sampled = len(df_sampled)

    print("\n" + "=" * 60)
    print("  抽样分布统计")
    print("=" * 60)

    print(f"\n📦 基本统计：")
    print(f"   全量总样本数：{n_full}")
    print(f"   盲标抽样数：  {n_sampled}")
    print(f"   抽样比例：    {n_sampled / n_full * 100:.2f}%")

    for dim_label, col_name in [
        ("立场 (stance)", COL_STANCE),
        ("年份 (year)",   COL_YEAR),
        ("来源 (source)", COL_SOURCE),
    ]:
        print(f"\n📊 各{dim_label}抽样数量：")
        full_counts = df_full[col_name].value_counts()
        sampled_counts = df_sampled[col_name].value_counts()

        max_bar = sampled_counts.max() if len(sampled_counts) > 0 else 1
        # 按全量频次降序排列
        for cat in full_counts.index:
            f_n = full_counts[cat]
            s_n = sampled_counts.get(cat, 0)
            pct = s_n / f_n * 100 if f_n > 0 else 0

            bar_len = max(1, int(s_n / max_bar * 30)) if max_bar > 0 else 0
            bar = "█" * bar_len

            print(f"    {str(cat):<25s} 全量:{f_n:>7d} → 抽样:{s_n:>5d} ({pct:>5.1f}%)  {bar}")

    print("\n" + "=" * 60)


# =============================================================================
# 7. 保存盲标模板
# =============================================================================

def save_template(df_blind: pd.DataFrame, output_path: str) -> None:
    """
    保存盲标模板为 CSV 文件。

    - 编码 utf-8-sig（Excel 打开不乱码）
    - index=False（不写入 Pandas 行索引）
    - 自动创建输出目录

    参数
    ----
    df_blind : pd.DataFrame
        盲标模板。
    output_path : str
        输出 CSV 绝对路径。
    """
    output_dir = os.path.dirname(output_path)
    if output_dir:
        os.makedirs(output_dir, exist_ok=True)

    df_blind.to_csv(output_path, index=False, encoding=OUTPUT_ENCODING)
    print(f"\n✅ 盲标模板已保存至：{output_path}")
    print(f"   行数：{len(df_blind)}，列数：{len(df_blind.columns)}")
    print(f"   列名：{list(df_blind.columns)}")


# =============================================================================
# 8. 主流程
# =============================================================================

def main():
    """主入口：串联全部步骤。"""
    print("=" * 60)
    print("  固定样本量三层分层抽样 — 盲标校验模板生成器")
    print(f"  启动时间：{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"  输入文件：{INPUT_FILE}")
    print(f"  输出文件：{OUTPUT_FILE}")
    print(f"  目标抽样量：{TOTAL_SAMPLES} 条")
    print(f"  随机种子：{RANDOM_SEED}")
    print("=" * 60)

    # ---- [1/6] 加载与清洗 ----
    print("\n[1/6] 加载与清洗数据...")
    df = load_and_clean(INPUT_FILE)

    # ---- [2/6] 构建分层索引 ----
    print("\n[2/6] 构建三层分层索引 (stance → year → source)...")
    strata = build_stratum_index(df)
    print_data_summary(df, strata)

    # ---- [3/6] 配额分配 ----
    print("\n[3/6] 贪心配额分配（满足 stance≥120 / year≥5 / source≥10 / 总计=400）...")
    quota = allocate_quotas(strata)

    # 打印各层配额明细
    print(f"\n   各分层单元配额明细：")
    for k in sorted(quota.keys(), key=lambda x: (x[0], x[1], x[2])):
        if quota[k] > 0:
            print(f"      {k[0]:<12s} | {k[1]:<6} | {k[2]:<40s} → {quota[k]:>4d} / {strata[k]['count']}")

    # ---- [4/6] 执行抽样 ----
    print("\n[4/6] 按配额执行随机抽样...")
    df_sampled = sample_by_quota(df, strata, quota)

    # ---- [5/6] 生成盲标模板 ----
    print("\n[5/6] 生成盲标校验模板（移除 stance，新增 sample_id + human_stance）...")
    df_blind = build_blind_template(df_sampled)
    print(f"   模板结构：{len(df_blind)} 行 × {len(df_blind.columns)} 列")

    # ---- [6/6] 打印统计 & 保存 ----
    print("\n[6/6] 输出分布统计 & 保存文件...")
    print_distribution_stats(df, df_sampled)
    save_template(df_blind, OUTPUT_FILE)

    # ---- 完成 ----
    print("\n" + "=" * 60)
    print("  🎉 全部完成！")
    print("=" * 60)
    print(f"""
  📋 后续操作指引：
     1. 打开盲标模板 → {OUTPUT_FILE}
     2. 分发给人工标注员，在 human_stance 列填写立场标注
     3. 回收后，用 sample_id 关联回原 stance 列做比对
     4. 计算一致率 = 一致条数 / 400（按 stance、year 等维度分别统计）
""")


if __name__ == "__main__":
    main()
