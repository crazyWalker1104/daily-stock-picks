"""量化跟投模块 — 信号格式化输出

为微信（ServerChan Markdown）和邮件（HTML）生成量化信号推送内容。
"""

from typing import List, Optional

from src.quant.models import (
    QuantSignal, Position, SIGNAL_EMOJI, SIGNAL_CN, REGIME_CN, MODE_CN,
    SignalType,
)


# ═══════════════════════════════════════════════════════════════
# 微信推送（ServerChan Markdown — 紧凑格式）
# ═══════════════════════════════════════════════════════════════

def format_signal_wechat(signal: QuantSignal) -> str:
    """将单个信号格式化为微信推送用的 Markdown

    ServerChan 建议控制在 500 字以内，突出重点。
    """
    emoji = SIGNAL_EMOJI.get(signal.signal, "❓")
    action = SIGNAL_CN.get(signal.signal, "未知")
    regime = REGIME_CN.get(signal.regime, "未知")
    mode = MODE_CN.get(signal.mode, "未知")

    lines = [
        f"## {emoji} {action} | {signal.symbol_name}({signal.symbol})",
        "",
        f"- **日期**: {signal.date}",
        f"- **市场**: {regime} | **策略**: {mode}",
        f"- **评分**: {signal.total_score:.0f}/100 (买入{signal.buy_score:.0f} | 卖出{signal.sell_score:.0f})",
        f"- **现价**: {signal.current_price:.2f}",
    ]

    if signal.stop_loss > 0:
        lines.append(f"- **止损**: {signal.stop_loss:.2f} | **止盈**: {signal.take_profit:.2f}")

    if signal.position_advice > 0:
        lines.append(f"- **建议仓位**: {signal.position_advice*100:.0f}%")

    # 技术指标摘要
    ind = signal.indicators
    if ind:
        rsi = ind.get("rsi14", 0)
        macd = ind.get("macd_hist", 0)
        adx = ind.get("adx", 0)
        vr = ind.get("volume_ratio", 1)
        lines.append(f"- **指标**: RSI{rsi:.0f} MACD{macd:+.2f} ADX{adx:.0f} 量比{vr:.2f}")

    lines.append(f"- **风险**: {signal.risk_level}")

    # 操作建议（最重要部分）
    if signal.signal in (SignalType.OPEN, SignalType.ADD):
        lines.append("")
        lines.append(f"> 🔔 **操作**: {signal.action_text}")
    elif signal.signal in (SignalType.REDUCE, SignalType.CLOSE):
        lines.append("")
        lines.append(f"> ⚠️ **操作**: {signal.action_text}")

    lines.append("")
    lines.append(signal.reasoning)
    lines.append("")
    lines.append("---")
    lines.append("🤖 量化信号 · 仅供参考 · 不构成投资建议")

    return "\n".join(lines)


# ═══════════════════════════════════════════════════════════════
# 邮件推送（HTML — 单信号紧急推送）
# ═══════════════════════════════════════════════════════════════

def format_signal_email(signal: QuantSignal) -> str:
    """将单个信号格式化为邮件 HTML"""
    emoji = SIGNAL_EMOJI.get(signal.signal, "❓")
    action = SIGNAL_CN.get(signal.signal, "未知")
    regime = REGIME_CN.get(signal.regime, "未知")
    mode = MODE_CN.get(signal.mode, "未知")

    # 信号颜色
    if signal.signal in (SignalType.OPEN, SignalType.ADD):
        card_color = "#22c55e"  # 绿色
        bg = "#f0fdf4"
        border = "#4ade80"
    elif signal.signal in (SignalType.REDUCE, SignalType.CLOSE):
        card_color = "#ef4444"  # 红色
        bg = "#fef2f2"
        border = "#f87171"
    else:
        card_color = "#6b7280"  # 灰色
        bg = "#f9fafb"
        border = "#d1d5db"

    # 评分条
    bar_width = min(signal.total_score, 100)
    bar_color = "#22c55e" if signal.total_score >= 40 else "#f59e0b" if signal.total_score >= 20 else "#ef4444"

    return f"""<!DOCTYPE html>
<html><head><meta charset="utf-8"></head>
<body style="font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif;
             max-width:600px; margin:0 auto; padding:20px; background:#f5f5f5;">
  <div style="background: linear-gradient(135deg, #1a1a2e 0%, #16213e 100%);
              color:white; padding:24px; border-radius:12px 12px 0 0; text-align:center;">
    <h1 style="margin:0 0 8px; font-size:22px;">{emoji} {action}信号</h1>
    <p style="margin:0; opacity:0.8; font-size:14px;">
      {signal.symbol_name}（{signal.symbol}）| {signal.date}</p>
  </div>

  <div style="background:white; padding:24px; border-radius:0 0 12px 12px;
              box-shadow:0 2px 8px rgba(0,0,0,0.1);">

    <div style="background:{bg}; border-left:4px solid {border};
                padding:16px; border-radius:8px; margin-bottom:16px;">
      <h2 style="margin:0 0 8px; color:{card_color}; font-size:18px;">
        {signal.action_text}</h2>
      <p style="margin:0; color:#374151; line-height:1.6;">{signal.reasoning}</p>
    </div>

    <table style="width:100%; border-collapse:collapse; margin-bottom:16px;">
      <tr>
        <td style="padding:8px 12px; border-bottom:1px solid #e5e7eb; color:#6b7280;">现价</td>
        <td style="padding:8px 12px; border-bottom:1px solid #e5e7eb; font-weight:bold;">{signal.current_price:.2f}</td>
        <td style="padding:8px 12px; border-bottom:1px solid #e5e7eb; color:#6b7280;">市场状态</td>
        <td style="padding:8px 12px; border-bottom:1px solid #e5e7eb;">{regime} · {mode}</td>
      </tr>
      <tr>
        <td style="padding:8px 12px; border-bottom:1px solid #e5e7eb; color:#6b7280;">止损</td>
        <td style="padding:8px 12px; border-bottom:1px solid #e5e7eb; font-weight:bold; color:#ef4444;">{signal.stop_loss:.2f}</td>
        <td style="padding:8px 12px; border-bottom:1px solid #e5e7eb; color:#6b7280;">止盈</td>
        <td style="padding:8px 12px; border-bottom:1px solid #e5e7eb; font-weight:bold; color:#22c55e;">{signal.take_profit:.2f}</td>
      </tr>
      <tr>
        <td style="padding:8px 12px; color:#6b7280;">建议仓位</td>
        <td style="padding:8px 12px; font-weight:bold;">{signal.position_advice*100:.0f}%</td>
        <td style="padding:8px 12px; color:#6b7280;">风险等级</td>
        <td style="padding:8px 12px;">{signal.risk_level}</td>
      </tr>
    </table>

    <!-- 评分 -->
    <div style="margin-bottom:16px;">
      <div style="display:flex; justify-content:space-between; margin-bottom:4px;">
        <span style="font-size:12px; color:#6b7280;">综合评分</span>
        <span style="font-size:14px; font-weight:bold;">{signal.total_score:.0f}/100</span>
      </div>
      <div style="background:#e5e7eb; border-radius:8px; height:12px; overflow:hidden;">
        <div style="background:{bar_color}; width:{bar_width}%; height:100%;
                    border-radius:8px; transition:width 0.3s;"></div>
      </div>
    </div>

    <!-- 指标 -->
    <div style="display:grid; grid-template-columns:repeat(4,1fr); gap:8px;
                margin-bottom:16px;">
      <div style="background:#f3f4f6; padding:8px; border-radius:6px; text-align:center;">
        <div style="font-size:11px; color:#6b7280;">RSI</div>
        <div style="font-weight:bold;">{signal.indicators.get('rsi14',0):.0f}</div>
      </div>
      <div style="background:#f3f4f6; padding:8px; border-radius:6px; text-align:center;">
        <div style="font-size:11px; color:#6b7280;">MACD</div>
        <div style="font-weight:bold;">{signal.indicators.get('macd_hist',0):.2f}</div>
      </div>
      <div style="background:#f3f4f6; padding:8px; border-radius:6px; text-align:center;">
        <div style="font-size:11px; color:#6b7280;">ADX</div>
        <div style="font-weight:bold;">{signal.indicators.get('adx',0):.0f}</div>
      </div>
      <div style="background:#f3f4f6; padding:8px; border-radius:6px; text-align:center;">
        <div style="font-size:11px; color:#6b7280;">量比</div>
        <div style="font-weight:bold;">{signal.indicators.get('volume_ratio',1):.2f}</div>
      </div>
    </div>

    <p style="color:#9ca3af; font-size:11px; text-align:center; margin:0;">
      🤖 量化信号 · AI生成 · 仅供参考 · 不构成投资建议</p>
  </div>
</body></html>"""


# ═══════════════════════════════════════════════════════════════
# 邮件推送（HTML — 每日总结）
# ═══════════════════════════════════════════════════════════════

def format_daily_summary_email(
    signals: List[QuantSignal],
    position_text: str = "",
    risk_stats: dict = None,
) -> str:
    """生成每日量化总结邮件 HTML

    Args:
        signals: 今日所有信号列表
        position_text: 持仓状态文本
        risk_stats: 风控统计 dict
    """
    date_str = signals[0].date if signals else ""

    # 信号行
    signal_rows = ""
    for s in signals:
        emoji = SIGNAL_EMOJI.get(s.signal, "❓")
        action = SIGNAL_CN.get(s.signal, "未知")
        regime = REGIME_CN.get(s.regime, "未知")

        # 行颜色
        if s.signal in (SignalType.OPEN, SignalType.ADD):
            row_bg = "#f0fdf4"
            text_color = "#16a34a"
        elif s.signal in (SignalType.REDUCE, SignalType.CLOSE):
            row_bg = "#fef2f2"
            text_color = "#dc2626"
        else:
            row_bg = "white"
            text_color = "#374151"

        signal_rows += f"""
          <tr style="background:{row_bg};">
            <td style="padding:12px; border-bottom:1px solid #e5e7eb;">
              <b>{s.symbol_name}</b><br>
              <span style="font-size:12px; color:#6b7280;">{s.symbol}</span>
            </td>
            <td style="padding:12px; border-bottom:1px solid #e5e7eb; color:{text_color}; font-weight:bold;">
              {emoji} {action}
            </td>
            <td style="padding:12px; border-bottom:1px solid #e5e7eb;">
              {s.total_score:.0f}/100
            </td>
            <td style="padding:12px; border-bottom:1px solid #e5e7eb;">
              {regime}
            </td>
            <td style="padding:12px; border-bottom:1px solid #e5e7eb;">
              {s.current_price:.2f}
            </td>
            <td style="padding:12px; border-bottom:1px solid #e5e7eb;">
              {s.stop_loss:.2f} / {s.take_profit:.2f}
            </td>
          </tr>"""

    # 风控统计
    risk_html = ""
    if risk_stats:
        risk_color = "#22c55e" if risk_stats.get("total_return", 0) >= 0 else "#ef4444"
        risk_html = f"""
      <div style="background:#f9fafb; padding:16px; border-radius:8px; margin-top:16px;">
        <h3 style="margin:0 0 12px; font-size:15px;">📋 风控统计</h3>
        <table style="width:100%; font-size:13px;">
          <tr>
            <td style="color:#6b7280;">已完成交易</td>
            <td><b>{risk_stats.get('completed_trades', 0)}笔</b></td>
            <td style="color:#6b7280;">胜率</td>
            <td style="color:{'#22c55e' if risk_stats.get('win_rate',0) >= 0.5 else '#ef4444'}"><b>{risk_stats.get('win_rate',0)*100:.0f}%</b></td>
          </tr>
          <tr>
            <td style="color:#6b7280;">总收益率</td>
            <td style="color:{risk_color};"><b>{risk_stats.get('total_return',0)*100:+.1f}%</b></td>
            <td style="color:#6b7280;">连续亏损</td>
            <td><b>{risk_stats.get('consecutive_losses', 0)}次</b></td>
          </tr>
        </table>
      </div>"""

    return f"""<!DOCTYPE html>
<html><head><meta charset="utf-8"></head>
<body style="font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif;
             max-width:680px; margin:0 auto; padding:20px; background:#f5f5f5;">

  <!-- Header -->
  <div style="background: linear-gradient(135deg, #0f172a 0%, #1e3a5f 100%);
              color:white; padding:28px; border-radius:12px 12px 0 0; text-align:center;">
    <h1 style="margin:0 0 6px; font-size:20px;">📊 量化跟投 · 每日总结</h1>
    <p style="margin:0; opacity:0.7; font-size:13px;">{date_str} 盘后信号</p>
  </div>

  <!-- Body -->
  <div style="background:white; padding:24px; border-radius:0 0 12px 12px;
              box-shadow:0 2px 8px rgba(0,0,0,0.1);">

    <!-- 持仓状态 -->
    <div style="background:#fffbeb; border-left:4px solid #f59e0b;
                padding:14px 16px; border-radius:8px; margin-bottom:20px;
                white-space:pre-line; font-size:14px;">
{position_text or '📭 当前空仓'}
    </div>

    <!-- 信号表格 -->
    <h3 style="margin:0 0 12px; font-size:15px;">
      📡 今日信号（{len(signals)}只标的）
    </h3>

    <table style="width:100%; border-collapse:collapse; font-size:13px; margin-bottom:16px;">
      <thead>
        <tr style="background:#f3f4f6;">
          <th style="padding:10px 12px; text-align:left;">标的</th>
          <th style="padding:10px 12px; text-align:left;">信号</th>
          <th style="padding:10px 12px; text-align:left;">评分</th>
          <th style="padding:10px 12px; text-align:left;">市场</th>
          <th style="padding:10px 12px; text-align:left;">现价</th>
          <th style="padding:10px 12px; text-align:left;">止损/止盈</th>
        </tr>
      </thead>
      <tbody>{signal_rows}
      </tbody>
    </table>
{risk_html}
    <p style="color:#9ca3af; font-size:11px; text-align:center; margin:20px 0 0;">
      🤖 量化信号 · 规则驱动 · 仅供参考 · 不构成投资建议<br>
      每日 15:00 收盘后自动更新
    </p>
  </div>
</body></html>"""
