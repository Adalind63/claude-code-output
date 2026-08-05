# -*- coding: utf-8 -*-
r"""
欧盟对华贸易英文语料自动标注脚本
加权计分制 + 语境约束（否定反转 / 转折加权 / 情态辅助） -> tough / cooperate / neutral 三分类
依赖：pandas, re（标准库）
"""

import pandas as pd
import re

# ============================================================
# 1. 路径配置
# ============================================================
INPUT_PATH = r"D:\项目流程\clean_corpus.csv"
OUTPUT_LABELED = r"D:\项目流程\auto_labeled_corpus.csv"
OUTPUT_FUZZY = r"D:\项目流程\fuzzy_samples.csv"

STANCE_THRESHOLD = 0.8  # 得分差值阈值

# ============================================================
# 2. 分级关键词权重词典（词根形式，自动匹配同根词形）
#    tough 类：欧盟对华强硬/防御话语
#    cooperate 类：欧盟对华合作/接触话语
#    （每组为 (权重, [关键词列表])）
# ============================================================
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


# ============================================================
# 3. 关键词 -> 正则表达式（自动匹配同根词形）
# ============================================================
def build_keyword_regex(keyword: str) -> str:
    """
    将关键词转为匹配同根词形的正则表达式。
    单字词：\b词根\w*\b → 自动覆盖 -ing/-ed/-tion/-ive 等后缀
    多字短语：逐词匹配，允许中间一个连字符或空格的可选变体
    特殊：处理 de-risk/de risk/derisk 等连字符变体
    """
    # 预处理：处理 de-risk / de risk / derisk 等变体
    kw_clean = keyword.lower().strip()

    words = kw_clean.split()
    patterns = []

    for w in words:
        # 小词（a, of, to, the, and 等）自身不变化
        if w in ('a', 'an', 'the', 'of', 'to', 'in', 'on', 'at', 'by', 'for', 'and', 'or'):
            patterns.append(re.escape(w))
            continue

        # 对关键词取词根：截断常见后缀
        stem = re.sub(
            r'(ing|ed|es|s|tion|sion|ive|ment|al|ly|ance|ence|able|ible|ise|ize|ship|ness|ity|ous|ful|less)$',
            '',
            w,
        )
        # 截短后至少保留 4 个字符，避免过度泛化
        if len(stem) < 4:
            stem = w

        # 处理 de- 前缀变体：de risk / de-risk / derisk 都可匹配
        if stem.startswith('de') and len(stem) > 4:
            # de-risk -> de[- ]?risk
            stem_no_de = stem[2:]
            patterns.append(r'(?:de[- ]?)?' + re.escape(stem_no_de) + r'\w*')
        else:
            patterns.append(re.escape(stem) + r'\w*')

    # 多词短语：词间允许空格或连字符
    joiner = r'[\s\-]+'
    return r'\b' + joiner.join(patterns) + r'\b'


# 预编译所有关键词正则（按权重分组）
def precompile_keywords(kw_dict: dict) -> dict:
    """预编译关键词正则，返回 {权重: [(原始关键词, compiled_regex), ...]}"""
    compiled = {}
    for weight, kw_list in kw_dict.items():
        compiled[weight] = []
        for kw in kw_list:
            pattern = build_keyword_regex(kw)
            compiled[weight].append((kw, re.compile(pattern, re.IGNORECASE)))
    return compiled


# ============================================================
# 4. 否定词 / 转折词 / 情态词 定义
# ============================================================
NEGATION_TERMS = [
    r'\bnot\b', r'\bno\b', r'\bhardly\b', r'\bnever\b',
    r'\bwithout\b', r'\black\s+of\b', r'\bfail(?:ed|s|ing)?\s+to\b',
    r'\bneither\b', r'\bnor\b', r'\babsence\s+of\b',
    r'\bdoes\s+not\b', r'\bdo\s+not\b', r'\bdid\s+not\b',
    r'\bcannot\b', r'\bcan\s+not\b', r'\bwill\s+not\b',
    r'\bunable\s+to\b', r'\brefuse(?:s|d)?\s+to\b',
]
NEGATION_RE = re.compile('|'.join(NEGATION_TERMS), re.IGNORECASE)

# 强转折连词：后半句 ×1.3，前半句 ×0.4
STRONG_CONTRAST = [r'\bbut\b', r'\bhowever\b', r'\bnevertheless\b',
                   r'\bnonetheless\b', r'\byet\b', r'\binstead\b']
STRONG_CONTRAST_RE = re.compile('|'.join(STRONG_CONTRAST), re.IGNORECASE)

# 弱转折连词：后半句 ×1.1，前半句 ×0.8
WEAK_CONTRAST = [r'\bwhile\b', r'\balthough\b', r'\bthough\b',
                 r'\bwhereas\b', r'\bdespite\b', r'\bin\s+spite\s+of\b']
WEAK_CONTRAST_RE = re.compile('|'.join(WEAK_CONTRAST), re.IGNORECASE)

# 强硬类情态动词
TOUGH_MODALS = [r'\bmust\b', r'\bshould\b', r'\bneed\s+to\b',
                r'\bhave\s+to\b', r'\bhas\s+to\b', r'\brequired\s+to\b',
                r'\bobliged\s+to\b', r'\bshall\b']
TOUGH_MODALS_RE = re.compile('|'.join(TOUGH_MODALS), re.IGNORECASE)

# 合作类情态动词
COOPERATE_MODALS = [r'\bcan\b', r'\bcould\b', r'\bmay\b', r'\bmight\b',
                    r'\bwilling\s+to\b', r'\bready\s+to\b', r'\bpossible\s+to\b']
COOPERATE_MODALS_RE = re.compile('|'.join(COOPERATE_MODALS), re.IGNORECASE)


# ============================================================
# 5. 核心标注函数
# ============================================================
def find_keyword_matches(text: str, compiled_dict: dict) -> list[dict]:
    """
    在文本中查找所有关键词匹配，返回 [{start, end, weight, keyword, category}, ...]
    category: 'tough' or 'cooperate'
    """
    # 确定类别名
    first_kw = list(compiled_dict[list(compiled_dict.keys())[0]])[0][0]
    # 根据第一个词的权重判断类别——这里改成传参
    return []  # placeholder, will be implemented differently


def compute_scores(text: str,
                   tough_compiled: dict,
                   coop_compiled: dict) -> tuple:
    """
    对单条文本执行完整标注流程，返回 (tough_score, cooperate_score)。

    步骤：
      ① 找到所有关键词匹配及其位置
      ② 应用否定反转：前后 5 词含否定 -> 反转入对立立场
      ③ 应用转折加权：句子中位置决定权重倍率
      ④ 应用情态辅助：全文本模态词总加分
    """
    text_lower = text.lower()
    words = text_lower.split()          # 用于"前后5词"窗口检查
    word_positions = []                 # 每个词在原文中的起始位置
    pos = 0
    for w in text_lower.split():
        # 跳过连续空格找到词的实际位置
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

    # 去重：重叠匹配保留权重最高的
    matches.sort(key=lambda x: (x['start'], -x['weight']))
    deduped = []
    for m in matches:
        if deduped and m['start'] < deduped[-1]['end']:
            continue  # 与前一个重叠，跳过
        deduped.append(m)
    matches = deduped

    # ---- ② 否定反转 ----
    def has_negation_in_window(match_start_char: int, match_end_char: int) -> bool:
        """检查匹配位置前后 5 个单词内是否有否定词"""
        # 找到匹配词在 words 列表中的索引范围
        match_word_start = None
        match_word_end = None
        for i, wp in enumerate(word_positions):
            if wp <= match_start_char < wp + 100:  # 近似匹配
                if match_word_start is None:
                    match_word_start = i
                if wp >= match_end_char:
                    match_word_end = i
                    break

        if match_word_start is None:
            match_word_start = 0
        if match_word_end is None:
            match_word_end = len(words) - 1

        # 前后 5 词窗口
        window_start = max(0, match_word_start - 5)
        window_end = min(len(words), match_word_end + 5)
        window_text = ' '.join(words[window_start:window_end])

        return bool(NEGATION_RE.search(window_text))

    # ---- ③ 转折加权 ----
    # 先将文本按句子拆分（简单规则：.?! 后跟空格+大写）
    sentence_splits = [-1]
    for m in re.finditer(r'[.!?]\s+(?=[A-Z])', text_lower):
        sentence_splits.append(m.start() + 1)
    sentence_splits.append(len(text_lower))

    def get_contrast_multiplier(match_start: int) -> float:
        """根据匹配词相对转折词的位置返回权重倍率"""
        # 找匹配词所在的句子索引
        sent_idx = 0
        for i in range(len(sentence_splits) - 1):
            if sentence_splits[i] < match_start <= sentence_splits[i + 1]:
                sent_idx = i
                break

        # 检查最近的前后句子中是否有转折词
        sent_start = sentence_splits[sent_idx] + 1
        sent_end = sentence_splits[sent_idx + 1]
        sent_text = text_lower[sent_start:sent_end] if sent_end > sent_start else ''

        # 在当前句中找转折词
        strong_matches = list(STRONG_CONTRAST_RE.finditer(sent_text))
        weak_matches = list(WEAK_CONTRAST_RE.finditer(sent_text))

        mult = 1.0
        for sm in strong_matches:
            contrast_pos_in_sent = sm.start()
            match_pos_in_sent = match_start - sent_start
            if match_pos_in_sent > contrast_pos_in_sent:
                mult *= 1.3  # 在转折词之后
            else:
                mult *= 0.4  # 在转折词之前

        for wm in weak_matches:
            contrast_pos_in_sent = wm.start()
            match_pos_in_sent = match_start - sent_start
            if match_pos_in_sent > contrast_pos_in_sent:
                mult *= 1.1
            else:
                mult *= 0.8

        return mult

    # ---- ④ 累加得分 ----
    tough_score = 0.0
    cooperate_score = 0.0

    for m in matches:
        weight = m['weight']
        category = m['category']

        # 否定反转检查
        negated = has_negation_in_window(m['start'], m['end'])

        # 转折倍率
        contrast_mult = get_contrast_multiplier(m['start'])

        # 最终权重
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

    # ---- ⑤ 情态辅助加分 ----
    # 若文本中有关键词命中（不计否定反转），则检查情态动词
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
      tough - cooperate > 0.8  -> tough
      cooperate - tough > 0.8  -> cooperate
      差值 <= 0.8 / 无命中     -> neutral（模糊样本）
    """
    diff = tough - cooperate
    if diff > STANCE_THRESHOLD:
        return "tough"
    elif -diff > STANCE_THRESHOLD:
        return "cooperate"
    else:
        return "neutral"


# ============================================================
# 6. 主流程
# ============================================================
def main():
    print("=" * 60)
    print("加载关键词词典并预编译正则...")
    tough_compiled = precompile_keywords(TOUGH_KEYWORDS)
    coop_compiled = precompile_keywords(COOPERATE_KEYWORDS)

    tough_kw_count = sum(len(v) for v in TOUGH_KEYWORDS.values())
    coop_kw_count = sum(len(v) for v in COOPERATE_KEYWORDS.values())
    print(f"tough 类关键词: {tough_kw_count} 条")
    print(f"cooperate 类关键词: {coop_kw_count} 条")

    # ---- 6.1 读取语料 ----
    print(f"\n读取语料: {INPUT_PATH}")
    df = pd.read_csv(INPUT_PATH, encoding="utf-8-sig")
    total = len(df)
    print(f"总行数: {total:,}\n")

    # ---- 6.2 逐条标注 ----
    print("开始标注...")
    results = []
    for i, row in df.iterrows():
        if (i + 1) % 10000 == 0:
            print(f"  标注进度: {i+1:,} / {total:,}")

        text = str(row['text']) if pd.notna(row['text']) else ''
        year = str(row['year']) if pd.notna(row['year']) else ''
        source = str(row['source']) if pd.notna(row['source']) else ''
        theme = str(row['theme']) if pd.notna(row['theme']) else ''

        tough_score, cooperate_score = compute_scores(text, tough_compiled, coop_compiled)
        stance = classify_stance(tough_score, cooperate_score)

        results.append({
            'text': text,
            'year': year,
            'source': source,
            'theme': theme,
            'tough_score': tough_score,
            'cooperate_score': cooperate_score,
            'stance': stance,
        })

    result_df = pd.DataFrame(results)

    # ---- 6.3 输出全量标注文件 ----
    result_df.to_csv(OUTPUT_LABELED, encoding="utf-8-sig", index=False)
    print(f"\n全量标注文件: {OUTPUT_LABELED}")
    print(f"总行数: {len(result_df):,}")

    # ---- 6.4 输出模糊样本 ----
    fuzzy_df = result_df[result_df['stance'] == 'neutral'].copy()
    fuzzy_df.to_csv(OUTPUT_FUZZY, encoding="utf-8-sig", index=False)
    print(f"模糊样本文件: {OUTPUT_FUZZY}")
    print(f"模糊样本数: {len(fuzzy_df):,}")

    # ---- 6.5 统计报告 ----
    print(f"\n{'=' * 60}")
    print("立场分布统计")
    print(f"{'=' * 60}")
    stance_counts = result_df['stance'].value_counts()
    for s in ['tough', 'cooperate', 'neutral']:
        cnt = stance_counts.get(s, 0)
        pct = cnt / len(result_df) * 100
        bar = "#" * max(1, int(pct / 2))
        print(f"  {s:>10s}: {cnt:>8,}  ({pct:5.1f}%)  {bar}")

    # 各年份立场占比
    print(f"\n{'=' * 60}")
    print("各年份立场占比")
    print(f"{'=' * 60}")
    years_sorted = sorted(result_df['year'].unique(), key=lambda x: (x == '', x))
    print(f"  {'Year':>6s}  {'Total':>8s}  {'tough%':>7s}  {'cooperate%':>10s}  {'neutral%':>8s}")
    for y in years_sorted:
        subset = result_df[result_df['year'] == y]
        n = len(subset)
        t = (subset['stance'] == 'tough').sum() / n * 100
        c = (subset['stance'] == 'cooperate').sum() / n * 100
        nu = (subset['stance'] == 'neutral').sum() / n * 100
        label = y if y else '未知'
        print(f"  {label:>6s}  {n:>8,}  {t:>6.1f}%  {c:>9.1f}%  {nu:>7.1f}%")

    # 得分分布
    print(f"\n{'=' * 60}")
    print("得分分布")
    print(f"{'=' * 60}")
    for label, col in [('tough_score', 'tough_score'), ('cooperate_score', 'cooperate_score')]:
        series = result_df[col]
        nonzero = (series > 0).sum()
        print(f"  {label}:")
        print(f"    非零样本: {nonzero:,} / {len(series):,} ({nonzero/len(series)*100:.1f}%)")
        if nonzero > 0:
            print(f"    非零均值: {series[series > 0].mean():.2f}")
            print(f"    非零最大: {series[series > 0].max():.2f}")

    print(f"\n全部完成。")


if __name__ == "__main__":
    main()
