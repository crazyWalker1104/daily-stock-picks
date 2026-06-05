"""信息聚合器 — 多因子评分：关键词+情绪+来源+资金共振+跨源确认+质量

Phase 2.3 重构：从纯关键词匹配升级为多因子加权评分。
每个新闻条目从 6 个维度打分（满分 100），优选出高信号质量的新闻送入 AI 分析。

因子权重设计：
  1. 关键词相关性 (0-25) — 是否覆盖A股当前热点题材（三层分级）
  2. 情绪信号强度 (0-15) — 利多/利空信号的密集程度，越强越可交易
  3. 来源权威性   (0-15) — 研报 > 快讯 > 综合 > 社区
  4. 资金面共振   (0-20) — 是否匹配今日主力资金净流入板块
  5. 跨源确认     (0-15) — 同一事件被多个不同来源报道，可信度更高
  6. 内容质量     (0-10) — 内容长度、标签、URL、时效性

与 Phase 2.1/2.2 的关系：
  - 聚合器在 AI 分析之前运行，决定哪些新闻进入 AI 视野
  - 确认引擎和技术面过滤在 AI 推荐之后运行，验证推荐质量
  - 聚合器的 sentiment/market 因子是确认引擎的轻量前置版本
"""

import hashlib
import logging
from typing import Dict, List, Optional, Set

from src.models import NewsItem

logger = logging.getLogger(__name__)

# ═══════════════════════════════════════════════════════════════════
# 关键词库（三层分级，取代旧版扁平列表）
# ═══════════════════════════════════════════════════════════════════

# Tier 1 — 当前市场最热题材（权重 5，上限 5 个命中）
HOT_KEYWORDS = [
    "AI", "人工智能", "算力", "光模块", "CPO", "机器人", "自动驾驶",
    "低空经济", "固态电池", "半导体", "芯片",
]

# Tier 2 — 持续性主题（权重 3）
THEME_KEYWORDS = [
    "光伏", "储能", "锂电", "新能源车", "充电桩", "氢能",
    "创新药", "CXO", "中药", "医疗器械", "减肥药",
    "券商", "银行", "保险", "房地产",
    "煤炭", "有色", "稀土", "黄金", "石油", "化工",
    "军工", "电力", "电网", "特高压", "虚拟电厂",
    "白酒", "食品", "旅游", "免税", "医美",
]

# Tier 3 — 政策/制度性主题（权重 2）
POLICY_KEYWORDS = [
    "国企改革", "中特估", "一带一路", "化债",
    "卫星", "6G", "量子", "国产替代",
    "北向资金", "ETF", "回购", "分红",
]

# ── 情绪信号词（与 confirmation.py 共用词典，保持一致性）───────
POSITIVE_SIGNALS = [
    "涨停", "大涨", "拉升", "突破", "新高", "放量",
    "利好", "增持", "买入", "推荐", "看好", "超预期",
    "预增", "扭亏", "反弹", "反转", "加速", "扩产",
    "中标", "获批", "补贴", "政策支持", "国产替代",
]

NEGATIVE_SIGNALS = [
    "跌停", "大跌", "跳水", "跌破", "新低", "缩量",
    "利空", "减持", "卖出", "下调", "警告", "低于预期",
    "预亏", "亏损", "退市", "立案", "处罚", "暴雷",
    "停工", "裁员", "诉讼", "债务违约",
]

# ── 来源权威性（0-15 直接映射）──────────────────────────────────
SOURCE_AUTHORITY = {
    "eastmoney": 15,   # 东方财富研报 — 机构级，最高权威
    "cls": 10,         # 财联社快讯 — 时效性强，中等权威
    "sina": 8,         # 新浪财经 — 综合可靠
    "xueqiu": 4,       # 雪球社区 — 噪音多，低权威
}

# ═══════════════════════════════════════════════════════════════════
# 去重（保留，与旧版一致）
# ═══════════════════════════════════════════════════════════════════


def deduplicate(news_list: List[NewsItem]) -> List[NewsItem]:
    """基于标题前50字符哈希去重，保留首次出现的来源"""
    seen = set()
    unique = []
    for item in news_list:
        h = hashlib.md5(item.title[:50].encode()).hexdigest()
        if h not in seen:
            seen.add(h)
            unique.append(item)
    logger.info(f"去重：{len(news_list)} → {len(unique)} 条")
    return unique


# ═══════════════════════════════════════════════════════════════════
# 多因子评分核心
# ═══════════════════════════════════════════════════════════════════


def _extract_hot_sectors(market_data: Optional[dict]) -> Set[str]:
    """从市场数据中提取今日主力资金净流入板块名称集合

    数据来源：
      - sector_flow.inflow（实时TOP5行业板块）
      - sector_rank_ak.industry.top_inflow（akshare行业TOP10）
      - sector_rank_ak.concept.top_inflow（akshare概念TOP10）

    返回板块名集合，用于判断新闻是否与当前市场热点共振。
    """
    if not market_data:
        return set()

    hot: Set[str] = set()

    # 实时板块资金流
    flow = market_data.get("sector_flow", {})
    for sec in flow.get("inflow", []):
        name = sec.get("name", "")
        if name:
            hot.add(name)

    # akshare 行业 + 概念板块排名
    sector_ak = market_data.get("sector_rank_ak", {})
    for section in ("industry", "concept"):
        for sec in sector_ak.get(section, {}).get("top_inflow", []):
            name = sec.get("name", "")
            if name:
                hot.add(name)

    if hot:
        logger.info(f"热门板块提取: {len(hot)} 个（资金净流入板块）")

    return hot


def _score_keyword_relevance(text: str) -> float:
    """关键词相关性评分 (0-25)

    Tier 1 热门关键词：5分/个，最多计 5 个 → 上限 25
    Tier 2 主题关键词：3分/个
    Tier 3 政策关键词：2分/个
    总分上限 25，防止长文堆砌关键词获得不合理高分。
    """
    score = 0.0

    # Tier 1: 每个 5 分，最多取 5 个
    t1_hits = sum(1 for kw in HOT_KEYWORDS if kw in text)
    score += min(t1_hits, 5) * 5

    # Tier 2: 每个 3 分
    t2_hits = sum(1 for kw in THEME_KEYWORDS if kw in text)
    score += t2_hits * 3

    # Tier 3: 每个 2 分
    t3_hits = sum(1 for kw in POLICY_KEYWORDS if kw in text)
    score += t3_hits * 2

    return min(score, 25.0)


def _score_sentiment_intensity(text: str) -> float:
    """情绪信号强度评分 (0-15)

    利多/利空信号词越密集 → 情绪越强 → 新闻越有交易参考价值。
    不区分方向（利多利空都有交易价值），只衡量强度。

    分级：
      1 个信号 → 4 分（有明确方向）
      2-3 个   → 8 分（情绪明确）
      4-5 个   → 12 分（情绪强烈）
      6+ 个    → 15 分（情绪极度亢奋/恐慌）
    """
    pos = sum(1 for w in POSITIVE_SIGNALS if w in text)
    neg = sum(1 for w in NEGATIVE_SIGNALS if w in text)
    total = pos + neg

    if total >= 6:
        return 15.0
    elif total >= 4:
        return 12.0
    elif total >= 2:
        return 8.0
    elif total >= 1:
        return 4.0
    return 0.0


def _score_source_authority(source: str) -> float:
    """来源权威性评分 (0-15)"""
    return float(SOURCE_AUTHORITY.get(source, 3))


def _score_market_alignment(text: str, hot_sectors: Set[str]) -> float:
    """资金面共振评分 (0-20)

    新闻覆盖今日主力资金流入的板块 → 信息与资金方向一致 → 高参考价值。

    精确匹配（板块名完整出现在文中）：每个 +10，上限 20
    模糊匹配（板块名作为子串）：每个 +6，上限 12
    """
    if not hot_sectors:
        return 0.0

    exact = 0
    fuzzy = 0

    for sector in hot_sectors:
        if len(sector) < 2:
            continue
        if sector in text:
            exact += 1
        elif len(sector) >= 3:
            # 子串匹配：板块名长度≥3才做，避免 "AI" 这类短词误匹配
            for i in range(len(text) - len(sector) + 1):
                if text[i:i + len(sector)] == sector:
                    fuzzy += 1
                    break

    if exact > 0:
        return min(20.0, exact * 10.0)
    elif fuzzy > 0:
        return min(12.0, fuzzy * 6.0)
    return 0.0


def _score_cross_source(news: NewsItem, all_news: List[NewsItem]) -> float:
    """跨源确认评分 (0-15)

    同一事件被多个不同来源报道 → 信息可信度更高。
    使用共享关键词数量判断是否报道同一事件（≥2 个关键词交集）。

    1 个额外来源 → +5
    2 个额外来源 → +10
    3+ 个额外来源 → +15
    """
    text = news.title + news.content
    my_keywords: Set[str] = set()
    for kw in HOT_KEYWORDS + THEME_KEYWORDS + POLICY_KEYWORDS:
        if kw in text:
            my_keywords.add(kw)

    if len(my_keywords) < 2:
        return 0.0  # 关键词太少，无法判断

    other_sources: Set[str] = set()
    for other in all_news:
        if other.source == news.source:
            continue
        if other is news:
            continue

        other_text = other.title + other.content
        common = sum(1 for kw in my_keywords if kw in other_text)
        if common >= 2:
            other_sources.add(other.source)

    n = len(other_sources)
    if n >= 3:
        return 15.0
    elif n >= 2:
        return 10.0
    elif n >= 1:
        return 5.0
    return 0.0


def _score_content_quality(news: NewsItem) -> float:
    """内容质量评分 (0-10)

    维度：
      内容长度 >500 → 4, >200 → 3, >50 → 1（空洞标题无价值）
      有标签     → +2
      有URL      → +2
      有时戳     → +2
    """
    score = 0.0

    clen = len(news.content)
    if clen > 500:
        score += 4
    elif clen > 200:
        score += 3
    elif clen > 50:
        score += 1

    if news.tags:
        score += 2
    if news.url and news.url.startswith("http"):
        score += 2
    if news.timestamp:
        score += 2

    return min(score, 10.0)


def multi_factor_score(
    news: NewsItem,
    all_news: List[NewsItem],
    hot_sectors: Set[str],
) -> dict:
    """多因子综合评分（单条新闻）

    Args:
        news: 待评分新闻
        all_news: 全部新闻列表（用于跨源确认因子）
        hot_sectors: 今日资金流入板块集合

    Returns:
        {"total": 72.5, "factors": {"keyword": 20, "sentiment": 8, ...}}
    """
    text = news.title + news.content

    factors = {
        "keyword": _score_keyword_relevance(text),
        "sentiment": _score_sentiment_intensity(text),
        "source": _score_source_authority(news.source),
        "market": _score_market_alignment(text, hot_sectors),
        "cross_source": _score_cross_source(news, all_news),
        "quality": _score_content_quality(news),
    }

    total = sum(factors.values())

    return {"total": round(total, 1), "factors": factors}


def multi_factor_rank(
    news_list: List[NewsItem],
    top_n: int = 40,
    market_data: Optional[dict] = None,
) -> List[NewsItem]:
    """多因子打分 → 排序 → 截断 topN

    输出评分分布日志，便于监控因子贡献度和调参。
    """
    if not news_list:
        return []

    hot_sectors = _extract_hot_sectors(market_data)

    scored = []
    for news in news_list:
        result = multi_factor_score(news, news_list, hot_sectors)
        scored.append((news, result))

    # 按总分降序
    scored.sort(key=lambda x: x[1]["total"], reverse=True)

    # 评分分布日志
    if scored:
        scores = [s[1]["total"] for s in scored]
        logger.info(
            f"多因子评分: {len(scored)}条 → "
            f"最高{scores[0]:.0f} 均{sum(scores)/len(scores):.0f} "
            f"最低{scores[-1]:.0f} | 截断至 {min(top_n, len(scored))} 条"
        )

        # 各因子均分统计（仅前 top_n）
        top = scored[:top_n]
        factor_sums: Dict[str, float] = {}
        for _, r in top:
            for k, v in r["factors"].items():
                factor_sums[k] = factor_sums.get(k, 0) + v
        n = len(top)
        factor_avg = {k: f"{v/n:.1f}" for k, v in sorted(factor_sums.items())}
        logger.info(f"因子均分: {factor_avg} (n={n})")

    return [item for item, _ in scored[:top_n]]


# ═══════════════════════════════════════════════════════════════════
# AI Prompt 格式化
# ═══════════════════════════════════════════════════════════════════


def format_for_ai(news_list: List[NewsItem]) -> str:
    """将新闻列表格式化为 AI 可读文本"""
    lines = []
    for i, news in enumerate(news_list, 1):
        lines.append(
            f"[{i}] 【{news.source}】{news.title}\n"
            f"    摘要：{news.content[:200]}\n"
            f"    标签：{', '.join(news.tags) if news.tags else '无'}\n"
            f"    链接：{news.url}"
        )
    return "\n\n".join(lines)


# ═══════════════════════════════════════════════════════════════════
# 主入口
# ═══════════════════════════════════════════════════════════════════


def aggregate(
    news_list: List[NewsItem],
    max_for_ai: int = 40,
    market_data: Optional[dict] = None,
) -> str:
    """聚合入口：去重 → 多因子打分 → 排序截断 → 格式化为 AI Prompt

    Args:
        news_list: 原始新闻列表（采集阶段输出）
        max_for_ai: 送入 AI 分析的最大新闻条数
        market_data: 市场数据（来自 collect_market_data()），
                     用于资金面共振因子。None 时该因子自动归零。

    Returns:
        格式化后的新闻文本，可直接注入 AI System Prompt
    """
    unique = deduplicate(news_list)
    ranked = multi_factor_rank(unique, top_n=max_for_ai, market_data=market_data)
    return format_for_ai(ranked)
