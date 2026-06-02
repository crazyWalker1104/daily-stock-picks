# 开发日志 · Daily Stock Picks

> 最后更新：2026-05-31 | 当前阶段：Phase 1 — 基础夯实

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
| 2.1 | 资金流向×新闻情绪双重确认引擎 | ⏳ | P0 | Phase 1 |
| 2.2 | 推荐后处理：技术面过滤（涨幅/量能/均线） | ⏳ | P0 | 1.3 |
| 2.3 | 聚合器重构：多因子打分替换纯关键词匹配 | ⏳ | P1 | 2.1 |

### Phase 3：回测与数据沉淀 `计划 2026-06-15 ~ 2026-06-21`

目标：积累数据，量化评估 AI 推荐质量。

| # | 任务 | 状态 | 优先级 | 依赖 |
|:---|:---|:---|:---|:---|
| 3.1 | SQLite 推荐数据库 + 历史查询 | ⏳ | P0 | Phase 2 |
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

### 2026-06-02 (周二) — v1.5.1

**完成事项：**
- 🐛 **修复 GitHub Actions 交易日检查双重 Bug（根因：CI从未真正运行过）**
  - Bug 1 (类型不匹配): `today in recent['trade_date'].values` — str vs numpy.datetime64 永远返回 False
  - Bug 2 (大小写): Python `print(f"{True}")` → `"True"`（大写），GHA 条件检查小写 `'true'`
  - 讽刺的是：之前能"运行"是因为 akshare 未安装时抛异常进了 except 分支（硬编码 `true`）
- 🐛 **修复 market_data.py push2 网络问题**
  - `push2.eastmoney.com`（IP 61.129.129.196）从当前网络环境完全不通
  - 指数行情改用 **Sina API** (`hq.sinajs.cn`) — 稳定、无频率限制、三大指数全覆盖
- 🔧 新增 `permissions.contents: write` — 修复 git push 权限问题

**待办事项：**
- [ ] 等待明日(6/3 周三)8:30 自动触发验证
- [ ] 板块资金流/成交额需要替代数据源（push2 被墙）
- [ ] 追踪模块个股行情（也依赖 push2）需要替代方案
- [ ] 财联社爬虫修复

---

### 模板：YYYY-MM-DD (周X) — vX.X

**完成事项：**
- 

**遇到的问题：**
- 

**待办事项：**
- [ ] 
- [ ] 

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
