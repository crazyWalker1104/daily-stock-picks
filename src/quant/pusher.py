"""量化跟投模块 — 推送管理器

封装量化信号的推送逻辑：
  - 紧急信号（开/加/减/清）→ 微信即时推送
  - 每日总结 → 邮件推送
  - 候选推荐 → 微信+邮件

复用 src/pusher.py 的 EmailPusher 和 WeChatPusher 通道。
"""

import logging
from typing import Dict, List, Optional

from src.pusher import EmailPusher, WeChatPusher
from src.quant.formatter import (
    format_signal_wechat, format_signal_email, format_daily_summary_email,
)
from src.quant.models import QuantSignal, SignalType, StockCandidate

logger = logging.getLogger(__name__)


# 可操作信号（需要推送的）
ACTIONABLE_SIGNALS = {SignalType.OPEN, SignalType.ADD,
                      SignalType.REDUCE, SignalType.CLOSE}


class QuantPusher:
    """量化推送管理器

    用法:
        pusher = QuantPusher()
        pusher.push_signal(signal)               # 单信号推送（紧急时微信+邮件）
        pusher.push_daily_summary(signals, ...)  # 每日总结（邮件）
    """

    def __init__(self, config: dict = None):
        self.config = config or {}

        # 从量化配置段读取开关
        quant_cfg = self.config.get("quant", {}).get("push", {})
        self.wechat_enabled = quant_cfg.get("wechat", {}).get("enabled", True)
        self.email_enabled = quant_cfg.get("email", {}).get("enabled", True)
        self.wechat_urgent_only = quant_cfg.get("wechat", {}).get("urgent_only", True)

        self._wechat: Optional[WeChatPusher] = None
        self._email: Optional[EmailPusher] = None

    # ── 懒初始化 ──

    @property
    def wechat(self) -> WeChatPusher:
        if self._wechat is None:
            self._wechat = WeChatPusher(config=self.config)
        return self._wechat

    @property
    def email(self) -> EmailPusher:
        if self._email is None:
            self._email = EmailPusher(config=self.config)
        return self._email

    # ── 推送方法 ──

    def push_signal(self, signal: QuantSignal,
                    force_wechat: bool = False) -> Dict[str, bool]:
        """推送单个信号

        - 微信：仅在信号可操作时推送（开/加/减/清），除非 force_wechat
        - 邮件：始终推送

        Returns:
            {channel: success} 字典
        """
        results = {}

        is_actionable = signal.signal in ACTIONABLE_SIGNALS

        # ── 微信推送（紧急信号优先） ──
        if self.wechat_enabled and self.wechat.is_configured():
            if is_actionable or force_wechat:
                title = f"📡 {signal.symbol_name} 量化信号"
                body = format_signal_wechat(signal)
                results["wechat"] = self.wechat.send_message(title, body)
                if results["wechat"]:
                    logger.info(f"量化信号已推送至微信: {signal.symbol} "
                                f"{signal.signal.value}")
            else:
                logger.debug(f"信号 {signal.signal.value} 非紧急，跳过微信推送")
        else:
            results["wechat"] = False

        # ── 邮件推送 ──
        if self.email_enabled and self.email.is_configured() and is_actionable:
            title = f"📡 量化信号: {signal.symbol_name} | {signal.date}"
            body = format_signal_email(signal)
            results["email"] = self.email.send_message(title, body)
            if results["email"]:
                logger.info(f"量化信号已推送至邮箱: {signal.symbol} "
                            f"{signal.signal.value}")
        else:
            results["email"] = False

        return results

    def push_daily_summary(
        self,
        signals: List[QuantSignal],
        position_text: str = "",
        risk_stats: dict = None,
    ) -> Dict[str, bool]:
        """推送每日量化总结（邮件）"""
        results = {}

        if self.email_enabled and self.email.is_configured():
            date_str = signals[0].date if signals else ""
            title = f"📊 量化跟投 · 每日总结 | {date_str}"
            body = format_daily_summary_email(signals, position_text, risk_stats)
            results["email"] = self.email.send_message(title, body)
            logger.info(f"每日量化总结已发送 ({len(signals)}只标的)")
        else:
            results["email"] = False

        results["wechat"] = False  # 日结不走微信
        return results

    def push_candidates(self, candidates: List["StockCandidate"]) -> Dict[str, bool]:
        """推送候选标的推荐（微信+邮件）"""
        results = {"wechat": False, "email": False}

        if not candidates:
            return results

        # 构建 markdown
        lines = [
            f"## 🎯 量化选股 · Top {len(candidates)} 候选",
            "",
        ]
        for i, c in enumerate(candidates, 1):
            lines.append(f"**#{i} {c.symbol_name}**（{c.symbol}）评分:{c.score:.0f}")
            lines.append(f"- 出现{c.appearance_count}次 | 胜率{c.win_rate:.0%} | 均收益{c.avg_return*100:+.1f}%")
            lines.append(f"- 板块:{c.last_sector} | 信心:{c.last_confidence}")
            lines.append(f"- {c.reason}")
            lines.append("")

        lines.append("📌 选择标的: python -m src.quant --symbol 代码")

        body_md = "\n".join(lines)

        # 微信
        if self.wechat_enabled and self.wechat.is_configured():
            results["wechat"] = self.wechat.send_message("🎯 量化选股候选", body_md)

        # 邮件
        if self.email_enabled and self.email.is_configured():
            body_html = format_daily_summary_email(
                [],  # 空信号列表
                position_text="📋 候选标的推荐\n\n" + body_md,
            )
            results["email"] = self.email.send_message(
                f"🎯 量化选股 · Top {len(candidates)} 候选", body_html
            )

        return results
