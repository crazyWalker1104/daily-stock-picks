"""量化跟投模块 — CLI 入口

用法:
  python -m src.quant --pick              从推荐池筛选候选标的
  python -m src.quant --symbol 000001     生成今日信号
  python -m src.quant --status            查看当前持仓+浮动盈亏
  python -m src.quant --backtest 000001   历史回测
  python -m src.quant --watch             进入每日跟踪模式
  python -m src.quant --daily-run         自动化日终管线（信号+推送）
  python -m src.quant --execute           模拟执行信号（更新持仓状态）
"""

import argparse
import logging
import os
import sys

# 编码兼容（Windows GBK）
try:
    sys.stdout.reconfigure(encoding='utf-8')
except Exception:
    pass

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(name)s: %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S',
)
logger = logging.getLogger("quant.cli")


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m src.quant",
        description="量化跟投模块 — 单标的深度跟踪 + 买卖信号推送",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
示例:
  python -m src.quant --pick              # 选股：从推荐池筛选Top3候选
  python -m src.quant --symbol 000001     # 信号：对指定标的全流程分析
  python -m src.quant --status            # 状态：查看持仓+浮动盈亏
  python -m src.quant --backtest 000001   # 回测：历史策略验证
  python -m src.quant --execute           # 执行：根据最新信号更新持仓
        """,
    )

    # 互斥的主要动作组
    action_group = parser.add_mutually_exclusive_group()
    action_group.add_argument("--pick", dest="action", action="store_const",
                              const="pick", help="从推荐池筛选候选标的")
    action_group.add_argument("--status", dest="action", action="store_const",
                              const="status", help="查看当前持仓状态")
    action_group.add_argument("--execute", dest="action", action="store_const",
                              const="execute", help="模拟执行当前信号")
    action_group.add_argument("--backtest", dest="backtest_symbol",
                              metavar="CODE", help="历史回测 (指定代码)")
    action_group.add_argument("--watch", dest="action", action="store_const",
                              const="watch", help="每日跟踪模式")
    action_group.add_argument("--daily-run", dest="action", action="store_const",
                              const="daily_run", help="自动化日终管线（信号+推送）")

    # 参数
    parser.add_argument("--symbol", dest="symbol", metavar="CODE",
                        help="股票代码 (6位)")
    parser.add_argument("--name", dest="name", metavar="NAME",
                        help="股票名称（可选，自动获取）")
    parser.add_argument("--capital", dest="capital", type=float,
                        default=20000, help="总资金 (默认20000)")
    parser.add_argument("--start", dest="start_date", metavar="DATE",
                        help="回测开始日期")
    parser.add_argument("--end", dest="end_date", metavar="DATE",
                        help="回测结束日期")
    parser.add_argument("--dry-run", dest="dry_run", action="store_true",
                        help="干运行（仅分析不推送）")
    parser.add_argument("--channels", dest="channels", metavar="CHANNELS",
                        help="推送通道 (逗号分隔: wechat,email)")
    parser.add_argument("--verbose", "-v", dest="verbose", action="store_true",
                        help="显示因子评分明细")

    parser.set_defaults(action=None)
    return parser


# ═══════════════════════════════════════════════════════════════
# 主入口
# ═══════════════════════════════════════════════════════════════

def main(argv: list = None):
    parser = _build_parser()
    args = parser.parse_args(argv)

    from src.quant.engine import QuantEngine
    from src.quant.backtest import backtest, format_backtest
    from src.quant.stock_picker import pick_candidates, format_candidates
    from src.quant.tracker import load_signal_snapshot

    engine = QuantEngine(total_capital=args.capital)
    engine.load_state()

    # ── 选股 ──
    if args.action == "pick":
        print("\n🔍 正在从推荐数据库中筛选候选标的...\n")
        candidates = engine.pick_stocks()
        if not candidates:
            print("📭 暂无可选标的（数据库为空或无近期记录）")
            print("   提示：先运行 python -m src.main 生成推荐数据")
        else:
            print(format_candidates(candidates))

    # ── 信号分析 ──
    elif args.symbol:
        print(f"\n📊 正在分析 {args.symbol}...")
        signal = engine.analyze(
            symbol=args.symbol,
            symbol_name=args.name or "",
        )

        if signal:
            print()
            print(engine.format_signal(signal, verbose=args.verbose))

            # 风控检查
            pos = engine.tracker.position
            if pos:
                allowed, reason = engine.risk.can_trade(pos, signal.signal)
                if not allowed:
                    print(f"\n⚠️ 风控拦截: {reason}")
            print()
        else:
            print("❌ 分析失败，请检查股票代码和网络连接")

    # ── 回测 ──
    elif args.backtest_symbol:
        print(f"\n📈 正在回测 {args.backtest_symbol}...")
        result = backtest(
            symbol=args.backtest_symbol,
            symbol_name=args.name or "",
            start_date=args.start_date or "",
            end_date=args.end_date or "",
            initial_capital=args.capital,
        )

        if result:
            print()
            print(format_backtest(result))
        else:
            print("❌ 回测失败，请检查股票代码或K线数据")

    # ── 状态 ──
    elif args.action == "status":
        print()
        print(engine.status_text())

    # ── 执行信号 ──
    elif args.action == "execute":
        # 加载最近一次信号
        from datetime import datetime
        today = datetime.now().strftime("%Y-%m-%d")
        snapshot = load_signal_snapshot(today)

        if not engine.current_signal and snapshot:
            from src.quant.models import QuantSignal, SignalType, MarketRegime, StrategyMode
            engine.current_signal = QuantSignal(
                symbol=snapshot.get("symbol", ""),
                symbol_name=snapshot.get("symbol_name", ""),
                date=snapshot.get("date", ""),
                signal=SignalType(snapshot.get("signal", "wait")),
                regime=MarketRegime(snapshot.get("regime", "transition")),
                mode=StrategyMode(snapshot.get("mode", "defensive")),
                total_score=snapshot.get("total_score", 0),
                current_price=snapshot.get("current_price", 0),
                stop_loss=snapshot.get("stop_loss", 0),
                take_profit=snapshot.get("take_profit", 0),
            )

        if not engine.current_signal:
            print("❌ 无当前信号，请先运行: python -m src.quant --symbol <代码>")
            return

        success, msg = engine.execute_signal()
        print(f"\n{msg}")

    # ── 每日跟踪模式 ──
    elif args.action == "watch":
        # 加载观察列表
        from src.quant.tracker import load_watchlist
        watchlist = load_watchlist()

        if not watchlist.get("symbol"):
            print("📭 尚未选择跟踪标的")
            print("   请先运行选股: python -m src.quant --pick")
            print("   或直接指定:  python -m src.quant --symbol <代码>")
            return

        symbol = watchlist["symbol"]
        name = watchlist.get("name", symbol)

        print(f"\n👁️ 开始跟踪: {name}（{symbol}）\n")
        signal = engine.analyze(symbol=symbol, symbol_name=name)

        if signal:
            print(engine.format_signal(signal, verbose=args.verbose))
            print()
            print(engine.status_text())

            # 如果有信号需要操作，提示
            if signal.signal.value in ("open", "add", "reduce", "close"):
                print(f"\n{'='*60}")
                print(f"⚠️ 触发操作信号: {signal.action_text}")
                print(f"   如需模拟执行: python -m src.quant --execute")
                print(f"{'='*60}")
        else:
            print("❌ 跟踪失败")

    # ── 自动化日终管线 ──
    elif args.action == "daily_run":
        from src.quant.daily_runner import run_daily
        channels = None
        if args.channels:
            channels = [c.strip() for c in args.channels.split(",")]
        success = run_daily(channels=channels, dry_run=args.dry_run,
                            capital=args.capital)
        if not success:
            print("❌ 日终管线执行失败")
            sys.exit(1)

    # ── 默认帮助 ──
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
