"""量化跟投模块 — 仓位管理 + 风控引擎

职责：
  1. 仓位计算：根据信号和当前状态计算目标仓位
  2. 止损止盈：硬止损(-5%)、ATR动态止损、移动止盈(8%)
  3. 风控规则：单日亏损熔断、连续亏损减半、总回撤熔断、T+1约束

资金模型（以 20,000 为例）：
  初始仓位：30% = 6,000 元
  最大仓位：60% = 12,000 元
  单次加仓：15% = 3,000 元
  现金保留：≥40% = 8,000 元
"""

import logging
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import List, Optional, Tuple

from src.quant.models import (
    IndicatorResults, Position, QuantSignal, SignalType, TradeRecord,
)

logger = logging.getLogger(__name__)


# ═══════════════════════════════════════════════════════════════
# 风控参数
# ═══════════════════════════════════════════════════════════════

DEFAULT_CAPITAL = 20000.0           # 默认总资金

# 仓位
INITIAL_POSITION = 0.30             # 初始仓位 30%
MAX_POSITION = 0.60                 # 最大仓位 60%
ADD_SIZE = 0.15                     # 单次加仓 15%
MIN_CASH = 0.40                     # 最低现金保留 40%

# 止损
HARD_STOP_PCT = -0.05               # 硬止损 -5%
ATR_STOP_MULT = 2.0                 # ATR 动态止损倍数
TRAILING_STOP_PCT = 0.08            # 移动止盈 8%（从最高点回撤）

# 止盈
TAKE_PROFIT_PCT = 0.15              # 目标止盈 15%

# 风控
DAILY_LOSS_LIMIT = -0.03            # 单日亏损熔断 -3%
MAX_CONSECUTIVE_LOSSES = 3          # 连续亏损上限
DRAWDOWN_CIRCUIT = -0.15            # 总回撤熔断 -15%
CIRCUIT_BREAKER_DAYS = 30           # 熔断恢复天数

# A股交易成本
STAMP_TAX_RATE = 0.001              # 印花税 0.1%（卖出单向）
COMMISSION_RATE = 0.00025           # 佣金 0.025%（双向，最低5元）


# ═══════════════════════════════════════════════════════════════
# 仓位管理
# ═══════════════════════════════════════════════════════════════

def calc_position_target(
    signal: SignalType,
    current_position: float,
    position: Optional[Position] = None,
) -> Tuple[float, int, float]:
    """根据信号计算目标仓位和操作股数

    Args:
        signal: 信号类型
        current_position: 当前仓位比例 (0-1)
        position: 当前持仓状态（可选）

    Returns:
        (target_ratio, target_shares, trade_amount) 目标仓位比例、目标股数、交易金额
    """
    total_capital = position.total_capital if position else DEFAULT_CAPITAL
    current_price = position.current_price if position and position.current_price > 0 else 0

    if signal == SignalType.OPEN:
        target = INITIAL_POSITION
    elif signal == SignalType.ADD:
        target = min(current_position + ADD_SIZE, MAX_POSITION)
    elif signal == SignalType.REDUCE:
        target = current_position * 0.5  # 减仓一半
    elif signal == SignalType.CLOSE:
        target = 0.0
    elif signal == SignalType.HOLD:
        target = current_position
    else:  # WAIT
        target = current_position

    trade_amount = (target - current_position) * total_capital
    shares = 0
    if current_price > 0:
        shares = int(abs(trade_amount) / current_price / 100) * 100  # 100股整手

    return target, shares, trade_amount


# ═══════════════════════════════════════════════════════════════
# 止损止盈计算
# ═══════════════════════════════════════════════════════════════

def calc_stop_loss(
    entry_price: float,
    current_price: float,
    atr14: float,
    highest_price: float = 0,
) -> Tuple[float, float, str]:
    """计算止损价和移动止盈价

    取更紧的：硬止损(-5%) vs ATR动态止损

    Returns:
        (stop_loss_price, trailing_stop, method)
    """
    hard_stop = entry_price * (1 + HARD_STOP_PCT)
    atr_stop = current_price - atr14 * ATR_STOP_MULT

    # 取更紧的止损（价格更高的）
    stop_loss = max(hard_stop, atr_stop)
    method = "硬止损" if stop_loss == hard_stop else "ATR动态"

    # 移动止盈：从最高点回撤 8%
    peak = max(highest_price, current_price)
    trailing = peak * (1 - TRAILING_STOP_PCT)

    return round(stop_loss, 2), round(trailing, 2), method


def calc_take_profit(entry_price: float) -> float:
    """计算目标止盈价"""
    return round(entry_price * (1 + TAKE_PROFIT_PCT), 2)


def check_stop_conditions(
    position: Position,
    current_price: float,
    atr14: float,
) -> Tuple[bool, str]:
    """检查是否触发止损/止盈

    Returns:
        (should_close, reason)
    """
    if position.status != "holding":
        return False, ""

    # 1. 硬止损
    if position.current_cost > 0:
        pnl_pct = (current_price - position.entry_price) / position.entry_price
        if pnl_pct <= HARD_STOP_PCT:
            return True, f"触发硬止损 ({pnl_pct*100:.1f}% ≤ -5%)"

    # 2. ATR 动态止损
    atr_stop = current_price - atr14 * ATR_STOP_MULT
    if position.stop_loss_price > 0 and current_price <= position.stop_loss_price:
        return True, f"触发动态止损 ({current_price:.2f} ≤ {position.stop_loss_price:.2f})"

    # 3. 移动止盈
    if position.trailing_stop > 0 and current_price <= position.trailing_stop:
        return True, f"触发移动止盈 (回撤>{TRAILING_STOP_PCT*100:.0f}%)"

    # 4. 目标止盈
    if (position.take_profit_price > 0 and
        current_price >= position.take_profit_price):
        return True, f"达到目标止盈 +{TAKE_PROFIT_PCT*100:.0f}%"

    return False, ""


# ═══════════════════════════════════════════════════════════════
# 风控规则
# ═══════════════════════════════════════════════════════════════

class RiskController:
    """风控控制器"""

    def __init__(self, total_capital: float = DEFAULT_CAPITAL):
        self.total_capital = total_capital
        self.initial_capital = total_capital
        self.consecutive_losses = 0
        self.trade_history: List[TradeRecord] = []
        self.circuit_breaker_until: Optional[str] = None  # 熔断到期日

    # ── 交易前检查 ──

    def can_trade(self, position: Position, signal: SignalType) -> Tuple[bool, str]:
        """检查是否可以执行交易

        Returns:
            (allowed, reason)
        """
        # 1. 熔断检查
        if self.circuit_breaker_until:
            if datetime.now().strftime("%Y-%m-%d") < self.circuit_breaker_until:
                return False, f"风控熔断中，{self.circuit_breaker_until} 前禁止交易"
            else:
                self.circuit_breaker_until = None  # 解禁

        # 2. 单日亏损检查
        if position.trading_blocked:
            return False, f"暂停交易: {position.block_reason}"

        # 3. 连续亏损检查
        if self.consecutive_losses >= MAX_CONSECUTIVE_LOSSES:
            return False, f"连续亏损{self.consecutive_losses}次，仓位已减半，请等待下次信号"

        # 4. T+1 约束：当天买入的次日才能卖
        # （此检查在调用方处理，这里仅标记）

        # 5. 买入限制：防御模式不开仓
        if signal == SignalType.OPEN and position.trading_blocked:
            return False, "交易暂停，不开新仓"

        return True, ""

    # ── 交易后更新 ──

    def record_trade(self, trade: TradeRecord):
        """记录交易并更新风控状态"""
        self.trade_history.append(trade)

        if trade.action == "sell":
            if trade.pnl < 0:
                self.consecutive_losses += 1
            else:
                self.consecutive_losses = 0  # 盈利重置

        # 检查连续亏损 → 仓位减半
        if self.consecutive_losses >= MAX_CONSECUTIVE_LOSSES:
            logger.warning(f"⚠️ 连续亏损{self.consecutive_losses}次，建议仓位减半")

        # 检查总回撤
        total_return = self._calc_total_return()
        if total_return <= DRAWDOWN_CIRCUIT:
            self.circuit_breaker_until = (
                datetime.now() + timedelta(days=CIRCUIT_BREAKER_DAYS)
            ).strftime("%Y-%m-%d")
            logger.warning(f"⚠️ 触发总回撤熔断: {total_return*100:.1f}%，暂停{CIRCUIT_BREAKER_DAYS}天")

    def _calc_total_return(self) -> float:
        """计算总收益率"""
        if not self.trade_history:
            return 0.0
        total_pnl = sum(t.pnl for t in self.trade_history)
        return total_pnl / self.initial_capital

    def get_stats(self) -> dict:
        """获取风控统计"""
        sells = [t for t in self.trade_history if t.action == "sell"]
        wins = [t for t in sells if t.pnl > 0]
        losses = [t for t in sells if t.pnl <= 0]

        return {
            "total_trades": len(self.trade_history),
            "completed_trades": len(sells),
            "win_rate": len(wins) / len(sells) if sells else 0.0,
            "consecutive_losses": self.consecutive_losses,
            "total_return": self._calc_total_return(),
            "avg_win": sum(t.pnl for t in wins) / len(wins) if wins else 0.0,
            "avg_loss": sum(t.pnl for t in losses) / len(losses) if losses else 0.0,
            "circuit_breaker": bool(self.circuit_breaker_until),
            "circuit_until": self.circuit_breaker_until or "",
        }


# ═══════════════════════════════════════════════════════════════
# 交易成本计算
# ═══════════════════════════════════════════════════════════════

def calc_trade_cost(price: float, shares: int, action: str = "buy") -> float:
    """计算交易成本（佣金+印花税）

    A股费用：
      - 佣金：0.025% 双向，最低 5 元
      - 印花税：0.1% 仅卖出
      - 过户费：0.001% 双向（通常忽略）
    """
    amount = price * shares
    commission = max(amount * COMMISSION_RATE, 5.0)
    stamp_tax = amount * STAMP_TAX_RATE if action == "sell" else 0.0

    return round(commission + stamp_tax, 2)


# ═══════════════════════════════════════════════════════════════
# 便捷初始化
# ═══════════════════════════════════════════════════════════════

def create_position(
    symbol: str,
    symbol_name: str = "",
    total_capital: float = DEFAULT_CAPITAL,
) -> Position:
    """创建空仓位实例"""
    return Position(
        symbol=symbol,
        symbol_name=symbol_name,
        total_capital=total_capital,
        max_position=total_capital * MAX_POSITION,
        cash_available=total_capital,
    )
