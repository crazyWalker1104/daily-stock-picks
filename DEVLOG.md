# 开发日志 · Daily Stock Picks

> 最后更新：2026-06-04 | 当前阶段：Phase 3 — 数据沉淀（3.1 ✅，3.2 待启动）

---

## 符号说明

| 符号 | 含义 |
|:---|:---|
| ✅ | 已完成 |
| 🔄 | 进行中 |
| ⏳ | 待开始 |
| ❌ | 已取消 |
| 🐛 | Bug修复 |
| 🔧 | 重构/优化 |
| 📝 | 文档 |
| 🚀 | 新功能 |
| ⚠️ | 阻塞/问题 |

---

## 开发路线图

### Phase 1：基础夯实（当前） `2026-05-31 ~ 2026-06-07`

目标：补齐基础设施，让推荐有数据支撑，建立反馈闭环。

| # | 任务 | 状态 | 优先级 | 预计行数 | 依赖 |
|:---|:---|:---|:---|:---|:---|
| 1.1 | 市场实况数据注入 — AI Prompt 增加结构化行情数据 | ✅ | P0 | ~150 | — |
| 1.2 | 次日推荐追踪 — 自动对比昨日推荐 vs 今日涨跌 | ✅ | P0 | ~200 | — |
| 1.3 | 依赖升级 — 安装 akshare，获取个股K线/北向资金 | ✅ | P0 | ~10 | — |
| 1.4 | `requirements.txt` 补全 akshare | ✅ | P1 | ~1 | 1.3 |

### Phase 2：量化因子引入 `计划 2026-06-08 ~ 2026-06-14`

目标：用数据替代"拍脑袋"，引入多因子评分。

| # | 任务 | 状态 | 优先级 | 依赖 |
|:---|:---|:---|:---|:---|
| 2.1 | 资金流向×新闻情绪双重确认引擎 | ✅ | P0 | Phase 1 |
| 2.2 | 推荐后处理：技术面过滤（涨幅/量能/均线） | ✅ | P0 | 1.3 |
| 2.3 | 聚合器重构：多因子打分替换纯关键词匹配 | ✅ | P1 | 2.1 |

### Phase 3：回测与数据沉淀 `计划 2026-06-15 ~ 2026-06-21`

目标：积累数据，量化评估 AI 推荐质量。

| # | 任务 | 状态 | 优先级 | 依赖 |
|:---|:---|:---|:---|:---|
| 3.1 | SQLite 推荐数据库 + 历史查询 | ✅ | P0 | Phase 2 |
| 3.2 | 因子有效性检验 — 哪个指标真正预测了涨跌？ | ⏳ | P1 | 3.1 |
| 3.3 | 策略分层：追强/抄底/事件驱动三条线 | ⏳ | P2 | 3.1 |

### Phase 4：策略进化 `计划 2026-06-22+`

| # | 任务 | 状态 | 备注 |
|:---|:---|:---|:---|
| 4.1 | 更多数据源（龙虎榜明细、两融余额、大宗交易） | ⏳ | akshare 已支持 |
| 4.2 | 行业轮动热力图 | ⏳ | 可视化板块强弱 |
| 4.3 | 邮件报告增加回顾区块 | ⏳ | 用户看到的不只是推荐，还有效果 |
| 4.4 | GitHub Pages 报告美化 | ⏳ | 匹配邮件模板的卡片风格 |

---

## 每日记录

### 2026-05-31 (周六) — v1.3

**完成事项：**
- 🚀 推送模块重构：`BasePusher` 抽象基类 + `PUSHER_REGISTRY` 通道注册表
- 🚀 新增微信推送通道：`WeChatPusher`（Server酱 ServerChan）
- 🚀 新增163邮箱支持：端口465→SMTP_SSL，587→STARTTLS 自动适配
- 🚀 CLI 新增 `--push` 通道选择参数（逗号分隔，支持 email,wechat,cli,web）
- 🚀 通道选择支持双模式：CLI `--push` 指定 或 YAML `enabled` 标志
- 🚀 **Phase 1.1 完成**：新增 [src/market_data.py](src/market_data.py) 市场实况数据模块
  - 三大指数实时行情（上证/深证/创业板）
  - 行业板块主力资金净流入/流出 TOP5
  - 两市成交额统计
  - 格式化为结构化文本注入 AI Prompt
  - 休日/API故障自动降级，不阻断管道
- 🐛 修复 CLI 默认开启逻辑：`"cli" not in push_config` 正确检查 cli 段是否存在
- 🐛 修复163邮箱测试：SMTP_HOST 从 qq.com 改为 163.com 后发送成功
- 📝 新增 [DEVLOG.md](DEVLOG.md) 开发日志 + 4阶段路线图
- 📝 更新 [CLAUDE.md](CLAUDE.md) 标准文件路径索引 + 开发工作流指引
- 📝 更新 .env.example 添加163邮箱配置示例

**当前状态：**
- v1.2 已提交推送（commit: 5a6046e）
- v1.3（Phase 1.1 市场数据 + 文档体系）待提交
- 改动文件：[src/market_data.py](src/market_data.py) (新), [src/ai_analyzer.py](src/ai_analyzer.py), [src/main.py](src/main.py), [CLAUDE.md](CLAUDE.md), [DEVLOG.md](DEVLOG.md)
- 163 邮箱推送已验证可用
- 微信推送待配置 WECHAT_SENDKEY 后验证
- GitHub Actions 待下个交易日自动触发验证

**待办事项：**
- [ ] 提交 Phase 1.1 变更
- [ ] 下个交易日验证市场数据 API 返回真实数据
- [ ] Phase 1.2: 次日推荐追踪

---

### 2026-06-01 (周一) — v1.5

**完成事项：**
- 🚀 **Phase 1.2 完成**：新增 [src/tracker.py](src/tracker.py) 次日推荐追踪模块
  - 自动加载昨日报告，提取推荐标的
  - 批量获取个股实时行情（东方财富API）
  - 计算胜率、均收益、涨跌统计
  - 三种输出格式（Markdown/纯文本/HTML邮件）均追加回顾区块
- 🚀 **Phase 1.3 完成**：akshare 增强行情数据模块
  - 新增 `fetch_north_bound_flow()` — 北向资金（沪深港通）当日流向，支持 akshare + 直接API双通道
  - 新增 `fetch_market_flow_trend()` — 近5日主力资金流向趋势（主力态度判断：偏多/偏空/中性）
  - 新增 `fetch_sector_rank_ak()` — 行业+概念板块资金排名（akshare，作为Layer1实时API的补充）
  - 数据源分层架构：Layer1 实时(push2 API) + Layer2 增强(akshare) + Layer3 历史(后续)
  - 北向资金格式化注入AI Prompt（外资动向+方向判断）
  - 主力资金趋势注入AI Prompt（近5日每日明细+态度总结）
  - 概念板块排名作为实时API的fallback数据源
  - akshare 懒加载机制，未安装时不影响其他模块
- 🔧 [src/models.py](src/models.py)：DailyReport 新增 `tracking` 字段
- 🔧 [src/formatter.py](src/formatter.py)：format_markdown/format_plain/format_email_html 均增加回顾区块
- 📝 更新 [README.md](README.md)：补全功能列表、项目结构、邮箱/微信配置说明
- 📝 更新 [CLAUDE.md](CLAUDE.md)：文件索引新增 tracker.py，版本更新 v1.4

**遇到的问题：**
- 东方财富 push2 API 盘前大面积 `RemoteDisconnected`（指数/板块/个股行情全部断连）— 仅北向资金(akshare)成功
- 确认盘前(9:00-9:30)是API薄弱窗口期，9:30开盘后应恢复
- akshare 的 `stock_sector_fund_flow_rank` 和 `stock_market_fund_flow` 底层也走东方财富，同样受盘前影响

**待办事项：**
- [ ] 9:30开盘后验证所有行情API真实数据
- [ ] Phase 2.1: 资金流向×新闻情绪双重确认引擎

---

### 2026-06-02 (周二) — v1.6

**完成事项：**
- 🚀 **Phase 2.1 完成**：新增 [src/confirmation.py](src/confirmation.py) 双重确认引擎
  - `DualConfirmationEngine` 类：资金流向×新闻情绪交叉验证
  - 北向资金信号提取（5级方向+强度分类：strong/moderate/weak inflow/outflow/neutral）
  - 板块级新闻情绪分析（正/负面信号词典 + 模糊板块关键词匹配）
  - 4种对齐判断：confirmed_bullish / confirmed_bearish / divergent / uncertain
  - 信心度自动调整（双确认→+1级，背离→-1级，不确定→不变）
  - 异常风险标注（背离警告自动注入 risk 字段）
  - Markdown/HTML邮件/纯文本 三种格式均追加确认摘要区块
- 🐛 **修复 GitHub Actions 交易日检查双重 Bug**（v1.5.1）
- 🐛 **修复 market_data.py push2.eastmoney.com 被墙问题**：指数行情改用 Sina API
- 🔧 `main.py`：消除 `collect_market_data()` 重复调用（节省 ~20s）
- 📝 更新 DEVLOG.md 路线图 Phase 2.1 标记完成

**遇到的问题：**
- 北向资金盘初数据为 0（中性），导致确认引擎对所有推荐输出 uncertain — 数据驱动下这是正确的保守行为，盘中有方向性数据后会触发确认/背离判断
- `push2.eastmoney.com` 完全被墙影响板块资金流、个股行情等多个模块，需要找替代数据源

**验证结果：**
- 6/1 推荐追踪：5/5 全涨，均收益 **+4.25%** 🎉（软通动力+7.34%、巨化股份+4.85%、天孚通信+4.41%）
- 确认引擎成功检测到板块级新闻情绪（AI算力 5+/11条、有色金属 2+/4条）
- AI 推荐 + 确认引擎 + 追踪 全管道串通

**待办事项：**
- [ ] 等待明日(6/3 周三)8:30 GitHub Actions 自动触发验证
- [ ] Phase 2.2: 技术面过滤（涨幅/量能/均线）
- [ ] 推送通道确认（用户反馈邮件接收情况）
- [ ] 财联社爬虫修复

---

### 2026-06-03 (周三) — v1.7

**完成事项：**
- 🚀 **Phase 2.2 完成**：新增 [src/technical_filter.py](src/technical_filter.py) 技术面过滤引擎
  - `TechnicalFilterEngine` 类：实时行情+K线数据交叉验证AI推荐标的
  - 基础过滤（无需K线）：ST检查、涨停接近度、换手率、流通市值、日内振幅
  - 增强过滤（需K线）：MA5/MA10/MA20均线位置、量能异常（放量/缩量）、连续上涨天数（超买检测）
  - 综合评分系统（0-100）：换手率+市值+涨跌幅+振幅+均线+量能多维度加权
  - 信心度自动调整：标的被排除→降级，所有标的评分>75→升级
  - K线 fallback 机制：push2实时API失败时，用 akshare K线末条收盘价/量替代
  - Markdown/HTML/纯文本三种格式均追加技术面过滤摘要
- 🐛 **修复代理阻塞**：[src/scrapers/base.py](src/scrapers/base.py) `requests.Session()` 新增 `trust_env = False`，绕开系统代理直接访问国内金融站点
- 🔧 [src/models.py](src/models.py) `DailyReport` 新增 `technical_summary` 字段
- 🔧 [src/main.py](src/main.py) 管道新增 Phase 2.2 步骤（Phase 2.1 确认引擎之后）
- 🔧 [config/config.example.yaml](config/config.example.yaml) 新增 `technical_filter` 配置节

**验证结果：**
- 6/2→6/3 追踪：5涨/1跌，胜率83%，均收益 **+5.97%** 🎉
- 技术面过滤今日通过 8/8 只标的，均线多头排列 4只(88分)、MA20之上 3只(78分)、MA20之下 1只(63分)
- QQ邮箱 + 微信 + CLI + Web 四通道推送全部成功

**遇到的问题：**
- `push2.eastmoney.com` 实时行情API不稳定（RemoteDisconnected），但 K线 fallback 机制已完善解决
- 代理 `127.0.0.1:7897` 未启动导致所有爬虫阻塞 → `trust_env = False` 修复
- 财联社爬虫持续返回0条
- Git push 因网络问题仍无法推送到 origin（本地 commits 积压 2个）

- 🎨 **UI 全面重构**（v2.0）：[src/formatter.py](src/formatter.py) 四种输出格式重新设计
  - CLI 输出：框线头部 + 分隔线层次 + 可视化评分条（█▓▒░）+ 每标的单行技术摘要
  - Markdown：推荐卡片三列表格（逻辑/催化/风险）+ 技术评分行内显示
  - HTML 邮件：现代财经简报风格 — 暗色渐变头部、评分进度条、三列Grid、信心度色标
  - GitHub Pages：全新 CSS 设计（Grid布局 + 卡片阴影 + 响应式 + 移动端适配）
  - 确认摘要精简：同 alignment 板块合并一行，资金信号/板块情绪各一行
  - 技术摘要精简：每标的单行概要（分数 · 均线 · 涨跌 · 市值），警告/危险标记展开
  - 追踪格式：表格式明细（标的/板块/信心/今日表现）
- 🔧 [src/confirmation.py](src/confirmation.py) `get_summary()` 合并同 alignment 板块，新增板块情绪统计
- 🔧 [src/technical_filter.py](src/technical_filter.py) `get_summary()` 紧凑单行格式，信息密度翻倍
- 🔧 [src/tracker.py](src/tracker.py) 追踪 Markdown 改为表格式、纯文本紧凑对齐

**待办事项：**
- [ ] 网络恢复后 push 本地 commits
- [ ] GitHub Secrets 添加 QQ邮箱 + 微信配置，验证 CI 自动推送
- [ ] Phase 2.3: 聚合器重构 — 多因子打分替换纯关键词匹配
- [ ] 财联社爬虫修复
- [x] UI 重构（CLI/Markdown/Email/Web 四种格式）

### 2026-06-04 (周四) — v2.2

**完成事项：**
- 🚀 **Phase 2.3 完成**：聚合器重构 — 多因子评分替换纯关键词匹配
  - 全新 6 因子评分模型（满分 100）：关键词相关性(0-25) + 情绪信号强度(0-15) + 来源权威性(0-15) + 资金面共振(0-20) + 跨源确认(0-15) + 内容质量(0-10)
  - 关键词三层分级（T1 热门 5分/个、T2 主题 3分/个、T3 政策 2分/个），取代旧版扁平列表
  - 情绪信号强度：复用 confirmation.py 的正/负面信号词典，强度分级（1→4, 2-3→8, 4-5→12, 6+→15）
  - 资金面共振：从 market_data 提取资金流入板块集合，精确匹配+10、模糊匹配+6
  - 跨源确认：共享关键词 ≥2 判断同事件不同源报道，1源+5、2源+10、3源+15
  - 评分分布日志：每轮输出因子均分统计，便于监控和调参
- 🔧 `main.py`：aggregate() 传入 market_data，启用资金面共振因子；移除冗余 import
- 🚀 **Phase 3.1 完成**：新增 [src/database.py](src/database.py) SQLite 推荐数据库
  - 3 表 Schema：reports（日报）→ recommendations（推荐）→ stocks（标的）+ tracking 列
  - Engine + Singleton + Convenience 三件套模式（遵循 confirmation/technical_filter 模式）
  - `save_report()` — 管道中自动持久化（JSON保存后、推送前）
  - `update_tracking()` — 次日追踪数据回写昨日 stocks 行
  - `_import_json_reports()` — 首次运行自动迁移 5 份历史 JSON 报告
  - `get_stats()` — 全量统计：总体胜率、按信心度/板块/确认信号的表现、最佳/最差单票
  - `get_history(days)` — 最近 N 天摘要表
  - `get_report(date)` — 单日完整报告查询
  - CLI 查询工具：`--stats` / `--history N` / `--date YYYY-MM-DD` / `--recent`
  - 零外部依赖（仅 sqlite3 stdlib），数据库故障不阻断主管道
  - 配置：`config.yaml` → `database.enabled` / `path` / `migrate_on_start`
- 🚀 **CI 双轮触发**：[.github/workflows/daily-push.yml] 新增 9:35 补充运行
  - 8:30 盘前预跑 + 9:35 开盘后补充（push2 API 9:30 后就绪）
- 📝 更新 DEVLOG.md 路线图 Phase 2.2/2.3 标记完成

**验证结果：**
- 本地干运行管道全通：采集 61 条 → 多因子评分 → AI 推荐 4 条 → 确认+技术过滤 → 追踪(胜率75%/均收益+6.47%)
- 因子均分（盘前）：source=13.2 quality=4.5 keyword=1.9 sentiment=1.8 market=0.0 cross_source=0.0
- 数据库迁移：5 份历史 JSON → 21 条推荐、32 只标的全部入库
- CLI 查询：`--stats` / `--history` / `--date` / `--recent` 四个命令全部可用

**待办事项：**
- [ ] Phase 3.2: 因子有效性检验 — 指标 vs 实际涨跌的相关性
- [ ] 财联社爬虫修复
- [ ] 雪球爬虫启用（配置 cookie）

---

## 待办池

非紧急事项暂存于此，适时排入具体 Phase：

- [ ] 财联社爬虫修复（API endpoint 已404，需更新）
- [ ] 雪球爬虫启用（需配置 cookie 后测试）
- [ ] 邮件模板根据实际使用反馈迭代
- [ ] 增加 `config.yaml` 校验（启动时检查必填字段）
- [ ] 增加 `--push` 参数合法性校验（拒绝无效通道名）
- [ ] 日志按日期分文件存储（目前全输出到 stdout，CI 环境中不易排查）
- [ ] 采集超时/失败告警（当前静默降级，可能漏掉数据源异常）

---

## 版本历史

| 版本 | 日期 | 关键变更 |
|:---|:---|:---|
| v1.5 | 2026-06-01 | Phase 1.3: akshare增强行情（北向资金+主力趋势+板块排名） |
| v1.4 | 2026-06-01 | Phase 1.2: 次日追踪模块（回顾+胜率）+ README补全 |
| v1.3 | 2026-05-31 | Phase 1.1: 市场实况数据注入 + DEVLOG开发日志 + CLAUDE.md路径索引 |
| v1.2 | 2026-05-31 | BasePusher抽象基类 + 微信推送 + 163邮箱 + 通道选择 |
| v1.1 | 2026-05-31 | 邮件HTML模板升级为现代卡片风 |
| v1.0 | 2026-05-31 | 首次发布：多源采集 + AI分析 + 邮件/CLI/Web推送 |

---

> 维护约定：每次开发会话结束时更新本日志。提交代码时在 commit message 中引用对应的 Phase/任务编号。
