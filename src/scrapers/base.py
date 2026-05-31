"""基础爬虫抽象类"""

import time
import random
import logging
from abc import ABC, abstractmethod
from typing import List

import requests
from bs4 import BeautifulSoup

from src.models import NewsItem

logger = logging.getLogger(__name__)

# 常用UA池
USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:126.0) Gecko/20100101 Firefox/126.0",
]


class BaseScraper(ABC):
    """爬虫基类，所有信息源爬虫继承此类"""

    # 子类需覆盖
    source_name: str = "base"

    def __init__(self, config: dict = None):
        self.config = config or {}
        self.delay = self.config.get("scraper", {}).get("request_delay", 2)
        self.timeout = self.config.get("scraper", {}).get("timeout", 15)
        self.max_retries = self.config.get("scraper", {}).get("max_retries", 3)
        self.session = requests.Session()

    def _get_headers(self) -> dict:
        """随机UA + 基础请求头"""
        return {
            "User-Agent": random.choice(USER_AGENTS),
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
            "Accept-Encoding": "gzip, deflate",
            "Connection": "keep-alive",
        }

    def _fetch(self, url: str, params: dict = None) -> str:
        """带重试机制的HTTP请求"""
        for attempt in range(self.max_retries):
            try:
                resp = self.session.get(
                    url,
                    params=params,
                    headers=self._get_headers(),
                    timeout=self.timeout
                )
                resp.raise_for_status()
                resp.encoding = resp.apparent_encoding  # 自动检测编码
                return resp.text
            except requests.RequestException as e:
                logger.warning(f"[{self.source_name}] 请求失败 (尝试 {attempt+1}/{self.max_retries}): {url} - {e}")
                if attempt < self.max_retries - 1:
                    time.sleep(self.delay * (attempt + 1))  # 递增延迟
        return ""

    def _parse_html(self, html: str) -> BeautifulSoup:
        """解析HTML"""
        return BeautifulSoup(html, "lxml")

    def _fetch_json(self, url: str, params: dict = None) -> dict:
        """请求JSON API"""
        for attempt in range(self.max_retries):
            try:
                resp = self.session.get(
                    url,
                    params=params,
                    headers={**self._get_headers(), "Accept": "application/json"},
                    timeout=self.timeout
                )
                resp.raise_for_status()
                return resp.json()
            except Exception as e:
                logger.warning(f"[{self.source_name}] JSON请求失败 (尝试 {attempt+1}): {url} - {e}")
                if attempt < self.max_retries - 1:
                    time.sleep(self.delay * (attempt + 1))
        return {}

    @abstractmethod
    def scrape(self) -> List[NewsItem]:
        """采集新闻，返回统一的NewsItem列表"""
        pass

    def run(self) -> List[NewsItem]:
        """执行采集，带异常保护"""
        try:
            logger.info(f"[{self.source_name}] 开始采集...")
            items = self.scrape()
            logger.info(f"[{self.source_name}] 采集完成，获取 {len(items)} 条")
            return items
        except Exception as e:
            logger.error(f"[{self.source_name}] 采集异常: {e}", exc_info=True)
            return []
