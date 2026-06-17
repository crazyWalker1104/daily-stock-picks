"""量化跟投模块 — 自动化日终管线

由 GitHub Actions 或本地定时任务调用，执行：
  1. 加载观察列表
  2. 如果为空 → 从推荐池自动选股
  3. 对每个标的生成信号
  4. 可操作信号 → 微信紧急推送
  5. 所有信号 → 邮件日结
  6. 保存状态

用法:
  python -m src.quant --daily-run              # 全流程（推送）
  python -m src.quant --daily-run --dry-run    # 不实际推送
  python -m src.quant --daily-run --channels wechat  # 仅微信
"""

import argparse
import logging
import sys
from datetime import datetime
from typing import Dict, List, Optional

from src.quant.engine import QuantEngine
from src.quant.models import QuantSignal, SignalType
from src.quant.pusher import QuantPusher, ACTIONABLE_SIGNALS
from src.quant.tracker import (
    load_watchlist, save_watchlist, save_signal_snapshot,
    PositionTracker, load_trade_history,
)

logger = logging.getLogger(__name__)


def run_daily(
    channels: Optional[List[str]] = None,
    dry_run: bool = False,
    capital: float = 20000,
) -> bool:
    """执行每日量化跟投管线

    Args:
        channels: 推送通道列表 (如 ['wechat', 'email'])，None=全部
        dry_run: True=只分析不推送，False=正常推送
        capital: 总资金

    Returns:
        True=成功，False=失败
    """
    logger.info("=" * 50)
    logger.info("  量化跟投 · 每日管线启动")
    logger.info("=" * 50)

    # ── 1. 加载引擎 ──
    engine = QuantEngine(total_capital=capital)
    pos = engine.load_state()
    tracker = engine.tracker
    risk = engine.risk

    # ── 2. 加载观察列表 ──
    watchlist = load_watchlist()
    if not watchlist or not watchlist.get("symbol"):
        logger.info("观察列表为空，自动从推荐池选股...")
        candidates = engine.pick_stocks()
        if not candidates:
            logger.warning("推荐池无候选，无法自动选股。请先运行 python -m src.main")
            return False

        # 自动选择第一名
        top = candidates[0]
        watchlist = {
            "symbol": top.symbol,
            "name": top.symbol_name,
            "score": top.score,
            "added_at": datetime.now().isoformat(),
        }
        save_watchlist(watchlist)
        logger.info(f"自动选择: {top.symbol_name}({top.symbol}) 评分:{top.score:.0f}")

        # 推送候选结果
        if not dry_run:
            pusher = QuantPusher()
            pusher.push_candidates(candidates[:3])

    symbol = watchlist["symbol"]
    symbol_name = watchlist.get("name", symbol)

    # ── 3. 信号分析 ──
    logger.info(f"分析标的: {symbol_name}({symbol})")
    signal = engine.analyze(symbol=symbol, symbol_name=symbol_name)

    if not signal:
        logger.error("信号生成失败")
        return False

    all_signals = [signal]

    # 保存快照
    save_signal_snapshot(signal)

    # 打印信号摘要
    logger.info(
        f"信号: {signal.signal.value} | "
        f"评分: {signal.total_score:.0f} | "
        f"市场: {signal.regime.value} | "
        f"策略: {signal.mode.value}"
    )

    # ── 4. 推送 ──
    if dry_run:
        logger.info("[DRY RUN] 跳过推送，仅打印信号")
        print(engine.format_signal(signal))
    else:
        pusher = QuantPusher()

        # 4a. 紧急信号 → 微信
        if signal.signal in ACTIONABLE_SIGNALS:
            logger.info(f"🚨 可操作信号，推送微信...")
            result = pusher.push_signal(signal)
            if result.get("wechat"):
                logger.info("微信推送成功")
            else:
                logger.warning("微信推送失败或被跳过")
        else:
            logger.info(f"信号 {signal.signal.value} 非紧急，跳过微信推送")

        # 4b. 每日总结 → 邮件
        position_text = tracker.get_status_text()
        risk_stats = risk.get_stats()
        pusher.push_daily_summary(all_signals, position_text, risk_stats)

    # ── 5. 保存状态 ──
    engine.save_state()

    logger.info("=" * 50)
    logger.info("  量化跟投 · 每日管线完成")
    logger.info("=" * 50)

    return True


# ═══════════════════════════════════════════════════════════════
# CLI 入口（--daily-run 调用）
# ═══════════════════════════════════════════════════════════════

def main(argv: list = None):
    parser = argparse.ArgumentParser(
        prog="quant-daily-run",
        description="量化跟投 · 每日自动化管线",
    )
    parser.add_argument("--dry-run", action="store_true",
                        help="仅分析不推送")
    parser.add_argument("--channels", type=str, default=None,
                        help="推送通道 (逗号分隔: wechat,email)")
    parser.add_argument("--capital", type=float, default=20000,
                        help="总资金 (默认20000)")
    args = parser.parse_args(argv)

    channels = None
    if args.channels:
        channels = [c.strip() for c in args.channels.split(",")]

    success = run_daily(channels=channels, dry_run=args.dry_run,
                        capital=args.capital)
    if not success:
        sys.exit(1)


if __name__ == "__main__":
    main()
