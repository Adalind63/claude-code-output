# -*- coding: utf-8 -*-
"""
=============================================================================
BERT 建模数据划分 —— 双层分层抽样 + 类别权重计算
=============================================================================
功能概述：
  1. 数据清洗：过滤词数 < 20 的过短文本 + text 去重
  2. 双层分层抽样（year + stance），70/15/15 划分训练/验证/测试集
  3. 随机种子固定 42，保证可复现；每个年份×立场组合在三集合中分布一致
  4. 计算训练集各类别样本权重（balanced），供 BERT 训练时处理类别不均衡
  5. 输出 train.csv / val.csv / test.csv
  6. 打印划分统计

依赖：pip install pandas scikit-learn
=============================================================================
"""

import pandas as pd
import numpy as np
import os
from datetime import datetime
from sklearn.model_selection import train_test_split
from sklearn.utils.class_weight import compute_class_weight

# =============================================================================
# 0. 全局配置（Windows 绝对路径）
# =============================================================================
INPUT_FILE = r"D:\项目流程\final_labeled_corpus.csv"
OUTPUT_DIR = r"D:\项目流程"
OUTPUT_TRAIN = os.path.join(OUTPUT_DIR, "train.csv")
OUTPUT_VAL = os.path.join(OUTPUT_DIR, "val.csv")
OUTPUT_TEST = os.path.join(OUTPUT_DIR, "test.csv")

ENCODING = "utf-8-sig"
RANDOM_SEED = 42
TRAIN_RATIO = 0.70
VAL_RATIO = 0.15
TEST_RATIO = 0.15
MIN_WORD_COUNT = 20            # 最小词数阈值，过滤过短文本

# 分层字段
STRATUM_COL_YEAR = "year"
STRATUM_COL_STANCE = "stance"


# =============================================================================
# 1. 数据加载与清洗
# =============================================================================

def load_and_clean(filepath: str) -> pd.DataFrame:
    """
    读取 final_labeled_corpus.csv，执行清洗。

    清洗步骤：
      ① 校验必需列（text, year, source, theme, stance）
      ② 计算每条 text 的单词数，过滤词数 < MIN_WORD_COUNT 的过短文本
      ③ 按 text 字段去重，保留第一条
      ④ 构建双层分层键（year||stance），用于后续分层抽样

    参数
    ----
    filepath : str
        输入 CSV 绝对路径。

    返回
    ----
    pd.DataFrame
        清洗后数据（含 _stratify_key 辅助列）。
    """
    if not os.path.exists(filepath):
        raise FileNotFoundError(f"输入文件不存在：{filepath}")

    df = pd.read_csv(filepath, encoding=ENCODING)
    n_raw = len(df)
    print(f"原始数据：{n_raw:,} 条")

    # --- 校验列 ---
    required = ["text", "year", "source", "theme", "stance"]
    missing = [c for c in required if c not in df.columns]
    if missing:
        raise ValueError(f"缺少必需列：{missing}\n   实际列名：{list(df.columns)}")

    # --- ① 过滤过短文本（单词数 < 20）---
    df["_word_count"] = df["text"].astype(str).str.split().str.len()
    df = df[df["_word_count"] >= MIN_WORD_COUNT].copy()
    n_after_len = len(df)
    print(f"过滤词数 < {MIN_WORD_COUNT}：丢弃 {n_raw - n_after_len:,} 条 → 剩余 {n_after_len:,} 条")

    # --- ② 按 text 去重 ---
    before_dedup = len(df)
    df = df.drop_duplicates(subset=["text"], keep="first").copy()
    n_after_dedup = len(df)
    print(f"text 去重：丢弃 {before_dedup - n_after_dedup:,} 条 → 剩余 {n_after_dedup:,} 条")

    # --- ③ 处理 year / stance 的 NaN 值 ---
    # 由于最终语料来自自动标注流程，year 或 stance 为 NaN 的极少量记录无法分层，予以丢弃
    before_nan = len(df)
    df = df.dropna(subset=[STRATUM_COL_YEAR, STRATUM_COL_STANCE]).copy()
    if before_nan > len(df):
        print(f"丢弃 year/stance 为空记录：{before_nan - len(df):,} 条")

    # year 统一为整数去掉小数点，避免生成 "2017.0" 之类的键
    df[STRATUM_COL_YEAR] = df[STRATUM_COL_YEAR].astype(float).astype(int)

    # --- ④ 构建双层分层键 ---
    df["_stratify_key"] = (
        df[STRATUM_COL_YEAR].astype(str) + "||" +
        df[STRATUM_COL_STANCE].astype(str)
    )

    print(f"清洗完成：{len(df):,} 条，分层键唯一值 {df['_stratify_key'].nunique()} 个\n")
    return df


# =============================================================================
# 2. 双层分层抽样划分
# =============================================================================

def stratified_split(
    df: pd.DataFrame,
    train_ratio: float = TRAIN_RATIO,
    val_ratio: float = VAL_RATIO,
    test_ratio: float = TEST_RATIO,
    random_seed: int = RANDOM_SEED,
) -> tuple:
    """
    按 year + stance 双层分层，将数据划分为训练/验证/测试三集合。

    方法：
      - 使用 sklearn train_test_split 两次连续分层划分
      - 第一次：全量 → train (70%) + temp (30%)
      - 第二次：temp → val (50% of temp = 15%) + test (50% of temp = 15%)
      - 每次均以 _stratify_key 为 stratify 参数，确保各 year×stance 组合
        在三个集合中的比例一致

    参数
    ----
    df : pd.DataFrame
        清洗后数据（含 _stratify_key 列）。
    train_ratio : float
        训练集比例，默认 0.70。
    val_ratio : float
        验证集比例，默认 0.15。
    test_ratio : float
        测试集比例，默认 0.15。
    random_seed : int
        随机种子。

    返回
    ----
    tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]
        (train_df, val_df, test_df)
    """
    # 校验比例之和
    total_ratio = train_ratio + val_ratio + test_ratio
    if abs(total_ratio - 1.0) > 0.001:
        raise ValueError(f"三集合比例之和应为 1.0，当前为 {total_ratio}")

    stratify_values = df["_stratify_key"].values

    # ---- 第一次划分：train vs (val + test) ----
    # test_size = val_ratio + test_ratio = 0.30
    temp_ratio = val_ratio + test_ratio
    train_df, temp_df = train_test_split(
        df,
        test_size=temp_ratio,
        random_state=random_seed,
        stratify=stratify_values,
    )

    # ---- 第二次划分：val vs test ----
    # test_size = test_ratio / temp_ratio = 0.15 / 0.30 = 0.50
    val_ratio_within_temp = test_ratio / temp_ratio
    val_df, test_df = train_test_split(
        temp_df,
        test_size=val_ratio_within_temp,
        random_state=random_seed,
        stratify=temp_df["_stratify_key"].values,
    )

    # 清理辅助列
    for subset in [train_df, val_df, test_df]:
        subset.drop(columns=["_stratify_key", "_word_count"], inplace=True, errors="ignore")

    print(f"划分完成：train={len(train_df):,}  val={len(val_df):,}  test={len(test_df):,}")
    return train_df, val_df, test_df


# =============================================================================
# 3. 计算训练集类别权重
# =============================================================================

def compute_weights(train_df: pd.DataFrame, stance_col: str = "stance") -> dict:
    """
    计算训练集各类别的样本权重，用于 BERT 训练时处理类别不均衡。

    使用 sklearn 的 'balanced' 模式：
      weight[class] = n_samples / (n_classes × n_samples_per_class)

    权重 > 1 的类别在训练时会获得更大损失权重，补偿其样本数不足；
    权重 < 1 的类别则会降低权重，避免主导梯度。

    参数
    ----
    train_df : pd.DataFrame
        训练集数据。
    stance_col : str
        标签列名。

    返回
    ----
    dict
        {类别标签: 权重值}
    """
    y = train_df[stance_col].values
    classes = np.unique(y)
    weights = compute_class_weight("balanced", classes=classes, y=y)
    weight_dict = dict(zip(classes, weights))
    return weight_dict


# =============================================================================
# 4. 打印划分统计
# =============================================================================

def print_split_stats(
    df_full: pd.DataFrame,
    train_df: pd.DataFrame,
    val_df: pd.DataFrame,
    test_df: pd.DataFrame,
    class_weights: dict,
) -> None:
    """
    打印详细的划分统计信息。

    统计维度：
      - 总样本量、各集合样本量与占比
      - 各立场（stance）在三集合中的分布与占比
      - 各年份（year）在三集合中的分布
      - 训练集各类别权重

    参数
    ----
    df_full : pd.DataFrame
        清洗后全量数据。
    train_df / val_df / test_df : pd.DataFrame
        三集合。
    class_weights : dict
        训练集类别权重。
    """
    n_total = len(df_full)
    n_train = len(train_df)
    n_val = len(val_df)
    n_test = len(test_df)

    print("\n" + "=" * 65)
    print("  BERT 建模数据划分统计报告")
    print("=" * 65)

    # --- 基本统计 ---
    print(f"\n  清洗后总样本量：{n_total:,}")
    print(f"  随机种子：{RANDOM_SEED}")
    print(f"  划分比例：训练 {TRAIN_RATIO:.0%} / 验证 {VAL_RATIO:.0%} / 测试 {TEST_RATIO:.0%}")
    print(f"\n  {'集合':<10s} {'样本量':>10s} {'占比':>10s}")
    print(f"  {'-'*32}")
    print(f"  {'训练集':<10s} {n_train:>10,} {n_train/n_total:>10.2%}")
    print(f"  {'验证集':<10s} {n_val:>10,} {n_val/n_total:>10.2%}")
    print(f"  {'测试集':<10s} {n_test:>10,} {n_test/n_total:>10.2%}")
    print(f"  {'合计':<10s} {n_train+n_val+n_test:>10,} {(n_train+n_val+n_test)/n_total:>10.2%}")

    # --- 各立场在三集合中的分布 ---
    print(f"\n  {'='*50}")
    print(f"  各立场 (stance) 在三集合中的分布")
    print(f"  {'='*50}")
    stance_list = ["tough", "cooperate", "neutral"]

    print(f"  {'立场':<12s} {'全量':>8s} {'训练':>8s} {'验证':>8s} {'测试':>8s}")
    print(f"  {'-'*50}")
    for s in stance_list:
        f_n = (df_full["stance"] == s).sum()
        t_n = (train_df["stance"] == s).sum()
        v_n = (val_df["stance"] == s).sum()
        ts_n = (test_df["stance"] == s).sum()
        print(f"  {s:<12s} {f_n:>8,} {t_n:>8,} {v_n:>8,} {ts_n:>8,}")

    # 各立场占比（用于验证分层效果）
    print(f"\n  {'立场':<12s} {'全量%':>8s} {'训练%':>8s} {'验证%':>8s} {'测试%':>8s}")
    print(f"  {'-'*50}")
    for s in stance_list:
        f_pct = (df_full["stance"] == s).sum() / n_total * 100
        t_pct = (train_df["stance"] == s).sum() / n_train * 100
        v_pct = (val_df["stance"] == s).sum() / n_val * 100
        ts_pct = (test_df["stance"] == s).sum() / n_test * 100
        print(f"  {s:<12s} {f_pct:>7.1f}% {t_pct:>7.1f}% {v_pct:>7.1f}% {ts_pct:>7.1f}%")

    # --- 各年份在三集合中的分布 ---
    print(f"\n  {'='*50}")
    print(f"  各年份 (year) 在三集合中的分布")
    print(f"  {'='*50}")
    years_sorted = sorted(df_full["year"].unique())
    print(f"  {'年份':<8s} {'全量':>8s} {'训练':>8s} {'验证':>8s} {'测试':>8s}")
    print(f"  {'-'*46}")
    for y in years_sorted:
        f_n = (df_full["year"] == y).sum()
        t_n = (train_df["year"] == y).sum()
        v_n = (val_df["year"] == y).sum()
        ts_n = (test_df["year"] == y).sum()
        print(f"  {str(y):<8s} {f_n:>8,} {t_n:>8,} {v_n:>8,} {ts_n:>8,}")

    # --- 训练集类别权重 ---
    print(f"\n  {'='*50}")
    print(f"  训练集类别权重（balanced，用于 BERT 训练）")
    print(f"  {'='*50}")
    print(f"  {'类别':<12s} {'样本数':>8s} {'权重':>10s} {'含义':>20s}")
    print(f"  {'-'*55}")
    for s in stance_list:
        cnt = (train_df["stance"] == s).sum()
        w = class_weights.get(s, 1.0)
        if w > 1.0:
            meaning = "↑ 样本偏少，加大损失"
        elif w < 1.0:
            meaning = "↓ 样本偏多，降低损失"
        else:
            meaning = "— 均衡"
        print(f"  {s:<12s} {cnt:>8,} {w:>10.4f}   {meaning}")

    print(f"\n  {'='*65}")
    print(f"  注：权重公式 weight = n_total / (n_classes * n_class_samples)")
    print(f"      训练时使用 CrossEntropyLoss(weight=class_weights) 或等效方式")
    print(f"  {'='*65}\n")


# =============================================================================
# 5. 保存输出
# =============================================================================

def save_datasets(train_df, val_df, test_df) -> None:
    """保存三个数据集为 CSV 文件（utf-8-sig，无行索引）。"""
    os.makedirs(OUTPUT_DIR, exist_ok=True)

    train_df.to_csv(OUTPUT_TRAIN, index=False, encoding=ENCODING)
    print(f"  train.csv → {OUTPUT_TRAIN}  ({len(train_df):,} 条)")

    val_df.to_csv(OUTPUT_VAL, index=False, encoding=ENCODING)
    print(f"  val.csv   → {OUTPUT_VAL}  ({len(val_df):,} 条)")

    test_df.to_csv(OUTPUT_TEST, index=False, encoding=ENCODING)
    print(f"  test.csv  → {OUTPUT_TEST}  ({len(test_df):,} 条)")


# =============================================================================
# 6. 主流程
# =============================================================================

def main():
    print("=" * 65)
    print("  BERT 建模数据划分 —— 双层分层抽样 + 类别权重计算")
    print(f"  启动时间：{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("=" * 65)

    # ---- [1] 加载与清洗 ----
    print("\n[1/4] 加载与清洗数据...")
    df = load_and_clean(INPUT_FILE)

    # ---- [2] 双层分层划分 ----
    print("[2/4] 双层分层划分（year + stance，70/15/15）...")
    train_df, val_df, test_df = stratified_split(df)

    # ---- [3] 计算类别权重 ----
    print("\n[3/4] 计算训练集类别权重（balanced）...")
    class_weights = compute_weights(train_df)
    for stance, w in class_weights.items():
        print(f"    {stance}: weight = {w:.4f}")

    # ---- [4] 打印统计 & 保存 ----
    print("\n[4/4] 打印划分统计 & 保存文件...")
    print_split_stats(df, train_df, val_df, test_df, class_weights)
    save_datasets(train_df, val_df, test_df)

    print("=" * 65)
    print("  完成！")
    print("=" * 65)


if __name__ == "__main__":
    main()
