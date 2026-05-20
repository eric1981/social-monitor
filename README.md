# Social Monitor

4 平台 × 12 账号社交媒体监控系统。采集抖音、快手、小红书、视频号的作品数据，生成时间序列快照，前端 Airbnb 风格看板展示。

## 项目结构

```
social-monitor/
├── collector.py           # 采集入口（WSL）
├── server.py              # API + 静态文件服务 :5408
├── schema.sql             # 数据库建表语句
├── monitor.db             # SQLite 数据库（WAL 模式）
├── requirements.txt       # Python 依赖
├── frontend/
│   └── index.html         # Vue 3 单页前端（Airbnb 风格）
└── social-auto-upload/
    └── cookies/           # 各平台 cookie 文件
```

Windows 侧（`C:\Users\NINGMEI\Desktop\social-monitor\`）：
```
win_collector.py            # 抖音采集（Playwright API 直调）
win_kuaishou.py             # 快手采集（Playwright DOM 提取）
win_xiaohongshu.py          # 小红书采集（Playwright DOM 提取）
win_shipinhao.py            # 视频号采集（Playwright API 直调）
win_login.py                # 通用扫码登录
win_relogin.py              # cookie 失效重扫
```

## 启动（WSL / Linux）

```bash
cd ~/social-monitor
pip install -r requirements.txt
python server.py
```

打开 http://localhost:5408 查看前端看板。

## 采集

```bash
# 全量采集所有活跃账号
python collector.py

# 指定平台
python collector.py --platform douyin

# 指定账号
python collector.py --account benxian1

# 预览（不写入数据库）
python collector.py --dry-run
```

## 跨平台支持

### Linux (WSL/Ubuntu)
- ✅ 前端 + API 服务完全支持（`server.py`）
- ⚠️ 采集依赖 Windows 侧 Playwright 脚本
- WSL 内 Playwright 因 EPIPE 崩溃，必须走 `cmd.exe → Windows Playwright` 模式

### macOS
- ❌ **不支持**。核心采集流程硬编码了：
  - `cmd.exe` 调用 Windows 脚本
  - Windows 文件路径（`C:\Users\NINGMEI\...`）
  - Windows 侧 Playwright 依赖
- 前端 + API 服务理论上可在 macOS 运行，但采集功能完全不可用

### 纯 Linux（非 WSL）
- ❌ **不支持**。同上，采集架构依赖 Windows 环境

> 如果要让 social-monitor 跨平台，需要重构 `collector.py`：去掉 `cmd.exe` 调用，改为直接运行 Playwright（Windows 侧脚本需移植为跨平台 Python 脚本），并移除硬编码的 Windows 路径。

## 数据库

```sql
accounts  — UNIQUE(platform, account_name)  昵称、是否活跃
videos    — UNIQUE(platform, aweme_id)       标题、封面、首次发现时间
snapshots — UNIQUE(video_id, collected_at)   播放/点赞/评论/分享/收藏 时间序列
```

## 已知问题

- **视频号定时发布重复**：定时发布和已发布有不同 `objectId`，已在 `win_shipinhao.py` 中通过比较 `createTime` 与当前时间过滤
- **小红书日期格式**：小红书前端显示"定时发布 2026年05月17日 17:24"，`server.py` 会自动标准化为 `2026-05-17 17:24:00` 以保证跨平台排序正确
- **视频号标题**：视频号 API 把"描述"存在 `desc.description`（非 `desc.text`），已在 `win_shipinhao.py` 中修正
