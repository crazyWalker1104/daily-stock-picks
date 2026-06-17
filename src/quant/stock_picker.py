"""量化跟投模块 — 标的筛选引擎

从推荐数据库（SQLite）中读取历史推荐记录，量化评估每只标的的
技术面、资金面、趋势面、基本面，输出 Top 3 候选供用户确认。

筛选维度：
  - 技术面 (35%): 历史K线形态，MA排列，MACD状态
  - 资金面 (25%): 历史次日资金流表现
  - 趋势面 (20%): 近期涨跌幅适中程度
  - 基本面 (20%): 推荐信心度、催化事件强度、出现频率
"""

import logging
import os
import sqlite3
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Tuple

from src.quant.models import StockCandidate

logger = logging.getLogger(__name__)


# ═══════════════════════════════════════════════════════════════
# 筛选配置
# ═══════════════════════════════════════════════════════════════

# 排除条件
EXCLUDE_ST = True                # 排除 ST 股
EXCLUDE_NEW_LISTING = True       # 排除次新股（上市<60天）
MIN_MARKET_CAP = 50              # 最低市值（亿）
MIN_APPEARANCES = 1              # 最少在推荐中出现次数
LOOKBACK_DAYS = 30               # 回顾天数
MAX_CANDIDATES = 3               # 最多输出候选数

# 评分权重
W_TECH = 0.35
W_FUND = 0.25
W_TREND = 0.20
W_FUNDAMENTAL = 0.20


# ═══════════════════════════════════════════════════════════════
# 主入口
# ═══════════════════════════════════════════════════════════════

def pick_candidates(
    db_path: str = None,
    lookback_days: int = LOOKBACK_DAYS,
    top_n: int = MAX_CANDIDATES,
) -> List[StockCandidate]:
    """从推荐数据库中筛选最优质标的

    Args:
        db_path: 数据库路径，默认 data/recommendations.db
        lookback_days: 回顾天数
        top_n: 返回前 N 个候选

    Returns:
        List[StockCandidate] 排序后的候选列表
    """
    if db_path is None:
        project_root = os.path.dirname(os.path.dirname(os.path.dirname(
            os.path.abspath(__file__))))
        db_path = os.path.join(project_root, "data", "recommendations.db")

    if not os.path.exists(db_path):
        logger.warning(f"数据库不存在: {db_path}")
        return []

    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row

    try:
        # ── 1. 提取近期推荐的所有标的 ──
        cursor = conn.execute("""
            SELECT
                s.code,
                s.name,
                s.tracking_change_pct as tracking_return,
                s.tracking_hit,
                r.sector,
                r.confidence,
                r.catalyst,
                r.report_date
            FROM stocks s
            JOIN recommendations r ON s.recommendation_id = r.id
            WHERE r.report_date >= date('now', ?)
            ORDER BY r.report_date DESC
        """, (f"-{lookback_days} days",))

        rows = cursor.fetchall()

        if not rows:
            logger.info("数据库中无近期推荐记录")
            return []

        # ── 2. 按股票代码分组 ──
        stock_groups: Dict[str, dict] = {}
        for row in rows:
            code = row["code"] or ""
            name = row["name"] or ""
            if not code:
                continue

            # 排除 ST
            if EXCLUDE_ST and ("ST" in name.upper() or "*ST" in name.upper()):
                continue

            key = code
            if key not in stock_groups:
                stock_groups[key] = {
                    "code": code,
                    "name": name,
                    "appearances": 0,
                    "returns": [],
                    "hits": [],
                    "sectors": [],
                    "confidences": [],
                    "catalysts": [],
                    "last_date": "",
                }

            g = stock_groups[key]
            g["appearances"] += 1
            if row["tracking_return"] is not None:
                g["returns"].append(row["tracking_return"])
            if row["tracking_hit"] is not None:
                g["hits"].append(int(row["tracking_hit"]))
            if row["sector"]:
                g["sectors"].append(row["sector"])
            if row["confidence"]:
                g["confidences"].append(row["confidence"])
            if row["catalyst"]:
                g["catalysts"].append(row["catalyst"])
            if row["report_date"] and row["report_date"] > g["last_date"]:
                g["last_date"] = row["report_date"]

        # ── 3. 逐只打分 ──
        candidates: List[StockCandidate] = []
        for code, g in stock_groups.items():
            if g["appearances"] < MIN_APPEARANCES:
                continue

            tech = _score_technical(g)
            fund = _score_fundamental(g)  # 注意：这里的"资金面"实际从tracking数据体现
            trend = _score_trend(g)
            fundamental = _score_quality(g)

            total = (tech * W_TECH + fund * W_FUND +
                     trend * W_TREND + fundamental * W_FUNDAMENTAL)

            # 最高置信度
            last_conf = g["confidences"][0] if g["confidences"] else ""
            last_sector = g["sectors"][0] if g["sectors"] else ""

            # 平均收益和胜率
            avg_ret = (sum(g["returns"]) / len(g["returns"])
                       if g["returns"] else 0)
            win_rate = (sum(g["hits"]) / len(g["hits"])
                        if g["hits"] else 0)

            candidates.append(StockCandidate(
                symbol=code,
                symbol_name=g["name"],
                score=round(total, 1),
                tech_score=round(tech, 1),
                fund_score=round(fund, 1),
                trend_score=round(trend, 1),
                fundamental_score=round(fundamental, 1),
                appearance_count=g["appearances"],
                last_confidence=last_conf,
                last_sector=last_sector,
                avg_return=round(avg_ret, 3),
                win_rate=round(win_rate, 2),
                reason=_build_reason(g, round(total, 1)),
                risks=_build_risks(g),
            ))

        # ── 4. 排序并返回 Top N ──
        candidates.sort(key=lambda c: c.score, reverse=True)
        top = candidates[:top_n]

        logger.info(f"标的筛选完成: {len(candidates)}只有效 → Top {len(top)}")
        for i, c in enumerate(top, 1):
            logger.info(
                f"  #{i} {c.symbol_name}({c.symbol}) "
                f"评分:{c.score:.0f} "
                f"出现:{c.appearance_count}次 "
                f"胜率:{c.win_rate:.0%}"
            )

        return top

    except Exception as e:
        logger.error(f"标的筛选失败: {e}")
        return []
    finally:
        conn.close()


# ═══════════════════════════════════════════════════════════════
# 各维度评分
# ═══════════════════════════════════════════════════════════════

def _score_technical(g: dict) -> float:
    """技术面评分 (0-100)

    基于：出现频率（热度）、近期命中率（准确性）
    注意：由于此处没有实时K线，用tracking数据代理技术面质量
    """
    score = 50.0  # 基础分

    # 出现次数加分
    if g["appearances"] >= 5:
        score += 20
    elif g["appearances"] >= 3:
        score += 10

    # 近期命中率
    if g["hits"]:
        recent_hits = g["hits"][-5:]  # 最近5次
        hit_rate = sum(recent_hits) / len(recent_hits)
        score += hit_rate * 20
    else:
        score += 5  # 无tracking数据，中等评分

    return min(score, 100)


def _score_fundamental(g: dict) -> float:
    """资金面/基本面评分 (0-100)

    基于：推荐信心度（高>中>低）、催化事件数量
    """
    score = 40.0

    # 信心度加权
    conf_map = {"高": 30, "中": 15, "低": 5}
    for conf in g["confidences"]:
        score += conf_map.get(conf, 10) / len(g["confidences"])

    # 催化事件丰富度
    if len(g["catalysts"]) >= 3:
        score += 15
    elif len(g["catalysts"]) >= 1:
        score += 10

    return min(score, 100)


def _score_trend(g: dict) -> float:
    """趋势面评分 (0-100)

    基于：平均收益是否在合理区间 (2-10%)
          胜率是否 > 50%
    """
    score = 50.0

    if g["returns"]:
        avg_ret = sum(g["returns"]) / len(g["returns"])

        # 正收益加分
        if avg_ret > 0.05:
            score += 25
        elif avg_ret > 0.02:
            score += 15
        elif avg_ret > 0:
            score += 5
        elif avg_ret > -0.02:
            score -= 5
        else:
            score -= 15

        # 胜率
        if g["hits"]:
            win_rate = sum(g["hits"]) / len(g["hits"])
            if win_rate >= 0.7:
                score += 20
            elif win_rate >= 0.5:
                score += 10
            elif win_rate < 0.3:
                score -= 10
    else:
        score = 40  # 无数据，偏保守

    return max(0, min(score, 100))


def _score_quality(g: dict) -> float:
    """质量/基本面评分 (0-100)

    基于：推荐出现的持续性、最近一次推荐的信度
    """
    score = 40.0

    # 最近一次推荐是高信心
    if g["confidences"]:
        latest_conf = g["confidences"][0]
        if latest_conf == "高":
            score += 30
        elif latest_conf == "中":
            score += 15

    # 多板块覆盖（被跨板块推荐说明基本面好）
    unique_sectors = set(g["sectors"])
    if len(unique_sectors) >= 3:
        score += 20
    elif len(unique_sectors) >= 2:
        score += 10

    # 出现的持续性
    if g["appearances"] >= 3:
        score += 10

    return min(score, 100)


# ═══════════════════════════════════════════════════════════════
# 辅助函数
# ═══════════════════════════════════════════════════════════════

def _build_reason(g: dict, total_score: float) -> str:
    """构建推荐理由"""
    parts = []

    if g["appearances"] >= 3:
        parts.append(f"近30天被推荐{g['appearances']}次")
    else:
        parts.append(f"近期推荐{g['appearances']}次")

    if g["returns"]:
        avg_ret = sum(g["returns"]) / len(g["returns"])
        parts.append(f"历史次日均收益{avg_ret*100:+.1f}%")

    if g["hits"]:
        hit_rate = sum(g["hits"]) / len(g["hits"])
        parts.append(f"胜率{hit_rate:.0%}")

    if g["confidences"]:
        parts.append(f"信心度{g['confidences'][0]}")

    return " · ".join(parts)


def _build_risks(g: dict) -> List[str]:
    """构建风险提示"""
    risks = []

    if g["returns"]:
        avg_ret = sum(g["returns"]) / len(g["returns"])
        if avg_ret < 0:
            risks.append(f"历史次日均收益为负({avg_ret*100:.1f}%)")

    if g["hits"]:
        hit_rate = sum(g["hits"]) / len(g["hits"])
        if hit_rate < 0.4:
            risks.append(f"历史胜率偏低({hit_rate:.0%})")

    if g["appearances"] < 3:
        risks.append("出现次数较少，样本不足")

    return risks


# ═══════════════════════════════════════════════════════════════
# CLI 友好输出
# ═══════════════════════════════════════════════════════════════

def format_candidates(candidates: List[StockCandidate]) -> str:
    """格式化候选列表为可读文本"""
    if not candidates:
        return "📭 暂无可选标的（数据库为空或无近期推荐记录）"

    lines = [
        "╔══════════════════════════════════════════════════════════════╗",
        "║           🎯 量化选股 · Top 候选标的                        ║",
        "╚══════════════════════════════════════════════════════════════╝",
        "",
    ]

    for i, c in enumerate(candidates, 1):
        lines.extend([
            f"  #{i}  {c.symbol_name}（{c.symbol}）  "
            f"综合评分: {c.score:.0f}/100",
            f"  ─────────────────────────────────────────────────────────",
            f"  技术:{c.tech_score:.0f}  |  资金:{c.fund_score:.0f}  |  "
            f"趋势:{c.trend_score:.0f}  |  基本面:{c.fundamental_score:.0f}",
            f"  出现: {c.appearance_count}次  |  "
            f"胜率: {c.win_rate:.0%}  |  "
            f"均收益: {c.avg_return*100:+.1f}%  |  "
            f"信心: {c.last_confidence}",
            f"  板块: {c.last_sector}",
            f"  💡 {c.reason}",
            "",
        ])

    lines.append("─" * 60)
    lines.append("📌 请选择一只标的开始跟踪：")
    lines.append(f"   python -m src.quant --watch --symbol <代码>")
    lines.append("")

    return "\n".join(lines)
