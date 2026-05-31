"""每日A股智能推荐系统 — 主入口"""

import os
import sys
import json
import logging
import argparse
from datetime import datetime

# Windows终端UTF-8兼容
if sys.platform == "win32":
    import io
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")

from dotenv import load_dotenv
import yaml

from src.scrapers import collect_all_news
from src.aggregator import aggregate
from src.ai_analyzer import AIAnalyzer
from src.pusher import Pusher

# 日志配置
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger("main")


def load_config() -> dict:
    """加载配置"""
    config_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), "config", "config.yaml")
    if os.path.exists(config_path):
        with open(config_path, "r", encoding="utf-8") as f:
            return yaml.safe_load(f)

    logger.warning(f"配置文件不存在: {config_path}，使用默认配置")
    return {
        "sources": {"cls": False, "eastmoney": True, "sina": True, "xueqiu": False},
        "push": {"email": {"enabled": True}, "wechat": {"enabled": False}, "cli": {"enabled": True}, "web": {"enabled": True}},
        "ai": {"provider": "deepseek", "model": "deepseek-chat", "temperature": 0.3, "max_tokens": 2000},
        "scraper": {"request_delay": 2, "timeout": 15, "max_retries": 3},
        "output": {"max_recommendations": 5, "save_raw_data": True},
    }


def run(date: str = None, dry_run: bool = False) -> dict:
    """主流程：采集 → 聚合 → AI分析 → 推送"""
    if date is None:
        date = datetime.now().strftime("%Y-%m-%d")

    logger.info(f"===== 每日A股推荐系统启动 | {date} =====")

    # 加载配置
    load_dotenv()
    config = load_config()

    # Phase 1: 数据采集
    logger.info("Phase 1: 数据采集...")
    all_news = collect_all_news(config)

    if not all_news:
        logger.warning("未采集到任何新闻，检查网络或信息源配置")
        return {"status": "no_data", "news_count": 0}

    # 保存原始数据
    if config.get("output", {}).get("save_raw_data", True):
        raw_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), "data", f"{date}_raw.json")
        os.makedirs(os.path.dirname(raw_path), exist_ok=True)
        with open(raw_path, "w", encoding="utf-8") as f:
            json.dump([n.to_dict() for n in all_news], f, ensure_ascii=False, indent=2)
        logger.info(f"原始数据已保存: {raw_path}")

    # Phase 2: 聚合 + AI分析
    logger.info("Phase 2: AI分析...")
    news_text = aggregate(all_news, max_for_ai=40)
    analyzer = AIAnalyzer(config)
    report = analyzer.analyze(news_text, date)

    # 保存报告JSON
    report_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), "output", f"{date}_report.json")
    os.makedirs(os.path.dirname(report_path), exist_ok=True)
    with open(report_path, "w", encoding="utf-8") as f:
        json.dump(report.to_dict(), f, ensure_ascii=False, indent=2)

    # Phase 3: 推送
    if dry_run:
        logger.info("Phase 3: 干运行模式 — 跳过推送")
        from src.formatter import format_plain
        try:
            print(format_plain(report))
        except UnicodeEncodeError:
            # Windows GBK终端降级：替换emoji为ASCII
            text = format_plain(report)
            import re
            text = re.sub(r'[^\x00-\x7f一-鿿＀-￯\n\r]', '?', text)
            print(text)
    else:
        logger.info("Phase 3: 推送分发...")
        pusher = Pusher(config)
        results = pusher.push(report)

        # CLI输出
        cli_output = results.get("cli", "")
        if cli_output:
            print(cli_output)

        logger.info(f"推送结果: email={results.get('email')}, web={bool(results.get('web'))}")

    # 汇总
    rec_count = len(report.recommendations)
    logger.info(f"===== 完成: 采集{len(all_news)}条 → AI推荐{rec_count}条 =====")

    return {
        "status": "success",
        "news_count": len(all_news),
        "recommendations": rec_count,
        "date": date,
    }


def main():
    parser = argparse.ArgumentParser(description="每日A股智能推荐系统")
    parser.add_argument("--date", type=str, default=None, help="指定日期 (YYYY-MM-DD)，默认今天")
    parser.add_argument("--dry-run", action="store_true", help="干运行模式（不推送）")
    parser.add_argument("--local", action="store_true", help="本地模式（同--dry-run，仅CLI输出）")
    parser.add_argument("--scrape-only", action="store_true", help="仅测试采集（不分析）")
    args = parser.parse_args()

    if args.scrape_only:
        # 仅测试爬虫
        load_dotenv()
        config = load_config()
        news = collect_all_news(config)
        print(f"\n采集到 {len(news)} 条新闻:")
        for n in news[:10]:
            print(f"  [{n.source}] {n.title[:80]}")
        return

    dry_run = args.dry_run or args.local
    result = run(date=args.date, dry_run=dry_run)

    if result["status"] == "no_data":
        sys.exit(1)


if __name__ == "__main__":
    main()
