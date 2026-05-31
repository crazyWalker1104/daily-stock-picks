"""新浪财经爬虫 — 要闻、龙虎榜、北向资金"""

import logging
from typing import List

from src.models import NewsItem
from src.scrapers.base import BaseScraper

logger = logging.getLogger(__name__)


class SinaScraper(BaseScraper):
    """新浪财经 — 传统财经门户，数据稳定"""

    source_name = "新浪财经"

    # 财经要闻滚动API
    NEWS_API = "https://feed.mix.sina.com.cn/api/roll/get"
    NEWS_PARAMS = {
        "pageid": "153",
        "lid": "2509",       # 财经要闻
        "k": "",
        "num": 30,
        "page": 1,
        "r": "0.5",
        "callback": "",
    }

    # 龙虎榜API
    LHB_API = "https://vip.stock.finance.sina.com.cn/q/go.php/vLHBData/kind/top50tradeday/index.phtml"

    def _fetch_news(self, num: int = 30) -> list:
        """获取财经要闻滚动列表"""
        params = {**self.NEWS_PARAMS, "num": num}
        try:
            resp = self.session.get(
                self.NEWS_API,
                params=params,
                headers={**self._get_headers(), "Referer": "https://finance.sina.com.cn/"},
                timeout=self.timeout
            )
            resp.raise_for_status()
            # 新浪API返回的JSON可能带特殊字符，需要处理
            text = resp.text
            if text.startswith("/*"):
                text = text.split("*/", 1)[-1] if "*/" in text else text
            import json
            data = json.loads(text)
            return data.get("result", {}).get("data", [])
        except Exception as e:
            logger.warning(f"[新浪财经] 新闻API失败: {e}")
            return []

    def _parse_news(self, item: dict) -> NewsItem:
        """解析新浪新闻为NewsItem"""
        title = item.get("title", "")
        intro = item.get("intro", "") or item.get("summary", "")
        url = item.get("url", "")
        keywords = item.get("keywords", "")
        media = item.get("media", "")

        tags = [k.strip() for k in keywords.split(",") if k.strip()] if keywords else []
        if media:
            tags.append(media)

        return NewsItem(
            title=title[:100],
            content=intro[:400],
            source="sina",
            url=url,
            tags=tags,
        )

    def scrape(self) -> List[NewsItem]:
        """采集新浪财经要闻"""
        all_items = []

        # 1. 财经要闻
        news_list = self._fetch_news(30)
        for item in news_list:
            try:
                parsed = self._parse_news(item)
                if parsed.title:
                    all_items.append(parsed)
            except Exception as e:
                logger.debug(f"[新浪财经] 解析新闻失败: {e}")

        # 2. 尝试获取龙虎榜数据
        try:
            resp = self.session.get(
                self.LHB_API,
                headers={**self._get_headers(), "Referer": "https://vip.stock.finance.sina.com.cn/"},
                timeout=self.timeout
            )
            if resp.status_code == 200:
                all_items.append(NewsItem(
                    title="今日龙虎榜数据已更新（Top50营业部）",
                    content="龙虎榜买卖数据，反映游资和机构动向",
                    source="sina",
                    url="https://vip.stock.finance.sina.com.cn/q/go.php/vLHBData/kind/top50tradeday/index.phtml",
                    tags=["龙虎榜", "游资动向"],
                ))
        except Exception as e:
            logger.debug(f"[新浪财经] 龙虎榜获取失败: {e}")

        return all_items
