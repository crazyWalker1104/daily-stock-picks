"""次日推荐追踪模块 — 自动对比昨日推荐 vs 今日行情，建立反馈闭环"""

import json
import logging
import os
from datetime import datetime, timedelta
from typing import Dict, List, Optional

import requests

from src.models import DailyReport

logger = logging.getLogger(__name__)

# ── 东方财富个股实时行情API ─────────────────────────────────────

STOCK_QUOTE_API = "https://push2.eastmoney.com/api/qt/ulist.np/get"


def _get_headers() -> dict:
    return {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
        "Referer": "https://quote.eastmoney.com/",
    }


def _code_to_secid(code: str) -> str:
    """6位A股代码 → 东方财富 secid 格式

    - 6xxxxx → 1.6xxxxx (上海)
    - 0xxxxx/3xxxxx → 0.0xxxxx/0.3xxxxx (深圳)
    - 688xxx → 1.688xxx (上海科创板)
    """
    if code.startswith("6"):
        return f"1.{code}"
    else:
        return f"0.{code}"


def load_previous_report(date: str, output_dir: str = "output") -> Optional[dict]:
    """加载上一交易日的推荐报告

    Args:
        date: 当前日期 YYYY-MM-DD
        output_dir: 报告输出目录

    Returns:
        上日报告 dict，不存在则返回 None
    """
    try:
        # 计算前一天日期
        today = datetime.strptime(date, "%Y-%m-%d")
        yesterday = today - timedelta(days=1)
        prev_date = yesterday.strftime("%Y-%m-%d")

        # 查找前一日报告文件
        report_path = os.path.join(output_dir, f"{prev_date}_report.json")
        if not os.path.exists(report_path):
            logger.info(f"未找到昨日报告 ({report_path})，跳过追踪")
            return None

        with open(report_path, "r", encoding="utf-8") as f:
            report = json.load(f)
        logger.info(f"加载昨日报告: {prev_date}，包含 {len(report.get('recommendations', []))} 条推荐")
        return report
    except Exception as e:
        logger.warning(f"加载昨日报告失败: {e}")
        return None


def _extract_stock_codes(report: dict) -> List[dict]:
    """从报告中提取所有推荐标的及其上下文

    Returns:
        [{"code": "300394", "name": "天孚通信", "sector": "AI算力", "confidence": "高"}, ...]
    """
    stocks = []
    for rec in report.get("recommendations", []):
        for s in rec.get("stocks", []):
            stocks.append({
                "code": s.get("code", ""),
                "name": s.get("name", ""),
                "sector": rec.get("sector", ""),
                "confidence": rec.get("confidence", ""),
            })
    return stocks


def fetch_stock_quotes(codes: List[str]) -> Dict[str, dict]:
    """批量获取个股实时行情

    Args:
        codes: 6位代码列表 ["300394", "600160", ...]

    Returns:
        {"300394": {"name": "...", "price": ..., "change_pct": ...}, ...}
    """
    if not codes:
        return {}

    try:
        secids = ["," for code in codes]  # 逗号分隔的 secid 列表
        secids_str = ",".join([_code_to_secid(c) for c in codes])
        params = {
            "fltt": "2",
            "fields": "f2,f3,f4,f12,f14",  # 最新价,涨跌幅,涨跌额,代码,名称
            "secids": secids_str,
            "invt": "2",
        }
        resp = requests.get(STOCK_QUOTE_API, params=params, headers=_get_headers(), timeout=10)
        resp.raise_for_status()
        data = resp.json()
        items = data.get("data", {}).get("diff", []) or []

        result = {}
        for item in items:
            code = item.get("f12", "")
            result[code] = {
                "name": item.get("f14", ""),
                "price": item.get("f2", 0),
                "change_pct": item.get("f3", 0),  # 涨跌幅 %
                "change_amt": item.get("f4", 0),  # 涨跌额
            }
        logger.info(f"个股行情获取: {len(result)}/{len(codes)} 只")
        return result
    except Exception as e:
        logger.warning(f"个股行情获取失败: {e}")
        return {}


def track_yesterday(current_date: str, output_dir: str = "output") -> Optional[dict]:
    """追踪昨日推荐今日表现

    Args:
        current_date: 当前日期
        output_dir: 报告目录

    Returns:
        {
            "prev_date": "2026-05-30",
            "stocks": [
                {"code": "...", "name": "...", "sector": "...",
                 "confidence": "高", "change_pct": 2.3, "hit": True},
                ...
            ],
            "hit_count": 3,
            "miss_count": 2,
            "hit_rate": 0.6,
            "avg_return": 0.85,
        }
        无昨日报告或获取失败返回 None
    """
    # 加载昨日报告
    prev_report = load_previous_report(current_date, output_dir)
    if not prev_report:
        return None

    prev_date = prev_report.get("date", "")
    stocks = _extract_stock_codes(prev_report)
    if not stocks:
        logger.info("昨日推荐无标的，跳过追踪")
        return None

    # 获取今日行情
    codes = [s["code"] for s in stocks]
    quotes = fetch_stock_quotes(codes)

    # 合并数据
    tracked = []
    hit_count = 0
    miss_count = 0
    total_return = 0

    for s in stocks:
        code = s["code"]
        quote = quotes.get(code, {})
        change_pct = quote.get("change_pct", None)
        price = quote.get("price", None)

        is_hit = change_pct is not None and change_pct > 0
        if is_hit:
            hit_count += 1
        elif change_pct is not None and change_pct <= 0:
            miss_count += 1

        if change_pct is not None:
            total_return += change_pct

        tracked.append({
            "code": code,
            "name": s["name"],
            "sector": s["sector"],
            "confidence": s["confidence"],
            "price": price,
            "change_pct": change_pct,
            "hit": is_hit,
        })

    total = hit_count + miss_count
    hit_rate = hit_count / total if total > 0 else 0
    avg_return = total_return / total if total > 0 else 0

    result = {
        "prev_date": prev_date,
        "stocks": tracked,
        "hit_count": hit_count,
        "miss_count": miss_count,
        "total_count": total,
        "hit_rate": round(hit_rate, 2),
        "avg_return": round(avg_return, 2),
    }
    logger.info(
        f"昨日推荐追踪: {hit_count}涨/{miss_count}跌/{len(stocks)-total}无数据 → "
        f"胜率{hit_rate:.0%} 均收益{avg_return:+.2f}%"
    )
    return result


def format_tracking_section(tracking: Optional[dict]) -> str:
    """将追踪数据格式化为报告追加段落（Markdown，紧凑表格式）"""
    if not tracking or not tracking.get("stocks"):
        return ""

    lines = []
    lines.append("---")
    lines.append("")
    lines.append(f"## 📊 昨日推荐回顾 ({tracking['prev_date']})")
    lines.append("")

    # 汇总一行
    if tracking["total_count"] > 0:
        lines.append(
            f"**胜率 {tracking['hit_rate']:.0%}** · "
            f"均收益 **{tracking['avg_return']:+.2f}%** · "
            f"{tracking['hit_count']}涨 / {tracking['miss_count']}跌"
        )
        lines.append("")

    # 表格式明细
    lines.append("| | 标的 | 板块 | 信心 | 今日 |")
    lines.append("|:---:|:---|:---|:---:|---:|")
    for s in tracking["stocks"]:
        emoji = "✅" if s.get("hit") else ("❌" if s.get("change_pct") is not None else "➖")
        perf = f"{s['change_pct']:+.2f}%" if s.get("change_pct") is not None else "—"
        lines.append(
            f"| {emoji} | **{s['name']}**({s['code']}) "
            f"| {s['sector']} | {s['confidence']} | {perf} |"
        )

    if tracking["total_count"] == 0:
        lines.append("> ⚠️ 昨日推荐标的今日无行情数据（可能休市或数据延迟）")

    lines.append("")
    return "\n".join(lines)


def format_tracking_plain(tracking: Optional[dict]) -> str:
    """追踪数据的纯文本版本（CLI用，紧凑格式）"""
    if not tracking or not tracking.get("stocks"):
        return ""

    lines = []
    lines.append(f"📊 昨日推荐回顾 ({tracking['prev_date']})")
    if tracking["total_count"] > 0:
        lines.append(
            f"   胜率 {tracking['hit_rate']:.0%} | "
            f"均收益 {tracking['avg_return']:+.2f}% | "
            f"{tracking['hit_count']}涨/{tracking['miss_count']}跌"
        )
    lines.append("")
    for s in tracking["stocks"]:
        emoji = "+" if s.get("hit") else ("-" if s.get("change_pct") is not None else "?")
        perf = f"{s['change_pct']:+.2f}%" if s.get("change_pct") is not None else "—"
        lines.append(f"   {emoji} {s['name']:<6s} {s['code']}  {s['sector']:<12s} → {perf}")
    if tracking["total_count"] == 0:
        lines.append("   (今日暂无行情数据)")
    lines.append("")
    return "\n".join(lines)
