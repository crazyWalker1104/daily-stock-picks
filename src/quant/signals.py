"""量化跟投模块 — 信号生成引擎

多因子规则打分，生成买卖信号。根据市场状态自适应切换策略：
  - 趋势市 → 追强模式（MA回踩买入、破位卖出）
  - 震荡市 → 抄底模式（布林下轨买入、上轨卖出）
  - 防御模式 → 仅持有或减仓，不开新仓

信号生成流程：
  1. 计算买入因子得分 (0-100)
  2. 计算卖出因子得分 (0-100，负数表示卖出压力)
  3. 综合得分 = 买入分 - 卖出分
  4. 根据阈值映射到信号类型
"""

import logging
from datetime import datetime
from typing import Dict, List, Optional

from src.quant.indicators import compute_all, latest_signal_flags as _get_flags
from src.quant.models import (
    IndicatorResults, MarketRegime, QuantSignal, RegimeResult,
    SignalType, StrategyMode,
)

logger = logging.getLogger(__name__)


# ═══════════════════════════════════════════════════════════════
# 信号阈值
# ═══════════════════════════════════════════════════════════════

SCORE_OPEN = 60       # ≥ 60 → 开仓
SCORE_ADD = 65        # ≥ 65 → 加仓（已有仓位时）
SCORE_HOLD = 40       # 40-59 → 持有
SCORE_REDUCE = 20     # 20-39 → 减仓
# < 20 → 清仓


# ═══════════════════════════════════════════════════════════════
# 主入口
# ═══════════════════════════════════════════════════════════════

def generate(
    symbol: str,
    symbol_name: str,
    indicators: IndicatorResults,
    regime_result: RegimeResult,
    current_price: float,
    in_position: bool = False,
    position_entry_price: float = 0.0,
) -> QuantSignal:
    """生成今日量化信号

    Args:
        symbol: 股票代码
        symbol_name: 股票名称
        indicators: 技术指标计算结果
        regime_result: 市场状态识别结果
        current_price: 当前价格
        in_position: 是否已持仓
        position_entry_price: 入场均价（已持仓时）

    Returns:
        QuantSignal 信号对象
    """
    mode = regime_result.mode
    flags = _get_flags(indicators)

    # ── 根据模式计算得分 ──
    if mode == StrategyMode.TREND_FOLLOWING:
        buy_score, buy_details = _calc_trend_following_buy(indicators, flags)
        sell_score, sell_details = _calc_common_sell(indicators, flags, current_price, position_entry_price)
    elif mode == StrategyMode.MEAN_REVERSION:
        buy_score, buy_details = _calc_mean_reversion_buy(indicators, flags)
        sell_score, sell_details = _calc_common_sell(indicators, flags, current_price, position_entry_price)
    else:
        # 防御模式：不生成买入信号
        buy_score, buy_details = 0.0, {"reason": "防御模式，不开新仓"}
        sell_score, sell_details = _calc_common_sell(indicators, flags, current_price, position_entry_price)

    total_score = buy_score - sell_score

    # ── 信号判定 ──
    signal, action_text, reasoning = _score_to_signal(
        total_score, buy_score, sell_score,
        in_position, mode, regime_result,
        buy_details, sell_details,
    )

    # ── 止损止盈价 ──
    atr14 = indicators.latest("atr14", default=current_price * 0.03)
    stop_loss = round(current_price - atr14 * 2, 2)
    take_profit = round(current_price * 1.15, 2)

    # ── 仓位建议 ──
    if signal in (SignalType.OPEN,):
        position_advice = 0.30  # 初始30%
    elif signal == SignalType.ADD:
        position_advice = 0.45  # 加仓至45%
    elif signal == SignalType.REDUCE:
        position_advice = 0.15  # 减至15%
    elif signal == SignalType.CLOSE:
        position_advice = 0.0
    elif signal == SignalType.HOLD:
        position_advice = 0.30  # 维持当前
    else:
        position_advice = 0.0

    # ── 风险等级 ──
    if sell_score >= 50:
        risk_level = "高"
    elif sell_score >= 30:
        risk_level = "中"
    else:
        risk_level = "低" if buy_score >= 50 else "中"

    return QuantSignal(
        symbol=symbol,
        symbol_name=symbol_name,
        date=datetime.now().strftime("%Y-%m-%d"),
        signal=signal,
        regime=regime_result.regime,
        mode=mode,
        total_score=round(total_score, 1),
        buy_score=round(buy_score, 1),
        sell_score=round(sell_score, 1),
        score_details={**buy_details, "sell_details": sell_details},
        current_price=current_price,
        suggested_entry=round(current_price, 2),
        stop_loss=stop_loss,
        take_profit=take_profit,
        position_advice=position_advice,
        risk_level=risk_level,
        indicators=indicators.to_dict(),
        action_text=action_text,
        reasoning=reasoning,
    )


# ═══════════════════════════════════════════════════════════════
# 追强模式 — 买入因子
# ═══════════════════════════════════════════════════════════════

def _calc_trend_following_buy(indicators: IndicatorResults, flags: dict) -> tuple:
    """趋势跟踪（追强）买入因子评分"""
    score = 0.0
    details = {}

    # 1. 均线多头排列 (+25)
    if flags["ma_bullish"]:
        score += 25
        details["ma_bullish"] = 25
    elif indicators.latest("ma5") > indicators.latest("ma20"):
        score += 15
        details["ma_partial_bullish"] = 15

    # 2. MACD 金叉 (+20)
    if flags["macd_golden_cross"] and indicators.latest("macd_hist") > 0:
        score += 20
        details["macd_golden_cross"] = 20
    elif flags["macd_hist_growing"]:
        score += 10
        details["macd_hist_growing"] = 10

    # 3. 量比 > 1.2 放量配合 (+15)
    vr = indicators.latest("volume_ratio")
    if vr > 1.5:
        score += 15
        details["volume_surge"] = 15
    elif vr > 1.2:
        score += 10
        details["volume_active"] = 10

    # 4. RSI 50-70 强势但不极端 (+10)
    rsi = indicators.latest("rsi14")
    if 50 < rsi <= 70:
        score += 10
        details["rsi_optimal"] = 10
    elif 40 < rsi <= 50:
        score += 5
        details["rsi_fair"] = 5

    # 5. KDJ 金叉 (+15)
    if flags["kdj_golden_cross"] and indicators.latest("j") < 80:
        score += 15
        details["kdj_golden_cross"] = 15
    elif indicators.latest("j") < 20:
        # KDJ 低位，可能即将金叉
        score += 5
        details["kdj_low"] = 5

    # 6. 回踩 MA20 不破 (+15)
    if (flags["price_above_ma20"] and
        indicators.latest("ma5") / indicators.latest("ma20") < 1.03):
        score += 15
        details["ma20_bounce"] = 15

    # 7. OBV 上行 (+10)
    if flags["obv_rising"] and not flags["obv_divergence"]:
        score += 10
        details["obv_rising"] = 10

    return min(score, 100), details


# ═══════════════════════════════════════════════════════════════
# 抄底模式 — 买入因子
# ═══════════════════════════════════════════════════════════════

def _calc_mean_reversion_buy(indicators: IndicatorResults, flags: dict) -> tuple:
    """均值回归（抄底）买入因子评分"""
    score = 0.0
    details = {}

    # 1. 价格触及布林下轨 (+25)
    if flags["boll_near_lower"]:
        score += 25
        details["boll_lower"] = 25
    elif (indicators.latest("boll_lower") > 0 and
          indicators.latest("ma5") <= indicators.latest("boll_lower") * 1.05):
        score += 15
        details["boll_near_lower"] = 15

    # 2. RSI < 35 超卖 (+20)
    rsi = indicators.latest("rsi14")
    if rsi < 30:
        score += 25
        details["rsi_oversold"] = 25
    elif rsi < 35:
        score += 20
        details["rsi_near_oversold"] = 20

    # 3. KDJ 低位金叉 (K/D < 30) (+20)
    if flags["kdj_golden_cross"] and flags["kdj_oversold"]:
        score += 20
        details["kdj_low_golden"] = 20
    elif flags["kdj_oversold"]:
        score += 10
        details["kdj_oversold"] = 10

    # 4. 缩量止跌 (量比 < 0.7) (+15)
    vr = indicators.latest("volume_ratio")
    if vr < 0.5:
        score += 15
        details["volume_dried"] = 15
    elif vr < 0.7:
        score += 10
        details["volume_low"] = 10

    # 5. 长下影线检测 (+10)
    if _has_long_lower_shadow(indicators):
        score += 10
        details["long_lower_shadow"] = 10

    # 6. OBV 底背离 → 虽然下跌但资金在流入 (+10)
    if flags["obv_divergence"]:
        score += 10
        details["obv_divergence_bullish"] = 10

    # 7. MACD 底背离 (-)
    if flags["macd_hist_growing"] and not flags["macd_golden_cross"]:
        score += 5
        details["macd_stabilizing"] = 5

    return min(score, 100), details


# ═══════════════════════════════════════════════════════════════
# 通用卖出因子
# ═══════════════════════════════════════════════════════════════

def _calc_common_sell(
    indicators: IndicatorResults,
    flags: dict,
    current_price: float,
    entry_price: float = 0.0,
) -> tuple:
    """通用卖出因子评分（趋势和震荡共用）"""
    score = 0.0
    details = {}

    # 1. 跌破 MA20 且 MA5 下穿 (-30)
    if flags["price_below_ma20"] and indicators.latest("ma5") < indicators.latest("ma10"):
        score += 30
        details["ma20_breakdown"] = 30
    elif flags["price_below_ma20"]:
        score += 15
        details["below_ma20"] = 15

    # 2. RSI > 80 严重超买 (-20)
    rsi = indicators.latest("rsi14")
    if rsi > 80:
        score += 20
        details["rsi_extreme"] = 20
    elif rsi > 70:
        score += 10
        details["rsi_overbought"] = 10

    # 3. MACD 死叉 (-20)
    if flags["macd_dead_cross"]:
        score += 20
        details["macd_dead_cross"] = 20
    elif flags["macd_hist_shrinking"] and indicators.latest("macd_hist") < 0:
        score += 10
        details["macd_weakening"] = 10

    # 4. 放量下跌 (量比 > 1.5) (-25)
    vr = indicators.latest("volume_ratio")
    price_dropping = indicators.latest("ma5") < indicators.latest("ma20")
    if vr > 1.5 and price_dropping:
        score += 25
        details["volume_crash"] = 25
    elif vr > 1.2 and price_dropping:
        score += 15
        details["volume_drop"] = 15

    # 5. KDJ 死叉 + 高位 (-15)
    if flags["kdj_dead_cross"] and indicators.latest("j") > 70:
        score += 15
        details["kdj_high_dead"] = 15

    # 6. 跌破布林中轨 (-10)
    if (indicators.latest("boll_mid") > 0 and
        indicators.latest("ma5") < indicators.latest("boll_mid")):
        score += 10
        details["boll_mid_break"] = 10

    # 7. OBV 连续下行 (-10)
    if not flags["obv_rising"] and flags["volume_surge"]:
        score += 10
        details["obv_volume_diverge"] = 10

    # 8. 浮亏超过止损线（已有仓位时）→ 直接清仓
    if entry_price > 0 and current_price < entry_price * 0.95:
        score += 100  # 强制清仓
        details["stop_loss_hit"] = 100

    return min(score, 100), details


# ═══════════════════════════════════════════════════════════════
# 辅助函数
# ═══════════════════════════════════════════════════════════════

def _score_to_signal(
    total_score: float,
    buy_score: float,
    sell_score: float,
    in_position: bool,
    mode: StrategyMode,
    regime_result: RegimeResult,
    buy_details: dict,
    sell_details: dict,
) -> tuple:
    """将评分映射到信号类型"""
    # 强制清仓
    if sell_details.get("stop_loss_hit", 0) >= 100:
        return (
            SignalType.CLOSE,
            "🔴 止损触发！请立即清仓",
            f"价格跌破-5%硬止损线，强制清仓（卖出压力分:{sell_score:.0f}）",
        )

    if in_position:
        # 已持仓状态
        if total_score >= SCORE_ADD:
            return (
                SignalType.ADD,
                f"🔵 建议加仓 (评分:{total_score:.0f})",
                f"追强趋势确认，MACD动量增强，加仓15%至总仓位45%（买入:{buy_score:.0f} 卖出:{sell_score:.0f}）",
            )
        elif total_score >= SCORE_HOLD:
            return (
                SignalType.HOLD,
                f"⚪ 继续持有 (评分:{total_score:.0f})",
                f"趋势完好但无明确加仓信号，持仓观望（买入:{buy_score:.0f} 卖出:{sell_score:.0f}）",
            )
        elif total_score >= SCORE_REDUCE:
            return (
                SignalType.REDUCE,
                f"🟠 建议减仓 (评分:{total_score:.0f})",
                f"趋势转弱/超买信号出现，减仓至15%控制风险（买入:{buy_score:.0f} 卖出:{sell_score:.0f}）",
            )
        else:
            return (
                SignalType.CLOSE,
                f"🔴 建议清仓 (评分:{total_score:.0f})",
                f"趋势破坏/卖出信号明确，清仓离场（买入:{buy_score:.0f} 卖出:{sell_score:.0f}）",
            )
    else:
        # 空仓状态
        if mode == StrategyMode.DEFENSIVE:
            return (
                SignalType.WAIT,
                f"⏸️ 建议观望 (评分:{total_score:.0f})",
                f"{regime_result.details.get('reason', '防御模式')}，等待明确信号",
            )
        elif total_score >= SCORE_OPEN:
            return (
                SignalType.OPEN,
                f"🟢 建议开仓 (评分:{total_score:.0f})",
                f"买入信号明确，建仓30%，止损设于ATR×2硬止损（买入:{buy_score:.0f} 卖出:{sell_score:.0f}）",
            )
        else:
            return (
                SignalType.WAIT,
                f"⏸️ 建议观望 (评分:{total_score:.0f})",
                f"买入信号不够强(需≥{SCORE_OPEN})，继续等待（买入:{buy_score:.0f} 卖出:{sell_score:.0f}）",
            )


def _has_long_lower_shadow(indicators: IndicatorResults) -> bool:
    """检测是否有长下影线（需要K线原始数据，此函数为近似检测）"""
    # 用布林带和RSI间接判断：价格在低位但RSI从低点回升
    atr = indicators.latest("atr14")
    boll_lower = indicators.latest("boll_lower")
    ma5 = indicators.latest("ma5")

    if atr > 0 and boll_lower > 0:
        # 如果价格在布林下轨附近且ATR相对较大 → 可能有长下影线
        price_above_lower = ma5 > boll_lower
        rsi_recovering = (
            len(indicators.rsi14) >= 3 and
            indicators.rsi14[-1] > indicators.rsi14[-3]
        )
        return not price_above_lower and rsi_recovering

    return False
