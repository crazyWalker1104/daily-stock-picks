"""双重确认引擎 — 资金流向×新闻情绪交叉验证

Phase 2.1 核心模块。AI 推荐后处理：用可获取的市场资金数据验证每条推荐方向，
信号一致时加成信心度，背离时标注风险。让推荐从"拍脑袋"进化到"数据佐证"。

数据依赖：
  - 北向资金（akshare stock_hsgt_fund_flow_summary_em）— 外资宏观态度
  - 主力资金趋势（akshare stock_market_fund_flow）— 市场整体主力方向
  - 新闻情绪（聚合器关键词记分）— 板块级市场关注度

不依赖 push2.eastmoney.com（已被墙），仅用 akshare 中非 push2 端点。
"""

import logging
from datetime import datetime
from typing import Dict, List, Optional, Tuple

from src.models import NewsItem, Recommendation

logger = logging.getLogger(__name__)

# ── 情绪分析词典 ─────────────────────────────────────────────────
# 正面信号词（新闻中利多含义）
POSITIVE_SIGNALS = [
    "涨停", "大涨", "拉升", "突破", "新高", "放量",
    "利好", "增持", "买入", "推荐", "看好", "超预期",
    "预增", "扭亏", "反弹", "反转", "加速", "扩产",
    "中标", "获批", "补贴", "政策支持", "国产替代",
]

# 负面信号词（新闻中利空含义）
NEGATIVE_SIGNALS = [
    "跌停", "大跌", "跳水", "跌破", "新低", "缩量",
    "利空", "减持", "卖出", "下调", "警告", "低于预期",
    "预亏", "亏损", "退市", "立案", "处罚", "暴雷",
    "停工", "裁员", "诉讼", "债务违约",
]

# 板块关键词映射（推荐中的板块名 → 新闻关键词）
SECTOR_KEYWORD_MAP = {
    "AI": ["AI", "人工智能", "大模型", "GPT", "Copilot", "AIGC", "Agent"],
    "算力": ["算力", "GPU", "数据中心", "服务器"],
    "芯片": ["芯片", "半导体", "光刻", "晶圆", "封装"],
    "CPO": ["CPO", "光模块", "光通信", "光引擎", "硅光"],
    "机器人": ["机器人", "具身智能", "人形", "伺服", "减速器"],
    "自动驾驶": ["自动驾驶", "智能驾驶", "智驾", "无人驾驶"],
    "低空经济": ["低空", "无人机", "eVTOL", "飞行汽车"],
    "光伏": ["光伏", "硅料", "硅片", "组件", "逆变器", "TOPCon"],
    "储能": ["储能", "电池", "钠离子", "液流"],
    "锂电": ["锂电", "锂电池", "正极", "负极", "电解液", "隔膜"],
    "新能源车": ["新能源车", "电动车", "新势力", "比亚迪"],
    "固态电池": ["固态电池", "全固态", "半固态"],
    "白酒": ["白酒", "茅台", "五粮液", "消费"],
    "医药": ["医药", "创新药", "CXO", "中药", "医疗器械", "减肥药"],
    "券商": ["券商", "证券", "投行", "经纪"],
    "银行": ["银行", "信贷", "息差"],
    "房地产": ["房地产", "地产", "楼市", "房贷"],
    "煤炭": ["煤炭", "煤价", "煤企"],
    "有色": ["有色", "铜", "铝", "稀土", "黄金"],
    "化工": ["化工", "氟化工", "磷化", "石化"],
    "军工": ["军工", "国防", "装备", "导弹"],
    "消费": ["消费", "零售", "免税", "医美"],
    "电力": ["电力", "电网", "特高压", "虚拟电厂"],
}

# ── 引擎核心 ───────────────────────────────────────────────────


class DualConfirmationEngine:
    """双重确认引擎：用资金数据+新闻情绪验证AI推荐方向"""

    def __init__(self):
        self.north_bound: dict = {}
        self.flow_trend: dict = {}
        self.news_list: List[NewsItem] = []
        self._news_sentiment_cache: Dict[str, dict] = {}

    # ── 数据加载 ──────────────────────────────────────────────

    def load_market_data(self, market_data: dict) -> None:
        """加载市场数据（来自 market_data.collect_market_data()）

        Args:
            market_data: 市场数据 dict，含 north_bound / flow_trend 等
        """
        self.north_bound = market_data.get("north_bound", {}) or {}
        self.flow_trend = market_data.get("flow_trend", {}) or {}
        self._news_sentiment_cache = {}  # 清空缓存

    def load_news(self, news_list: List[NewsItem]) -> None:
        """加载原始新闻列表（用于情绪分析）"""
        self.news_list = news_list
        self._news_sentiment_cache = {}

    # ── 信号提取 ──────────────────────────────────────────────

    def get_fund_signal(self) -> dict:
        """提取综合资金流向信号

        Returns:
            {"direction": "inflow"|"outflow"|"neutral",
             "strength": "strong"|"moderate"|"weak",
             "source": "north_bound"|"none",
             "detail": str}
        """
        # 优先使用北向资金（最可靠的数据源）
        if self.north_bound:
            total = self.north_bound.get("total_net", 0) or 0
            if total > 30:
                return {"direction": "inflow", "strength": "strong",
                        "source": "north_bound",
                        "detail": f"北向资金大幅净流入 {total:+.2f}亿"}
            elif total > 10:
                return {"direction": "inflow", "strength": "moderate",
                        "source": "north_bound",
                        "detail": f"北向资金净流入 {total:+.2f}亿"}
            elif total > 0:
                return {"direction": "inflow", "strength": "weak",
                        "source": "north_bound",
                        "detail": f"北向资金小幅净流入 {total:+.2f}亿"}
            elif total > -10:
                return {"direction": "neutral", "strength": "weak",
                        "source": "north_bound",
                        "detail": f"北向资金基本持平 {total:+.2f}亿"}
            elif total > -30:
                return {"direction": "outflow", "strength": "moderate",
                        "source": "north_bound",
                        "detail": f"北向资金净流出 {total:+.2f}亿"}
            else:
                return {"direction": "outflow", "strength": "strong",
                        "source": "north_bound",
                        "detail": f"北向资金大幅净流出 {total:+.2f}亿"}

        # 无北向数据，尝试用主力趋势
        if self.flow_trend:
            bias = self.flow_trend.get("recent_bias", "")
            if bias == "偏多":
                return {"direction": "inflow", "strength": "moderate",
                        "source": "main_force",
                        "detail": "近5日主力资金偏多"}
            elif bias == "偏空":
                return {"direction": "outflow", "strength": "moderate",
                        "source": "main_force",
                        "detail": "近5日主力资金偏空"}

        return {"direction": "neutral", "strength": "weak",
                "source": "none", "detail": "无可用资金数据"}

    def _match_sector_keywords(self, sector: str) -> list:
        """模糊匹配板块关键词（支持 "AI应用" → "AI", "电子/AI算力" → "AI"+"算力"+"芯片"）"""
        matched = set()

        # 1. 精确匹配
        if sector in SECTOR_KEYWORD_MAP:
            matched.update(SECTOR_KEYWORD_MAP[sector])

        # 2. 模糊匹配：板块名包含 keyword 字典中的 key，或 key 包含在板块名中
        for key, keywords in SECTOR_KEYWORD_MAP.items():
            if key in sector or sector in key:
                matched.update(keywords)

        # 3. 分割匹配：处理 "电子/AI算力"、"AI应用/大模型" 等复合板块名
        parts = sector.replace("/", " ").replace("、", " ").replace("（", " ").replace("）", " ").split()
        for part in parts:
            if part in SECTOR_KEYWORD_MAP:
                matched.update(SECTOR_KEYWORD_MAP[part])
            # 二级模糊：part 是否包含 key
            for key, keywords in SECTOR_KEYWORD_MAP.items():
                if key in part or part in key:
                    matched.update(keywords)

        return list(matched) if matched else [sector]

    def analyze_news_sentiment(self, sector: str) -> dict:
        """分析指定板块的新闻情绪

        通过关键词匹配，统计与该板块相关的新闻中的利多/利空信号。
        优先使用 SECTOR_KEYWORD_MAP 做板块→关键词映射，
        找不到映射时将 sector 名本身作为关键词匹配。

        Returns:
            {"positive_count": int, "negative_count": int,
             "total_relevant": int, "net_sentiment": "positive"|"negative"|"neutral",
             "score": float}
        """
        # 缓存命中
        if sector in self._news_sentiment_cache:
            return self._news_sentiment_cache[sector]

        # 获取板块相关关键词（模糊匹配）
        sector_kw = self._match_sector_keywords(sector)

        pos_count = 0
        neg_count = 0
        relevant_news = 0

        for news in self.news_list:
            text = news.title + news.content
            # 检查是否与该板块相关
            if not any(kw in text for kw in sector_kw):
                continue
            relevant_news += 1

            # 统计正面/负面信号词
            pos_count += sum(1 for w in POSITIVE_SIGNALS if w in text)
            neg_count += sum(1 for w in NEGATIVE_SIGNALS if w in text)

        # 计算净情绪（阈值为正负1，因为财经新闻中情绪信号稀疏）
        net = pos_count - neg_count
        if net >= 1:
            sentiment = "positive"
        elif net <= -1:
            sentiment = "negative"
        else:
            sentiment = "neutral"

        # 归一化分数（-1 到 +1）
        total = max(pos_count + neg_count, 1)
        score = round(net / max(total, 1), 2)

        result = {
            "positive_count": pos_count,
            "negative_count": neg_count,
            "total_relevant": relevant_news,
            "net_sentiment": sentiment,
            "score": score,
        }
        self._news_sentiment_cache[sector] = result
        return result

    # ── 双重确认逻辑 ──────────────────────────────────────────

    def _check_alignment(
        self, fund_signal: dict, news_sentiment: dict
    ) -> Tuple[str, str]:
        """判断资金信号与新闻情绪的匹配度

        Returns:
            (alignment: str, explanation: str)
            alignment ∈ {"confirmed_bullish", "confirmed_bearish",
                         "divergent", "uncertain"}
        """
        fund_dir = fund_signal["direction"]
        news_dir = news_sentiment["net_sentiment"]

        # 同向看多
        if fund_dir == "inflow" and news_dir == "positive":
            return (
                "confirmed_bullish",
                f"资金流入({fund_signal['detail']})与新闻情绪偏多一致，信号确认",
            )
        # 同向看空
        if fund_dir == "outflow" and news_dir == "negative":
            return (
                "confirmed_bearish",
                f"资金流出({fund_signal['detail']})与新闻情绪偏空一致，需警惕",
            )
        # 背离：新闻看多但资金流出
        if news_dir == "positive" and fund_dir == "outflow":
            return (
                "divergent",
                f"新闻情绪偏多但{fund_signal['detail']}，外资与舆情背离，谨慎追高",
            )
        # 背离：新闻看空但资金流入
        if news_dir == "negative" and fund_dir == "inflow":
            return (
                "divergent",
                f"新闻情绪偏空但{fund_signal['detail']}，可能有资金逆势布局",
            )
        # 数据不足
        if fund_signal["source"] == "none" and news_sentiment["total_relevant"] == 0:
            return ("uncertain", "该板块缺乏资金和新闻双重数据，无法交叉验证")

        return (
            "uncertain",
            f"资金信号({fund_dir})与新闻情绪({news_dir})方向不明确，建议观望",
        )

    def _adjust_confidence(
        self, original: str, alignment: str
    ) -> Tuple[str, str]:
        """根据确认结果调整信心度

        Returns:
            (adjusted_confidence: str, adjustment_note: str)
        """
        confidence_levels = {"低": 1, "中": 2, "高": 3}
        reverse = {1: "低", 2: "中", 3: "高"}

        level = confidence_levels.get(original, 2)

        if alignment == "confirmed_bullish":
            new_level = min(level + 1, 3)
            if new_level > level:
                return reverse[new_level], "↑ 资金+情绪双确认，信心度提升"
            return original, "✓ 资金+情绪双确认，维持当前评级"
        elif alignment == "confirmed_bearish":
            new_level = max(level - 1, 1)
            if new_level < level:
                return reverse[new_level], "↓ 资金与情绪双看空，信心度下调"
            return original, "⚠️ 资金与情绪双看空，注意风险"
        elif alignment == "divergent":
            new_level = max(level - 1, 1)
            if new_level < level:
                return reverse[new_level], "↓ 资金与舆情背离，信心度下调"
            return original, "⚠️ 资金与舆情背离，需谨慎"
        else:
            return original, "— 数据不足，维持原始评级"

    # ── 主入口 ─────────────────────────────────────────────────

    def confirm(self, recommendations: List[Recommendation]) -> List[Recommendation]:
        """对每条AI推荐进行双重确认，返回增强后的推荐列表

        每条推荐的 confidence/risk 字段可能被调整，新增 confirmation 元数据。
        """
        if not recommendations:
            return recommendations

        fund_signal = self.get_fund_signal()
        logger.info(
            f"双重确认引擎启动 — 资金信号: {fund_signal['direction']}"
            f"({fund_signal['source']}) | 新闻样本: {len(self.news_list)}条"
        )

        confirmed = []
        for rec in recommendations:
            # 1. 分析该板块的新闻情绪
            news_sentiment = self.analyze_news_sentiment(rec.sector)

            # 2. 交叉验证
            alignment, explanation = self._check_alignment(fund_signal, news_sentiment)

            # 3. 调整信心度
            new_confidence, adj_note = self._adjust_confidence(
                rec.confidence, alignment
            )

            # 4. 生成增强风险提示
            enhanced_risk = rec.risk
            if alignment == "divergent":
                enhanced_risk = f"[背离警告] {explanation}。{rec.risk}"
            elif alignment == "confirmed_bearish":
                enhanced_risk = f"[双看空] {explanation}。{rec.risk}"

            # 5. 更新推荐
            rec.confidence = new_confidence
            rec.risk = enhanced_risk
            # 添加确认元数据（不影响 JSON 序列化，dataclass 会忽略未知字段）
            if not hasattr(rec, "confirmation"):
                rec.confirmation = {}  # type: ignore
            rec.confirmation = {  # type: ignore
                "alignment": alignment,
                "explanation": explanation,
                "adjustment": adj_note,
                "fund_signal": fund_signal,
                "news_sentiment": news_sentiment,
            }

            logger.info(
                f"  [{rec.sector}] {rec.confidence} | {alignment} | {adj_note}"
            )
            confirmed.append(rec)

        return confirmed

    def get_summary(self, confirmed_recs: List[Recommendation]) -> str:
        """生成确认摘要（用于追加到AI Prompt的输出中）"""
        if not confirmed_recs:
            return ""

        lines = ["## 🔍 双重确认引擎验证结果", ""]

        fund = self.get_fund_signal()
        lines.append(f"**资金面信号**：{fund['detail']}")
        lines.append("")

        for rec in confirmed_recs:
            if hasattr(rec, "confirmation") and rec.confirmation:
                conf = rec.confirmation
                align = conf.get("alignment", "?")
                icon = {
                    "confirmed_bullish": "🟢",
                    "confirmed_bearish": "🔴",
                    "divergent": "⚠️",
                    "uncertain": "❓",
                }.get(align, "—")

                lines.append(
                    f"{icon} **{rec.sector}**：{conf.get('explanation', '')}"
                )
                if conf.get("adjustment", "").startswith("↑") or conf.get(
                    "adjustment", ""
                ).startswith("↓"):
                    lines.append(f"   → {conf['adjustment']}")

        lines.append("")
        return "\n".join(lines)


# ── 便捷函数 ───────────────────────────────────────────────────

_engine: Optional[DualConfirmationEngine] = None


def get_engine() -> DualConfirmationEngine:
    """获取全局引擎实例（单例模式）"""
    global _engine
    if _engine is None:
        _engine = DualConfirmationEngine()
    return _engine


def confirm_recommendations(
    recommendations: List[Recommendation],
    market_data: dict,
    news_list: List[NewsItem],
) -> List[Recommendation]:
    """便捷函数：一站式双重确认

    Args:
        recommendations: AI生成的原始推荐列表
        market_data: 市场数据（来自 collect_market_data()）
        news_list: 原始新闻列表

    Returns:
        增强后的推荐列表（confidence/risk 可能已调整）
    """
    engine = get_engine()
    engine.load_market_data(market_data)
    engine.load_news(news_list)
    return engine.confirm(recommendations)
