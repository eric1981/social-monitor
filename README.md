# Social Monitor

社交媒体账号监控系统。基于 social-auto-upload 的 cookie 机制采集各平台创作者后台数据。

## 支持的平台

| 平台 | 采集方式 | 自动化 |
|------|---------|--------|
| 🎵 抖音 | Playwright + cookie → 创作者后台 API | ✅ 全自动 |
| 🎬 快手 | Playwright + cookie → DOM 提取 | ✅ 全自动 |
| 📕 小红书 | Playwright + cookie → DOM 提取 | ✅ 全自动 |
| 📺 视频号 | Playwright + cookie → post_list API | ✅ 全自动 |

每个平台的采集器都在 Windows 侧独立运行（Playwright + storage_state cookie 文件），不需要手动切换 Chrome 账号。

## 项目结构

```
social-monitor/
├── collector.py              ← 主采集脚本（WSL 侧调度）
├── server.py                 ← 轻量 API 服务（前端 + 后端，:5408）
├── schema.sql                ← 数据库建表 SQL
├── monitor.db                ← SQLite 数据库
├── scheduled_collect.py      ← 定时采集调度（每天6:00，失败每小时重试）
├── login_tencent.py          ← 视频号扫码登录辅助脚本
├── frontend/
│   └── index.html            ← 前端页面（Airbnb 风格）
├── cookies/                  ← cookie 文件（已 gitignore）
├── logs/                     ← 采集日志（已 gitignore）
├── social-auto-upload/       ← 上游项目依赖（完整复制，独立管理）
│   ├── uploader/             ← 各平台上传达器（含 cookie_auth 等函数）
│   ├── cookies/              ← 原始 cookie 文件
│   └── utils/                ← 工具（base_social_media, login_qrcode 等）
└── .venv/                    ← Python 虚拟环境（已 gitignore）
```

### Windows 侧（C:\Users\NINGMEI\Desktop\social-monitor\）

```
social-monitor/
├── win_collector.py          ← 抖音采集器（Playwright）
├── win_kuaishou.py           ← 快手采集器（Playwright + DOM）
├── win_xiaohongshu.py        ← 小红书采集器（Playwright + DOM）
├── win_shipinhao.py          ← 视频号采集器（Playwright + API）
├── social-auto-upload/
│   └── cookies/              ← cookie 文件（WSL 自动同步）
└── tmp/                      ← 采集中间结果（可通过 /mnt/c/ 读取）
```

## 使用方式

```bash
# 采集所有活跃账号
python3 collector.py

# 采集特定平台
python3 collector.py --platform douyin

# 采集特定账号
python3 collector.py --account benxian1

# 启动前端服务
python3 server.py
# → 浏览器打开 http://localhost:5408

# 运行定时采集（供 cron/任务计划调用）
python3 scheduled_collect.py
```

## 定时采集

- **Windows 任务计划**: `SocialMonitor_DailyCollect`，每天 6:00 执行
- **失败重试**: 脚本内部每小时重试，最多 3 次
- **日志**: 每次运行生成 `logs/collect_YYYYMMDD_HHMMSS.log`

## 采集架构

```
cron/任务计划 (每天6:00)
  └─ scheduled_collect.py          ← 调度器，失败重试
       ├─ collector.py --platform douyin
       │    └─ cmd.exe → win_collector.py (Playwright + cookie)
       ├─ collector.py --platform kuaishou
       │    └─ cmd.exe → win_kuaishou.py (Playwright + cookie + DOM)
       ├─ collector.py --platform xiaohongshu
       │    └─ cmd.exe → win_xiaohongshu.py (Playwright + cookie + DOM)
       └─ collector.py --platform shipinhao
            └─ cmd.exe → win_shipinhao.py (Playwright + cookie + API)
```

每个平台的 cookie 文件由 social-auto-upload 的 CLI 扫码登录生成，之后采集全自动，无需人工干预。

## 数据库

- `accounts`: 平台 × 账号（is_active 控制是否采集）
- `videos`: 视频静态信息（一条视频一条记录，aweme_id 去重）
- `snapshots`: 时间序列数据（每次采集追加，按 minute 去重）

## 关键教训

1. **先看现有实现** — social-auto-upload 的 uploader 里已有各平台的 cookie 管理和页面交互逻辑
2. **不要死磕 API** — API 不通时，DOM 提取或拦截网络请求找真实 API 更快
3. **cookie + Playwright 是最稳的模式** — 所有平台统一用 storage_state 管理登录态
4. **先 fallback 再优化** — 小红书 API 406 时，adapter 的 DOM 提取是现成方案
5. **改代码前先 git status** — 确保工作区干净再修改，重大更改建 branch
