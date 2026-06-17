"""量化跟投模块 — 主引擎

编排所有子模块，提供统一的量化分析入口：
  - 标的筛选 (stock_picker)
  - 信号生成 (indicators → regime → signals)
  - 持仓管理 (tracker → risk)
  - 回测 (backtest)
  - K线数据获取 (通过 akshare)
"""

import logging
import os
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Tuple


from src.quant.models import (
    IndicatorResults, KLData, MarketRegime, Position, QuantSignal,
    SignalType, StockCandidate, TradeRecord,
    SIGNAL_EMOJI, SIGNAL_CN, REGIME_CN, MODE_CN,
)
from src.quant.indicators import compute_all
from src.quant.regime import detect as detect_regime
from src.quant.signals import generate as generate_signal
from src.quant.risk import (
    RiskController, calc_stop_loss, calc_take_profit, calc_position_target,
    calc_trade_cost, check_stop_conditions, create_position,
    DEFAULT_CAPITAL,
)
from src.quant.tracker import (
    PositionTracker, save_signal_snapshot, load_signal_snapshot,
    load_trade_history, record_trade, save_trade_history,
    save_watchlist, load_watchlist,
)
from src.quant.stock_picker import pick_candidates, format_candidates

logger = logging.getLogger(__name__)


# ═══════════════════════════════════════════════════════════════
# K线获取（akshare 封装）
# ═══════════════════════════════════════════════════════════════

_ak = None


def _get_ak():
    """懒加载 akshare（禁用系统代理 — 国内金融 API 直连）"""
    global _ak
    if _ak is None:
        # 绕过 Windows 系统代理（注册表/WPAD），国内金融站点直连更快更稳
        os.environ.setdefault('NO_PROXY', '*')
        try:
            import akshare as ak
            _ak = ak
        except ImportError:
            logger.warning("akshare 未安装")
            _ak = False
    return _ak if _ak is not False else None


def _symbol_to_ak(symbol: str) -> str:
    """6位代码转 akshare 格式：600036 → sh600036, 000001 → sz000001"""
    code = symbol.strip()
    if code.startswith(("60", "68")):
        return f"sh{code}"
    elif code.startswith(("00", "30")):
        return f"sz{code}"
    else:
        return f"sh{code}"  # 默认沪市


def fetch_klines(symbol: str, period: str = "daily",
                 days: int = 200) -> List[KLData]:
    """获取个股K线数据（使用 akshare stock_zh_a_daily，数据源：新浪）

    Args:
        symbol: 股票代码（6位数字，如 600036）
        period: K线周期 (daily/weekly/monthly) — 当前仅支持 daily
        days: 获取天数

    Returns:
        List[KLData] 按日期升序排列
    """
    ak = _get_ak()
    if not ak:
        logger.error("akshare 未安装，无法获取K线数据")
        return []

    try:
        end_date = datetime.now()
        start_date = end_date - timedelta(days=days + 30)  # 多取一些以覆盖非交易日

        ak_symbol = _symbol_to_ak(symbol)
        df = ak.stock_zh_a_daily(
            symbol=ak_symbol,
            start_date=start_date.strftime("%Y%m%d"),
            end_date=end_date.strftime("%Y%m%d"),
            adjust="qfq",  # 前复权
        )

        if df is None or df.empty:
            logger.warning(f"未获取到 {symbol} 的K线数据")
            return []

        # 取最近 days 条
        df = df.tail(days)

        klines = []
        for _, row in df.iterrows():
            klines.append(KLData(
                date=str(row.get("date", "")),
                open=float(row.get("open", 0)),
                high=float(row.get("high", 0)),
                low=float(row.get("low", 0)),
                close=float(row.get("close", 0)),
                volume=float(row.get("volume", 0)),
                amount=float(row.get("amount", 0)),
                turnover=float(row.get("turnover", 0)),
            ))

        logger.info(f"K线数据获取成功: {symbol} ({len(klines)} 条)")
        return klines

    except Exception as e:
        logger.error(f"获取K线数据失败: {symbol} — {e}")
        return []


def get_stock_name(symbol: str) -> str:
    """获取股票名称（通过 akshare）"""
    ak = _get_ak()
    if not ak:
        return ""

    try:
        df = ak.stock_info_a_code_name()
        match = df[df["code"] == symbol]
        if not match.empty:
            return str(match.iloc[0]["name"])
    except Exception as e:
        logger.warning(f"获取股票名称失败: {e}")

    return ""


# ═══════════════════════════════════════════════════════════════
# 主引擎
# ═══════════════════════════════════════════════════════════════

class QuantEngine:
    """量化跟投主引擎

    用法:
        engine = QuantEngine()
        engine.load_state()

        # 选股
        candidates = engine.pick_stocks()

        # 生成信号
        signal = engine.analyze("000001", "平安银行")

        # 查看状态
        print(engine.status_text())
    """

    def __init__(self, total_capital: float = DEFAULT_CAPITAL):
        self.total_capital = total_capital
        self.tracker = PositionTracker()
        self.risk = RiskController(total_capital)
        self.klines: List[KLData] = []
        self.indicators: Optional[IndicatorResults] = None
        self.current_signal: Optional[QuantSignal] = None

    # ── 状态管理 ──

    def load_state(self):
        """加载持仓状态和交易历史"""
        pos = self.tracker.load()
        trades = load_trade_history()
        self.risk.trade_history = trades

        if pos:
            self.total_capital = pos.total_capital
            self.risk.total_capital = pos.total_capital
            self.risk.initial_capital = pos.total_capital

        # 计算连续亏损
        sells = [t for t in trades if t.action == "sell"][::-1]
        for t in sells:
            if t.pnl < 0:
                self.risk.consecutive_losses += 1
            else:
                break

        return pos

    def save_state(self):
        """保存持仓状态"""
        self.tracker.save()
        save_trade_history(self.risk.trade_history)

    # ── 选股 ──

    def pick_stocks(self) -> List[StockCandidate]:
        """从推荐池筛选候选标的"""
        return pick_candidates()

    # ── 信号分析 ──

    def analyze(self, symbol: str, symbol_name: str = "",
                current_price: float = 0.0) -> Optional[QuantSignal]:
        """对指定标的全流程分析

        1. 获取K线数据
        2. 计算技术指标
        3. 识别市场状态
        4. 生成买卖信号

        Returns:
            QuantSignal 或 None（数据不足时）
        """
        # ── 1. K线 ──
        klines = fetch_klines(symbol)
        if not klines:
            logger.error(f"无法获取 {symbol} K线数据，分析中止")
            return None
        self.klines = klines

        if not symbol_name:
            symbol_name = get_stock_name(symbol) or symbol

        # ── 2. 指标 ──
        indicators = compute_all(klines)
        self.indicators = indicators

        # ── 3. 市场状态 ──
        regime_result = detect_regime(indicators)

        # ── 4. 当前价格 ──
        if current_price <= 0:
            current_price = klines[-1].close

        # ── 5. 持仓状态 ──
        in_position = False
        entry_price = 0.0
        if self.tracker.position and self.tracker.position.status == "holding":
            in_position = (self.tracker.position.symbol == symbol)
            entry_price = self.tracker.position.entry_price

        # ── 6. 信号 ──
        signal = generate_signal(
            symbol=symbol,
            symbol_name=symbol_name,
            indicators=indicators,
            regime_result=regime_result,
            current_price=current_price,
            in_position=in_position,
            position_entry_price=entry_price,
        )

        self.current_signal = signal

        # ── 7. 保存信号快照 ──
        save_signal_snapshot(signal)

        # ── 8. 更新持仓市价 ──
        if in_position:
            self.tracker.update_market(current_price)
            self.tracker.save()

        return signal

    # ── 交易执行模拟 ──

    def execute_signal(self) -> Tuple[bool, str]:
        """模拟执行当前信号（不实际交易，仅更新持仓状态）

        Returns:
            (success, message)
        """
        if not self.current_signal:
            return False, "无当前信号，请先调用 analyze()"

        signal = self.current_signal
        symbol = signal.symbol
        price = signal.current_price

        # 风控检查
        pos = self.tracker.position
        if pos:
            allowed, reason = self.risk.can_trade(pos, signal.signal)
            if not allowed:
                return False, reason

        if signal.signal == SignalType.OPEN:
            # 开仓
            target_ratio, shares, amount = calc_position_target(
                signal.signal, 0, pos
            )
            if shares < 100:
                return False, f"资金不足：最少1手100股需要 {price*100:.0f}元"

            cost = shares * price + calc_trade_cost(price, shares, "buy")
            self.tracker.open_position(
                symbol, signal.symbol_name, shares, price, cost,
                self.total_capital, signal.stop_loss, signal.take_profit,
            )
            self.tracker.save()

            trade = TradeRecord(
                symbol=symbol, symbol_name=signal.symbol_name,
                action="buy", trade_date=datetime.now().strftime("%Y-%m-%d"),
                price=price, shares=shares, amount=shares * price,
                commission=cost - shares * price,
                reason=signal.action_text,
                signal_snapshot=signal.to_dict(),
            )
            record_trade(trade, self.risk.trade_history)
            self.risk.record_trade(trade)

            return True, f"🟢 开仓成功: {signal.symbol_name} {shares}股 @ {price:.2f}"

        elif signal.signal == SignalType.ADD:
            # 加仓
            if not pos or pos.status != "holding":
                return False, "无持仓，无法加仓"

            current_ratio = pos.position_ratio
            target_ratio, shares, amount = calc_position_target(
                signal.signal, current_ratio, pos
            )
            if shares < 100:
                return False, f"资金不足，无法加仓"

            cost = shares * price + calc_trade_cost(price, shares, "buy")
            self.tracker.open_position(
                symbol, signal.symbol_name, shares, price,
                cost, self.total_capital,
                signal.stop_loss, signal.take_profit,
            )
            self.tracker.save()

            trade = TradeRecord(
                symbol=symbol, symbol_name=signal.symbol_name,
                action="buy", trade_date=datetime.now().strftime("%Y-%m-%d"),
                price=price, shares=shares, amount=shares * price,
                commission=cost - shares * price,
                reason=signal.action_text,
                signal_snapshot=signal.to_dict(),
            )
            record_trade(trade, self.risk.trade_history)
            self.risk.record_trade(trade)

            return True, f"🔵 加仓成功: {signal.symbol_name} +{shares}股 @ {price:.2f}"

        elif signal.signal == SignalType.REDUCE:
            if not pos or pos.status != "holding":
                return False, "无持仓，无法减仓"

            sell_shares = pos.current_shares // 2
            sell_shares = (sell_shares // 100) * 100  # 整手
            if sell_shares < 100:
                sell_shares = pos.current_shares

            sell_amount = sell_shares * price
            cost = calc_trade_cost(price, sell_shares, "sell")
            pnl = sell_amount - pos.entry_price * sell_shares - cost
            pnl_pct = pnl / (pos.entry_price * sell_shares) if pos.entry_price > 0 else 0

            new_shares = pos.current_shares - sell_shares
            pos.current_shares = new_shares
            pos.current_cost = pos.entry_price * new_shares if new_shares > 0 else 0
            if new_shares == 0:
                self.tracker.close_position()
            self.tracker.update_market(price)
            self.tracker.save()

            trade = TradeRecord(
                symbol=symbol, symbol_name=signal.symbol_name,
                action="sell", trade_date=datetime.now().strftime("%Y-%m-%d"),
                price=price, shares=sell_shares, amount=sell_amount,
                commission=cost - sell_amount * 0.001,
                stamp_tax=sell_amount * 0.001,
                pnl=pnl, pnl_pct=pnl_pct,
                reason=signal.action_text,
                signal_snapshot=signal.to_dict(),
            )
            record_trade(trade, self.risk.trade_history)
            self.risk.record_trade(trade)

            return True, f"🟠 减仓成功: 卖出{sell_shares}股 @ {price:.2f} (盈亏{pnl:+.0f}元)"

        elif signal.signal == SignalType.CLOSE:
            if not pos or pos.status != "holding":
                return False, "无持仓，无需清仓"

            sell_shares = pos.current_shares
            sell_amount = sell_shares * price
            cost = calc_trade_cost(price, sell_shares, "sell")
            total_pnl = sell_amount - pos.current_cost - cost
            total_pnl_pct = total_pnl / pos.current_cost if pos.current_cost > 0 else 0

            self.tracker.close_position()
            self.tracker.save()

            trade = TradeRecord(
                symbol=symbol, symbol_name=signal.symbol_name,
                action="sell", trade_date=datetime.now().strftime("%Y-%m-%d"),
                price=price, shares=sell_shares, amount=sell_amount,
                commission=cost - sell_amount * 0.001,
                stamp_tax=sell_amount * 0.001,
                pnl=total_pnl, pnl_pct=total_pnl_pct,
                reason=signal.action_text,
                signal_snapshot=signal.to_dict(),
            )
            record_trade(trade, self.risk.trade_history)
            self.risk.record_trade(trade)

            return True, f"🔴 清仓: 卖出{sell_shares}股 @ {price:.2f} (总盈亏{total_pnl:+.0f}元)"

        else:
            return True, f"⏸️ 观望，不操作"

    # ── 状态展示 ──

    def status_text(self) -> str:
        """生成完整状态文本"""
        lines = [
            "╔══════════════════════════════════════════════════════════════╗",
            "║               📊 量化跟投 · 当前状态                        ║",
            "╚══════════════════════════════════════════════════════════════╝",
            "",
        ]

        # 持仓
        lines.append(self.tracker.get_status_text())
        lines.append("")

        # 风控
        stats = self.risk.get_stats()
        lines.append("─" * 60)
        lines.append("📋 风控状态")
        lines.append(f"  已完成交易: {stats['completed_trades']}笔  |  "
                     f"胜率: {stats['win_rate']*100:.0f}%  |  "
                     f"连续亏损: {stats['consecutive_losses']}次")
        lines.append(f"  总收益: {stats['total_return']*100:+.1f}%")
        if stats["circuit_breaker"]:
            lines.append(f"  ⚠️ 熔断中！解禁: {stats['circuit_until']}")

        # 最近信号
        if self.current_signal:
            lines.append("")
            lines.append("─" * 60)
            lines.append(self.format_signal(self.current_signal))

        return "\n".join(lines)

    @staticmethod
    def format_signal(signal: QuantSignal) -> str:
        """格式化信号为可读文本"""
        emoji = SIGNAL_EMOJI.get(signal.signal, "❓")
        signal_cn = SIGNAL_CN.get(signal.signal, "未知")
        regime_cn = REGIME_CN.get(signal.regime, "未知")
        mode_cn = MODE_CN.get(signal.mode, "未知")

        lines = [
            f"  {emoji} 信号: {signal_cn}  |  "
            f"市场: {regime_cn}  |  策略: {mode_cn}",
            f"  综合评分: {signal.total_score:.0f}/100  "
            f"(买入 {signal.buy_score:.0f} | 卖出 {signal.sell_score:.0f})",
        ]

        if signal.position_advice > 0:
            lines.append(f"  建议仓位: {signal.position_advice*100:.0f}%  |  "
                         f"入场: {signal.suggested_entry:.2f}  |  "
                         f"止损: {signal.stop_loss:.2f}  |  "
                         f"止盈: {signal.take_profit:.2f}")

        lines.append(f"  风险: {signal.risk_level}  |  "
                     f"理由: {signal.reasoning}")

        # 指标摘要
        ind = signal.indicators
        if ind:
            rsi = ind.get("rsi14", 0)
            macd = ind.get("macd_hist", 0)
            adx = ind.get("adx", 0)
            vr = ind.get("volume_ratio", 1)
            lines.append(f"  RSI:{rsi:.0f}  MACD:{macd:.2f}  "
                         f"ADX:{adx:.0f}  量比:{vr:.2f}")

        return "\n".join(lines)
