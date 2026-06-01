"""市场实况数据模块 — 采集指数/资金流/北向资金，为AI分析提供结构化行情上下文

数据源分层：
  Layer 1 (实时) — 东方财富 push2 API：指数行情、板块资金流（低延迟）
  Layer 2 (增强) — akshare 封装：北向资金、主力资金趋势、板块排名（更全维度）
  Layer 3 (历史) — akshare 历史数据：个股K线、融资融券（后续 Phase）

优雅降级：任一数据源失败不影响其他，无有效数据时返回空字符串不注入 Prompt
"""

import logging
import time
from datetime import datetime
from typing import Dict, List, Optional

import pandas as pd
import requests

logger = logging.getLogger(__name__)

# ── akshare 懒加载 ─────────────────────────────────────────────────
_ak = None


def _get_ak():
    """懒加载 akshare（避免未安装时阻塞整个模块）"""
    global _ak
    if _ak is None:
        try:
            import akshare as ak
            _ak = ak
        except ImportError:
            logger.warning("akshare 未安装，增强行情数据不可用")
            _ak = False
    return _ak if _ak is not False else None

# ── 东方财富实时行情API ──────────────────────────────────────────

INDEX_API = "https://push2.eastmoney.com/api/qt/ulist.np/get"
SECTOR_FLOW_API = "https://push2.eastmoney.com/api/qt/clist/get"
# 北向资金（沪深港通）
NORTH_BOUND_API = "https://push2.eastmoney.com/api/qt/kamt.kline/get"

# 三大指数 secid
INDEX_IDS = [
    "1.000001",   # 上证指数
    "0.399001",   # 深证成指
    "0.399006",   # 创业板指
]

# 大盘统计
MARKET_STAT_API = "https://push2.eastmoney.com/api/qt/ulist.np/get"


def _get_headers() -> dict:
    return {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
        "Referer": "https://data.eastmoney.com/",
    }


def fetch_index_data() -> List[dict]:
    """获取三大指数实时行情

    Returns:
        [{"name": "上证指数", "code": "000001", "price": 3245.12,
          "change_pct": 0.37, "change_amt": 12.05}, ...]
    """
    params = {
        "fltt": "2",
        "fields": "f2,f3,f4,f12,f14",  # 最新价,涨跌幅,涨跌额,代码,名称
        "secids": ",".join(INDEX_IDS),
        "invt": "2",
    }
    try:
        resp = requests.get(INDEX_API, params=params, headers=_get_headers(), timeout=10)
        resp.raise_for_status()
        data = resp.json()
        items = data.get("data", {}).get("diff", []) or []
        result = []
        for item in items:
            result.append({
                "name": item.get("f14", ""),
                "code": item.get("f12", ""),
                "price": item.get("f2", 0),
                "change_pct": item.get("f3", 0),    # 涨跌幅 %
                "change_amt": item.get("f4", 0),    # 涨跌额
            })
        logger.info(f"指数数据获取成功: {len(result)} 条")
        return result
    except Exception as e:
        logger.warning(f"指数数据获取失败: {e}")
        return []


def fetch_sector_flow(top_n: int = 5) -> dict:
    """获取行业板块资金流向TOP流入和流出

    Returns:
        {"inflow": [{name, change_pct, net_inflow_yi}, ...],
         "outflow": [{name, change_pct, net_outflow_yi}, ...]}
    """
    params = {
        "pn": "1",
        "pz": str(top_n * 2),
        "po": "1",       # 按净流入降序
        "np": "1",
        "ut": "bd1d9ddb04089700cf9c27f6f7426281",
        "fltt": "2",
        "invt": "2",
        "fid": "f62",    # 主力净流入
        "fs": "m:90+t2", # 行业板块
        "fields": "f12,f14,f2,f3,f62,f184,f66",
    }
    try:
        resp = requests.get(SECTOR_FLOW_API, params=params, headers=_get_headers(), timeout=10)
        resp.raise_for_status()
        data = resp.json()
        # 兼容 data 为 null 的场景（非交易日/休市）
        inner = data.get("data")
        items = inner.get("diff", []) if inner else []

        inflow, outflow = [], []
        for item in items:
            name = item.get("f14", "")
            change_pct = item.get("f3", 0)         # 板块涨跌幅
            net_flow = float(item.get("f62", 0))    # 主力净流入（元）

            entry = {
                "name": name,
                "change_pct": change_pct,
                "net_flow_yi": round(net_flow / 1e8, 2),  # 转亿
            }

            if net_flow > 0 and len(inflow) < top_n:
                inflow.append(entry)
            elif net_flow < 0 and len(outflow) < top_n:
                entry["net_flow_yi"] = abs(entry["net_flow_yi"])
                outflow.append(entry)

        logger.info(f"板块资金流获取成功: 流入{len(inflow)} 流出{len(outflow)}")
        return {"inflow": inflow, "outflow": outflow}
    except Exception as e:
        logger.warning(f"板块资金流获取失败: {e}")
        return {"inflow": [], "outflow": []}


def fetch_market_stat() -> dict:
    """获取市场统计：上涨/下跌家数、成交额

    Returns:
        {"up_count": 2156, "down_count": 1987, "turnover_yi": 8432}
    """
    # 使用东方财富全市场统计
    params = {
        "fltt": "2",
        "fields": "f2,f3,f4,f12,f14,f15,f16,f17",
        "secids": "1.000001,0.399001",  # 上证+深证（含成交额）
        "invt": "2",
    }
    try:
        resp = requests.get(MARKET_STAT_API, params=params, headers=_get_headers(), timeout=10)
        resp.raise_for_status()
        data = resp.json()
        inner = data.get("data")
        items = inner.get("diff", []) if inner else []

        # 从指数数据中提取成交额
        total_turnover = 0
        for item in items:
            # f6=成交额, f15=最高, f16=最低, f17=开盘
            turnover = float(item.get("f6", 0) or 0)
            total_turnover += turnover

        logger.info(f"市场统计获取成功")
        return {
            "up_count": None,   # 该接口不提供涨跌家数，后续用akshare补充
            "down_count": None,
            "turnover_yi": round(total_turnover / 1e8, 0) if total_turnover > 0 else None,
        }
    except Exception as e:
        logger.warning(f"市场统计获取失败: {e}")
        return {"up_count": None, "down_count": None, "turnover_yi": None}


def fetch_north_bound_flow() -> dict:
    """获取北向资金（沪深港通）当日流向 — 通过 akshare

    优先使用 akshare，失败时回退到东方财富直接 API。

    Returns:
        {"date": "2026-06-01", "hgt_net": +15.3, "sgt_net": +8.2,
         "total_net": +23.5, "status": "休市"|"正常"|None}
    """
    ak = _get_ak()
    if ak:
        try:
            df = ak.stock_hsgt_fund_flow_summary_em()
            # 筛选北向资金（沪股通+深股通）
            north = df[df["资金方向"] == "北向"]
            if north.empty:
                logger.info("北向资金：无数据（可能休市）")
                return {}

            hgt_row = north[north["板块"] == "沪股通"]
            sgt_row = north[north["板块"] == "深股通"]

            hgt_net = float(hgt_row["成交净买额"].iloc[0]) if not hgt_row.empty else 0
            sgt_net = float(sgt_row["成交净买额"].iloc[0]) if not sgt_row.empty else 0
            total_net = round(hgt_net + sgt_net, 2)

            # 检查是否休市（交易状态: 1=正常, 3=休市）
            status_map = {1: "正常", 3: "休市"}
            raw_status = int(north["交易状态"].iloc[0]) if not north.empty else None
            status = status_map.get(raw_status, str(raw_status))

            result = {
                "date": str(north["交易日"].iloc[0]) if not north.empty else "",
                "hgt_net": round(hgt_net, 2),    # 沪股通净买额（亿）
                "sgt_net": round(sgt_net, 2),    # 深股通净买额（亿）
                "total_net": total_net,           # 北向合计净买额（亿）
                "status": status,
            }
            logger.info(f"北向资金获取成功: 合计{total_net:+.2f}亿 ({status})")
            return result
        except Exception as e:
            logger.warning(f"北向资金(akshare)获取失败: {e}，尝试直接API")

    # 回退：东方财富直接API
    try:
        params = {
            "lmt": "0", "klt": "1", "fields1": "f1,f3",
            "fields2": "f51,f52", "ut": "b2884a393a59ad64002292a3e90d46a5",
        }
        resp = requests.get("https://push2.eastmoney.com/api/qt/kamt.kline/get",
                           params=params, headers=_get_headers(), timeout=10)
        resp.raise_for_status()
        data = resp.json()
        klines = (data.get("data") or {}).get("klines", []) or []
        if klines:
            last = klines[-1].split(",")
            total_net = round(float(last[1]) / 1e8, 2) if len(last) > 1 else 0
            logger.info(f"北向资金(直接API)获取成功: 合计{total_net:+.2f}亿")
            return {"date": last[0], "total_net": total_net, "status": None}
    except Exception as e:
        logger.warning(f"北向资金(直接API)也失败: {e}")

    return {}


def fetch_market_flow_trend(days: int = 5) -> dict:
    """获取近期市场主力资金流向趋势 — 通过 akshare

    反映主力资金（超大单+大单）近N日的整体态度变化。

    Returns:
        {"latest_date": "2026-05-30", "trend": [
            {"date": "2026-05-30", "main_net_yi": -33.5, "super_large_net_yi": -15.0},
            ...], "recent_bias": "偏多"|"偏空"|"中性"}
    """
    ak = _get_ak()
    if not ak:
        logger.info("akshare 不可用，跳过主力资金趋势")
        return {}

    try:
        df = ak.stock_market_fund_flow()
        if df.empty:
            return {}

        recent = df.tail(days)
        trend = []
        for _, row in recent.iterrows():
            trend.append({
                "date": str(row["日期"]),
                "main_net_yi": round(float(row["主力净流入-净额"]) / 1e8, 2) if row.get("主力净流入-净额") else 0,
                "super_large_net_yi": round(float(row["超大单净流入-净额"]) / 1e8, 2) if row.get("超大单净流入-净额") else 0,
            })

        # 判断近期主力态度
        recent_total = sum(t["main_net_yi"] for t in trend)
        if recent_total > 50:
            bias = "偏多"
        elif recent_total < -50:
            bias = "偏空"
        else:
            bias = "中性"

        logger.info(f"主力资金趋势获取成功: 近{days}日主力净流入合计{recent_total:+.2f}亿 ({bias})")
        return {
            "latest_date": trend[-1]["date"] if trend else "",
            "trend": trend,
            "recent_bias": bias,
        }
    except Exception as e:
        logger.warning(f"主力资金趋势获取失败: {e}")
        return {}


def fetch_sector_rank_ak(top_n: int = 10) -> dict:
    """获取行业板块资金流排名 — 通过 akshare（补充 Layer1 的直接 API）

    当 Layer1 的直接 API 成功时，此函数作为验证和补充；
    当 Layer1 失败时，此函数作为主要数据源。

    Returns:
        {"industry": {"top_inflow": [...], "top_outflow": [...]},
         "concept": {"top_inflow": [...], "top_outflow": [...]}}
    """
    ak = _get_ak()
    if not ak:
        return {}

    result = {}

    # 行业板块
    try:
        df = ak.stock_sector_fund_flow_rank(indicator="今日", sector_type="行业资金流")
        if not df.empty:
            # 按主力净流入排序
            sorted_df = df.sort_values("今日主力净流入-净额", ascending=False,
                                       key=lambda x: pd.to_numeric(x, errors="coerce"))
            inflow = []
            outflow = []
            for _, row in sorted_df.iterrows():
                name = row.get("名称", "")
                change_pct = float(row.get("今日涨跌幅", 0) or 0)
                net_flow = float(row.get("今日主力净流入-净额", 0) or 0)
                entry = {
                    "name": name,
                    "change_pct": change_pct,
                    "net_flow_yi": round(net_flow / 1e8, 2),
                }
                if net_flow > 0 and len(inflow) < top_n:
                    inflow.append(entry)
                elif net_flow < 0 and len(outflow) < top_n:
                    entry["net_flow_yi"] = abs(entry["net_flow_yi"])
                    outflow.append(entry)
            result["industry"] = {"top_inflow": inflow, "top_outflow": outflow}
    except Exception as e:
        logger.warning(f"行业板块排名(akshare)失败: {e}")

    # 概念板块
    try:
        df = ak.stock_sector_fund_flow_rank(indicator="今日", sector_type="概念资金流")
        if not df.empty:
            sorted_df = df.sort_values("今日主力净流入-净额", ascending=False,
                                       key=lambda x: pd.to_numeric(x, errors="coerce"))
            inflow = []
            outflow = []
            for _, row in sorted_df.iterrows():
                name = row.get("名称", "")
                change_pct = float(row.get("今日涨跌幅", 0) or 0)
                net_flow = float(row.get("今日主力净流入-净额", 0) or 0)
                entry = {
                    "name": name,
                    "change_pct": change_pct,
                    "net_flow_yi": round(net_flow / 1e8, 2),
                }
                if net_flow > 0 and len(inflow) < top_n:
                    inflow.append(entry)
                elif net_flow < 0 and len(outflow) < top_n:
                    entry["net_flow_yi"] = abs(entry["net_flow_yi"])
                    outflow.append(entry)
            result["concept"] = {"top_inflow": inflow, "top_outflow": outflow}
    except Exception as e:
        logger.warning(f"概念板块排名(akshare)失败: {e}")

    if result:
        ind_count = len(result.get("industry", {}).get("top_inflow", [])) + len(result.get("industry", {}).get("top_outflow", []))
        con_count = len(result.get("concept", {}).get("top_inflow", [])) + len(result.get("concept", {}).get("top_outflow", []))
        logger.info(f"板块排名(akshare)获取成功: 行业{ind_count} 概念{con_count}")
    return result


def collect_market_data() -> dict:
    """采集所有市场实况数据（多层数据源融合）

    Returns:
        {"indices": [...], "sector_flow": {...}, "market_stat": {...},
         "north_bound": {...}, "flow_trend": {...}, "sector_rank_ak": {...}}
    """
    logger.info("开始采集市场实况数据...")

    # Layer 1: 东方财富直接API（低延迟）
    indices = fetch_index_data()
    time.sleep(0.3)
    sector_flow = fetch_sector_flow(top_n=5)
    time.sleep(0.3)
    market_stat = fetch_market_stat()
    time.sleep(0.3)

    # Layer 2: akshare 增强数据
    north_bound = fetch_north_bound_flow()
    time.sleep(0.3)
    flow_trend = fetch_market_flow_trend(days=5)
    time.sleep(0.3)
    sector_rank_ak = fetch_sector_rank_ak(top_n=10)

    result = {
        "indices": indices,
        "sector_flow": sector_flow,
        "market_stat": market_stat,
        "north_bound": north_bound,
        "flow_trend": flow_trend,
        "sector_rank_ak": sector_rank_ak,
    }
    logger.info(
        f"市场数据采集完成: 指数{len(indices)} "
        f"板块{len(sector_flow['inflow'])}流入/{len(sector_flow['outflow'])}流出 "
        f"北向{'✓' if north_bound else '✗'} "
        f"趋势{'✓' if flow_trend else '✗'} "
        f"板块排名{'✓' if sector_rank_ak else '✗'}"
    )
    return result


def format_market_overview(data: dict) -> str:
    """将市场数据格式化为AI Prompt可读的结构化文本

    Args:
        data: collect_market_data()的返回结果

    Returns:
        格式化后的文本块，无有效数据时返回空字符串（避免注入空壳提示）
    """
    indices = data.get("indices", [])
    flow = data.get("sector_flow", {})
    stat = data.get("market_stat", {})
    north = data.get("north_bound", {})
    trend = data.get("flow_trend", {})
    sector_ak = data.get("sector_rank_ak", {})

    # 如果没有任何有效数据，返回空字符串
    has_data = (
        bool(indices)
        or bool(flow.get("inflow"))
        or bool(flow.get("outflow"))
        or bool(north)
        or bool(trend)
    )
    if not has_data:
        logger.info("无有效市场数据，跳过注入")
        return ""

    lines = ["## 📈 今日市场实况（实时数据）", ""]

    # ── 指数行情 ──
    if indices:
        lines.append("### 三大指数")
        for idx in indices:
            sign = "+" if (idx.get("change_pct") or 0) >= 0 else ""
            lines.append(
                f"- {idx['name']}（{idx['code']}）：{idx['price']:.2f}  "
                f"{sign}{idx['change_pct']:.2f}%（{sign}{idx['change_amt']:.2f}点）"
            )
        lines.append("")

    # ── 北向资金 ──
    if north:
        total = north.get("total_net", 0)
        direction = "大幅流入" if total > 30 else ("流入" if total > 0 else ("流出" if total < 0 else "持平"))
        abs_total = abs(total)
        sign = "+" if total >= 0 else ""
        lines.append("### 🌏 北向资金（外资动向）")
        lines.append(
            f"- 沪股通：{sign}{north.get('hgt_net', 0):.2f}亿  |  "
            f"深股通：{sign}{north.get('sgt_net', 0):.2f}亿  |  "
            f"**北向合计：{sign}{abs_total:.2f}亿** → {direction}"
        )
        if north.get("status"):
            lines.append(f"- 状态：{north['status']}")
        lines.append("")

    # ── 板块资金流向（实时API） ──
    if flow.get("inflow"):
        lines.append("### 🔥 主力资金净流入 TOP5 板块（实时）")
        for i, sec in enumerate(flow["inflow"], 1):
            lines.append(
                f"{i}. {sec['name']} — 净流入 **{sec['net_flow_yi']:.2f}亿**  "
                f"板块涨跌 {sec['change_pct']:+.2f}%"
            )
        lines.append("")

    if flow.get("outflow"):
        lines.append("### ❄️ 主力资金净流出 TOP5 板块（实时）")
        for i, sec in enumerate(flow["outflow"], 1):
            lines.append(
                f"{i}. {sec['name']} — 净流出 **{sec['net_flow_yi']:.2f}亿**  "
                f"板块涨跌 {sec['change_pct']:+.2f}%"
            )
        lines.append("")

    # ── 近期主力资金趋势（akshare） ──
    if trend and trend.get("trend"):
        lines.append("### 💰 近5日主力资金流向趋势")
        lines.append(f"近期态度：**{trend.get('recent_bias', '?')}**")
        for t in trend["trend"]:
            m = t["main_net_yi"]
            s = t["super_large_net_yi"]
            sign_m = "+" if m >= 0 else ""
            sign_s = "+" if s >= 0 else ""
            lines.append(
                f"- {t['date']}：主力{sign_m}{m:.2f}亿  |  超大单{sign_s}{s:.2f}亿"
            )
        lines.append("")

    # ── 市场统计 ──
    turnover = stat.get("turnover_yi")
    if turnover:
        lines.append(f"### 📊 市场概况")
        lines.append(f"- 两市成交额：约 **{turnover:.0f}亿**")
        up_cnt = stat.get("up_count")
        down_cnt = stat.get("down_count")
        if up_cnt is not None and down_cnt is not None:
            ratio = up_cnt / (up_cnt + down_cnt) * 100 if (up_cnt + down_cnt) > 0 else 0
            lines.append(f"- 上涨 {up_cnt} / 下跌 {down_cnt}（涨跌比 {ratio:.0f}%）")
        lines.append("")

    # ── 概念板块排名（akshare补充） ──
    # 仅在实时API未获取到板块数据时使用
    if not flow.get("inflow") and not flow.get("outflow"):
        concept = sector_ak.get("concept", {})
        if concept.get("top_inflow"):
            lines.append("### 🔥 概念板块主力资金流入TOP5")
            for i, sec in enumerate(concept["top_inflow"][:5], 1):
                lines.append(
                    f"{i}. {sec['name']} — 净流入 **{sec['net_flow_yi']:.2f}亿**  "
                    f"涨跌 {sec['change_pct']:+.2f}%"
                )
            lines.append("")
        if concept.get("top_outflow"):
            lines.append("### ❄️ 概念板块主力资金流出TOP5")
            for i, sec in enumerate(concept["top_outflow"][:5], 1):
                lines.append(
                    f"{i}. {sec['name']} — 净流出 **{sec['net_flow_yi']:.2f}亿**  "
                    f"涨跌 {sec['change_pct']:+.2f}%"
                )
            lines.append("")

    lines.append("> 提示：以上数据为实时行情，请结合新闻内容综合判断。资金大幅流入+利好新闻=高确定性机会。")
    lines.append("")

    return "\n".join(lines)


# ── 快速入口：一句话采集+格式化 ──

def get_market_context() -> str:
    """获取市场上下文文本，失败时返回空字符串（不阻塞管道）"""
    try:
        data = collect_market_data()
        return format_market_overview(data)
    except Exception as e:
        logger.warning(f"市场数据采集完全失败: {e}")
        return ""
