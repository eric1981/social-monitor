# Social Monitor

四平台社交媒体数据监控系统。抖音 · 快手 · 小红书 · 视频号，12 个账号，自动采集视频播放/点赞/评论数据，生成时间序列快照，Airbnb 风格 Web 看板。

## 功能

- **自动采集**：每日 06:00 cron 自动采集，失败自动重试 1 次
- **多平台**：抖音 / 快手 / 小红书 / 视频号，统一数据模型
- **趋势分析**：单视频播放增长折线图 + 账号级日聚合趋势
- **健康监控**：Cookie 状态 + 数据断档检测，首页一目了然
- **涨跌标识**：每张卡片显示今日播放增量 ↑↓
- **跨平台对比**：同一账号在多个平台的粉丝/播放横向对比
- **数据导出**：账号 CSV / 视频 CSV 一键下载
- **快捷筛选**：3天 / 7天 / 30天 日期按钮，排序可切换

## 页面

| 页面 | 路径 | 说明 |
|------|------|------|
| 首页看板 | `/` | 健康面板 + 统计 + 视频卡片网格 |
| 账号列表 | `/accounts.html` | 跨平台对比 + 账号卡片 |
| 账号详情 | `/account.html?id=X` | 增长曲线 + 分平台视频 + Cookie 状态 |
| 系统配置 | `/settings.html` | Web 界面管理所有配置项 |

## 配置

所有硬编码已提取到 `config.json`，由 `config.py` 模块统一加载。Web 端 `/settings.html` 可直接编辑。

| 模块 | 可配置项 |
|------|----------|
| 服务 | 监听端口 |
| Windows 集成 | 项目路径、WSL 挂载点、各平台脚本名 |
| 采集 | Cookie 过期阈值、超时、重试间隔 |
| 定时调度 | 最大重试、重试间隔、采集平台列表 |
| 数据清理 | 快照保留天数 |
| 图片代理 | Referer、UA、缓存时长、允许域名白名单 |

## 项目结构

```
social-monitor/
├── collector.py           # 采集入口（WSL，支持自动重试）
├── server.py              # API + 静态文件服务 :5408
├── config.json            # 系统配置文件
├── config.py              # 配置加载模块
├── schema.sql             # 数据库建表语句（含 cover_url）
├── vacuum_db.py           # DB 维护（每周清理旧快照）
├── scheduled_collect.py   # 定时采集调度（cron 触发）
├── start.sh               # 启动脚本
├── frontend/
│   ├── index.html         # 首页（Vue 3 + Chart.js）
│   ├── accounts.html      # 账号列表页
│   ├── account.html       # 账号详情页
│   ├── settings.html      # 系统配置页
│   └── *.png              # 平台图标
├── logs/                  # 采集日志
└── social-auto-upload/
    └── cookies/           # 各平台 cookie 文件
```

## 启动

```bash
cd ~/social-monitor
./start.sh
# → http://localhost:5408
```

## 采集

```bash
python3 collector.py                    # 全量采集
python3 collector.py --platform douyin  # 指定平台
python3 collector.py --account benxian1 # 指定账号
python3 collector.py --stats-only       # 仅采集账号统计
```

## Cron

```
0 6 * * *    collector.py    # 每日采集
0 3 * * 0    vacuum_db.py    # 每周 DB 清理
```

## 已知限制

- 采集依赖 Windows 侧 Playwright 脚本（WSL 内 Playwright 因 EPIPE 崩溃）
- 快手封面图 CDN URL 有时效性，过期后显示占位符
- 小红书 cookie 不易失效，但数据可能因反爬静默断档
