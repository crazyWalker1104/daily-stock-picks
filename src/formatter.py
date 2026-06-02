"""格式化模块 — 将推荐报告转换为多种输出格式"""

from datetime import datetime
from typing import List

from src.models import Recommendation, DailyReport
from src.tracker import format_tracking_section, format_tracking_plain


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

    # 双重确认引擎验证摘要（Phase 2.1）
    if hasattr(report, "confirmation_summary") and report.confirmation_summary:
        lines.append(report.confirmation_summary)
        lines.append("")

    # 昨日推荐回顾
    tracking_text = format_tracking_section(report.tracking)
    if tracking_text:
        lines.append(tracking_text)
        lines.append("")

    # 页脚
    lines.append(f"> ⚠️ 免责声明：以上内容由AI自动生成，仅供学习参考，不构成投资建议。投资有风险，入市需谨慎。")
    lines.append(f"> 生成时间：{report.generated_at}")

    return "\n".join(lines)


def format_email_html(report: DailyReport) -> str:
    """生成精美的HTML邮件模板（方案A：现代卡片风）"""

    # 信心度配色
    CONF_COLORS = {
        "高": {"border": "#d4380d", "bg": "#fff2f0", "badge": "#d4380d", "icon": "🔥"},
        "中": {"border": "#d48806", "bg": "#fffbe6", "badge": "#d48806", "icon": "📈"},
        "低": {"border": "#8c8c8c", "bg": "#fafafa", "badge": "#8c8c8c", "icon": "📌"},
    }

    # 生成推荐卡片
    cards_html = ""
    for i, rec in enumerate(report.recommendations, 1):
        colors = CONF_COLORS.get(rec.confidence, CONF_COLORS["低"])

        # 标的列表
        stocks_items = ""
        if rec.stocks:
            for s in rec.stocks:
                name = s.get('name', '?')
                code = s.get('code', '??????')
                stocks_items += f"""
                <span style="display:inline-block;background:{colors['bg']};color:{colors['badge']};
                    padding:3px 10px;margin:2px 4px;border-radius:3px;font-size:13px;font-weight:600;
                    border:1px solid {colors['border']}33;">
                    {name}<span style="color:#999;font-weight:400;">（{code}）</span>
                </span>"""

        cards_html += f"""
        <!-- 推荐卡片 {i} -->
        <table width="100%" cellpadding="0" cellspacing="0" border="0"
            style="background:#fff;border-radius:8px;margin-bottom:16px;
            box-shadow:0 2px 8px rgba(0,0,0,0.06);border-left:4px solid {colors['border']};">
            <tr>
                <td style="padding:20px 24px;">
                    <!-- 标题行 -->
                    <table width="100%" cellpadding="0" cellspacing="0" border="0">
                        <tr>
                            <td style="font-size:18px;font-weight:700;color:#1a1a1a;padding-bottom:4px;">
                                {colors['icon']} {rec.sector}
                            </td>
                            <td align="right">
                                <span style="display:inline-block;background:{colors['badge']};color:#fff;
                                    padding:4px 12px;border-radius:12px;font-size:12px;font-weight:600;letter-spacing:1px;">
                                    信心 {rec.confidence}
                                </span>
                            </td>
                        </tr>
                    </table>

                    <!-- 标的 -->
                    <div style="margin:12px 0 8px;">
                        <span style="color:#666;font-size:13px;">📌 标的关注：</span>
                        {stocks_items}
                    </div>

                    <!-- 三项要点 -->
                    <table width="100%" cellpadding="0" cellspacing="0" border="0" style="margin-top:12px;">
                        <tr>
                            <td width="33%" valign="top" style="padding:10px 12px;background:#f9fafb;border-radius:6px;">
                                <div style="font-size:12px;color:#999;margin-bottom:4px;">💡 推荐逻辑</div>
                                <div style="font-size:14px;color:#333;line-height:1.6;">{rec.logic}</div>
                            </td>
                            <td width="8">&nbsp;</td>
                            <td width="33%" valign="top" style="padding:10px 12px;background:#f9fafb;border-radius:6px;">
                                <div style="font-size:12px;color:#999;margin-bottom:4px;">⚡ 催化事件</div>
                                <div style="font-size:14px;color:#333;line-height:1.6;">{rec.catalyst}</div>
                            </td>
                            <td width="8">&nbsp;</td>
                            <td width="33%" valign="top" style="padding:10px 12px;background:#fff2f0;border-radius:6px;">
                                <div style="font-size:12px;color:#999;margin-bottom:4px;">⚠️ 风险提示</div>
                                <div style="font-size:14px;color:#d4380d;line-height:1.6;">{rec.risk}</div>
                            </td>
                        </tr>
                    </table>
                </td>
            </tr>
        </table>"""

    # 双重确认引擎验证摘要（Phase 2.1）
    confirmation_html = ""
    if hasattr(report, "confirmation_summary") and report.confirmation_summary:
        # 将 Markdown 格式的确认摘要转简单 HTML
        conf_lines = report.confirmation_summary.strip().split("\n")
        conf_body = ""
        for line in conf_lines:
            if line.startswith("## "):
                conf_body += f'<div style="font-size:16px;font-weight:700;color:#1a1a1a;margin-bottom:12px;">{line[3:]}</div>'
            elif line.startswith("**"):
                conf_body += f'<p style="font-size:14px;color:#333;margin:8px 0;">{line}</p>'
            elif line.strip().startswith(("🟢", "🔴", "⚠️", "❓")):
                conf_body += f'<p style="font-size:14px;color:#555;margin:4px 0 4px 16px;">{line.strip()}</p>'
            elif line.strip():
                conf_body += f'<p style="font-size:14px;color:#666;margin:4px 0;">{line.strip()}</p>'

        confirmation_html = f"""
        <!-- 双重确认引擎验证 -->
        <table width="100%" cellpadding="0" cellspacing="0" border="0"
            style="background:#f6ffed;border-radius:8px;margin-top:16px;margin-bottom:16px;
            border:1px solid #b7eb8f;box-shadow:0 2px 8px rgba(0,0,0,0.04);">
            <tr>
                <td style="padding:20px 24px;">
                    {conf_body}
                </td>
            </tr>
        </table>"""

    # 昨日推荐回顾区块（HTML）
    tracking_html = ""
    if report.tracking and report.tracking.get("stocks"):
        t = report.tracking
        t_rows = ""
        for s in t["stocks"]:
            t_emoji = "✅" if s.get("hit") else ("❌" if s.get("change_pct") is not None else "➖")
            t_perf = f"{s['change_pct']:+.2f}%" if s.get("change_pct") is not None else "—"
            t_color = "#cf1322" if (s.get("change_pct") or 0) > 0 else ("#d4380d" if (s.get("change_pct") or 0) <= 0 else "#999")
            t_rows += f"""
                    <tr style="border-bottom:1px solid #f0f0f0;">
                        <td style="padding:8px 12px;font-size:13px;">{t_emoji}</td>
                        <td style="padding:8px 12px;font-size:13px;font-weight:600;">{s['name']}<span style="color:#999;font-weight:400;">（{s['code']}）</span></td>
                        <td style="padding:8px 12px;font-size:13px;color:#666;">{s['sector']}</td>
                        <td style="padding:8px 12px;font-size:13px;color:#666;">{s['confidence']}</td>
                        <td style="padding:8px 12px;font-size:13px;color:{t_color};font-weight:600;">{t_perf}</td>
                    </tr>"""

        tracking_html = f"""
        <!-- 昨日推荐回顾 -->
        <table width="100%" cellpadding="0" cellspacing="0" border="0"
            style="background:#fff;border-radius:8px;margin-top:16px;margin-bottom:16px;
            box-shadow:0 2px 8px rgba(0,0,0,0.06);">
            <tr>
                <td style="padding:20px 24px;">
                    <div style="font-size:16px;font-weight:700;color:#1a1a1a;margin-bottom:12px;">
                        📊 昨日推荐回顾 ({t['prev_date']})
                    </div>
                    <div style="font-size:13px;color:#666;margin-bottom:12px;">
                        胜率 <strong>{t['hit_rate']:.0%}</strong> &nbsp;|&nbsp;
                        均收益 <strong style="color:{'#cf1322' if t['avg_return'] > 0 else '#d4380d'};">{t['avg_return']:+.2f}%</strong> &nbsp;|&nbsp;
                        {t['hit_count']}涨 / {t['miss_count']}跌
                    </div>
                    <table width="100%" cellpadding="0" cellspacing="0" border="0">
                        <tr style="background:#fafafa;">
                            <th style="padding:8px 12px;text-align:left;font-size:12px;color:#999;"></th>
                            <th style="padding:8px 12px;text-align:left;font-size:12px;color:#999;">标的</th>
                            <th style="padding:8px 12px;text-align:left;font-size:12px;color:#999;">板块</th>
                            <th style="padding:8px 12px;text-align:left;font-size:12px;color:#999;">信心</th>
                            <th style="padding:8px 12px;text-align:left;font-size:12px;color:#999;">今日表现</th>
                        </tr>
                        {t_rows}
                    </table>
                </td>
            </tr>
        </table>"""

    # 空推荐处理
    if not report.recommendations:
        cards_html = """
        <div style="text-align:center;padding:40px 20px;color:#999;">
            <div style="font-size:48px;margin-bottom:16px;">📭</div>
            <div style="font-size:16px;">今日暂无推荐</div>
            <div style="font-size:13px;margin-top:8px;">可能原因：信息源异常或AI服务不可用，请稍后重试</div>
        </div>"""

    # 来源标签
    sources_tags = "".join([
        f'<span style="display:inline-block;background:rgba(255,255,255,0.2);padding:3px 10px;'
        f'margin:0 4px;border-radius:3px;font-size:12px;">{s}</span>'
        for s in report.sources_used
    ])

    # 拼装完整邮件
    html = f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
</head>
<body style="margin:0;padding:0;background:#f5f5f5;font-family:-apple-system,BlinkMacSystemFont,'Segoe UI','PingFang SC','Microsoft YaHei',sans-serif;">

    <!-- 外层容器 -->
    <table width="100%" cellpadding="0" cellspacing="0" border="0" style="background:#f5f5f5;">
        <tr>
            <td align="center" style="padding:20px 16px;">

                <!-- 内容区 600px -->
                <table width="600" cellpadding="0" cellspacing="0" border="0"
                    style="max-width:600px;width:100%;">

                    <!-- 头部 -->
                    <tr>
                        <td style="background:linear-gradient(135deg,#1a1a2e 0%,#16213e 50%,#0f3460 100%);
                            background-color:#1a1a2e;border-radius:12px 12px 0 0;padding:32px 28px 24px;">
                            <div style="font-size:24px;font-weight:700;color:#fff;margin-bottom:4px;">
                                📊 每日A股速递
                            </div>
                            <div style="font-size:15px;color:rgba(255,255,255,0.85);margin-bottom:12px;">
                                {report.date} · {get_weekday_cn(report.date)}
                            </div>
                            <div style="font-size:13px;color:rgba(255,255,255,0.65);">
                                🤖 AI综合分析 | 采集 {report.raw_news_count} 条信息 | 来源 {sources_tags}
                            </div>
                        </td>
                    </tr>

                    <!-- 主体 -->
                    <tr>
                        <td style="background:#fff;padding:24px 20px;">
                            {cards_html}
                            {confirmation_html}
                            {tracking_html}
                        </td>
                    </tr>

                    <!-- 页脚 -->
                    <tr>
                        <td style="background:#fafafa;border-radius:0 0 12px 12px;
                            padding:20px 28px;border-top:1px solid #eee;">
                            <div style="font-size:13px;color:#999;line-height:1.8;">
                                ⚠️ <strong>免责声明</strong>：以上内容由AI自动生成，仅供学习参考和技术交流，
                                <span style="color:#d4380d;">不构成任何投资建议</span>。
                                股市有风险，投资需谨慎。请勿据此进行交易决策。
                            </div>
                            <div style="font-size:12px;color:#bbb;margin-top:8px;">
                                生成时间：{report.generated_at[:19]}
                            </div>
                        </td>
                    </tr>

                </table>

                <!-- 底部署名 -->
                <div style="margin-top:16px;font-size:12px;color:#ccc;text-align:center;">
                    每日A股智能推荐系统 · Powered by DeepSeek AI
                </div>

            </td>
        </tr>
    </table>

</body>
</html>"""

    return html


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

    # 双重确认引擎验证摘要（Phase 2.1）
    if hasattr(report, "confirmation_summary") and report.confirmation_summary:
        lines.append(report.confirmation_summary)
        lines.append("")

    # 昨日推荐回顾
    tracking_text = format_tracking_plain(report.tracking)
    if tracking_text:
        lines.append(tracking_text)

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
