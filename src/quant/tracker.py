"""量化跟投模块 — 持仓跟踪

职责：
  1. 持仓状态持久化（JSON文件）
  2. 浮动盈亏更新
  3. 交易历史记录
  4. 信号快照保存

数据存储路径：data/quant/
"""

import json
import logging
import os
from datetime import datetime
from typing import Dict, List, Optional

from src.quant.models import (
    Position, QuantSignal, TradeRecord, SIGNAL_EMOJI, SIGNAL_CN,
)

logger = logging.getLogger(__name__)


# ═══════════════════════════════════════════════════════════════
# 存储路径
# ═══════════════════════════════════════════════════════════════

_DATA_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__)))), "data", "quant")

POSITIONS_FILE = os.path.join(_DATA_DIR, "positions.json")
WATCHLIST_FILE = os.path.join(_DATA_DIR, "watchlist.json")
TRADE_HISTORY_FILE = os.path.join(_DATA_DIR, "trade_history.json")
SIGNALS_DIR = os.path.join(_DATA_DIR, "signals")


def _ensure_dir(path: str):
    """确保目录存在"""
    os.makedirs(os.path.dirname(path) if os.path.splitext(path)[1] else path,
                exist_ok=True)


# ═══════════════════════════════════════════════════════════════
# 持仓状态
# ═══════════════════════════════════════════════════════════════

class PositionTracker:
    """持仓跟踪器 — 管理当前持仓的读写和更新"""

    def __init__(self):
        self.position: Optional[Position] = None
        self.trades: List[TradeRecord] = []

    # ── 加载/保存 ──

    def load(self) -> Optional[Position]:
        """从文件加载持仓状态"""
        _ensure_dir(POSITIONS_FILE)
        try:
            if os.path.exists(POSITIONS_FILE):
                with open(POSITIONS_FILE, "r", encoding="utf-8") as f:
                    data = json.load(f)
                self.position = Position.from_dict(data)
                logger.info(f"持仓已加载: {self.position.symbol} "
                           f"{self.position.symbol_name} "
                           f"状态={self.position.status}")
                return self.position
        except Exception as e:
            logger.warning(f"加载持仓失败: {e}")
        return None

    def save(self):
        """保存持仓状态到文件"""
        if not self.position:
            return
        _ensure_dir(POSITIONS_FILE)
        try:
            self.position.updated_at = datetime.now().isoformat()
            with open(POSITIONS_FILE, "w", encoding="utf-8") as f:
                json.dump(self.position.to_dict(), f, ensure_ascii=False, indent=2)
        except Exception as e:
            logger.error(f"保存持仓失败: {e}")

    # ── 更新 ──

    def update_market(self, current_price: float, indicators: dict = None):
        """更新市价和浮动盈亏"""
        if not self.position or self.position.status != "holding":
            return

        self.position.current_price = current_price
        self.position.market_value = current_price * self.position.current_shares

        if self.position.current_cost > 0:
            self.position.float_pnl = (
                self.position.market_value - self.position.current_cost
            )
            self.position.float_pnl_pct = (
                self.position.float_pnl / self.position.current_cost
            )

        # 更新最高价
        if current_price > self.position.highest_price:
            self.position.highest_price = current_price

        # 更新移动止盈
        if self.position.highest_price > 0:
            self.position.trailing_stop = self.position.highest_price * 0.92

        self.position.position_ratio = (
            self.position.market_value / self.position.total_capital
            if self.position.total_capital > 0 else 0
        )

        self.position.cash_available = (
            self.position.total_capital - self.position.market_value
        )

    def open_position(self, symbol: str, symbol_name: str, shares: int,
                      price: float, cost: float, total_capital: float,
                      stop_loss: float, take_profit: float):
        """开仓/加仓"""
        if not self.position:
            from src.quant.risk import create_position
            self.position = create_position(symbol, symbol_name, total_capital)

        if self.position.status == "holding":
            # 加仓：更新均价
            old_cost = self.position.current_cost
            old_shares = self.position.current_shares
            new_total_cost = old_cost + cost
            new_total_shares = old_shares + shares
            self.position.entry_price = new_total_cost / new_total_shares if new_total_shares > 0 else price
            self.position.current_shares = new_total_shares
            self.position.current_cost = new_total_cost
        else:
            # 新开仓
            self.position.status = "holding"
            self.position.entry_date = datetime.now().strftime("%Y-%m-%d")
            self.position.entry_price = price
            self.position.current_shares = shares
            self.position.current_cost = cost

        self.position.current_price = price
        self.position.market_value = price * self.position.current_shares
        self.position.stop_loss_price = stop_loss
        self.position.take_profit_price = take_profit
        self.position.highest_price = price
        self.position.total_capital = total_capital
        self.position.position_ratio = (
            self.position.market_value / total_capital if total_capital > 0 else 0
        )

    def close_position(self):
        """清仓"""
        if self.position:
            self.position.status = "empty"
            self.position.current_shares = 0
            self.position.current_cost = 0
            self.position.market_value = 0
            self.position.float_pnl = 0
            self.position.float_pnl_pct = 0
            self.position.entry_price = 0
            self.position.entry_date = ""
            self.position.highest_price = 0
            self.position.trailing_stop = 0
            self.position.stop_loss_price = 0
            self.position.take_profit_price = 0
            self.position.position_ratio = 0
            self.position.cash_available = self.position.total_capital

    # ── 状态查询 ──

    def get_status_text(self) -> str:
        """生成持仓状态文本（用于CLI/推送）"""
        if not self.position or self.position.status != "holding":
            return "当前空仓 📭"

        return (
            f"📊 {self.position.symbol_name}({self.position.symbol})\n"
            f"  入场价: {self.position.entry_price:.2f}  |  "
            f"现价: {self.position.current_price:.2f}\n"
            f"  持股: {self.position.current_shares}股  |  "
            f"市值: {self.position.market_value:.0f}元  |  "
            f"仓位: {self.position.position_ratio*100:.0f}%\n"
            f"  浮动盈亏: {self.position.float_pnl:+.0f}元 "
            f"({self.position.float_pnl_pct*100:+.1f}%)\n"
            f"  止损: {self.position.stop_loss_price:.2f}  |  "
            f"止盈: {self.position.take_profit_price:.2f}  |  "
            f"移动止盈: {self.position.trailing_stop:.2f}"
        )


# ═══════════════════════════════════════════════════════════════
# 交易历史
# ═══════════════════════════════════════════════════════════════

def load_trade_history() -> List[TradeRecord]:
    """加载交易历史"""
    _ensure_dir(TRADE_HISTORY_FILE)
    try:
        if os.path.exists(TRADE_HISTORY_FILE):
            with open(TRADE_HISTORY_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
            return [TradeRecord(**item) for item in data]
    except Exception as e:
        logger.warning(f"加载交易历史失败: {e}")
    return []


def save_trade_history(trades: List[TradeRecord]):
    """保存交易历史"""
    _ensure_dir(TRADE_HISTORY_FILE)
    try:
        with open(TRADE_HISTORY_FILE, "w", encoding="utf-8") as f:
            json.dump([t.to_dict() for t in trades], f,
                      ensure_ascii=False, indent=2)
    except Exception as e:
        logger.error(f"保存交易历史失败: {e}")


def record_trade(trade: TradeRecord, trades: Optional[List[TradeRecord]] = None):
    """追加一条交易记录"""
    if trades is None:
        trades = load_trade_history()
    trades.append(trade)
    save_trade_history(trades)


# ═══════════════════════════════════════════════════════════════
# 信号快照
# ═══════════════════════════════════════════════════════════════

def save_signal_snapshot(signal: QuantSignal):
    """保存每日信号快照"""
    _ensure_dir(SIGNALS_DIR)
    filename = f"{signal.date}_signal.json"
    filepath = os.path.join(SIGNALS_DIR, filename)
    try:
        with open(filepath, "w", encoding="utf-8") as f:
            json.dump(signal.to_dict(), f, ensure_ascii=False, indent=2)
        logger.info(f"信号快照已保存: {filepath}")
    except Exception as e:
        logger.error(f"保存信号快照失败: {e}")


def load_signal_snapshot(date: str) -> Optional[dict]:
    """加载某天的信号快照"""
    filename = f"{date}_signal.json"
    filepath = os.path.join(SIGNALS_DIR, filename)
    try:
        if os.path.exists(filepath):
            with open(filepath, "r", encoding="utf-8") as f:
                return json.load(f)
    except Exception as e:
        logger.warning(f"加载信号快照失败: {e}")
    return None


# ═══════════════════════════════════════════════════════════════
# 观察列表
# ═══════════════════════════════════════════════════════════════

def load_watchlist() -> dict:
    """加载观察列表"""
    _ensure_dir(WATCHLIST_FILE)
    try:
        if os.path.exists(WATCHLIST_FILE):
            with open(WATCHLIST_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
    except Exception as e:
        logger.warning(f"加载观察列表失败: {e}")
    return {}


def save_watchlist(data: dict):
    """保存观察列表"""
    _ensure_dir(WATCHLIST_FILE)
    try:
        with open(WATCHLIST_FILE, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        logger.info("观察列表已保存")
    except Exception as e:
        logger.error(f"保存观察列表失败: {e}")
