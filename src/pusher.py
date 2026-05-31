"""推送模块 — 多通道分发（邮箱 + 微信 + CLI + Web）"""

import os
import logging
import smtplib
from abc import ABC, abstractmethod
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from datetime import datetime
from typing import Dict, List, Optional

import requests

from src.models import DailyReport
from src.formatter import format_markdown, format_plain, format_html_page, format_email_html

logger = logging.getLogger(__name__)


# ═══════════════════════════════════════════════════════════
# 抽象基类
# ═══════════════════════════════════════════════════════════

class BasePusher(ABC):
    """推送通道基类 — 所有推送渠道继承此类"""

    channel_name: str = "base"

    def __init__(self, config: dict = None):
        self.config = config or {}

    def is_configured(self) -> bool:
        """检查该通道是否已正确配置（凭证齐全），子类可按需覆写"""
        return True

    @abstractmethod
    def send(self, report: DailyReport) -> bool:
        """执行推送，返回 True/False"""
        ...


# ═══════════════════════════════════════════════════════════
# 邮箱推送（QQ邮箱 + 163邮箱）
# ═══════════════════════════════════════════════════════════

class EmailPusher(BasePusher):
    """邮箱推送 — 支持 QQ邮箱(smtp.qq.com:587/STARTTLS) 和 163邮箱(smtp.163.com:465/SSL)"""

    channel_name = "email"

    def __init__(self, config: dict = None):
        super().__init__(config)
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

        msg = MIMEMultipart("alternative")
        msg["Subject"] = subject
        msg["From"] = self.user
        msg["To"] = self.recipient

        # 纯文本 + 精美HTML双版本
        msg.attach(MIMEText(format_plain(report), "plain", "utf-8"))
        msg.attach(MIMEText(format_email_html(report), "html", "utf-8"))

        try:
            if self.port == 465:
                # SSL直连（163邮箱推荐）
                with smtplib.SMTP_SSL(self.host, self.port, timeout=15) as server:
                    server.login(self.user, self.password)
                    server.sendmail(self.user, [self.recipient], msg.as_string())
            else:
                # STARTTLS升级（QQ邮箱推荐 587）
                with smtplib.SMTP(self.host, self.port, timeout=15) as server:
                    server.starttls()
                    server.login(self.user, self.password)
                    server.sendmail(self.user, [self.recipient], msg.as_string())
            logger.info(f"邮件发送成功 (via {self.host}:{self.port})")
            return True
        except Exception as e:
            logger.error(f"邮件发送失败 ({self.host}:{self.port}): {e}")
            return False


# ═══════════════════════════════════════════════════════════
# 微信推送（Server酱）
# ═══════════════════════════════════════════════════════════

class WeChatPusher(BasePusher):
    """微信推送 — 通过Server酱(ServerChan)推送到微信

    使用步骤:
    1. 前往 https://sct.ftqq.com/ 登录获取 SendKey
    2. 设置环境变量 WECHAT_SENDKEY=你的SendKey
    3. 在微信中关注「方糖」公众号即可接收推送
    """

    channel_name = "wechat"

    def __init__(self, config: dict = None):
        super().__init__(config)
        self.sendkey = os.getenv("WECHAT_SENDKEY", "")
        self.api_url = "https://sctapi.ftqq.com"

    def is_configured(self) -> bool:
        return bool(self.sendkey)

    def send(self, report: DailyReport) -> bool:
        """通过Server酱发送微信推送"""
        if not self.is_configured():
            logger.warning("微信推送未配置 (WECHAT_SENDKEY为空)，跳过")
            return False

        title = f"📊 每日A股速递 | {report.date}"
        body = format_markdown(report)

        try:
            resp = requests.post(
                f"{self.api_url}/{self.sendkey}.send",
                data={"title": title, "desp": body},
                timeout=15,
            )
            result = resp.json()
            if result.get("code") == 0:
                logger.info("微信推送成功 (Server酱)")
                return True
            else:
                logger.error(f"微信推送失败: {result.get('message', '未知错误')}")
                return False
        except Exception as e:
            logger.error(f"微信推送异常: {e}")
            return False


# ═══════════════════════════════════════════════════════════
# 命令行输出
# ═══════════════════════════════════════════════════════════

class CLIPusher(BasePusher):
    """命令行推送 — 格式化文本输出到终端"""

    channel_name = "cli"

    def send(self, report: DailyReport) -> bool:
        """生成格式化文本，存入 self.output_text 供调用方打印"""
        self.output_text = format_plain(report)
        return True


# ═══════════════════════════════════════════════════════════
# 网页推送（GitHub Pages）
# ═══════════════════════════════════════════════════════════

class WebPusher(BasePusher):
    """网页推送 — 生成HTML到docs/目录（GitHub Pages）"""

    channel_name = "web"

    def __init__(self, config: dict = None, output_dir: str = "docs"):
        super().__init__(config)
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

    def send(self, report: DailyReport) -> bool:
        """保存报告HTML到docs/目录，路径存入 self.output_path"""
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

        self.output_path = filepath
        return True


# ═══════════════════════════════════════════════════════════
# 通道注册表 — 新增通道只需在此添加一行
# ═══════════════════════════════════════════════════════════

PUSHER_REGISTRY: Dict[str, type] = {
    "email": EmailPusher,
    "wechat": WeChatPusher,
    "cli": CLIPusher,
    "web": WebPusher,
}


# ═══════════════════════════════════════════════════════════
# 推送管理器
# ═══════════════════════════════════════════════════════════

class Pusher:
    """推送管理器 — 动态加载推送通道"""

    def __init__(self, config: dict, selected_channels: Optional[List[str]] = None):
        self.config = config
        push_config = config.get("push", {})
        self.channels: Dict[str, BasePusher] = {}

        for channel_key, pusher_cls in PUSHER_REGISTRY.items():
            # 判断是否启用该通道
            if selected_channels is not None:
                # CLI 明确指定 → 只看 CLI 参数
                enabled = channel_key in selected_channels
            else:
                # 回退到 YAML 配置
                channel_cfg = push_config.get(channel_key, {})
                enabled = channel_cfg.get("enabled", False)

                # CLI 通道默认开启（除非显式设为 false）
                if channel_key == "cli" and "cli" not in push_config:
                    enabled = True

            if enabled:
                try:
                    instance = pusher_cls(config=config)
                    self.channels[channel_key] = instance
                    logger.info(f"推送通道 [{channel_key}] 已启用")
                except Exception as e:
                    logger.error(f"推送通道 [{channel_key}] 初始化失败: {e}")

    def push(self, report: DailyReport) -> dict:
        """执行所有启用的推送通道，返回各通道执行结果"""
        results = {}
        for channel_key, pusher in self.channels.items():
            try:
                success = pusher.send(report)
                results[channel_key] = success
            except Exception as e:
                logger.error(f"推送通道 [{channel_key}] 执行异常: {e}")
                results[channel_key] = False
        return results
