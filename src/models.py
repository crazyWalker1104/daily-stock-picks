"""数据模型定义"""

from dataclasses import dataclass, field, asdict
from datetime import datetime
from typing import Optional


@dataclass
class NewsItem:
    """统一的新���数据模型"""
    title: str
    content: str
    source: str          # 来源标识：cls, eastmoney, xueqiu, sina
    url: str
    category: str = ""   # 板块/题材标签
    timestamp: str = field(default_factory=lambda: datetime.now().isoformat())
    tags: list = field(default_factory=list)

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class Recommendation:
    """AI生成的推荐条目"""
    sector: str           # 板块名称
    confidence: str       # 高/中/低
    logic: str            # 推荐逻辑
    stocks: list          # 推荐标的列表 [{"name": "xxx", "code": "xxxxxx"}]
    catalyst: str         # 核心催化事件
    risk: str             # 主要风险
    source: list          # 引用的信息源URL

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class DailyReport:
    """每日完整报告"""
    date: str
    recommendations: list  # List[Recommendation]
    raw_news_count: int    # 原始采集新闻数
    sources_used: list     # 本次使用的信息源
    tracking: dict = field(default_factory=dict)  # 昨日推荐追踪结果（tracker模块填充）
    confirmation_summary: str = ""  # 双重确认引擎验证摘要（Phase 2.1）
    technical_summary: str = ""     # 技术面过滤摘要（Phase 2.2）
    generated_at: str = field(default_factory=lambda: datetime.now().isoformat())

    def to_dict(self) -> dict:
        return {
            "date": self.date,
            "recommendations": [r.to_dict() for r in self.recommendations],
            "raw_news_count": self.raw_news_count,
            "sources_used": self.sources_used,
            "tracking": self.tracking,
            "confirmation_summary": self.confirmation_summary,
            "technical_summary": self.technical_summary,
            "generated_at": self.generated_at
        }
