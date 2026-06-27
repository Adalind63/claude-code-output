# -*- coding: utf-8 -*-
"""
欧盟理事会 (consilium.europa.eu) 英文语料爬虫
=============================================
用途: 爬取欧盟理事会对华政策相关英文语料，用于欧盟对华话语政策语料库建设

搜索关键词 (20个):
    EU-China relations, EU-China trade, EU industrial policy, China,
    critical raw materials, semiconductors, electric vehicles, renewable energy,
    steel, market access, digital trade, subsidy investigation, anti-subsidy,
    anti-dumping, tariffs, investment screening, FDI, intellectual property, IP,
    carbon border adjustment, CBAM

自动分类:
    年份: 2017-2026
    议题领域: 半导体、新能源、钢铁、市场准入、数字贸易、补贴调查、关税、投资审查、知识产权、其他
    发布机构: 欧委会、欧洲议会、欧盟理事会、贸易总司(DG TRADE)、欧洲对外行动署(EEAS)、其他
    文件类型: 条例、报告、声明、白皮书、决议、其他

输出:
    TXT: 一篇一个文件 (含元数据头 + 全文)
    CSV: 汇总表 (含所有分类字段)

依赖安装:
    pip install requests beautifulsoup4 pandas lxml DrissionPage

使用方法:
    python consilium_crawler.py                  # 全新开始
    python consilium_crawler.py --resume          # 从断点续爬
    python consilium_crawler.py --mode sparql     # 仅使用 SPARQL 模式 (推荐，无需浏览器)
    python consilium_crawler.py --mode browser    # 仅使用浏览器模式
    python consilium_crawler.py --mode both       # 两种模式都运行
"""

import requests
from bs4 import BeautifulSoup, XMLParsedAsHTMLWarning
import pandas as pd
import os
import sys
import re
import json
import time
import random
import signal
import traceback
import argparse
import warnings
from datetime import datetime, timedelta
from urllib.parse import urljoin, quote

# 强制 stdout 使用 UTF-8 编码，避免 Windows GBK 控制台报错
if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

warnings.filterwarnings("ignore", category=XMLParsedAsHTMLWarning)

# ============================================================
# 第一部分: 全局配置
# ============================================================

class CrawlerConfig:
    """爬虫全局配置 — 所有可调参数集中管理"""

    # ---- 搜索关键词（必须全部纳入爬取范围）----
    SEARCH_KEYWORDS = [
        "EU-China relations",
        "EU-China trade",
        "EU industrial policy",
        "China",
        "critical raw materials",
        "semiconductors",
        "electric vehicles",
        "renewable energy",
        "steel",
        "market access",
        "digital trade",
        "subsidy investigation",
        "anti-subsidy",
        "anti-dumping",
        "tariffs",
        "investment screening",
        "FDI",
        "intellectual property",
        "IP",
        "carbon border adjustment",
        "CBAM",
    ]

    # ---- 年份范围 ----
    YEAR_START = 2017
    YEAR_END = 2026

    # ---- 反爬与延迟（严格遵守: 5~15秒随机间隔）----
    DELAY_MIN = 5.0
    DELAY_MAX = 15.0
    BATCH_DELAY_MIN = 60.0    # 每批次之间的额外休息
    BATCH_DELAY_MAX = 120.0
    BATCH_SIZE = 20           # 每爬取 N 篇后额外休息一次
    DAILY_MAX_REQUESTS = 500  # 每日最大请求数，超出则暂停

    # ---- SPARQL 端点配置 ----
    SPARQL_ENDPOINT = "https://publications.europa.eu/webapi/rdf/sparql"
    SPARQL_TIMEOUT = 120
    SPARQL_PAGE_LIMIT = 5000
    SPARQL_MAX_PAGES = 5

    # ---- 全文获取 ----
    FULLTEXT_URL_TEMPLATE = (
        "https://eur-lex.europa.eu/legal-content/EN/TXT/HTML/?uri=CELEX:{celex_id}"
    )
    FULLTEXT_TIMEOUT = 60
    FULLTEXT_RETRY_COUNT = 3

    # ---- 浏览器配置 ----
    BROWSER_TIMEOUT = 60        # 页面加载超时 (秒)
    BROWSER_CF_WAIT_MAX = 60    # Cloudflare 挑战等待最长时间 (秒)
    BROWSER_RESTART_EVERY = 100 # 每 N 次请求后重启浏览器

    # ---- 输出路径 ----
    DESKTOP = os.path.join(os.path.expanduser("~"), "Desktop")
    OUTPUT_ROOT = os.path.join(DESKTOP, "项目流程", "欧盟理事会")
    TXT_DIR = os.path.join(OUTPUT_ROOT, "txt")
    CSV_FILE = os.path.join(OUTPUT_ROOT, "consilium_docs.csv")
    CHECKPOINT_FILE = os.path.join(OUTPUT_ROOT, "checkpoint.json")

    # ---- User-Agent 池（12 个真实浏览器 UA）----
    USER_AGENTS = [
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:133.0) Gecko/20100101 Firefox/133.0",
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 14_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/18.1 Safari/605.1.15",
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36 Edg/131.0.0.0",
        "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0.0.0 Safari/537.36",
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0.0.0 Safari/537.36",
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/129.0.0.0 Safari/537.36",
        "Mozilla/5.0 (X11; Ubuntu; Linux x86_64; rv:132.0) Gecko/20100101 Firefox/132.0",
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.6 Safari/605.1.15",
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:128.0) Gecko/20100101 Firefox/128.0",
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36 Edg/131.0.0.0",
        "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36",
    ]

    # ---- 议题分类关键词 ----
    # 格式: (英文标签, 中文标签, [关键词列表])
    # 注意: 短关键词(≤3字符)使用词边界匹配，避免误匹配
    TOPIC_KEYWORDS = [
        ("semiconductors",      "半导体", [
            "semiconductor", "chip", "microchip", "integrated circuit", "wafer",
            "半导体", "芯片", "集成电路", "晶圆",
        ]),
        ("new energy",          "新能源", [
            "renewable energy", "solar energy", "wind energy",
            "electric vehicle", "EV", "clean energy", "photovoltaic", "solar panel",
            "新能源", "太阳能", "风能", "电动车", "光伏", "清洁能源", "电动汽车",
        ]),
        ("steel",               "钢铁", [
            "steel industry", "steel products", "steel sector",
            "aluminium", "aluminum", "钢铁", "钢材", "铝产品", "铝行业", "钢铝",
        ]),
        ("market access",       "市场准入", [
            "market access", "market opening", "public procurement",
            "level playing field", "市场准入", "市场开放", "政府采购", "公平竞争",
        ]),
        ("digital trade",       "数字贸易", [
            "digital trade", "e-commerce", "data flow", "data protection",
            "digital services", "cross-border data", "数字贸易", "电子商务",
            "数据流动", "数据保护", "跨境数据", "digital services act", "DSA",
        ]),
        ("subsidy investigation","补贴调查", [
            "subsidy", "anti-subsidy", "countervailing", "state aid",
            "补贴", "反补贴", "国家援助", "反补贴税",
        ]),
        ("tariffs",             "关税", [
            "tariff", "customs duty", "anti-dumping", "safeguard measure",
            "关税", "反倾销", "保障措施", "附加关税", "CBAM",
            "carbon border adjustment", "碳边境",
        ]),
        ("investment screening", "投资审查", [
            "investment screening", "foreign direct investment",
            "foreign investment", "outward investment", "FDI",
            "投资审查", "外商直接投资", "外资审查", "对外投资",
        ]),
        ("intellectual property","知识产权", [
            "intellectual property", "IPR", "patent", "copyright", "trademark",
            "trade secret", "IP theft", "forced technology transfer",
            "知识产权", "专利", "版权", "商标", "技术转让",
        ]),
    ]

    # ---- 发布机构映射 ----
    INSTITUTION_MAP = [
        (["TRADE", "DG-TRADE", "DIRECTORATE-GENERAL-TRADE", "DG_TRADE"],
         "DG TRADE", "贸易总司(DG TRADE)", 1),
        (["EEAS", "EXTERNAL-ACTION-SERVICE", "EUROPEAN-EXTERNAL-ACTION"],
         "EEAS", "欧洲对外行动署(EEAS)", 2),
        (["COM", "COMMISSION", "EUROPEAN-COMMISSION"],
         "European Commission", "欧委会", 3),
        (["EP", "PARL", "EUROPEAN-PARLIAMENT"],
         "European Parliament", "欧洲议会", 4),
        (["CONSIL", "COUNCIL-OF-THE-EUROPEAN-UNION", "COUNCIL"],
         "Council of the EU", "欧盟理事会", 5),
        (["ECB", "EUROPEAN-CENTRAL-BANK"],
         "European Central Bank", "欧洲央行", 6),
        (["EESC", "EUROPEAN-ECONOMIC-AND-SOCIAL"],
         "European Economic and Social Committee", "欧洲经社委员会", 6),
        (["COR", "COMMITTEE-OF-THE-REGIONS"],
         "Committee of the Regions", "地区委员会", 6),
    ]

    # ---- 文件类型映射 ----
    DOC_TYPE_MAP = {
        "REG": ("Regulation", "条例"),
        "REG_IMPL": ("Implementing Regulation", "实施条例"),
        "REG_DEL": ("Delegated Regulation", "授权条例"),
        "DIR": ("Directive", "指令"),
        "DIR_IMPL": ("Implementing Directive", "实施指令"),
        "DIR_DEL": ("Delegated Directive", "授权指令"),
        "DEC": ("Decision", "决定"),
        "DEC_IMPL": ("Implementing Decision", "实施决定"),
        "REC": ("Recommendation", "建议"),
        "RES": ("Resolution", "决议"),
        "RESOLUTION": ("Resolution", "决议"),
        "LEGIS-RES": ("Legislative Resolution", "立法决议"),
        "REPORT": ("Report", "报告"),
        "COMMUNICATION": ("Communication", "通讯文件"),
        "NOT": ("Notice", "公告"),
        "NOTICE": ("Notice", "公告"),
        "ANNOUNC": ("Announcement", "公告"),
        "ANNOUNCEMENT": ("Announcement", "公告"),
        "INFO": ("Information", "信息通告"),
        "INFORMATION": ("Information", "信息通告"),
        "CASE-LAW": ("Case Law", "判例法"),
        "JUDG": ("Judgment", "判决书"),
        "JUDGMENT": ("Judgment", "判决书"),
        "COM_DOC": ("Commission Document", "委员会文件"),
        "STATEMENT": ("Statement", "声明"),
        "DECL": ("Declaration", "声明"),
        "JOINT-DECL": ("Joint Declaration", "联合声明"),
        "JOINT_DECL": ("Joint Declaration", "联合声明"),
        "CONCLUSIONS": ("Conclusions", "结论"),
        "WHITE-PAPER": ("White Paper", "白皮书"),
        "GREEN-PAPER": ("Green Paper", "绿皮书"),
        "PROPOSAL": ("Proposal", "提案"),
        "OPINION": ("Opinion", "意见书"),
        "PRESS-RELEASE": ("Press Release", "新闻稿"),
        "PRESS_RELEASE": ("Press Release", "新闻稿"),
        "SPEECH": ("Speech", "演讲"),
        "NOTE": ("Note", "说明文件"),
        "WORKING-DOCUMENT": ("Working Document", "工作文件"),
        "STUDY": ("Study", "研究报告"),
    }

    # ---- consilium.europa.eu 列表页 URL 模板 ----
    COUNCIL_LIST_URLS = [
        # 新闻稿列表
        {
            "url_template": "https://www.consilium.europa.eu/en/press/press-releases/?page={page}",
            "label": "Press Releases",
            "doc_type_default": ("Press Release", "新闻稿"),
            "institution_default": ("Council of the EU", "欧盟理事会"),
        },
        # 会议结论
        {
            "url_template": "https://www.consilium.europa.eu/en/press/press-releases/?page={page}&type=conclusions",
            "label": "Council Conclusions",
            "doc_type_default": ("Conclusions", "结论"),
            "institution_default": ("Council of the EU", "欧盟理事会"),
        },
        # 声明
        {
            "url_template": "https://www.consilium.europa.eu/en/press/press-releases/?page={page}&type=statements",
            "label": "Statements",
            "doc_type_default": ("Statement", "声明"),
            "institution_default": ("Council of the EU", "欧盟理事会"),
        },
    ]


# ============================================================
# 第二部分: 断点管理器
# ============================================================

class CheckpointManager:
    """
    断点续爬管理器
    - 使用 JSON 文件持久化已完成的 URL
    - 支持原子写入（先写临时文件，再替换），防止写入中断导致损坏
    """

    def __init__(self, checkpoint_path):
        self.path = checkpoint_path
        self.completed_urls = set()
        self.total_completed = 0
        self.last_updated = None
        self._load()

    def _load(self):
        if os.path.exists(self.path):
            try:
                with open(self.path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                self.completed_urls = set(data.get("completed_urls", []))
                self.total_completed = data.get("total_completed", len(self.completed_urls))
                self.last_updated = data.get("last_updated", "")
                print(f"[断点] 已加载: {self.total_completed} 条已完成记录")
                if self.last_updated:
                    print(f"       最后更新: {self.last_updated}")
            except (json.JSONDecodeError, IOError) as e:
                print(f"[警告] 断点文件损坏，将重新开始: {e}")
                self.completed_urls = set()
                self.total_completed = 0
        else:
            print("[断点] 未发现断点文件，开始全新爬取")

    def is_completed(self, url):
        """检查某 URL 是否已完成"""
        return url in self.completed_urls

    def mark_completed(self, url):
        """标记一条记录为已完成并立即写入磁盘"""
        self.completed_urls.add(url)
        self.total_completed = len(self.completed_urls)
        self.last_updated = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        self._save()

    def _save(self):
        """原子写入断点文件"""
        data = {
            "completed_urls": list(self.completed_urls),
            "total_completed": self.total_completed,
            "last_updated": self.last_updated,
        }
        temp_path = self.path + ".tmp"
        try:
            with open(temp_path, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
            os.replace(temp_path, self.path)
        except OSError as e:
            print(f"[警告] 断点保存失败: {e}")

    def summary(self):
        return f"已完成: {self.total_completed} 条"


# ============================================================
# 第三部分: 反爬节流器
# ============================================================

class Throttle:
    """
    反爬节流器
    - 每次请求前随机延迟 5~15 秒
    - User-Agent 轮换
    - 每日请求限额
    - 批次额外休息
    """

    def __init__(self, config):
        self.config = config
        self.user_agents = config.USER_AGENTS
        self.delay_min = config.DELAY_MIN
        self.delay_max = config.DELAY_MAX
        self.batch_size = config.BATCH_SIZE
        self.daily_max = config.DAILY_MAX_REQUESTS
        self.current_ua = random.choice(self.user_agents)
        self.request_count = 0
        self.batch_count = 0
        self.today_date = datetime.now().date()
        self.today_requests = 0

    def wait(self, label=""):
        """
        执行反爬等待:
        1. 检查每日限额
        2. 随机延迟 5~15 秒
        3. 每 N 次请求额外休息
        4. 轮换 User-Agent
        """
        # 检查日期变化
        today = datetime.now().date()
        if today != self.today_date:
            self.today_date = today
            self.today_requests = 0

        # 每日限额检查
        if self.today_requests >= self.daily_max:
            print(f"\n{'='*60}")
            print(f"[限额] 今日请求已达上限 ({self.daily_max})")
            print(f"[限额] 将于明天 {datetime.now().replace(hour=0, minute=0, second=0) + timedelta(days=1)} 继续")
            print(f"[限额] 按 Ctrl+C 随时保存断点退出")
            print(f"{'='*60}")
            # 等待到明天凌晨
            seconds_until_midnight = (
                (datetime.now().replace(hour=0, minute=0, second=0) + timedelta(days=1))
                - datetime.now()
            ).total_seconds()
            if seconds_until_midnight > 0 and seconds_until_midnight < 86400:
                time.sleep(min(seconds_until_midnight, 3600))  # 最多等1小时
            self.today_requests = 0

        # 随机延迟 5~15 秒
        delay = random.uniform(self.delay_min, self.delay_max)
        if label:
            print(f"  [延迟] {delay:.1f}s ... ({label})")
        time.sleep(delay)

        # 轮换 UA
        self.current_ua = random.choice(self.user_agents)

        # 计数
        self.request_count += 1
        self.today_requests += 1
        self.batch_count += 1

        # 批次额外休息（每 N 次请求后）
        if self.batch_count >= self.batch_size:
            extra_delay = random.uniform(self.config.BATCH_DELAY_MIN, self.config.BATCH_DELAY_MAX)
            print(f"\n  [批次休息] 已完成 {self.batch_count} 次请求，额外等待 {extra_delay:.1f}s ...")
            time.sleep(extra_delay)
            self.batch_count = 0

    def get_headers(self):
        """获取当前请求头"""
        return {
            "User-Agent": self.current_ua,
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "en-US,en;q=0.9",
            "Accept-Encoding": "gzip, deflate, br",
            "Connection": "keep-alive",
            "DNT": "1",
        }


# ============================================================
# 第四部分: 关键词过滤器
# ============================================================

class KeywordFilter:
    """
    本地关键词过滤器
    在爬取的标题和全文中检测是否包含目标关键词
    只有匹配至少一个关键词的文档才被保留
    """

    def __init__(self, keywords):
        self.keywords = keywords
        # 构建正则：对每个关键词进行词边界匹配（避免 "IP" 误匹配 "chip"）
        patterns = []
        for kw in keywords:
            kw_lower = kw.lower()
            if len(kw) <= 3:
                patterns.append(r'\b' + re.escape(kw_lower) + r'\b')
            else:
                patterns.append(re.escape(kw_lower))
        self.pattern = re.compile('|'.join(patterns), re.IGNORECASE)
        self.simple_kws = set(kw.lower() for kw in keywords if len(kw) > 3)

    def matches(self, title, full_text=""):
        """
        检查文档是否匹配至少一个关键词
        搜索范围: 标题 + 全文前 10000 字符
        """
        search_text = (title or "") + " " + (full_text or "")[:10000]
        search_lower = search_text.lower()

        # 先用正则匹配（处理短关键词的词边界）
        if self.pattern.search(search_text):
            return True

        # 再用简单子串匹配（长关键词）
        for kw in self.simple_kws:
            if kw in search_lower:
                return True

        return False


# ============================================================
# 第五部分: 自动分类器
# ============================================================

class DocumentClassifier:
    """
    自动分类器
    根据标题、全文和元数据对文档进行四维分类:
    - 年份: 2017-2026
    - 议题领域: 10 类
    - 发布机构: 6 类
    - 文件类型: 6 类
    """

    def __init__(self, config):
        self.topic_keywords = config.TOPIC_KEYWORDS
        self.institution_map = config.INSTITUTION_MAP
        self.doc_type_map = config.DOC_TYPE_MAP

    def classify(self, title, full_text, meta=None):
        """
        对单篇文档进行全部分类
        meta: dict, 可包含 date, author_uris, author_labels, type_uri, default_institution, default_type
        """
        meta = meta or {}
        year = self._classify_year(meta.get("date", ""))
        institution_en, institution_zh = self._classify_institution(meta)
        doc_type_en, doc_type_zh = self._classify_doc_type(meta)
        topic_en, topic_zh = self._classify_topic(title, full_text)

        return {
            "year": year,
            "topic_en": topic_en,
            "topic_zh": topic_zh,
            "institution_en": institution_en,
            "institution_zh": institution_zh,
            "doc_type_en": doc_type_en,
            "doc_type_zh": doc_type_zh,
        }

    def _classify_year(self, date_str):
        """从日期字符串提取年份"""
        if not date_str:
            return ""
        match = re.match(r"(\d{4})", str(date_str))
        if match:
            return match.group(1)
        return ""

    def _classify_institution(self, meta):
        """
        根据元数据判断发布机构
        优先级: DG TRADE > EEAS > Commission > Parliament > Council > other
        """
        # 收集候选文本
        candidates = []
        for uri in meta.get("author_uris", []):
            if uri:
                candidates.append(uri.rstrip("/").rsplit("/", 1)[-1])
        for label in meta.get("author_labels", []):
            if label:
                candidates.append(label)

        # 使用默认机构（适用于直接从 Council 网站爬取的内容）
        if not candidates and meta.get("default_institution"):
            return meta["default_institution"]

        if not candidates:
            return "Other", "其他"

        # 按优先级匹配
        sorted_map = sorted(self.institution_map, key=lambda x: x[3])
        for uri_kws, en_name, zh_name, priority in sorted_map:
            for cand in candidates:
                cand_upper = cand.upper()
                for kw in uri_kws:
                    if kw.upper() == cand_upper or kw.upper() in cand_upper:
                        return en_name, zh_name

        # 如果所有匹配都失败，尝试从 URI 中提取（不返回无意义的非英文标签）
        for uri in meta.get("author_uris", []):
            if uri:
                last_seg = uri.rstrip("/").rsplit("/", 1)[-1].replace("-", " ")
                # 检查是否为已知的机构缩写
                for uri_kws, en_name, zh_name, priority in sorted_map:
                    if any(kw.upper() in last_seg.upper() for kw in uri_kws):
                        return en_name, zh_name
                # 常见缩写直接映射
                if "CONSIL" in last_seg.upper():
                    return "Council of the EU", "欧盟理事会"
                if "COMMISSION" in last_seg.upper() or last_seg.upper().startswith("COM"):
                    return "European Commission", "欧委会"
                if "PARLIAMENT" in last_seg.upper() or "PARL" in last_seg.upper():
                    return "European Parliament", "欧洲议会"

        return "Other", "其他"

    def _classify_doc_type(self, meta):
        """
        根据 type_uri 或默认类型判断文件类型
        """
        # 优先使用默认类型（适用于从 Council 网站爬取的内容）
        type_uri = meta.get("type_uri", "")
        if not type_uri and meta.get("default_type"):
            return meta["default_type"]

        if not type_uri:
            return "Other", "其他"

        last_seg = type_uri.rstrip("/").rsplit("/", 1)[-1].upper()

        if last_seg in self.doc_type_map:
            return self.doc_type_map[last_seg]

        # 模糊匹配
        for seg_key, (en_name, zh_name) in self.doc_type_map.items():
            if seg_key in last_seg or last_seg in seg_key:
                return en_name, zh_name

        return "Other", "其他"

    def _classify_topic(self, title, full_text):
        """
        基于标题+全文关键词匹配判断议题领域
        搜索范围: 标题 + 全文前 5000 字符
        短关键词(≤3字符)使用词边界匹配
        """
        search_text = (title or "") + " " + (full_text or "")[:5000]
        search_lower = search_text.lower()

        for topic_en, topic_zh, keywords in self.topic_keywords:
            for kw in keywords:
                kw_lower = kw.lower()
                if len(kw) <= 3:
                    pattern = r'\b' + re.escape(kw_lower) + r'\b'
                    if re.search(pattern, search_lower):
                        return topic_en, topic_zh
                else:
                    if kw_lower in search_lower:
                        return topic_en, topic_zh

        return "other", "其他"


# ============================================================
# 第六部分: 输出写入器
# ============================================================

class OutputWriter:
    """写入 TXT 文件和管理 CSV 缓冲区"""

    def __init__(self, config):
        self.txt_dir = config.TXT_DIR
        self.csv_path = config.CSV_FILE
        self.csv_rows = []

    def setup_dirs(self):
        """创建输出目录"""
        os.makedirs(self.txt_dir, exist_ok=True)
        os.makedirs(os.path.dirname(self.csv_path), exist_ok=True)
        print(f"[输出] TXT 目录: {self.txt_dir}")
        print(f"[输出] CSV 路径: {self.csv_path}")

    def _safe_filename(self, url_or_id):
        """将 URL 或 ID 转换为安全的文件名"""
        # 提取文件名友好的部分
        safe = re.sub(r'[\\/:*?"<>|]', '_', url_or_id)
        safe = safe.replace('https___www_consilium_europa_eu_', '')
        safe = safe.replace('https_', '')
        if len(safe) > 80:
            safe = safe[:80]
        return safe.strip('_')

    def write_txt(self, doc_id, title, date_str, classification, full_text, original_url):
        """写入单篇 TXT 文件"""
        filename = self._safe_filename(doc_id) + ".txt"
        filepath = os.path.join(self.txt_dir, filename)

        # 格式化日期
        date_display = str(date_str) if date_str else "N/A"
        if isinstance(date_display, str) and "T" in date_display:
            date_display = date_display.split("T")[0]

        header = (
            f"Title: {title}\n"
            f"Date: {date_display}\n"
            f"Source: Council of the EU (consilium.europa.eu)\n"
            f"Institution (EN): {classification.get('institution_en', 'N/A')}\n"
            f"Institution (ZH): {classification.get('institution_zh', 'N/A')}\n"
            f"Document Type (EN): {classification.get('doc_type_en', 'N/A')}\n"
            f"Document Type (ZH): {classification.get('doc_type_zh', 'N/A')}\n"
            f"Topic (EN): {classification.get('topic_en', 'N/A')}\n"
            f"Topic (ZH): {classification.get('topic_zh', 'N/A')}\n"
            f"Year: {classification.get('year', 'N/A')}\n"
            f"Original URL: {original_url}\n"
            f"{'='*70}\n\n"
        )

        try:
            with open(filepath, "w", encoding="utf-8") as f:
                f.write(header)
                f.write(full_text)
        except OSError as e:
            print(f"    [错误] TXT 写入失败: {e}")

    def append_csv_row(self, doc_id, title, date_str, classification, full_text, original_url):
        """追加一行到 CSV 缓冲区"""
        date_display = str(date_str) if date_str else ""
        if "T" in date_display:
            date_display = date_display.split("T")[0]

        self.csv_rows.append({
            "文档ID": doc_id,
            "标题 (Title)": title,
            "发布日期 (Publication Date)": date_display,
            "全文 (Full Text)": full_text,
            "发布机构_EN (Institution EN)": classification.get("institution_en", ""),
            "发布机构_ZH (Institution ZH)": classification.get("institution_zh", ""),
            "文件类型_EN (Document Type EN)": classification.get("doc_type_en", ""),
            "文件类型_ZH (Document Type ZH)": classification.get("doc_type_zh", ""),
            "年份 (Year)": classification.get("year", ""),
            "主题_EN (Topic EN)": classification.get("topic_en", ""),
            "主题_ZH (Topic ZH)": classification.get("topic_zh", ""),
            "原文链接 (Original URL)": original_url,
        })

    def flush_csv(self):
        """将 CSV 缓冲区写入磁盘 (UTF-8-BOM 编码，兼容 Excel)"""
        if not self.csv_rows:
            print("[CSV] 无数据，跳过 CSV 输出")
            return

        df = pd.DataFrame(self.csv_rows)
        if "年份 (Year)" in df.columns:
            df = df.sort_values(by=["年份 (Year)", "文档ID"], ascending=[False, True])

        df.to_csv(self.csv_path, index=False, encoding="utf-8-sig")
        print(f"[CSV] 已保存 {len(self.csv_rows)} 条记录 → {self.csv_path}")


# ============================================================
# 第七部分: SPARQL 查询客户端 (用于 EUR-Lex)
# ============================================================

class SparqlClient:
    """
    SPARQL 查询客户端
    通过 EU Publications Office SPARQL 端点检索 Council 文档
    这个端点没有 Cloudflare 保护！
    """

    def __init__(self, config, throttle):
        self.endpoint = config.SPARQL_ENDPOINT
        self.timeout = config.SPARQL_TIMEOUT
        self.page_limit = config.SPARQL_PAGE_LIMIT
        self.max_pages = config.SPARQL_MAX_PAGES
        self.throttle = throttle

    def _build_query(self, year):
        """
        构建 SPARQL 查询
        策略:
          1. 标题必须包含 China/Chinese/Beijing/EU-China（核心中国相关）
          2. 或标题同时包含 EU/European + 对华政策关键词（CBAM, anti-subsidy 等）
          避免匹配大量无关内部文件
        """
        # 核心过滤: 标题中必须出现中国相关词汇
        china_filter = (
            'REGEX(STR(?title), "China", "i") || '
            'REGEX(STR(?title), "Chinese", "i") || '
            'REGEX(STR(?title), "Beijing", "i") || '
            'REGEX(STR(?title), "EU-China", "i")'
        )

        # 扩展过滤: 如果没有 China 但涉及明确的对华政策工具（CBAM、反补贴等）
        # 这些文件大概率与中国相关
        extended_filter = (
            'REGEX(STR(?title), "anti-subsidy", "i") || '
            'REGEX(STR(?title), "anti-dumping", "i") || '
            'REGEX(STR(?title), "CBAM", "i") || '
            'REGEX(STR(?title), "carbon border adjustment", "i") || '
            'REGEX(STR(?title), "foreign subsidy", "i") || '
            'REGEX(STR(?title), "countervailing", "i") || '
            'REGEX(STR(?title), "electric vehicle", "i") || '
            'REGEX(STR(?title), "semiconductor", "i") || '
            'REGEX(STR(?title), "investment screening", "i") || '
            'REGEX(STR(?title), "de-risking", "i")'
        )

        keyword_filters = f"({china_filter}) || ({extended_filter})"

        query = f"""
PREFIX cdm: <http://publications.europa.eu/ontology/cdm#>
PREFIX xsd: <http://www.w3.org/2001/XMLSchema#>
PREFIX skos: <http://www.w3.org/2004/02/skos/core#>

SELECT DISTINCT ?celex ?title ?date ?author_uri ?author_label ?type_uri
WHERE {{
  ?work cdm:work_date_document ?date .
  ?work cdm:resource_legal_id_celex ?celex .
  ?work cdm:work_has_resource-type ?type_uri .

  OPTIONAL {{
    ?work cdm:work_created_by_agent ?author_uri .
    OPTIONAL {{ ?author_uri skos:prefLabel ?author_label . }}
  }}

  ?expr cdm:expression_belongs_to_work ?work .
  ?expr cdm:expression_title ?title .
  ?expr cdm:expression_uses_language
    <http://publications.europa.eu/resource/authority/language/ENG> .

  FILTER (
    {keyword_filters}
  )
  FILTER (YEAR(?date) = {year})
  FILTER NOT EXISTS {{
    ?work cdm:work_has_resource-type
      <http://publications.europa.eu/resource/authority/resource-type/CORRIGENDUM>
  }}
  FILTER NOT EXISTS {{
    ?work cdm:do_not_index "true"^^xsd:boolean
  }}
}}
ORDER BY DESC(?date)
"""
        return query

    def query_year(self, year):
        """查询指定年份的所有匹配文档"""
        print(f"\n{'='*60}")
        print(f"[SPARQL] 查询年份: {year}")
        print(f"{'='*60}")

        query = self._build_query(year)
        all_docs = []
        seen_celex = set()

        for page in range(self.max_pages):
            offset = page * self.page_limit
            if page > 0:
                time.sleep(random.uniform(2.0, 5.0))

            print(f"  [SPARQL] 第 {page+1} 页 (OFFSET={offset})...", end=" ", flush=True)

            data = self._post_query(query, offset)
            if data is None:
                print("失败")
                break

            bindings = data.get("results", {}).get("bindings", [])
            print(f"返回 {len(bindings)} 条")

            if not bindings:
                break

            for b in bindings:
                celex = b.get("celex", {}).get("value", "")
                if not celex:
                    continue

                if celex in seen_celex:
                    continue
                seen_celex.add(celex)

                title = b.get("title", {}).get("value", "")
                date = b.get("date", {}).get("value", "")
                author_uri = b.get("author_uri", {}).get("value", "")
                author_label = b.get("author_label", {}).get("value", "")
                type_uri = b.get("type_uri", {}).get("value", "")

                all_docs.append({
                    "celex": celex,
                    "title": title,
                    "date": date,
                    "author_uris": [author_uri] if author_uri else [],
                    "author_labels": [author_label] if author_label else [],
                    "type_uri": type_uri,
                    "source": "EUR-Lex",
                })

            if len(bindings) < self.page_limit:
                break

        print(f"  [SPARQL] 年份 {year}: 共 {len(all_docs)} 篇（去重后）")
        return all_docs

    def _post_query(self, query, offset=0):
        """发送 SPARQL 查询"""
        full_query = query + f"\nLIMIT {self.page_limit}\nOFFSET {offset}"
        try:
            resp = requests.post(
                self.endpoint,
                data={"query": full_query, "format": "application/json"},
                headers={"User-Agent": self.throttle.current_ua},
                timeout=self.timeout,
            )
            if resp.status_code == 200:
                return resp.json()
            else:
                print(f"HTTP {resp.status_code}")
                return None
        except requests.Timeout:
            print("超时")
            return None
        except requests.ConnectionError as e:
            print(f"连接失败: {e}")
            return None


# ============================================================
# 第八部分: 全文获取器
# ============================================================

class TextFetcher:
    """从 EUR-Lex 获取文档全文（HTML → 纯文本）"""

    def __init__(self, config, throttle):
        self.url_template = config.FULLTEXT_URL_TEMPLATE
        self.timeout = config.FULLTEXT_TIMEOUT
        self.retry_count = config.FULLTEXT_RETRY_COUNT
        self.throttle = throttle

    def fetch(self, celex_id):
        """获取文档全文，返回 (text, success)"""
        url = self.url_template.format(celex_id=celex_id)

        for attempt in range(1, self.retry_count + 1):
            try:
                resp = requests.get(
                    url,
                    headers=self.throttle.get_headers(),
                    timeout=self.timeout,
                    allow_redirects=True,
                )

                if resp.status_code == 200:
                    text = self._extract_text(resp.text)
                    if text and len(text.strip()) > 50:
                        return text, True
                    else:
                        if attempt < self.retry_count:
                            time.sleep(10 * attempt)
                        continue

                elif resp.status_code == 404:
                    return "[NO_ENGLISH_TEXT_AVAILABLE]", False

                elif resp.status_code == 429:
                    wait_time = 60 + random.uniform(0, 30)
                    print(f"    [限流] 429, 等待 {wait_time:.0f}s ...")
                    time.sleep(wait_time)
                    continue

                elif resp.status_code in (502, 503, 504):
                    if attempt < self.retry_count:
                        time.sleep(10 * attempt)
                    continue

                else:
                    if attempt < self.retry_count:
                        time.sleep(10 * attempt)
                    continue

            except requests.Timeout:
                if attempt < self.retry_count:
                    time.sleep(15 * attempt)
            except requests.ConnectionError:
                if attempt < self.retry_count:
                    time.sleep(15 * attempt)
            except Exception as e:
                print(f"    [获取错误] {e}")
                if attempt < self.retry_count:
                    time.sleep(10 * attempt)

        return "[FETCH_FAILED]", False

    def _extract_text(self, html):
        """从 HTML 中提取纯文本"""
        soup = BeautifulSoup(html, "lxml" if self._has_lxml() else "html.parser")

        for tag_name in ["script", "style", "nav", "footer", "header", "meta", "link"]:
            for tag in soup.find_all(tag_name):
                tag.decompose()

        body = soup.find("body")
        if body:
            text = body.get_text(separator="\n", strip=True)
        else:
            text = soup.get_text(separator="\n", strip=True)

        text = re.sub(r"\n{3,}", "\n\n", text)
        text = re.sub(r"[ \t]{3,}", "  ", text)
        return text.strip()

    @staticmethod
    def _has_lxml():
        try:
            import lxml
            return True
        except ImportError:
            return False


# ============================================================
# 第九部分: 浏览器管理器 (DrissionPage)
# ============================================================

class BrowserManager:
    """
    浏览器管理器
    使用 DrissionPage 驱动 Chromium，处理 Cloudflare 挑战
    """

    def __init__(self, config):
        self.config = config
        self._page = None
        self._restart_counter = 0

    @property
    def page(self):
        """懒加载浏览器页面"""
        if self._page is None:
            self._start_browser()
        return self._page

    def _start_browser(self):
        """启动浏览器并配置反检测参数"""
        print("[浏览器] 正在启动 Chromium ...")
        try:
            from DrissionPage import ChromiumPage, ChromiumOptions

            co = ChromiumOptions()
            co.set_argument("--no-sandbox")
            co.set_argument("--disable-gpu")
            co.set_argument("--disable-blink-features=AutomationControlled")
            co.set_argument("--window-size=1920,1080")
            co.set_argument(
                "--user-agent="
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/131.0.0.0 Safari/537.36"
            )
            co.headless(False)  # 非无头模式：Cloudflare 需要 JS 执行

            self._page = ChromiumPage(co)
            print("[浏览器] 启动成功")
        except ImportError:
            print("[浏览器] DrissionPage 未安装！")
            print("[浏览器] 请运行: pip install DrissionPage")
            self._page = None
        except Exception as e:
            print(f"[浏览器] 启动失败: {e}")
            self._page = None

    def navigate(self, url, wait_cf=True):
        """
        导航到指定 URL，自动处理 Cloudflare 挑战
        返回: (success, html_content)
        """
        if self._page is None:
            return False, None

        try:
            self._page.get(url, timeout=self.config.BROWSER_TIMEOUT)
        except Exception as e:
            print(f"    [浏览器] 导航失败: {e}")
            return False, None

        # 等待 Cloudflare 挑战解决
        if wait_cf:
            cf_resolved = self._wait_for_cloudflare()
            if not cf_resolved:
                print(f"    [浏览器] Cloudflare 挑战未解决")
                return False, None

        # 获取页面内容
        try:
            html = self._page.html
            return True, html
        except Exception as e:
            print(f"    [浏览器] 获取 HTML 失败: {e}")
            return False, None

    def _wait_for_cloudflare(self, timeout=None):
        """
        等待 Cloudflare 挑战自动解决
        检测页面标题不再包含 "请稍候" / "Checking" 等字样
        """
        if timeout is None:
            timeout = self.config.BROWSER_CF_WAIT_MAX

        start = time.time()
        check_interval = 2  # 每 2 秒检查一次

        while time.time() - start < timeout:
            try:
                title = self._page.title
                url = self._page.url

                # 检查是否仍在 Cloudflare 挑战页面
                cf_indicators = [
                    "请稍候",
                    "Checking your browser",
                    "Browser check",
                    "cf_chl",
                ]
                still_blocked = any(ind in title or ind in url
                                   for ind in cf_indicators)

                if not still_blocked:
                    # 等待额外 2 秒确保页面完全渲染
                    time.sleep(2)
                    return True

                elapsed = int(time.time() - start)
                print(f"    [Cloudflare] 等待中... ({elapsed}s)")
                time.sleep(check_interval)

            except Exception:
                time.sleep(check_interval)

        return False

    def restart(self):
        """重启浏览器（用于定期重置，避免内存泄漏）"""
        self._restart_counter += 1
        print(f"[浏览器] 重启 # {self._restart_counter} ...")
        self.quit()
        time.sleep(random.uniform(5, 10))
        self._start_browser()

    def should_restart(self):
        """检查是否应该重启浏览器"""
        return self._restart_counter * self.config.BROWSER_RESTART_EVERY < self.config.BROWSER_RESTART_EVERY

    def quit(self):
        """关闭浏览器"""
        if self._page:
            try:
                self._page.quit()
            except Exception:
                pass
            self._page = None


# ============================================================
# 第十部分: Council 页面爬取器 (浏览器模式)
# ============================================================

class CouncilPageCrawler:
    """
    consilium.europa.eu 页面爬取器
    使用浏览器自动化遍历列表页并提取文章详情
    """

    def __init__(self, config, browser, keyword_filter, classifier):
        self.config = config
        self.browser = browser
        self.keyword_filter = keyword_filter
        self.classifier = classifier

    def crawl_list_pages(self, list_config):
        """
        遍历某个列表页类型（如 press-releases），
        提取所有文章的 URL 和元数据
        返回: list[dict]
        """
        label = list_config["label"]
        url_template = list_config["url_template"]
        doc_type_default = list_config["doc_type_default"]
        institution_default = list_config["institution_default"]

        print(f"\n{'='*60}")
        print(f"[列表爬取] {label}")
        print(f"{'='*60}")

        all_articles = []

        for page_num in range(1, 200):  # 最多 200 页
            url = url_template.format(page=page_num)
            print(f"  [第 {page_num} 页] {url}")

            success, html = self.browser.navigate(url)
            if not success:
                print(f"    [跳过] 页面加载失败")
                break

            # 解析列表页
            articles = self._parse_list_page(html, url)
            if not articles:
                print(f"    [结束] 无更多文章")
                break

            print(f"    [找到] {len(articles)} 篇文章")
            all_articles.extend(articles)

            # 检查是否有超出年份范围的文章
            oldest_year = self._get_oldest_year(articles)
            if oldest_year and oldest_year < self.config.YEAR_START:
                print(f"    [停止] 已到达 {self.config.YEAR_START} 年之前的内容")
                break

            # 页面间的反爬延迟
            if page_num > 1:
                time.sleep(random.uniform(
                    self.config.DELAY_MIN, self.config.DELAY_MAX
                ))

        print(f"\n  [{label}] 总共提取 {len(all_articles)} 篇文章")
        return all_articles

    def _parse_list_page(self, html, list_url):
        """
        从列表页 HTML 中提取文章信息
        适配 consilium.europa.eu 的 HTML 结构
        """
        soup = BeautifulSoup(html, "lxml" if self._has_lxml() else "html.parser")
        articles = []

        # 尝试多种可能的选择器（适配不同页面结构）
        article_selectors = [
            "article",
            ".card",
            ".listing-item",
            ".view-content .views-row",
            ".search-result",
            "li a[href*='/en/press/']",
        ]

        for selector in article_selectors:
            items = soup.select(selector)
            if items and len(items) >= 2:
                break

        if not items:
            # 最后的尝试：直接查找所有内部链接
            items = []
            for a in soup.find_all("a", href=True):
                href = a.get("href", "")
                if any(pat in href for pat in [
                    "/en/press/press-releases/20",
                    "/en/press/press-releases/201",
                ]):
                    if a not in items:
                        items.append(a)

        for item in items:
            try:
                article_info = self._extract_article_info(item, list_url)
                if article_info:
                    articles.append(article_info)
            except Exception as e:
                print(f"    [警告] 解析文章失败: {e}")
                continue

        return articles

    def _extract_article_info(self, item, list_url):
        """从单个列表项中提取文章信息"""
        # 找链接
        link_tag = item if item.name == "a" else item.find("a", href=True)
        if not link_tag:
            return None

        href = link_tag.get("href", "")
        if not href:
            return None

        # 转换为绝对 URL
        full_url = urljoin(list_url, href)

        # 只处理 press-releases 相关链接
        if "/en/press/press-releases/" not in full_url:
            return None

        # 提取标题
        title = link_tag.get_text(strip=True)
        if not title or len(title) < 10:
            # 尝试从父元素找标题
            for heading in item.find_all(["h2", "h3", "h4", "h5"]):
                title = heading.get_text(strip=True)
                if title:
                    break

        if not title or len(title) < 10:
            title = "Untitled"

        # 提取日期
        date_str = ""
        date_tag = item.find("time")
        if date_tag:
            date_str = date_tag.get("datetime", date_tag.get_text(strip=True))
        if not date_str:
            # 尝试匹配日期模式
            date_match = re.search(r'(\d{1,2}\s+(January|February|March|April|May|June|July|August|September|October|November|December)\s+\d{4})', str(item))
            if date_match:
                date_str = date_match.group(1)

        return {
            "title": title,
            "url": full_url,
            "date_str": date_str,
        }

    def fetch_article_detail(self, article_info):
        """
        访问文章详情页，提取全文
        返回: (full_text, success)
        """
        url = article_info["url"]
        print(f"    [详情] {url[:100]}")

        success, html = self.browser.navigate(url)
        if not success:
            return "[PAGE_LOAD_FAILED]", False

        text = self._extract_detail_text(html)
        if text and len(text.strip()) > 100:
            return text, True
        else:
            return "[TEXT_TOO_SHORT]", False

    def _extract_detail_text(self, html):
        """从文章详情页提取正文"""
        soup = BeautifulSoup(html, "lxml" if self._has_lxml() else "html.parser")

        # 移除无用标签
        for tag_name in ["script", "style", "nav", "footer", "header", "meta", "link", "noscript"]:
            for tag in soup.find_all(tag_name):
                tag.decompose()

        # 尝试找到主要内容区域
        content_selectors = [
            ".content",
            ".main-content",
            ".page-content",
            "#content",
            "article",
            ".article-content",
            ".press-release-content",
            "main",
        ]

        content = None
        for selector in content_selectors:
            content = soup.select_one(selector)
            if content:
                break

        if content:
            text = content.get_text(separator="\n", strip=True)
        else:
            body = soup.find("body")
            text = body.get_text(separator="\n", strip=True) if body else soup.get_text(separator="\n", strip=True)

        # 清理
        text = re.sub(r"\n{3,}", "\n\n", text)
        text = re.sub(r"[ \t]{3,}", "  ", text)
        return text.strip()

    @staticmethod
    def _get_oldest_year(articles):
        """获取一批文章中最旧的年份"""
        years = []
        for a in articles:
            date_str = a.get("date_str", "")
            match = re.search(r"(\d{4})", str(date_str))
            if match:
                years.append(int(match.group(1)))
        return min(years) if years else None

    @staticmethod
    def _has_lxml():
        try:
            import lxml
            return True
        except ImportError:
            return False


# ============================================================
# 第十一部分: 主控爬虫
# ============================================================

class ConsiliumCrawler:
    """欧盟理事会爬虫主控制器"""

    def __init__(self, mode="sparql"):
        self.config = CrawlerConfig()
        self.mode = mode
        self.throttle = Throttle(self.config)
        self.checkpoint = CheckpointManager(self.config.CHECKPOINT_FILE)
        self.keyword_filter = KeywordFilter(self.config.SEARCH_KEYWORDS)
        self.classifier = DocumentClassifier(self.config)
        self.writer = OutputWriter(self.config)

        # SPARQL 模式组件
        self.sparql = SparqlClient(self.config, self.throttle)
        self.fetcher = TextFetcher(self.config, self.throttle)

        # 浏览器模式组件
        self.browser = BrowserManager(self.config)

        # 统计
        self.stats = {
            "total_found": 0,
            "total_skipped": 0,
            "total_matched": 0,      # 关键词匹配数
            "total_fetched": 0,      # 成功获取全文数
            "total_failed_text": 0,
            "per_year": {},
        }

        self._register_signal_handler()

    def _register_signal_handler(self):
        """注册 Ctrl+C 信号处理器"""
        def handler(sig, frame):
            print(f"\n\n{'='*60}")
            print("[中断] 收到 Ctrl+C，正在保存断点...")
            print(f"[中断] {self.checkpoint.summary()}")
            self.writer.flush_csv()
            print(f"[中断] 可重新运行脚本从断点续爬")
            print(f"{'='*60}")
            if self.browser:
                self.browser.quit()
            sys.exit(0)

        signal.signal(signal.SIGINT, handler)

    def run(self):
        """主入口"""
        self._print_header()
        self.writer.setup_dirs()

        if self.mode in ("sparql", "both"):
            self._run_sparql_mode()

        if self.mode in ("browser", "both"):
            self._run_browser_mode()

        # 最终输出
        print(f"\n{'='*60}")
        print("[完成] 正在输出最终 CSV ...")
        self.writer.flush_csv()
        self._print_summary()

        if self.browser:
            self.browser.quit()

    def _print_header(self):
        print("=" * 60)
        print("  欧盟理事会 (consilium.europa.eu) 英文语料爬虫")
        print("  用途: 欧盟对华话语政策语料库建设")
        print("=" * 60)
        print(f"  运行模式: {self.mode}")
        print(f"  关键词数量: {len(self.config.SEARCH_KEYWORDS)}")
        print(f"  年份范围: {self.config.YEAR_START}–{self.config.YEAR_END}")
        print(f"  输出路径: {self.config.OUTPUT_ROOT}")
        print(f"  请求间隔: {self.config.DELAY_MIN}–{self.config.DELAY_MAX}s")
        print(f"  {self.checkpoint.summary()}")
        print("=" * 60)

    # === SPARQL 模式 ===

    def _run_sparql_mode(self):
        """SPARQL 模式: 通过 EUR-Lex 查询 Council 相关文档"""
        print(f"\n{'#'*60}")
        print("# SPARQL 模式: 查询 EUR-Lex 数据库中的欧盟理事会相关文档")
        print(f"{'#'*60}")

        for year in range(self.config.YEAR_START, self.config.YEAR_END + 1):
            self._process_year_sparql(year)

    def _process_year_sparql(self, year):
        """SPARQL 模式: 处理单一年份"""
        docs = self.sparql.query_year(year)
        self.stats["total_found"] += len(docs)

        if not docs:
            print(f"  [跳过] 年份 {year} 无匹配文档")
            return

        self.stats["per_year"][year] = {
            "total": len(docs), "new": 0, "skipped": 0,
            "matched": 0, "fetched": 0, "failed": 0,
        }

        for idx, meta in enumerate(docs, 1):
            celex_id = meta["celex"]
            status_bar = f"[{idx}/{len(docs)}]"
            print(f"\n{status_bar} Year {year} | CELEX: {celex_id}")
            print(f"    标题: {meta['title'][:100]}")

            # 断点检查
            if self.checkpoint.is_completed(celex_id):
                print(f"    [跳过] 已完成")
                self.stats["total_skipped"] += 1
                self.stats["per_year"][year]["skipped"] += 1
                continue

            # 关键词匹配
            if not self.keyword_filter.matches(meta["title"], ""):
                # 不确定是否有词匹配，先获取全文再判断
                pass

            # 反爬延迟
            self.throttle.wait(label=f"CELEX {celex_id}")

            # 获取全文
            print(f"    [获取全文] ...", end=" ", flush=True)
            full_text, success = self.fetcher.fetch(celex_id)

            if success:
                print(f"OK ({len(full_text)} 字符)")
                self.stats["per_year"][year]["fetched"] += 1
                self.stats["total_fetched"] += 1
            else:
                print(f"FAIL ({full_text[:50]})")
                self.stats["per_year"][year]["failed"] += 1
                self.stats["total_failed_text"] += 1

            # 关键词过滤（基于标题 + 全文）
            if not self.keyword_filter.matches(meta["title"], full_text):
                print(f"    [过滤] 不包含目标关键词，跳过")
                continue

            self.stats["total_matched"] += 1
            self.stats["per_year"][year]["matched"] += 1

            # 自动分类
            classification = self.classifier.classify(meta["title"], full_text, meta)
            print(f"    [分类] 年份={classification['year']} | "
                  f"主题={classification['topic_zh']} | "
                  f"机构={classification['institution_zh']} | "
                  f"类型={classification['doc_type_zh']}")

            # 构建原文链接
            original_url = (
                f"https://eur-lex.europa.eu/legal-content/EN/TXT/HTML/"
                f"?uri=CELEX:{celex_id}"
            )

            # 写入 TXT
            self.writer.write_txt(celex_id, meta["title"], meta["date"],
                                 classification, full_text, original_url)

            # 追加 CSV 行
            self.writer.append_csv_row(celex_id, meta["title"], meta["date"],
                                       classification, full_text, original_url)

            # 更新断点
            self.checkpoint.mark_completed(celex_id)
            self.stats["per_year"][year]["new"] += 1

            print(f"    [进度] 总完成 {self.checkpoint.total_completed} | "
                  f"本年新增 {self.stats['per_year'][year]['new']}")

        ystat = self.stats["per_year"][year]
        print(f"\n--- Year {year} 小结: "
              f"共 {ystat['total']}, 新增 {ystat['new']}, "
              f"跳过 {ystat['skipped']}, 匹配 {ystat['matched']}, "
              f"成功 {ystat['fetched']}, 失败 {ystat['failed']} ---")

    # === 浏览器模式 ===

    def _run_browser_mode(self):
        """浏览器模式: 直接从 consilium.europa.eu 爬取"""
        print(f"\n{'#'*60}")
        print("# 浏览器模式: 直接爬取 consilium.europa.eu")
        print(f"{'#'*60}")

        if self.browser.page is None:
            print("[错误] 浏览器启动失败，跳过浏览器模式")
            print("[提示] 请确保已安装 DrissionPage: pip install DrissionPage")
            return

        crawler = CouncilPageCrawler(
            self.config, self.browser, self.keyword_filter, self.classifier
        )

        for list_config in self.config.COUNCIL_LIST_URLS:
            articles = crawler.crawl_list_pages(list_config)
            self._process_articles_browser(articles, list_config, crawler)

    def _process_articles_browser(self, articles, list_config, crawler):
        """处理浏览器模式下获取的文章列表"""
        doc_type_default = list_config["doc_type_default"]
        institution_default = list_config["institution_default"]

        for idx, article in enumerate(articles, 1):
            url = article["url"]
            status_bar = f"[{idx}/{len(articles)}]"
            print(f"\n{status_bar} {list_config['label']} | {url[:80]}")

            # 断点检查
            if self.checkpoint.is_completed(url):
                print(f"    [跳过] 已完成")
                self.stats["total_skipped"] += 1
                continue

            # 反爬延迟
            self.throttle.wait(label="press release")

            # 获取详情页全文
            full_text, success = crawler.fetch_article_detail(article)
            if success:
                print(f"    [全文] OK ({len(full_text)} 字符)")
            else:
                print(f"    [全文] FAIL")
                continue

            # 关键词过滤
            if not self.keyword_filter.matches(article["title"], full_text):
                print(f"    [过滤] 不包含目标关键词，跳过")
                continue

            # 分类
            meta = {
                "date": article.get("date_str", ""),
                "default_institution": institution_default,
                "default_type": doc_type_default,
            }
            classification = self.classifier.classify(article["title"], full_text, meta)
            print(f"    [分类] 年份={classification['year']} | "
                  f"主题={classification['topic_zh']} | "
                  f"机构={classification['institution_zh']} | "
                  f"类型={classification['doc_type_zh']}")

            # 写入 TXT
            doc_id = re.sub(r'[\\/:*?"<>|]', '_', url)[:80]
            self.writer.write_txt(doc_id, article["title"], article.get("date_str", ""),
                                 classification, full_text, url)

            # 追加 CSV
            self.writer.append_csv_row(doc_id, article["title"],
                                       article.get("date_str", ""),
                                       classification, full_text, url)

            # 更新断点
            self.checkpoint.mark_completed(url)
            self.stats["total_fetched"] += 1
            self.stats["total_matched"] += 1

            # 定期刷新 CSV
            if self.checkpoint.total_completed % 50 == 0:
                print(f"    [CSV] 定期刷新 ({self.checkpoint.total_completed} 条)")
                self.writer.flush_csv()

    def _print_summary(self):
        """打印最终汇总"""
        print(f"\n{'='*60}")
        print("  爬取汇总")
        print("=" * 60)
        print(f"  SPARQL 检索总数: {self.stats['total_found']}")
        print(f"  断点跳过数:       {self.stats['total_skipped']}")
        print(f"  关键词匹配数:     {self.stats['total_matched']}")
        print(f"  全文获取成功:     {self.stats['total_fetched']}")
        print(f"  全文获取失败:     {self.stats['total_failed_text']}")
        print(f"  最终完成总数:     {self.checkpoint.total_completed}")
        print()
        if self.stats["per_year"]:
            print("  各年度统计:")
            for year in sorted(self.stats["per_year"].keys()):
                y = self.stats["per_year"][year]
                print(f"    {year}: 共 {y.get('total',0)} | 新增 {y.get('new',0)} | "
                      f"跳过 {y.get('skipped',0)} | 匹配 {y.get('matched',0)} | "
                      f"成功 {y.get('fetched',0)} | 失败 {y.get('failed',0)}")
        print(f"\n  TXT 目录: {self.config.TXT_DIR}")
        print(f"  CSV 文件: {self.config.CSV_FILE}")
        print(f"  断点文件: {self.config.CHECKPOINT_FILE}")
        print("=" * 60)


# ============================================================
# 入口
# ============================================================

if __name__ == "__main__":
    # 解析命令行参数
    parser = argparse.ArgumentParser(
        description="欧盟理事会 (consilium.europa.eu) 英文语料爬虫",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
示例:
  python consilium_crawler.py                      # 默认 SPARQL 模式
  python consilium_crawler.py --mode sparql        # 仅 EUR-Lex SPARQL (推荐，无需浏览器)
  python consilium_crawler.py --mode browser       # 仅浏览器模式
  python consilium_crawler.py --mode both          # 两种模式都运行
  python consilium_crawler.py --resume             # 从断点续爬
        """
    )
    parser.add_argument(
        "--mode", choices=["sparql", "browser", "both"],
        default="sparql",
        help="爬取模式: sparql (EUR-Lex API), browser (consilium 直接爬取), both (两者都运行)"
    )
    parser.add_argument(
        "--resume", action="store_true",
        help="从断点续爬（自动加载 checkpoint.json）"
    )
    args = parser.parse_args()

    # 依赖检查
    print("依赖检查:")
    deps_ok = True

    try:
        import requests as _r
        print(f"  OK requests {_r.__version__}")
    except ImportError:
        print("  MISS requests → 请运行: pip install requests")
        deps_ok = False

    try:
        import bs4 as _b
        print(f"  OK beautifulsoup4 {_b.__version__}")
    except ImportError:
        print("  MISS beautifulsoup4 → 请运行: pip install beautifulsoup4")
        deps_ok = False

    try:
        import pandas as _p
        print(f"  OK pandas {_p.__version__}")
    except ImportError:
        print("  MISS pandas → 请运行: pip install pandas")
        deps_ok = False

    try:
        import lxml
        print(f"  OK lxml (快速 HTML 解析器)")
    except ImportError:
        print("  INFO lxml 未安装 (将使用标准解析器) → pip install lxml")

    if args.mode in ("browser", "both"):
        try:
            from DrissionPage import ChromiumPage
            print(f"  OK DrissionPage (浏览器自动化)")
        except ImportError:
            print("  MISS DrissionPage → 请运行: pip install DrissionPage")
            deps_ok = False

    if not deps_ok:
        print("\n请安装缺失的依赖后重新运行。")
        sys.exit(1)

    print()

    # 启动爬虫
    crawler = ConsiliumCrawler(mode=args.mode)
    crawler.run()
