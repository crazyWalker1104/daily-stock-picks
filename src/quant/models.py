"""量化跟投模块 — 数据模型定义

信号类型、持仓状态、交易记录、市场状态等核心数据结构。
"""

from dataclasses import dataclass, field, asdict
from datetime import datetime
from enum import Enum
from typing import Dict, List, Optional


# ═══════════════════════════════════════════════════════════════
# 枚举定义
# ═══════════════════════════════════════════════════════════════

class SignalType(str, Enum):
    """信号类型 — 对应操作建议"""
    OPEN = "open"         # 🟢 开仓：首次入场
    ADD = "add"           # 🔵 加仓：顺势加码
    HOLD = "hold"         # ⚪ 持有：无需操作
    REDUCE = "reduce"     # 🟠 减仓：卖出一半
    CLOSE = "close"       # 🔴 清仓：全部卖出
    WAIT = "wait"         # ⏸️ 观望：空仓等待


class MarketRegime(str, Enum):
    """市场状态"""
    TRENDING_UP = "trending_up"       # 上升趋势
    TRENDING_DOWN = "trending_down"   # 下降趋势
    RANGING = "ranging"               # 震荡
    TRANSITION = "transition"         # 过渡期（不明确）


class StrategyMode(str, Enum):
    """策略模式"""
    TREND_FOLLOWING = "trend_following"   # 追强模式（趋势市）
    MEAN_REVERSION = "mean_reversion"     # 抄底模式（震荡市）
    DEFENSIVE = "defensive"               # 防御模式（降趋势）


# ═══════════════════════════════════════════════════════════════
# 数据类
# ═══════════════════════════════════════════════════════════════

@dataclass
class KLData:
    """K线数据（单日）"""
    date: str                # YYYY-MM-DD
    open: float
    high: float
    low: float
    close: float
    volume: float            # 成交量（手）
    amount: float = 0.0      # 成交额（元）
    turnover: float = 0.0    # 换手率（%）

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class IndicatorResults:
    """技术指标计算结果"""
    # 均线
    ma5: List[float] = field(default_factory=list)
    ma10: List[float] = field(default_factory=list)
    ma20: List[float] = field(default_factory=list)
    ma60: List[float] = field(default_factory=list)
    ma120: List[float] = field(default_factory=list)

    # MACD
    dif: List[float] = field(default_factory=list)
    dea: List[float] = field(default_factory=list)
    macd_hist: List[float] = field(default_factory=list)  # 柱状线 (DIF-DEA)*2

    # RSI
    rsi6: List[float] = field(default_factory=list)
    rsi14: List[float] = field(default_factory=list)
    rsi24: List[float] = field(default_factory=list)

    # 布林带
    boll_mid: List[float] = field(default_factory=list)    # 中轨 MA20
    boll_upper: List[float] = field(default_factory=list)  # 上轨
    boll_lower: List[float] = field(default_factory=list)  # 下轨
    boll_width: List[float] = field(default_factory=list)  # 带宽

    # KDJ
    k: List[float] = field(default_factory=list)
    d: List[float] = field(default_factory=list)
    j: List[float] = field(default_factory=list)

    # ATR
    atr14: List[float] = field(default_factory=list)

    # ADX
    adx: List[float] = field(default_factory=list)
    pdi: List[float] = field(default_factory=list)   # +DI
    mdi: List[float] = field(default_factory=list)   # -DI

    # OBV
    obv: List[float] = field(default_factory=list)

    # 成交量
    vol_ma5: List[float] = field(default_factory=list)
    vol_ma20: List[float] = field(default_factory=list)
    volume_ratio: List[float] = field(default_factory=list)  # 量比（相对5日均量）

    def latest(self, field_name: str, default: float = 0.0) -> float:
        """获取最新（最后一天）的指标值"""
        values = getattr(self, field_name, None)
        if values and len(values) > 0:
            return values[-1]
        return default

    def to_dict(self) -> dict:
        """转为字典（仅保存最新值，用于信号记录）"""
        return {
            "ma5": self.latest("ma5"),
            "ma10": self.latest("ma10"),
            "ma20": self.latest("ma20"),
            "ma60": self.latest("ma60"),
            "ma120": self.latest("ma120"),
            "dif": self.latest("dif"),
            "dea": self.latest("dea"),
            "macd_hist": self.latest("macd_hist"),
            "rsi6": self.latest("rsi6"),
            "rsi14": self.latest("rsi14"),
            "rsi24": self.latest("rsi24"),
            "boll_upper": self.latest("boll_upper"),
            "boll_mid": self.latest("boll_mid"),
            "boll_lower": self.latest("boll_lower"),
            "boll_width": self.latest("boll_width"),
            "k": self.latest("k"),
            "d": self.latest("d"),
            "j": self.latest("j"),
            "atr14": self.latest("atr14"),
            "adx": self.latest("adx"),
            "pdi": self.latest("pdi"),
            "mdi": self.latest("mdi"),
            "obv": self.latest("obv"),
            "vol_ma5": self.latest("vol_ma5"),
            "vol_ma20": self.latest("vol_ma20"),
            "volume_ratio": self.latest("volume_ratio"),
        }


@dataclass
class RegimeResult:
    """市场状态识别结果"""
    regime: MarketRegime = MarketRegime.TRANSITION
    mode: StrategyMode = StrategyMode.DEFENSIVE
    confidence: float = 0.0         # 状态判定的信心度 (0-100)
    details: dict = field(default_factory=dict)  # 详细指标

    def to_dict(self) -> dict:
        return {
            "regime": self.regime.value,
            "mode": self.mode.value,
            "confidence": self.confidence,
            "details": self.details,
        }


@dataclass
class QuantSignal:
    """每日量化信号"""
    symbol: str                       # 股票代码
    symbol_name: str = ""             # 股票名称
    date: str = ""                    # YYYY-MM-DD
    signal: SignalType = SignalType.WAIT
    regime: MarketRegime = MarketRegime.TRANSITION
    mode: StrategyMode = StrategyMode.DEFENSIVE

    # 评分详情
    total_score: float = 0.0          # 总得分
    buy_score: float = 0.0            # 买入因子得分
    sell_score: float = 0.0           # 卖出因子得分
    score_details: dict = field(default_factory=dict)  # 各因子详细得分

    # 价格信息
    current_price: float = 0.0
    suggested_entry: float = 0.0      # 建议入场价
    stop_loss: float = 0.0            # 止损价
    take_profit: float = 0.0          # 止盈价

    # 仓位建议
    position_advice: float = 0.0      # 建议仓位比例 (0-1)
    risk_level: str = "中"            # 风险等级：高/中/低

    # 指标快照
    indicators: dict = field(default_factory=dict)

    # 操作说明
    action_text: str = ""             # 操作建议文字
    reasoning: str = ""               # 决策理由

    generated_at: str = field(default_factory=lambda: datetime.now().isoformat())

    def to_dict(self) -> dict:
        return {
            "symbol": self.symbol,
            "symbol_name": self.symbol_name,
            "date": self.date,
            "signal": self.signal.value,
            "regime": self.regime.value,
            "mode": self.mode.value,
            "total_score": self.total_score,
            "buy_score": self.buy_score,
            "sell_score": self.sell_score,
            "score_details": self.score_details,
            "current_price": self.current_price,
            "suggested_entry": self.suggested_entry,
            "stop_loss": self.stop_loss,
            "take_profit": self.take_profit,
            "position_advice": self.position_advice,
            "risk_level": self.risk_level,
            "indicators": self.indicators,
            "action_text": self.action_text,
            "reasoning": self.reasoning,
            "generated_at": self.generated_at,
        }


@dataclass
class Position:
    """当前持仓状态"""
    symbol: str
    symbol_name: str = ""
    status: str = "empty"             # holding / empty

    # 入场信息
    entry_date: str = ""              # 入场日期
    entry_price: float = 0.0          # 入场均价
    current_shares: int = 0           # 当前持股数
    current_cost: float = 0.0         # 当前持仓成本（含手续费）

    # 当前状态
    current_price: float = 0.0
    market_value: float = 0.0         # 当前市值
    float_pnl: float = 0.0            # 浮动盈亏
    float_pnl_pct: float = 0.0        # 浮动盈亏百分比

    # 风控线
    stop_loss_price: float = 0.0
    take_profit_price: float = 0.0
    highest_price: float = 0.0        # 持仓期间最高价（移动止盈用）
    trailing_stop: float = 0.0        # 当前移动止盈价

    # 仓位
    total_capital: float = 0.0        # 总资金
    position_ratio: float = 0.0       # 仓位比例
    max_position: float = 0.0         # 最大仓位限制
    cash_available: float = 0.0       # 可用现金

    # 风控状态
    trading_blocked: bool = False     # 暂停交易
    block_reason: str = ""
    circuit_breaker: bool = False     # 熔断
    consecutive_losses: int = 0       # 连续亏损次数

    updated_at: str = field(default_factory=lambda: datetime.now().isoformat())

    def to_dict(self) -> dict:
        return {
            "symbol": self.symbol,
            "symbol_name": self.symbol_name,
            "status": self.status,
            "entry_date": self.entry_date,
            "entry_price": self.entry_price,
            "current_shares": self.current_shares,
            "current_cost": self.current_cost,
            "current_price": self.current_price,
            "market_value": self.market_value,
            "float_pnl": self.float_pnl,
            "float_pnl_pct": self.float_pnl_pct,
            "stop_loss_price": self.stop_loss_price,
            "take_profit_price": self.take_profit_price,
            "highest_price": self.highest_price,
            "trailing_stop": self.trailing_stop,
            "total_capital": self.total_capital,
            "position_ratio": self.position_ratio,
            "max_position": self.max_position,
            "cash_available": self.cash_available,
            "trading_blocked": self.trading_blocked,
            "block_reason": self.block_reason,
            "circuit_breaker": self.circuit_breaker,
            "consecutive_losses": self.consecutive_losses,
            "updated_at": self.updated_at,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "Position":
        return cls(**{k: v for k, v in data.items() if k in cls.__dataclass_fields__})


@dataclass
class TradeRecord:
    """单笔交易记录"""
    symbol: str
    symbol_name: str = ""
    action: str = ""                   # buy / sell
    trade_date: str = ""               # 成交日期
    price: float = 0.0
    shares: int = 0
    amount: float = 0.0               # 成交金额
    commission: float = 0.0           # 手续费
    stamp_tax: float = 0.0            # 印花税（卖出时）
    pnl: float = 0.0                  # 盈亏（仅卖出时）
    pnl_pct: float = 0.0              # 盈亏百分比
    reason: str = ""                  # 交易理由
    signal_snapshot: dict = field(default_factory=dict)  # 当时的信号快照

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class StockCandidate:
    """标的候选（从推荐池筛选）"""
    symbol: str
    symbol_name: str
    score: float = 0.0                # 综合评分 (0-100)
    tech_score: float = 0.0           # 技术面得分
    fund_score: float = 0.0           # 资金面得分
    trend_score: float = 0.0          # 趋势面得分
    fundamental_score: float = 0.0    # 基本面得分
    appearance_count: int = 0         # 在推荐中出现的次数
    last_confidence: str = ""         # 最近一次推荐的信心度
    last_sector: str = ""             # 最近一次推荐的板块
    avg_return: float = 0.0           # 历史次日平均收益
    win_rate: float = 0.0             # 历史胜率
    reason: str = ""                  # 推荐理由
    risks: List[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class BacktestResult:
    """回测结果"""
    symbol: str
    symbol_name: str = ""
    start_date: str = ""
    end_date: str = ""
    total_trades: int = 0
    win_trades: int = 0
    loss_trades: int = 0
    win_rate: float = 0.0

    # 收益
    total_return: float = 0.0         # 总收益率
    annual_return: float = 0.0        # 年化收益率
    max_drawdown: float = 0.0         # 最大回撤
    sharpe_ratio: float = 0.0         # 夏普比率

    # 交易细节
    avg_win: float = 0.0              # 平均盈利
    avg_loss: float = 0.0             # 平均亏损
    profit_factor: float = 0.0        # 盈亏比
    max_win_streak: int = 0           # 最大连胜
    max_loss_streak: int = 0          # 最大连败

    # 详细记录
    trades: List[TradeRecord] = field(default_factory=list)
    equity_curve: List[dict] = field(default_factory=list)  # 净值曲线

    def to_dict(self) -> dict:
        return {
            "symbol": self.symbol,
            "symbol_name": self.symbol_name,
            "start_date": self.start_date,
            "end_date": self.end_date,
            "total_trades": self.total_trades,
            "win_trades": self.win_trades,
            "loss_trades": self.loss_trades,
            "win_rate": self.win_rate,
            "total_return": self.total_return,
            "annual_return": self.annual_return,
            "max_drawdown": self.max_drawdown,
            "sharpe_ratio": self.sharpe_ratio,
            "avg_win": self.avg_win,
            "avg_loss": self.avg_loss,
            "profit_factor": self.profit_factor,
            "max_win_streak": self.max_win_streak,
            "max_loss_streak": self.max_loss_streak,
            "trades": [t.to_dict() for t in self.trades],
            "equity_curve": self.equity_curve,
        }


# ═══════════════════════════════════════════════════════════════
# 映射
# ═══════════════════════════════════════════════════════════════

SIGNAL_EMOJI = {
    SignalType.OPEN: "🟢",
    SignalType.ADD: "🔵",
    SignalType.HOLD: "⚪",
    SignalType.REDUCE: "🟠",
    SignalType.CLOSE: "🔴",
    SignalType.WAIT: "⏸️",
}

SIGNAL_CN = {
    SignalType.OPEN: "开仓",
    SignalType.ADD: "加仓",
    SignalType.HOLD: "持有",
    SignalType.REDUCE: "减仓",
    SignalType.CLOSE: "清仓",
    SignalType.WAIT: "观望",
}

REGIME_CN = {
    MarketRegime.TRENDING_UP: "上升趋势",
    MarketRegime.TRENDING_DOWN: "下降趋势",
    MarketRegime.RANGING: "震荡",
    MarketRegime.TRANSITION: "过渡期",
}

MODE_CN = {
    StrategyMode.TREND_FOLLOWING: "追强模式",
    StrategyMode.MEAN_REVERSION: "抄底模式",
    StrategyMode.DEFENSIVE: "防御模式",
}
