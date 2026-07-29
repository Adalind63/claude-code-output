"""
POLIANNA-style dual-tier keyword configuration for EU-China trade policy corpus.
Reference: POLIANNA Dataset methodology (PMC, 2026)
"""

# ============================================================================
# TIER 1: General EU Industrial & Trade Policy Keywords
# Purpose: Broad filter for EU industry, international trade, global supply chain
# ============================================================================
TIER1_GENERAL = [
    # International Trade (core)
    "international trade", "trade policy", "trade agreement", "trade relation",
    "free trade agreement", "FTA", "trade negotiation", "trade dialogue",
    "trade cooperation", "trade partnership", "bilateral trade",
    "trade and investment", "trade and technology council", "TTC",
    "WTO", "world trade organization",

    # Global Supply Chain
    "supply chain", "global supply chain", "global value chain",
    "supply chain resilience", "supply chain diversification",
    "supply chain security", "critical supply", "supply chain due diligence",
    "strategic dependency", "trade dependency",

    # Trade Defence / Level Playing Field
    "level playing field", "trade defence", "trade defense",
    "unfair trade", "trade barrier", "market distortion",
    "foreign subsidy", "dumping", "anti-dumping",
    "trade distorting", "trade remedy",

    # Market Access & Reciprocity
    "market access", "reciprocity", "reciprocal",
    "regulatory cooperation", "regulatory dialogue",

    # Investment & Security
    "investment screening", "foreign investment review",
    "screening mechanism", "export control", "economic security",

    # EU Trade Strategy
    "trade strategy", "trade for all", "trade policy review",
    "de-risking", "derisking",
]

# ============================================================================
# TIER 2: Sector-Specific Industry Keywords
# Purpose: Fine-grained industry sector classification
# ============================================================================
TIER2_SECTOR = {
    "semiconductor": [
        "semiconductor", "chip", "microchip", "microelectronics",
        "processor", "advanced chip", "chip manufacturing",
        "semiconductor supply", "semiconductor ecosystem",
        "fab", "foundry", "wafer", "integrated circuit",
        "advanced semiconductor", "leading-edge chip",
    ],

    "new_energy": [
        "renewable energy", "solar panel", "solar cell", "solar module",
        "photovoltaic", "wind turbine", "wind energy",
        "battery", "electric vehicle", "new energy vehicle",
        "lithium battery", "energy storage", "hydrogen",
        "clean energy", "clean tech", "green technology",
        "electrolyser", "electrolyzer", "rare earth",
        "permanent magnet", "critical mineral",
        "biofuel", "sustainable aviation fuel",
    ],

    "steel": [
        "steel", "steel industry", "steel production", "steel sector",
        "steel overcapacity", "steel import", "steel export",
        "aluminium", "aluminum", "aluminium industry",
        "metal industry", "ferrous", "non-ferrous",
        "steel safeguard", "steel tariff",
    ],

    "market_access": [
        "market access", "market openness", "access to market",
        "public procurement", "government procurement",
        "investment access", "market barrier",
        "reciprocity", "reciprocal access",
        "licensing regime", "forced technology transfer",
        "technology transfer", "localization requirement",
        "joint venture requirement",
    ],

    "digital_trade": [
        "digital trade", "digital economy", "digital service",
        "cross-border data flow", "data flow", "data localisation",
        "data localization", "data governance", "data sovereignty",
        "digital sovereignty", "e-commerce", "electronic commerce",
        "artificial intelligence", "AI regulation", "AI governance",
        "telecom", "telecommunication",
        "cybersecurity", "network security", "cloud computing",
        "digital platform", "platform regulation",
        "Digital Services Act", "Digital Markets Act",
    ],

    "subsidy_investigation": [
        "anti-subsidy", "countervailing duty",
        "subsidy investigation", "subsidy probe",
        "state aid", "state subsidy", "government subsidy",
        "foreign subsidy regulation",
        "foreign subsidies instrument",
        "distortive subsidy", "subsidy notification",
        "WTO subsidy", "SCM agreement",
    ],

    "tariffs": [
        "tariff", "tariff rate", "tariff quota",
        "anti-dumping duty", "dumping investigation",
        "safeguard measure", "safeguard investigation",
        "trade remedy", "trade defence instrument",
        "MFN tariff", "bound tariff", "applied tariff",
        "import duty", "customs duty", "additional duty",
        "provisional duty", "definitive duty",
    ],

    "investment_review": [
        "foreign direct investment", "FDI screening",
        "investment screening", "investment review",
        "foreign investment", "inward investment",
        "strategic asset", "critical infrastructure",
        "critical technology", "dual-use",
        "export control", "export restriction",
        "investment restriction", "capital control",
    ],

    "intellectual_property": [
        "intellectual property", "intellectual property right",
        "patent", "trademark", "copyright",
        "trade secret", "IP enforcement", "IP protection",
        "counterfeit", "piracy", "IP theft",
        "standard essential patent",
        "geographical indication",
        "technology leakage", "know-how protection",
    ],
}

# Flattened Tier2 for quick matching
TIER2_FLAT = []
for _category, _terms in TIER2_SECTOR.items():
    TIER2_FLAT.extend(_terms)

# ============================================================================
# CHINA OVERLAY Keywords
# Purpose: Double-filter to ensure documents are China-related
# ============================================================================
CHINA_OVERLAY = [
    # Direct China references (removed short acronyms: BRI/CCP/PRC — too many false positives)
    "China", "Chinese", "People's Republic of China",
    "Beijing", "Chinese Communist Party",

    # China-specific policy instruments (full forms only, no acronyms)
    "Belt and Road", "Belt & Road",
    "Made in China 2025", "China 2025",
    "China Standards 2035",

    # China trade-specific terms
    "China-specific", "China-related",
    "EU-China", "China-EU", "Sino-European", "Sino-EU",

    # China-linked entities / frameworks
    "Chinese SOE", "Chinese state-owned",
    "Chinese company", "Chinese firm", "Chinese enterprise",
    "Chinese manufacturer", "Chinese exporter", "Chinese producer",
    "Chinese investor", "Chinese investment",
    "from China", "with China", "on China", "in China",
    "China's", "Chinese government",
]

# ============================================================================
# AUTO-CLASSIFICATION MAPS
# ============================================================================

# Topic classification based on Tier2 keyword matching
TOPIC_CATEGORIES = {
    "semiconductor": "半导体",
    "new_energy": "新能源",
    "steel": "钢铁",
    "market_access": "市场准入",
    "digital_trade": "数字贸易",
    "subsidy_investigation": "补贴调查",
    "tariffs": "关税",
    "investment_review": "投资审查",
    "intellectual_property": "知识产权",
}

# Institution name patterns → classification
INSTITUTION_MAP = [
    (["European Commission", "European Commission", "Commission",
      "DG GROW", "DG TRADE", "DG COMP", "Directorate-General",
      "EC"], "欧委会"),
    (["European Parliament", "Parliament", "MEP",
      "EP"], "欧洲议会"),
    (["Council of the European Union", "Council of the EU",
      "EU Council", "the Council"], "欧盟理事会"),
    (["DG TRADE", "Directorate-General for Trade",
      "Trade"], "贸易总司(DG TRADE)"),
    (["EEAS", "European External Action Service",
      "External Action"], "欧洲对外行动署(EEAS)"),
]

# Document type patterns → classification
DOC_TYPE_MAP = [
    (["Regulation", "Regulation (EU)", "Commission Regulation",
      "Council Regulation", "Implementing Regulation",
      "Delegated Regulation"], "条例"),
    (["Report", "Annual Report", "Progress Report",
      "Monitoring Report", "Implementation Report",
      "Evaluation Report", "Staff Working Document",
      "SWD"], "报告"),
    (["Statement", "Joint Statement", "Press Statement",
      "Declaration", "Press Release", "Speech",
      "Remarks", "communication"], "声明"),
    (["White Paper", "White paper"], "白皮书"),
    (["Resolution", "European Parliament Resolution",
      "Legislative Resolution"], "决议"),
    (["Communication", "Joint Communication",
      "Commission Communication"], "通讯"),
    (["Directive", "Directive (EU)"], "指令"),
    (["Decision", "Commission Decision", "Council Decision",
      "Implementing Decision"], "决定"),
    (["Recommendation", "Commission Recommendation"], "建议"),
    (["Opinion", "Commission Opinion"], "意见"),
    (["Proposal", "Legislative Proposal", "Commission Proposal"], "提案"),
    (["Notice", "Commission Notice"], "通告"),
    (["Green Paper", "Green paper"], "绿皮书"),
    (["Working Document", "Working Paper", "Discussion Paper",
      "Briefing", "Policy Paper", "Inception Impact Assessment",
      "Impact Assessment"], "工作文件"),
]

# ============================================================================
# KNOWN EU INSTITUTION NAMES (for metadata extraction)
# ============================================================================
EU_INSTITUTIONS = [
    "European Commission",
    "European Parliament",
    "Council of the European Union",
    "Council of the EU",
    "European Council",
    "Directorate-General for Internal Market, Industry, Entrepreneurship and SMEs",
    "Directorate-General for Trade",
    "Directorate-General for Competition",
    "Directorate-General for Communications Networks, Content and Technology",
    "Directorate-General for Defence Industry and Space",
    "Directorate-General for Taxation and Customs Union",
    "Directorate-General for Financial Stability, Financial Services and Capital Markets Union",
    "European External Action Service",
    "European Economic and Social Committee",
    "European Committee of the Regions",
    "European Anti-Fraud Office",
    "European Investment Bank",
    "High Representative of the Union for Foreign Affairs and Security Policy",
]

# Short names mapping for display
INSTITUTION_SHORT = {
    "Directorate-General for Internal Market, Industry, Entrepreneurship and SMEs": "DG GROW",
    "Directorate-General for Trade": "DG TRADE",
    "Directorate-General for Competition": "DG COMP",
    "Directorate-General for Communications Networks, Content and Technology": "DG CNECT",
    "Directorate-General for Defence Industry and Space": "DG DEFIS",
    "Directorate-General for Taxation and Customs Union": "DG TAXUD",
    "European External Action Service": "EEAS",
}
