"""技术面过滤引擎 — 实时行情+技术指标验证AI推荐标的

Phase 2.2 核心模块。AI 推荐后处理：用东方财富push2实时行情数据对每条推荐的标的
进行技术面校验，过滤超买/低流动性/极端波动标的，并据技术评分调整信心度。

数据依赖：
  - 东方财富 push2 API：实时行情（16字段批量获取）
  - akshare（可选）：K线数据用于 MA/量能异常/连涨检测

基础过滤（无需K线）：ST检查、涨停接近度、换手率、流通市值
增强过滤（需K线）：MA位置、量能异常、连续上涨天数
"""

import logging
import time
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Tuple

import requests

from src.models import Recommendation

logger = logging.getLogger(__name__)

# ── API 端点 ─────────────────────────────────────────────────────

STOCK_QUOTE_API = "https://push2.eastmoney.com/api/qt/ulist.np/get"

# 扩展字段：覆盖价格/涨跌/量能/市值/估值等16项
QUOTE_FIELDS = "f2,f3,f4,f5,f6,f7,f8,f9,f12,f14,f15,f16,f17,f18,f20,f21"
# f2=最新价, f3=涨跌幅%, f4=涨跌额, f5=成交量(手), f6=成交额(元)
# f7=振幅%, f8=换手率%, f9=市盈率(动态), f12=代码, f14=名称
# f15=最高价, f16=最低价, f17=开盘价, f18=昨收价
# f20=总市值(元), f21=流通市值(元)

# ── 默认配置 ─────────────────────────────────────────────────────

DEFAULT_CONFIG = {
    "enabled": True,
    "min_turnover_rate": 0.5,         # 最低换手率%
    "small_cap_threshold_yi": 20,     # 小盘股流通市值阈值(亿)
    "micro_cap_threshold_yi": 5,      # 微盘股流通市值阈值(亿)
    "limit_up_threshold": 9.5,        # 主板接近涨停线%
    "limit_up_threshold_gem": 19.5,   # 创业板/科创板接近涨停线%
    "consecutive_rise_warning": 3,    # 连续上涨N天 → 警告
    "consecutive_rise_exclude": 5,    # 连续上涨N天 → 排除
    "volume_surge_ratio": 2.0,        # 相对5日均量放大倍数 → 放量标记
    "volume_shrink_ratio": 0.3,       # 相对5日均量缩小比例 → 缩量标记
    "use_akshare_enhancement": True,  # 是否使用akshare K线增强
    "kline_days": 30,                 # K线获取天数(够算MA20)
}

# ── 工具函数 ─────────────────────────────────────────────────────


def _get_headers() -> dict:
    return {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
        "Referer": "https://quote.eastmoney.com/",
    }


def _code_to_secid(code: str) -> str:
    """6位A股代码 → 东方财富 secid

    - 6xxxxx → 1.6xxxxx (上海主板)
    - 688xxx → 1.688xxx (上海科创板)
    - 0xxxxx/3xxxxx → 0.xxxxxx (深圳)
    """
    if code.startswith("6"):
        return f"1.{code}"
    else:
        return f"0.{code}"


# ── 引擎核心 ─────────────────────────────────────────────────────


class TechnicalFilterEngine:
    """技术面过滤器：用实时行情+K线数据标记/排除AI推荐标的"""

    def __init__(self, config: dict = None):
        self.config = {**DEFAULT_CONFIG, **(config or {})}
        self.quotes: Dict[str, dict] = {}
        self.kline_data: Dict[str, list] = {}
        self._ak = None
        self._stats = {
            "total": 0, "passed": 0, "warned": 0, "excluded": 0,
        }

    # ── 懒加载 akshare ─────────────────────────────────────────

    def _get_ak(self):
        """懒加载 akshare（跟随 market_data.py 模式）"""
        if self._ak is not None:
            return self._ak
        try:
            import akshare as ak
            self._ak = ak
            return ak
        except ImportError:
            logger.debug("akshare 未安装，跳过K线增强分析")
            self._ak = False
            return None

    # ── 数据获取 ───────────────────────────────────────────────

    def fetch_quotes(self, codes: List[str]) -> Dict[str, dict]:
        """批量获取个股扩展行情（16字段）

        使用东方财富 push2 API，一次请求获取所有标的。
        trust_env=False 绕过系统代理（国内站点直连）。
        """
        if not codes:
            return {}

        try:
            session = requests.Session()
            session.trust_env = False
            secids_str = ",".join([_code_to_secid(c) for c in codes])
            params = {
                "fltt": "2",
                "fields": QUOTE_FIELDS,
                "secids": secids_str,
                "invt": "2",
            }
            resp = session.get(
                STOCK_QUOTE_API, params=params,
                headers=_get_headers(), timeout=10
            )
            resp.raise_for_status()
            data = resp.json()
            items = data.get("data", {}).get("diff", []) or []

            result = {}
            for item in items:
                code = item.get("f12", "")
                result[code] = {
                    "name": item.get("f14", ""),
                    "price": item.get("f2", 0) or 0,
                    "change_pct": item.get("f3", 0) or 0,
                    "change_amt": item.get("f4", 0) or 0,
                    "volume": item.get("f5", 0) or 0,
                    "turnover_amt": item.get("f6", 0) or 0,
                    "amplitude": item.get("f7", 0) or 0,
                    "turnover_rate": item.get("f8", 0) or 0,
                    "pe": item.get("f9", 0) or 0,
                    "high": item.get("f15", 0) or 0,
                    "low": item.get("f16", 0) or 0,
                    "open": item.get("f17", 0) or 0,
                    "prev_close": item.get("f18", 0) or 0,
                    "total_cap": item.get("f20", 0) or 0,
                    "circulating_cap": item.get("f21", 0) or 0,
                }
            logger.info(f"技术面行情获取: {len(result)}/{len(codes)} 只")
            return result
        except Exception as e:
            logger.warning(f"技术面行情获取失败: {e}")
            return {}

    def fetch_kline(self, codes: List[str]) -> Dict[str, list]:
        """批量获取个股日K线（akshare，支持前复权）

        用于计算均线、量能对比、连续涨跌。失败时优雅降级，
        不影响基础过滤功能。
        """
        ak = self._get_ak()
        if not ak or not self.config.get("use_akshare_enhancement"):
            return {}

        days = self.config.get("kline_days", 30)
        end_date = datetime.now().strftime("%Y%m%d")
        start_date = (datetime.now() - timedelta(days=days + 10)).strftime("%Y%m%d")

        result = {}
        for i, code in enumerate(codes):
            try:
                df = ak.stock_zh_a_hist(
                    symbol=code, period="daily",
                    start_date=start_date, end_date=end_date,
                    adjust="qfq"
                )
                if df is not None and not df.empty and len(df) >= 5:
                    bars = []
                    for _, row in df.tail(days).iterrows():
                        bars.append({
                            "date": str(row["日期"]),
                            "open": float(row["开盘"]),
                            "high": float(row["最高"]),
                            "low": float(row["最低"]),
                            "close": float(row["收盘"]),
                            "volume": float(row["成交量"]),
                        })
                    result[code] = bars
                if i < len(codes) - 1:
                    time.sleep(0.3)  # 限速，避免被ban
            except Exception as e:
                logger.debug(f"K线获取失败 {code}: {e}")
                continue

        if result:
            logger.info(f"K线数据获取: {len(result)}/{len(codes)} 只")
        return result

    # ── 基础过滤（无需K线）──────────────────────────────────────

    def _check_st(self, code: str, name: str) -> Optional[dict]:
        """ST/*ST 标的检查"""
        if "ST" in name.upper():
            is_gem_st = code.startswith("3")
            if is_gem_st:
                return {
                    "type": "st_stock", "severity": "danger",
                    "message": f"{name} 为创业板ST标的，建议回避",
                }
            else:
                return {
                    "type": "st_stock", "severity": "warning",
                    "message": f"{name} 含ST标识，风险较高，谨慎参与",
                }
        return None

    def _check_limit_up(self, change_pct: float, code: str) -> Optional[dict]:
        """涨停接近度检查

        主板±10%涨跌停，创业板(300/301)和科创板(688)±20%。
        """
        if change_pct is None or change_pct == 0:
            return None

        is_gem_or_star = (
            code.startswith("3") or code.startswith("688")
        )
        threshold = (
            self.config["limit_up_threshold_gem"]
            if is_gem_or_star
            else self.config["limit_up_threshold"]
        )

        if abs(change_pct) >= threshold:
            direction = "涨停" if change_pct > 0 else "跌停"
            return {
                "type": "limit_up", "severity": "warning",
                "message": f"接近{direction}({change_pct:+.1f}%，阈值{threshold}%)，追高风险大，建议等待回调",
            }
        return None

    def _check_liquidity(self, turnover_rate: float) -> Optional[dict]:
        """换手率流动性检查"""
        if turnover_rate is None or turnover_rate == 0:
            return {
                "type": "liquidity", "severity": "info",
                "message": "换手率数据缺失，无法评估流动性",
            }

        min_rate = self.config["min_turnover_rate"]
        if turnover_rate < min_rate:
            return {
                "type": "liquidity", "severity": "warning",
                "message": f"换手率仅 {turnover_rate:.2f}%，流动性偏低，大资金进出受限",
            }
        return None

    def _check_market_cap(self, circulating_cap: float) -> Optional[dict]:
        """流通市值检查（小盘/微盘股风险）"""
        if circulating_cap is None or circulating_cap == 0:
            return None

        cap_yi = circulating_cap / 1e8  # 元 → 亿
        micro = self.config["micro_cap_threshold_yi"]
        small = self.config["small_cap_threshold_yi"]

        if cap_yi < micro:
            return {
                "type": "market_cap", "severity": "danger",
                "message": f"流通市值仅 {cap_yi:.1f}亿（微盘股），波动剧烈、流动性差，建议回避",
            }
        elif cap_yi < small:
            return {
                "type": "market_cap", "severity": "warning",
                "message": f"流通市值 {cap_yi:.1f}亿（小盘股），波动较大，注意仓位控制",
            }
        return None

    def _check_amplitude(self, amplitude: float) -> Optional[dict]:
        """日内振幅异常检查"""
        if amplitude is None or amplitude == 0:
            return None
        if amplitude > 12:
            return {
                "type": "amplitude", "severity": "warning",
                "message": f"日内振幅 {amplitude:.1f}%，波动剧烈，多空分歧大",
            }
        return None

    # ── 增强过滤（需K线）────────────────────────────────────────

    def _calc_ma(self, bars: list, period: int) -> Optional[float]:
        """从K线bars计算移动均线"""
        if not bars or len(bars) < period:
            return None
        closes = [b["close"] for b in bars[-period:]]
        return round(sum(closes) / len(closes), 2)

    def _check_ma_position(self, code: str, price: float) -> Optional[dict]:
        """均线位置检查：价格相对MA5/MA10/MA20"""
        bars = self.kline_data.get(code)
        if not bars or len(bars) < 20:
            return None

        ma5 = self._calc_ma(bars, 5)
        ma10 = self._calc_ma(bars, 10)
        ma20 = self._calc_ma(bars, 20)

        if ma5 is None:
            return None

        # 判断均线排列
        if ma20 and price > ma5 > ma10 > ma20:
            status = "bullish_aligned"
            desc = "均线多头排列(价>MA5>MA10>MA20)，趋势强劲"
        elif ma20 and price > ma20:
            status = "above_ma20"
            desc = f"价格在MA20({ma20:.2f})之上，中期趋势向好"
        elif ma20:
            status = "below_ma20"
            desc = f"价格在MA20({ma20:.2f})之下，中期趋势偏弱"
        else:
            return None

        return {
            "type": "ma_position", "severity": "info",
            "message": desc,
            "detail": {
                "ma5": ma5, "ma10": ma10, "ma20": ma20,
                "status": status,
            },
            "score_bonus": 25 if "bullish" in status else (15 if "above_ma20" in status else 0),
        }

    def _check_volume_anomaly(self, code: str, volume: float) -> Optional[dict]:
        """量能异常检查：今日成交量 vs 5日均量"""
        bars = self.kline_data.get(code)
        if not bars or len(bars) < 6 or volume == 0:
            return None

        # 取最近5天（不含今天）的成交量均值
        recent_vols = [b["volume"] for b in bars[-6:-1]]
        avg_vol = sum(recent_vols) / len(recent_vols)
        if avg_vol == 0:
            return None

        ratio = volume / avg_vol
        surge = self.config["volume_surge_ratio"]
        extreme = self.config["volume_extreme_ratio"] if "volume_extreme_ratio" in self.config else 3.0
        shrink = self.config["volume_shrink_ratio"]

        if ratio >= extreme:
            return {
                "type": "volume_anomaly", "severity": "warning",
                "message": f"成交量是5日均量的 {ratio:.1f}倍，极端放量，注意高位出货风险",
                "score_bonus": 0,
            }
        elif ratio >= surge:
            return {
                "type": "volume_anomaly", "severity": "info",
                "message": f"成交量是5日均量的 {ratio:.1f}倍，放量明显，关注后续走势",
                "score_bonus": 5,
            }
        elif ratio <= shrink:
            return {
                "type": "volume_anomaly", "severity": "warning",
                "message": f"成交量仅5日均量的 {ratio:.0%}，缩量明显，缺乏上攻动力",
                "score_bonus": 5,
            }
        return None

    def _check_consecutive_rise(self, code: str) -> Optional[dict]:
        """连续上涨天数检查"""
        bars = self.kline_data.get(code)
        if not bars or len(bars) < 5:
            return None

        # 从最近一根K线往前数连续阳线（收盘>开盘）
        count = 0
        for bar in reversed(bars):
            if bar["close"] > bar["open"]:
                count += 1
            else:
                break

        warning = self.config["consecutive_rise_warning"]
        exclude = self.config.get("consecutive_rise_exclude", 5)

        if count >= exclude:
            return {
                "type": "consecutive_rise", "severity": "danger",
                "message": f"已连续上涨 {count} 天，严重超买，追高风险极大",
                "score_bonus": 0,
            }
        elif count >= warning:
            return {
                "type": "consecutive_rise", "severity": "warning",
                "message": f"已连续上涨 {count} 天，短期超买，追高需谨慎",
                "score_bonus": 5,
            }
        return None

    # ── 综合评分 ───────────────────────────────────────────────

    def _compute_score(self, quote: dict, kline_signals: list) -> int:
        """计算技术面综合评分 (0-100)

        基础分 50，各维度加减分。
        """
        score = 50

        # 换手率：1%~5% 最优
        tr = quote.get("turnover_rate", 0) or 0
        if 1 <= tr <= 5:
            score += 15
        elif 0.5 <= tr < 1:
            score += 8
        elif tr > 10:
            score += 5  # 过度活跃，需注意

        # 流通市值：越大越稳
        cap = (quote.get("circulating_cap", 0) or 0) / 1e8
        if cap > 500:
            score += 10
        elif cap > 100:
            score += 7
        elif cap > 20:
            score += 3

        # 涨跌幅：温和上涨最优
        chg = abs(quote.get("change_pct", 0) or 0)
        if chg < 3:
            score += 8
        elif chg < 5:
            score += 5
        elif chg > 8:
            score -= 5  # 追高成本高

        # 振幅：适中最好
        amp = quote.get("amplitude", 0) or 0
        if amp < 3:
            score += 5
        elif amp > 10:
            score -= 5

        # K线信号加分
        for sig in kline_signals:
            bonus = sig.get("score_bonus", 0)
            score += bonus

        return max(0, min(100, score))

    # ── 单标的过滤 ─────────────────────────────────────────────

    def _filter_single_stock(
        self, stock: dict, sector: str
    ) -> dict:
        """对单个标的执行全部过滤检查

        Args:
            stock: {"name": "天孚通信", "code": "300394"}
            sector: 所属板块名

        Returns:
            过滤结果 dict
        """
        code = stock.get("code", "")
        name = stock.get("name", "")
        quote = self.quotes.get(code, {})

        # 若 push2 实时行情获取失败，用 K线末条收盘价作价格 fallback
        if not quote.get("price") and code in self.kline_data:
            bars = self.kline_data[code]
            if bars:
                quote = {**quote,
                    "price": bars[-1]["close"],
                    "volume": bars[-1]["volume"],
                }
                logger.debug(f"{name}({code}) 使用K线收盘价/量 fallback: {bars[-1]['close']}")

        signals = []
        excluded = False
        kline_available = code in self.kline_data

        # ── 基础过滤 ──
        for check in [self._check_st, self._check_limit_up,
                       self._check_liquidity, self._check_market_cap,
                       self._check_amplitude]:
            try:
                if check == self._check_st:
                    result = self._check_st(code, name)
                elif check == self._check_limit_up:
                    result = self._check_limit_up(
                        quote.get("change_pct", 0), code
                    )
                elif check == self._check_liquidity:
                    result = self._check_liquidity(
                        quote.get("turnover_rate", 0)
                    )
                elif check == self._check_market_cap:
                    result = self._check_market_cap(
                        quote.get("circulating_cap", 0)
                    )
                else:
                    result = self._check_amplitude(
                        quote.get("amplitude", 0)
                    )

                if result:
                    signals.append(result)
                    if result["severity"] == "danger":
                        excluded = True
            except Exception as e:
                logger.debug(f"过滤检查异常 {name}({code}): {e}")

        # ── 增强过滤（K线）──
        kline_signals = []
        if kline_available:
            for check in [self._check_ma_position,
                           self._check_volume_anomaly,
                           self._check_consecutive_rise]:
                try:
                    if check == self._check_ma_position:
                        result = self._check_ma_position(code, quote.get("price", 0))
                    elif check == self._check_volume_anomaly:
                        result = self._check_volume_anomaly(code, quote.get("volume", 0))
                    else:
                        result = self._check_consecutive_rise(code)

                    if result:
                        signals.append(result)
                        kline_signals.append(result)
                        if result["severity"] == "danger":
                            excluded = True
                except Exception as e:
                    logger.debug(f"K线检查异常 {name}({code}): {e}")

        # ── 计算技术评分 ──
        score = self._compute_score(quote, kline_signals)

        return {
            "code": code,
            "name": name,
            "passed": not excluded,
            "excluded": excluded,
            "signals": signals,
            "technical_score": score,
            "quote": {
                "price": quote.get("price"),
                "change_pct": quote.get("change_pct"),
                "turnover_rate": quote.get("turnover_rate"),
                "circulating_cap_yi": round((quote.get("circulating_cap", 0) or 0) / 1e8, 1),
                "pe": quote.get("pe"),
            },
            "kline_available": kline_available,
        }

    # ── 信心度调整 ──────────────────────────────────────────────

    def _adjust_confidence(self, current: str, stock_results: list) -> str:
        """根据技术面结果调整板块推荐信心度

        规则：若有标的被排除 → 降一级；若所有标的评分>70 → 升一级
        """
        levels = {"低": 1, "中": 2, "高": 3}
        reverse = {1: "低", 2: "中", 3: "高"}
        level = levels.get(current, 2)

        excluded_count = sum(1 for r in stock_results if r["excluded"])
        avg_score = (
            sum(r["technical_score"] for r in stock_results) / len(stock_results)
            if stock_results else 50
        )

        if excluded_count >= len(stock_results):
            # 全部排除 → 降两级（后续可能整个板块被移除）
            new_level = max(level - 2, 1)
            return reverse[new_level]
        elif excluded_count > 0:
            new_level = max(level - 1, 1)
            return reverse[new_level]
        elif avg_score >= 75:
            new_level = min(level + 1, 3)
            return reverse[new_level]

        return current

    # ── 主入口 ─────────────────────────────────────────────────

    def apply(self, recommendations: List[Recommendation]) -> List[Recommendation]:
        """对全部推荐执行技术面过滤

        1. 收集所有标的 → 批量获取行情+K线
        2. 逐标的执行过滤检查
        3. 剔除被排除的标的，调整板块信心度
        4. 若板块内全部标的被排除 → 移除该板块推荐
        """
        if not recommendations or not self.config.get("enabled", True):
            return recommendations

        # 1. 收集所有唯一标的代码
        all_stocks: Dict[str, dict] = {}  # code → stock info
        for rec in recommendations:
            for s in rec.stocks:
                code = s.get("code", "")
                if code and code not in all_stocks:
                    all_stocks[code] = s

        if not all_stocks:
            return recommendations

        codes = list(all_stocks.keys())
        logger.info(f"技术面过滤启动 — 检查 {len(codes)} 只标的（来自 {len(recommendations)} 个板块）")

        # 2. 批量获取数据
        self.quotes = self.fetch_quotes(codes)
        self.kline_data = self.fetch_kline(codes)

        # 3. 逐板块过滤
        self._stats = {"total": 0, "passed": 0, "warned": 0, "excluded": 0}
        filtered = []

        for rec in recommendations:
            stock_results = []
            for s in rec.stocks:
                self._stats["total"] += 1
                result = self._filter_single_stock(s, rec.sector)
                stock_results.append(result)

                if result["excluded"]:
                    self._stats["excluded"] += 1
                elif any(sig["severity"] == "warning" for sig in result["signals"]):
                    self._stats["warned"] += 1
                else:
                    self._stats["passed"] += 1

            # 剔除被排除的标的
            valid_stocks = [
                s for i, s in enumerate(rec.stocks)
                if stock_results[i]["passed"]
            ]

            if not valid_stocks:
                logger.info(
                    f"  [{rec.sector}] 全部标的被技术面排除，移除该推荐"
                )
                continue  # 跳过该板块

            # 更新标的列表和信心度
            rec.stocks = valid_stocks

            # 根据技术面调整信心度
            old_conf = rec.confidence
            valid_results = [r for r in stock_results if r["passed"]]
            new_conf = self._adjust_confidence(old_conf, valid_results)
            if new_conf != old_conf:
                logger.info(
                    f"  [{rec.sector}] 信心度调整: {old_conf} → {new_conf}"
                )
            rec.confidence = new_conf

            # 注入技术面元数据
            if not hasattr(rec, "technical"):
                rec.technical = {}  # type: ignore
            rec.technical = {  # type: ignore
                "stock_results": stock_results,
                "avg_score": (
                    sum(r["technical_score"] for r in valid_results) / len(valid_results)
                    if valid_results else 0
                ),
            }

            # 将技术面警告注入风险提示
            danger_msgs = []
            for r in stock_results:
                for sig in r["signals"]:
                    if sig["severity"] in ("warning", "danger"):
                        danger_msgs.append(f"[{r['name']}] {sig['message']}")
            if danger_msgs:
                rec.risk = rec.risk + "；".join(["", "技术面警告："]) + "；".join(danger_msgs)

            filtered.append(rec)

        logger.info(
            f"技术面过滤完成: {self._stats['total']}只 → "
            f"通过{self._stats['passed']} | 警告{self._stats['warned']} | 排除{self._stats['excluded']}"
        )
        return filtered

    # ── 摘要生成 ───────────────────────────────────────────────

    def get_summary(self, filtered_recs: List[Recommendation]) -> str:
        """生成技术面过滤摘要（Markdown）"""
        if not filtered_recs or not self._stats.get("total"):
            return ""

        lines = [
            "## 📋 技术面过滤结果",
            "",
            f"**过滤统计**：检查 {self._stats['total']} 只标的 → "
            f"通过 {self._stats['passed']} | 警告 {self._stats['warned']} | 排除 {self._stats['excluded']}",
            "",
        ]

        for rec in filtered_recs:
            lines.append(f"### {rec.sector}")
            if hasattr(rec, "technical") and rec.technical:
                tr = rec.technical
                for r in tr.get("stock_results", []):
                    q = r.get("quote", {})
                    name = r["name"]
                    code = r["code"]

                    # 状态图标
                    if r["excluded"]:
                        icon = "🚫"
                    elif any(s["severity"] == "warning" for s in r["signals"]):
                        icon = "⚠️"
                    else:
                        icon = "✅"

                    # 基本信息
                    parts = [f"{icon} **{name}**（{code}）"]
                    if q.get("change_pct") is not None:
                        parts.append(f"{q['change_pct']:+.2f}%")
                    if q.get("turnover_rate"):
                        parts.append(f"换手{q['turnover_rate']:.2f}%")
                    if q.get("circulating_cap_yi"):
                        parts.append(f"流通{q['circulating_cap_yi']:.1f}亿")

                    lines.append("- " + " | ".join(parts))

                    # 信号详情
                    for sig in r["signals"]:
                        sev = {"danger": "🔴", "warning": "🟡", "info": "ℹ️"}.get(
                            sig["severity"], ""
                        )
                        lines.append(f"  {sev} {sig['message']}")

                    # 评分
                    lines.append(f"  > 技术评分: {r['technical_score']}/100")

                    if r.get("kline_available"):
                        # 查找MA信号
                        for sig in r["signals"]:
                            if sig.get("type") == "ma_position" and "detail" in sig:
                                d = sig["detail"]
                                lines.append(
                                    f"  > MA5:{d.get('ma5','?')} "
                                    f"MA10:{d.get('ma10','?')} "
                                    f"MA20:{d.get('ma20','?')}"
                                )
                                break

        lines.append("")
        return "\n".join(lines)


# ── 便捷函数 ─────────────────────────────────────────────────────

_engine: Optional[TechnicalFilterEngine] = None


def get_engine(config: dict = None) -> TechnicalFilterEngine:
    """获取全局引擎实例（单例模式）"""
    global _engine
    if _engine is None:
        _engine = TechnicalFilterEngine(config)
    return _engine


def apply_technical_filter(
    recommendations: List[Recommendation],
    config: dict = None,
) -> List[Recommendation]:
    """便捷函数：一站式技术面过滤

    Args:
        recommendations: AI生成+确认后的推荐列表
        config: 技术面过滤配置（可选，使用默认值）

    Returns:
        过滤后的推荐列表（标的可能被移除，信心度可能调整）
    """
    engine = get_engine(config)
    return engine.apply(recommendations)
