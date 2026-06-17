"""量化跟投模块 — 历史回测引擎

对单只标的进行历史回测，验证策略有效性。

功能：
  - 按天遍历历史K线
  - 每天生成信号 → 执行模拟交易
  - 统计胜率、收益率、最大回撤、夏普比率
  - 考虑 T+1（当天买次日才能卖）、手续费（佣金+印花税）

回测参数：
  - 初始资金：20,000
  - 每次买入仓位：30%（首次）/ 15%（加仓）
  - 最大仓位：60%
  - 止损：-5% 硬止损
"""

import logging
import math
from datetime import datetime
from typing import Dict, List, Optional, Tuple

from src.quant.models import (
    BacktestResult, IndicatorResults, KLData, MarketRegime, Position,
    QuantSignal, SignalType, StrategyMode, TradeRecord,
)
from src.quant.indicators import compute_all
from src.quant.regime import detect as detect_regime
from src.quant.signals import generate as generate_signal
from src.quant.risk import (
    DEFAULT_CAPITAL, INITIAL_POSITION, ADD_SIZE, MAX_POSITION,
    HARD_STOP_PCT, TAKE_PROFIT_PCT,
    calc_trade_cost, create_position,
)

logger = logging.getLogger(__name__)


# ═══════════════════════════════════════════════════════════════
# 主回测入口
# ═══════════════════════════════════════════════════════════════

def backtest(
    symbol: str,
    symbol_name: str = "",
    klines: List[KLData] = None,
    start_date: str = "",
    end_date: str = "",
    initial_capital: float = DEFAULT_CAPITAL,
) -> Optional[BacktestResult]:
    """执行单标的历史回测

    模拟逻辑：
      - 每天用当天收盘价生成信号
      - 买入/加仓次日开盘执行（模拟T+1）
      - 卖出当天收盘执行
      - 止损条件盘后检查

    Args:
        symbol: 股票代码
        symbol_name: 股票名称
        klines: K线数据（按日期升序）
        start_date: 回测开始日期
        end_date: 回测结束日期
        initial_capital: 初始资金

    Returns:
        BacktestResult 或 None
    """
    if not klines:
        from src.quant.engine import fetch_klines
        klines = fetch_klines(symbol)
        if not klines:
            return None

    # 按日期过滤
    if start_date:
        klines = [k for k in klines if k.date >= start_date]
    if end_date:
        klines = [k for k in klines if k.date <= end_date]

    if len(klines) < 60:
        logger.warning(f"数据不足 {len(klines)}条，至少需要60条K线")
        return None

    if not symbol_name:
        symbol_name = symbol

    # ── 回测状态 ──
    cash = initial_capital
    shares = 0
    entry_price = 0.0
    highest_price = 0.0
    trades: List[TradeRecord] = []
    equity_curve: List[dict] = []
    total_capital = initial_capital

    # T+1：今日买入的不能在今日卖出
    t1_shares = 0           # 今日买入的股票（明日才能卖）
    t1_cost = 0.0

    last_signal = None

    # ── 逐日遍历 ──
    for i in range(60, len(klines)):
        # 用前 i+1 根K线做分析
        window = klines[:i + 1]
        today = window[-1]
        yesterday = window[-2]

        # 计算指标
        indicators = compute_all(window)
        regime = detect_regime(indicators)

        current_price = today.close
        in_position = shares > 0

        # 生成信号
        signal = generate_signal(
            symbol=symbol,
            symbol_name=symbol_name,
            indicators=indicators,
            regime_result=regime,
            current_price=current_price,
            in_position=in_position,
            position_entry_price=entry_price,
        )

        # ── T+1 交割：昨日买入的股票今天才可用于卖出 ──
        available_shares = shares
        if t1_shares > 0:
            # 昨日买入的股数今天成为可用
            available_shares = shares  # 今日可以卖全部持股
            t1_shares = 0
            t1_cost = 0.0

        # ── 先检查止损（盘中触发） ──
        if in_position and entry_price > 0:
            pnl_pct = (current_price - entry_price) / entry_price

            # 硬止损
            if pnl_pct <= HARD_STOP_PCT:
                # 清仓
                sell_amount = current_price * available_shares
                cost = calc_trade_cost(current_price, available_shares, "sell")
                total_pnl = sell_amount - entry_price * available_shares - cost
                total_pnl_pct = total_pnl / (entry_price * available_shares) if entry_price > 0 else 0

                cash += sell_amount - cost
                trades.append(TradeRecord(
                    symbol=symbol, symbol_name=symbol_name,
                    action="sell", trade_date=today.date,
                    price=current_price, shares=available_shares,
                    amount=sell_amount, commission=cost - sell_amount * 0.001,
                    stamp_tax=sell_amount * 0.001,
                    pnl=total_pnl, pnl_pct=total_pnl_pct,
                    reason=f"硬止损 ({pnl_pct*100:.1f}%)",
                ))
                shares = 0
                entry_price = 0
                highest_price = 0
                in_position = False
                last_signal = signal
                _record_equity(equity_curve, today.date, cash, shares, current_price)
                continue

            # 移动止盈（从最高点回撤 8%）
            if highest_price > 0 and current_price < highest_price * 0.92:
                sell_amount = current_price * available_shares
                cost = calc_trade_cost(current_price, available_shares, "sell")
                total_pnl = sell_amount - entry_price * available_shares - cost
                total_pnl_pct = total_pnl / (entry_price * available_shares) if entry_price > 0 else 0

                cash += sell_amount - cost
                trades.append(TradeRecord(
                    symbol=symbol, symbol_name=symbol_name,
                    action="sell", trade_date=today.date,
                    price=current_price, shares=available_shares,
                    amount=sell_amount, commission=cost - sell_amount * 0.001,
                    stamp_tax=sell_amount * 0.001,
                    pnl=total_pnl, pnl_pct=total_pnl_pct,
                    reason=f"移动止盈 ({current_price:.2f}<{highest_price*0.92:.2f})",
                ))
                shares = 0
                entry_price = 0
                highest_price = 0
                in_position = False
                last_signal = signal
                _record_equity(equity_curve, today.date, cash, shares, current_price)
                continue

        # ── 信号执行 ──
        if signal.signal == SignalType.OPEN and not in_position:
            # 开仓（次日开盘买入，模拟T+1）
            position_ratio = INITIAL_POSITION
            buy_amount = total_capital * position_ratio
            buy_price = today.close
            buy_shares = int(buy_amount / buy_price / 100) * 100

            if buy_shares >= 100 and cash >= buy_shares * buy_price:
                cost = buy_shares * buy_price + calc_trade_cost(buy_price, buy_shares, "buy")
                if cash >= cost:
                    cash -= cost
                    shares = buy_shares
                    entry_price = buy_price
                    highest_price = buy_price
                    t1_shares = buy_shares  # 今日买入，明日才能卖

                    trades.append(TradeRecord(
                        symbol=symbol, symbol_name=symbol_name,
                        action="buy", trade_date=today.date,
                        price=buy_price, shares=buy_shares, amount=buy_price * buy_shares,
                        commission=cost - buy_price * buy_shares,
                        reason=f"开仓信号 (评分:{signal.total_score:.0f})",
                    ))

        elif signal.signal == SignalType.ADD and in_position:
            # 加仓
            current_ratio = (shares * current_price) / total_capital
            new_ratio = min(current_ratio + ADD_SIZE, MAX_POSITION)
            add_amount = total_capital * (new_ratio - current_ratio)
            add_price = today.close
            add_shares = int(add_amount / add_price / 100) * 100

            if add_shares >= 100 and cash >= add_shares * add_price:
                cost = add_shares * add_price + calc_trade_cost(add_price, add_shares, "buy")
                if cash >= cost:
                    cash -= cost
                    # 更新均价
                    old_total_cost = entry_price * (shares - t1_shares + t1_shares)
                    entry_price = (old_total_cost + add_shares * add_price) / (shares + add_shares)
                    shares += add_shares
                    t1_shares += add_shares  # 今日新买入的

                    trades.append(TradeRecord(
                        symbol=symbol, symbol_name=symbol_name,
                        action="buy", trade_date=today.date,
                        price=add_price, shares=add_shares, amount=add_price * add_shares,
                        commission=cost - add_price * add_shares,
                        reason=f"加仓信号 (评分:{signal.total_score:.0f})",
                    ))

        elif signal.signal == SignalType.REDUCE and in_position:
            # 减仓一半（今天卖出，不涉及T+1）
            sell_shares = (available_shares // 2 // 100) * 100
            if sell_shares >= 100:
                sell_amount = current_price * sell_shares
                cost = calc_trade_cost(current_price, sell_shares, "sell")
                pnl = sell_amount - entry_price * sell_shares - cost
                pnl_pct = pnl / (entry_price * sell_shares) if entry_price > 0 else 0

                cash += sell_amount - cost
                shares -= sell_shares

                trades.append(TradeRecord(
                    symbol=symbol, symbol_name=symbol_name,
                    action="sell", trade_date=today.date,
                    price=current_price, shares=sell_shares, amount=sell_amount,
                    commission=cost - sell_amount * 0.001,
                    stamp_tax=sell_amount * 0.001,
                    pnl=pnl, pnl_pct=pnl_pct,
                    reason=f"减仓信号 (评分:{signal.total_score:.0f})",
                ))

        elif signal.signal == SignalType.CLOSE and in_position:
            # 清仓
            sell_shares = available_shares
            if sell_shares >= 100:
                sell_amount = current_price * sell_shares
                cost = calc_trade_cost(current_price, sell_shares, "sell")
                total_pnl = sell_amount - entry_price * sell_shares - cost
                total_pnl_pct = total_pnl / (entry_price * sell_shares) if entry_price > 0 else 0

                cash += sell_amount - cost
                trades.append(TradeRecord(
                    symbol=symbol, symbol_name=symbol_name,
                    action="sell", trade_date=today.date,
                    price=current_price, shares=sell_shares, amount=sell_amount,
                    commission=cost - sell_amount * 0.001,
                    stamp_tax=sell_amount * 0.001,
                    pnl=total_pnl, pnl_pct=total_pnl_pct,
                    reason=f"清仓信号 (评分:{signal.total_score:.0f})",
                ))
                shares = 0
                entry_price = 0
                highest_price = 0
                in_position = False

        # 更新最高价
        if in_position and current_price > highest_price:
            highest_price = current_price

        last_signal = signal
        _record_equity(equity_curve, today.date, cash, shares, current_price)

    # ── 回测结束：如果还持仓，以最后一天收盘价清仓 ──
    if shares > 0:
        last_close = klines[-1].close
        sell_amount = last_close * shares
        cost = calc_trade_cost(last_close, shares, "sell")
        final_pnl = sell_amount - entry_price * shares - cost

        cash += sell_amount - cost
        trades.append(TradeRecord(
            symbol=symbol, symbol_name=symbol_name,
            action="sell", trade_date=klines[-1].date,
            price=last_close, shares=shares, amount=sell_amount,
            commission=cost - sell_amount * 0.001,
            stamp_tax=sell_amount * 0.001,
            pnl=final_pnl,
            reason="回测结束，强制平仓",
        ))

    # ── 统计 ──
    return _compute_stats(
        symbol=symbol,
        symbol_name=symbol_name,
        start_date=klines[0].date,
        end_date=klines[-1].date,
        initial_capital=initial_capital,
        final_capital=cash,
        trades=trades,
        equity_curve=equity_curve,
        klines=klines,
    )


def _record_equity(curve: List[dict], date: str, cash: float,
                   shares: int, price: float):
    """记录每日净值"""
    curve.append({
        "date": date,
        "equity": cash + shares * price,
        "cash": cash,
        "shares": shares,
        "price": price,
    })


def _compute_stats(
    symbol: str,
    symbol_name: str,
    start_date: str,
    end_date: str,
    initial_capital: float,
    final_capital: float,
    trades: List[TradeRecord],
    equity_curve: List[dict],
    klines: List[KLData],
) -> BacktestResult:
    """计算回测统计指标"""
    sells = [t for t in trades if t.action == "sell"]

    total_return = (final_capital - initial_capital) / initial_capital

    # 年化收益率
    days = max(1, len(klines))
    annual_return = (1 + total_return) ** (252 / days) - 1

    # 胜率
    wins = [t for t in sells if t.pnl > 0]
    losses = [t for t in sells if t.pnl <= 0]
    win_rate = len(wins) / len(sells) if sells else 0

    # 最大回撤
    max_dd = 0.0
    peak = initial_capital
    for eq in equity_curve:
        if eq["equity"] > peak:
            peak = eq["equity"]
        dd = (peak - eq["equity"]) / peak
        if dd > max_dd:
            max_dd = dd

    # 夏普比率（简化计算）
    sharpe = 0.0
    if len(equity_curve) >= 2:
        daily_returns = []
        for i in range(1, len(equity_curve)):
            if equity_curve[i - 1]["equity"] > 0:
                r = (equity_curve[i]["equity"] - equity_curve[i - 1]["equity"]) / equity_curve[i - 1]["equity"]
                daily_returns.append(r)

        if daily_returns:
            avg = sum(daily_returns) / len(daily_returns)
            variance = sum((r - avg) ** 2 for r in daily_returns) / len(daily_returns)
            std = math.sqrt(variance)
            if std > 0:
                sharpe = (avg / std) * math.sqrt(252)

    # 盈亏比
    avg_win = sum(t.pnl for t in wins) / len(wins) if wins else 0
    avg_loss = sum(t.pnl for t in losses) / len(losses) if losses else 0
    profit_factor = abs(avg_win / avg_loss) if avg_loss != 0 else 0

    # 连胜/连败
    max_win_streak = 0
    max_loss_streak = 0
    current_win = 0
    current_loss = 0
    for t in sells:
        if t.pnl > 0:
            current_win += 1
            current_loss = 0
            max_win_streak = max(max_win_streak, current_win)
        else:
            current_loss += 1
            current_win = 0
            max_loss_streak = max(max_loss_streak, current_loss)

    return BacktestResult(
        symbol=symbol,
        symbol_name=symbol_name,
        start_date=start_date,
        end_date=end_date,
        total_trades=len(sells),
        win_trades=len(wins),
        loss_trades=len(losses),
        win_rate=round(win_rate, 4),
        total_return=round(total_return, 4),
        annual_return=round(annual_return, 4),
        max_drawdown=round(max_dd, 4),
        sharpe_ratio=round(sharpe, 2),
        avg_win=round(avg_win, 2),
        avg_loss=round(avg_loss, 2),
        profit_factor=round(profit_factor, 2),
        max_win_streak=max_win_streak,
        max_loss_streak=max_loss_streak,
        trades=trades,
        equity_curve=equity_curve,
    )


# ═══════════════════════════════════════════════════════════════
# CLI 友好输出
# ═══════════════════════════════════════════════════════════════

def format_backtest(result: BacktestResult) -> str:
    """格式化回测结果为可读文本"""
    lines = [
        "╔══════════════════════════════════════════════════════════════╗",
        "║             📈 历史回测 · 绩效报告                          ║",
        "╚══════════════════════════════════════════════════════════════╝",
        "",
        f"  标的: {result.symbol_name}（{result.symbol}）",
        f"  回测区间: {result.start_date} ～ {result.end_date}",
        "",
        "─" * 60,
        "📊 核心指标",
        f"  总交易: {result.total_trades}笔  |  "
        f"胜: {result.win_trades}  |  "
        f"败: {result.loss_trades}  |  "
        f"胜率: {result.win_rate*100:.1f}%",
        "",
        f"  总收益率: {result.total_return*100:+.2f}%  |  "
        f"年化收益率: {result.annual_return*100:+.2f}%",
        f"  最大回撤: {result.max_drawdown*100:.2f}%  |  "
        f"夏普比率: {result.sharpe_ratio:.2f}",
        "",
        f"  平均盈利: {result.avg_win:+,.0f}元  |  "
        f"平均亏损: {result.avg_loss:+,.0f}元  |  "
        f"盈亏比: {result.profit_factor:.2f}",
        f"  最大连胜: {result.max_win_streak}次  |  "
        f"最大连败: {result.max_loss_streak}次",
        "",
    ]

    # 最近10笔交易详情
    if result.trades:
        lines.append("─" * 60)
        lines.append("📋 最近交易记录")
        for t in result.trades[-10:]:
            emoji = "🟢" if t.action == "buy" else "🔴"
            pnl_str = f"盈亏{t.pnl:+.0f}元 ({t.pnl_pct*100:+.1f}%)" if t.action == "sell" else ""
            lines.append(
                f"  {emoji} {t.trade_date} {t.action.upper()} "
                f"{t.shares}股 @ {t.price:.2f}  {pnl_str}"
            )

    # 评估建议
    lines.append("")
    lines.append("─" * 60)
    if result.win_rate >= 0.6 and result.total_return > 0 and result.sharpe_ratio > 1.0:
        lines.append("✅ 回测表现良好，策略有效")
    elif result.win_rate >= 0.5 and result.total_return > 0:
        lines.append("⚠️ 回测表现一般，可继续优化")
    elif result.total_return > 0:
        lines.append("⚠️ 收益为正但胜率偏低，需优化信号阈值")
    else:
        lines.append("❌ 回测亏损，建议暂不实盘")

    return "\n".join(lines)
