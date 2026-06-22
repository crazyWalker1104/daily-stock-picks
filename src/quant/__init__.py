"""量化跟投模块 (Phase 5)

独立于每日A股推荐管线，专注单标的深度量化跟踪 + 买卖信号推送。

核心组件:
  - QuantEngine: 主引擎，编排所有子模块
  - models: 数据模型（信号/持仓/交易/回测）
  - indicators: 技术指标计算（MACD/RSI/布林/KDJ/ATR/ADX）
  - regime: 市场状态识别（趋势/震荡自适应）
  - signals: 信号生成引擎（多因子规则打分）
  - risk: 仓位管理 + 止损止盈 + 风控
  - tracker: 持仓跟踪 + 交易历史（JSON持久化）
  - stock_picker: 从推荐池量化选股
  - backtest: 历史回测（含T+1/手续费/印花税）

用法:
  python -m src.quant --pick              从推荐池筛选候选标的
  python -m src.quant --symbol 000001     生成今日信号
  python -m src.quant --status            查看持仓状态
  python -m src.quant --backtest 000001   历史回测
  python -m src.quant --watch             每日跟踪模式

设计原则:
  - 与现有 src/ 模块完全独立，仅复用 pusher.py 推送通道
  - 纯规则驱动，零ML依赖，透明可调
  - 信号生成可回溯，每步打分有明细
"""

import os

# 绕过 Windows 系统代理（必须在所有导入之前设置，因为 src.pusher 等
# 模块会在导入时实例化 requests.Session，触发 urllib3 缓存代理配置）
os.environ.setdefault('NO_PROXY', '*')
os.environ.setdefault('no_proxy', '*')

# 加载 .env 环境变量（必须在导入 pusher 之前，因为 WeChatPusher
# 在实例化时读取 WECHAT_SENDKEY 环境变量）
from dotenv import load_dotenv
load_dotenv()

from src.quant.models import (
    SignalType, MarketRegime, StrategyMode,
    QuantSignal, Position, TradeRecord, StockCandidate,
    BacktestResult, IndicatorResults, RegimeResult, KLData,
    SIGNAL_EMOJI, SIGNAL_CN,
)
from src.quant.indicators import compute_all
from src.quant.regime import detect as detect_regime
from src.quant.signals import generate as generate_signal
from src.quant.engine import QuantEngine
from src.quant.risk import (
    RiskController, calc_stop_loss, calc_take_profit,
    calc_position_target, create_position,
)
from src.quant.tracker import PositionTracker
from src.quant.stock_picker import pick_candidates
from src.quant.formatter import (
    format_signal_wechat, format_signal_email, format_daily_summary_email,
    format_status_wechat,
)
from src.quant.pusher import QuantPusher
from src.quant.daily_runner import run_daily

__all__ = [
    # 引擎
    "QuantEngine",

    # 模型
    "SignalType", "MarketRegime", "StrategyMode",
    "QuantSignal", "Position", "TradeRecord", "StockCandidate",
    "BacktestResult", "IndicatorResults", "RegimeResult", "KLData",
    "SIGNAL_EMOJI", "SIGNAL_CN",

    # 计算
    "compute_all", "detect_regime", "generate_signal",

    # 风控
    "RiskController", "calc_stop_loss", "calc_take_profit",
    "calc_position_target", "create_position",

    # 跟踪
    "PositionTracker",

    # 选股
    "pick_candidates",

    # 推送 (Phase 5.9)
    "QuantPusher", "format_signal_wechat", "format_signal_email",
    "format_daily_summary_email", "format_status_wechat", "run_daily",
]
