"""推荐数据库模块 — SQLite 持久化 + 历史查询 + 统计分析

Phase 3.1: 结构化存储每日推荐、标的、追踪数据，支持 CLI 查询和统计。

表结构：
  reports         — 每日报告（1行/天）
  recommendations — AI 推荐板块（1行/推荐）
  stocks          — 推荐标的（1行/只），含次日追踪表现

设计原则：
  - 零外部依赖（仅 stdlib sqlite3 + json）
  - 数据库故障不阻断主管道（所有异常捕获 → warning）
  - 遵循 confirmation/technical_filter 的 Engine + Singleton + Convenience 模式
"""

import json
import logging
import os
import sqlite3
from datetime import datetime
from glob import glob
from typing import Dict, List, Optional

from src.models import DailyReport

logger = logging.getLogger(__name__)

# ═══════════════════════════════════════════════════════════════════
# Schema 定义
# ═══════════════════════════════════════════════════════════════════

SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS reports (
    date                TEXT PRIMARY KEY,
    raw_news_count      INTEGER NOT NULL DEFAULT 0,
    sources_used        TEXT NOT NULL DEFAULT '[]',
    confirmation_summary TEXT NOT NULL DEFAULT '',
    technical_summary   TEXT NOT NULL DEFAULT '',
    tracking_json       TEXT NOT NULL DEFAULT '{}',
    generated_at        TEXT NOT NULL,
    created_at          TEXT NOT NULL DEFAULT (datetime('now', 'localtime'))
);

CREATE TABLE IF NOT EXISTS recommendations (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    report_date     TEXT NOT NULL,
    sector          TEXT NOT NULL,
    confidence      TEXT NOT NULL,
    strategy        TEXT NOT NULL DEFAULT '',
    strategy_score  INTEGER NOT NULL DEFAULT 0,
    logic           TEXT NOT NULL,
    catalyst        TEXT NOT NULL,
    risk            TEXT NOT NULL,
    sources_json    TEXT NOT NULL DEFAULT '[]',
    confirmation_json TEXT NOT NULL DEFAULT '{}',
    technical_json  TEXT NOT NULL DEFAULT '{}',
    sort_order      INTEGER NOT NULL DEFAULT 0,
    FOREIGN KEY (report_date) REFERENCES reports(date) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS stocks (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    recommendation_id   INTEGER NOT NULL,
    name                TEXT NOT NULL,
    code                TEXT NOT NULL,
    technical_score     INTEGER,
    change_pct_at_rec   REAL,
    turnover_rate       REAL,
    circulating_cap_yi  REAL,
    tracking_change_pct REAL,
    tracking_hit        INTEGER,
    tracking_price      REAL,
    tracking_updated    TEXT,
    FOREIGN KEY (recommendation_id) REFERENCES recommendations(id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_recs_date ON recommendations(report_date);
CREATE INDEX IF NOT EXISTS idx_stocks_rec ON stocks(recommendation_id);
CREATE INDEX IF NOT EXISTS idx_stocks_code ON stocks(code);
CREATE INDEX IF NOT EXISTS idx_stocks_tracking ON stocks(tracking_change_pct, tracking_hit);
"""


# ═══════════════════════════════════════════════════════════════════
# DatabaseEngine
# ═══════════════════════════════════════════════════════════════════

class DatabaseEngine:
    """SQLite 推荐数据库引擎

    用法：
        engine = DatabaseEngine(config)
        engine.save_report(report)
        engine.update_tracking(date, tracking_data)
        stats = engine.get_stats()
    """

    def __init__(self, config: dict = None):
        cfg = config or {}
        db_cfg = cfg.get("database", {})
        self.enabled = db_cfg.get("enabled", True)
        self.migrate_on_start = db_cfg.get("migrate_on_start", True)

        db_path = db_cfg.get("path", "data/recommendations.db")
        if not os.path.isabs(db_path):
            project_root = os.path.dirname(os.path.dirname(__file__))
            db_path = os.path.join(project_root, db_path)
        self.db_path = db_path

        self._conn: Optional[sqlite3.Connection] = None
        self._migrated = False

    # ── 连接管理 ───────────────────────────────────────────────

    def _connect(self) -> sqlite3.Connection:
        """惰性连接（WAL 模式，外键强制）"""
        if self._conn is not None:
            return self._conn
        os.makedirs(os.path.dirname(self.db_path), exist_ok=True)
        conn = sqlite3.connect(self.db_path)
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA foreign_keys=ON")
        conn.row_factory = sqlite3.Row
        self._conn = conn
        logger.debug(f"数据库连接: {self.db_path}")
        return conn

    def close(self):
        """关闭数据库连接"""
        if self._conn is not None:
            self._conn.close()
            self._conn = None

    # ── Schema 迁移 ────────────────────────────────────────────

    def _migrate_schema(self):
        """执行建表 + 增量迁移（幂等）"""
        try:
            conn = self._connect()
            conn.executescript(SCHEMA_SQL)
            conn.commit()
            # Phase 3.4 增量迁移：为已有 recommendations 表添加 strategy 列
            self._migrate_add_strategy_columns(conn)
            logger.debug("数据库 schema 就绪")
        except Exception as e:
            logger.warning(f"数据库 schema 迁移失败: {e}")

    def _migrate_add_strategy_columns(self, conn: sqlite3.Connection):
        """检查并添加 strategy / strategy_score 列（兼容 v3.3 之前的 DB）"""
        cols = {row[1] for row in conn.execute("PRAGMA table_info(recommendations)")}
        if "strategy" not in cols:
            conn.execute("ALTER TABLE recommendations ADD COLUMN strategy TEXT NOT NULL DEFAULT ''")
            logger.info("数据库迁移: 已添加 recommendations.strategy 列")
        if "strategy_score" not in cols:
            conn.execute("ALTER TABLE recommendations ADD COLUMN strategy_score INTEGER NOT NULL DEFAULT 0")
            logger.info("数据库迁移: 已添加 recommendations.strategy_score 列")

    # ── 写操作 ─────────────────────────────────────────────────

    def save_report(self, report: DailyReport) -> bool:
        """保存完整日报到数据库（单事务）

        Args:
            report: DailyReport 实例（已完成确认+技术过滤+追踪）

        Returns:
            True 成功，False 失败（已自动降级）
        """
        if not self.enabled:
            return True

        try:
            self._migrate_schema()

            # 首次空库自动迁移 JSON
            if not self._migrated and self.migrate_on_start:
                self._import_json_reports()
                self._migrated = True

            conn = self._connect()

            with conn:  # 事务
                # 1. 写入 reports
                conn.execute("""
                    INSERT OR REPLACE INTO reports
                        (date, raw_news_count, sources_used,
                         confirmation_summary, technical_summary,
                         tracking_json, generated_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                """, (
                    report.date,
                    report.raw_news_count,
                    json.dumps(report.sources_used, ensure_ascii=False),
                    report.confirmation_summary or "",
                    report.technical_summary or "",
                    json.dumps(report.tracking or {}, ensure_ascii=False),
                    report.generated_at or datetime.now().isoformat(),
                ))

                # 2. 写入 recommendations + stocks
                for i, rec in enumerate(report.recommendations):
                    # 收集 confirmation / technical / strategy 元数据
                    confirmation = getattr(rec, "confirmation", {}) or {}
                    technical = getattr(rec, "technical", {}) or {}
                    strategy = getattr(rec, "strategy", "") or ""
                    strategy_score = getattr(rec, "strategy_score", 0) or 0

                    cursor = conn.execute("""
                        INSERT INTO recommendations
                            (report_date, sector, confidence, strategy, strategy_score,
                             logic, catalyst, risk, sources_json,
                             confirmation_json, technical_json, sort_order)
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """, (
                        report.date,
                        rec.sector,
                        rec.confidence,
                        strategy,
                        strategy_score,
                        rec.logic,
                        rec.catalyst,
                        rec.risk,
                        json.dumps(rec.source if hasattr(rec, "source") else [], ensure_ascii=False),
                        json.dumps(confirmation, ensure_ascii=False),
                        json.dumps(technical, ensure_ascii=False),
                        i,
                    ))
                    rec_id = cursor.lastrowid

                    # 提取每只标的的技术面详情
                    stock_tech_map: Dict[str, dict] = {}
                    for sr in technical.get("stock_results", []):
                        stock_tech_map[sr.get("code", "")] = sr

                    for stock in rec.stocks:
                        code = stock.get("code", "")
                        tech_info = stock_tech_map.get(code, {})
                        conn.execute("""
                            INSERT INTO stocks
                                (recommendation_id, name, code,
                                 technical_score, change_pct_at_rec,
                                 turnover_rate, circulating_cap_yi)
                            VALUES (?, ?, ?, ?, ?, ?, ?)
                        """, (
                            rec_id,
                            stock.get("name", ""),
                            code,
                            tech_info.get("technical_score"),
                            tech_info.get("change_pct"),
                            tech_info.get("turnover_rate"),
                            tech_info.get("circulating_cap_yi"),
                        ))

            logger.info(
                f"报告已存入数据库: {report.date} "
                f"({len(report.recommendations)}条推荐, "
                f"{sum(len(r.stocks) for r in report.recommendations)}只标的)"
            )
            return True

        except Exception as e:
            logger.warning(f"数据库保存失败 (非致命，管道继续): {e}")
            return False

    def update_tracking(self, date: str, tracking_data: dict) -> bool:
        """将今日追踪结果写入昨日推荐的 stocks 行

        Args:
            date: 当前日期（用于上下文日志，实际匹配 prev_date）
            tracking_data: track_yesterday() 返回的追踪 dict

        Returns:
            True 成功/跳过，False 失败
        """
        if not self.enabled:
            return True
        if not tracking_data:
            return True

        prev_date = tracking_data.get("prev_date")
        if not prev_date:
            return True

        stocks_list = tracking_data.get("stocks", [])
        if not stocks_list:
            return True

        # 确保 schema 就绪（首次运行时 save_report 尚未调用）
        self._migrate_schema()

        try:
            conn = self._connect()
            now = datetime.now().isoformat()

            updated = 0
            with conn:
                for stock in stocks_list:
                    cursor = conn.execute("""
                        UPDATE stocks SET
                            tracking_change_pct = ?,
                            tracking_hit = ?,
                            tracking_price = ?,
                            tracking_updated = ?
                        WHERE code = ?
                          AND recommendation_id IN (
                              SELECT id FROM recommendations WHERE report_date = ?
                          )
                    """, (
                        stock.get("change_pct"),
                        1 if stock.get("hit") else 0,
                        stock.get("price"),
                        now,
                        stock.get("code", ""),
                        prev_date,
                    ))
                    updated += cursor.rowcount

            logger.info(
                f"数据库追踪更新: {prev_date} → "
                f"{updated}/{len(stocks_list)}只标的"
            )
            return True

        except Exception as e:
            logger.warning(f"数据库追踪更新失败 (非致命): {e}")
            return False

    # ── JSON 迁移 ──────────────────────────────────────────────

    def _import_json_reports(self) -> int:
        """首次运行时从 output/*_report.json 批量导入历史数据

        Returns:
            导入报告数
        """
        try:
            conn = self._connect()
            row = conn.execute("SELECT COUNT(*) as cnt FROM reports").fetchone()
            if row["cnt"] > 0:
                logger.debug(f"数据库已有 {row['cnt']} 条记录，跳过迁移")
                return 0
        except Exception:
            logger.debug("reports 表不存在，即将创建并迁移")
            self._migrate_schema()

        # 扫描 output 目录
        output_dir = os.path.join(os.path.dirname(os.path.dirname(__file__)), "output")
        pattern = os.path.join(output_dir, "*_report.json")
        files = sorted(glob(pattern))

        if not files:
            logger.info("未找到历史 JSON 报告，跳过迁移")
            return 0

        imported = 0
        for filepath in files:
            try:
                with open(filepath, "r", encoding="utf-8") as f:
                    data = json.load(f)
                report = DailyReport.from_dict(data)
                # 直接写DB，跳过 migrate_on_start 检查避免递归
                with self._conn:
                    conn = self._connect()
                    conn.execute("""
                        INSERT OR REPLACE INTO reports
                            (date, raw_news_count, sources_used,
                             confirmation_summary, technical_summary,
                             tracking_json, generated_at)
                        VALUES (?, ?, ?, ?, ?, ?, ?)
                    """, (
                        report.date,
                        report.raw_news_count,
                        json.dumps(report.sources_used, ensure_ascii=False),
                        report.confirmation_summary or "",
                        report.technical_summary or "",
                        json.dumps(report.tracking or {}, ensure_ascii=False),
                        report.generated_at or "",
                    ))

                    for i, rec in enumerate(report.recommendations):
                        cursor = conn.execute("""
                            INSERT INTO recommendations
                                (report_date, sector, confidence, logic, catalyst,
                                 risk, sources_json, confirmation_json, technical_json, sort_order)
                            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                        """, (
                            report.date,
                            rec.sector,
                            rec.confidence,
                            rec.logic,
                            rec.catalyst,
                            rec.risk,
                            json.dumps(rec.source if hasattr(rec, "source") else [], ensure_ascii=False),
                            "{}",
                            "{}",
                            i,
                        ))
                        rec_id = cursor.lastrowid

                        for stock in rec.stocks:
                            conn.execute("""
                                INSERT INTO stocks
                                    (recommendation_id, name, code)
                                VALUES (?, ?, ?)
                            """, (rec_id, stock.get("name", ""), stock.get("code", "")))

                imported += 1
                logger.info(f"迁移: {os.path.basename(filepath)} → {len(report.recommendations)}条推荐")

            except Exception as e:
                logger.warning(f"迁移文件失败 (跳过): {filepath} — {e}")

        if imported > 0:
            logger.info(f"JSON 迁移完成: {imported} 份报告入库")
        return imported

    # ── 读操作 ─────────────────────────────────────────────────

    def get_history(self, days: int = 7) -> List[dict]:
        """获取最近 N 天的报告摘要列表

        Returns:
            [{date, raw_news_count, rec_count, stock_count,
              hit_count, miss_count, avg_return, hit_rate}, ...]
        """
        if not self.enabled:
            return []
        try:
            conn = self._connect()
            rows = conn.execute("""
                SELECT
                    r.date,
                    r.raw_news_count,
                    r.generated_at,
                    COUNT(DISTINCT rec.id) as rec_count,
                    COUNT(s.id) as stock_count,
                    ROUND(AVG(CASE WHEN s.tracking_change_pct IS NOT NULL
                                   THEN s.tracking_change_pct END), 2) as avg_return,
                    SUM(CASE WHEN s.tracking_hit = 1 THEN 1 ELSE 0 END) as hit_count,
                    SUM(CASE WHEN s.tracking_hit = 0 THEN 1 ELSE 0 END) as miss_count
                FROM reports r
                LEFT JOIN recommendations rec ON rec.report_date = r.date
                LEFT JOIN stocks s ON s.recommendation_id = rec.id
                GROUP BY r.date
                ORDER BY r.date DESC
                LIMIT ?
            """, (days,))
            return [dict(row) for row in rows.fetchall()]
        except Exception as e:
            logger.warning(f"历史查询失败: {e}")
            return []

    def get_stats(self) -> dict:
        """获取全量统计数据

        Returns:
            {total_days, total_recommendations, total_stocks,
             overall_hit_rate, overall_avg_return, total_tracked, total_hits,
             by_confidence: [{confidence, total, hits, avg_return}],
             top_sectors: [{sector, total, hits, avg_return}],
             best_stock: {name, code, tracking_change_pct},
             worst_stock: {name, code, tracking_change_pct},
             by_alignment: [{alignment, total, avg_return}]}
        """
        if not self.enabled:
            return {}
        try:
            conn = self._connect()
            stats: dict = {}

            # 基本计数
            row = conn.execute("SELECT COUNT(*) as cnt FROM reports").fetchone()
            stats["total_days"] = row["cnt"]

            row = conn.execute("SELECT COUNT(*) as cnt FROM recommendations").fetchone()
            stats["total_recommendations"] = row["cnt"]

            row = conn.execute("SELECT COUNT(*) as cnt FROM stocks").fetchone()
            stats["total_stocks"] = row["cnt"]

            # 总体胜率和均收益
            row = conn.execute("""
                SELECT
                    COUNT(*) as tracked,
                    SUM(CASE WHEN tracking_hit = 1 THEN 1 ELSE 0 END) as hits,
                    ROUND(AVG(tracking_change_pct), 2) as avg_return
                FROM stocks
                WHERE tracking_change_pct IS NOT NULL
            """).fetchone()

            if row["tracked"]:
                stats["overall_hit_rate"] = round(
                    row["hits"] / row["tracked"], 3
                )
                stats["overall_avg_return"] = row["avg_return"]
                stats["total_tracked"] = row["tracked"]
                stats["total_hits"] = row["hits"]

            # 按信心度
            rows = conn.execute("""
                SELECT
                    r.confidence,
                    COUNT(s.id) as total,
                    SUM(CASE WHEN s.tracking_hit = 1 THEN 1 ELSE 0 END) as hits,
                    ROUND(AVG(s.tracking_change_pct), 2) as avg_return
                FROM stocks s
                JOIN recommendations r ON r.id = s.recommendation_id
                WHERE s.tracking_change_pct IS NOT NULL
                GROUP BY r.confidence
                ORDER BY avg_return DESC
            """).fetchall()
            stats["by_confidence"] = [dict(row) for row in rows]

            # 最佳板块 TOP10
            rows = conn.execute("""
                SELECT
                    r.sector,
                    COUNT(s.id) as total,
                    ROUND(AVG(s.tracking_change_pct), 2) as avg_return,
                    SUM(CASE WHEN s.tracking_hit = 1 THEN 1 ELSE 0 END) as hits
                FROM stocks s
                JOIN recommendations r ON r.id = s.recommendation_id
                WHERE s.tracking_change_pct IS NOT NULL
                GROUP BY r.sector
                ORDER BY avg_return DESC
                LIMIT 10
            """).fetchall()
            stats["top_sectors"] = [dict(row) for row in rows]

            # 最佳/最差单票
            best = conn.execute("""
                SELECT name, code, tracking_change_pct
                FROM stocks
                WHERE tracking_change_pct IS NOT NULL
                ORDER BY tracking_change_pct DESC LIMIT 1
            """).fetchone()
            stats["best_stock"] = dict(best) if best else {}

            worst = conn.execute("""
                SELECT name, code, tracking_change_pct
                FROM stocks
                WHERE tracking_change_pct IS NOT NULL
                ORDER BY tracking_change_pct ASC LIMIT 1
            """).fetchone()
            stats["worst_stock"] = dict(worst) if worst else {}

            # 确认信号 vs 实际表现
            rows = conn.execute("""
                SELECT
                    json_extract(r.confirmation_json, '$.alignment') as alignment,
                    COUNT(s.id) as total,
                    ROUND(AVG(s.tracking_change_pct), 2) as avg_return
                FROM stocks s
                JOIN recommendations r ON r.id = s.recommendation_id
                WHERE s.tracking_change_pct IS NOT NULL
                  AND r.confirmation_json != '{}'
                GROUP BY alignment
                ORDER BY avg_return DESC
            """).fetchall()
            stats["by_alignment"] = [
                dict(row) for row in rows if row["alignment"]
            ]

            return stats

        except Exception as e:
            logger.warning(f"统计查询失败: {e}")
            return {"error": str(e)}

    def get_report(self, date: str) -> Optional[dict]:
        """查询指定日期的报告详情

        Returns:
            {date, raw_news_count, sources_used, recommendations: [
                {sector, confidence, logic, catalyst, risk,
                 stocks: [{name, code, technical_score, tracking_change_pct, ...}]}]}
        """
        if not self.enabled:
            return None
        try:
            conn = self._connect()

            report_row = conn.execute(
                "SELECT * FROM reports WHERE date = ?", (date,)
            ).fetchone()
            if not report_row:
                return None

            result = dict(report_row)
            result["sources_used"] = json.loads(result.get("sources_used", "[]"))
            result["tracking"] = json.loads(result.get("tracking_json", "{}"))

            rec_rows = conn.execute("""
                SELECT * FROM recommendations
                WHERE report_date = ?
                ORDER BY sort_order
            """, (date,)).fetchall()

            recommendations = []
            for r in rec_rows:
                rec = dict(r)
                rec["source"] = json.loads(rec.pop("sources_json", "[]"))
                rec["confirmation"] = json.loads(rec.pop("confirmation_json", "{}"))
                rec["technical"] = json.loads(rec.pop("technical_json", "{}"))

                stock_rows = conn.execute("""
                    SELECT * FROM stocks WHERE recommendation_id = ?
                """, (rec["id"],)).fetchall()
                rec["stocks"] = [dict(s) for s in stock_rows]
                recommendations.append(rec)

            result["recommendations"] = recommendations
            return result

        except Exception as e:
            logger.warning(f"报告查询失败 ({date}): {e}")
            return None


    # ── 策略回测 (Phase 3.4) ────────────────────────────────────

    def get_strategy_stats(self) -> dict:
        """按策略维度统计胜率和收益率

        Returns:
            {by_strategy: [{strategy, rec_count, total, tracked, hits, hit_rate, avg_return}],
             unlabeled_count: int}
        """
        if not self.enabled:
            return {}
        try:
            self._migrate_schema()
            conn = self._connect()
            rows = conn.execute("""
                SELECT
                    r.strategy,
                    COUNT(DISTINCT r.id) as rec_count,
                    COUNT(s.id) as total,
                    SUM(CASE WHEN s.tracking_change_pct IS NOT NULL THEN 1 ELSE 0 END) as tracked,
                    SUM(CASE WHEN s.tracking_hit = 1 THEN 1 ELSE 0 END) as hits,
                    ROUND(AVG(CASE WHEN s.tracking_change_pct IS NOT NULL
                                   THEN s.tracking_change_pct END), 2) as avg_return
                FROM recommendations r
                LEFT JOIN stocks s ON s.recommendation_id = r.id
                WHERE r.strategy != ''
                GROUP BY r.strategy
                ORDER BY avg_return DESC
            """).fetchall()

            # 未标注数量
            unlabeled = conn.execute(
                "SELECT COUNT(*) as cnt FROM recommendations WHERE strategy = '' OR strategy IS NULL"
            ).fetchone()

            return {
                "by_strategy": [dict(row) for row in rows],
                "unlabeled_count": unlabeled["cnt"] if unlabeled else 0,
            }
        except Exception as e:
            logger.warning(f"策略统计查询失败: {e}")
            return {"error": str(e)}

    def backfill_strategies(self, config: dict = None) -> int:
        """回填已有推荐行的 strategy 字段

        从 technical_json + confidence + catalyst 重新运行策略分类。
        仅在 strategy 为空时更新。

        Returns:
            更新行数
        """
        try:
            from src.strategy_classifier import StrategyClassifierEngine

            self._migrate_schema()  # 确保 strategy 列已存在
            conn = self._connect()

            rows = conn.execute("""
                SELECT id, confidence, catalyst, logic, sector, technical_json
                FROM recommendations
                WHERE strategy = '' OR strategy IS NULL
            """).fetchall()

            if not rows:
                logger.info("策略回填: 所有推荐已有标签，跳过")
                return 0

            engine = StrategyClassifierEngine(config or {})
            updated = 0

            with conn:
                for row in rows:
                    tech = json.loads(row["technical_json"] or "{}")
                    stock_results = tech.get("stock_results", [])

                    score_data = {
                        "confidence": row["confidence"],
                        "catalyst": row["catalyst"],
                        "logic": row["logic"],
                        "sector": row["sector"],
                        "stock_results": stock_results,
                    }

                    strategy, strategy_score = engine._classify_from_db(score_data)

                    conn.execute(
                        "UPDATE recommendations SET strategy = ?, strategy_score = ? WHERE id = ?",
                        (strategy, strategy_score, row["id"]),
                    )
                    updated += 1

            logger.info(f"策略回填完成: {updated} 行")
            return updated

        except ImportError:
            logger.warning("策略回填失败: strategy_classifier 模块不可用")
            return 0
        except Exception as e:
            logger.warning(f"策略回填失败: {e}")
            return 0


# ═══════════════════════════════════════════════════════════════════
# 单例 + 便捷函数
# ═══════════════════════════════════════════════════════════════════

_engine: Optional[DatabaseEngine] = None


def get_engine(config: dict = None) -> DatabaseEngine:
    """获取全局数据库引擎实例（单例模式）"""
    global _engine
    if _engine is None:
        _engine = DatabaseEngine(config)
    return _engine


def save_report(report: DailyReport, config: dict = None) -> bool:
    """便捷函数：保存日报到数据库"""
    engine = get_engine(config)
    return engine.save_report(report)


def update_tracking(date: str, tracking_data: dict, config: dict = None) -> bool:
    """便捷函数：更新昨日标的的追踪数据"""
    engine = get_engine(config)
    return engine.update_tracking(date, tracking_data)


# ═══════════════════════════════════════════════════════════════════
# CLI 查询工具
# ═══════════════════════════════════════════════════════════════════


def _print_stats(stats: dict):
    """格式化打印统计数据"""
    print("\n" + "=" * 60)
    print("  📊 推荐系统统计")
    print("=" * 60)

    if stats.get("error"):
        print(f"  ❌ 查询失败: {stats['error']}\n")
        return

    print(f"  累计运行天数: {stats.get('total_days', 0)}")
    print(f"  累计推荐数:   {stats.get('total_recommendations', 0)}")
    print(f"  累计标的数:   {stats.get('total_stocks', 0)}")

    if "overall_hit_rate" in stats:
        print()
        print(f"  🎯 总体胜率: {stats['overall_hit_rate']:.1%}  "
              f"({stats['total_hits']}/{stats['total_tracked']})")
        print(f"  📈 均收益:   {stats['overall_avg_return']:+.2f}%")

    if stats.get("by_confidence"):
        print("\n  ── 按信心度 ──")
        for row in stats["by_confidence"]:
            total = row["total"]
            hits = row["hits"]
            hit_rate = hits / total if total > 0 else 0
            print(f"  {row['confidence']}信心: 胜率 {hit_rate:.0%} ({hits}/{total})  "
                  f"均收益 {row['avg_return']:+.2f}%")

    if stats.get("top_sectors"):
        print("\n  ── 最佳板块 TOP5 ──")
        for row in stats["top_sectors"][:5]:
            print(f"  {row['sector']:<16s} 均收益 {row['avg_return']:+.2f}%  "
                  f"({row['hits']}/{row['total']})")

    if stats.get("best_stock") and stats["best_stock"].get("name"):
        bs = stats["best_stock"]
        ws = stats["worst_stock"]
        print(f"\n  🏆 最佳单票: {bs.get('name', '?')}({bs.get('code', '?')})  "
              f"{bs.get('tracking_change_pct', 0):+.2f}%")
        print(f"  💀 最差单票: {ws.get('name', '?')}({ws.get('code', '?')})  "
              f"{ws.get('tracking_change_pct', 0):+.2f}%")

    if stats.get("by_alignment"):
        print("\n  ── 确认信号 vs 实际表现 ──")
        icons = {
            "confirmed_bullish": "🟢", "confirmed_bearish": "🔴",
            "divergent": "⚠️", "uncertain": "❓",
        }
        for row in stats["by_alignment"]:
            icon = icons.get(row["alignment"], "—")
            print(f"  {icon} {row['alignment']:<20s} {row['total']:>3d}次  "
                  f"均收益 {row['avg_return']:+.2f}%")
    print()


def _print_history(history: List[dict]):
    """格式化打印历史记录"""
    if not history:
        print("\n  (暂无历史数据)\n")
        return

    print("\n" + "=" * 75)
    print(f"  📅 最近 {len(history)} 天推荐记录")
    print("=" * 75)
    header = f"  {'日期':<12s} {'推荐':>4s} {'标的':>4s} {'追踪':>4s} {'胜率':>6s} {'均收益':>8s}"
    print(header)
    print("  " + "-" * 55)
    for row in history:
        tracked = (row.get("hit_count", 0) or 0) + (row.get("miss_count", 0) or 0)
        hits = row.get("hit_count", 0) or 0
        hit_rate = hits / tracked if tracked > 0 else 0
        avg_ret = row.get("avg_return")
        avg_str = f"{avg_ret:+.2f}%" if avg_ret is not None else "—"
        hit_str = f"{hit_rate:.0%}" if tracked > 0 else "—"
        print(f"  {row['date']:<12s} {row.get('rec_count',0) or 0:>4d} "
              f"{row.get('stock_count',0) or 0:>4d} {tracked:>4d} {hit_str:>6s} {avg_str:>8s}")
    print()


def _print_report(report: Optional[dict]):
    """格式化打印单日报告详情"""
    if not report:
        print("\n  (未找到该日报告)\n")
        return

    print("\n" + "=" * 70)
    print(f"  📄 {report['date']} 报告详情")
    print("=" * 70)
    print(f"  新闻数: {report.get('raw_news_count', 0)}")
    print(f"  信息源: {', '.join(report.get('sources_used', []))}")
    print()

    STRATEGY_EMOJI = {"追强": "🚀", "抄底": "🎯", "事件驱动": "⚡", "观望": "👀"}

    for i, rec in enumerate(report.get("recommendations", []), 1):
        strat = rec.get("strategy", "")
        strat_str = f"  [{STRATEGY_EMOJI.get(strat, '')} {strat}]" if strat else ""
        print(f"  ── 推荐 {i}: {rec['sector']} [{rec['confidence']}信心]{strat_str} ──")
        print(f"  逻辑: {rec['logic'][:120]}")
        print(f"  催化: {rec['catalyst'][:120]}")
        print(f"  风险: {rec['risk'][:120]}")

        # 确认信号
        if rec.get("confirmation") and rec["confirmation"].get("alignment"):
            conf = rec["confirmation"]
            align_icon = {
                "confirmed_bullish": "🟢", "confirmed_bearish": "🔴",
                "divergent": "⚠️", "uncertain": "❓",
            }.get(conf["alignment"], "—")
            print(f"  确认: {align_icon} {conf['alignment']} — {conf.get('explanation', '')[:80]}")

        # 标的
        for s in rec.get("stocks", []):
            tscore = s.get("technical_score")
            tscore_str = f"评分{tscore}" if tscore else "—"
            chg = s.get("change_pct_at_rec")
            chg_str = f"{chg:+.1f}%" if chg is not None else ""

            track_chg = s.get("tracking_change_pct")
            if track_chg is not None:
                track_icon = "✅" if s.get("tracking_hit") else "❌"
                track_str = f"→ 次日 {track_icon} {track_chg:+.2f}%"
            else:
                track_str = "→ 待追踪"

            print(f"    {s['name']}({s['code']})  {tscore_str} {chg_str}  {track_str}")
        print()

    # 追踪回顾
    tracking = report.get("tracking", {})
    if tracking and tracking.get("stocks"):
        print(f"  ── 昨日推荐回顾 ({tracking.get('prev_date', '?')}) ──")
        if tracking.get("total_count", 0) > 0:
            print(f"  胜率 {tracking['hit_rate']:.0%} · "
                  f"均收益 {tracking['avg_return']:+.2f}% · "
                  f"{tracking['hit_count']}涨/{tracking['miss_count']}跌")
        print()

    # 摘要
    if report.get("confirmation_summary"):
        print(f"  ── 确认摘要 ──")
        print(f"  {report['confirmation_summary'][:200]}")
        print()

    if report.get("technical_summary"):
        print(f"  ── 技术摘要 ──")
        print(f"  {report['technical_summary'][:200]}")
        print()


def _load_config() -> dict:
    """加载配置文件（CLI 模式）"""
    try:
        import yaml
        config_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), "config", "config.yaml")
        if os.path.exists(config_path):
            with open(config_path, "r", encoding="utf-8") as f:
                return yaml.safe_load(f)
    except Exception:
        pass
    return {}


def _print_strategy_stats(stats: dict):
    """格式化打印策略回测统计"""
    STRATEGY_EMOJI = {"追强": "🚀", "抄底": "🎯", "事件驱动": "⚡", "观望": "👀"}

    print("\n" + "=" * 65)
    print("  📐 策略回测 — 按策略维度胜率对比 (Phase 3.4)")
    print("=" * 65)

    if stats.get("error"):
        print(f"  ❌ {stats['error']}\n")
        return

    by_strategy = stats.get("by_strategy", [])
    if not by_strategy:
        print("  (暂无策略数据，运行 python -m src.database --backfill-strategy 回填)\n")
        return

    print(f"  {'策略':<12s} {'推荐':>4s} {'标的':>4s} {'可追踪':>6s} {'胜率':>8s} {'均收益':>10s}")
    print("  " + "-" * 55)

    total_recs = 0
    total_tracked = 0
    total_hits = 0
    for row in by_strategy:
        strat = row["strategy"]
        se = STRATEGY_EMOJI.get(strat, "📌")
        rec_count = row["rec_count"] or 0
        tracked = row["tracked"] or 0
        hits = row["hits"] or 0
        hit_rate = f"{hits / tracked:.0%}" if tracked > 0 else "—"
        avg_ret = f"{row['avg_return']:+.2f}%" if row["avg_return"] is not None else "—"

        total_recs += rec_count
        total_tracked += tracked
        total_hits += hits

        print(f"  {se} {strat:<8s} {rec_count:>4d} {row['total']:>4d} "
              f"{tracked:>6d} {hit_rate:>8s} {avg_ret:>10s}")

    print("  " + "-" * 55)
    overall_rate = f"{total_hits / total_tracked:.0%}" if total_tracked > 0 else "—"
    print(f"  {'合计':<12s} {total_recs:>4d} {'':>4s} {total_tracked:>6d} {overall_rate:>8s}")
    print()

    # 对比分析
    if len(by_strategy) >= 2:
        print("  ── 策略对比 ──")
        strategies_with_data = [
            r for r in by_strategy if (r["tracked"] or 0) >= 2
        ]
        if strategies_with_data:
            best = max(strategies_with_data, key=lambda r: r["avg_return"] or -999)
            worst = min(strategies_with_data, key=lambda r: r["avg_return"] or 999)
            bse = STRATEGY_EMOJI.get(best["strategy"], "📌")
            wse = STRATEGY_EMOJI.get(worst["strategy"], "📌")
            print(f"  🏆 最优: {bse} {best['strategy']} 均收益 {best['avg_return']:+.2f}% "
                  f"(胜率 {best['hits']}/{best['tracked']})")
            print(f"  ⚠️  最弱: {wse} {worst['strategy']} 均收益 {worst['avg_return']:+.2f}% "
                  f"(胜率 {worst['hits']}/{worst['tracked']})")

    unlabeled = stats.get("unlabeled_count", 0)
    if unlabeled > 0:
        print(f"\n  💡 {unlabeled} 条推荐尚无策略标签，运行 --backfill-strategy 回填")
    print()


if __name__ == "__main__":
    import argparse
    import sys

    # Windows UTF-8
    if sys.platform == "win32":
        import io
        sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

    parser = argparse.ArgumentParser(description="推荐数据库查询工具 (Phase 3.1 / 3.4)")
    parser.add_argument("--stats", action="store_true", help="显示全量统计数据")
    parser.add_argument("--history", type=int, default=None, metavar="N",
                        help="显示最近N天记录 (默认7)")
    parser.add_argument("--date", type=str, default=None, metavar="YYYY-MM-DD",
                        help="查询指定日期的推荐详情")
    parser.add_argument("--recent", action="store_true",
                        help="显示最近一次推荐详情")
    parser.add_argument("--strategy", action="store_true",
                        help="Phase 3.4: 按策略维度对比胜率")
    parser.add_argument("--backfill-strategy", action="store_true",
                        help="Phase 3.4: 回填已有推荐行的策略标签")
    args = parser.parse_args()

    config = _load_config()
    engine = get_engine(config)

    # Phase 3.4: 策略回填（先执行，因为后续查询依赖它）
    if args.backfill_strategy:
        n = engine.backfill_strategies(config)
        print(f"\n  策略回填完成: {n} 行已更新\n")

    if args.strategy:
        _print_strategy_stats(engine.get_strategy_stats())

    # 默认行为：显示历史
    show_default = not (args.stats or args.date or args.recent
                        or args.strategy or args.backfill_strategy)

    if args.stats:
        _print_stats(engine.get_stats())

    if show_default:
        days = args.history or 7
        _print_history(engine.get_history(days))

    if args.history is not None and not show_default:
        _print_history(engine.get_history(args.history))

    if args.recent:
        history = engine.get_history(1)
        if history:
            _print_report(engine.get_report(history[0]["date"]))
        else:
            print("\n  (暂无历史数据)\n")

    if args.date:
        _print_report(engine.get_report(args.date))
