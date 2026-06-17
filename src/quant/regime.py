"""量化跟投模块 — 市场状态识别引擎

通过均线排列 + ADX 判断当前市场状态（趋势/震荡/过渡），
并自动选择对应的策略模式（追强/抄底/防御）。

规则：
  - 趋势市 (trending): MA5 > MA20 > MA60 且 ADX > 25 → 追强模式
  - 趋势市 (trending): MA5 < MA20 < MA60 且 ADX > 25 → 防御模式
  - 震荡市 (ranging): 均线缠绕（MA5与MA20差距<2%）且 ADX < 20 → 抄底模式
  - 过渡期 (transition): 不满足以上条件 → 防御模式
"""

import logging
from typing import List

from src.quant.models import (
    IndicatorResults, KLData, MarketRegime, RegimeResult, StrategyMode,
)

logger = logging.getLogger(__name__)


# ═══════════════════════════════════════════════════════════════
# 状态判定参数
# ═══════════════════════════════════════════════════════════════

# ADX 阈值
ADX_TRENDING = 25        # ADX > 此值判定为趋势
ADX_STRONG_TREND = 40    # ADX > 此值判定为强趋势
ADX_RANGING = 20         # ADX < 此值判定为震荡

# 均线缠绕阈值
MA_TANGLE_PCT = 2.0      # MA5 与 MA20 差值百分比 < 此值视为缠绕



def detect(indicators: IndicatorResults, closes: List[float] = None) -> RegimeResult:
    """根据技术指标判断当前市场状态和策略模式

    Args:
        indicators: 技术指标计算结果
        closes: 收盘价列表（可选，用于辅助判断）

    Returns:
        RegimeResult 包含状态、模式、信心度
    """
    ma5 = indicators.latest("ma5")
    ma10 = indicators.latest("ma10")
    ma20 = indicators.latest("ma20")
    ma60 = indicators.latest("ma60")
    adx = indicators.latest("adx")
    pdi = indicators.latest("pdi")
    mdi = indicators.latest("mdi")
    rsi14 = indicators.latest("rsi14")

    details = {
        "ma5": round(ma5, 2),
        "ma10": round(ma10, 2),
        "ma20": round(ma20, 2),
        "ma60": round(ma60, 2),
        "adx": round(adx, 2),
        "pdi": round(pdi, 2),
        "mdi": round(mdi, 2),
        "rsi14": round(rsi14, 2),
    }

    # 数据不足 → 过渡期
    if ma5 == 0 or ma20 == 0:
        return RegimeResult(
            regime=MarketRegime.TRANSITION,
            mode=StrategyMode.DEFENSIVE,
            confidence=0.0,
            details=details,
        )

    # ── 1. 均线排列判断 ──
    bull_alignment = ma5 > ma10 > ma20
    bear_alignment = ma5 < ma10 < ma20

    if ma60 > 0:
        bull_alignment = ma5 > ma10 > ma20 > ma60
        bear_alignment = ma5 < ma10 < ma20 < ma60

    # 均线缠绕检测
    ma_diff_pct = abs(ma5 - ma20) / ma20 * 100 if ma20 > 0 else 100
    is_tangled = ma_diff_pct < MA_TANGLE_PCT

    # ── 2. ADX 趋势强度判断 ──
    strong_trend = adx > ADX_STRONG_TREND
    trending = adx > ADX_TRENDING
    ranging = adx < ADX_RANGING

    # ── 3. +DI/-DI 方向 ──
    di_bullish = pdi > mdi
    di_bearish = mdi > pdi

    # ── 4. 综合判定 ──

    # 多头排列 + 强趋势 → 上升趋势
    if bull_alignment and trending and di_bullish:
        confidence = 85.0 if strong_trend else 70.0
        return RegimeResult(
            regime=MarketRegime.TRENDING_UP,
            mode=StrategyMode.TREND_FOLLOWING,
            confidence=confidence,
            details={**details, "reason": "多头排列 + ADX趋势确认 + +DI领先"},
        )

    # 多头排列 + 弱趋势 → 上升趋势（轻度）
    if bull_alignment and di_bullish:
        return RegimeResult(
            regime=MarketRegime.TRENDING_UP,
            mode=StrategyMode.TREND_FOLLOWING,
            confidence=60.0,
            details={**details, "reason": "多头排列确认，ADX偏弱"},
        )

    # 空头排列 + 趋势 → 下降趋势
    if bear_alignment and trending and di_bearish:
        confidence = 85.0 if strong_trend else 70.0
        return RegimeResult(
            regime=MarketRegime.TRENDING_DOWN,
            mode=StrategyMode.DEFENSIVE,
            confidence=confidence,
            details={**details, "reason": "空头排列 + ADX趋势确认 + -DI领先"},
        )

    # 空头排列 + 弱趋势
    if bear_alignment and di_bearish:
        return RegimeResult(
            regime=MarketRegime.TRENDING_DOWN,
            mode=StrategyMode.DEFENSIVE,
            confidence=60.0,
            details={**details, "reason": "空头排列确认"},
        )

    # 均线缠绕 + 低ADX + 价格在布林中轨附近 → 震荡市
    if is_tangled and ranging:
        return RegimeResult(
            regime=MarketRegime.RANGING,
            mode=StrategyMode.MEAN_REVERSION,
            confidence=65.0 if ma_diff_pct < 1.0 else 50.0,
            details={**details, "reason": f"均线缠绕(差{ma_diff_pct:.1f}%) + 低ADX({adx:.1f})"},
        )

    # 均线缠绕 + 不太强的趋势 → 震荡
    if is_tangled and not strong_trend:
        return RegimeResult(
            regime=MarketRegime.RANGING,
            mode=StrategyMode.MEAN_REVERSION,
            confidence=50.0,
            details={**details, "reason": f"均线缠绕(差{ma_diff_pct:.1f}%)"},
        )

    # ── 5. 特殊情况 ──

    # RSI 极端超卖 + 低ADX → 可能即将反弹，暂按震荡处理
    if rsi14 < 30 and not strong_trend:
        return RegimeResult(
            regime=MarketRegime.RANGING,
            mode=StrategyMode.MEAN_REVERSION,
            confidence=45.0,
            details={**details, "reason": f"RSI超卖({rsi14:.1f})，关注反弹"},
        )

    # RSI 极端超买 + 高ADX → 趋势加速中，按趋势处理
    if rsi14 > 75 and trending and di_bullish:
        return RegimeResult(
            regime=MarketRegime.TRENDING_UP,
            mode=StrategyMode.TREND_FOLLOWING,
            confidence=55.0,
            details={**details, "reason": f"RSI超买({rsi14:.1f}) + 强趋势，注意追高风险"},
        )

    # ── 6. 默认：过渡期 → 防御模式 ──
    return RegimeResult(
        regime=MarketRegime.TRANSITION,
        mode=StrategyMode.DEFENSIVE,
        confidence=30.0,
        details={**details, "reason": "信号混杂，建议观望"},
    )
