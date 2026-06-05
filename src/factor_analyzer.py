"""因子有效性检验模块 — 量化分析各因子对次日涨跌的预测能力

Phase 3.2: 分析 SQLite 中存储的推荐历史数据，计算每个因子（技术评分、信心度、
确认信号、板块等）与次日实际收益的相关性，输出因子排名和统计显著性评估。

分析维度：
  1. 相关性 — 连续因子 vs tracking_change_pct（Pearson r + Spearman rho）
  2. 分类对比 — 分类因子的分组胜率/均收益/置信区间
  3. Information Coefficient — Rank IC（因子排序 vs 收益排序）
  4. 分位数 — 按因子值分桶，看 Q4-Q1 胜率差异
  5. 因子排名 — 综合排序，识别有效/无效因子

设计原则：
  - 零外部依赖（仅 stdlib sqlite3 + json + math + statistics）
  - 独立 CLI 工具，不嵌入每日管道
  - 小样本诚实：N<30 处处标注 ⚠️，N<3 跳过统计
  - 遵循 Engine + Singleton + Convenience 模式
"""

import json
import logging
import math
import os
import statistics
from datetime import datetime
from typing import Dict, List, Optional, Tuple

from src.database import get_engine as get_db_engine

logger = logging.getLogger(__name__)

# ═══════════════════════════════════════════════════════════════════
# 默认配置
# ═══════════════════════════════════════════════════════════════════

DEFAULT_CONFIG: dict = {
    "enabled": True,
    "min_samples_for_stats": 10,   # 低于此样本数的统计标注 ⚠️
    "quantile_bins": 4,            # 分位数分组数
    "inject_into_report": False,   # 是否注入每日报告（Phase 3.3 启用）
}

# 连续因子定义：(显示名, stocks表列名)
CONTINUOUS_FACTORS: List[Tuple[str, str]] = [
    ("technical_score", "technical_score"),
    ("change_pct_at_rec", "change_pct_at_rec"),
    ("turnover_rate", "turnover_rate"),
    ("circulating_cap_yi", "circulating_cap_yi"),
]

# 分类因子定义：(显示名, 来源类型, 来源列名)
CATEGORICAL_FACTORS: List[Tuple[str, str, str]] = [
    ("confidence", "column", "confidence"),           # recommendations 列
    ("alignment", "json", "$.alignment"),              # confirmation_json 提取
]

# t 分布临界值表（双尾 95%, df=1..30），df>30 用 1.96
T_CRITICAL_95: List[float] = [
    12.706, 4.303, 3.182, 2.776, 2.571, 2.447, 2.365, 2.306, 2.262, 2.228,
    2.201, 2.179, 2.160, 2.145, 2.131, 2.120, 2.110, 2.101, 2.093, 2.086,
    2.080, 2.074, 2.069, 2.064, 2.060, 2.056, 2.052, 2.048, 2.045, 2.042,
]


# ═══════════════════════════════════════════════════════════════════
# 统计工具函数
# ═══════════════════════════════════════════════════════════════════

def _rankdata(values: List[float]) -> List[float]:
    """计算排名（平均值处理平局），返回 1-indexed 的排名列表"""
    if not values:
        return []
    n = len(values)
    indexed = sorted(enumerate(values), key=lambda x: x[1])
    ranks = [0.0] * n
    i = 0
    while i < n:
        j = i
        while j < n and abs(indexed[j][1] - indexed[i][1]) < 1e-12:
            j += 1
        avg_rank = (i + j + 1) / 2.0  # 1-indexed average
        for k in range(i, j):
            ranks[indexed[k][0]] = avg_rank
        i = j
    return ranks


def _pearson_r(xs: List[float], ys: List[float]) -> Optional[float]:
    """Pearson 相关系数。方差为零时返回 None。"""
    n = len(xs)
    if n < 3:
        return None
    mean_x = sum(xs) / n
    mean_y = sum(ys) / n
    cov = sum((x - mean_x) * (y - mean_y) for x, y in zip(xs, ys))
    std_x = math.sqrt(sum((x - mean_x) ** 2 for x in xs))
    std_y = math.sqrt(sum((y - mean_y) ** 2 for y in ys))
    if std_x < 1e-12 or std_y < 1e-12:
        return None  # 方差为零
    r = cov / (std_x * std_y)
    # Clamp to [-1, 1]
    return max(-1.0, min(1.0, r))


def _spearman_rho(xs: List[float], ys: List[float]) -> Optional[float]:
    """Spearman 秩相关系数。"""
    if len(xs) < 3:
        return None
    rank_x = _rankdata(xs)
    rank_y = _rankdata(ys)
    return _pearson_r(rank_x, rank_y)


def _t_pvalue(r: float, n: int) -> float:
    """Pearson r 的双尾 p 值（基于 t 分布近似）。"""
    if n <= 2 or abs(r) >= 1.0 - 1e-12:
        return 0.0 if abs(r) >= 1.0 - 1e-12 else 1.0
    t_stat = r * math.sqrt((n - 2) / (1 - r * r))
    df = n - 2
    # t 分布 CDF 近似 (Abramowitz & Stegun 26.7.1)
    # 使用标准 normal + 修正项
    # 简化：用 scipy 的近似公式
    x = abs(t_stat)
    # 使用 Beta function 的连分数近似
    a = df / 2.0
    b = 0.5
    # 不完全 Beta 函数近似（连分数展开）
    # I_x(a, b) where x = df/(df + t^2)
    xb = df / (df + x * x)
    # 简化：用标准正态近似（对于大 df 足够准）
    # 这里用更精确的连分数展开
    if df > 30:
        # 标准正态近似
        z = x
        p = math.exp(-z * z / 2) / math.sqrt(2 * math.pi) / z
        p = p * (1 - 1/z**2 + 3/z**4 - 15/z**6)
    else:
        # 查表 + 线性插值
        t_crit = T_CRITICAL_95[min(df, 30) - 1]
        # 用 t / t_crit 的比例近似 p-value（粗略但可用）
        ratio = x / t_crit
        if ratio < 0.5:
            p = 0.5
        elif ratio > 3.0:
            p = 0.001
        else:
            # 近似：p ≈ 0.05 * (1.96 / ratio)
            p = 0.05 * (t_crit / x)
    return min(1.0, max(0.0, 2.0 * p))


def _mean_ci(values: List[float], confidence: float = 0.95) -> Optional[str]:
    """计算均值的置信区间，返回格式化字符串如 "(+0.5%, +3.2%)" """
    n = len(values)
    if n < 3:
        return None
    mean = sum(values) / n
    if n > 1:
        std_err = statistics.stdev(values) / math.sqrt(n)
    else:
        return None
    df = n - 1
    if df <= 30:
        t_crit = T_CRITICAL_95[min(df, 30) - 1] if confidence == 0.95 else 1.96
    else:
        t_crit = 1.96
    margin = t_crit * std_err
    return f"[{mean - margin:+.2f}%, {mean + margin:+.2f}%]"


def _describe(values: List[float]) -> dict:
    """基本描述统计"""
    if not values:
        return {"count": 0}
    n = len(values)
    mean = sum(values) / n
    if n > 1:
        std = statistics.stdev(values)
    else:
        std = 0.0
    return {
        "count": n,
        "mean": round(mean, 3),
        "std": round(std, 3),
        "min": round(min(values), 3),
        "max": round(max(values), 3),
    }


# ═══════════════════════════════════════════════════════════════════
# FactorAnalyzerEngine
# ═══════════════════════════════════════════════════════════════════

class FactorAnalyzerEngine:
    """因子有效性分析引擎

    用法：
        engine = FactorAnalyzerEngine(config)
        results = engine.analyze()
        print(engine.get_summary(results))
    """

    def __init__(self, config: dict = None):
        cfg = config or {}
        fa_cfg = cfg.get("factor_analysis", {})
        self.enabled = fa_cfg.get("enabled", DEFAULT_CONFIG["enabled"])
        self.min_samples = fa_cfg.get("min_samples_for_stats",
                                       DEFAULT_CONFIG["min_samples_for_stats"])
        self.quantile_bins = fa_cfg.get("quantile_bins",
                                        DEFAULT_CONFIG["quantile_bins"])
        self._db_engine = get_db_engine(config)
        self._data: Optional[List[dict]] = None  # 缓存查询结果

    # ── 数据获取 ─────────────────────────────────────────────────

    def _fetch_data(self) -> List[dict]:
        """从数据库获取所有带追踪数据的标的及其因子信息"""
        if self._data is not None:
            return self._data

        if not self._db_engine.enabled:
            self._data = []
            return self._data

        try:
            conn = self._db_engine._connect()
            rows = conn.execute("""
                SELECT
                    s.name, s.code,
                    s.technical_score,
                    s.change_pct_at_rec,
                    s.turnover_rate,
                    s.circulating_cap_yi,
                    s.tracking_change_pct,
                    s.tracking_hit,
                    r.confidence,
                    r.sector,
                    r.report_date,
                    json_extract(r.confirmation_json, '$.alignment') as alignment
                FROM stocks s
                JOIN recommendations r ON r.id = s.recommendation_id
                WHERE s.tracking_change_pct IS NOT NULL
                ORDER BY r.report_date DESC, r.sort_order, s.id
            """).fetchall()
            self._data = [dict(row) for row in rows]
            return self._data
        except Exception as e:
            logger.warning(f"因子分析数据查询失败: {e}")
            self._data = []
            return self._data

    def _fetch_total_stocks(self) -> int:
        """获取所有标的总数（含未追踪的）"""
        try:
            conn = self._db_engine._connect()
            row = conn.execute("SELECT COUNT(*) as cnt FROM stocks").fetchone()
            return row["cnt"] if row else 0
        except Exception:
            return 0

    # ── 相关性分析 ───────────────────────────────────────────────

    def _correlation_analysis(self, data: List[dict]) -> dict:
        """连续因子相关性分析（Pearson r + Spearman rho）"""
        results = {}
        for factor_name, col_name in CONTINUOUS_FACTORS:
            xs, ys = [], []
            for row in data:
                x = row.get(col_name)
                y = row.get("tracking_change_pct")
                if x is not None and y is not None:
                    xs.append(float(x))
                    ys.append(float(y))

            n = len(xs)
            entry: dict = {"factor": factor_name, "n": n}

            if n < 3:
                entry["pearson_r"] = None
                entry["spearman_rho"] = None
                entry["note"] = "⚠️ N<3，无法计算相关性"
                results[factor_name] = entry
                continue

            # 检测方差
            unique_x = len(set(round(v, 6) for v in xs))
            if unique_x <= 1:
                entry["pearson_r"] = None
                entry["spearman_rho"] = None
                entry["note"] = "⚠️ 因子无方差（所有值相同），无法计算相关性"
                entry["unique_values"] = unique_x
                results[factor_name] = entry
                continue

            # Spearman rho（始终计算）
            rho = _spearman_rho(xs, ys)
            entry["spearman_rho"] = round(rho, 4) if rho is not None else None

            # Pearson r（N>=10 才计算，N<10 只报 Spearman）
            if n >= 10:
                r = _pearson_r(xs, ys)
                entry["pearson_r"] = round(r, 4) if r is not None else None
                if r is not None:
                    entry["p_value"] = round(_t_pvalue(r, n), 4)
            else:
                entry["pearson_r"] = None
                entry["note"] = f"⚠️ N={n}<10，仅报 Spearman rho，Pearson 待更多样本"

            # 方向判断
            if rho is not None:
                if abs(rho) < 0.1:
                    entry["direction"] = "无显著相关"
                elif rho > 0:
                    entry["direction"] = "正向" if rho >= 0.3 else "弱正向"
                else:
                    entry["direction"] = "负向" if rho <= -0.3 else "弱负向"

            # 小样本警告
            if n < self.min_samples:
                if "note" not in entry:
                    entry["note"] = f"⚠️ N={n}<{self.min_samples}，统计效力不足"

            results[factor_name] = entry
        return results

    # ── 分类对比 ─────────────────────────────────────────────────

    def _categorical_analysis(self, data: List[dict]) -> dict:
        """分类因子对比分析（分组胜率/均收益）"""
        results = {}
        for factor_name, source_type, source_col in CATEGORICAL_FACTORS:
            groups: Dict[str, List[dict]] = {}
            for row in data:
                if source_type == "column":
                    key = row.get(source_col, "?") or "?"
                else:  # json
                    key = row.get("alignment", "?") or "?"
                if key not in groups:
                    groups[key] = []
                groups[key].append(row)

            group_results = []
            for group_name in sorted(groups.keys()):
                members = groups[group_name]
                returns = [m["tracking_change_pct"] for m in members]
                hits = [m["tracking_hit"] for m in members]
                n = len(members)
                hit_count = sum(1 for h in hits if h == 1)
                avg_ret = sum(returns) / n if n > 0 else 0.0
                std_ret = statistics.stdev(returns) if n > 1 else 0.0

                entry = {
                    "group": group_name,
                    "count": n,
                    "hit_count": hit_count,
                    "hit_rate": round(hit_count / n, 3) if n > 0 else 0.0,
                    "avg_return": round(avg_ret, 3),
                    "std_return": round(std_ret, 3),
                }

                if n >= 3:
                    entry["ci_95"] = _mean_ci(returns)
                else:
                    entry["ci_95"] = None
                    entry["note"] = "⚠️ N<3"

                group_results.append(entry)

            # Sort by avg_return descending
            group_results.sort(key=lambda g: g["avg_return"], reverse=True)
            results[factor_name] = group_results

        # 板块分析（额外分类因子）
        sector_groups: Dict[str, List[dict]] = {}
        for row in data:
            sector = row.get("sector", "?") or "?"
            if sector not in sector_groups:
                sector_groups[sector] = []
            sector_groups[sector].append(row)

        sector_results = []
        for sector, members in sector_groups.items():
            returns = [m["tracking_change_pct"] for m in members]
            hits = [m["tracking_hit"] for m in members]
            n = len(members)
            hit_count = sum(1 for h in hits if h == 1)
            avg_ret = sum(returns) / n if n > 0 else 0.0
            sector_results.append({
                "sector": sector,
                "count": n,
                "hit_count": hit_count,
                "hit_rate": round(hit_count / n, 3) if n > 0 else 0.0,
                "avg_return": round(avg_ret, 3),
            })

        sector_results.sort(key=lambda g: g["avg_return"], reverse=True)
        results["sector"] = sector_results

        return results

    # ── Information Coefficient ──────────────────────────────────

    def _information_coefficient(self, data: List[dict]) -> List[dict]:
        """计算每个连续因子的 Rank IC（Spearman rho 因子 vs 收益）"""
        ic_results = []
        for factor_name, col_name in CONTINUOUS_FACTORS:
            xs, ys = [], []
            for row in data:
                x = row.get(col_name)
                y = row.get("tracking_change_pct")
                if x is not None and y is not None:
                    xs.append(float(x))
                    ys.append(float(y))

            if len(xs) < 3:
                ic_results.append({
                    "factor": factor_name, "IC": None,
                    "n": len(xs), "note": "⚠️ N<3"
                })
                continue

            unique_x = len(set(round(v, 6) for v in xs))
            if unique_x <= 1:
                ic_results.append({
                    "factor": factor_name, "IC": None,
                    "n": len(xs),
                    "note": "⚠️ 因子无方差"
                })
                continue

            ic = _spearman_rho(xs, ys)
            entry = {
                "factor": factor_name,
                "IC": round(ic, 4) if ic is not None else None,
                "n": len(xs),
            }

            # IC 强度判断
            if ic is not None:
                abs_ic = abs(ic)
                if abs_ic < 0.05:
                    entry["strength"] = "几乎无预测力"
                elif abs_ic < 0.1:
                    entry["strength"] = "弱预测力"
                elif abs_ic < 0.2:
                    entry["strength"] = "中等预测力"
                else:
                    entry["strength"] = "强预测力"

            # 小样本警告
            if len(xs) < self.min_samples:
                entry["note"] = f"⚠️ N={len(xs)}<{self.min_samples}，IC 不稳定"

            ic_results.append(entry)

        # Sort by absolute IC descending
        ic_results.sort(key=lambda x: abs(x["IC"]) if x["IC"] is not None else -1,
                       reverse=True)
        return ic_results

    # ── 分位数分析 ───────────────────────────────────────────────

    def _quantile_analysis(self, data: List[dict]) -> dict:
        """按因子值分桶，比较头部 vs 尾部桶的胜率差异"""
        results = {}
        for factor_name, col_name in CONTINUOUS_FACTORS:
            pairs = []
            for row in data:
                x = row.get(col_name)
                y = row.get("tracking_change_pct")
                hit = row.get("tracking_hit")
                if x is not None and y is not None:
                    pairs.append((float(x), y, hit))

            n = len(pairs)
            if n < self.quantile_bins * 2:
                results[factor_name] = {
                    "bins": [],
                    "note": f"⚠️ N={n} < {self.quantile_bins * 2}，跳过分位数分析",
                    "n": n,
                }
                continue

            # Check variance
            unique_vals = len(set(round(p[0], 6) for p in pairs))
            if unique_vals <= 1:
                results[factor_name] = {
                    "bins": [],
                    "note": "⚠️ 因子无方差，跳过分位数分析",
                    "n": n,
                }
                continue

            # Sort by factor value
            pairs.sort(key=lambda p: p[0])
            bins = self.quantile_bins
            bin_size = n // bins
            bin_results = []
            labels = [f"Q{i+1}" for i in range(bins)]

            for i in range(bins):
                start = i * bin_size
                if i == bins - 1:
                    end = n  # 最后一个桶吃掉剩余所有
                else:
                    end = (i + 1) * bin_size

                chunk = pairs[start:end]
                chunk_n = len(chunk)
                chunk_returns = [p[1] for p in chunk]
                chunk_hits = [p[2] for p in chunk if p[2] is not None]
                avg_ret = sum(chunk_returns) / chunk_n
                hit_count = sum(1 for h in chunk_hits if h == 1)
                factor_range = f"{chunk[0][0]:.1f}-{chunk[-1][0]:.1f}"

                bin_results.append({
                    "bin": labels[i],
                    "range": factor_range,
                    "count": chunk_n,
                    "hit_rate": round(hit_count / len(chunk_hits), 3) if chunk_hits else 0.0,
                    "avg_return": round(avg_ret, 3),
                })

            # Calculate Q4-Q1 return spread
            if len(bin_results) >= 2:
                spread = bin_results[-1]["avg_return"] - bin_results[0]["avg_return"]
                hit_spread = bin_results[-1]["hit_rate"] - bin_results[0]["hit_rate"]
            else:
                spread = None
                hit_spread = None

            results[factor_name] = {
                "bins": bin_results,
                "n": n,
                "q_high_minus_low_return": round(spread, 3) if spread is not None else None,
                "q_high_minus_low_hit_rate": round(hit_spread, 3) if hit_spread is not None else None,
            }

        return results

    # ── 因子排名 ─────────────────────────────────────────────────

    def _rank_factors(self, correlations: dict, categorical: dict,
                      ic_results: List[dict]) -> List[dict]:
        """综合因子排名（按预测能力）"""
        ranked = []

        # 连续因子：按 IC 绝对值
        for entry in ic_results:
            ic = entry.get("IC")
            if ic is not None:
                ranked.append({
                    "factor": entry["factor"],
                    "type": "连续",
                    "metric": "IC",
                    "value": abs(ic),
                    "raw_ic": ic,
                    "interpretation": entry.get("strength", ""),
                    "note": entry.get("note", ""),
                })

        # 分类因子：按组间最大收益差
        for factor_name in CATEGORICAL_FACTORS:
            groups = categorical.get(factor_name[0], [])
            if len(groups) >= 2:
                max_ret = groups[0]["avg_return"]
                min_ret = groups[-1]["avg_return"]
                spread = max_ret - min_ret
                # Effect size = spread / pooled std (simplified: spread / avg std)
                avg_std = sum(g.get("std_return", 0) or 0 for g in groups) / max(len(groups), 1)
                effect_size = abs(spread) / max(avg_std, 0.01)
                ranked.append({
                    "factor": factor_name[0],
                    "type": "分类",
                    "metric": "组间收益差",
                    "value": abs(spread),
                    "raw_spread": spread,
                    "effect_size": round(effect_size, 2),
                    "best_group": groups[0]["group"],
                    "worst_group": groups[-1]["group"],
                    "interpretation": (
                        "强区分力" if effect_size > 1.0 else
                        "中等区分力" if effect_size > 0.5 else
                        "弱区分力"
                    ),
                })
            elif len(groups) == 1:
                ranked.append({
                    "factor": factor_name[0],
                    "type": "分类",
                    "metric": "组间收益差",
                    "value": 0,
                    "note": f"⚠️ 仅1个分组({groups[0]['group']})，无法对比",
                })

        # Sort by value descending
        ranked.sort(key=lambda x: x["value"], reverse=True)

        # Assign rank numbers
        for i, entry in enumerate(ranked):
            entry["rank"] = i + 1

        return ranked

    # ── 主入口 ───────────────────────────────────────────────────

    def analyze(self) -> dict:
        """运行全部分析，返回结构化结果 dict。

        Returns:
            {"meta": {...}, "correlations": {...}, "categorical": {...},
             "information_coefficient": [...], "quantiles": {...},
             "ranking": [...]}
        """
        if not self.enabled:
            return {"meta": {"enabled": False, "note": "因子分析已禁用"}}

        data = self._fetch_data()
        total_stocks = self._fetch_total_stocks()
        tracked_n = len(data)

        meta = {
            "enabled": True,
            "total_stocks": total_stocks,
            "tracked_stocks": tracked_n,
            "analysis_date": datetime.now().strftime("%Y-%m-%d %H:%M"),
            "small_sample": tracked_n < self.min_samples,
            "warning": None,
        }

        if tracked_n == 0:
            meta["warning"] = "⚠️ 无追踪数据：尚未有任何标的完成次日追踪。待至少1个交易日追踪后可用。"
            return {"meta": meta,
                    "correlations": {}, "categorical": {},
                    "information_coefficient": [], "quantiles": {},
                    "ranking": []}

        if meta["small_sample"]:
            meta["warning"] = (
                f"⚠️ 样本量警告：仅 {tracked_n}/{total_stocks} 只标的有追踪数据"
                f"（来自有追踪的交易日）。需要 ≥{self.min_samples} 样本才能获得"
                f"统计显著性。以下分析仅供参考。"
            )

        # 各分析独立运行，一个失败不影响其他
        correlations = {}
        categorical = {}
        quantiles = {}
        ic_results = []
        ranking = []

        try:
            correlations = self._correlation_analysis(data)
        except Exception as e:
            logger.warning(f"相关性分析失败: {e}")
            meta["correlation_error"] = str(e)

        try:
            categorical = self._categorical_analysis(data)
        except Exception as e:
            logger.warning(f"分类分析失败: {e}")
            meta["categorical_error"] = str(e)

        try:
            ic_results = self._information_coefficient(data)
        except Exception as e:
            logger.warning(f"IC 分析失败: {e}")
            meta["ic_error"] = str(e)

        try:
            quantiles = self._quantile_analysis(data)
        except Exception as e:
            logger.warning(f"分位数分析失败: {e}")
            meta["quantile_error"] = str(e)

        try:
            ranking = self._rank_factors(correlations, categorical, ic_results)
        except Exception as e:
            logger.warning(f"因子排名失败: {e}")
            meta["ranking_error"] = str(e)

        return {
            "meta": meta,
            "correlations": correlations,
            "categorical": categorical,
            "information_coefficient": ic_results,
            "quantiles": quantiles,
            "ranking": ranking,
        }

    # ── 输出格式化 ───────────────────────────────────────────────

    def get_summary(self, results: dict = None) -> str:
        """生成 Markdown 格式的摘要（供报告注入或 CLI --format markdown）"""
        if results is None:
            results = self.analyze()
        return self._format_markdown(results)

    def _format_markdown(self, r: dict) -> str:
        """将分析结果渲染为 Markdown 字符串"""
        meta = r.get("meta", {})
        if not meta.get("enabled", True):
            return "> 因子分析已禁用。\n"

        if not meta.get("tracked_stocks", 0):
            return "## 📊 因子有效性分析\n\n" + meta.get("warning",
                   "> ⚠️ 暂无追踪数据。\n")

        lines = ["## 📊 因子有效性分析", ""]

        # Warning
        if meta.get("warning"):
            lines.append(f"> {meta['warning']}")
            lines.append("")

        lines.extend([
            f"- **总标的数**: {meta.get('total_stocks', 0)}",
            f"- **已追踪**: {meta.get('tracked_stocks', 0)}",
            f"- **分析时间**: {meta.get('analysis_date', '?')}",
            "",
        ])

        # ── 因子排名 ──
        ranking = r.get("ranking", [])
        if ranking:
            lines.extend([
                "### 🏆 因子排名（按预测能力）",
                "",
                "| 排名 | 因子 | 类型 | 指标 | 值 | 解读 |",
                "|:---:|:---|:---|:---|:---:|:---|",
            ])
            for entry in ranking:
                rank = entry.get("rank", "?")
                factor = entry.get("factor", "?")
                ftype = entry.get("type", "?")
                metric = entry.get("metric", "?")
                value = entry.get("value", 0)
                interp = entry.get("interpretation", "")
                note = entry.get("note", "")
                interp_str = f"{interp} {note}" if note else interp
                lines.append(
                    f"| {rank} | {factor} | {ftype} | {metric} | "
                    f"{value:+.3f} | {interp_str} |"
                )
            lines.append("")

        # ── 连续因子相关性 ──
        correlations = r.get("correlations", {})
        if correlations:
            lines.extend([
                "### 📈 连续因子相关性",
                "",
                "| 因子 | N | Pearson r | Spearman rho | 方向 | 备注 |",
                "|:---|---:|:---:|:---:|:---|:---|",
            ])
            for fname, entry in correlations.items():
                n = entry.get("n", 0)
                pr = entry.get("pearson_r")
                sr = entry.get("spearman_rho")
                direction = entry.get("direction", "")
                note = entry.get("note", "")
                pr_str = f"{pr:+.3f}" if pr is not None else "—"
                sr_str = f"{sr:+.3f}" if sr is not None else "—"
                lines.append(
                    f"| {fname} | {n} | {pr_str} | {sr_str} | {direction} | {note} |"
                )
            lines.append("")

        # ── 分类因子 ──
        categorical = r.get("categorical", {})
        for factor_name, _, _ in CATEGORICAL_FACTORS:
            groups = categorical.get(factor_name, [])
            if not groups:
                continue
            lines.extend([
                f"### 🔖 分类因子: {factor_name}",
                "",
                "| 分组 | 数量 | 胜率 | 均收益 | 标准差 | 95% CI |",
                "|:---|---:|---:|---:|---:|:---|",
            ])
            for g in groups:
                ci = g.get("ci_95") or g.get("note", "")
                lines.append(
                    f"| {g['group']} | {g['count']} | {g['hit_rate']:.0%} | "
                    f"{g['avg_return']:+.2f}% | {g.get('std_return', 0):.2f}% | {ci} |"
                )
            lines.append("")

        # 板块（Top 10）
        sector_list = categorical.get("sector", [])
        if sector_list:
            lines.extend([
                "### 🏭 板块表现（按均收益排序）",
                "",
                "| 板块 | 数量 | 胜率 | 均收益 |",
                "|:---|---:|---:|---:|",
            ])
            for s in sector_list[:10]:
                lines.append(
                    f"| {s['sector']} | {s['count']} | {s['hit_rate']:.0%} | "
                    f"{s['avg_return']:+.2f}% |"
                )
            lines.append("")

        # ── Information Coefficient ──
        ic_list = r.get("information_coefficient", [])
        if ic_list:
            lines.extend([
                "### 🎯 Information Coefficient (Rank IC)",
                "",
                "| 因子 | N | IC | 预测力 | 备注 |",
                "|:---|---:|:---:|:---|:---|",
            ])
            for entry in ic_list:
                ic_val = entry.get("IC")
                ic_str = f"{ic_val:+.3f}" if ic_val is not None else "—"
                lines.append(
                    f"| {entry['factor']} | {entry.get('n', 0)} | {ic_str} | "
                    f"{entry.get('strength', '—')} | {entry.get('note', '')} |"
                )
            lines.append("")

        # ── 分位数 ──
        quantiles = r.get("quantiles", {})
        for fname, qdata in quantiles.items():
            bins = qdata.get("bins", [])
            if not bins:
                if qdata.get("note"):
                    lines.append(f"#### 分位数: {fname}")
                    lines.append(f"> {qdata['note']}")
                    lines.append("")
                continue
            lines.extend([
                f"### 📊 分位数: {fname}",
                "",
                "| 分位 | 范围 | 数量 | 胜率 | 均收益 |",
                "|:---|:---|:---:|:---:|:---:|",
            ])
            for b in bins:
                lines.append(
                    f"| {b['bin']} | {b['range']} | {b['count']} | "
                    f"{b['hit_rate']:.0%} | {b['avg_return']:+.2f}% |"
                )
            # Spread line
            spread_ret = qdata.get("q_high_minus_low_return")
            spread_hit = qdata.get("q_high_minus_low_hit_rate")
            if spread_ret is not None and spread_hit is not None:
                lines.append(
                    f"| **Q4-Q1** | — | — | "
                    f"**{spread_hit:+.0%}** | **{spread_ret:+.2f}%** |"
                )
            lines.append("")

        # ── 局限性 ──
        if meta.get("small_sample"):
            lines.extend([
                "### ⚠️ 局限性说明",
                "",
                f"- 当前仅 {meta['tracked_stocks']} 只有效追踪样本，所有结论均为初步观察",
                "- 随着每日追踪数据积累（预计 2-4 周后 N>30），分析将逐步具有统计意义",
                "- 连续因子方差较小时（如技术评分高度集中），相关性指标失效",
                "- IC_IR（IC 信息比）需多日 IC 序列才能计算，当前单日截面无法评估因子稳定性",
                "",
            ])

        return "\n".join(lines)

    def _format_cli(self, r: dict) -> str:
        """将分析结果渲染为 CLI 表格字符串"""
        meta = r.get("meta", {})
        if not meta.get("enabled", True):
            return "\n  因子分析已禁用（设置 factor_analysis.enabled: true 启用）\n"

        if not meta.get("tracked_stocks", 0):
            return f"\n{meta.get('warning', '⚠️ 暂无追踪数据。')}\n"

        lines = [
            "",
            "=" * 78,
            "  📊 因子有效性检验 — Factor Effectiveness Analysis",
            "=" * 78,
        ]

        if meta.get("warning"):
            lines.extend(["", f"  {meta['warning']}", ""])

        lines.extend([
            f"  总标的: {meta.get('total_stocks', 0)} | "
            f"已追踪: {meta.get('tracked_stocks', 0)} | "
            f"分析时间: {meta.get('analysis_date', '?')}",
            "",
        ])

        # ── 因子排名 ──
        ranking = r.get("ranking", [])
        if ranking:
            lines.extend([
                "-" * 78,
                "  🏆 因子排名（按预测能力）",
                "-" * 78,
                f"  {'排名':<4s} {'因子':<22s} {'类型':<6s} {'指标':<12s} {'值':>8s}  {'解读'}",
                f"  {'─'*4} {'─'*22} {'─'*6} {'─'*12} {'─'*8}  {'─'*20}",
            ])
            for entry in ranking:
                interp = entry.get("interpretation", "")
                note = entry.get("note", "")
                note_str = f" {note}" if note else ""
                lines.append(
                    f"  #{entry['rank']:<3d} {entry['factor']:<22s} {entry['type']:<6s} "
                    f"{entry['metric']:<12s} {entry['value']:+.3f}  {interp}{note_str}"
                )
            lines.append("")

        # ── 连续因子 ──
        correlations = r.get("correlations", {})
        if correlations:
            lines.extend([
                "-" * 78,
                "  📈 连续因子相关性",
                "-" * 78,
                f"  {'因子':<22s} {'N':>4s} {'Pearson r':>10s} {'Spearman rho':>12s}  {'方向':<10s} {'备注'}",
                f"  {'─'*22} {'─'*4} {'─'*10} {'─'*12}  {'─'*10} {'─'*20}",
            ])
            for fname, entry in correlations.items():
                n = entry.get("n", 0)
                pr = entry.get("pearson_r")
                sr = entry.get("spearman_rho")
                direction = entry.get("direction", "—")
                note = entry.get("note", "")
                pr_str = f"{pr:+.3f}" if pr is not None else "—"
                sr_str = f"{sr:+.3f}" if sr is not None else "—"
                lines.append(
                    f"  {fname:<22s} {n:>4d} {pr_str:>10s} {sr_str:>12s}  "
                    f"{direction:<10s} {note}"
                )
            lines.append("")

        # ── 分类因子 ──
        categorical = r.get("categorical", {})
        for factor_name, _, _ in CATEGORICAL_FACTORS:
            groups = categorical.get(factor_name, [])
            if not groups:
                continue
            lines.extend([
                "-" * 78,
                f"  🔖 分类因子: {factor_name}",
                "-" * 78,
                f"  {'分组':<20s} {'数量':>4s} {'胜率':>8s} {'均收益':>10s} {'标准差':>8s}  {'95% CI'}",
                f"  {'─'*20} {'─'*4} {'─'*8} {'─'*10} {'─'*8}  {'─'*24}",
            ])
            for g in groups:
                ci = g.get("ci_95") or g.get("note", "")
                lines.append(
                    f"  {g['group']:<20s} {g['count']:>4d} {g['hit_rate']:>7.0%} "
                    f"{g['avg_return']:>+9.2f}% {g.get('std_return', 0):>8.2f}%  {ci}"
                )
            lines.append("")

        # ── IC ──
        ic_list = r.get("information_coefficient", [])
        if ic_list:
            lines.extend([
                "-" * 78,
                "  🎯 Information Coefficient (Rank IC)",
                "-" * 78,
                f"  {'因子':<22s} {'N':>4s} {'IC':>8s}  {'预测力':<14s} {'备注'}",
                f"  {'─'*22} {'─'*4} {'─'*8}  {'─'*14} {'─'*24}",
            ])
            for entry in ic_list:
                ic_val = entry.get("IC")
                ic_str = f"{ic_val:+.3f}" if ic_val is not None else "—"
                lines.append(
                    f"  {entry['factor']:<22s} {entry.get('n', 0):>4d} {ic_str:>8s}  "
                    f"{entry.get('strength', '—'):<14s} {entry.get('note', '')}"
                )
            lines.append("")

        # ── 分位数 ──
        quantiles = r.get("quantiles", {})
        for fname, qdata in quantiles.items():
            bins = qdata.get("bins", [])
            if not bins:
                if qdata.get("note"):
                    lines.append(f"  📊 分位数({fname}): {qdata['note']}")
                continue
            lines.extend([
                "-" * 78,
                f"  📊 分位数分析: {fname} (N={qdata.get('n', 0)})",
                "-" * 78,
                f"  {'分位':<6s} {'范围':<16s} {'数量':>4s} {'胜率':>8s} {'均收益':>10s}",
                f"  {'─'*6} {'─'*16} {'─'*4} {'─'*8} {'─'*10}",
            ])
            for b in bins:
                lines.append(
                    f"  {b['bin']:<6s} {b['range']:<16s} {b['count']:>4d} "
                    f"{b['hit_rate']:>7.0%} {b['avg_return']:>+9.2f}%"
                )
            spread_ret = qdata.get("q_high_minus_low_return")
            spread_hit = qdata.get("q_high_minus_low_hit_rate")
            if spread_ret is not None and spread_hit is not None:
                lines.append(
                    f"  {'─'*6} {'─'*16} {'─'*4} {'─'*8} {'─'*10}\n"
                    f"  {'Q4-Q1':<6s} {'—':<16s} {'—':>4s} "
                    f"{spread_hit:>+7.0%} {spread_ret:>+9.2f}%  ← 分位差"
                )
            lines.append("")

        # ── 局限性 ──
        if meta.get("small_sample"):
            lines.extend([
                "-" * 78,
                "  ⚠️ 局限性说明",
                "-" * 78,
                f"  · 当前仅 {meta['tracked_stocks']} 只有效追踪样本，所有结论为初步观察",
                "  · 随着每日追踪数据积累（预计 2-4 周后 N>30），分析将具统计意义",
                "  · 连续因子方差较小时（如技术评分高度集中），相关性指标失效",
                "  · IC_IR 需多日 IC 序列才能计算，当前单日截面无法评估因子稳定性",
                "",
            ])

        lines.append("")
        return "\n".join(lines)

    def _format_json(self, r: dict) -> str:
        """将分析结果渲染为 JSON 字符串"""
        return json.dumps(r, ensure_ascii=False, indent=2, default=str)


# ═══════════════════════════════════════════════════════════════════
# 单例 + 便捷函数
# ═══════════════════════════════════════════════════════════════════

_engine: Optional[FactorAnalyzerEngine] = None


def get_engine(config: dict = None) -> FactorAnalyzerEngine:
    """获取全局因子分析引擎实例（单例模式）"""
    global _engine
    if _engine is None:
        _engine = FactorAnalyzerEngine(config)
    return _engine


def analyze_factors(config: dict = None) -> dict:
    """便捷函数：运行因子有效性分析"""
    engine = get_engine(config)
    return engine.analyze()


# ═══════════════════════════════════════════════════════════════════
# CLI 查询工具
# ═══════════════════════════════════════════════════════════════════

def _load_config() -> dict:
    """加载配置文件（CLI 模式）"""
    try:
        import yaml
        config_path = os.path.join(
            os.path.dirname(os.path.dirname(__file__)),
            "config", "config.yaml"
        )
        if os.path.exists(config_path):
            with open(config_path, "r", encoding="utf-8") as f:
                return yaml.safe_load(f)
    except Exception:
        pass
    return {}


if __name__ == "__main__":
    import argparse
    import sys

    # Windows UTF-8
    if sys.platform == "win32":
        import io
        sys.stdout = io.TextIOWrapper(
            sys.stdout.buffer, encoding="utf-8", errors="replace"
        )

    parser = argparse.ArgumentParser(
        description="因子有效性检验工具 (Phase 3.2)"
    )
    parser.add_argument(
        "--format", type=str, default="table",
        choices=["table", "markdown", "json"],
        help="输出格式: table(默认), markdown, json"
    )
    args = parser.parse_args()

    config = _load_config()
    engine = get_engine(config)
    results = engine.analyze()

    if args.format == "json":
        print(engine._format_json(results))
    elif args.format == "markdown":
        print(engine._format_markdown(results))
    else:
        print(engine._format_cli(results))
