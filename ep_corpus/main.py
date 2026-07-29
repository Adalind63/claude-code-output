#!/usr/bin/env python3
"""
=============================================================================
EU Delegation to China — Trade/Economy News Crawler
欧盟驻华代表团英文站 — 中欧经贸新闻定向爬虫

Target:  https://www.eeas.europa.eu/delegations/china_en
Purpose: Academic corpus linguistics research, EU-China economic relations
Method:  Single-thread, low-frequency, DSM TDM Art.3-4 compliant

Install: pip install requests beautifulsoup4 pdfplumber python-dateutil
Usage:   python main.py [--max-pages N]
=============================================================================
"""

import csv
import hashlib
import logging
import os
import re
import sys
import tempfile
import time
import warnings
from datetime import datetime
from typing import Any, Dict, List, Optional, Set
from urllib.parse import urljoin, urlparse

import requests
from bs4 import BeautifulSoup

# 抑制 PDF 解析库的冗余警告
warnings.filterwarnings("ignore", category=UserWarning, module="pdfplumber")
logging.getLogger("pdfplumber").setLevel(logging.ERROR)
logging.getLogger("pdfminer").setLevel(logging.ERROR)


# ============================================================================
# 一、全局配置
# ============================================================================

# --- 路径 (程序启动自动创建) ---
BASE_DIR = r"D:\项目流程\ep_corpus"
TXT_DIR = os.path.join(BASE_DIR, "txt")
CSV_DIR = os.path.join(BASE_DIR, "csv")
LOG_DIR = os.path.join(BASE_DIR, "logs")
CSV_FILE = os.path.join(CSV_DIR, "eu_china_trade_corpus.csv")
PROGRESS_FILE = os.path.join(BASE_DIR, "progress.json")  # 断点续爬进度文件

# --- CSV 固定字段顺序 (不可调换) ---
CSV_COLUMNS = [
    "文档ID",        # MD5 hash 前12位
    "标题",          # 文章标题
    "发布日期",       # YYYY-MM-DD
    "原文链接",       # 原始URL
    "发布机构",       # 自动分类
    "文件类型",       # 自动分类
    "年份",          # 自动分类
    "议题领域",       # 自动分类
    "完整正文文本",    # HTML正文 + PDF文本
]

# --- 爬虫合规参数 ---
USER_AGENT = (
    "EU-China-Corpus-Bot/2.0 "
    "(Academic Research; Corpus Linguistics; "
    "mailto:researcher@university.edu; "
    "DSM-TDM-Art.3-4-Academic-Exemption)"
)
LISTING_DELAY = 5.0      # 列表页请求间隔 (秒)
DETAIL_DELAY = 5.0       # 详情页请求间隔 (秒)
PDF_DELAY = 10.0         # PDF 下载间隔 (秒)
REQUEST_TIMEOUT = 30     # 单次请求超时 (秒)
MAX_RETRIES = 2          # 失败重试次数
RETRY_BACKOFF = 5.0      # 重试退避基数 (秒)

# --- 采集年份范围 ---
VALID_YEARS = {2017, 2018, 2019, 2020, 2021, 2022, 2023, 2024, 2025, 2026}

# --- 目标站点 ---
BASE_URL = "https://www.eeas.europa.eu/delegations/china_en"
NEWS_LISTING = "https://www.eeas.europa.eu/delegations/china_en"  # 实际分页: china_en?page=N
CONTENT_SELECTORS = [  # 正文容器选择器 (按优先级)
    ".field--name-field-text",     # EEAS Drupal 正文
    ".node__content",              # 节点内容 (fallback)
    ".card-body",                  # 卡片内容 (fallback)
    ".main-content",               # 主内容区 (fallback)
]


# ============================================================================
# 二、经贸关键词库 (白名单 + 黑名单)
# ============================================================================

# 白名单：经贸/产业政策关键词 —— 至少命中1个才保留页面
TRADE_WHITELIST = [
    # 贸易核心
    "trade", "trading", "export", "import", "commerce", "commercial",
    "WTO", "world trade", "bilateral trade", "multilateral trade",
    "free trade agreement", "FTA", "trade agreement", "trade deal",
    "trade negotiation", "trade dialogue", "trade relation",
    "trade policy", "trade strategy", "trade review",
    # 投资/市场
    "investment", "investor", "foreign direct investment", "FDI",
    "market access", "market openness", "public procurement",
    "government procurement", "reciprocity", "reciprocal",
    "market barrier", "market distortion", "level playing field",
    # 关税/贸易救济
    "tariff", "customs duty", "anti-dumping", "anti-subsidy",
    "countervailing", "safeguard measure", "trade remedy",
    "trade defence", "trade defense", "dumping",
    "subsidy", "state aid", "foreign subsidy",
    # 供应链/产业
    "supply chain", "value chain", "global supply chain",
    "industrial policy", "industrial strategy", "industry",
    "manufacturing", "industrial ecosystem", "industrial alliance",
    "strategic autonomy", "de-risking", "derisking",
    "economic security", "resilience",
    # 数字经济
    "digital trade", "digital economy", "e-commerce",
    "data flow", "data localisation", "data governance",
    "digital sovereignty", "digital service",
    "artificial intelligence", "AI", "5G", "6G",
    "cybersecurity", "cyber security", "cloud computing",
    "telecom", "telecommunication", "digital platform",
    "Digital Services Act", "Digital Markets Act", "DMA", "DSA",
    # 能源/气候贸易
    "renewable energy", "solar", "photovoltaic", "wind energy",
    "electric vehicle", "battery", "lithium", "hydrogen",
    "clean energy", "clean tech", "green technology",
    "carbon border", "CBAM", "emission trading",
    # 行业关键词
    "semiconductor", "chip", "microelectronics", "processor",
    "steel", "aluminium", "aluminum", "metal industry",
    "rare earth", "critical mineral", "critical raw material",
    "pharmaceutical", "medical device", "biotech",
    "textile", "automotive", "shipbuilding", "aerospace",
    # 知识产权/标准
    "intellectual property", "IPR", "patent", "trademark",
    "copyright", "trade secret", "geographical indication",
    "standard essential patent", "technical standard",
    "conformity assessment", "certification",
    # 其他经贸
    "SME", "small and medium", "entrepreneur", "startup",
    "innovation", "research and development", "R&D",
    "single market", "internal market", "customs union",
    "regulatory cooperation", "regulatory dialogue",
    "screening", "export control", "dual-use",
]

# 黑名单：纯非经贸内容关键词 —— 仅命中黑名单但未命中白名单时丢弃
# 如果同时命中白名单+黑名单，保留 (例如 "trade and human rights" 的情况)
NON_TRADE_BLACKLIST = [
    # 人权/政治
    "human rights", "human right", "fundamental rights",
    "democracy", "democratic", "rule of law", "judicial",
    "civil society", "NGO", "non-governmental",
    "political prisoner", "political dialogue",
    "death penalty", "torture", "freedom of expression",
    "freedom of religion", "freedom of assembly",
    # 文化/教育/旅游
    "culture", "cultural", "heritage", "museum",
    "art exhibition", "film festival", "music", "literature",
    "tourism", "tourist", "travel guide", "sightseeing",
    "scholarship", "education exchange", "academic cooperation",
    "university partnership", "student exchange", "Erasmus",
    "language", "linguistic", "cultural diversity",
    # 领事/签证
    "consular", "visa", "passport", "travel document",
    "consulate", "embassy event", "national day",
    "diplomatic reception", "ambassador credentials",
    # 其他非经贸
    "sport", "olympic", "football", "athletic",
    "religion", "religious", "interfaith",
    "humanitarian aid", "disaster relief", "earthquake",
    "flood", "typhoon", "pandemic", "COVID", "epidemic",
    "gender equality", "women's right", "LGBT",
    "children's right", "disability", "social inclusion",
]

# 议题领域分类关键词 (摘自 ec_growth_corpus 项目，适配 EEAS)
TOPIC_KEYWORDS = {
    "半导体":       ["semiconductor", "chip", "microchip", "microelectronics",
                    "processor", "wafer", "foundry", "integrated circuit",
                    "advanced chip", "chip manufacturing"],
    "新能源":       ["solar panel", "solar cell", "photovoltaic", "wind turbine",
                    "electric vehicle", "EV", "battery", "lithium battery",
                    "energy storage", "hydrogen", "renewable energy",
                    "clean energy", "green technology", "rare earth",
                    "critical mineral", "electrolyser", "biofuel"],
    "钢铁":         ["steel", "steel overcapacity", "steel industry",
                    "steel safeguard", "steel tariff", "aluminium",
                    "aluminum", "metal industry", "ferrous", "non-ferrous"],
    "市场准入":     ["market access", "market openness", "public procurement",
                    "government procurement", "reciprocity", "reciprocal",
                    "market barrier", "technology transfer",
                    "localization requirement", "joint venture"],
    "数字贸易":     ["digital trade", "digital economy", "data flow",
                    "data localisation", "digital sovereignty",
                    "e-commerce", "artificial intelligence", "5G", "6G",
                    "cybersecurity", "cloud computing", "digital platform",
                    "Digital Services Act", "Digital Markets Act"],
    "补贴调查":     ["anti-subsidy", "countervailing duty", "CVD",
                    "subsidy investigation", "subsidy probe",
                    "foreign subsidy", "state aid", "government subsidy",
                    "distortive subsidy", "FSR"],
    "关税":         ["tariff", "anti-dumping", "safeguard measure",
                    "trade remedy", "trade defence instrument",
                    "import duty", "customs duty", "MFN tariff",
                    "provisional duty", "definitive duty", "TDI"],
    "投资审查":     ["foreign direct investment", "FDI screening",
                    "investment screening", "investment review",
                    "export control", "dual-use", "critical infrastructure",
                    "strategic asset", "foreign investment"],
    "知识产权":     ["intellectual property", "IPR", "patent", "trademark",
                    "copyright", "trade secret", "counterfeit", "piracy",
                    "standard essential patent", "SEP",
                    "geographical indication", "IP enforcement"],
}

# 文件类型分类关键词
DOCTYPE_KEYWORDS = {
    "条例":       ["regulation", "implementing regulation", "delegated regulation",
                   "directive", "legal act"],
    "报告":       ["report", "annual report", "progress report", "study",
                   "assessment", "evaluation", "staff working document",
                   "SWD", "working paper", "briefing", "analysis"],
    "声明":       ["statement", "declaration", "press release", "speech",
                   "remarks", "joint statement", "communiqué", "news",
                   "announcement", "communication"],
    "白皮书":     ["white paper", "strategy paper", "policy paper"],
    "决议":       ["resolution", "decision", "legislative resolution"],
}


# ============================================================================
# 三、日志配置
# ============================================================================

def setup_logging():
    """配置日志：同时输出到控制台和文件"""
    os.makedirs(LOG_DIR, exist_ok=True)
    log_file = os.path.join(
        LOG_DIR,
        f"crawl_{datetime.now().strftime('%Y%m%d_%H%M%S')}.log"
    )
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s | %(levelname)-8s | %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
        handlers=[
            logging.FileHandler(log_file, encoding="utf-8"),
            logging.StreamHandler(sys.stdout),
        ],
    )
    return logging.getLogger(__name__)

logger = logging.getLogger(__name__)  # 将在 main() 中正式初始化


# ============================================================================
# 四、工具函数
# ============================================================================

def ensure_directories():
    """自动创建所有输出目录 (TXT/CSV/Logs)，无需手动新建"""
    for d in [TXT_DIR, CSV_DIR, LOG_DIR]:
        os.makedirs(d, exist_ok=True)
        logger.debug("  Directory ensured: %s", d)


def generate_doc_id(url: str) -> str:
    """对原文链接做 MD5 哈希，截取前12位作为全局唯一文档ID，用于去重"""
    return hashlib.md5(url.strip().encode("utf-8")).hexdigest()[:12]


def extract_year_from_date(date_str: str) -> str:
    """从日期字符串提取年份，仅识别 2017-2026，否则返回 '其他'"""
    if not date_str:
        return "其他"
    m = re.search(r"(\d{4})", str(date_str))
    if m:
        year = int(m.group(1))
        if year in VALID_YEARS:
            return str(year)
    return "其他"


def sanitize_pii(text: str) -> str:
    """清洗文本中的姓名、邮箱、电话等个人信息，仅保留政策正文"""
    if not text:
        return ""
    # 邮箱
    text = re.sub(r'[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}', '[EMAIL]', text)
    # 欧洲电话格式
    text = re.sub(r'\+?[0-9]{1,4}[\s-]?\(?[0-9]{1,4}\)?[\s-][0-9]{2,4}[\s-][0-9]{2,4}[\s-][0-9]{2,4}', '[PHONE]', text)
    # 国际电话
    text = re.sub(r'\+[0-9]{7,15}', '[PHONE]', text)
    return text


# 多词经贸短语 (必须至少命中1个，单字如"trade"在非经贸语境太常见)
MULTI_WORD_TRADE = [
    "trade policy", "trade agreement", "trade negotiation", "trade relation",
    "trade dialogue", "trade strategy", "trade deal", "trade cooperation",
    "trade partnership", "trade dispute", "trade tension", "trade imbalance",
    "free trade agreement", "FTA", "bilateral trade", "international trade",
    "supply chain", "value chain", "global supply chain", "supply chain resilience",
    "market access", "public procurement", "government procurement",
    "foreign investment", "foreign direct investment", "FDI",
    "intellectual property", "IPR", "standard essential patent",
    "level playing field", "trade barrier", "market distortion",
    "anti-dumping", "anti-subsidy", "countervailing duty",
    "economic security", "economic coercion", "de-risking",
    "industrial policy", "industrial strategy", "industrial overcapacity",
    "export control", "investment screening", "technology transfer",
    "rare earth", "critical mineral", "critical raw material",
    "strategic dependency", "strategic autonomy",
    "carbon border", "CBAM", "emission trading",
    "digital trade", "data localisation", "cross-border data",
    "state aid", "foreign subsidy", "subsidy investigation",
    "customs cooperation", "customs union", "regulatory cooperation",
    "sanctions regime", "sanctions package", "trade restrictive",
    "WTO", "world trade organization", "trade and technology council",
]


def has_trade_content(text: str) -> bool:
    """
    经贸内容黑白关键词过滤 (严格模式)：
    1. 正文至少200字符
    2. 必须命中至少1个多词经贸短语 (如"trade policy", "supply chain")
    3. 白名单总计至少3个经贸关键词
    4. 头部2500字必须有关键词 (防止仅页尾提及)
    5. 黑名单命中 > 白名单*3 → 丢弃
    """
    if not text or len(text) < 200:
        return False
    t = text.lower()

    # 第一阶段：必须命中至少1个多词经贸短语 (这是最严格的信号)
    multi_hits = sum(1 for kw in MULTI_WORD_TRADE if kw.lower() in t)
    if multi_hits == 0:
        return False

    # 第二阶段：白名单总命中数至少3个
    white_hits = sum(1 for kw in TRADE_WHITELIST if kw.lower() in t)
    if white_hits < 3:
        return False

    # 第三阶段：头部2500字中必须有多词短语
    head = t[:2500]
    head_multi = sum(1 for kw in MULTI_WORD_TRADE if kw.lower() in head)
    if head_multi == 0:
        return False

    # 第四阶段：黑名单检查
    black_hits = sum(1 for kw in NON_TRADE_BLACKLIST if kw.lower() in t)
    if black_hits > white_hits * 3:
        return False

    return True


# ============================================================================
# 五、自动分类函数
# ============================================================================

def classify_topic(title: str, body_text: str) -> str:
    """根据标题和正文匹配议题领域关键词，无匹配返回'其他'"""
    combined = ((title or "") + " " + (body_text or "")[:5000]).lower()
    if not combined.strip():
        return "其他"

    scores = {}
    for topic, keywords in TOPIC_KEYWORDS.items():
        score = 0
        for kw in keywords:
            count = combined.count(kw.lower())
            if count > 0:
                score += min(count, 10)  # 单关键词贡献封顶
        if score > 0:
            scores[topic] = score

    if not scores:
        return "其他"
    best = max(scores, key=scores.get)
    # 要求最低匹配分 >= 2，避免单次偶然命中
    return best if scores[best] >= 2 else "其他"


def classify_institution(text: str) -> str:
    """识别发布机构，当前站点固定默认 EEAS，预留拓展匹配"""
    # EEAS 站点内容默认归为 EEAS
    # 如果正文明确提及其他机构，按优先级匹配
    t = (text or "").lower()
    if "european commission" in t and "commission" in t[:500]:
        return "欧委会"
    if "european parliament" in t:
        return "欧洲议会"
    if "council of the european union" in t or "eu council" in t:
        return "欧盟理事会"
    if "dg trade" in t or "directorate-general for trade" in t:
        return "贸易总司(DG TRADE)"
    # 默认：EEAS 站点内容
    return "欧洲对外行动署(EEAS)"


def classify_doctype(text: str) -> str:
    """根据正文前800字符 + 标题匹配文件类型关键词，无匹配填'其他'"""
    if not text:
        return "其他"
    header = text[:800].lower()
    scores = {}
    for dtype, keywords in DOCTYPE_KEYWORDS.items():
        score = sum(1 for kw in keywords if kw.lower() in header)
        if score > 0:
            scores[dtype] = score
    if not scores:
        return "其他"
    return max(scores, key=scores.get)


def classify_document(title: str, body_text: str, date_str: str) -> Dict[str, str]:
    """对文档执行全维度自动分类，返回分类结果字典"""
    year = extract_year_from_date(date_str)
    topic = classify_topic(title, body_text)
    # 用标题+正文前2000字符做机构识别
    inst_text = f"{title}\n{body_text[:2000]}" if body_text else title
    institution = classify_institution(inst_text)
    # 用标题+正文做文件类型识别
    type_text = f"{title}\n{body_text[:500]}" if body_text else title
    doc_type = classify_doctype(type_text)

    return {
        "year": year,
        "topic": topic,
        "institution": institution,
        "doc_type": doc_type,
    }


# ============================================================================
# 六、存储函数
# ============================================================================

def load_existing_csv_ids() -> Set[str]:
    """读取CSV中已有文档ID集合，用于增量去重"""
    existing = set()
    if os.path.exists(CSV_FILE):
        try:
            with open(CSV_FILE, "r", encoding="utf-8-sig") as f:
                reader = csv.DictReader(f)
                for row in reader:
                    doc_id = row.get("文档ID", "")
                    if doc_id:
                        existing.add(doc_id)
        except Exception:
            pass
    return existing


def csv_header_exists() -> bool:
    """检查CSV文件是否存在且已有正确表头"""
    if not os.path.exists(CSV_FILE):
        return False
    try:
        with open(CSV_FILE, "r", encoding="utf-8-sig") as f:
            first_line = f.readline().strip()
            return "文档ID" in first_line
    except Exception:
        return False


def append_to_csv(doc: Dict[str, Any]) -> bool:
    """
    单行追加CSV数据，永久增量写入，绝不覆盖历史数据。
    如果文件不存在则自动生成表头。
    返回 True=成功写入, False=重复跳过
    """
    os.makedirs(CSV_DIR, exist_ok=True)
    existing_ids = load_existing_csv_ids()
    doc_id = doc.get("doc_id", "")
    if doc_id in existing_ids:
        logger.debug("  重复跳过: %s", doc_id)
        return False

    file_exists = csv_header_exists()
    try:
        with open(CSV_FILE, "a", newline="", encoding="utf-8-sig") as f:
            writer = csv.DictWriter(f, fieldnames=CSV_COLUMNS)
            if not file_exists:
                writer.writeheader()
            row = {
                "文档ID":    doc_id,
                "标题":      doc.get("title", ""),
                "发布日期":   doc.get("date", ""),
                "原文链接":   doc.get("url", ""),
                "发布机构":   doc.get("institution", ""),
                "文件类型":   doc.get("doc_type", ""),
                "年份":      doc.get("year", ""),
                "议题领域":   doc.get("topic", ""),
                "完整正文文本": doc.get("full_text", ""),
            }
            writer.writerow(row)
        return True
    except Exception as e:
        logger.error("  CSV写入失败: %s", str(e)[:100])
        return False


def save_txt_file(doc: Dict[str, Any]) -> Optional[str]:
    """
    保存单篇TXT文件，命名规则 YYYYMMDD_文档ID.txt。
    内部格式：顶部完整元数据 → 分隔线 → 完整英文正文。
    """
    os.makedirs(TXT_DIR, exist_ok=True)
    doc_id = doc.get("doc_id", "unknown")
    date_str = doc.get("date", "")
    date_prefix = date_str[:10].replace("-", "") if date_str and date_str != "unknown" else "00000000"
    safe_id = re.sub(r'[<>:"/\\|?*]', '', doc_id)[:32]
    filename = f"{date_prefix}_{safe_id}.txt"
    filepath = os.path.join(TXT_DIR, filename)

    # 跳过已存在的文件 (去重保护)
    if os.path.exists(filepath):
        return None

    classification = classify_document(
        doc.get("title", ""),
        doc.get("full_text", ""),
        doc.get("date", ""),
    )

    lines = []
    lines.append("=" * 80)
    lines.append(f"DOCUMENT ID:    {doc_id}")
    lines.append(f"TITLE:          {doc.get('title', '')}")
    lines.append(f"DATE:           {doc.get('date', '')}")
    lines.append(f"INSTITUTION:    {doc.get('institution', classification['institution'])}")
    lines.append(f"DOCUMENT TYPE:  {doc.get('doc_type', classification['doc_type'])}")
    lines.append(f"SOURCE URL:     {doc.get('url', '')}")
    lines.append(f"YEAR (AUTO):    {classification['year']}")
    lines.append(f"TOPIC (AUTO):   {classification['topic']}")
    lines.append(f"INST (AUTO):    {classification['institution']}")
    lines.append(f"DOCTYPE (AUTO): {classification['doc_type']}")
    lines.append("=" * 80)
    lines.append("")
    lines.append(doc.get("full_text", ""))

    try:
        with open(filepath, "w", encoding="utf-8") as f:
            f.write("\n".join(lines))
        return filepath
    except Exception as e:
        logger.error("  TXT写入失败 (%s): %s", filename, str(e)[:100])
        return None


# ============================================================================
# 七、网络请求与HTML解析
# ============================================================================

def get_session() -> requests.Session:
    """创建带自定义学术UA的requests会话"""
    s = requests.Session()
    s.headers.update({
        "User-Agent": USER_AGENT,
        "Accept": "text/html,application/xhtml+xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.9",
    })
    return s


def safe_fetch(url: str, session: requests.Session) -> Optional[requests.Response]:
    """
    安全HTTP请求，带重试和退避。
    403/404/5xx 打印日志，不抛异常，返回 None。
    """
    for attempt in range(MAX_RETRIES):
        try:
            resp = session.get(url, timeout=REQUEST_TIMEOUT, allow_redirects=True)
            if resp.status_code == 200:
                return resp
            elif resp.status_code in (403, 404, 410):
                logger.warning("  HTTP %d: %s", resp.status_code, url[:100])
                return None
            elif resp.status_code >= 500:
                logger.warning("  HTTP %d: %s", resp.status_code, url[:100])
            else:
                logger.debug("  HTTP %d: %s", resp.status_code, url[:80])
        except requests.Timeout:
            logger.debug("  Timeout: %s", url[:80])
        except requests.RequestException as e:
            logger.debug("  Request error: %s — %s", url[:80], str(e)[:80])

        if attempt < MAX_RETRIES - 1:
            time.sleep(RETRY_BACKOFF * (attempt + 1))
    return None


def parse_html(resp: requests.Response) -> Optional[BeautifulSoup]:
    """解析HTML响应为BeautifulSoup对象"""
    try:
        return BeautifulSoup(resp.content, "lxml")
    except Exception:
        try:
            return BeautifulSoup(resp.content, "html.parser")
        except Exception:
            return None


def extract_title(soup: BeautifulSoup) -> str:
    """提取文章标题，优先级: h1 > meta og:title > <title>"""
    h1 = soup.find("h1")
    if h1:
        return h1.get_text(strip=True)
    og = soup.find("meta", property="og:title")
    if og and og.get("content"):
        return og["content"].strip()
    if soup.title:
        return soup.title.get_text(strip=True)
    return ""


def extract_date(soup: BeautifulSoup, url: str) -> str:
    """提取发布日期，来源: meta标签 > time元素 > 正文DD.MM.YYYY > URL模式"""
    # 1. Meta标签
    for meta in soup.find_all("meta"):
        name = (meta.get("name") or "").lower()
        content = meta.get("content", "")
        if name in ("dc.date", "dcterms.issued", "publication-date", "date"):
            m = re.match(r"(\d{4}-\d{2}-\d{2})", content)
            if m:
                return m.group(1)
    # 2. Time元素
    for time_tag in soup.find_all("time"):
        dt = time_tag.get("datetime", "")
        m = re.match(r"(\d{4}-\d{2}-\d{2})", str(dt))
        if m:
            return m.group(1)
    # 3. 正文中的 DD.MM.YYYY 格式 (EEAS站点常用)
    body_text = soup.get_text()
    m = re.search(r'(\d{2})\.(\d{2})\.(\d{4})', body_text)
    if m:
        return f"{m.group(3)}-{m.group(2)}-{m.group(1)}"
    # 4. URL模式: ...YYYY-MM-DD...
    m = re.search(r"(\d{4}-\d{2}-\d{2})", url)
    if m:
        return m.group(0)
    return ""


def extract_html_text(soup: BeautifulSoup) -> str:
    """
    清洗提取正文：按优先级尝试多个正文容器选择器，
    移除 script/style/nav/footer 等非内容标签后提取纯文本。
    """
    # 移除非内容元素
    for tag in soup(["script", "style", "nav", "footer", "noscript",
                      "iframe", "svg", "header", "button", "input", "select"]):
        tag.decompose()

    # 移除 EU 站点 chrome 元素
    chrome_selectors = [
        ".ecl-site-header", ".ecl-site-footer", ".ecl-breadcrumb",
        ".cookie-consent", ".ecl-mega-menu", ".ecl-language-list",
        ".skip-link", "#skip-link", ".region-header", ".region-footer",
        ".site-header", ".site-footer", ".ecl-message",
        ".content-options", ".content-share", ".content-pdf-print",
    ]
    for sel in chrome_selectors:
        for el in soup.select(sel):
            el.decompose()

    # 按优先级尝试正文容器选择器
    content = None
    for sel in CONTENT_SELECTORS:
        content = soup.select_one(sel)
        if content:
            break

    # 最终回退
    if not content:
        content = (soup.find("main") or
                   soup.find(id="main-content") or
                   soup.find(role="main") or
                   soup.body)

    if not content:
        return ""

    text = content.get_text(separator="\n", strip=True)
    text = re.sub(r'\n\s*\n\s*\n+', '\n\n', text)  # 合并多余换行
    text = re.sub(r'[ \t]{2,}', ' ', text)           # 合并多余空格
    return text.strip()


def find_pdf_links(soup: BeautifulSoup, base_url: str) -> List[str]:
    """提取页面内所有PDF附件链接 (去重)"""
    pdfs = set()
    for a in soup.find_all("a", href=True):
        href = a["href"].strip()
        low = href.lower()
        if low.endswith(".pdf"):
            pdfs.add(urljoin(base_url, href))
        elif "/document/download/" in low and "filename=" in low:
            pdfs.add(urljoin(base_url, href))
        elif "_en.pdf" in low or "en.pdf" in low:
            pdfs.add(urljoin(base_url, href))
    return list(pdfs)


# ============================================================================
# 八、PDF文本提取
# ============================================================================

def extract_pdf_text(pdf_url: str, session: requests.Session) -> Optional[str]:
    """
    下载PDF并使用 pdfplumber 提取文本。
    超过 50MB 的PDF自动跳过。
    """
    resp = safe_fetch(pdf_url, session)
    if not resp or len(resp.content) < 100:
        return None

    content = resp.content
    if len(content) > 50 * 1024 * 1024:  # 50MB 上限
        logger.debug("    PDF too large (%d MB), skip", len(content) // (1024 * 1024))
        return None

    if content[:5] != b'%PDF-':
        return None

    # 写入临时文件供 pdfplumber 解析
    try:
        fd, tmp = tempfile.mkstemp(suffix=".pdf")
        with os.fdopen(fd, "wb") as f:
            f.write(content)

        text = ""
        try:
            import pdfplumber
            with pdfplumber.open(tmp) as pdf:
                for page in pdf.pages:
                    pt = page.extract_text()
                    if pt:
                        text += pt + "\n"
        except ImportError:
            # pdfplumber 不可用时回退 PyPDF2
            try:
                from PyPDF2 import PdfReader
                reader = PdfReader(tmp)
                for page in reader.pages:
                    pt = page.extract_text()
                    if pt:
                        text += pt + "\n"
            except ImportError:
                pass

        os.unlink(tmp)
        return text.strip() if text.strip() else None
    except Exception as e:
        logger.debug("    PDF extract error: %s", str(e)[:80])
        return None


# ============================================================================
# 九、列表页遍历
# ============================================================================

def extract_news_links(html: str, base_url: str) -> List[str]:
    """
    从新闻列表页HTML中提取合规英文详情链接。
    规则：仅保留EEAS站点内 /delegations/china/ 路径的文章详情页，自动去重。
    过滤外部链接、锚点链接、非英文页面。
    """
    soup = BeautifulSoup(html, "lxml") if "lxml" in sys.modules else BeautifulSoup(html, "html.parser")
    links = set()

    # EEAS Drupal 站点新闻列表选择器 (按优先级)
    selectors = [
        ".node a[href]",              # 主选择器：Drupal节点链接
        ".views-row a[href]",         # 视图行链接
        "article a[href]",            # article元素内链接
        "h2 a[href]", "h3 a[href]",  # 标题链接
        ".listing-item a[href]",      # 列表项链接
    ]
    for sel in selectors:
        for a in soup.select(sel):
            href = a.get("href", "").strip()
            if not href or href.startswith("#") or href.startswith("javascript:"):
                continue

            # 处理相对URL
            if href.startswith("/"):
                full = "https://www.eeas.europa.eu" + href
            elif href.startswith("http"):
                full = href
            else:
                full = urljoin(base_url, href)

            # 移除Drupal缓存参数 ?s=166
            full = re.sub(r'\?s=\d+', '', full)

            parsed = urlparse(full)
            path = parsed.path.lower()

            # 仅保留 EEAS 站点内的链接
            if "eeas.europa.eu" not in parsed.netloc and "europa.eu" not in parsed.netloc:
                continue

            # 仅保留 /delegations/china/ 路径 (过滤 /eeas/ 通用页面)
            if "/delegations/china/" not in full:
                continue

            # 过滤非英文页面 (带 _bg, _es, _fr 等后缀)
            path_no_query = path.split("?")[0]
            if re.search(r'_(bg|es|cs|da|de|et|el|fr|ga|hr|it|lv|lt|hu|mt|nl|pl|pt|ro|sk|sl|fi|sv)$', path_no_query):
                continue

            # 需要是详情页 (路径深度 > 3)，过滤首页/栏目页
            parts = [p for p in parsed.path.split("/") if p]
            if len(parts) < 3:
                continue

            links.add(full)

    return sorted(links)


def crawl_listing_pages(session: requests.Session, max_pages: int = 50) -> List[str]:
    """
    循环遍历新闻分页，提取所有英文详情链接并去重。
    页面无新闻条目时自动终止循环。
    参数 max_pages: 最大翻页数量 (0-based, 50页覆盖约500+条新闻)
    """
    all_links: Set[str] = set()
    empty_pages = 0

    logger.info("开始遍历新闻列表页 (max_pages=%d)...", max_pages)

    for page_num in range(max_pages):
        url = f"{NEWS_LISTING}?page={page_num}"
        logger.info("  列表页 %d: %s", page_num, url[:100])

        resp = safe_fetch(url, session)
        if not resp:
            logger.warning("  列表页 %d 请求失败，跳过", page_num)
            empty_pages += 1
            if empty_pages >= 3:
                logger.info("  连续3页失败，终止列表遍历")
                break
            continue

        links = extract_news_links(resp.text, url)
        new_count = 0
        for link in links:
            if link not in all_links:
                all_links.add(link)
                new_count += 1

        logger.info("    本页: %d 链接, 新增: %d, 累计: %d", len(links), new_count, len(all_links))

        if len(links) == 0:
            empty_pages += 1
        else:
            empty_pages = 0

        # 连续3页无内容 → 终止
        if empty_pages >= 3:
            logger.info("  连续%d页无新闻条目，终止列表遍历", empty_pages)
            break

        # 合规间隔
        time.sleep(LISTING_DELAY)

    logger.info("列表遍历完成: 共获取 %d 个唯一英文详情链接", len(all_links))
    return sorted(all_links)


# ============================================================================
# 十、Sitemap解析 (主要URL来源)
# ============================================================================

SITEMAP_URL = "https://www.eeas.europa.eu/sitemap.xml"


def parse_sitemap(session: requests.Session) -> List[Dict[str, str]]:
    """
    递归解析EEAS sitemap，提取 /delegations/china/ 下所有英文页面。
    采用验证过的递归逻辑：深度≤2，每层最多取30个子sitemap。
    预期产出：~1,800 China delegation URL。
    """
    from xml.etree import ElementTree as ET

    def _parse(url: str, depth: int = 0) -> List[Dict[str, str]]:
        if depth > 2:
            return []
        entries = []
        try:
            r = session.get(url, timeout=30)
            if r.status_code != 200:
                return entries
            root = ET.fromstring(r.content)
            ns_match = re.match(r'\{(.*?)\}', root.tag)
            ns = ns_match.group(1) if ns_match else ""
            if not ns:
                return entries

            # sitemap index → 递归处理子sitemap
            sitemap_tags = root.findall(f"{{{ns}}}sitemap")
            if sitemap_tags:
                for sm in sitemap_tags[:30]:
                    loc = sm.find(f"{{{ns}}}loc")
                    if loc is not None and loc.text:
                        entries.extend(_parse(loc.text.strip(), depth + 1))
                return entries

            # 常规sitemap → 提取URL条目
            for url_tag in root.findall(f"{{{ns}}}url"):
                loc = url_tag.find(f"{{{ns}}}loc")
                lastmod = url_tag.find(f"{{{ns}}}lastmod")
                if loc is not None and loc.text:
                    url_text = loc.text.strip()
                    if "/delegations/china/" in url_text and "_en" in url_text.lower():
                        # 过滤非英文语言变体
                        path = url_text.split("?")[0].lower()
                        if re.search(r'_(zh-hans|zh-hant|zh|ja|ko|ar|ru)$', path):
                            continue
                        entries.append({
                            "url": url_text,
                            "lastmod": lastmod.text.strip() if lastmod is not None and lastmod.text else "",
                        })
        except Exception:
            pass
        return entries

    logger.info("解析 EEAS sitemap...")
    all_entries = _parse(SITEMAP_URL)
    logger.info("  获取 %d 个 /delegations/china/ 英文页面", len(all_entries))

    # 按URL去重，过滤栏目首页
    seen = set()
    unique = []
    for e in all_entries:
        if e["url"] not in seen:
            seen.add(e["url"])
            # 过滤明显的栏目首页 (URL末尾为通用栏目名)
            path = urlparse(e["url"]).path.lower()
            slug = path.rstrip("/").split("/")[-1].replace("_en", "")
            if slug in ("china", "news", "events", "publications", "about", "contact",
                        "european-union-and-china", "basic-framework-relations",
                        "political-relations-human-rights",
                        "economic-relations-trade-and-investment",
                        "green-transition", "research-innovation",
                        "digital-policies", "international-development-cooperation",
                        "ambassador-s-corner-0"):
                continue
            unique.append(e)

    logger.info("  去重 + 过滤栏目页后: %d 个详情页", len(unique))
    return unique


# ============================================================================
# 十一、详情页解析主函数
# ============================================================================

def process_detail_page(
    url: str,
    session: requests.Session,
    existing_ids: Set[str],
    stats: Dict[str, int],
) -> bool:
    """
    解析单篇新闻详情页，完成6项基础内容提取、全维度自动分类、
    本地TXT存档、CSV增量写入。
    返回 True=成功处理, False=跳过/失败
    """
    # 预检查去重
    doc_id = generate_doc_id(url)
    if doc_id in existing_ids:
        return False

    # 请求HTML
    resp = safe_fetch(url, session)
    if not resp:
        stats["failed"] += 1
        return False

    soup = parse_html(resp)
    if not soup:
        stats["failed"] += 1
        return False

    # --- 提取6项基础内容 ---
    title = extract_title(soup)
    if not title:
        logger.debug("  无标题，跳过: %s", url[:80])
        stats["failed"] += 1
        return False

    date_str = extract_date(soup, url)
    html_text = extract_html_text(soup)

    # 默认发布机构 (EEAS站点)
    institution = "European External Action Service (EEAS)"

    # --- PDF附件提取 ---
    pdf_texts = []
    pdf_links = find_pdf_links(soup, url)
    for pdf_url in pdf_links[:3]:  # 最多下载3个PDF
        logger.debug("    PDF: %s", pdf_url[:80])
        pdf_text = extract_pdf_text(pdf_url, session)
        if pdf_text:
            pdf_texts.append(pdf_text)
        time.sleep(PDF_DELAY)

    # --- 合并全文 ---
    full_text = html_text
    if pdf_texts:
        for pt in pdf_texts:
            full_text += "\n\n--- PDF Attachment ---\n\n" + pt

    full_text = sanitize_pii(full_text)

    # --- 经贸关键词过滤 ---
    if not has_trade_content(full_text):
        logger.debug("  非经贸内容，丢弃: %s", title[:80])
        stats["filtered"] += 1
        return False

    # --- 自动分类 ---
    classification = classify_document(title, full_text, date_str)

    # --- 构建文档 ---
    doc = {
        "doc_id":      doc_id,
        "title":       title,
        "date":        date_str,
        "url":         url,
        "institution": institution,
        "doc_type":    classification["doc_type"],
        "year":        classification["year"],
        "topic":       classification["topic"],
        "full_text":   full_text,
    }

    # --- 存储 ---
    txt_path = save_txt_file(doc)
    csv_ok = append_to_csv(doc)

    if txt_path and csv_ok:
        existing_ids.add(doc_id)
        stats["saved"] += 1
        logger.info("  ✓ [%d] %s | %s | %s",
                    stats["saved"], title[:80], date_str, classification["topic"])
        return True
    elif csv_ok:
        stats["saved"] += 1
        return True
    else:
        stats["failed"] += 1
        return False


# ============================================================================
# 十二、断点续爬
# ============================================================================

def load_progress() -> Optional[Set[str]]:
    """从 progress.json 加载已处理的URL集合"""
    if not os.path.exists(PROGRESS_FILE):
        return None
    try:
        import json
        with open(PROGRESS_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
        urls = set(data.get("processed_urls", []))
        logger.info("📂 断点续爬: %d 个URL已处理，跳过...", len(urls))
        return urls
    except Exception:
        return None


def save_progress(processed_urls: Set[str]):
    """保存已处理URL集合到 progress.json (原子写入)"""
    import json
    data = {
        "processed_urls": sorted(processed_urls),
        "last_updated": datetime.now().isoformat(),
    }
    tmp = PROGRESS_FILE + ".tmp"
    try:
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        os.replace(tmp, PROGRESS_FILE)
    except Exception as e:
        logger.warning("⚠️  进度保存失败: %s", str(e)[:80])


# ============================================================================
# 十三、程序主入口
# ============================================================================

def main(max_pages: int = 50):
    """
    主入口：自动创建文件夹 → 初始化CSV表头 → 遍历列表页 → 逐篇解析存储。
    参数 max_pages: 最大翻页数量，默认50 (每页约10条新闻，覆盖~500篇)
    """
    global logger
    setup_logging()
    logger = logging.getLogger(__name__)

    logger.info("=" * 60)
    logger.info("EU DELEGATION TO CHINA — Trade News Crawler")
    logger.info("Target: %s", BASE_URL)
    logger.info("Max pages: %d | Listing delay: %.0fs | Detail delay: %.0fs | PDF delay: %.0fs",
                max_pages, LISTING_DELAY, DETAIL_DELAY, PDF_DELAY)
    logger.info("=" * 60)

    # 1. 自动创建所有文件夹
    ensure_directories()

    # 2. 初始化CSV表头 (如果文件不存在)
    if not csv_header_exists():
        os.makedirs(CSV_DIR, exist_ok=True)
        with open(CSV_FILE, "w", newline="", encoding="utf-8-sig") as f:
            writer = csv.DictWriter(f, fieldnames=CSV_COLUMNS)
            writer.writeheader()
        logger.info("CSV表头已初始化: %s", CSV_FILE)

    # 3. 加载已有文档ID (增量去重) + 断点续爬进度
    existing_ids = load_existing_csv_ids()
    progress_urls = load_progress()
    if progress_urls:
        # 将已处理的URL也加入去重集合
        for url in progress_urls:
            doc_id = generate_doc_id(url)
            existing_ids.add(doc_id)

    logger.info("已有 %d 篇文档 (CSV增量去重)", len(existing_ids))

    # 4. 创建会话
    session = get_session()

    # 5. 收集详情链接：优先从 sitemap 获取，列表页作为补充
    logger.info("\nPHASE 1: SITEMAP URL DISCOVERY")
    sitemap_entries = parse_sitemap(session)
    sitemap_links = [e["url"] for e in sitemap_entries]
    logger.info("  Sitemap 详情链接: %d", len(sitemap_links))

    logger.info("\nPHASE 2: LISTING PAGE CRAWL (supplement)")
    listing_links = crawl_listing_pages(session, max_pages)
    logger.info("  列表页详情链接: %d", len(listing_links))

    # 合并去重
    all_links = sorted(set(sitemap_links + listing_links))
    logger.info("\n合并后总链接: %d (sitemap %d + listing %d)",
                len(all_links), len(sitemap_links), len(listing_links))

    if not all_links:
        logger.warning("未获取到任何新闻链接，请检查网络或站点结构")
        return

    # 剔除已处理的链接
    processed_urls = progress_urls or set()
    pending_links = [l for l in all_links if l not in processed_urls]
    logger.info("待处理: %d 篇 (已跳过 %d 篇)",
                len(pending_links), len(all_links) - len(pending_links))

    # 6. 逐篇处理详情页
    stats = {"saved": 0, "filtered": 0, "failed": 0}
    checkpoint_counter = 0

    for i, link in enumerate(pending_links):
        logger.info("[%d/%d] %s", i + 1, len(pending_links), link[:100])
        process_detail_page(link, session, existing_ids, stats)
        processed_urls.add(link)
        checkpoint_counter += 1

        # 每20篇保存一次进度
        if checkpoint_counter % 20 == 0:
            save_progress(processed_urls)
            logger.info("  💾 进度已保存 (%d URLs)", len(processed_urls))

        # 合规间隔
        time.sleep(DETAIL_DELAY)

    # 最终保存进度
    save_progress(processed_urls)

    # 7. 输出统计
    logger.info("\n" + "=" * 60)
    logger.info("CRAWL COMPLETE")
    logger.info("=" * 60)
    logger.info("  详情链接总数:     %d", len(all_links))
    logger.info("  成功保存:         %d", stats["saved"])
    logger.info("  经贸过滤丢弃:     %d", stats["filtered"])
    logger.info("  请求失败/跳过:    %d", stats["failed"])
    logger.info("  TXT目录:          %s", TXT_DIR)
    logger.info("  CSV文件:          %s", CSV_FILE)
    logger.info("  CSV累计行数:      %d", len(existing_ids))
    logger.info("=" * 60)

    # 爬取完全成功时删除进度文件
    if os.path.exists(PROGRESS_FILE) and stats["failed"] == 0:
        os.remove(PROGRESS_FILE)
        logger.info("✓ 进度文件已清理")


# ============================================================================
# 命令行入口
# ============================================================================

if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(
        description="EU Delegation to China — Trade/Economy News Crawler"
    )
    parser.add_argument(
        "--max-pages", type=int, default=50,
        help="最大翻页数量 (默认50, 覆盖约500条新闻)"
    )
    args = parser.parse_args()

    try:
        main(max_pages=args.max_pages)
    except KeyboardInterrupt:
        logger.info("\n⏸️  用户中断。进度已保存，重新运行即可续爬。")
        sys.exit(130)
    except Exception as e:
        logger.error("💥 致命错误: %s", str(e))
        import traceback
        traceback.print_exc()
        sys.exit(1)


# ============================================================================
# 使用说明
# ============================================================================

r"""
================================================================================
                            EU-China Trade News Crawler
                              使 用 说 明
================================================================================

【环境要求】
  Python 3.8+
  pip install requests beautifulsoup4 pdfplumber python-dateutil

【基本使用】
  python main.py                          # 默认爬取50页
  python main.py --max-pages 10           # 只爬10页 (测试用)
  python main.py --max-pages 100          # 爬100页

【输出目录】
  D:\项目流程\ep_corpus\
  ├── txt\                               # 每篇新闻一个TXT
  │   └── YYYYMMDD_文档ID.txt
  ├── csv\
  │   └── eu_china_trade_corpus.csv       # 增量追加，绝不覆盖
  ├── logs\
  │   └── crawl_YYYYMMDD_HHMMSS.log       # 运行日志
  └── progress.json                       # 断点续爬进度 (完成后自动删除)

【断点续爬】
  爬取中断后 (Ctrl+C 或网络断开)，直接重新运行相同命令即可从断点继续。
  已处理的URL自动跳过，已保存的文档不会重复写入。

【过滤规则】
  白名单：必须包含至少1个经贸关键词 (trade/investment/tariff/supply chain...)
  黑名单：仅含人权/文化/签证/旅游等非经贸内容且白名单命中小于黑名单 → 丢弃
  同时命中白名单+黑名单 (如 "trade and human rights") → 保留

【年份范围】
  仅识别 2017-2026，其余标记为 "其他"

【注意事项】
  - 单线程运行，请勿开多个实例（可能触发403封禁）
  - 列表页间隔5秒，详情页间隔5秒，PDF间隔10秒
  - 如需重置重新爬取，删除 progress.json 和 csv/ 目录即可
================================================================================
"""
