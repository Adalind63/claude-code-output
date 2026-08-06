# -*- coding: utf-8 -*-
"""
=============================================================================
标注信度检验 + 全量语料标签优化修正
=============================================================================
功能概述：
  一、信度检验模块
    1. 按 text 字段匹配 AI 标签与人工标签（400条金标准）
    2. 计算 Cohen's Kappa、各类别 P/R/F1、混淆矩阵、信度等级
    3. 提取人机标注不一致的分歧样本
    4. 生成信度报告文本文件

  二、全量标签优化修正模块
    1. 基于 400 条金标准，逐关键词计算命中准确率
    2. 自动调整关键词权重（高准确率提升、低准确率降低）
    3. 使用优化权重重标全量语料
    4. 400 条人工金标准样本强制以 human_stance 覆盖
    5. 输出最终标注语料

依赖：pip install pandas scikit-learn
=============================================================================
"""

import pandas as pd
import numpy as np
import re
import os
from datetime import datetime
from collections import defaultdict
from sklearn.metrics import (
    cohen_kappa_score,
    precision_recall_fscore_support,
    confusion_matrix,
    classification_report,
)

# =============================================================================
# 0. 全局路径配置（Windows 绝对路径）
# =============================================================================
AUTO_LABELED_PATH = r"D:\项目流程\auto_labeled_corpus.csv"   # AI 全量标注
MANUAL_CHECK_PATH = r"D:\项目流程\manual_check_400.csv"       # 人工金标准（400条）
OUTPUT_RELIABILITY = r"D:\项目流程\reliability_report.txt"     # 信度报告
OUTPUT_DISAGREEMENT = r"D:\项目流程\disagreement_samples.csv"  # 分歧样本
OUTPUT_FINAL_CORPUS = r"D:\项目流程\final_labeled_corpus.csv"  # 最终标注语料

ENCODING = "utf-8-sig"
STANCE_THRESHOLD = 0.8           # 原标注逻辑的得分差值阈值

# =============================================================================
# 1. 原标注逻辑 —— 关键词词典（与 auto_label.py 完全一致）
# =============================================================================
TOUGH_KEYWORDS = {
    2.0: [
        "de-risk", "de-risking", "decoupling", "decouple",
        "systemic rival", "systemic rivalry",
        "strategic competitor", "strategic competition",
        "security threat", "threat to security",
        "strategic dependency", "strategic dependence",
        "economic coercion", "economic coercive",
        "level playing field", "reciprocity", "reciprocal",
        "weaponize interdependence", "weaponisation of interdependence",
        "economic security", "supply chain resilience",
        "foreign subsidy", "strategic autonomy",
        "trade defence", "trade defense",
        "derisking strategy",
    ],
    1.5: [
        "anti-dumping", "anti dumping", "antidumping",
        "countervailing duty", "countervailing measure",
        "anti-subsidy", "anti subsidy", "antisubsidy",
        "export control", "export restriction",
        "investment screening", "investment review",
        "sanction", "restriction", "restrictive",
        "barrier", "tariff", "ban",
        "safeguard measure", "safeguard investigation",
        "trade remedy", "trade remedies",
        "market access barrier", "market access restriction",
        "forced technology transfer", "forced transfer of technology",
        "circumvention", "circumvent",
        "dumping", "subsidy", "investigation",
        "countermeasure", "retaliation", "retaliatory",
        "surveillance", "screening mechanism",
        "critical infrastructure",
        "dependency reduction", "reducing dependence",
    ],
    1.0: [
        "unfair competition", "unfair trade",
        "market distortion", "distortion", "distortive",
        "overcapacity", "excess capacity",
        "discriminatory", "discrimination", "discriminate",
        "non-compliant", "noncompliance", "non compliance",
        "predatory pricing", "state subsidy",
        "intellectual property theft", "IP theft",
        "imbalanced trade", "trade imbalance",
        "trade deficit", "market protection",
        "state-owned enterprise", "SOE",
        "industrial overcapacity",
        "unfair trade practice", "origin fraud",
    ],
}

COOPERATE_KEYWORDS = {
    2.0: [
        "win-win", "win win",
        "mutual benefit", "mutually beneficial",
        "strategic partnership", "comprehensive strategic partnership",
        "shared governance", "common development",
        "multilateral cooperation", "multilateral collaboration",
        "shared interest", "common interest",
        "partnership agreement", "comprehensive agreement",
        "economic integration", "rules-based order",
        "constructive engagement", "strategic trust",
    ],
    1.5: [
        "cooperation", "cooperate", "cooperative",
        "collaboration", "collaborate", "collaborative",
        "dialogue", "consultation", "consult",
        "negotiation", "negotiate", "negotiating",
        "trade agreement", "free trade agreement",
        "joint initiative", "joint effort",
        "working group", "bilateral summit",
        "green cooperation", "digital cooperation",
        "engagement", "partnership",
        "memorandum of understanding", "MoU",
        "high-level dialogue", "technical cooperation",
        "capacity building", "exchange",
        "joint statement", "coordinated approach",
        "investment agreement", "economic dialogue",
    ],
    1.0: [
        "open market", "market opening",
        "mutual respect", "respectful",
        "complementary", "complementarity",
        "inclusive", "inclusiveness",
        "mutual understanding",
        "transparency", "predictability",
        "harmonization", "harmonisation", "harmonize",
        "alignment", "align", "aligned",
        "convergence", "converge",
        "facilitation", "facilitate",
        "liberalization", "liberalisation",
    ],
}

# =============================================================================
# 2. 原标注逻辑 —— 正则编译、否定/转折/情态词（与 auto_label.py 完全一致）
# =============================================================================

def build_keyword_regex(keyword: str) -> str:
    """
    将关键词转为匹配同根词形的正则表达式。
    单字词：\\b词根\\w*\\b —— 自动覆盖 -ing/-ed/-tion/-ive 等后缀
    多字短语：逐词匹配，允许连字符或空格变体。
    """
    kw_clean = keyword.lower().strip()
    words = kw_clean.split()
    patterns = []

    for w in words:
        if w in ('a', 'an', 'the', 'of', 'to', 'in', 'on', 'at', 'by', 'for', 'and', 'or'):
            patterns.append(re.escape(w))
            continue

        # 取词根：截断常见后缀
        stem = re.sub(
            r'(ing|ed|es|s|tion|sion|ive|ment|al|ly|ance|ence|able|ible|ise|ize|ship|ness|ity|ous|ful|less)$',
            '', w,
        )
        if len(stem) < 4:
            stem = w

        # 处理 de- 前缀变体
        if stem.startswith('de') and len(stem) > 4:
            stem_no_de = stem[2:]
            patterns.append(r'(?:de[- ]?)?' + re.escape(stem_no_de) + r'\w*')
        else:
            patterns.append(re.escape(stem) + r'\w*')

    joiner = r'[\s\-]+'
    return r'\b' + joiner.join(patterns) + r'\b'


def precompile_keywords(kw_dict: dict) -> dict:
    """预编译关键词正则，返回 {权重: [(原始关键词, compiled_regex), ...]}"""
    compiled = {}
    for weight, kw_list in kw_dict.items():
        compiled[weight] = []
        for kw in kw_list:
            pattern = build_keyword_regex(kw)
            compiled[weight].append((kw, re.compile(pattern, re.IGNORECASE)))
    return compiled


# --- 否定词 ---
NEGATION_TERMS = [
    r'\bnot\b', r'\bno\b', r'\bhardly\b', r'\bnever\b',
    r'\bwithout\b', r'\black\s+of\b', r'\bfail(?:ed|s|ing)?\s+to\b',
    r'\bneither\b', r'\bnor\b', r'\babsence\s+of\b',
    r'\bdoes\s+not\b', r'\bdo\s+not\b', r'\bdid\s+not\b',
    r'\bcannot\b', r'\bcan\s+not\b', r'\bwill\s+not\b',
    r'\bunable\s+to\b', r'\brefuse(?:s|d)?\s+to\b',
]
NEGATION_RE = re.compile('|'.join(NEGATION_TERMS), re.IGNORECASE)

# --- 强转折连词：后半句 ×1.3，前半句 ×0.4 ---
STRONG_CONTRAST = [r'\bbut\b', r'\bhowever\b', r'\bnevertheless\b',
                   r'\bnonetheless\b', r'\byet\b', r'\binstead\b']
STRONG_CONTRAST_RE = re.compile('|'.join(STRONG_CONTRAST), re.IGNORECASE)

# --- 弱转折连词：后半句 ×1.1，前半句 ×0.8 ---
WEAK_CONTRAST = [r'\bwhile\b', r'\balthough\b', r'\bthough\b',
                 r'\bwhereas\b', r'\bdespite\b', r'\bin\s+spite\s+of\b']
WEAK_CONTRAST_RE = re.compile('|'.join(WEAK_CONTRAST), re.IGNORECASE)

# --- 强硬类情态动词 ---
TOUGH_MODALS = [r'\bmust\b', r'\bshould\b', r'\bneed\s+to\b',
                r'\bhave\s+to\b', r'\bhas\s+to\b', r'\brequired\s+to\b',
                r'\bobliged\s+to\b', r'\bshall\b']
TOUGH_MODALS_RE = re.compile('|'.join(TOUGH_MODALS), re.IGNORECASE)

# --- 合作类情态动词 ---
COOPERATE_MODALS = [r'\bcan\b', r'\bcould\b', r'\bmay\b', r'\bmight\b',
                    r'\bwilling\s+to\b', r'\bready\s+to\b', r'\bpossible\s+to\b']
COOPERATE_MODALS_RE = re.compile('|'.join(COOPERATE_MODALS), re.IGNORECASE)


# =============================================================================
# 3. 核心标注函数（可接受自定义关键词词典，支持权重优化）
# =============================================================================

def compute_scores(text: str,
                   tough_compiled: dict,
                   coop_compiled: dict) -> tuple:
    """
    对单条文本执行完整标注流程，返回 (tough_score, cooperate_score)。

    步骤：
      ① 查找所有关键词匹配及其位置
      ② 去重（重叠匹配保留权重最高者）
      ③ 否定反转：匹配词前后 5 词含否定词 → 分数计入对立立场
      ④ 转折加权：匹配词在转折词之后 → 权重倍率 ×1.3/1.1；之前 → ×0.4/0.8
      ⑤ 情态辅助：全文本含强硬类情态词每个 +0.5，合作类 +0.5

    参数
    ----
    text : str
        待标注文本。
    tough_compiled : dict
        {权重: [(原始关键词, compiled_regex), ...]} 的 tough 类关键词。
    coop_compiled : dict
        同结构的 cooperate 类关键词。

    返回
    ----
    tuple[float, float]
        (tough_score, cooperate_score)
    """
    text_lower = text.lower()

    # 构建 word -> 起始位置 映射（用于前后 5 词窗口）
    words = text_lower.split()
    word_positions = []
    pos = 0
    for w in words:
        while pos < len(text_lower) and text_lower[pos] == ' ':
            pos += 1
        word_positions.append(pos)
        pos += len(w)

    # ---- ① 查找所有关键词匹配 ----
    matches = []  # [{start, end, weight, text, category}]
    for category, compiled_dict in [('tough', tough_compiled), ('cooperate', coop_compiled)]:
        for weight, regex_list in compiled_dict.items():
            for kw_original, pattern in regex_list:
                for m in pattern.finditer(text_lower):
                    matches.append({
                        'start': m.start(),
                        'end': m.end(),
                        'weight': weight,
                        'text': m.group(),
                        'category': category,
                    })

    if not matches:
        return 0.0, 0.0

    # ---- ② 去重：重叠匹配保留权重最高的 ----
    matches.sort(key=lambda x: (x['start'], -x['weight']))
    deduped = []
    for m in matches:
        if deduped and m['start'] < deduped[-1]['end']:
            continue
        deduped.append(m)
    matches = deduped

    # ---- ③ 否定反转：前后 5 词含否定词 → 反转入对立立场 ----
    def has_negation_in_window(match_start_char: int, match_end_char: int) -> bool:
        """检查匹配位置前后 5 个单词内是否有否定词。"""
        match_word_start = None
        match_word_end = None
        for i, wp in enumerate(word_positions):
            if wp <= match_start_char < wp + 100:
                if match_word_start is None:
                    match_word_start = i
                if wp >= match_end_char:
                    match_word_end = i
                    break
        if match_word_start is None:
            match_word_start = 0
        if match_word_end is None:
            match_word_end = len(words) - 1

        window_start = max(0, match_word_start - 5)
        window_end = min(len(words), match_word_end + 5)
        window_text = ' '.join(words[window_start:window_end])
        return bool(NEGATION_RE.search(window_text))

    # ---- ④ 转折加权 ----
    # 按句子拆分（.?! 后跟空格+大写）
    sentence_splits = [-1]
    for m in re.finditer(r'[.!?]\s+(?=[A-Z])', text_lower):
        sentence_splits.append(m.start() + 1)
    sentence_splits.append(len(text_lower))

    def get_contrast_multiplier(match_start: int) -> float:
        """根据匹配词相对转折词的位置返回权重倍率。"""
        sent_idx = 0
        for i in range(len(sentence_splits) - 1):
            if sentence_splits[i] < match_start <= sentence_splits[i + 1]:
                sent_idx = i
                break

        sent_start = sentence_splits[sent_idx] + 1
        sent_end = sentence_splits[sent_idx + 1]
        sent_text = text_lower[sent_start:sent_end] if sent_end > sent_start else ''

        mult = 1.0
        for sm in STRONG_CONTRAST_RE.finditer(sent_text):
            contrast_pos_in_sent = sm.start()
            match_pos_in_sent = match_start - sent_start
            if match_pos_in_sent > contrast_pos_in_sent:
                mult *= 1.3   # 在转折词之后 → 强调
            else:
                mult *= 0.4   # 在转折词之前 → 削弱

        for wm in WEAK_CONTRAST_RE.finditer(sent_text):
            contrast_pos_in_sent = wm.start()
            match_pos_in_sent = match_start - sent_start
            if match_pos_in_sent > contrast_pos_in_sent:
                mult *= 1.1
            else:
                mult *= 0.8

        return mult

    # ---- ⑤ 累加得分 ----
    tough_score = 0.0
    cooperate_score = 0.0

    for m in matches:
        weight = m['weight']
        category = m['category']
        negated = has_negation_in_window(m['start'], m['end'])
        contrast_mult = get_contrast_multiplier(m['start'])
        final_weight = weight * contrast_mult

        if negated:
            # 否定反转：分数计入对立类别
            if category == 'tough':
                cooperate_score += final_weight
            else:
                tough_score += final_weight
        else:
            if category == 'tough':
                tough_score += final_weight
            else:
                cooperate_score += final_weight

    # ---- ⑥ 情态辅助加分 ----
    has_tough_hit = any(m['category'] == 'tough' for m in matches)
    has_coop_hit = any(m['category'] == 'cooperate' for m in matches)

    if has_tough_hit:
        tough_modals_count = len(TOUGH_MODALS_RE.findall(text_lower))
        tough_score += tough_modals_count * 0.5

    if has_coop_hit:
        coop_modals_count = len(COOPERATE_MODALS_RE.findall(text_lower))
        cooperate_score += coop_modals_count * 0.5

    return round(tough_score, 4), round(cooperate_score, 4)


def classify_stance(tough: float, cooperate: float) -> str:
    """
    根据得分差值判定立场：
      tough - cooperate > 0.8  → tough
      cooperate - tough > 0.8  → cooperate
      差值 ≤ 0.8 / 无命中     → neutral
    """
    diff = tough - cooperate
    if diff > STANCE_THRESHOLD:
        return "tough"
    elif -diff > STANCE_THRESHOLD:
        return "cooperate"
    else:
        return "neutral"


# =============================================================================
# 一、信度检验模块
# =============================================================================

def load_and_align(auto_path: str, manual_path: str) -> tuple:
    """
    加载两份文件，按 text 字段精确匹配，对齐 AI 标签与人工标签。

    匹配策略：
      - 以 manual_check_400.csv 的 text 为基准
      - 在 auto_labeled_corpus.csv 中查找完全相同的 text
      - 若 text 重复，取第一条匹配（金标准样本 text 在语料中应唯一）

    参数
    ----
    auto_path : str
        AI 全量标注文件路径。
    manual_path : str
        人工金标准文件路径。

    返回
    ----
    tuple[pd.DataFrame, pd.DataFrame]
        (auto_df 全量, 对齐后的 400 条 gold_df)
    """
    print("[信度检验] 加载数据...")
    # 编码回退：优先 utf-8-sig，失败则尝试 latin-1
    try:
        auto_df = pd.read_csv(auto_path, encoding=ENCODING)
    except UnicodeDecodeError:
        print("    ⚠️ utf-8-sig 读取失败，尝试 latin-1...")
        auto_df = pd.read_csv(auto_path, encoding="latin-1")

    try:
        manual_df = pd.read_csv(manual_path, encoding=ENCODING)
    except UnicodeDecodeError:
        print("    ⚠️ utf-8-sig 读取失败，尝试 latin-1...")
        manual_df = pd.read_csv(manual_path, encoding="latin-1")

    print(f"    AI 全量标注：{len(auto_df)} 条")
    print(f"    人工金标准：  {len(manual_df)} 条")

    # 校验人工文件是否有 human_stance 列
    if "human_stance" not in manual_df.columns:
        raise ValueError("人工金标准文件缺少 'human_stance' 列，请确认文件是否正确。")

    # 规范化 human_stance：去空格、转小写、修正常见拼写错误
    manual_df["human_stance"] = (
        manual_df["human_stance"]
        .astype(str)
        .str.strip()
        .str.lower()
        .replace({"netural": "neutral", "neutural": "neutral", "cooprate": "cooperate"})
    )

    # 检查 human_stance 是否已填写
    filled = (manual_df["human_stance"].notna() & (manual_df["human_stance"] != "")).sum()
    empty = len(manual_df) - filled
    if empty > 0:
        print(f"    ⚠️ 人工金标准中有 {empty} 条 human_stance 为空！请先完成人工标注再运行。")
        if filled == 0:
            raise ValueError("human_stance 列全部为空，无法进行信度检验。")

    # 按 text 精确匹配
    auto_text_set = set(auto_df["text"].dropna())
    manual_df = manual_df.copy()
    manual_df["_matched"] = manual_df["text"].isin(auto_text_set)
    matched_count = manual_df["_matched"].sum()
    print(f"    text 匹配成功：{matched_count} / {len(manual_df)}")
    if matched_count < len(manual_df):
        missing = len(manual_df) - matched_count
        print(f"    ⚠️ {missing} 条金标准样本在全量语料中未找到对应 text")

    # 构建对齐表：取匹配成功的那部分
    # 用 text -> AI stance 的映射
    text_to_ai = dict(zip(auto_df["text"], auto_df["stance"]))
    text_to_tough = dict(zip(auto_df["text"], auto_df["tough_score"]))
    text_to_coop = dict(zip(auto_df["text"], auto_df["cooperate_score"]))

    gold = manual_df[manual_df["_matched"]].copy()
    gold["ai_stance"] = gold["text"].map(text_to_ai)
    gold["ai_tough_score"] = gold["text"].map(text_to_tough)
    gold["ai_cooperate_score"] = gold["text"].map(text_to_coop)

    # 只保留 human_stance 已填写的
    gold = gold[(gold["human_stance"].notna()) & (gold["human_stance"] != "")]

    print(f"    可用于信度检验的样本：{len(gold)} 条\n")
    return auto_df, gold


def compute_reliability(gold_df: pd.DataFrame) -> dict:
    """
    计算标注信度指标。

    返回
    ----
    dict
        包含 kappa, per_class_metrics, confusion_mat, grade, disagreements 等。
    """
    y_ai = gold_df["ai_stance"].values
    y_human = gold_df["human_stance"].values
    labels = ["tough", "cooperate", "neutral"]

    # ---- Cohen's Kappa ----
    kappa = cohen_kappa_score(y_human, y_ai)

    # ---- 信度等级 ----
    if kappa >= 0.8:
        grade = "优秀 (Kappa >= 0.8)"
    elif kappa >= 0.75:
        grade = "良好 (0.75 <= Kappa < 0.8)"
    elif kappa >= 0.6:
        grade = "一般 (0.6 <= Kappa < 0.75)"
    else:
        grade = "信度不足 (Kappa < 0.6)"

    # ---- 各类别精确率、召回率、F1 ----
    precision, recall, f1, support = precision_recall_fscore_support(
        y_human, y_ai, labels=labels, zero_division=0
    )

    per_class = {}
    for i, lbl in enumerate(labels):
        per_class[lbl] = {
            "precision": round(precision[i], 4),
            "recall": round(recall[i], 4),
            "f1": round(f1[i], 4),
            "support": int(support[i]),
        }

    # ---- 混淆矩阵 ----
    cm = confusion_matrix(y_human, y_ai, labels=labels)

    # ---- 分歧样本 ----
    gold_df = gold_df.copy()
    gold_df["disagree"] = gold_df["ai_stance"] != gold_df["human_stance"]
    disagreements = gold_df[gold_df["disagree"]].copy()

    # 分歧类型
    disagreements["conflict_type"] = disagreements.apply(
        lambda r: f"AI:{r['ai_stance']} → 人工:{r['human_stance']}", axis=1
    )

    return {
        "kappa": round(kappa, 4),
        "grade": grade,
        "per_class": per_class,
        "confusion_matrix": cm,
        "labels": labels,
        "disagreements": disagreements,
        "n_total": len(gold_df),
        "n_agree": len(gold_df) - len(disagreements),
        "n_disagree": len(disagreements),
        "agreement_rate": round((len(gold_df) - len(disagreements)) / len(gold_df) * 100, 2),
    }


def generate_reliability_report(results: dict) -> str:
    """生成格式化的信度报告文本。"""
    lines = []
    lines.append("=" * 65)
    lines.append("  标注信度检验报告")
    lines.append("=" * 65)
    lines.append(f"  生成时间：{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    lines.append(f"  检验样本数：{results['n_total']}")
    lines.append("")

    # Kappa
    lines.append(f"  Cohen's Kappa 系数：{results['kappa']}")
    lines.append(f"  信度等级：{results['grade']}")
    lines.append("")

    # 一致率
    lines.append(f"  人机一致样本数：{results['n_agree']}")
    lines.append(f"  人机分歧样本数：{results['n_disagree']}")
    lines.append(f"  总体一致率：{results['agreement_rate']}%")
    lines.append("")

    # 各类别指标
    lines.append("-" * 65)
    lines.append(f"  {'类别':<12s} {'精确率':>8s} {'召回率':>8s} {'F1值':>8s} {'支持数':>8s}")
    lines.append("-" * 65)
    for lbl, m in results["per_class"].items():
        lines.append(
            f"  {lbl:<12s} {m['precision']:>8.4f} {m['recall']:>8.4f} "
            f"{m['f1']:>8.4f} {m['support']:>8d}"
        )
    lines.append("-" * 65)
    lines.append("")

    # 混淆矩阵
    labels = results["labels"]
    cm = results["confusion_matrix"]
    lines.append("  混淆矩阵（行=人工金标准，列=AI预测）：")
    header = f"  {'':>12s}" + "".join(f"{lbl:>10s}" for lbl in labels)
    lines.append(header)
    for i, lbl_row in enumerate(labels):
        row_str = f"  {lbl_row:<12s}" + "".join(f"{cm[i][j]:>10d}" for j in range(len(labels)))
        lines.append(row_str)
    lines.append("")

    # 分歧类型统计
    if results["n_disagree"] > 0:
        lines.append("  分歧类型分布：")
        conflict_counts = results["disagreements"]["conflict_type"].value_counts()
        for ct, cnt in conflict_counts.items():
            lines.append(f"    {ct}: {cnt} 条 ({cnt/results['n_disagree']*100:.1f}%)")
    lines.append("")

    lines.append("=" * 65)
    return "\n".join(lines)


# =============================================================================
# 二、关键词权重优化模块
# =============================================================================

def optimize_keyword_weights(
    gold_df: pd.DataFrame,
    tough_compiled: dict,
    coop_compiled: dict,
) -> tuple:
    """
    基于 400 条人工金标准样本，逐关键词计算命中准确率并调整权重。

    算法：
      1. 遍历每条金标准样本，查找所有关键词匹配
      2. 对每个关键词，统计：
         - total: 在金标准样本中的总命中次数
         - correct: 命中时人工标注与关键词类别一致的次数
         - precision = correct / total
      3. 权重调整公式：
         - 命中次数 ≥ 3：new_weight = old_weight × clamp(precision, 0.3, 1.5)
         - 命中次数 < 3：沿用该关键词所在权重层级的平均调整系数
         - 未命中（total=0）：权重不变
      4. 输出优化后的关键词词典（结构与原词典一致）

    参数
    ----
    gold_df : pd.DataFrame
        含 text, human_stance 的金标准样本。
    tough_compiled : dict
        原 tough 类编译后关键词。
    coop_compiled : dict
        原 cooperate 类编译后关键词。

    返回
    ----
    tuple[dict, dict, pd.DataFrame]
        (优化后 tough 词典, 优化后 cooperate 词典, 关键词精度明细表)
    """
    print("\n[权重优化] 基于金标准计算关键词命中准确率...")

    # ---- 2.1 收集每条金标准样本的关键词命中情况 ----
    # keyword_stats: {keyword: {category, original_weight, total, correct}}
    keyword_stats = {}

    for _, row in gold_df.iterrows():
        text = str(row["text"]) if pd.notna(row["text"]) else ""
        human_stance = row["human_stance"]
        text_lower = text.lower()

        for category, compiled_dict in [("tough", tough_compiled), ("cooperate", coop_compiled)]:
            for weight, regex_list in compiled_dict.items():
                for kw_original, pattern in regex_list:
                    found = pattern.findall(text_lower)
                    if found:
                        if kw_original not in keyword_stats:
                            keyword_stats[kw_original] = {
                                "category": category,
                                "original_weight": weight,
                                "total": 0,
                                "correct": 0,
                            }
                        keyword_stats[kw_original]["total"] += 1
                        if human_stance == category:
                            keyword_stats[kw_original]["correct"] += 1

    # ---- 2.2 计算每个关键词的精度和调整系数 ----
    detail_rows = []
    for kw, stats in keyword_stats.items():
        total = stats["total"]
        correct = stats["correct"]
        precision = correct / total if total > 0 else 0.5  # 无数据默认 0.5
        stats["precision"] = round(precision, 4)

        detail_rows.append({
            "keyword": kw,
            "category": stats["category"],
            "original_weight": stats["original_weight"],
            "total_hits": total,
            "correct_hits": correct,
            "precision": round(precision, 4),
        })

    detail_df = pd.DataFrame(detail_rows)
    detail_df = detail_df.sort_values(["category", "precision"])

    # 打印精度概要
    for cat in ["tough", "cooperate"]:
        sub = detail_df[detail_df["category"] == cat]
        if len(sub) > 0:
            print(f"    {cat} 类关键词精度：均值={sub['precision'].mean():.3f}, "
                  f"中位={sub['precision'].median():.3f}, "
                  f"范围=[{sub['precision'].min():.3f}, {sub['precision'].max():.3f}]")
            # 列出精度极低的关键词
            low_prec = sub[sub["precision"] < 0.3].sort_values("precision")
            if len(low_prec) > 0:
                print(f"      精度 < 0.3（将被降权）：{len(low_prec)} 个")
                for _, r in low_prec.iterrows():
                    print(f"        {r['keyword']:<35s} precision={r['precision']:.3f}  hits={r['total_hits']}")

    # ---- 2.3 计算每个权重层级的平均调整系数 ----
    # 用于处理命中次数不足的关键词
    tier_adjustments = {}  # {(category, weight): avg_factor}
    for cat in ["tough", "cooperate"]:
        for weight in [2.0, 1.5, 1.0]:
            tier_kws = detail_df[
                (detail_df["category"] == cat) &
                (detail_df["original_weight"] == weight) &
                (detail_df["total_hits"] >= 3)  # 只统计有足够数据的
            ]
            if len(tier_kws) > 0:
                avg_precision = tier_kws["precision"].mean()
                # factor: precision 1.0 → 1.5x, 0.5 → 1.0x, 0.0 → 0.5x
                avg_factor = 0.5 + avg_precision
                tier_adjustments[(cat, weight)] = round(avg_factor, 4)
            else:
                tier_adjustments[(cat, weight)] = 1.0  # 无数据，保持原权重

    # ---- 2.4 构建优化后的关键词词典 ----
    def build_optimized_dict(original_dict: dict, category: str) -> dict:
        """根据关键词精度构建优化后的权重词典。"""
        optimized = {}
        for weight, kw_list in original_dict.items():
            new_entries = []
            for kw in kw_list:
                if kw in keyword_stats and keyword_stats[kw]["total"] >= 3:
                    # 有足够命中数据：使用个体精度调整
                    precision = keyword_stats[kw]["precision"]
                    # factor in [0.5, 1.5] range, clamped
                    factor = max(0.3, min(1.5, 0.5 + precision))
                    new_weight = round(weight * factor, 2)
                else:
                    # 命中数据不足：使用该层级平均调整系数
                    tier_factor = tier_adjustments.get((category, weight), 1.0)
                    new_weight = round(weight * tier_factor, 2)

                new_entries.append((new_weight, kw))

            # 将同权重（四舍五入）的关键词分组
            for nw, kw in new_entries:
                # 将调整后的权重四舍五入到最近的组
                rounded_weight = round(nw * 2) / 2  # 四舍五入到 0.5
                rounded_weight = max(0.5, min(3.0, rounded_weight))
                if rounded_weight not in optimized:
                    optimized[rounded_weight] = []
                optimized[rounded_weight].append(kw)

        return optimized

    optimized_tough = build_optimized_dict(TOUGH_KEYWORDS, "tough")
    optimized_cooperate = build_optimized_dict(COOPERATE_KEYWORDS, "cooperate")

    # 打印优化摘要
    print(f"\n    权重优化完成：")
    for cat, orig, opt in [("tough", TOUGH_KEYWORDS, optimized_tough),
                            ("cooperate", COOPERATE_KEYWORDS, optimized_cooperate)]:
        orig_total = sum(len(v) for v in orig.values())
        opt_total = sum(len(v) for v in opt.values())
        print(f"      {cat}: {orig_total} 个关键词 → 权重已调整")

    return optimized_tough, optimized_cooperate, detail_df


# =============================================================================
# 三、全量重标注 + 强制覆盖模块
# =============================================================================

def relabel_corpus(
    auto_df: pd.DataFrame,
    gold_df: pd.DataFrame,
    tough_opt: dict,
    coop_opt: dict,
) -> pd.DataFrame:
    """
    使用优化后的权重体系重标全量语料，并对金标准样本强制覆盖为人工标注。

    步骤：
      1. 预编译优化后的关键词正则
      2. 逐条重标全量数据（复用 compute_scores + classify_stance）
      3. 构建 text → human_stance 映射
      4. 对映射中存在的样本，强制 stance = human_stance

    参数
    ----
    auto_df : pd.DataFrame
        全量语料（含 text, year, source, theme）。
    gold_df : pd.DataFrame
        金标准样本（含 text, human_stance）。
    tough_opt : dict
        优化后的 tough 关键词。
    coop_opt : dict
        优化后的 cooperate 关键词。

    返回
    ----
    pd.DataFrame
        最终标注语料，字段：text, year, source, theme, stance
    """
    print("\n[重标注] 预编译优化后关键词...")
    tough_compiled = precompile_keywords(tough_opt)
    coop_compiled = precompile_keywords(coop_opt)

    total = len(auto_df)
    print(f"[重标注] 开始逐条标注全量语料（共 {total:,} 条）...")

    stances = []
    for i, row in auto_df.iterrows():
        if (i + 1) % 20000 == 0:
            print(f"    进度: {i+1:,} / {total:,}")

        text = str(row["text"]) if pd.notna(row["text"]) else ""
        tough_score, cooperate_score = compute_scores(text, tough_compiled, coop_compiled)
        stances.append(classify_stance(tough_score, cooperate_score))

    # 构建输出 DataFrame
    result = auto_df[["text", "year", "source", "theme"]].copy()
    result["stance"] = stances

    # ---- 强制覆盖：金标准样本以人工标注为准 ----
    text_to_human = dict(zip(gold_df["text"], gold_df["human_stance"]))
    gold_texts = set(text_to_human.keys())

    override_mask = result["text"].isin(gold_texts)
    override_count = override_mask.sum()
    result.loc[override_mask, "stance"] = result.loc[override_mask, "text"].map(text_to_human)

    print(f"    重标注完成。金标准覆盖：{override_count} 条")
    return result


# =============================================================================
# 四、输出与统计
# =============================================================================

def save_disagreements(disagreements: pd.DataFrame, output_path: str) -> None:
    """保存分歧样本文件。"""
    cols = ["sample_id", "text", "year", "source", "theme",
            "ai_stance", "human_stance", "ai_tough_score", "ai_cooperate_score", "conflict_type"]
    available = [c for c in cols if c in disagreements.columns]
    out = disagreements[available].copy()
    out.to_csv(output_path, index=False, encoding=ENCODING)
    print(f"\n✅ 分歧样本已保存：{output_path}")
    print(f"   共 {len(out)} 条")


def save_reliability_report(report_text: str, output_path: str) -> None:
    """保存信度报告。"""
    with open(output_path, "w", encoding="utf-8") as f:
        f.write(report_text)
    print(f"✅ 信度报告已保存：{output_path}")


def save_final_corpus(df: pd.DataFrame, output_path: str) -> None:
    """保存最终标注语料。"""
    df.to_csv(output_path, index=False, encoding=ENCODING)
    print(f"✅ 最终标注语料已保存：{output_path}")
    print(f"   行数：{len(df):,}，列：{list(df.columns)}")


def print_final_stats(df: pd.DataFrame) -> None:
    """打印最终全量语料统计信息。"""
    total = len(df)
    print("\n" + "=" * 65)
    print("  最终全量语料统计")
    print("=" * 65)
    print(f"\n  总样本量：{total:,}")

    # 三类立场占比
    print(f"\n  三类立场占比：")
    stance_counts = df["stance"].value_counts()
    for s in ["tough", "cooperate", "neutral"]:
        cnt = stance_counts.get(s, 0)
        pct = cnt / total * 100
        bar = "█" * max(1, int(pct / 2))
        print(f"    {s:<12s} {cnt:>8,}  ({pct:>5.1f}%)  {bar}")

    # 各年份立场分布
    print(f"\n  各年份立场分布：")
    years_sorted = sorted(df["year"].unique())
    header = f"    {'Year':>6s}  {'Total':>8s}  {'tough%':>7s}  {'cooperate%':>10s}  {'neutral%':>8s}"
    print(header)
    print("    " + "-" * 55)
    for y in years_sorted:
        subset = df[df["year"] == y]
        n = len(subset)
        t = (subset["stance"] == "tough").sum() / n * 100 if n > 0 else 0
        c = (subset["stance"] == "cooperate").sum() / n * 100 if n > 0 else 0
        nu = (subset["stance"] == "neutral").sum() / n * 100 if n > 0 else 0
        print(f"    {str(y):>6s}  {n:>8,}  {t:>6.1f}%  {c:>9.1f}%  {nu:>7.1f}%")

    print("\n" + "=" * 65)


# =============================================================================
# 五、主流程
# =============================================================================

def main():
    print("=" * 65)
    print("  标注信度检验 + 全量语料标签优化修正")
    print(f"  启动时间：{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("=" * 65)

    # ==================== 一、信度检验 ====================
    print("\n" + "-" * 40)
    print("  一、信度检验模块")
    print("-" * 40)

    # 1.1 加载并对齐数据
    auto_df, gold_df = load_and_align(AUTO_LABELED_PATH, MANUAL_CHECK_PATH)

    # 1.2 计算信度指标
    reliability = compute_reliability(gold_df)

    # 1.3 打印结果到控制台
    print(f"    Cohen's Kappa: {reliability['kappa']}")
    print(f"    信度等级: {reliability['grade']}")
    print(f"    一致率: {reliability['agreement_rate']}% ({reliability['n_agree']}/{reliability['n_total']})")
    print(f"    分歧样本: {reliability['n_disagree']} 条")
    print(f"\n    各类别指标:")
    for lbl, m in reliability["per_class"].items():
        print(f"      {lbl:<12s} P={m['precision']:.4f}  R={m['recall']:.4f}  F1={m['f1']:.4f}  N={m['support']}")

    # 1.4 生成并保存信度报告
    report_text = generate_reliability_report(reliability)
    save_reliability_report(report_text, OUTPUT_RELIABILITY)
    print(report_text)  # 同时打印到控制台

    # 1.5 保存分歧样本
    save_disagreements(reliability["disagreements"], OUTPUT_DISAGREEMENT)

    # ==================== 二、权重优化 ====================
    print("\n" + "-" * 40)
    print("  二、关键词权重优化模块")
    print("-" * 40)

    # 2.1 预编译原关键词
    tough_orig_compiled = precompile_keywords(TOUGH_KEYWORDS)
    coop_orig_compiled = precompile_keywords(COOPERATE_KEYWORDS)

    # 2.2 优化权重
    tough_opt, coop_opt, kw_detail_df = optimize_keyword_weights(
        gold_df, tough_orig_compiled, coop_orig_compiled
    )

    # 2.3 打印优化后的权重分布
    print(f"\n    优化后 tough 权重分布：")
    for w in sorted(tough_opt.keys(), reverse=True):
        print(f"      权重 {w:.1f}: {len(tough_opt[w])} 个关键词")
    print(f"    优化后 cooperate 权重分布：")
    for w in sorted(coop_opt.keys(), reverse=True):
        print(f"      权重 {w:.1f}: {len(coop_opt[w])} 个关键词")

    # ==================== 三、全量重标注 ====================
    print("\n" + "-" * 40)
    print("  三、全量重标注与强制覆盖")
    print("-" * 40)

    final_df = relabel_corpus(auto_df, gold_df, tough_opt, coop_opt)

    # 保存最终语料
    save_final_corpus(final_df, OUTPUT_FINAL_CORPUS)

    # 打印统计
    print_final_stats(final_df)

    # ==================== 完成 ====================
    print("\n" + "=" * 65)
    print("  🎉 全部完成！")
    print("=" * 65)
    print(f"""
  输出文件：
    1. 信度报告：{OUTPUT_RELIABILITY}
    2. 分歧样本：{OUTPUT_DISAGREEMENT}
    3. 最终标注语料：{OUTPUT_FINAL_CORPUS}
""")


if __name__ == "__main__":
    main()
