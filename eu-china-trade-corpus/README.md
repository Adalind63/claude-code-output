# EU-China Trade Policy English Corpus Collector

采集欧盟对华贸易政策英文法律语料的 Python 程序，使用欧盟官方 **SPARQL 端点** 和 **EUR-Lex API**，不依赖任何网页爬虫库。

## 数据源

- SPARQL 端点: `https://publications.europa.eu/webapi/rdf/sparql`
- 文档下载: `https://eur-lex.europa.eu/legal-content/EN/TXT/HTML/`

## 覆盖议题

trade, anti-dumping, anti-subsidy, subsidy, tariff, steel, electric vehicle, renewable energy, semiconductor, critical raw material, market access, digital trade, investment screening, FDI, intellectual property, carbon border adjustment (CBAM), industrial policy

## 采集参数

- **时间范围**: 2017–2026
- **语种**: 英文
- **文档类型**: 条例 (Regulation)、决议 (Decision)、报告 (Report)、声明 (Declaration)、白皮书 (White Paper)
- **检索词**: China / Chinese + 19 个贸易关键词

## 快速开始

### 依赖

```bash
pip install requests lxml PyPDF2
```

### 运行

```bash
# 完整采集 (SPARQL检索 + 下载 + 处理)
python eu_china_corpus_collector.py

# 仅重新处理已下载文件 (分类/校验/导出TXT)
python reprocess.py
```

### 自定义配置

编辑 `eu_china_corpus_collector.py` 顶部的常量区：

```python
BASE_DIR = os.path.join("D:", os.sep, "项目流程", "eu_corpus")  # 输出目录
YEAR_START = 2017   # 起始年份
YEAR_END = 2026     # 结束年份
REQUEST_INTERVAL = 1.5  # 请求间隔(秒)
```

## 输出结构

```
eu_corpus/
├── xml/          # HTML 原文 (241 files)
├── txt/          # 纯文本语料 (221 files, ~18 MB)
├── pdf/          # PDF 校验样本
└── csv/          # 清单与校验表
    ├── eu_china_celex_list.csv      # 主清单 (268条)
    ├── xml_structure_check.csv      # 结构校验
    ├── invalid_document.csv         # 低相关性文档
    ├── missing_celex.csv            # 下载缺失清单
    └── collection_summary.json      # 采集总结
```

## 采集流程

1. **SPARQL 检索** — 查询 2017-2026 年标题含 China + 贸易关键词的英文文档
2. **本地过滤** — 排除港澳台、非贸易相关文档
3. **批量下载** — 通过 EUR-Lex API 下载 HTML 全文
4. **语义校验** — 全文二次确认 China + ≥2 个贸易关键词
5. **自动分类** — 按议题（新能源/补贴调查/钢铁/半导体等）分类标注
6. **双层校验** — XML 结构统计 + PDF 文本相似度
7. **TXT 导出** — 每份文档独立纯文本文件

## 采集结果 (2026-07)

| 指标 | 数值 |
|------|------|
| SPARQL 命中 | 322 |
| 贸易相关 | 268 |
| 下载成功 | 241 (89.9%) |
| TXT 导出 | 221 (82.5%) |

### 年份分布

| 2023 | 2024 | 2025 | 2026 |
|------|------|------|------|
| 25 | 83 | 99 | 61 |

### 议题分布

| 新能源 | 补贴调查 | 半导体 | 钢铁 |
|--------|----------|--------|------|
| 225 | 12 | 2 | 2 |

## 技术特点

- 纯官方 API，无网页爬虫 (zero scraping)
- 断点续爬：中断后重跑自动跳过已下载文档
- 增量更新：重复执行自动识别新增 CELEX
- SHA256 文件完整性校验
- 请求限流 (1.5s 间隔 + 指数退避重试)
