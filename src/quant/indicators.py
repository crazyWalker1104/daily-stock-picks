"""量化跟投模块 — 技术指标计算引擎

纯 Python 实现，零外部依赖（仅 math + statistics 标准库）。
从 K 线数据计算 MACD / RSI / 布林带 / KDJ / ATR / ADX / OBV 等常用指标。

设计原则：
  - 输入：List[KLData] 按日期升序
  - 输出：IndicatorResults 对象
  - 容错：数据不足时返回空列表，不抛异常
"""

import logging
import math
from typing import List, Optional, Tuple

from src.quant.models import IndicatorResults, KLData

logger = logging.getLogger(__name__)


# ═══════════════════════════════════════════════════════════════
# 基本工具函数
# ═══════════════════════════════════════════════════════════════

def _ema(prices: List[float], period: int) -> List[float]:
    """计算指数移动平均 (EMA)"""
    if len(prices) < period:
        return [0.0] * len(prices)

    result = [0.0] * len(prices)
    multiplier = 2.0 / (period + 1)

    # 第一个有效值 = SMA
    result[period - 1] = sum(prices[:period]) / period

    for i in range(period, len(prices)):
        result[i] = (prices[i] - result[i - 1]) * multiplier + result[i - 1]

    return result


def _sma(prices: List[float], period: int) -> List[float]:
    """计算简单移动平均 (SMA)，不足时用已有数据"""
    result = [0.0] * len(prices)
    for i in range(len(prices)):
        if i >= period - 1:
            result[i] = sum(prices[i - period + 1:i + 1]) / period
    return result


def _highest(values: List[float], period: int) -> List[float]:
    """period 内最高值"""
    result = [0.0] * len(values)
    for i in range(len(values)):
        start = max(0, i - period + 1)
        result[i] = max(values[start:i + 1])
    return result


def _lowest(values: List[float], period: int) -> List[float]:
    """period 内最低值"""
    result = [0.0] * len(values)
    for i in range(len(values)):
        start = max(0, i - period + 1)
        result[i] = min(values[start:i + 1])
    return result


def _true_range(highs: List[float], lows: List[float], closes: List[float]) -> List[float]:
    """计算真实波幅 (True Range)"""
    result = [0.0] * len(highs)
    for i in range(len(highs)):
        if i == 0:
            result[i] = highs[i] - lows[i]
        else:
            result[i] = max(
                highs[i] - lows[i],
                abs(highs[i] - closes[i - 1]),
                abs(lows[i] - closes[i - 1])
            )
    return result


# ═══════════════════════════════════════════════════════════════
# 主计算函数
# ═══════════════════════════════════════════════════════════════

def compute_all(klines: List[KLData]) -> IndicatorResults:
    """一次性计算所有技术指标

    Args:
        klines: K线数据列表（按日期升序）

    Returns:
        IndicatorResults 包含所有指标
    """
    if not klines:
        return IndicatorResults()

    n = len(klines)
    closes = [k.close for k in klines]
    highs = [k.high for k in klines]
    lows = [k.low for k in klines]
    volumes = [k.volume for k in klines]

    result = IndicatorResults()

    # ── 均线 ──
    result.ma5 = _sma(closes, 5)
    result.ma10 = _sma(closes, 10)
    result.ma20 = _sma(closes, 20)
    result.ma60 = _sma(closes, 60) if n >= 60 else _sma(closes, min(n, 60))
    result.ma120 = _sma(closes, 120) if n >= 120 else _sma(closes, min(n, 120))

    # ── MACD (12, 26, 9) ──
    ema12 = _ema(closes, 12)
    ema26 = _ema(closes, 26)
    dif = [ema12[i] - ema26[i] for i in range(n)]
    dea = _ema(dif, 9)
    result.dif = dif
    result.dea = dea
    result.macd_hist = [(dif[i] - dea[i]) * 2 for i in range(n)]

    # ── RSI (6, 14, 24) ──
    result.rsi6 = _rsi(closes, 6)
    result.rsi14 = _rsi(closes, 14)
    result.rsi24 = _rsi(closes, 24)

    # ── 布林带 (20, 2) ──
    result.boll_mid = result.ma20
    result.boll_upper = [0.0] * n
    result.boll_lower = [0.0] * n
    result.boll_width = [0.0] * n
    for i in range(n):
        if i >= 19:
            window = closes[i - 19:i + 1]
            mean = sum(window) / 20
            variance = sum((x - mean) ** 2 for x in window) / 20
            std = math.sqrt(variance)
            result.boll_upper[i] = mean + 2 * std
            result.boll_lower[i] = mean - 2 * std
            result.boll_width[i] = (result.boll_upper[i] - result.boll_lower[i]) / mean * 100 if mean > 0 else 0

    # ── KDJ (9, 3, 3) ──
    result.k, result.d, result.j = _kdj(highs, lows, closes)

    # ── ATR (14) ──
    tr = _true_range(highs, lows, closes)
    # 使用 EMA 平滑 TR
    tr_ema = _ema(tr, 14) if n >= 14 else tr
    result.atr14 = tr_ema

    # ── ADX (14) ──
    result.pdi, result.mdi, result.adx = _adx(highs, lows, closes)

    # ── OBV ──
    result.obv = _obv(closes, volumes)

    # ── 成交量 ──
    result.vol_ma5 = _sma(volumes, 5)
    result.vol_ma20 = _sma(volumes, 20)
    result.volume_ratio = []
    for i in range(n):
        if i >= 4 and result.vol_ma5[i] > 0:
            result.volume_ratio.append(volumes[i] / result.vol_ma5[i])
        else:
            result.volume_ratio.append(1.0)

    return result


def _rsi(prices: List[float], period: int) -> List[float]:
    """计算 RSI (Relative Strength Index)"""
    n = len(prices)
    result = [0.0] * n
    if n < period + 1:
        return result

    gains = []
    losses = []
    for i in range(1, n):
        diff = prices[i] - prices[i - 1]
        gains.append(diff if diff > 0 else 0.0)
        losses.append(abs(diff) if diff < 0 else 0.0)

    # Wilder's smoothing
    avg_gain = sum(gains[:period]) / period
    avg_loss = sum(losses[:period]) / period

    for i in range(period, n):
        if i == period:
            if avg_loss == 0:
                result[i] = 100.0
            else:
                rs = avg_gain / avg_loss
                result[i] = 100.0 - (100.0 / (1.0 + rs))
        else:
            avg_gain = (avg_gain * (period - 1) + gains[i - 1]) / period
            avg_loss = (avg_loss * (period - 1) + losses[i - 1]) / period
            if avg_loss == 0:
                result[i] = 100.0
            else:
                rs = avg_gain / avg_loss
                result[i] = 100.0 - (100.0 / (1.0 + rs))

    return result


def _kdj(highs: List[float], lows: List[float], closes: List[float],
         n: int = 9, m1: int = 3, m2: int = 3) -> Tuple[List[float], List[float], List[float]]:
    """计算 KDJ 指标

    Returns:
        (k, d, j) 三个列表
    """
    length = len(closes)
    k = [50.0] * length
    d = [50.0] * length
    j = [50.0] * length

    if length < n:
        return k, d, j

    # RSV
    rsv = [0.0] * length
    for i in range(n - 1, length):
        hh = max(highs[i - n + 1:i + 1])
        ll = min(lows[i - n + 1:i + 1])
        if hh != ll:
            rsv[i] = (closes[i] - ll) / (hh - ll) * 100

    # K, D, J 递推
    for i in range(n, length):
        k[i] = (m1 - 1) / m1 * k[i - 1] + 1 / m1 * rsv[i]
        d[i] = (m2 - 1) / m2 * d[i - 1] + 1 / m2 * k[i]
        j[i] = 3 * k[i] - 2 * d[i]

    return k, d, j


def _adx(highs: List[float], lows: List[float], closes: List[float],
         period: int = 14) -> Tuple[List[float], List[float], List[float]]:
    """计算 ADX (Average Directional Index)

    Returns:
        (pdi, mdi, adx) 三个列表
    """
    n = len(highs)
    pdi = [0.0] * n
    mdi = [0.0] * n
    adx = [0.0] * n

    if n < period + 1:
        return pdi, mdi, adx

    # True Range
    tr = _true_range(highs, lows, closes)

    # +DM, -DM
    plus_dm = [0.0] * n
    minus_dm = [0.0] * n
    for i in range(1, n):
        up = highs[i] - highs[i - 1]
        down = lows[i - 1] - lows[i]

        if up > down and up > 0:
            plus_dm[i] = up
        else:
            plus_dm[i] = 0.0

        if down > up and down > 0:
            minus_dm[i] = down
        else:
            minus_dm[i] = 0.0

    # Wilder's smoothing for TR, +DM, -DM
    tr_smoothed = [0.0] * n
    plus_dm_smoothed = [0.0] * n
    minus_dm_smoothed = [0.0] * n

    # Initial values (SMA of first period)
    start = period
    tr_smoothed[start] = sum(tr[1:start + 1])
    plus_dm_smoothed[start] = sum(plus_dm[1:start + 1])
    minus_dm_smoothed[start] = sum(minus_dm[1:start + 1])

    for i in range(start + 1, n):
        tr_smoothed[i] = tr_smoothed[i - 1] - tr_smoothed[i - 1] / period + tr[i]
        plus_dm_smoothed[i] = plus_dm_smoothed[i - 1] - plus_dm_smoothed[i - 1] / period + plus_dm[i]
        minus_dm_smoothed[i] = minus_dm_smoothed[i - 1] - minus_dm_smoothed[i - 1] / period + minus_dm[i]

    # +DI, -DI
    for i in range(start, n):
        if tr_smoothed[i] > 0:
            pdi[i] = plus_dm_smoothed[i] / tr_smoothed[i] * 100
            mdi[i] = minus_dm_smoothed[i] / tr_smoothed[i] * 100

    # DX and ADX
    dx = [0.0] * n
    for i in range(start, n):
        if pdi[i] + mdi[i] > 0:
            dx[i] = abs(pdi[i] - mdi[i]) / (pdi[i] + mdi[i]) * 100

    # ADX = EMA of DX with period
    adx_start = start + period - 1
    if adx_start < n:
        # Initial ADX = SMA of DX
        adx[adx_start] = sum(dx[start:adx_start + 1]) / period
        for i in range(adx_start + 1, n):
            adx[i] = (adx[i - 1] * (period - 1) + dx[i]) / period

    return pdi, mdi, adx


def _obv(closes: List[float], volumes: List[float]) -> List[float]:
    """计算 OBV (On-Balance Volume)"""
    n = len(closes)
    obv = [0.0] * n
    if n == 0:
        return obv

    obv[0] = volumes[0]
    for i in range(1, n):
        if closes[i] > closes[i - 1]:
            obv[i] = obv[i - 1] + volumes[i]
        elif closes[i] < closes[i - 1]:
            obv[i] = obv[i - 1] - volumes[i]
        else:
            obv[i] = obv[i - 1]

    return obv


# ═══════════════════════════════════════════════════════════════
# 便捷函数 — 获取最新值
# ═══════════════════════════════════════════════════════════════

def latest_signal_flags(ind: IndicatorResults) -> dict:
    """从指标结果中提取信号判定用的布尔标志

    Returns:
        dict 包含各种技术信号标志
    """
    return {
        # 均线排列
        "ma_bullish": (
            ind.latest("ma5") > ind.latest("ma10") > ind.latest("ma20")
        ),
        "ma_bearish": (
            ind.latest("ma5") < ind.latest("ma10") < ind.latest("ma20")
        ),
        "price_above_ma20": (
            ind.latest("ma20") > 0 and ind.latest("ma5") > ind.latest("ma20")
        ),
        "price_below_ma20": (
            ind.latest("ma20") > 0 and ind.latest("ma5") < ind.latest("ma20")
        ),

        # MACD
        "macd_golden_cross": _check_golden_cross(ind.dif, ind.dea, lookback=5),
        "macd_dead_cross": _check_dead_cross(ind.dif, ind.dea, lookback=5),
        "macd_hist_growing": _check_growing(ind.macd_hist),
        "macd_hist_shrinking": _check_shrinking(ind.macd_hist),

        # RSI
        "rsi_overbought": ind.latest("rsi14") > 70,
        "rsi_oversold": ind.latest("rsi14") < 35,
        "rsi_strong": 50 < ind.latest("rsi14") <= 70,
        "rsi_weak": 30 <= ind.latest("rsi14") < 45,

        # 布林
        "boll_near_lower": (
            ind.latest("boll_lower") > 0 and
            ind.latest("ma5") <= ind.latest("boll_lower") * 1.02
        ),
        "boll_near_upper": (
            ind.latest("boll_upper") > 0 and
            ind.latest("ma5") >= ind.latest("boll_upper") * 0.98
        ),
        "boll_squeeze": ind.latest("boll_width") < 5,     # 带宽收窄

        # KDJ
        "kdj_golden_cross": _check_kdj_golden_cross(ind),
        "kdj_dead_cross": _check_kdj_dead_cross(ind),
        "kdj_oversold": ind.latest("k") < 30 and ind.latest("d") < 30,
        "kdj_overbought": ind.latest("k") > 80 and ind.latest("d") > 80,

        # 成交量
        "volume_surge": ind.latest("volume_ratio") > 1.5,
        "volume_shrink": ind.latest("volume_ratio") < 0.6,
        "vol_ma5_up": _check_rising(ind.vol_ma5, 5),

        # ADX
        "adx_trending": ind.latest("adx") > 25,
        "adx_high": ind.latest("adx") > 40,
        "pdi_above_mdi": ind.latest("pdi") > ind.latest("mdi"),

        # OBV
        "obv_rising": _check_rising(ind.obv, 10),
        "obv_divergence": _check_obv_divergence(ind),
    }


def _check_golden_cross(dif: List[float], dea: List[float], lookback: int = 5) -> bool:
    """检查最近 lookback 天内是否有金叉"""
    if len(dif) < 2 or len(dea) < 2:
        return False
    start = max(0, len(dif) - lookback - 1)
    for i in range(start, len(dif) - 1):
        if dif[i] <= dea[i] and dif[i + 1] > dea[i + 1]:
            return True
    return False


def _check_dead_cross(dif: List[float], dea: List[float], lookback: int = 5) -> bool:
    """检查最近 lookback 天内是否有死叉"""
    if len(dif) < 2 or len(dea) < 2:
        return False
    start = max(0, len(dif) - lookback - 1)
    for i in range(start, len(dif) - 1):
        if dif[i] >= dea[i] and dif[i + 1] < dea[i + 1]:
            return True
    return False


def _check_kdj_golden_cross(ind: IndicatorResults) -> bool:
    """KDJ 金叉：K上穿D 且 J向上"""
    if len(ind.k) < 2 or len(ind.d) < 2:
        return False
    i = len(ind.k) - 1
    return ind.k[i - 1] <= ind.d[i - 1] and ind.k[i] > ind.d[i] and ind.j[i] > ind.j[i - 1]


def _check_kdj_dead_cross(ind: IndicatorResults) -> bool:
    """KDJ 死叉：K下穿D"""
    if len(ind.k) < 2 or len(ind.d) < 2:
        return False
    i = len(ind.k) - 1
    return ind.k[i - 1] >= ind.d[i - 1] and ind.k[i] < ind.d[i]


def _check_growing(values: List[float], lookback: int = 3) -> bool:
    """检查最近 N 个值是否递增"""
    if len(values) < lookback:
        return False
    recent = values[-lookback:]
    return all(recent[i] < recent[i + 1] for i in range(len(recent) - 1))


def _check_shrinking(values: List[float], lookback: int = 3) -> bool:
    """检查最近 N 个值是否递减"""
    if len(values) < lookback:
        return False
    recent = values[-lookback:]
    return all(recent[i] > recent[i + 1] for i in range(len(recent) - 1))


def _check_rising(values: List[float], lookback: int = 5) -> bool:
    """检查最近值是否高于 lookback 天前的值"""
    if len(values) < lookback:
        return False
    return values[-1] > values[-lookback] if values[-lookback] > 0 else False


def _check_obv_divergence(ind: IndicatorResults) -> bool:
    """OBV 顶背离：价格新高但OBV未新高"""
    if len(ind.obv) < 20:
        return False
    # 简单检查：近20日
    price_20d = ind.ma5[-20:] if len(ind.ma5) >= 20 else ind.ma5
    obv_20d = ind.obv[-20:]

    price_high = max(price_20d)
    obv_high = max(obv_20d)

    # 价格近高点但OBV不在高点
    latest_price = price_20d[-1]
    latest_obv = obv_20d[-1]

    return latest_price >= price_high * 0.97 and latest_obv < obv_high * 0.9
