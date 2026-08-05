# -*- coding: utf-8 -*-
r"""
欧盟对华贸易英文语料清洗与 BERT 切块预处理脚本
功能：
  1. 基础清洗：去页码/网址/邮箱/表格行 -> 过滤碎片
  2. spaCy 分句：识别 .?! 边界，不拆分 U.S. / EU 等缩写
  3. BERT tokenizer 计数 -> 重叠滑动切块（450 token/块，重叠3句）
  4. 每个语块继承 year / source / theme
输出：D:\项目流程\clean_corpus.csv

依赖：pip install pandas spacy transformers
      python -m spacy download en_core_web_md
"""

import pandas as pd
import spacy
import re
from transformers import BertTokenizer

# ============================================================
# 1. 路径与超参数配置
# ============================================================
INPUT_PATH = r"D:\项目流程\all_corpus_total.csv"
OUTPUT_PATH = r"D:\项目流程\clean_corpus.csv"

MAX_TOKENS = 450         # 单块最大 BERT token 数（绝不拆分单句）
OVERLAP_SENTS = 3        # 块间重叠的完整句子数
MIN_WORDS_TEXT = 15      # 基础清洗：文本最少单词数，低于此视为碎片丢弃
MIN_WORDS_CHUNK = 20     # 最终语块：单词数低于此的块丢弃

# ============================================================
# 2. 加载模型（sentencizer 纯规则模式，零显存，10x 加速）
# ============================================================
print("加载 spaCy 模型 en_core_web_md（sentencizer 模式）...")
nlp = spacy.load(
    "en_core_web_md",
    disable=["tok2vec", "tagger", "parser", "ner", "lemmatizer", "attribute_ruler"],
)
if "sentencizer" not in nlp.pipe_names:
    nlp.add_pipe("sentencizer")  # 纯规则分句，tokenizer 自带 U.S./EU 缩写例外

print("加载 BERT tokenizer（bert-base-cased，保留大小写）...")
tokenizer = BertTokenizer.from_pretrained("bert-base-cased")
print("模型加载完成。\n")


# ============================================================
# 3. 基础清洗函数
# ============================================================
def remove_urls(text: str) -> str:
    """删除 URL：http/https/www"""
    text = re.sub(r'https?://\S+|www\.\S+', ' ', text)
    return text


def remove_emails(text: str) -> str:
    """删除邮箱地址"""
    text = re.sub(r'\S+@\S+\.\S+', ' ', text)
    return text


def remove_page_numbers(text: str) -> str:
    r"""删除页码标记：Page 5 / p.3 / p. 3 / 独立行 - 5 - 等形式"""
    text = re.sub(r'\b[Pp]age\s*\d+\b', ' ', text)
    text = re.sub(r'\b[Pp]\.\s*\d+\b', ' ', text)
    text = re.sub(r'\b[Pp]\.\d+\b', ' ', text)
    # 独立成行的 "- 数字 -" 页码（行首行尾均为空白的情况）
    text = re.sub(r'^\s*[-–—]+\s*\d+\s*[-–—]+\s*$', ' ', text, flags=re.MULTILINE)
    return text


def is_numeric_table_row(line: str) -> bool:
    """
    判断是否为表格纯数字行。
    去除数字、空格、标点、货币符号后，剩余字母不足3个 -> 视为表格行。
    """
    stripped = line.strip()
    if not stripped:
        return False
    cleaned = re.sub(
        r'[\d\s\.\,\|\-\+\/\*\t\%\$\€\£\¥\(\)\[\]\{\}\:\;\=\<\>\~\#\@\&\^]',
        '',
        stripped,
    )
    alpha_chars = re.findall(r'[a-zA-Z]', cleaned)
    return len(alpha_chars) < 3 and len(stripped) > 5


def normalize_whitespace(text: str) -> str:
    """规范化空白：合并多余换行（>2）和空格，去首尾空白"""
    text = text.replace('\r\n', '\n')              # CRLF -> LF
    text = re.sub(r'\n{3,}', '\n\n', text)          # 最多保留2个连续换行
    text = re.sub(r'[ \t]+', ' ', text)             # 合并水平空白
    text = re.sub(r'^[ \t]+', '', text, flags=re.MULTILINE)
    text = re.sub(r'[ \t]+$', '', text, flags=re.MULTILINE)
    return text.strip()


def basic_clean(text: str) -> str | None:
    """
    对单条文本执行全部基础清洗。
    保留大小写、情态动词、否定词、停用词（CDA 分析需要这些特征）。
    返回清洗后文本；单词 < MIN_WORDS_TEXT 则返回 None（碎片丢弃）。
    """
    if not isinstance(text, str) or not text.strip():
        return None

    text = remove_urls(text)
    text = remove_emails(text)
    text = remove_page_numbers(text)

    # 按行过滤表格纯数字行
    lines = text.split('\n')
    text = '\n'.join(line for line in lines if not is_numeric_table_row(line))

    # 规范化空白
    text = normalize_whitespace(text)

    # 过滤单词过少的碎片
    if len(text.split()) < MIN_WORDS_TEXT:
        return None

    return text


# ============================================================
# 4. 句子分割（spaCy sentencizer，自动处理 U.S./EU 等缩写）
# ============================================================
def segment_sentences(text: str) -> list[str]:
    """
    用 spaCy 将文本切分为完整句子列表。
    tokenizer 内置缩写例外表，不会在 U.S. / EU / Art. 等处误拆分。
    """
    doc = nlp(text)
    return [sent.text.strip() for sent in doc.sents if sent.text.strip()]


# ============================================================
# 5. 重叠滑动切块
# ============================================================
def build_chunks(
    sentences: list[str],
    year: str,
    source: str,
    theme: str,
) -> list[dict]:
    """
    以完整句子为单位累加 BERT token，构建重叠语块。

    规则：
      - 按顺序累加句子，总 token <= MAX_TOKENS
      - 下一块起点 = 当前块末端回退 OVERLAP_SENTS 句
      - 单句 > MAX_TOKENS 时独立成块，绝不拆分
      - 过滤最终单词数 < MIN_WORDS_CHUNK 的语块
    """
    if not sentences:
        return []

    # ---- 预计算每个句子的 BERT token 数和单词数 ----
    sent_data = []
    for sent in sentences:
        token_ids = tokenizer.encode(sent, add_special_tokens=False)
        sent_data.append({
            'text': sent,
            'token_count': len(token_ids),
            'word_count': len(sent.split()),
        })

    chunks = []
    chunk_start = 0
    total_sents = len(sent_data)

    while chunk_start < total_sents:
        # ---- 累加句子至接近 450 tokens ----
        current_tokens = 0
        chunk_end = chunk_start

        for i in range(chunk_start, total_sents):
            st = sent_data[i]['token_count']
            if current_tokens + st <= MAX_TOKENS:
                current_tokens += st
                chunk_end = i + 1
            else:
                # 首个句子本身就超长：强制包含，不拆分
                if i == chunk_start:
                    chunk_end = i + 1
                break

        # ---- 生成当前语块 ----
        chunk_sents = sent_data[chunk_start:chunk_end]
        chunk_text = ' '.join(s['text'] for s in chunk_sents)
        chunk_words = sum(s['word_count'] for s in chunk_sents)

        if chunk_words >= MIN_WORDS_CHUNK:
            chunks.append({
                'text': chunk_text,
                'year': year,
                'source': source,
                'theme': theme,
            })

        # ---- 下一块起点：回退实现重叠 ----
        chunk_start = max(chunk_start + 1, chunk_end - OVERLAP_SENTS)

    return chunks


# ============================================================
# 6. 主流程
# ============================================================
def main():
    # ---- 6.1 读取原始语料 ----
    print("读取原始语料...")
    df = pd.read_csv(INPUT_PATH, encoding="utf-8-sig")
    total_rows = len(df)
    print(f"读取行数: {total_rows:,}\n")

    # ---- 6.2 基础清洗 ----
    print("基础清洗（去页码/网址/邮箱/表格行/碎片）...")
    texts_to_process = []   # 清洗后的文本
    metadata = []           # 对应元数据 (year, source, theme)

    for i, row in df.iterrows():
        if (i + 1) % 500 == 0:
            print(f"  清洗进度: {i+1:,} / {total_rows:,}")

        cleaned = basic_clean(row['text'])
        if cleaned is not None:
            texts_to_process.append(cleaned)
            # 安全处理 NaN：空值转为空字符串
            year_val = row.get('year', '')
            source_val = row.get('source', '')
            theme_val = row.get('theme', '')
            metadata.append((
                '' if pd.isna(year_val) else str(year_val).strip(),
                '' if pd.isna(source_val) else str(source_val).strip(),
                '' if pd.isna(theme_val) else str(theme_val).strip(),
            ))

    n_clean = len(texts_to_process)
    print(f"清洗完成: 保留 {n_clean:,} 行，过滤 {total_rows - n_clean:,} 行\n")

    if not texts_to_process:
        print("无有效数据，退出。")
        return

    # ---- 6.3 spaCy 批量分句 + BERT 切块 ----
    print("spaCy 分句 + BERT tokenizer 滑动切块...")
    all_chunks = []
    batch_size = 64  # 全文档较长，用小批次

    for batch_start in range(0, n_clean, batch_size):
        batch_end = min(batch_start + batch_size, n_clean)
        batch_texts = texts_to_process[batch_start:batch_end]
        batch_meta = metadata[batch_start:batch_end]

        # spaCy 批量处理
        docs = list(nlp.pipe(batch_texts))

        # 每篇文档：分句 -> 切块
        for doc, (year, source, theme) in zip(docs, batch_meta):
            sentences = [sent.text.strip() for sent in doc.sents if sent.text.strip()]
            chunks = build_chunks(sentences, year, source, theme)
            all_chunks.extend(chunks)

        if (batch_end) % 500 == 0 or batch_end == n_clean:
            print(f"  处理进度: {batch_end:,} / {n_clean:,}，已生成语块: {len(all_chunks):,}")

    print(f"切块完成，共生成语块: {len(all_chunks):,}")

    # ---- 6.4 输出 ----
    result_df = pd.DataFrame(all_chunks, columns=['text', 'year', 'source', 'theme'])

    # 最终去重（重叠切块可能产生完全相同的语块）
    before_final = len(result_df)
    result_df = result_df.drop_duplicates(subset=['text'], keep='first')
    if len(result_df) < before_final:
        print(f"最终去重: 剔除 {before_final - len(result_df):,} 条")

    result_df.to_csv(OUTPUT_PATH, encoding="utf-8-sig", index=False)

    # ---- 6.5 汇总报告 ----
    valid_year = result_df.loc[(result_df['year'].notna()) & (result_df['year'] != ''), 'year']
    has_source = (result_df['source'].notna() & (result_df['source'] != '')).sum()
    has_theme = (result_df['theme'].notna() & (result_df['theme'] != '')).sum()

    print(f"\n{'=' * 60}")
    print(f"输出文件: {OUTPUT_PATH}")
    print(f"总语块数: {len(result_df):,}")
    print(f"字段: {list(result_df.columns)}")
    if len(valid_year) > 0:
        print(f"年份范围: {valid_year.min()} ~ {valid_year.max()}")
    print(f"有来源信息: {has_source:,} / {len(result_df):,}")
    print(f"有议题标签: {has_theme:,} / {len(result_df):,}")

    # 语块 token 数分布
    token_counts = result_df['text'].apply(
        lambda t: len(tokenizer.encode(t, add_special_tokens=False))
    )
    print(f"\n语块 token 数分布:")
    print(f"  最小: {token_counts.min()}")
    print(f"  25%分位: {token_counts.quantile(0.25):.0f}")
    print(f"  中位数: {token_counts.quantile(0.50):.0f}")
    print(f"  75%分位: {token_counts.quantile(0.75):.0f}")
    print(f"  最大: {token_counts.max()}")
    print(f"  平均值: {token_counts.mean():.0f}")

    # 年份分布
    year_counts = result_df['year'].replace('', '未知').value_counts().sort_index()
    print(f"\n年份分布:")
    for y, c in year_counts.items():
        bar = "#" * max(1, c // max(1, year_counts.max() // 40))
        print(f"  {y:>6s}: {c:>6,}  {bar}")

    print(f"\n全部完成。")


if __name__ == "__main__":
    main()
