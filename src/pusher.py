"""推送模块 — 多通道分发（邮箱 + CLI + Web）"""

import os
import logging
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from datetime import datetime
from typing import List

from src.models import DailyReport
from src.formatter import format_markdown, format_plain, format_html_page, format_email_html

logger = logging.getLogger(__name__)


class EmailPusher:
    """邮箱推送（SMTP）"""

    def __init__(self):
        self.host = os.getenv("SMTP_HOST", "smtp.qq.com")
        self.port = int(os.getenv("SMTP_PORT", "587"))
        self.user = os.getenv("SMTP_USER", "")
        self.password = os.getenv("SMTP_PASSWORD", "")
        self.recipient = os.getenv("RECIPIENT_EMAIL", "")

    def is_configured(self) -> bool:
        return bool(self.user and self.password and self.recipient)

    def send(self, report: DailyReport) -> bool:
        """发送邮件"""
        if not self.is_configured():
            logger.warning("邮箱未配置，跳过邮件推送")
            return False

        subject = f"📊 每日A股速递 | {report.date}"
        body = format_markdown(report)

        msg = MIMEMultipart("alternative")
        msg["Subject"] = subject
        msg["From"] = self.user
        msg["To"] = self.recipient

        # 纯文本 + 精美HTML双版本
        msg.attach(MIMEText(format_plain(report), "plain", "utf-8"))
        msg.attach(MIMEText(format_email_html(report), "html", "utf-8"))

        try:
            with smtplib.SMTP(self.host, self.port, timeout=15) as server:
                server.starttls()
                server.login(self.user, self.password)
                server.sendmail(self.user, [self.recipient], msg.as_string())
            logger.info("邮件发送成功")
            return True
        except Exception as e:
            logger.error(f"邮件发送失败: {e}")
            return False


class CLIPusher:
    """命令行推送"""

    def send(self, report: DailyReport) -> str:
        """返回格式化文本"""
        return format_plain(report)


class WebPusher:
    """网页推送 — 生成HTML到docs/目录"""

    def __init__(self, output_dir: str = "docs"):
        self.output_dir = output_dir

    def get_history_dates(self) -> List[str]:
        """获取已有的历史报告日期列表"""
        dates = []
        if not os.path.exists(self.output_dir):
            return dates
        for f in os.listdir(self.output_dir):
            if f.endswith(".html") and f != "index.html":
                dates.append(f.replace(".html", ""))
        return sorted(dates, reverse=True)

    def save(self, report: DailyReport) -> str:
        """保存报告HTML到docs/目录"""
        os.makedirs(self.output_dir, exist_ok=True)

        history = self.get_history_dates()
        if report.date not in history:
            history.append(report.date)

        # 保存当日报告
        filename = f"{report.date}.html"
        filepath = os.path.join(self.output_dir, filename)
        html = format_html_page(report, history)
        with open(filepath, "w", encoding="utf-8") as f:
            f.write(html)
        logger.info(f"网页报告已保存: {filepath}")

        # 更新index.html（最新报告）
        index_path = os.path.join(self.output_dir, "index.html")
        with open(index_path, "w", encoding="utf-8") as f:
            f.write(html)
        logger.info(f"首页已更新: {index_path}")

        return filepath


class Pusher:
    """推送管理器 — 协调所有推送通道"""

    def __init__(self, config: dict):
        self.config = config
        push_config = config.get("push", {})

        self.email_pusher = EmailPusher() if push_config.get("email", {}).get("enabled", False) else None
        self.cli_pusher = CLIPusher()
        self.web_pusher = WebPusher() if push_config.get("web", {}).get("enabled", False) else None

    def push(self, report: DailyReport) -> dict:
        """执行所有启用的推送通道，返回执行结果"""
        results = {"email": False, "cli": "", "web": ""}

        # 邮箱推送
        if self.email_pusher:
            results["email"] = self.email_pusher.send(report)

        # CLI输出（始终可用）
        results["cli"] = self.cli_pusher.send(report)

        # 网页生成
        if self.web_pusher:
            results["web"] = self.web_pusher.save(report)

        return results
