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

# 量化跟投模块 (Phase 5)
python -m src.quant --pick              # 从推荐池筛选候选标的
python -m src.quant --symbol 000001     # 对指定标的全流程分析+信号
python -m src.quant --status            # 查看持仓状态+浮动盈亏
python -m src.quant --backtest 000001   # 历史回测验证
python -m src.quant --watch             # 每日跟踪模式（自动加载观察列表）
python -m src.quant --daily-run         # 自动化日终管线（信号+推送，CI调用）
python -m src.quant --execute           # 模拟执行当前信号

# 安装依赖（需要代理）
export https_proxy=http://127.0.0.1:7897 http_proxy=http://127.0.0.1:7897
pip install -r requirements.txt

# 数据库查询 (Phase 3.1 / 3.4)
python -m src.database --stats          # 全量统计（胜率、板块、信心度）
python -m src.database --history 7      # 最近N天记录摘要
python -m src.database --date 2026-06-01  # 指定日期报告详情
python -m src.database --recent         # 最近一次报告详情
python -m src.database --strategy       # 策略回测：按追强/抄底/事件驱动维度的胜率对比
python -m src.database --backfill-strategy  # 回填已有推荐行的策略标签

# 因子有效性分析 (Phase 3.2)
python -m src.factor_analyzer               # CLI表格（默认）
python -m src.factor_analyzer --format markdown  # Markdown输出
python -m src.factor_analyzer --format json      # JSON输出
```

## 标准文件路径索引

| 文件 | 路径 | 用途 | 变更频率 |
|:---|:---|:---|:---|
| **项目说明** | [CLAUDE.md](CLAUDE.md) | AI助手上下文：架构、约定、状态 | 每次会话更新 |
| **开发日志** | [DEVLOG.md](DEVLOG.md) | 每日开发记录、路线图、待办池 | 每次开发会话更新 |
| **README** | [README.md](README.md) | 面向用户的说明文档 | 版本发布时更新 |
| **主入口** | [src/main.py](src/main.py) | CLI参数解析、三阶段编排、入口函数 | 新增通道/参数时 |
| **市场数据** | [src/market_data.py](src/market_data.py) | 三层数据源（实时API+akshare增强+历史）+ Prompt格式化注入 | 新增数据维度时 |
| **数据模型** | [src/models.py](src/models.py) | NewsItem / Recommendation / DailyReport 定义 | 新增数据字段时 |
| **聚合器** | [src/aggregator.py](src/aggregator.py) | 多因子评分：关键词+情绪+来源+资金共振+跨源+质量 | 调整因子权重时 |
| **追踪器** | [src/tracker.py](src/tracker.py) | 昨日推荐vs今日行情对比，胜率/均收益统计 | 新增追踪维度时 |
| **确认引擎** | [src/confirmation.py](src/confirmation.py) | 资金流向×新闻情绪双重确认，信心度调整（Phase 2.1） | 调整确认逻辑时 |
| **技术面过滤** | [src/technical_filter.py](src/technical_filter.py) | 实时行情+K线技术指标过滤，评分×信心度（Phase 2.2） | 调整过滤逻辑时 |
| **推荐数据库** | [src/database.py](src/database.py) | SQLite持久化+历史查询+统计+策略回测+CLI工具（Phase 3.1/3.4） | 调整统计维度时 |
| **因子分析** | [src/factor_analyzer.py](src/factor_analyzer.py) | 因子有效性检验：相关性+IC+分组+分位数+排名（Phase 3.2） | 累积20+追踪样本后 |
| **策略分类** | [src/strategy_classifier.py](src/strategy_classifier.py) | 规则打分三维归类：追强/抄底/事件驱动（Phase 3.3） | 调整权重时 |
| **量化模块入口** | [src/quant/__init__.py](src/quant/__init__.py) | Phase 5 量化跟投模块入口（独立于推荐管线） | 新增模块时 |
| **量化数据模型** | [src/quant/models.py](src/quant/models.py) | QuantSignal / Position / TradeRecord / BacktestResult | 新增字段时 |
| **技术指标** | [src/quant/indicators.py](src/quant/indicators.py) | MACD/RSI/布林/KDJ/ATR/ADX/OBV 纯Python计算 | 新增指标时 |
| **市场状态** | [src/quant/regime.py](src/quant/regime.py) | 趋势/震荡/过渡识别 → 自适应策略切换 | 调整判定逻辑时 |
| **信号引擎** | [src/quant/signals.py](src/quant/signals.py) | 多因子规则打分 → 开/加/持/减/清/观望 | 调整因子权重时 |
| **仓位风控** | [src/quant/risk.py](src/quant/risk.py) | 仓位计算+止损止盈+风控熔断+T+1约束 | 调整风控参数时 |
| **持仓跟踪** | [src/quant/tracker.py](src/quant/tracker.py) | JSON持久化+浮动盈亏+交易历史+信号快照 | 改存储结构时 |
| **标的筛选** | [src/quant/stock_picker.py](src/quant/stock_picker.py) | 从推荐池SQLite量化选Top3候选 | 调整筛选维度时 |
| **历史回测** | [src/quant/backtest.py](src/quant/backtest.py) | 单标的历史回测（T+1/手续费/印花税） | 调整回测逻辑时 |
| **量化引擎** | [src/quant/engine.py](src/quant/engine.py) | QuantEngine主引擎编排所有子模块 | 改主流程时 |
| **量化CLI** | [src/quant/cli.py](src/quant/cli.py) | CLI：--pick/--symbol/--status/--backtest/--watch | 新增命令时 |
| **AI分析** | [src/ai_analyzer.py](src/ai_analyzer.py) | DeepSeek API调用 + System Prompt + JSON解析 | 调Prompt/换模型时 |
| **格式化** | [src/formatter.py](src/formatter.py) | Markdown/纯文本/HTML邮件/HTML网页 四种输出 | 改模板样式时 |
| **推送模块** | [src/pusher.py](src/pusher.py) | BasePusher + 4通道 + 注册表 + Pusher管理器 | 新增推送通道时 |
| **爬虫基类** | [src/scrapers/base.py](src/scrapers/base.py) | UA轮换、重试、HTML/JSON通用获取 | 不常改 |
| **爬虫注册** | [src/scrapers/__init__.py](src/scrapers/__init__.py) | SCRAPER_REGISTRY + collect_all_news() | 新增爬虫时 |
| **东方财富** | [src/scrapers/eastmoney.py](src/scrapers/eastmoney.py) | 研报+板块资金流+概念资金流 | API变更时 |
| **新浪财经** | [src/scrapers/sina.py](src/scrapers/sina.py) | 要闻滚动+龙虎榜 | API变更时 |
| **财联社** | [src/scrapers/cls.py](src/scrapers/cls.py) | 快讯（默认关闭） | 修复后启用 |
| **雪球** | [src/scrapers/xueqiu.py](src/scrapers/xueqiu.py) | 社区情绪（需cookie） | 配置后启用 |
| **环境变量** | [.env.example](.env.example) | 所有环境变量模板（API Key/SMTP/微信） | 新增配置项时 |
| **应用配置** | [config/config.example.yaml](config/config.example.yaml) | 功能开关/爬虫/AI/推送参数 | 新增功能开关时 |
| **CI/CD** | [.github/workflows/daily-push.yml](.github/workflows/daily-push.yml) | 交易日8:30自动运行+提交网页 | 改流程时 |
| **依赖** | [requirements.txt](requirements.txt) | Python依赖列表 | 新增库时 |
| **原始数据** | data/*_raw.json | 爬虫采集的原始新闻缓存 | 每日自动 |
| **报告输出** | output/*_report.json | AI分析后的结构化报告 | 每日自动 |
| **网页归档** | docs/*.html | GitHub Pages 静态网页 | 每日自动 |

## 项目架构

```
Daily Stock Picks/
├── src/
│   ├── main.py              # 主入口，编排三阶段流程
│   ├── models.py            # 数据模型：NewsItem, Recommendation, DailyReport
│   ├── aggregator.py        # 多因子评分：关键词+情绪+来源+资金共振+跨源+质量
│   ├── market_data.py       # 市场数据：指数/资金流实时采集 + Prompt注入
│   ├── tracker.py           # 追踪器：昨日推荐vs今日表现对比反馈
│   ├── ai_analyzer.py       # AI分析：DeepSeek API 调用 + Prompt 管理
│   ├── formatter.py         # 格式化：Markdown / 纯文本 / 邮件HTML / 网页HTML
│   ├── pusher.py            # 推送：BasePusher基类 + 4通道 + PUSHER_REGISTRY
│   ├── confirmation.py     # 双重确认：资金流向×新闻情绪交叉验证（Phase 2.1）
│   ├── technical_filter.py # 技术面过滤：实时行情+K线+评分（Phase 2.2）
│   ├── database.py         # SQLite数据库：持久化+历史查询+统计（Phase 3.1）
│   ├── factor_analyzer.py  # 因子有效性检验：相关性+IC+排名（Phase 3.2）
│   ├── strategy_classifier.py  # 策略分层：追强/抄底/事件驱动三维归类（Phase 3.3）
│   └── quant/                   # Phase 5: 量化跟投模块（独立于推荐管线）
│       ├── __init__.py          # 模块入口，导出公共接口
│       ├── models.py            # 数据模型：信号/持仓/交易/回测
│       ├── indicators.py        # 技术指标：MACD/RSI/布林/KDJ/ATR/ADX
│       ├── regime.py            # 市场状态识别：趋势/震荡自适应
│       ├── signals.py           # 信号引擎：多因子规则打分
│       ├── engine.py            # 主引擎：编排所有子模块
│       ├── risk.py              # 仓位风控：止损止盈+熔断
│       ├── tracker.py           # 持仓跟踪：JSON持久化
│       ├── stock_picker.py      # 选股：从推荐池量化筛选
│       ├── backtest.py          # 回测：历史策略验证
│       └── cli.py               # CLI入口
├── scrapers/
│       ├── __init__.py      # 爬虫注册中心 SCRAPER_REGISTRY
│       ├── base.py          # 基类：UA轮换、重试、HTML/JSON通用方法
│       ├── cls.py           # 财联社（API不稳定，默认关闭）
│       ├── eastmoney.py     # 东方财富（研报+资金流，主力源）
│       ├── sina.py          # 新浪财经（要闻，稳定）
│       └── xueqiu.py        # 雪球（需cookie，默认关闭）
├── config/
│   └── config.example.yaml  # 配置模板（复制为config.yaml使用）
├── output/                  # 每日报告JSON
├── data/                    # 原始采集数据缓存
├── docs/                    # GitHub Pages 网页归档
├── .github/workflows/
│   └── daily-push.yml       # 每个交易日 8:30 CST 触发
├── .env.example             # 环境变量模板
├── requirements.txt
├── README.md
├── CLAUDE.md                # AI助手上下文（本文件）
└── DEVLOG.md                # 开发日志 + 路线图 + 待办池
```

## 数据流

```
采集 (scrapers/) → 聚合 (aggregator.py) → AI分析 (ai_analyzer.py) → 推送 (pusher.py)
                                                                      ├── 邮箱 (SMTP QQ/163)
                                                                      ├── 微信 (Server酱)
                                                                      ├── CLI  (stdout)
                                                                      ├── Web  (docs/*.html)
                                                                      └── DB   (data/recommendations.db)

数据流新增：AI分析后 → 确认引擎 → 技术过滤 → 策略分层 → 追踪 → DB存储 → 推送
```

## 开发工作流

### 日常开发会话

1. **开始前** — 查看 [DEVLOG.md](DEVLOG.md) 了解当前阶段和待办事项
2. **开发中** — 遵循下方"关键约定"中的各模块规范
3. **收尾时** — 更新 [DEVLOG.md](DEVLOG.md) 记录：
   - 今日完成的事项（带符号标注：🚀新功能 🐛修复 🔧重构 📝文档）
   - 遇到的问题和解决方案
   - 新的待办事项
4. **提交时** — Commit message 引用 Phase/任务编号，例如 `feat: 市场数据注入 (Phase 1.1)`

### 添加新功能的标准流程

- **新爬虫**：写爬虫类 → [__init__.py](src/scrapers/__init__.py) 注册 → [config.example.yaml](config/config.example.yaml) 加开关 → [CLAUDE.md](CLAUDE.md) 更新状态表
- **新推送通道**：写Pusher类 → [pusher.py](src/pusher.py) 注册表加一行 → [config.example.yaml](config/config.example.yaml) 加开关 → [.env.example](.env.example) 加配置 → [daily-push.yml](.github/workflows/daily-push.yml) 加Secret
- **新数据模型**：在 [models.py](src/models.py) 定义 dataclass → 相关模块导入使用

### 代码风格

- Python 类型注解：所有函数签名标注参数和返回值类型
- 异常处理：爬虫/推送失败不阻断主流程，返回空列表或 False
- 日志：使用 `logging.getLogger(__name__)`，关键节点打 INFO，调试细节打 DEBUG
- 编码：Windows 环境下注意 GBK 兼容，终端输出做 UTF-8 wrap
- 文档字符串：使用中文，类和公开方法必须有 docstring

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
- 推送通道继承 `BasePusher` 抽象基类，通过 `PUSHER_REGISTRY` 注册
- 通道选择：YAML `enabled` 标志 或 CLI `--push email,wechat,cli,web` 参数
- 推送通道独立实现，各通道失败互不影响
- 邮件正文同时包含纯文本和HTML版本，支持 QQ邮箱(587/STARTTLS) 和 163邮箱(465/SSL)
- 微信推送通过 Server酱 (ServerChan) 实现
- CLI输出需处理 Windows GBK 编码问题

## 环境要求

- Python 3.9+（开发机 3.9.7）
- 需要代理访问外网（默认 `127.0.0.1:7897`）
- DeepSeek API Key（必填）
- QQ邮箱 SMTP 授权码（邮件推送可选）

## 变更记录

| 日期 | 版本 | 变更内容 |
|------|------|---------|
| 2026-06-15 | v3.0 | Phase 5: 量化跟投模块 — 独立 src/quant/ (11文件) + 指标/状态/信号/风控/回测/CLI |
| 2026-06-12 | v2.5 | Phase 3.4: 策略回测（按策略维度胜率对比 + DB策略回填 + --strategy CLI）|
| 2026-06-10 | v2.4 | Phase 3.3: 策略分层（追强/抄底/事件驱动三维规则打分+管线注入+四格式输出）|
| 2026-06-10 | — | fix: _safe_float() 处理push2 API返回字符串类型数值 |  
| 2026-06-05 | v2.3 | Phase 3.2: 因子有效性检验（相关性+IC+分组对比+分位数+排名+CLI工具） |
| 2026-06-04 | v2.2 | Phase 3.1: SQLite 推荐数据库 + from_dict() + CLI查询工具(--stats/--history/--date/--recent) |
| 2026-06-04 | v2.1 | Phase 2.3: 聚合器多因子重构（6维度评分：关键词+情绪+来源+资金共振+跨源+质量） |
| 2026-06-03 | v2.0 | UI全面重构：CLI框线+评分条、HTML现代财经简报、Markdown表格化、GitHub Pages响应式 |
| 2026-06-02 | v1.6 | Phase 2.1: 双重确认引擎（资金流向×新闻情绪交叉验证+信心度调整） |
| 2026-06-02 | v1.5.1 | BugFix: GitHub Actions 交易日检查双重Bug + market_data push2→Sina API |
| 2026-06-01 | v1.5 | Phase 1.3: akshare增强行情（北向资金+主力趋势+板块排名分层架构） |
| 2026-06-01 | v1.4 | Phase 1.2 次日追踪：src/tracker.py（推荐回顾+胜率统计）+ report.tracking字段 + 三种输出格式回顾区块 |
| 2026-05-31 | v1.3 | Phase 1.1 市场数据注入：src/market_data.py（指数+资金流+成交额）+ 文档体系（DEVLOG + CLAUDE.md路径索引） |
| 2026-05-31 | v1.2 | 推送模块重构：BasePusher抽象基类 + 通道注册表 + 微信推送(Server酱) + 163邮箱支持(SSL) + CLI `--push` 通道选择 |
| 2026-05-31 | v1.1 | 邮件HTML模板升级为现代卡片风（渐变头部 + 三栏网格 + 信心度色标） |
| 2026-05-31 | v1.0 | 首次发布：多源采集 + AI分析 + 邮件/CLI/Web推送 + GitHub Actions |

## 当前状态

| 模块 | 状态 | 备注 |
|------|------|------|
| 市场数据(实时) | ✅ 就绪 | 东方财富 push2 API：指数+板块资金流+成交额 |
| 市场数据(增强) | ✅ 新增 | akshare：北向资金+主力趋势+板块排名 |
| 次日追踪 | ✅ 就绪 | 昨日推荐vs今日行情对比，胜率统计 |
| 双重确认引擎 | ✅ 就绪 | 资金流向×新闻情绪交叉验证（Phase 2.1） |
| 技术面过滤 | ✅ 新增 | K线均线+量能+超买检测+综合评分（Phase 2.2） |
| 多因子聚合 | ✅ 新增 | 6维度加权评分替代纯关键词匹配（Phase 2.3） |
| SQLite 数据库 | ✅ 新增 | 推荐持久化+历史查询+统计分析+CLI工具（Phase 3.1） |
| 因子有效性检验 | ✅ 新增 | 相关性+IC+分组+分位数+因子排名（Phase 3.2） |
| 策略分层 | ✅ 新增 | 追强/抄底/事件驱动三维规则打分（Phase 3.3） |
| 策略回测 | ✅ 新增 | 按策略维度胜率对比统计 + DB回填（Phase 3.4） |
| 量化跟投模块 | ✅ 新增 | 独立 src/quant/ — 指标/状态/信号/风控/回测/CLI（Phase 5） |
| AI分析 | ✅ 就绪 | DeepSeek API 已配置，正常运行 |
| QQ邮箱推送 | ✅ 就绪 | SMTP 587/STARTTLS，授权码登录 |
| 163邮箱推送 | ✅ 就绪 | SMTP 465/SSL，授权码登录 |
| 微信推送 | ✅ 新增 | Server酱 (sct.ftqq.com)，需 WECHAT_SENDKEY |
| 通道选择 | ✅ 新增 | YAML `enabled` 或 CLI `--push email,wechat,...` |
| GitHub Actions | ⚠️ 待验证 | 代码已推送，Secrets已配置，待交易日自动触发验证 |
| GitHub Pages | ⚠️ 待验证 | 需在仓库Settings中启用Pages（Source: main, /docs） |

## 后续计划

详细路线图和待办事项见 **[DEVLOG.md](DEVLOG.md)**，以下为阶段概览：

| Phase | 周期 | 目标 | 入口 |
|:---|:---|:---|:---|
| Phase 1 | 2026-05-31 ~ 06-07 | 基础夯实：市场数据注入 + 次日追踪 + akshare | [DEVLOG.md](DEVLOG.md) |
| Phase 2 | 2026-06-03 ~ 06-04 | 量化因子：资金×情绪确认 ✅ + 技术面过滤 ✅ + 多因子打分 ✅ | [DEVLOG.md](DEVLOG.md) |
| Phase 3 | 2026-06-04 ~ 06-21 | 数据沉淀：SQLite推荐库 ✅ + 因子检验 ✅ + 策略分层 ✅ + 策略回测 ✅ | [DEVLOG.md](DEVLOG.md) |
| Phase 4 | 2026-06-22+ | 策略进化：新数据源 + 行业热力图 + 报告升级 | [DEVLOG.md](DEVLOG.md) |
| Phase 5 | 2026-06-15 | 量化跟投模块：11文件/指标/状态/信号/风控/回测/CLI ✅ | [DEVLOG.md](DEVLOG.md) |

**当前优先事项（P0）：**
- [ ] 数据源稳定性 — push2/akshare 连接频繁断开，需增加重试机制或替代源
- [x] Phase 5: 量化跟投模块 — 独立 src/quant/ (11文件) ✅
- [ ] GitHub Pages 启用 — 仓库 Settings → Pages → main /docs
- [x] Phase 3.4: 策略回测 — 按策略维度胜率对比 ✅
- [x] Phase 3.1-3.3 全部完成：SQLite数据库 + 因子分析 + 策略分层
- [x] CI git push 已修复（reset--soft 替代 rebase），待下次交易日验证
