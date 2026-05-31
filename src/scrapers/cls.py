"""财联社爬虫 — 24h电报、快讯、题材挖掘"""

import logging
from typing import List

from src.models import NewsItem
from src.scrapers.base import BaseScraper

logger = logging.getLogger(__name__)


class CLSScraper(BaseScraper):
    """财联社 — 最快的财经快讯来源"""

    source_name = "财联社"

    # 多个备选API（财联社接口经常变动）
    API_OPTIONS = [
        # 方案1: 新版电报列表接口
        {
            "url": "https://www.cls.cn/nodeapi/telegraphList",
            "method": "GET",
            "params": {
                "app": "CailianpressWeb",
                "os": "web",
                "sv": "8.4.6",
                "category": "all",
                "rn": 50,
            },
            "data_key": ["data", "roll_data"],
        },
        # 方案2: v3 电报接口
        {
            "url": "https://www.cls.cn/nodeapi/updateTelegraphList",
            "method": "GET",
            "params": {
                "app": "CailianpressWeb",
                "os": "web",
                "sv": "8.4.6",
                "rn": 50,
            },
            "data_key": ["data", "roll_data"],
        },
    ]

    # 深度文章API
    DEPTH_API = "https://www.cls.cn/v3/depth/home/assembled/1000"

    def _fetch_telegraphs(self, rn: int = 50) -> list:
        """尝试多个API获取电报列表"""
        for option in self.API_OPTIONS:
            try:
                if option["method"] == "GET":
                    resp = self.session.get(
                        option["url"],
                        params=option.get("params", {}),
                        headers={**self._get_headers(), "Referer": "https://www.cls.cn/telegraph"},
                        timeout=self.timeout
                    )
                else:
                    resp = self.session.post(
                        option["url"],
                        json=option.get("params", {}),
                        headers={**self._get_headers(), "Content-Type": "application/json"},
                        timeout=self.timeout
                    )
                resp.raise_for_status()
                data = resp.json()

                # 按 data_key 路径提取数据
                items = data
                for key in option["data_key"]:
                    items = items.get(key, {}) if isinstance(items, dict) else []
                if isinstance(items, list) and items:
                    logger.info(f"[财联社] 使用 {option['url']} 获取 {len(items)} 条电报")
                    return items
            except Exception as e:
                logger.debug(f"[财联社] API尝试失败 ({option['url']}): {e}")
                continue

        # 所有API都失败，尝试直接解析电报首页HTML
        return self._fallback_html_parse()

    def _fallback_html_parse(self) -> list:
        """兜底方案：解析财联社电报首页HTML"""
        try:
            resp = self.session.get(
                "https://www.cls.cn/telegraph",
                headers=self._get_headers(),
                timeout=self.timeout
            )
            resp.raise_for_status()
            soup = self._parse_html(resp.text)
            items = []
            # 查找电报列表项
            for item_el in soup.select(".telegraph-list .telegraph-item, .telegraph-content-box")[:50]:
                title_el = item_el.select_one(".telegraph-title, .title")
                content_el = item_el.select_one(".telegraph-content, .content")
                link_el = item_el.select_one("a[href]")

                title = title_el.get_text(strip=True) if title_el else ""
                content = content_el.get_text(strip=True) if content_el else ""
                href = link_el.get("href", "") if link_el else ""

                if title:
                    url = f"https://www.cls.cn{href}" if href and href.startswith("/") else href
                    items.append({"title": title, "content": content, "id": href, "url": url})

            logger.info(f"[财联社] HTML兜底解析获取 {len(items)} 条电报")
            return items
        except Exception as e:
            logger.warning(f"[财联社] HTML兜底解析也失败: {e}")
            return []

    def _fetch_depth_articles(self) -> list:
        """获取深度报道/题材挖掘"""
        try:
            resp = self.session.get(
                self.DEPTH_API,
                headers={**self._get_headers(), "Referer": "https://www.cls.cn/depth"},
                timeout=self.timeout
            )
            resp.raise_for_status()
            data = resp.json()
            # v3 API结构: data -> 可能有多种嵌套
            if isinstance(data, dict):
                items = data.get("data", data)
                if isinstance(items, dict):
                    items = items.get("list", items.get("roll_data", []))
                if isinstance(items, list):
                    return items
        except Exception as e:
            logger.debug(f"[财联社] 深度文章API失败: {e}")
        return []

    def _parse_telegraph(self, item: dict) -> NewsItem:
        """解析单条电报为NewsItem"""
        title = item.get("title", "") or item.get("brief", "")
        content = item.get("content", "") or item.get("brief", "") or item.get("description", "")
        article_id = item.get("id", "") or item.get("article_id", "")

        # 提取题材标签，兼容多种字段名
        subjects = item.get("subjects", []) or item.get("tags", [])
        tags = []
        if isinstance(subjects, list):
            for s in subjects:
                if isinstance(s, dict):
                    tags.append(s.get("subject_name", s.get("name", "")))
                elif isinstance(s, str):
                    tags.append(s)

        # 兼容直接带url字段的情况
        url = item.get("url", "")
        if not url and article_id:
            url = f"https://www.cls.cn/detail/{article_id}"

        return NewsItem(
            title=title[:100],
            content=content[:500],
            source="cls",
            url=url,
            tags=tags,
        )

    def scrape(self) -> List[NewsItem]:
        """采集财联社电报和深度文章"""
        all_items = []

        # 1. 电报快讯
        telegraphs = self._fetch_telegraphs(50)
        for item in telegraphs:
            try:
                parsed = self._parse_telegraph(item)
                if parsed.title:
                    all_items.append(parsed)
            except Exception as e:
                logger.debug(f"[财联社] 解析电报失败: {e}")

        # 2. 深度报道
        depths = self._fetch_depth_articles()
        for item in depths:
            try:
                parsed = self._parse_telegraph(item)
                if parsed.title:
                    parsed.tags.append("深度报道")
                    all_items.append(parsed)
            except Exception as e:
                logger.debug(f"[财联社] 解析深度文章失败: {e}")

        return all_items
