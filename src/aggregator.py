"""信息聚合器 — 去重、排序、分类、截断"""

import hashlib
import logging
from datetime import datetime
from typing import List

from src.models import NewsItem

logger = logging.getLogger(__name__)

# 关注的关键词（A股热点板块/题材）
KEYWORDS = [
    # 科技
    "半导体", "芯片", "AI", "人工智能", "算力", "光模块", "CPO", "机器人",
    "自动驾驶", "低空经济", "卫星", "6G", "量子",
    # 新能源
    "光伏", "储能", "锂电", "固态电池", "新能源车", "充电桩", "氢能",
    # 消费
    "白酒", "食品", "旅游", "免税", "医美",
    # 医药
    "创新药", "CXO", "中药", "医疗器械", "减肥药",
    # 金融地产
    "券商", "银行", "保险", "房地产",
    # 周期
    "煤炭", "有色", "稀土", "黄金", "石油", "化工",
    # 政策
    "国企改革", "中特估", "一带一路", "化债",
    # 其他热点
    "北向资金", "ETF", "回购", "分红",
]


def deduplicate(news_list: List[NewsItem]) -> List[NewsItem]:
    """基于标题哈希去重，保留首次出现的来源"""
    seen = set()
    unique = []
    for item in news_list:
        # 用标题前50字符做哈希（同一新闻不同源标题可能略有差异）
        h = hashlib.md5(item.title[:50].encode()).hexdigest()
        if h not in seen:
            seen.add(h)
            unique.append(item)
    logger.info(f"去重：{len(news_list)} → {len(unique)} 条")
    return unique


def score_relevance(news: NewsItem) -> int:
    """根据关键词匹配度和来源权威性打分"""
    text = news.title + news.content + " ".join(news.tags)
    score = 0

    # 关键词命中加分
    for kw in KEYWORDS:
        if kw in text:
            score += 10

    # 来源权威性加权
    source_weight = {
        "eastmoney": 5,   # 东方财富（研报）权威性高
        "cls": 3,         # 财联社（快讯）
        "sina": 2,        # 新浪（综合）
        "xueqiu": 1,      # 雪球（社区，噪音多）
    }
    score += source_weight.get(news.source, 1)

    # 有时间戳的优先
    if news.timestamp and news.timestamp > datetime.now().isoformat()[:10]:
        score += 3

    return score


def rank_and_filter(news_list: List[NewsItem], top_n: int = 40) -> List[NewsItem]:
    """按相关性排序，保留topN送入AI分析"""
    scored = [(news, score_relevance(news)) for news in news_list]
    scored.sort(key=lambda x: x[1], reverse=True)

    top = [item for item, _ in scored[:top_n]]
    logger.info(f"排序过滤：保留前 {len(top)} 条送入AI分析")
    return top


def format_for_ai(news_list: List[NewsItem]) -> str:
    """将新闻列表格式化为AI可读的文本"""
    lines = []
    for i, news in enumerate(news_list, 1):
        lines.append(
            f"[{i}] 【{news.source}】{news.title}\n"
            f"    摘要：{news.content[:200]}\n"
            f"    标签：{', '.join(news.tags) if news.tags else '无'}\n"
            f"    链接：{news.url}"
        )
    return "\n\n".join(lines)


def aggregate(news_list: List[NewsItem], max_for_ai: int = 40) -> str:
    """聚合入口：去重 → 排序 → 格式化为AI Prompt"""
    unique = deduplicate(news_list)
    ranked = rank_and_filter(unique, top_n=max_for_ai)
    return format_for_ai(ranked)
