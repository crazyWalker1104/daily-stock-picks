"""格式化模块 — 将推荐报告转换为多种输出格式"""

from datetime import datetime
from typing import List

from src.models import Recommendation, DailyReport


def format_markdown(report: DailyReport) -> str:
    """生成Markdown格式报告（用于邮件和GitHub Pages）"""
    date_str = report.date
    weekday = get_weekday_cn(report.date)

    lines = [
        f"# 📊 每日A股速递 | {date_str} {weekday}",
        "",
        f"> 🤖 AI综合分析 | 采集 {report.raw_news_count} 条信息 | 来源：{'、'.join(report.sources_used)}",
        "",
        "---",
        "",
    ]

    if not report.recommendations:
        lines.append("⚠️ **今日暂无推荐** — 可能原因：信息源异常或AI服务不可用，请稍后重试。")
    else:
        for i, rec in enumerate(report.recommendations, 1):
            emoji = {"高": "🔥", "中": "📈", "低": "📌"}.get(rec.confidence, "📌")

            lines.append(f"## {i}. {emoji} {rec.sector} — 信心度：{rec.confidence}")
            lines.append("")

            if rec.stocks:
                stocks_str = "、".join([
                    f"{s.get('name', '?')}（{s.get('code', '??????')}）"
                    for s in rec.stocks
                ])
                lines.append(f"**标的关注**：{stocks_str}")
                lines.append("")

            lines.append(f"**推荐逻辑**：{rec.logic}")
            lines.append("")
            lines.append(f"**催化事件**：{rec.catalyst}")
            lines.append("")
            lines.append(f"**风险提示**：{rec.risk}")
            lines.append("")
            lines.append("---")
            lines.append("")

    # 页脚
    lines.append(f"> ⚠️ 免责声明：以上内容由AI自动生成，仅供学习参考，不构成投资建议。投资有风险，入市需谨慎。")
    lines.append(f"> 生成时间：{report.generated_at}")

    return "\n".join(lines)


def format_plain(report: DailyReport) -> str:
    """生成纯文本格式（用于CLI输出）"""
    date_str = report.date
    weekday = get_weekday_cn(report.date)

    lines = [
        f"📊 每日A股速递 | {date_str} {weekday}",
        f"─── 采集 {report.raw_news_count} 条信息 | {'、'.join(report.sources_used)}",
        "",
    ]

    if not report.recommendations:
        lines.append("⚠️ 今日暂无推荐")
    else:
        for i, rec in enumerate(report.recommendations, 1):
            emoji = {"高": "🔥", "中": "📈", "低": "📌"}.get(rec.confidence, "📌")
            lines.append(f"{emoji} {rec.sector} [信心:{rec.confidence}]")

            if rec.stocks:
                stocks_str = "、".join([
                    f"{s.get('name', '?')}({s.get('code', '??????')})"
                    for s in rec.stocks
                ])
                lines.append(f"   标的: {stocks_str}")

            lines.append(f"   逻辑: {rec.logic[:80]}")
            lines.append(f"   催化: {rec.catalyst[:60]}")
            lines.append(f"   风险: {rec.risk[:60]}")
            lines.append("")

    lines.append(f"─── {report.generated_at[:19]}")
    lines.append("⚠️ AI生成，仅供参考，不构成投资建议")
    return "\n".join(lines)


def format_html_page(report: DailyReport, history_dates: List[str] = None) -> str:
    """生成完整HTML页面（用于GitHub Pages）"""
    md_body = format_markdown(report)
    md_body_html = _markdown_to_html(md_body)

    # 历史日期导航
    nav_html = ""
    if history_dates:
        nav_items = []
        for d in sorted(history_dates, reverse=True)[:30]:
            active = ' class="active"' if d == report.date else ""
            nav_items.append(f'<li{active}><a href="{d}.html">{d}</a></li>')
        nav_html = "\n".join(nav_items)

    return f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>每日A股速递 | {report.date}</title>
    <style>
        body {{ font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif; max-width: 800px; margin: 0 auto; padding: 20px; background: #f5f5f5; }}
        .container {{ background: white; padding: 30px; border-radius: 12px; box-shadow: 0 2px 10px rgba(0,0,0,0.1); }}
        h1 {{ color: #1a1a1a; border-bottom: 3px solid #d4380d; padding-bottom: 10px; }}
        h2 {{ color: #333; margin-top: 30px; }}
        blockquote {{ background: #fff7e6; padding: 10px 15px; border-left: 4px solid #fa8c16; }}
        nav {{ margin-bottom: 20px; }}
        nav ul {{ list-style: none; padding: 0; display: flex; flex-wrap: wrap; gap: 8px; }}
        nav li {{ }}
        nav a {{ padding: 5px 12px; background: #e6f7ff; border-radius: 4px; text-decoration: none; color: #1890ff; }}
        nav a:hover, nav a.active {{ background: #1890ff; color: white; }}
        .disclaimer {{ color: #999; font-size: 0.9em; margin-top: 40px; padding-top: 20px; border-top: 1px solid #eee; }}
    </style>
</head>
<body>
    <nav>
        <h3>📅 历史报告</h3>
        <ul>{nav_html}</ul>
    </nav>
    <div class="container">
        {md_body_html}
    </div>
</body>
</html>"""


def get_weekday_cn(date_str: str) -> str:
    """获取中文星期"""
    try:
        dt = datetime.strptime(date_str, "%Y-%m-%d")
        weekdays = ["周一", "周二", "周三", "周四", "周五", "周六", "周日"]
        return weekdays[dt.weekday()]
    except Exception:
        return ""


def _markdown_to_html(md: str) -> str:
    """简单的Markdown到HTML转换（仅处理常用语法）"""
    import re

    html = md

    # 标题
    html = re.sub(r'^### (.*)', r'<h3>\1</h3>', html, flags=re.MULTILINE)
    html = re.sub(r'^## (.*)', r'<h2>\1</h2>', html, flags=re.MULTILINE)
    html = re.sub(r'^# (.*)', r'<h1>\1</h1>', html, flags=re.MULTILINE)

    # 加粗
    html = re.sub(r'\*\*(.*?)\*\*', r'<strong>\1</strong>', html)

    # 引用
    html = re.sub(r'^> (.*)', r'<blockquote>\1</blockquote>', html, flags=re.MULTILINE)

    # 水平线
    html = html.replace('---', '<hr>')

    # 换行
    html = html.replace('\n\n', '<br><br>')
    html = html.replace('\n', '<br>')

    return html
