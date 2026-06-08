"""AI分析模块 — 调用DeepSeek API进行综合研判"""

import json
import logging
import os
import re
from datetime import datetime
from typing import List

import httpx
from openai import OpenAI

from src.models import Recommendation, DailyReport

logger = logging.getLogger(__name__)

# AI System Prompt
SYSTEM_PROMPT = """你是一位资深的A股短线分析师，擅长从海量财经信息中捕捉板块轮动和短线机会。

你的任务：
1. 仔细阅读提供的财经新闻、研报摘要和市场数据
2. 识别今日最值得关注的3-5个板块/题材（短线1-3天视角）
3. 每个板块推荐1-2只代表性标的，必须给出股票代码和简称
4. 给出短线看涨的核心逻辑，必须引用具体的新闻事件或数据
5. 标注主要风险点

分析要点：
- 重点关注：政策催化 > 资金流入 > 业绩超预期 > 题材共振
- 结合北向资金流向、龙虎榜机构动向、板块资金净流入
- 区分"短期炒作"和"趋势性机会"，在confidence中标注
- 避免追高建议，优先关注处于启动初期或回调到位的板块

输出格式（严格JSON）：
{
  "recommendations": [
    {
      "sector": "板块名称",
      "confidence": "高/中/低",
      "logic": "推荐逻辑（引���具体事件或数据，80字内）",
      "stocks": [{"name": "股票简称", "code": "6位代码"}],
      "catalyst": "核心催化事件（50字内）",
      "risk": "主要风险（50字内）"
    }
  ],
  "summary": "今日市场总览（用1-2句话概括今日主要看点）",
  "risk_warning": "整体风险提示（关注大盘风险、外围市场等）"
}

注意：
- 如果某板块没有可推荐的具体标的，请跳过
- 只输出JSON，不要输出其他内容
- 推荐的股票必须是A股实际存在的标的"""


class AIAnalyzer:
    """AI分析器 — 负责调用LLM进行综合研判"""

    def __init__(self, config: dict):
        self.config = config
        ai_config = config.get("ai", {})

        self.provider = ai_config.get("provider", "deepseek")
        self.model = ai_config.get("model", "deepseek-chat")
        self.temperature = ai_config.get("temperature", 0.3)
        self.max_tokens = ai_config.get("max_tokens", 2000)

        # 初始化客户端
        api_key = None
        base_url = None

        if self.provider == "deepseek":
            import os
            api_key = os.getenv("DEEPSEEK_API_KEY")
            base_url = os.getenv("DEEPSEEK_BASE_URL", "https://api.deepseek.com")
        elif self.provider == "anthropic":
            import os
            api_key = os.getenv("ANTHROPIC_API_KEY")
            base_url = os.getenv("ANTHROPIC_BASE_URL", "https://api.anthropic.com")

        if not api_key:
            logger.warning("未设置API Key，AI分析将不可用")
            self.client = None
        else:
            # 禁用系统代理（直连 DeepSeek API 更快，避免代理 SSLEOFError）
            http_client = httpx.Client(trust_env=False)
            self.client = OpenAI(
                api_key=api_key,
                base_url=base_url,
                http_client=http_client,
            )

    def analyze(self, news_text: str, date: str = None,
                market_context: str = "") -> DailyReport:
        """分析新闻数据，生成每日推荐报告

        Args:
            news_text: 聚合后的新闻文本
            date: 日期字符串 YYYY-MM-DD
            market_context: 市场实况数据（指数/资金流等），由 market_data 模块生成
        """
        if date is None:
            date = datetime.now().strftime("%Y-%m-%d")

        if not news_text.strip():
            logger.warning("无新闻数据，生成空报告")
            return DailyReport(
                date=date,
                recommendations=[],
                raw_news_count=0,
                sources_used=[],
            )

        if self.client is None:
            logger.error("AI客户端未初始化，无法分析")
            return DailyReport(
                date=date,
                recommendations=[],
                raw_news_count=news_text.count("\n[") + 1,
                sources_used=[],
            )

        # 构造用户消息（需控制token量）
        # 新闻文本限额 = 总量 - 市场数据占用
        market_overhead = len(market_context) if market_context else 0
        max_len = 12000 - market_overhead
        if len(news_text) > max_len:
            news_text = news_text[:max_len] + "\n...(内容已截断)"

        # 组装 Prompt：市场数据 + 新闻
        sections = [f"以下是今日（{date}）的财经信息，请进行分析：\n"]

        if market_context:
            sections.append(market_context)
            sections.append("---\n")

        sections.append("## 📰 今日财经新闻及研报汇总\n")
        sections.append(news_text)
        sections.append("\n请严格按照JSON格式输出分析结果。")

        user_prompt = "\n".join(sections)

        try:
            logger.info(f"调用 {self.provider} API ({self.model}) 进行分析...")

            response = self.client.chat.completions.create(
                model=self.model,
                messages=[
                    {"role": "system", "content": SYSTEM_PROMPT},
                    {"role": "user", "content": user_prompt},
                ],
                temperature=self.temperature,
                max_tokens=self.max_tokens,
            )

            raw_output = response.choices[0].message.content.strip()
            logger.info(f"AI分析完成，输出长度: {len(raw_output)} 字符")

            return self._parse_response(raw_output, date, news_text)

        except Exception as e:
            logger.error(f"AI API调用失败: {e}", exc_info=True)
            # 返回空报告而非崩溃
            return DailyReport(
                date=date,
                recommendations=[],
                raw_news_count=news_text.count("\n[") + 1,
                sources_used=[],
            )

    def _parse_response(self, raw: str, date: str, news_text: str) -> DailyReport:
        """解析AI返回的JSON，提取推荐列表"""
        try:
            # 尝试提取JSON块（处理模型可能在JSON外用markdown包裹的情况）
            json_match = re.search(r'\{[\s\S]*"recommendations"[\s\S]*\}', raw)
            if json_match:
                raw = json_match.group()

            data = json.loads(raw)
            recs_raw = data.get("recommendations", [])

            recommendations = []
            for item in recs_raw:
                try:
                    recommendations.append(Recommendation(
                        sector=item.get("sector", "未知"),
                        confidence=item.get("confidence", "中"),
                        logic=item.get("logic", ""),
                        stocks=item.get("stocks", []),
                        catalyst=item.get("catalyst", ""),
                        risk=item.get("risk", ""),
                        source=[],  # AI会自动引用
                    ))
                except Exception as e:
                    logger.warning(f"解析单条推荐失败: {e}")

            # 提取来源信息
            sources = list(set(
                re.findall(r'【(\w+)】', news_text)
            ))

            return DailyReport(
                date=date,
                recommendations=recommendations,
                raw_news_count=news_text.count("\n[") + 1,
                sources_used=sources,
                generated_at=datetime.now().isoformat(),
            )

        except json.JSONDecodeError as e:
            logger.error(f"AI输出JSON解析失败: {e}\n原始输出: {raw[:500]}")
            return DailyReport(
                date=date,
                recommendations=[],
                raw_news_count=news_text.count("\n[") + 1,
                sources_used=[],
            )
