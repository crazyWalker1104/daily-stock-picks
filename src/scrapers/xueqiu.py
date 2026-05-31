"""雪球爬虫 — 热门讨论、个股热帖"""

import logging
from typing import List

from src.models import NewsItem
from src.scrapers.base import BaseScraper

logger = logging.getLogger(__name__)


class XueqiuScraper(BaseScraper):
    """雪球 — 投资者社区，反映市场情绪"""

    source_name = "雪球"

    # 热门帖子API
    HOT_POSTS_API = "https://xueqiu.com/statuses/hot/listV2.json"

    # 热门股票API
    HOT_STOCKS_API = "https://stock.xueqiu.com/v5/stock/hot_stock/list.json"

    def _init_session(self):
        """雪球需要先访问首页获取cookie"""
        try:
            self.session.get(
                "https://xueqiu.com",
                headers=self._get_headers(),
                timeout=self.timeout
            )
        except Exception:
            pass  # 即使首页失败也尝试后续请求

    def _fetch_hot_posts(self, page: int = 1, size: int = 20) -> list:
        """获取热门帖子"""
        params = {
            "page": page,
            "size": size,
            "type": "12",  # 热门
        }
        try:
            resp = self.session.get(
                self.HOT_POSTS_API,
                params=params,
                headers={
                    **self._get_headers(),
                    "Referer": "https://xueqiu.com",
                    "X-Requested-With": "XMLHttpRequest",
                },
                timeout=self.timeout
            )
            resp.raise_for_status()
            data = resp.json()
            return data.get("list", [])
        except Exception as e:
            logger.warning(f"[雪球] 热帖API失败: {e}")
            return []

    def _fetch_hot_stocks(self, size: int = 20) -> list:
        """获取热门关注股票"""
        params = {
            "size": size,
            "_type": "12",
            "type": "12",
        }
        try:
            resp = self.session.get(
                self.HOT_STOCKS_API,
                params=params,
                headers={
                    **self._get_headers(),
                    "Referer": "https://xueqiu.com",
                    "X-Requested-With": "XMLHttpRequest",
                },
                timeout=self.timeout
            )
            resp.raise_for_status()
            data = resp.json()
            return data.get("data", {}).get("items", [])
        except Exception as e:
            logger.warning(f"[雪球] 热门股票API失败: {e}")
            return []

    def _parse_post(self, item: dict) -> NewsItem:
        """解析雪球帖子为NewsItem"""
        title = item.get("title", "") or item.get("text", "")[:80]
        content = item.get("text", "") or item.get("description", "")
        target = item.get("target", "")  # 帖子链接
        stocks = item.get("stocks", [])  # 关联股票

        tags = []
        for stock in stocks:
            stock_name = stock.get("name", "")
            if stock_name:
                tags.append(stock_name)

        # 从HTML内容提取纯文本
        from bs4 import BeautifulSoup
        if content:
            soup = BeautifulSoup(content, "html.parser")
            content = soup.get_text()[:400]

        url = f"https://xueqiu.com{target}" if target else ""

        return NewsItem(
            title=f"[雪球热议] {title[:80]}",
            content=content[:400],
            source="xueqiu",
            url=url,
            tags=tags[:5],
        )

    def scrape(self) -> List[NewsItem]:
        """采集雪球热门讨论"""
        all_items = []

        # 初始化session（获取cookie）
        self._init_session()

        # 1. 热门帖子
        posts = self._fetch_hot_posts(1, 15)
        for item in posts:
            try:
                parsed = self._parse_post(item)
                if parsed.title:
                    all_items.append(parsed)
            except Exception as e:
                logger.debug(f"[雪球] 解析帖子失败: {e}")

        # 2. 热门股票
        try:
            hot_stocks = self._fetch_hot_stocks(15)
            stock_names = []
            for item in hot_stocks:
                name = item.get("name", "") or item.get("stock_name", "")
                code = item.get("code", "") or item.get("symbol", "")
                if name:
                    stock_names.append(f"{name}({code})")

            if stock_names:
                all_items.append(NewsItem(
                    title=f"雪球热股榜：{', '.join(stock_names[:10])}",
                    content=f"今日雪球社区关注度最高的股票：{', '.join(stock_names[:15])}",
                    source="xueqiu",
                    url="https://xueqiu.com/hq",
                    tags=["热门关注"] + stock_names[:5],
                ))
        except Exception as e:
            logger.debug(f"[雪球] 解析热门股票失败: {e}")

        return all_items
