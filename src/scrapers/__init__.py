"""爬虫注册中心 — 可插拔信息源管理"""

import logging
from typing import List, Dict

from src.models import NewsItem
from src.scrapers.base import BaseScraper
from src.scrapers.cls import CLSScraper
from src.scrapers.eastmoney import EastmoneyScraper
from src.scrapers.sina import SinaScraper
from src.scrapers.xueqiu import XueqiuScraper

logger = logging.getLogger(__name__)

# 信息源注册表：新增源只需在此添加一行
# 格式："key": ScraperClass()
SCRAPER_REGISTRY: Dict[str, BaseScraper] = {
    "cls": CLSScraper(),
    "eastmoney": EastmoneyScraper(),
    "sina": SinaScraper(),
    "xueqiu": XueqiuScraper(),
    # 付费源预留接口：
    # "wind": WindScraper(),       # 万得 — 需API Key
    # "choice": ChoiceScraper(),   # Choice — 需订阅
}


def get_enabled_scrapers(config: dict) -> Dict[str, BaseScraper]:
    """根据配置返回启用的爬虫列表"""
    enabled = {}
    source_config = config.get("sources", {})

    for key, scraper in SCRAPER_REGISTRY.items():
        if source_config.get(key, False):
            scraper.config = config
            enabled[key] = scraper

    return enabled


def collect_all_news(config: dict) -> List[NewsItem]:
    """运行所有启用的爬虫，汇总新闻"""
    scrapers = get_enabled_scrapers(config)
    all_news = []

    for key, scraper in scrapers.items():
        try:
            items = scraper.run()
            all_news.extend(items)
        except Exception as e:
            logger.error(f"爬虫 [{key}] 执行异常: {e}")

    logger.info(f"采集完成：共 {len(all_news)} 条新闻，来自 {len(scrapers)} 个信息源")
    return all_news
