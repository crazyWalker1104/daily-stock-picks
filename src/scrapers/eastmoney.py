"""东方财富爬虫 — 研报中心、板块资金流向、龙虎榜"""

import logging
from typing import List

from src.models import NewsItem
from src.scrapers.base import BaseScraper

logger = logging.getLogger(__name__)


class EastmoneyScraper(BaseScraper):
    """东方财富 — A股数据最全的免费来源"""

    source_name = "东方财富"

    # 研报列表API
    REPORT_API = "https://reportapi.eastmoney.com/report/list"

    # 板块资金流向API
    FUND_FLOW_API = "https://push2.eastmoney.com/api/qt/clist/get"

    # 龙虎榜API
    LHB_API = "https://push2.eastmoney.com/api/qt/clist/get"

    def _fetch_reports(self, page_size: int = 30) -> list:
        """获取最新研报"""
        params = {
            "cb": "",
            "pageSize": page_size,
            "pageNo": 1,
            "beginTime": "",
            "endTime": "",
            "qType": "0",
            "industryCode": "",
            "rating": "",
            "fields": "",
        }
        try:
            resp = self.session.get(
                self.REPORT_API,
                params=params,
                headers=self._get_headers(),
                timeout=self.timeout
            )
            resp.raise_for_status()
            data = resp.json()
            return data.get("data", [])
        except Exception as e:
            logger.warning(f"[东方财富] 研报API失败: {e}")
            return []

    def _fetch_sector_flow(self) -> list:
        """获取行业板块资金流向（今日）"""
        params = {
            "pn": "1",
            "pz": "50",
            "po": "1",  # 按净流入排序
            "np": "1",
            "ut": "bd1d9ddb04089700cf9c27f6f7426281",
            "fltt": "2",
            "invt": "2",
            "fid": "f62",  # 主力净流入
            "fs": "m:90+t2",  # 行业板块
            "fields": "f12,f14,f2,f3,f62,f184,f66,f69,f72,f75,f78,f81,f84,f87",
        }
        try:
            resp = self.session.get(
                self.FUND_FLOW_API,
                params=params,
                headers=self._get_headers(),
                timeout=self.timeout
            )
            resp.raise_for_status()
            data = resp.json()
            if data and isinstance(data, dict):
                return data.get("data", {}).get("diff", []) or []
            return []
        except Exception as e:
            logger.debug(f"[东方财富] 资金流向API失败: {e}")
            return []

    def _fetch_concept_flow(self) -> list:
        """获取概念板块资金流向"""
        params = {
            "pn": "1",
            "pz": "30",
            "po": "1",
            "np": "1",
            "ut": "bd1d9ddb04089700cf9c27f6f7426281",
            "fltt": "2",
            "invt": "2",
            "fid": "f62",
            "fs": "m:90+t3",  # 概念板块
            "fields": "f12,f14,f2,f3,f62,f184,f66",
        }
        try:
            resp = self.session.get(
                self.FUND_FLOW_API,
                params=params,
                headers=self._get_headers(),
                timeout=self.timeout
            )
            resp.raise_for_status()
            data = resp.json()
            if data and isinstance(data, dict):
                return data.get("data", {}).get("diff", []) or []
            return []
        except Exception as e:
            logger.debug(f"[东方财富] 概念资金API失败: {e}")
            return []

    def _parse_report(self, item: dict) -> NewsItem:
        """解析研报为NewsItem"""
        title = item.get("title", "")
        org_name = item.get("orgName", "")  # 机构名称
        stock_name = item.get("stockName", "")
        industry = item.get("industryName", "")
        rate = item.get("rate", "")  # 评级
        info_code = item.get("infoCode", "")

        content = f"[{org_name}] 对 {stock_name} 评级：{rate}"
        url = f"https://data.eastmoney.com/report/zw_industry.jshtml?infocode={info_code}" if info_code else ""

        tags = [industry] if industry else []
        if rate:
            tags.append(rate)

        return NewsItem(
            title=title[:100],
            content=content[:300],
            source="eastmoney",
            url=url,
            category=industry,
            tags=tags,
        )

    def scrape(self) -> List[NewsItem]:
        """采集东方财富研报+资金流向"""
        all_items = []

        # 1. 券商研报
        reports = self._fetch_reports(30)
        for item in reports:
            try:
                parsed = self._parse_report(item)
                if parsed.title:
                    all_items.append(parsed)
            except Exception as e:
                logger.debug(f"[东方财富] 解析研报失败: {e}")

        # 2. 行业板块资金流向（top10 流入 + top5 流出）
        sector_flows = self._fetch_sector_flow()
        top_inflow = sector_flows[:10] if sector_flows else []
        top_outflow = sector_flows[-5:] if len(sector_flows) > 5 else []

        for item in top_inflow:
            sector_name = item.get("f14", "")
            net_inflow = item.get("f62", 0)  # 主力净流入（元）
            if sector_name and net_inflow:
                amount = abs(float(net_inflow)) / 1e8  # 转换为亿
                all_items.append(NewsItem(
                    title=f"资金流入：{sector_name}板块 主力净流入{amount:.2f}亿",
                    content=f"{sector_name}行业板块今日主力资金净流入{amount:.2f}亿元，"
                             f"板块涨跌幅{item.get('f3', '--')}%",
                    source="eastmoney",
                    url="https://data.eastmoney.com/bkzj/hy.html",
                    category=sector_name,
                    tags=["资金流入", sector_name],
                ))

        for item in top_outflow:
            sector_name = item.get("f14", "")
            net_inflow = item.get("f62", 0)
            if sector_name and net_inflow:
                amount = abs(float(net_inflow)) / 1e8
                all_items.append(NewsItem(
                    title=f"资金流出：{sector_name}板块 主力净流出{amount:.2f}亿",
                    content=f"{sector_name}行业板块今日主力资金净流出{amount:.2f}亿元",
                    source="eastmoney",
                    url="https://data.eastmoney.com/bkzj/hy.html",
                    category=sector_name,
                    tags=["资金流出", sector_name],
                ))

        # 3. 概念板块资金流向（top5 流入）
        concept_flows = self._fetch_concept_flow()
        for item in concept_flows[:5]:
            concept_name = item.get("f14", "")
            net_inflow = item.get("f62", 0)
            if concept_name and float(net_inflow) > 0:
                amount = abs(float(net_inflow)) / 1e8
                all_items.append(NewsItem(
                    title=f"概念活跃：{concept_name} 资金净流入{amount:.2f}亿",
                    content=f"{concept_name}概念板块主力资金净流入{amount:.2f}亿元",
                    source="eastmoney",
                    url="https://data.eastmoney.com/bkzj/gn.html",
                    category=concept_name,
                    tags=["概念板块", concept_name, "资金流入"],
                ))

        return all_items
