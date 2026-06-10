"""格式化模块 — 将推荐报告转换为多种输出格式

v2.0 重新设计：清晰的视觉层次、评分可视化、专业的财经简报风格
"""

from datetime import datetime
from typing import List

from src.models import Recommendation, DailyReport
from src.tracker import format_tracking_section, format_tracking_plain


# ═══════════════════════════════════════════════════════════════
# 通用工具
# ═══════════════════════════════════════════════════════════════

CONFIDENCE_EMOJI = {"高": "🔥", "中": "📈", "低": "📌"}
CONFIDENCE_COLOR = {"高": "#d4380d", "中": "#d48806", "低": "#8c8c8c"}
CONFIDENCE_BG = {"高": "#fff2f0", "中": "#fffbe6", "低": "#fafafa"}

STRATEGY_EMOJI = {"追强": "🚀", "抄底": "🎯", "事件驱动": "⚡", "观望": "👀"}
STRATEGY_COLOR = {"追强": "#cf1322", "抄底": "#237804", "事件驱动": "#2f54eb", "观望": "#8c8c8c"}
STRATEGY_BG = {"追强": "#fff2f0", "抄底": "#f6ffed", "事件驱动": "#f0f5ff", "观望": "#fafafa"}

SCORE_COLORS = [
    (40, "#d4380d"),   # 0-40: 红色 — 弱
    (60, "#fa8c16"),   # 40-60: 橙色 — 一般
    (75, "#52c41a"),   # 60-75: 浅绿 — 良好
    (90, "#237804"),   # 75-90: 绿色 — 优秀
    (100, "#092b00"),  # 90-100: 深绿 — 卓越
]


def _score_color(score: int) -> str:
    """评分 → 颜色"""
    for threshold, color in SCORE_COLORS:
        if score <= threshold:
            return color
    return "#092b00"


def _score_bar(score: int, width: int = 12) -> str:
    """0-100分 → 可视化字符条 (CLI用)"""
    filled = int(score / 100 * width)
    if score >= 80:
        bar = "█" * filled + "░" * (width - filled)
    elif score >= 60:
        bar = "▓" * filled + "░" * (width - filled)
    else:
        bar = "▒" * filled + "░" * (width - filled)
    return bar


def _ma_status_icon(status: str) -> str:
    """均线状态 → 图标"""
    return {
        "bullish_aligned": "🚀",
        "above_ma20": "✅",
        "below_ma20": "⚠️",
    }.get(status, "")


def _ma_status_short(status: str) -> str:
    """均线状态 → 简短中文"""
    return {
        "bullish_aligned": "多头排列",
        "above_ma20": "MA20之上",
        "below_ma20": "MA20之下",
    }.get(status, "—")


def get_weekday_cn(date_str: str) -> str:
    """获取中文星期"""
    try:
        dt = datetime.strptime(date_str, "%Y-%m-%d")
        return ["周一", "周二", "周三", "周四", "周五", "周六", "周日"][dt.weekday()]
    except Exception:
        return ""


# ═══════════════════════════════════════════════════════════════
# 1. CLI / 纯文本格式
# ═══════════════════════════════════════════════════════════════

def format_plain(report: DailyReport) -> str:
    """生成纯文本格式（CLI 终端输出）

    采用分隔线 + 标签缩进布局，突出信息层次。
    """
    W = _width()
    date_str = report.date
    weekday = get_weekday_cn(report.date)

    lines = []
    lines.append("")
    lines.append("╔" + "═" * (W - 2) + "╗")
    lines.append(_center(f"📊  每日A股速递  ·  {date_str} {weekday}", W))
    lines.append(_center(
        f"🤖 AI综合研判  |  {report.raw_news_count}条信息  |  {', '.join(report.sources_used)}",
        W
    ))
    lines.append("╚" + "═" * (W - 2) + "╝")
    lines.append("")

    if not report.recommendations:
        lines.append(_center("⚠️  今日暂无推荐", W))
        lines.append("")
    else:
        for i, rec in enumerate(report.recommendations, 1):
            emoji = CONFIDENCE_EMOJI.get(rec.confidence, "📌")
            strategy_label = ""
            if hasattr(rec, "strategy") and rec.strategy and rec.strategy != "观望":
                se = STRATEGY_EMOJI.get(rec.strategy, "")
                strategy_label = f"  [{se} {rec.strategy}]"
            lines.append(f"  {emoji}  {rec.sector}{strategy_label}                         [信心: {rec.confidence}]")
            lines.append("  " + "─" * (W - 4))

            # 标的标签
            if rec.stocks:
                stock_tags = "  ·  ".join(
                    f"{s.get('name', '?')}({s.get('code', '??????')})"
                    for s in rec.stocks
                )
                lines.append(f"  标的  {stock_tags}")

            lines.append(f"  💡 逻辑  {rec.logic}")
            lines.append(f"  ⚡ 催化  {rec.catalyst}")
            lines.append(f"  ⚠️  风险  {rec.risk}")

            # 技术评分（若有）
            if hasattr(rec, "technical") and rec.technical:
                tr = rec.technical
                lines.append("")
                lines.append(f"  📊 技术评分")
                for r in tr.get("stock_results", []):
                    if r.get("excluded"):
                        continue
                    bar = _score_bar(r["technical_score"], 14)
                    score = r["technical_score"]
                    # 找 MA 状态
                    ma_status = ""
                    for sig in r["signals"]:
                        if sig.get("type") == "ma_position" and "detail" in sig:
                            ma_status = _ma_status_short(sig["detail"].get("status", ""))
                            break
                    q = r.get("quote", {})
                    cap_str = f"流通{q['circulating_cap_yi']:.0f}亿" if q.get("circulating_cap_yi") else ""
                    chg_str = f"{q['change_pct']:+.1f}%" if q.get("change_pct") is not None else ""
                    lines.append(f"  {r['name']:<6s}  {bar}  {score:<3d}  {ma_status:<6s}  {chg_str}  {cap_str}")

            lines.append("")

    # 确认摘要（精简版）
    if hasattr(report, "confirmation_summary") and report.confirmation_summary:
        lines.append(_render_confirmation_plain(report.confirmation_summary))
        lines.append("")

    # 技术面摘要（精简版）
    if hasattr(report, "technical_summary") and report.technical_summary:
        lines.append(_render_technical_plain(report.technical_summary))
        lines.append("")

    # 策略分层摘要
    if hasattr(report, "strategy_summary") and report.strategy_summary:
        lines.append(f"  📐 策略分布：{report.strategy_summary}")
        lines.append("")

    # 追踪
    tracking_text = format_tracking_plain(report.tracking)
    if tracking_text:
        lines.append("  " + "─" * (W - 4))
        lines.append(tracking_text)

    lines.append("  ⚠️  AI生成 · 仅供参考 · 不构成投资建议")
    lines.append(f"  {report.generated_at[:19]}")
    lines.append("")
    return "\n".join(lines)


def _width() -> int:
    """终端宽度，默认80"""
    import shutil
    try:
        return min(shutil.get_terminal_size().columns, 100)
    except Exception:
        return 80


def _center(text: str, width: int) -> str:
    """居中文本（中文/emoji 宽度近似：CJK占2，其余占1）"""
    visible = 0
    for ch in str(text):
        if '一' <= ch <= '鿿' or '　' <= ch <= '〿' or '＀' <= ch <= '￯':
            visible += 2
        elif ord(ch) > 127:
            visible += 2  # emoji 等 wide chars
        else:
            visible += 1
    if visible >= width - 4:
        return "║ " + text[:width-6] + "... ║"
    left = (width - 2 - visible) // 2
    return "║" + " " * left + text + " " * (width - 2 - visible - left) + "║"


def _render_confirmation_plain(summary: str) -> str:
    """将 Markdown 确认摘要转为 CLI 紧凑格式"""
    lines = summary.strip().split("\n")
    out = []
    for line in lines:
        stripped = line.strip()
        if stripped.startswith("## "):
            out.append(f"  🔍 {stripped[3:].lstrip('🔍 ')}")
        elif stripped.startswith("**资金面"):
            out.append(f"  {stripped.replace('**', '')}")
        elif stripped.startswith("**板块情绪"):
            out.append(f"  {stripped.replace('**', '')}")
        elif stripped.startswith(("🟢", "🔴", "⚠️", "❓", "✅")):
            out.append(f"  {stripped}")
        elif stripped.startswith("→"):
            out.append(f"     {stripped}")
    return "\n".join(out)


def _render_technical_plain(summary: str) -> str:
    """将 Markdown 技术摘要转为 CLI 紧凑格式"""
    lines = summary.strip().split("\n")
    out = []
    for line in lines:
        stripped = line.strip()
        if stripped.startswith("## "):
            out.append(f"  📋 {stripped[3:].lstrip('📋 ')}")
        elif stripped.startswith("**过滤统计"):
            out.append(f"  {stripped.replace('**', '')}")
        elif stripped.startswith("### "):
            out.append(f"  ▸ {stripped[4:]}")
        elif stripped.startswith("- ") and any(x in stripped for x in ["✅", "⚠️", "🚫"]):
            out.append(f"  {stripped}")
    return "\n".join(out)


# ═══════════════════════════════════════════════════════════════
# 2. Markdown 格式
# ═══════════════════════════════════════════════════════════════

def format_markdown(report: DailyReport) -> str:
    """生成 Markdown 格式报告（GitHub/GitHub Pages 用）"""
    date_str = report.date
    weekday = get_weekday_cn(report.date)

    lines = [
        f"# 📊 每日A股速递 | {date_str} {weekday}",
        "",
        f"> 🤖 AI综合分析 | 采集 {report.raw_news_count} 条信息 "
        f"| 来源：{'、'.join(report.sources_used)}",
        "",
        "---",
        "",
    ]

    if not report.recommendations:
        lines.append("⚠️ **今日暂无推荐** — 可能原因：信息源异常或AI服务不可用，请稍后重试。")
    else:
        for i, rec in enumerate(report.recommendations, 1):
            emoji = CONFIDENCE_EMOJI.get(rec.confidence, "📌")
            strategy_label = ""
            if hasattr(rec, "strategy") and rec.strategy and rec.strategy != "观望":
                se = STRATEGY_EMOJI.get(rec.strategy, "")
                strategy_label = f"  |  {se} {rec.strategy}"
            lines.append(f"## {i}. {emoji} {rec.sector} — 信心度：{rec.confidence}{strategy_label}")
            lines.append("")

            if rec.stocks:
                stocks_str = " · ".join(
                    f"**{s.get('name', '?')}**（{s.get('code', '??????')}）"
                    for s in rec.stocks
                )
                lines.append(f"🏷️ 标的关注：{stocks_str}")
                lines.append("")

            # 三列信息
            lines.append(f"| 💡 推荐逻辑 | ⚡ 催化事件 | ⚠️ 风险提示 |")
            lines.append(f"|:---|:---|:---|")
            lines.append(f"| {rec.logic} | {rec.catalyst} | {rec.risk} |")
            lines.append("")

            # 技术评分行（若有）
            if hasattr(rec, "technical") and rec.technical:
                tr = rec.technical
                score_items = []
                for r in tr.get("stock_results", []):
                    if r.get("excluded"):
                        continue
                    score = r["technical_score"]
                    icon = "🟢" if score >= 75 else ("🟡" if score >= 60 else "🔴")
                    ma_status = ""
                    for sig in r["signals"]:
                        if sig.get("type") == "ma_position" and "detail" in sig:
                            ma_status = _ma_status_short(sig["detail"].get("status", ""))
                            break
                    score_items.append(f"{icon} {r['name']} **{score}**分 {ma_status}")
                if score_items:
                    lines.append(f"📊 技术评分：{' · '.join(score_items)}")
                    lines.append("")

            lines.append("---")
            lines.append("")

    # 确认 + 技术 + 追踪
    if hasattr(report, "confirmation_summary") and report.confirmation_summary:
        lines.append(_compact_confirmation_md(report.confirmation_summary))
        lines.append("")

    if hasattr(report, "technical_summary") and report.technical_summary:
        lines.append(_compact_technical_md(report.technical_summary))
        lines.append("")

    if hasattr(report, "strategy_summary") and report.strategy_summary:
        lines.append(f"## 📐 策略分布")
        lines.append("")
        lines.append(f"**{report.strategy_summary}**")
        lines.append("")

    tracking_text = format_tracking_section(report.tracking)
    if tracking_text:
        lines.append(tracking_text)
        lines.append("")

    lines.append(
        "> ⚠️ 免责声明：以上内容由AI自动生成，仅供学习参考，"
        "不构成投资建议。投资有风险，入市需谨慎。"
    )
    lines.append(f"> 生成时间：{report.generated_at}")

    return "\n".join(lines)


def _compact_confirmation_md(summary: str) -> str:
    """精简确认摘要 Markdown"""
    lines = summary.strip().split("\n")
    out = ["## 🔍 双重确认"]
    out.append("")
    for line in lines:
        stripped = line.strip()
        if stripped.startswith("**资金面"):
            out.append(stripped)
            out.append("")
        elif stripped.startswith("**板块情绪"):
            out.append(stripped)
            out.append("")
        elif stripped.startswith(("🟢", "🔴", "⚠️", "❓", "✅")):
            out.append(f"- {stripped}")
        elif stripped.startswith("→"):
            out.append(f"  {stripped}")
    return "\n".join(out)


def _compact_technical_md(summary: str) -> str:
    """精简技术面摘要 Markdown"""
    lines = summary.strip().split("\n")
    out = ["## 📋 技术面过滤"]
    out.append("")
    for line in lines:
        stripped = line.strip()
        if stripped.startswith("**过滤统计"):
            out.append(stripped)
            out.append("")
        elif stripped.startswith("### "):
            out.append(f"### {stripped[4:]}")
        elif stripped.startswith("- ") and any(x in stripped for x in ["✅", "⚠️", "🚫"]):
            out.append(stripped)
    return "\n".join(out)


# ═══════════════════════════════════════════════════════════════
# 3. HTML Email 格式 — 专业财经简报风格
# ═══════════════════════════════════════════════════════════════

def format_email_html(report: DailyReport) -> str:
    """生成精美的 HTML 邮件（现代财经简报风格）

    设计要点：
    - 暗色渐变头部 → 干净白卡片
    - 评分进度条可视化
    - 三列网格：逻辑/催化/风险
    - 适配各主流邮箱客户端
    """
    # ── 推荐卡片 ──
    cards_html = ""
    for i, rec in enumerate(report.recommendations, 1):
        cards_html += _render_recommendation_card(rec, i)

    if not report.recommendations:
        cards_html = """
        <div style="text-align:center;padding:48px 20px;color:#999;">
            <div style="font-size:56px;margin-bottom:12px;">📭</div>
            <div style="font-size:18px;font-weight:600;margin-bottom:8px;">今日暂无推荐</div>
            <div style="font-size:13px;">可能原因：信息源异常或AI服务不可用</div>
        </div>"""

    # ── 确认区块 ──
    confirm_html = _render_confirm_email(report)

    # ── 技术面区块 ──
    tech_html = _render_technical_email(report)

    # ── 策略分布区块 ──
    strategy_html = ""
    if hasattr(report, "strategy_summary") and report.strategy_summary:
        strategy_html = f"""
    <table width="100%" cellpadding="0" cellspacing="0" border="0"
        style="background:#fff7e6;border-radius:10px;margin-top:18px;margin-bottom:18px;
        border:1px solid #ffd591;">
        <tr><td style="padding:16px 22px;">
            <div style="font-size:15px;font-weight:700;color:#1a1a1a;margin-bottom:6px;">📐 策略分布</div>
            <p style="font-size:14px;color:#555;margin:0;">{report.strategy_summary}</p>
        </td></tr>
    </table>"""

    # ── 追踪区块 ──
    tracking_html = _render_tracking_email(report)

    # ── 来源标签 ──
    sources_tags = "".join(
        f'<span style="display:inline-block;background:rgba(255,255,255,0.18);padding:3px 10px;'
        f'margin:0 4px;border-radius:3px;font-size:12px;">{s}</span>'
        for s in report.sources_used
    )

    html = f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
</head>
<body style="margin:0;padding:0;background:#f0f2f5;font-family:-apple-system,BlinkMacSystemFont,'Segoe UI','PingFang SC','Microsoft YaHei',sans-serif;">

<!-- 外层 -->
<table width="100%" cellpadding="0" cellspacing="0" border="0" style="background:#f0f2f5;">
<tr><td align="center" style="padding:24px 16px;">

<!-- 内容容器 620px -->
<table width="620" cellpadding="0" cellspacing="0" border="0" style="max-width:620px;width:100%;">

<!-- ── 头部 ── -->
<tr>
<td style="background:linear-gradient(160deg,#0f0c29 0%,#1a1a2e 30%,#16213e 60%,#0f3460 100%);
    background-color:#1a1a2e;border-radius:14px 14px 0 0;padding:36px 32px 28px;">
    <div style="font-size:26px;font-weight:800;color:#fff;letter-spacing:1px;margin-bottom:8px;">
        📊 每日A股速递
    </div>
    <div style="font-size:15px;color:rgba(255,255,255,0.82);margin-bottom:14px;">
        {report.date} · {get_weekday_cn(report.date)}
    </div>
    <div style="font-size:12px;color:rgba(255,255,255,0.55);">
        🤖 AI综合分析 | 采集 {report.raw_news_count} 条信息 | 来源 {sources_tags}
    </div>
</td>
</tr>

<!-- ── 主体 ── -->
<tr>
<td style="background:#fff;padding:28px 24px 20px;border-radius:0;">
    {cards_html}
    {confirm_html}
    {tech_html}
    {strategy_html}
    {tracking_html}
</td>
</tr>

<!-- ── 页脚 ── -->
<tr>
<td style="background:#fafafa;border-radius:0 0 14px 14px;padding:22px 28px;
    border-top:1px solid #eee;">
    <div style="font-size:12px;color:#999;line-height:1.8;">
        ⚠️ <strong>免责声明</strong>：以上内容由AI自动生成，仅供学习参考和技术交流，
        <span style="color:#d4380d;">不构成任何投资建议</span>。
        股市有风险，投资需谨慎。
    </div>
    <div style="font-size:11px;color:#bbb;margin-top:8px;">
        生成时间：{report.generated_at[:19]}
    </div>
</td>
</tr>

</table>

<!-- 底部署名 -->
<div style="margin-top:16px;font-size:11px;color:#ccc;text-align:center;">
    每日A股智能推荐系统 · Powered by DeepSeek AI
</div>

</td></tr>
</table>
</body>
</html>"""

    return html


def _render_recommendation_card(rec: Recommendation, index: int) -> str:
    """渲染单条推荐卡片"""
    color = CONFIDENCE_COLOR.get(rec.confidence, "#8c8c8c")
    bg = CONFIDENCE_BG.get(rec.confidence, "#fafafa")
    emoji = CONFIDENCE_EMOJI.get(rec.confidence, "📌")

    # 策略标签
    strategy_html = ""
    if hasattr(rec, "strategy") and rec.strategy and rec.strategy != "观望":
        sc = STRATEGY_COLOR.get(rec.strategy, "#8c8c8c")
        sbg = STRATEGY_BG.get(rec.strategy, "#fafafa")
        se = STRATEGY_EMOJI.get(rec.strategy, "")
        strategy_html = (
            f'<span style="display:inline-block;background:{sbg};color:{sc};'
            f'padding:3px 10px;margin-left:8px;border-radius:12px;font-size:11px;font-weight:600;'
            f'border:1px solid {sc}44;">{se} {rec.strategy}</span>'
        )

    # 标的标签
    stock_tags = ""
    if rec.stocks:
        for s in rec.stocks:
            stock_tags += f"""
            <span style="display:inline-block;background:{bg};color:{color};
                padding:4px 12px;margin:2px 6px 2px 0;border-radius:4px;font-size:13px;font-weight:600;
                border:1px solid {color}22;">
                {s.get('name','?')}<span style="color:#999;font-weight:400;font-size:11px;"> {s.get('code','??????')}</span>
            </span>"""

    # 技术评分条
    score_html = ""
    if hasattr(rec, "technical") and rec.technical:
        tr = rec.technical
        score_parts = []
        for r in tr.get("stock_results", []):
            if r.get("excluded"):
                continue
            score = r["technical_score"]
            sc = _score_color(score)
            ma_status = ""
            for sig in r["signals"]:
                if sig.get("type") == "ma_position" and "detail" in sig:
                    ma_status = _ma_status_short(sig["detail"].get("status", ""))
                    break
            score_parts.append(f"""
            <div style="display:flex;align-items:center;margin-bottom:4px;">
                <span style="font-size:11px;font-weight:600;color:#555;width:52px;text-align:right;margin-right:8px;">{r['name']}</span>
                <span style="flex:1;height:6px;background:#eee;border-radius:3px;overflow:hidden;display:inline-block;max-width:140px;">
                    <span style="display:block;height:6px;width:{score}%;background:{sc};border-radius:3px;"></span>
                </span>
                <span style="font-size:12px;font-weight:700;color:{sc};margin-left:8px;min-width:24px;">{score}</span>
                <span style="font-size:10px;color:#999;margin-left:4px;">{ma_status}</span>
            </div>""")
        if score_parts:
            score_html = f"""
            <div style="margin-top:14px;padding-top:12px;border-top:1px dashed #eee;">
                <div style="font-size:11px;color:#999;margin-bottom:6px;">📊 技术面评分</div>
                {"".join(score_parts)}
            </div>"""

    card = f"""
    <!-- 推荐卡片 {index} -->
    <table width="100%" cellpadding="0" cellspacing="0" border="0"
        style="background:#fff;border-radius:10px;margin-bottom:18px;
        box-shadow:0 1px 6px rgba(0,0,0,0.05);border:1px solid #eee;
        border-left:4px solid {color};">
        <tr>
            <td style="padding:20px 22px;">

                <!-- 标题行 -->
                <table width="100%" cellpadding="0" cellspacing="0" border="0">
                    <tr>
                        <td style="font-size:17px;font-weight:700;color:#1a1a1a;padding-bottom:4px;">
                            {emoji} {rec.sector}{strategy_html}
                        </td>
                        <td align="right">
                            <span style="display:inline-block;background:{color};color:#fff;
                                padding:4px 14px;border-radius:14px;font-size:11px;font-weight:700;letter-spacing:1px;">
                                信心 {rec.confidence}
                            </span>
                        </td>
                    </tr>
                </table>

                <!-- 标的 -->
                <div style="margin:14px 0 6px;">
                    <span style="color:#999;font-size:12px;">🏷️ 标的：</span>
                    {stock_tags}
                </div>

                <!-- 三列 Grid -->
                <table width="100%" cellpadding="0" cellspacing="0" border="0" style="margin-top:14px;">
                    <tr>
                        <td width="33.33%" valign="top" style="padding:12px 10px;background:#f8fafb;border-radius:6px;">
                            <div style="font-size:10px;color:#999;text-transform:uppercase;letter-spacing:1px;margin-bottom:5px;">💡 推荐逻辑</div>
                            <div style="font-size:13px;color:#333;line-height:1.65;">{rec.logic}</div>
                        </td>
                        <td width="8">&nbsp;</td>
                        <td width="33.33%" valign="top" style="padding:12px 10px;background:#f8fafb;border-radius:6px;">
                            <div style="font-size:10px;color:#999;text-transform:uppercase;letter-spacing:1px;margin-bottom:5px;">⚡ 催化事件</div>
                            <div style="font-size:13px;color:#333;line-height:1.65;">{rec.catalyst}</div>
                        </td>
                        <td width="8">&nbsp;</td>
                        <td width="33.33%" valign="top" style="padding:12px 10px;background:{bg};border-radius:6px;">
                            <div style="font-size:10px;color:#999;text-transform:uppercase;letter-spacing:1px;margin-bottom:5px;">⚠️ 风险提示</div>
                            <div style="font-size:13px;color:{color};line-height:1.65;">{rec.risk}</div>
                        </td>
                    </tr>
                </table>

                {score_html}

            </td>
        </tr>
    </table>"""
    return card


def _render_confirm_email(report: DailyReport) -> str:
    """渲染确认引擎区块 HTML"""
    if not hasattr(report, "confirmation_summary") or not report.confirmation_summary:
        return ""

    lines = report.confirmation_summary.strip().split("\n")
    body = ""
    for line in lines:
        stripped = line.strip()
        if stripped.startswith("## "):
            body += f'<div style="font-size:15px;font-weight:700;color:#1a1a1a;margin-bottom:10px;">{stripped[3:]}</div>'
        elif stripped.startswith("**资金面"):
            body += f'<p style="font-size:13px;color:#555;margin:6px 0;">{stripped}</p>'
        elif stripped.startswith("**板块情绪"):
            body += f'<p style="font-size:13px;color:#555;margin:6px 0;">{stripped}</p>'
        elif stripped.startswith(("🟢", "🔴", "⚠️", "❓", "✅")):
            body += f'<p style="font-size:13px;color:#555;margin:2px 0 2px 12px;">{stripped}</p>'
        elif stripped.startswith("→"):
            body += f'<p style="font-size:12px;color:#888;margin:1px 0 1px 24px;">{stripped}</p>'

    return f"""
    <table width="100%" cellpadding="0" cellspacing="0" border="0"
        style="background:#f6ffed;border-radius:10px;margin-top:20px;margin-bottom:18px;
        border:1px solid #b7eb8f;">
        <tr><td style="padding:18px 22px;">{body}</td></tr>
    </table>"""


def _render_technical_email(report: DailyReport) -> str:
    """渲染技术面过滤区块 HTML"""
    if not hasattr(report, "technical_summary") or not report.technical_summary:
        return ""

    lines = report.technical_summary.strip().split("\n")
    body = ""
    for line in lines:
        stripped = line.strip()
        if stripped.startswith("## "):
            body += f'<div style="font-size:15px;font-weight:700;color:#1a1a1a;margin-bottom:10px;">{stripped[3:]}</div>'
        elif stripped.startswith("**过滤统计"):
            body += f'<p style="font-size:13px;color:#555;margin:6px 0;">{stripped}</p>'
        elif stripped.startswith("### "):
            body += f'<div style="font-size:14px;font-weight:600;color:#1a1a1a;margin:12px 0 4px;">{stripped[4:]}</div>'
        elif stripped.startswith("- ") and any(x in stripped for x in ["✅", "⚠️", "🚫"]):
            body += f'<p style="font-size:13px;color:#444;margin:3px 0 3px 8px;">{stripped}</p>'

    return f"""
    <table width="100%" cellpadding="0" cellspacing="0" border="0"
        style="background:#f0f5ff;border-radius:10px;margin-top:18px;margin-bottom:18px;
        border:1px solid #adc6ff;">
        <tr><td style="padding:18px 22px;">{body}</td></tr>
    </table>"""


def _render_tracking_email(report: DailyReport) -> str:
    """渲染追踪回顾区块 HTML"""
    if not report.tracking or not report.tracking.get("stocks"):
        return ""

    t = report.tracking
    t_rows = ""
    for s in t["stocks"]:
        t_emoji = "✅" if s.get("hit") else ("❌" if s.get("change_pct") is not None else "➖")
        t_perf = f"{s['change_pct']:+.2f}%" if s.get("change_pct") is not None else "—"
        sc = "#cf1322" if (s.get("change_pct") or 0) > 0 else ("#d4380d" if (s.get("change_pct") or 0) <= 0 else "#999")
        t_rows += f"""
        <tr style="border-bottom:1px solid #f5f5f5;">
            <td style="padding:7px 10px;font-size:13px;">{t_emoji}</td>
            <td style="padding:7px 10px;font-size:13px;font-weight:600;">{s['name']}
                <span style="color:#bbb;font-weight:400;font-size:11px;">{s['code']}</span></td>
            <td style="padding:7px 10px;font-size:12px;color:#888;">{s['sector']}</td>
            <td style="padding:7px 10px;font-size:12px;color:#888;">{s['confidence']}</td>
            <td style="padding:7px 10px;font-size:13px;font-weight:600;color:{sc};">{t_perf}</td>
        </tr>"""

    hit_color = "#cf1322" if t.get("avg_return", 0) > 0 else "#d4380d"
    summary = ""
    if t.get("total_count", 0) > 0:
        summary = (
            f'胜率 <strong style="font-size:18px;">{t["hit_rate"]:.0%}</strong> &nbsp;|&nbsp;'
            f'均收益 <strong style="color:{hit_color};font-size:16px;">{t["avg_return"]:+.2f}%</strong> &nbsp;|&nbsp;'
            f'{t["hit_count"]}涨 / {t["miss_count"]}跌'
        )

    return f"""
    <table width="100%" cellpadding="0" cellspacing="0" border="0"
        style="background:#fff;border-radius:10px;margin-top:20px;margin-bottom:18px;
        border:1px solid #eee;box-shadow:0 1px 6px rgba(0,0,0,0.04);">
        <tr><td style="padding:20px 22px;">
            <div style="font-size:15px;font-weight:700;color:#1a1a1a;margin-bottom:10px;">
                📊 昨日推荐回顾 ({t.get('prev_date','')})</div>
            <div style="font-size:13px;color:#666;margin-bottom:14px;">{summary}</div>
            <table width="100%" cellpadding="0" cellspacing="0" border="0">
                <tr style="background:#fafafa;">
                    <th style="padding:7px 10px;text-align:left;font-size:11px;color:#aaa;"></th>
                    <th style="padding:7px 10px;text-align:left;font-size:11px;color:#aaa;">标的</th>
                    <th style="padding:7px 10px;text-align:left;font-size:11px;color:#aaa;">板块</th>
                    <th style="padding:7px 10px;text-align:left;font-size:11px;color:#aaa;">信心</th>
                    <th style="padding:7px 10px;text-align:left;font-size:11px;color:#aaa;">今日</th>
                </tr>
                {t_rows}
            </table>
        </td></tr>
    </table>"""


# ═══════════════════════════════════════════════════════════════
# 4. HTML 网页 — GitHub Pages
# ═══════════════════════════════════════════════════════════════

def format_html_page(report: DailyReport, history_dates: List[str] = None) -> str:
    """生成完整 HTML 网页（GitHub Pages）

    匹配邮件模板的设计语言，增加更好的排版和交互体验。
    """
    date_str = report.date
    weekday = get_weekday_cn(report.date)

    # ── 历史导航 ──
    nav_html = ""
    if history_dates:
        nav_items = []
        for d in sorted(history_dates, reverse=True)[:30]:
            active = ' class="active"' if d == report.date else ""
            nav_items.append(f'<li{active}><a href="{d}.html">{d}</a></li>')
        nav_html = "\n".join(nav_items)

    # ── 推荐卡片 ──
    cards_html = ""
    if not report.recommendations:
        cards_html = '<div class="empty-state">📭<br>今日暂无推荐</div>'
    else:
        for i, rec in enumerate(report.recommendations, 1):
            cards_html += _render_page_card(rec, i)

    # ── 确认区块 ──
    confirm_html = ""
    if hasattr(report, "confirmation_summary") and report.confirmation_summary:
        confirm_html = _render_page_confirm(report.confirmation_summary)

    # ── 技术面区块 ──
    tech_html = ""
    if hasattr(report, "technical_summary") and report.technical_summary:
        tech_html = _render_page_technical(report.technical_summary)

    # ── 策略分布区块 ──
    strategy_html = ""
    if hasattr(report, "strategy_summary") and report.strategy_summary:
        strategy_html = (
            f'<div class="section-box" style="background:#fff7e6;border-color:#ffd591;">'
            f'<h3>📐 策略分布</h3>'
            f'<p style="font-size:14px;color:#555;">{report.strategy_summary}</p>'
            f'</div>'
        )

    # ── 追踪区块 ──
    tracking_html = _render_page_tracking(report)

    return f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>每日A股速递 | {date_str}</title>
<style>
    *,*::before,*::after{{box-sizing:border-box;margin:0;padding:0}}
    body{{
        font-family:-apple-system,BlinkMacSystemFont,"Segoe UI","PingFang SC","Microsoft YaHei",sans-serif;
        background:#f0f2f5;color:#1a1a1a;line-height:1.6;min-height:100vh;
    }}
    .wrapper{{max-width:820px;margin:0 auto;padding:24px 16px;}}

    /* 导航 */
    nav{{margin-bottom:20px;}}
    nav h3{{font-size:14px;color:#999;margin-bottom:8px;font-weight:500;}}
    nav ul{{list-style:none;display:flex;flex-wrap:wrap;gap:6px;}}
    nav a{{
        display:inline-block;padding:5px 13px;background:#e6f0ff;border-radius:6px;
        text-decoration:none;color:#3b82f6;font-size:13px;font-weight:500;transition:all .15s;
    }}
    nav a:hover,nav a.active{{background:#3b82f6;color:#fff;}}

    /* 头部 */
    .header{{
        background:linear-gradient(160deg,#0f0c29 0%,#1a1a2e 30%,#16213e 60%,#0f3460 100%);
        background-color:#1a1a2e;border-radius:14px 14px 0 0;padding:36px 32px 28px;color:#fff;
    }}
    .header h1{{font-size:26px;font-weight:800;letter-spacing:1px;margin-bottom:6px;}}
    .header .date{{font-size:15px;color:rgba(255,255,255,0.82);margin-bottom:12px;}}
    .header .meta{{font-size:12px;color:rgba(255,255,255,0.55);}}

    /* 内容区 */
    .content{{background:#fff;padding:28px 24px 20px;}}
    .content:last-child{{border-radius:0 0 14px 14px;}}

    /* 推荐卡片 */
    .rec-card{{
        background:#fff;border-radius:10px;margin-bottom:18px;
        border:1px solid #eee;border-left:4px solid #d4380d;
        box-shadow:0 1px 6px rgba(0,0,0,0.04);overflow:hidden;
    }}
    .rec-card .card-body{{padding:20px 22px;}}
    .rec-card .card-header{{display:flex;justify-content:space-between;align-items:center;margin-bottom:10px;}}
    .rec-card .sector{{font-size:18px;font-weight:700;}}
    .rec-card .confidence-badge{{
        display:inline-block;padding:4px 14px;border-radius:14px;
        font-size:11px;font-weight:700;color:#fff;letter-spacing:1px;
    }}
    .rec-card .stock-tags{{margin:14px 0 6px;}}
    .rec-card .stock-tag{{
        display:inline-block;padding:4px 12px;margin:2px 6px 2px 0;
        border-radius:4px;font-size:13px;font-weight:600;
    }}
    .rec-card .info-grid{{display:grid;grid-template-columns:1fr 1fr 1fr;gap:8px;margin-top:14px;}}
    .rec-card .info-cell{{
        padding:12px 10px;background:#f8fafb;border-radius:6px;font-size:13px;
    }}
    .rec-card .info-cell.risk{{font-weight:500;}}
    .rec-card .info-label{{font-size:10px;color:#999;text-transform:uppercase;letter-spacing:1px;margin-bottom:5px;}}

    /* 评分条 */
    .score-section{{margin-top:14px;padding-top:12px;border-top:1px dashed #eee;}}
    .score-section .score-label{{font-size:11px;color:#999;margin-bottom:6px;}}
    .score-row{{display:flex;align-items:center;margin-bottom:5px;}}
    .score-name{{font-size:12px;font-weight:600;color:#555;width:56px;text-align:right;margin-right:10px;flex-shrink:0;}}
    .score-bar-wrap{{flex:1;max-width:200px;height:6px;background:#eee;border-radius:3px;overflow:hidden;}}
    .score-bar{{display:block;height:6px;border-radius:3px;transition:width .3s;}}
    .score-val{{font-size:13px;font-weight:700;margin-left:8px;min-width:26px;}}
    .score-ma{{font-size:11px;color:#999;margin-left:6px;}}

    /* 确认 / 技术面 section */
    .section-box{{
        border-radius:10px;margin-top:18px;margin-bottom:18px;padding:18px 22px;border:1px solid;
    }}
    .section-box h3{{font-size:15px;font-weight:700;margin-bottom:10px;}}
    .section-box p{{font-size:13px;color:#555;margin:3px 0;}}

    /* 追踪 */
    .tracking-table{{width:100%;border-collapse:collapse;margin-top:10px;}}
    .tracking-table th{{text-align:left;font-size:11px;color:#aaa;padding:7px 10px;background:#fafafa;}}
    .tracking-table td{{padding:7px 10px;font-size:13px;border-bottom:1px solid #f5f5f5;}}

    /* 页脚 */
    .footer{{background:#fafafa;border-radius:0 0 14px 14px;padding:22px 28px;border-top:1px solid #eee;}}
    .footer .disclaimer{{font-size:12px;color:#999;line-height:1.8;}}
    .footer .timestamp{{font-size:11px;color:#bbb;margin-top:8px;}}

    /* 辅助 */
    .empty-state{{text-align:center;padding:48px 20px;color:#ccc;font-size:18px;}}
    .empty-state .empty-icon{{font-size:56px;margin-bottom:12px;}}
    .divider{{border:none;border-top:1px solid #eee;margin:18px 0;}}

    @media(max-width:640px){{
        .rec-card .info-grid{{grid-template-columns:1fr;}}
        .wrapper{{padding:12px 8px;}}
    }}
</style>
</head>
<body>
<div class="wrapper">

    <nav>
        <h3>📅 历史报告</h3>
        <ul>{nav_html}</ul>
    </nav>

    <div class="header">
        <h1>📊 每日A股速递</h1>
        <div class="date">{date_str} · {weekday}</div>
        <div class="meta">🤖 AI综合分析 | 采集 {report.raw_news_count} 条信息 | 来源：{'、'.join(report.sources_used)}</div>
    </div>

    <div class="content">
        {cards_html}
        {confirm_html}
        {tech_html}
        {strategy_html}
        {tracking_html}
    </div>

    <div class="footer">
        <div class="disclaimer">
            ⚠️ <strong>免责声明</strong>：以上内容由AI自动生成，仅供学习参考和技术交流，
            <span style="color:#d4380d;">不构成任何投资建议</span>。股市有风险，投资需谨慎。
        </div>
        <div class="timestamp">生成时间：{report.generated_at[:19]}</div>
    </div>

    <div style="text-align:center;margin-top:16px;font-size:11px;color:#ccc;">
        每日A股智能推荐系统 · Powered by DeepSeek AI
    </div>

</div>
</body>
</html>"""


def _render_page_card(rec: Recommendation, index: int) -> str:
    """渲染网页版推荐卡片"""
    color = CONFIDENCE_COLOR.get(rec.confidence, "#8c8c8c")
    bg = CONFIDENCE_BG.get(rec.confidence, "#fafafa")
    emoji = CONFIDENCE_EMOJI.get(rec.confidence, "📌")

    # 策略标签
    strategy_html = ""
    if hasattr(rec, "strategy") and rec.strategy and rec.strategy != "观望":
        sc = STRATEGY_COLOR.get(rec.strategy, "#8c8c8c")
        sbg = STRATEGY_BG.get(rec.strategy, "#fafafa")
        se = STRATEGY_EMOJI.get(rec.strategy, "")
        strategy_html = (
            f'<span style="display:inline-block;background:{sbg};color:{sc};'
            f'padding:3px 10px;margin-left:8px;border-radius:12px;font-size:11px;font-weight:600;'
            f'border:1px solid {sc}44;">{se} {rec.strategy}</span>'
        )

    stock_tags = ""
    if rec.stocks:
        for s in rec.stocks:
            stock_tags += (
                f'<span class="stock-tag" style="background:{bg};color:{color};'
                f'border:1px solid {color}22;">{s.get("name","?")}'
                f'<span style="color:#999;font-weight:400;font-size:11px;"> {s.get("code","")}</span></span>'
            )

    # 评分条
    score_html = ""
    if hasattr(rec, "technical") and rec.technical:
        tr = rec.technical
        rows = []
        for r in tr.get("stock_results", []):
            if r.get("excluded"):
                continue
            score = r["technical_score"]
            sc = _score_color(score)
            ma_status = ""
            for sig in r["signals"]:
                if sig.get("type") == "ma_position" and "detail" in sig:
                    ma_status = _ma_status_short(sig["detail"].get("status", ""))
                    break
            rows.append(
                f'<div class="score-row">'
                f'<span class="score-name">{r["name"]}</span>'
                f'<span class="score-bar-wrap"><span class="score-bar" style="width:{score}%;background:{sc};"></span></span>'
                f'<span class="score-val" style="color:{sc};">{score}</span>'
                f'<span class="score-ma">{ma_status}</span>'
                f'</div>'
            )
        if rows:
            score_html = f'<div class="score-section"><div class="score-label">📊 技术面评分</div>{"".join(rows)}</div>'

    return f"""
    <div class="rec-card" style="border-left-color:{color};">
        <div class="card-body">
            <div class="card-header">
                <span class="sector">{emoji} {rec.sector}{strategy_html}</span>
                <span class="confidence-badge" style="background:{color};">信心 {rec.confidence}</span>
            </div>
            <div class="stock-tags"><span style="color:#999;font-size:12px;">🏷️ 标的：</span>{stock_tags}</div>
            <div class="info-grid">
                <div class="info-cell">
                    <div class="info-label">💡 推荐逻辑</div>
                    {rec.logic}
                </div>
                <div class="info-cell">
                    <div class="info-label">⚡ 催化事件</div>
                    {rec.catalyst}
                </div>
                <div class="info-cell risk" style="background:{bg};color:{color};">
                    <div class="info-label">⚠️ 风险提示</div>
                    {rec.risk}
                </div>
            </div>
            {score_html}
        </div>
    </div>"""


def _render_page_confirm(summary: str) -> str:
    """渲染网页版确认摘要"""
    lines = summary.strip().split("\n")
    body = ""
    for line in lines:
        stripped = line.strip()
        if stripped.startswith("## "):
            body += f"<h3>{stripped[3:]}</h3>"
        elif stripped.startswith("**资金面"):
            body += f"<p><strong>{stripped.strip('*')}</strong></p>"
        elif stripped.startswith("**板块情绪"):
            body += f"<p><strong>{stripped.strip('*')}</strong></p>"
        elif stripped.startswith(("🟢", "🔴", "⚠️", "❓", "✅")):
            body += f"<p>{stripped}</p>"
        elif stripped.startswith("→"):
            body += f"<p style='font-size:12px;color:#888;margin-left:16px;'>{stripped}</p>"
    return f'<div class="section-box" style="background:#f6ffed;border-color:#b7eb8f;">{body}</div>'


def _render_page_technical(summary: str) -> str:
    """渲染网页版技术面摘要"""
    lines = summary.strip().split("\n")
    body = ""
    for line in lines:
        stripped = line.strip()
        if stripped.startswith("## "):
            body += f"<h3>{stripped[3:]}</h3>"
        elif stripped.startswith("**过滤统计"):
            body += f"<p><strong>{stripped.strip('*')}</strong></p>"
        elif stripped.startswith("### "):
            body += f"<p style='font-weight:600;margin-top:10px;'>{stripped[4:]}</p>"
        elif stripped.startswith("- ") and any(x in stripped for x in ["✅", "⚠️", "🚫"]):
            body += f"<p style='font-size:13px;margin:2px 0 2px 8px;'>{stripped}</p>"
    return f'<div class="section-box" style="background:#f0f5ff;border-color:#adc6ff;">{body}</div>'


def _render_page_tracking(report: DailyReport) -> str:
    """渲染网页版追踪"""
    if not report.tracking or not report.tracking.get("stocks"):
        return ""

    t = report.tracking
    rows = ""
    for s in t["stocks"]:
        t_emoji = "✅" if s.get("hit") else ("❌" if s.get("change_pct") is not None else "➖")
        t_perf = f"{s['change_pct']:+.2f}%" if s.get("change_pct") is not None else "—"
        sc = "#cf1322" if (s.get("change_pct") or 0) > 0 else ("#d4380d" if (s.get("change_pct") or 0) <= 0 else "#999")
        rows += (
            f"<tr>"
            f"<td>{t_emoji}</td><td><strong>{s['name']}</strong>"
            f"<span style='color:#bbb;font-weight:400;font-size:11px;'> {s['code']}</span></td>"
            f"<td style='color:#888;'>{s['sector']}</td><td style='color:#888;'>{s['confidence']}</td>"
            f"<td style='font-weight:600;color:{sc};'>{t_perf}</td>"
            f"</tr>"
        )

    summary = ""
    if t.get("total_count", 0) > 0:
        hit_color = "#cf1322" if t.get("avg_return", 0) > 0 else "#d4380d"
        summary = (
            f'胜率 <strong style="font-size:18px;">{t["hit_rate"]:.0%}</strong> | '
            f'均收益 <strong style="color:{hit_color};font-size:16px;">{t["avg_return"]:+.2f}%</strong> | '
            f'{t["hit_count"]}涨 / {t["miss_count"]}跌'
        )

    return f"""
    <div class="section-box" style="background:#fff;border-color:#eee;">
        <h3>📊 昨日推荐回顾 ({t.get('prev_date','')})</h3>
        <p style="font-size:13px;color:#666;margin-bottom:12px;">{summary}</p>
        <table class="tracking-table">
            <tr><th></th><th>标的</th><th>板块</th><th>信心</th><th>今日表现</th></tr>
            {rows}
        </table>
    </div>"""
