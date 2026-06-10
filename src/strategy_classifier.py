"""策略分层引擎 — 将AI推荐归类到追强/抄底/事件驱动三条策略线

Phase 3.3 核心模块。在技术面过滤之后运行，利用已有的 technical metadata
对每条推荐进行三维打分（momentum / bottom_fish / event），输出策略标签、
得分和操作建议，注入到 Recommendation 的动态属性中。

使用 Engine + Singleton + Convenience 模式，与 confirmation / technical_filter 一致。
"""

import logging
from typing import Dict, List, Optional

from src.models import Recommendation

logger = logging.getLogger(__name__)

# ── 配置默认值 ──────────────────────────────────────────────────

DEFAULT_CONFIG = {
    "enabled": True,
    "min_score_to_classify": 15,       # 最低分才标记策略（否则"观望"）
    "min_margin": 5,                    # top1 vs top2 最小分差（否则"观望"）
    "momentum": {
        "tech_score_high": 80,          # 追强技术分高阈值
        "tech_score_mid": 70,           # 追强技术分中阈值
    },
    "bottom_fish": {
        "tech_score_max": 74,           # 抄底技术分上限
        "tech_score_min": 60,           # 抄底技术分下限
    },
    "event": {
        "tech_score_max": 79,           # 事件驱动技术分上限
        "tech_score_min": 60,           # 事件驱动技术分下限
    },
}

# 强催化事件关键词
STRONG_CATALYST_KEYWORDS = [
    "政策", "发布", "获批", "突破", "签约", "中标",
    "上市", "量产", "涨价", "涨价", "订单", "落地",
    "首次", "重磅", "授权", "通过", "注册",
]

# 政策板块关键词
POLICY_SECTOR_KEYWORDS = [
    "政策", "新基建", "国产替代", "信创", "碳中和",
    "数据要素", "AI", "人工智能", "半导体",
]


# ── 工具函数 ────────────────────────────────────────────────────


def _has_any_keyword(text: str, keywords: List[str]) -> bool:
    """检查文本是否包含任意关键词"""
    if not text:
        return False
    return any(kw in text for kw in keywords)


def _extract_signal_detail(signals: list, signal_type: str) -> Optional[dict]:
    """从信号列表中提取指定类型的信号详情"""
    for sig in signals:
        if sig.get("type") == signal_type:
            return sig.get("detail", {})
    return None


def _stock_avg_change(technical: dict) -> float:
    """计算板块内所有标的的平均涨跌幅"""
    results = technical.get("stock_results", [])
    changes = []
    for r in results:
        if r.get("passed") and r.get("quote"):
            chg = r["quote"].get("change_pct")
            if chg is not None:
                changes.append(float(chg))
    return sum(changes) / len(changes) if changes else 0.0


# ── 引擎核心 ────────────────────────────────────────────────────


class StrategyClassifierEngine:
    """策略分类引擎 — 规则打分，三维归类"""

    def __init__(self, config: dict = None):
        self.config = {**DEFAULT_CONFIG, **(config or {})}
        self._stats = {"追强": 0, "抄底": 0, "事件驱动": 0, "观望": 0}

    # ── 三大维度打分 ──────────────────────────────────────────

    def _score_momentum(self, rec: Recommendation) -> int:
        """追强得分：趋势强劲、多头排列、温和上涨"""
        score = 0
        technical = getattr(rec, "technical", {})
        results = technical.get("stock_results", [])

        for r in results:
            if not r.get("passed"):
                continue

            ts = r.get("technical_score", 50)
            if ts >= self.config["momentum"]["tech_score_high"]:
                score += 25
            elif ts >= self.config["momentum"]["tech_score_mid"]:
                score += 15

            # MA位置
            ma_detail = _extract_signal_detail(r.get("signals", []), "ma_position")
            if ma_detail:
                status = ma_detail.get("status", "")
                if "bullish" in status:
                    score += 25
                elif "above_ma20" == status:
                    score += 20

            # 涨跌幅
            quote = r.get("quote", {})
            chg = quote.get("change_pct")
            if chg is not None:
                chg = float(chg)
                if 0 < chg <= 5:
                    score += 15
                elif chg > 5:
                    score += 5  # 有点高，但不扣

            # 换手率
            tr = quote.get("turnover_rate")
            if tr is not None:
                tr = float(tr)
                if 1 <= tr <= 5:
                    score += 10

            # 连续上涨
            cons = _extract_signal_detail(r.get("signals", []), "consecutive_rise")
            if cons:
                # 有信号说明在涨，检查不超额
                if r.get("technical_score", 50) >= 70:
                    score += 10

        # 多标的取平均
        n = max(1, len([r for r in results if r.get("passed")]))
        return min(100, score // n)

    def _score_bottom_fish(self, rec: Recommendation) -> int:
        """抄底得分：回调到位、企稳信号、强催化"""
        score = 0
        technical = getattr(rec, "technical", {})
        results = technical.get("stock_results", [])

        for r in results:
            if not r.get("passed"):
                continue

            ts = r.get("technical_score", 50)
            cfg = self.config["bottom_fish"]
            if cfg["tech_score_min"] <= ts <= cfg["tech_score_max"]:
                score += 15

            # MA位置：MA20之下 → 回调中
            ma_detail = _extract_signal_detail(r.get("signals", []), "ma_position")
            if ma_detail:
                status = ma_detail.get("status", "")
                if status == "below_ma20":
                    score += 15

            # 涨跌幅：温和回调
            quote = r.get("quote", {})
            chg = quote.get("change_pct")
            if chg is not None:
                chg = float(chg)
                if -5 <= chg <= 0:
                    score += 15
                elif -10 <= chg < -5:
                    score += 10

            # 缩量筑底
            tr = quote.get("turnover_rate")
            if tr is not None and float(tr) < 1:
                score += 10

        # 强催化加分
        if _has_any_keyword(rec.catalyst, STRONG_CATALYST_KEYWORDS):
            score += 15
        if _has_any_keyword(rec.logic, STRONG_CATALYST_KEYWORDS):
            score += 10

        n = max(1, len([r for r in results if r.get("passed")]))
        return min(100, score // n)

    def _score_event(self, rec: Recommendation) -> int:
        """事件驱动得分：强政策、重磅事件、中等技术面"""
        score = 0
        technical = getattr(rec, "technical", {})
        results = technical.get("stock_results", [])

        # 催化文本强度
        catalyst_len = len(rec.catalyst) if rec.catalyst else 0
        if catalyst_len > 30 and _has_any_keyword(rec.catalyst, STRONG_CATALYST_KEYWORDS):
            score += 25
        elif catalyst_len > 20:
            score += 10

        # AI 信心度
        if rec.confidence == "高":
            score += 15
        elif rec.confidence == "中":
            score += 8

        # 板块政策属性
        if _has_any_keyword(rec.sector, POLICY_SECTOR_KEYWORDS):
            score += 10

        for r in results:
            if not r.get("passed"):
                continue
            ts = r.get("technical_score", 50)
            cfg = self.config["event"]
            if cfg["tech_score_min"] <= ts <= cfg["tech_score_max"]:
                score += 10

        n = max(1, len([r for r in results if r.get("passed")]))
        return min(100, score // n)

    # ── 策略建议 ────────────────────────────────────────────────

    _ADVICE = {
        "追强": "趋势确立，沿MA5跟进，止损设MA10破位",
        "抄底": "左侧布局，分批建仓，止损设近期低点-3%",
        "事件驱动": "关注催化兑现节点，风控优先，快进快出",
        "观望": "信号不明，建议等待更明确的入场时机",
    }

    # ── 分类 ────────────────────────────────────────────────────

    def classify(self, rec: Recommendation) -> dict:
        """对单条推荐打分归类

        Returns:
            {"strategy": "追强", "score": 72, "scores": {...}, "advice": "..."}
        """
        scores = {
            "追强": self._score_momentum(rec),
            "抄底": self._score_bottom_fish(rec),
            "事件驱动": self._score_event(rec),
        }

        sorted_items = sorted(scores.items(), key=lambda x: x[1], reverse=True)
        top_strategy, top_score = sorted_items[0]
        second_score = sorted_items[1][1] if len(sorted_items) > 1 else 0

        margin = self.config["min_margin"]
        min_score = self.config["min_score_to_classify"]

        if top_score < min_score:
            strategy = "观望"
        elif top_score - second_score < margin:
            strategy = "观望"
        else:
            strategy = top_strategy

        return {
            "strategy": strategy,
            "score": top_score,
            "scores": scores,
            "advice": self._ADVICE.get(strategy, ""),
        }

    def apply(self, recommendations: List[Recommendation]) -> List[Recommendation]:
        """批量分类并注入元数据到每条推荐

        为每条推荐动态添加: strategy, strategy_score, strategy_advice
        """
        if not recommendations or not self.config.get("enabled", True):
            return recommendations

        self._stats = {"追强": 0, "抄底": 0, "事件驱动": 0, "观望": 0}

        for rec in recommendations:
            try:
                result = self.classify(rec)
                rec.strategy = result["strategy"]           # type: ignore
                rec.strategy_score = result["score"]        # type: ignore
                rec.strategy_advice = result["advice"]      # type: ignore
                rec.strategy_scores = result["scores"]      # type: ignore

                self._stats[result["strategy"]] += 1
                logger.debug(
                    f"[{rec.sector}] → {result['strategy']} "
                    f"(追强{result['scores']['追强']} "
                    f"抄底{result['scores']['抄底']} "
                    f"事件{result['scores']['事件驱动']})"
                )
            except Exception as e:
                logger.warning(f"策略分类异常 [{rec.sector}]: {e}")
                rec.strategy = "观望"                        # type: ignore
                rec.strategy_score = 0                       # type: ignore
                rec.strategy_advice = ""                     # type: ignore
                self._stats["观望"] += 1

        logger.info(
            f"策略分类完成: 追强{self._stats['追强']} · "
            f"抄底{self._stats['抄底']} · "
            f"事件驱动{self._stats['事件驱动']} · "
            f"观望{self._stats['观望']}"
        )
        return recommendations

    def get_summary(self, recommendations: List[Recommendation] = None) -> str:
        """生成策略分布的文本摘要"""
        if recommendations is None:
            stats = self._stats
        else:
            stats = {"追强": 0, "抄底": 0, "事件驱动": 0, "观望": 0}
            for rec in recommendations:
                s = getattr(rec, "strategy", "观望")
                stats[s] = stats.get(s, 0) + 1

        parts = []
        for label, emoji in [("追强", "🚀"), ("抄底", "🎯"), ("事件驱动", "⚡"), ("观望", "👀")]:
            if stats.get(label, 0) > 0:
                parts.append(f"{emoji}{label}{stats[label]}")
        return " · ".join(parts) if parts else "无分类数据"


# ═══════════════════════════════════════════════════════════════════
# Singleton + Convenience
# ═══════════════════════════════════════════════════════════════════

_engine: Optional[StrategyClassifierEngine] = None


def get_engine(config: dict = None) -> StrategyClassifierEngine:
    """获取全局策略分类引擎实例（Singleton）"""
    global _engine
    if _engine is None:
        _engine = StrategyClassifierEngine(config)
    elif config is not None:
        _engine.config = {**DEFAULT_CONFIG, **config}
    return _engine


def classify_recommendations(
    recommendations: List[Recommendation],
    config: dict = None,
) -> List[Recommendation]:
    """便捷函数：一站式策略分类

    Args:
        recommendations: 技术面过滤后的推荐列表
        config: 策略分类配置（可选）

    Returns:
        已注入 strategy/strategy_score/strategy_advice 的推荐列表
    """
    engine = get_engine(config)
    return engine.apply(recommendations)
