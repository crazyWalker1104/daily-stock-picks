# 📊 每日A股智能推荐系统

AI驱动的A股短线投资参考，每天自动抓取财经新闻和券商研报，通过DeepSeek API综合研判，输出5条精简推荐。

## 🎯 核心功能

- 🤖 **AI综合分析**：DeepSeek大模型研判市场热点，识别板块轮动
- 📈 **市场实况注入**：实时指数/资金流向/成交额结构化为AI上下文
- 📰 **多源采集**：东方财富（研报+资金流）、新浪财经（要闻）、财联社、雪球（可插拔）
- 📧 **多通道推送**：163邮箱 / QQ邮箱 / 微信(Server酱) / CLI / Web — 自由选择
- 📊 **次日追踪**：自动对比昨日推荐 vs 今日行情，胜率+均收益统计
- 🌐 **网页归档**：GitHub Pages自动渲染，支持历史回顾
- ⏰ **全自动**：GitHub Actions交易日8:30触发，无需服务器

## 🚀 快速开始

### 1. 环境要求
- Python 3.11+
- Git

### 2. 安装
```bash
cd 'Daily Stock Picks'
pip install -r requirements.txt
```

### 3. 配置
```bash
# 复制配置模板
cp .env.example .env
cp config/config.example.yaml config/config.yaml

# 编辑 .env，填入你的API Key
# 必填：DEEPSEEK_API_KEY（DeepSeek API密钥）
# 邮件推送：SMTP_USER, SMTP_PASSWORD, RECIPIENT_EMAIL
```

### 4. 本地运行
```bash
# 本地测试（仅采集+CLI输出，不推送）
python -m src.main --local

# 指定推送通道（逗号分隔，可选 email,wechat,cli,web）
python -m src.main --push email,cli

# 仅测试爬虫
python -m src.main --scrape-only

# 干运行（完整流程但不推送）
python -m src.main --dry-run

# 指定日期
python -m src.main --date 2026-06-01
```

## 📁 项目结构

```
├── src/
│   ├── scrapers/        # 信息源爬虫（可插拔）
│   │   ├── base.py      # 爬虫基类
│   │   ├── cls.py       # 财联社
│   │   ├── eastmoney.py # 东方财富（研报+资金流）
│   │   ├── sina.py      # 新浪财经
│   │   └── xueqiu.py    # 雪球
│   ├── aggregator.py    # 聚合去重排序
│   ├── market_data.py   # 市场实况采集（指数/资金流）
│   ├── tracker.py       # 次日推荐追踪（胜率统计）
│   ├── ai_analyzer.py   # AI分析（DeepSeek API）
│   ├── formatter.py     # 格式化输出（Markdown/纯文本/HTML邮件/HTML网页）
│   ├── pusher.py        # 推送分发（邮箱/微信/CLI/Web四通道）
│   └── main.py          # 主入口
├── config/              # 配置文件
├── docs/                # GitHub Pages 网页
├── output/              # 每日报告JSON
├── data/                # 原始采集数据
├── DEVLOG.md            # 开发日志 + 路线图
├── CLAUDE.md            # AI助手上下文 + 文件索引
├── .github/workflows/   # GitHub Actions 调度
└── requirements.txt
```

## 🔧 GitHub Actions 部署

1. 在仓库 Settings → Secrets and variables → Actions 中添加以下Secrets：

| Secret | 说明 |
|--------|------|
| `DEEPSEEK_API_KEY` | DeepSeek API密钥（必填） |
| `DEEPSEEK_BASE_URL` | DeepSeek API地址（默认 https://api.deepseek.com） |
| `SMTP_HOST` | SMTP服务器（QQ: smtp.qq.com / 163: smtp.163.com） |
| `SMTP_PORT` | SMTP端口（QQ: 587 / 163: 465） |
| `SMTP_USER` | 发件邮箱地址 |
| `SMTP_PASSWORD` | 邮箱SMTP授权码（非登录密码） |
| `RECIPIENT_EMAIL` | 接收推送的邮箱 |
| `WECHAT_SENDKEY` | Server酱 SendKey（可选，微信推送用） |

2. 启用 GitHub Pages：
   - Settings → Pages → Source: `main` branch, `/docs` folder
   - 访问 `https://<你的用户名>.github.io/<仓库名>/`

3. 每日自动运行：北京时间周一至周五 8:30
   - 也可手动触发：Actions → 每日A股推荐推送 → Run workflow

## 📧 邮箱推送配置

### QQ邮箱 (587端口/STARTTLS)
1. 登录QQ邮箱 → 设置 → 账户 → POP3/SMTP服务
2. 开启SMTP服务，获取**授权码**
3. `.env` 配置：`SMTP_HOST=smtp.qq.com` `SMTP_PORT=587`

### 163邮箱 (465端口/SSL)
1. 登录163邮箱 → 设置 → POP3/SMTP/IMAP
2. 开启SMTP服务，获取**授权码**
3. `.env` 配置：`SMTP_HOST=smtp.163.com` `SMTP_PORT=465`

## 📱 微信推送配置 (Server酱)

1. 前往 https://sct.ftqq.com/ 登录获取 **SendKey**
2. 微信关注「方糖」公众号
3. `.env` 配置：`WECHAT_SENDKEY=你的SendKey`
4. 运行时指定：`python -m src.main --push wechat`

## ⚠️ 重要免责声明

> **本系统仅为AI技术实验项目，绝非投资建议工具。**

1. **不构成投资建议**：所有推荐由AI模型自动生成，基于公开信息源，不代表任何投资建议、理财推荐或买卖指导。请勿据此进行任何交易决策。
2. **不对收益负责**：股市有风险，投资需谨慎。AI分析可能包含错误、幻觉或过时信息，据此操作导致的任何亏损与项目作者无关。
3. **仅供学习参考**：本项目的目的是展示AI在金融信息处理领域的应用，仅适用于学习、研究和技术交流场景。
4. **独立判断**：任何投资决策应由您基于独立研究、风险承受能力并与持牌投资顾问咨询后作出。

> ⚠️ **强烈建议不要将本系统的输出用于实际投资操作。入市有风险，投资须谨慎。**

## 📝 License

MIT
