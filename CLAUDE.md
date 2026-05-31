# CLAUDE.md

## 项目概述

每日A股智能推荐系统 — AI驱动的短线投资参考工具。自动抓取财经新闻/券商研报，通过 DeepSeek API 综合分析，每日推送 5 条精简推荐（含板块、标的、逻辑、风险）。

## 命令

```bash
# 本地干运行（完整流程，仅CLI输出，不推送）
python -m src.main --local

# 干运行 + 保存原始数据
python -m src.main --dry-run

# 仅测试爬虫采集
python -m src.main --scrape-only

# 指定日期运行
python -m src.main --date 2026-06-01

# 安装依赖（需要代理）
export https_proxy=http://127.0.0.1:7897 http_proxy=http://127.0.0.1:7897
pip install -r requirements.txt
```

## 项目架构

```
Daily Stock Picks/
├── src/
│   ├── main.py              # 主入口，编排三阶段流程
│   ├── models.py            # 数据模型：NewsItem, Recommendation, DailyReport
│   ├── aggregator.py        # 聚合器：去重 → 关键词打分 → 排序截断
│   ├── ai_analyzer.py       # AI分析：DeepSeek API 调用 + Prompt 管理
│   ├── formatter.py         # 格式化：Markdown / 纯文本 / HTML
│   ├── pusher.py            # 推送：EmailPusher, CLIPusher, WebPusher
│   └── scrapers/
│       ├── __init__.py      # 爬虫注册中心 SCRAPER_REGISTRY
│       ├── base.py          # 基类：UA轮换、重试、HTML/JSON通用方法
│       ├── cls.py           # 财联社（API不稳定，默认关闭）
│       ├── eastmoney.py     # 东方财富（研报+资金流，主力源）
│       ├── sina.py          # 新浪财经（要闻，稳定）
│       └── xueqiu.py        # 雪球（需cookie，默认关闭）
├── config/
│   └── config.example.yaml  # 配置模板（复制为config.yaml使用）
├── output/                  # 每日报告JSON/MD
├── data/                    # 原始采集数据缓存
├── docs/                    # GitHub Pages 网页归档
├── .github/workflows/
│   └── daily-push.yml       # 每个交易日 8:30 CST 触发
├── .env.example             # 环境变量模板
├── requirements.txt
└── README.md
```

## 数据流

```
采集 (scrapers/) → 聚合 (aggregator.py) → AI分析 (ai_analyzer.py) → 推送 (pusher.py)
                                                                      ├── 邮箱 (SMTP)
                                                                      ├── CLI  (stdout)
                                                                      └── Web  (docs/*.html)
```

## 关键约定

### 爬虫开发
- 所有爬虫继承 `BaseScraper`（`src/scrapers/base.py`），实现 `scrape() -> List[NewsItem]`
- 新增源在 `src/scrapers/__init__.py` 的 `SCRAPER_REGISTRY` 注册
- 返回统一 `NewsItem` 模型（`src/models.py`）
- 爬虫间完全独立，一个源失效不影响其他
- 采集异常必须捕获，返回空列表而非抛出

### 配置管理
- 敏感信息（API Key、邮箱密码）通过 `.env` 环境变量注入
- 功能开关通过 `config/config.yaml` 控制
- GitHub Actions 通过仓库 Secrets 注入环境变量

### AI 分析
- 系统提示词在 `src/ai_analyzer.py:SYSTEM_PROMPT`
- 输出必须是结构化JSON，包含 `recommendations` 数组
- 支持 DeepSeek 和 Anthropic 两个 Provider（通过配置切换）
- API不可用时降级为空报告，不阻断管道

### 推送
- 推送通道独立实现，各通道失败互不影响
- 邮件正文同时包含纯文本和HTML版本
- CLI输出需处理 Windows GBK 编码问题

## 环境要求

- Python 3.9+（开发机 3.9.7）
- 需要代理访问外网（默认 `127.0.0.1:7897`）
- DeepSeek API Key（必填）
- QQ邮箱 SMTP 授权码（邮件推送可选）

## 变更记录

| 日期 | 版本 | 变更内容 |
|------|------|---------|
| 2026-05-31 | v1.1 | 邮件HTML模板升级为现代卡片风（渐变头部 + 三栏网格 + 信心度色标） |
| 2026-05-31 | v1.0 | 首次发布：多源采集 + AI分析 + 邮件/CLI/Web推送 + GitHub Actions |

## 当前状态

| 模块 | 状态 | 备注 |
|------|------|------|
| 东方财富 | ✅ 稳定 | 研报数据源，实测30条/次 |
| 新浪财经 | ✅ 稳定 | 要闻，实测31条/次 |
| 财联社 | ⚠️ 关闭 | API接口404，需更新endpoint |
| 雪球 | 📦 关闭 | 需配置cookie后启用 |
| AI分析 | ✅ 就绪 | DeepSeek API 已配置，正常运行 |
| 邮箱推送 | ✅ 就绪 | QQ邮箱SMTP 已配置，正常运行 |
| GitHub Actions | ⚠️ 待验证 | 代码已推送，Secrets已配置，待交易日自动触发验证 |
| GitHub Pages | ⚠️ 待验证 | 需在仓库Settings中启用Pages（Source: main, /docs） |

## 后续计划

| 优先级 | 事项 | 说明 |
|--------|------|------|
| P0 | GitHub Actions 首跑验证 | 下一个交易日确认定时推送正常工作 |
| P0 | GitHub Pages 启用 | 仓库 Settings → Pages → main /docs |
| P1 | 邮件模板迭代 | 根据实际使用反馈调整配色/排版 |
| P1 | GitHub Pages 网页美化 | 网页版同步邮件模板的卡片风格 |
| P2 | 财联社爬虫修复 | 更新API endpoint，恢复正常采集 |
| P2 | 微信推送接入 | Server酱 / 企业微信Bot |
| P2 | 雪球爬虫启用 | 配置cookie后接入社区情绪数据 |
| P3 | 推荐效果回测 | 每日记录推荐标的次日表现，评估AI准确率 |
