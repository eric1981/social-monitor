<p align="center">
  <img src="frontend/social-monitor-logo.svg" alt="Social Monitor" width="80" height="80">
</p>

<h1 align="center">Social Monitor</h1>

<p align="center">
  四平台社交媒体数据监控 · 抖音 · 快手 · 小红书 · 视频号
</p>

<p align="center">
  <img src="https://img.shields.io/badge/python-3.8%2B-blue" alt="Python">
  <img src="https://img.shields.io/badge/docker-%E2%9C%93-2496ED" alt="Docker">
  <img src="https://img.shields.io/badge/license-MIT-green" alt="License">
  <img src="https://img.shields.io/badge/platform-WSL%20%7C%20Linux%20%7C%20macOS%20%7C%20Docker-lightgrey" alt="Platform">
  <a href="https://github.com/eric1981/social-monitor/actions"><img src="https://github.com/eric1981/social-monitor/actions/workflows/ci.yml/badge.svg" alt="CI"></a>
</p>

---

## 这是什么

**Social Monitor** 是一个轻量级的社交媒体数据监控系统。自动采集你在抖音、快手、小红书、视频号上的视频播放/点赞/评论数据，生成时间序列快照，通过 Airbnb 风格的 Web 看板直观展示。

> 3 句话：**看你的社交媒体数据在涨还是跌** · **一个页面看所有平台** · **开箱即用，一条命令启动**

## 预览

<!-- TODO: 截图待 T5 内嵌二维码功能上线后补充 -->
<!-- 首页看板截图 -->
<!-- 账号详情 + 增长曲线截图 -->
<!-- 扫码登录流程 GIF -->

| 首页看板 | 账号详情 |
|:---:|:---:|
| ![首页](docs/screenshots/dashboard.png) | ![详情](docs/screenshots/account.png) |

| 账号对比 | 系统配置 |
|:---:|:---:|
| ![对比](docs/screenshots/accounts.png) | ![配置](docs/screenshots/settings.png) |

> 💡 截图占位 — 运行 `python3 server.py` 后访问 `http://localhost:5408` 即可看到完整界面。

## 功能

- **📊 自动采集** — 每日 06:00 cron 定时采集，失败自动重试
- **📱 四平台覆盖** — 抖音 / 快手 / 小红书 / 视频号，统一数据模型
- **📈 趋势分析** — 单视频播放增长折线图 + 账号级日聚合趋势
- **🩺 健康监控** — Cookie 状态 + 数据断档检测，首页一目了然
- **🔺 涨跌标识** — 每张卡片显示今日播放增量 ↑↓
- **🔀 跨平台对比** — 同一账号在多个平台的粉丝/播放横向对比
- **📥 数据导出** — 账号 CSV / 视频 CSV 一键下载
- **⚡ 快捷筛选** — 3天 / 7天 / 30天 日期按钮，排序可切换
- **🔑 扫码登录** — 支持各平台二维码扫码登录，Cookie 自动管理
- **🔔 异常通知** — Cookie 过期、数据断档自动告警

## 快速开始

### Docker（推荐 — 零配置）

```bash
# 1. 克隆
git clone https://github.com/eric1981/social-monitor.git
cd social-monitor

# 2. 一键启动
docker compose up -d

# 3. 浏览器打开
# → http://localhost:5408
```

> **数据持久化**：数据库、Cookie、日志保存在 Docker 卷 `social-monitor-data` 中，容器重启/重建不丢失。

#### 自定义端口

```bash
# 创建 .env 文件
cp .env.example .env
# 编辑 SM_PORT=8080
docker compose up -d
```

### 本地安装

```bash
# 1. 安装
python3 install.py

# 2. 启动
python3 server.py
# → 浏览器打开 http://localhost:5408

# 3. 首次采集
python3 collector.py
```

### 系统要求

- Python 3.8+
- 浏览器（Playwright 采集用）
- WSL / Linux / macOS（Windows 通过 WSL 支持）

## 页面

| 页面 | 路径 | 说明 |
|:---|:---|:---|
| 首页看板 | `/` | 健康面板 + 统计 + 视频卡片网格 |
| 账号列表 | `/accounts.html` | 跨平台对比 + 账号卡片 |
| 账号详情 | `/account.html?id=X` | 增长曲线 + 分平台视频 + Cookie 状态 |
| 系统配置 | `/settings.html` | Web 界面管理所有配置项 |

## 采集命令

```bash
python3 collector.py                    # 全量采集
python3 collector.py --platform douyin  # 指定平台
python3 collector.py --account benxian1 # 指定账号
python3 collector.py --stats-only       # 仅采集账号统计
```

## 定时任务

```
0 6 * * *    collector.py    # 每日采集
0 3 * * 0    vacuum_db.py    # 每周 DB 清理
```

## 技术栈

| 层 | 技术 |
|:---|:---|
| 后端 | Python 3 · http.server · sqlite3 |
| 前端 | Vue 3 · Chart.js · 原生 CSS (Airbnb 风格) |
| 采集 | Playwright (浏览器自动化) |
| 部署 | Docker · docker-compose · WSL / Linux · systemd / cron |

## 项目结构

```
social-monitor/
├── server.py              # API + 静态文件服务 (:5408)
├── collector.py           # 采集入口（跨平台）
├── config.json            # 系统配置文件
├── config.py              # 配置加载模块
├── schema.sql             # 数据库建表语句
├── install.py             # 跨平台安装脚本
├── start.sh               # 启动脚本
├── vacuum_db.py           # DB 维护（清理旧快照）
├── scheduled_collect.py   # 定时采集调度
├── Dockerfile             # Docker 镜像
├── docker-compose.yml     # Docker 一键部署
├── docker-entrypoint.sh   # 容器入口脚本
├── .env.example           # 环境变量模板
├── frontend/
│   ├── index.html         # 首页（Vue 3 + Chart.js）
│   ├── accounts.html      # 账号列表页
│   ├── account.html       # 账号详情页
│   ├── settings.html      # 系统配置页
│   └── *.png              # 平台图标
├── logs/                  # 采集日志
└── social-auto-upload/    # 采集引擎（子模块）
```

## Roadmap

- [x] 四平台自动采集 + 定时调度
- [x] Web 看板（趋势图、卡片网格、跨平台对比）
- [x] Cookie 健康监控 + 异常通知
- [ ] ~~扫码登录~~ → ✅ 已上线
- [ ] Docker 一键部署 → ✅ 已上线
- [ ] 关键词监控 + 评论预警
- [ ] 数据导出增强（Excel + PDF 报表）
- [ ] 多用户支持

## 贡献

欢迎提 Issue 和 PR！请先阅读：

- [CONTRIBUTING.md](CONTRIBUTING.md) — 贡献流程
- [CODE_OF_CONDUCT.md](CODE_OF_CONDUCT.md) — 行为准则

## License

MIT © Eric — 详见 [LICENSE](LICENSE)
