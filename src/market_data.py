"""市场实况数据模块 — 采集指数/资金流/北向资金，为AI分析提供结构化行情上下文"""

import logging
import time
from typing import Dict, List, Optional

import requests

logger = logging.getLogger(__name__)

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


def collect_market_data() -> dict:
    """采集所有市场实况数据

    Returns:
        {"indices": [...], "sector_flow": {...}, "market_stat": {...}}
    """
    logger.info("开始采集市场实况数据...")

    indices = fetch_index_data()
    time.sleep(0.5)  # 避免API限流
    sector_flow = fetch_sector_flow(top_n=5)
    time.sleep(0.5)
    market_stat = fetch_market_stat()

    result = {
        "indices": indices,
        "sector_flow": sector_flow,
        "market_stat": market_stat,
    }
    logger.info(f"市场数据采集完成: 指数{len(indices)} 板块{len(sector_flow['inflow'])}流入/{len(sector_flow['outflow'])}流出")
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

    # 如果没有任何有效数据，返回空字符串
    has_data = bool(indices) or bool(flow.get("inflow")) or bool(flow.get("outflow"))
    if not has_data:
        logger.info("无有效市场数据，跳过注入")
        return ""

    lines = ["## 📈 今日市场实况（实时数据）", ""]

    # ── 指数行情 ──
    indices = data.get("indices", [])
    if indices:
        lines.append("### 三大指数")
        for idx in indices:
            sign = "+" if (idx.get("change_pct") or 0) >= 0 else ""
            lines.append(
                f"- {idx['name']}（{idx['code']}）：{idx['price']:.2f}  "
                f"{sign}{idx['change_pct']:.2f}%（{sign}{idx['change_amt']:.2f}点）"
            )
        lines.append("")

    # ── 资金流向 ──
    flow = data.get("sector_flow", {})
    if flow.get("inflow"):
        lines.append("### 🔥 主力资金净流入 TOP5 板块")
        for i, sec in enumerate(flow["inflow"], 1):
            lines.append(
                f"{i}. {sec['name']} — 净流入 **{sec['net_flow_yi']:.2f}亿**  "
                f"板块涨跌 {sec['change_pct']:+.2f}%"
            )
        lines.append("")

    if flow.get("outflow"):
        lines.append("### ❄️ 主力资金净流出 TOP5 板块")
        for i, sec in enumerate(flow["outflow"], 1):
            lines.append(
                f"{i}. {sec['name']} — 净流出 **{sec['net_flow_yi']:.2f}亿**  "
                f"板块涨跌 {sec['change_pct']:+.2f}%"
            )
        lines.append("")

    # ── 市场统计 ──
    stat = data.get("market_stat", {})
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
