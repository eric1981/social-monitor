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
├── monitor.db                ← SQLite 数据库（WAL 模式）
├── collect_status.json       ← 采集进度状态（前端轮询）
├── frontend/
│   └── index.html            ← 前端页面（Airbnb 风格，Vue 3 CDN）
├── social-auto-upload/       ← 上游项目依赖（完整复制，独立管理）
│   ├── uploader/             ← 各平台上传达器（含 cookie_auth 等函数）
│   ├── cookies/              ← cookie 文件（gitignored）
│   └── utils/                ← 工具（base_social_media, login_qrcode 等）
├── cookies/                  ← cookie 文件副本（gitignored，待清理）
└── .venv/                    ← Python 虚拟环境（gitignored）
```

### Windows 侧（C:\Users\NINGMEI\Desktop\social-monitor\）

```
social-monitor/
├── win_collector.py          ← 抖音采集器（Playwright + API fetch + 游标翻页）
├── win_kuaishou.py           ← 快手采集器（Playwright + DOM，支持流量助推行）
├── win_xiaohongshu.py        ← 小红书采集器（Playwright + DOM + text fallback）
├── win_shipinhao.py          ← 视频号采集器（Playwright + post_list API + 翻页）
├── login_tencent_win.py      ← 视频号扫码登录脚本
├── social-auto-upload/
│   └── cookies/              ← cookie 文件
│       ├── douyin_*.json     ← 抖音 cookie
│       ├── kuaishou_*.json   ← 快手 cookie
│       ├── xiaohongshu_*.json← 小红书 cookie
│       └── tencent_uploader/ ← 视频号 cookie（sph1, sph2, sph3）
└── tmp/                      ← 采集中间结果 JSON
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
```

### 前端功能

- **抓取** — 一键全平台采集，深色日志面板实时显示进度
- **刷新** — 手动刷新数据
- **新增账号 / 重新扫码** — 支持选已有账号重新扫码登录
- **日期筛选** — 按发布时间范围过滤
- **排序** — 播放量/点赞数/评论数/发布时间
- **账号筛选** — 按账号过滤
- **封面图** — 卡片显示视频封面，整张卡片可点击跳转原文
- **自动刷新** — 30秒/1分/5分自动刷新
- **昨日播放** — 统计昨日新增播放量，与筛选条件联动

## 采集架构

```
前端点"抓取" / 命令行执行 collector.py
  │
  ├─ 抖音：cmd.exe → win_collector.py (Playwright + cookie → creator API)
  │    └─ 翻页：游标模式（max_cursor），非 page_num
  │
  ├─ 快手：cmd.exe → win_kuaishou.py (Playwright + cookie → DOM 提取)
  │    └─ 注意：获"流量助推"的视频多一行 DOM，采集用倒序查找 stats row
  │
  ├─ 小红书：cmd.exe → win_xiaohongshu.py (Playwright + cookie → DOM 提取)
  │    └─ API 有签名保护(406)，不能用 fetch，只能用 DOM
  │
  └─ 视频号：cmd.exe → win_shipinhao.py (Playwright + cookie → post_list API)
       └─ wujie 微前端沙箱，API 路径 /micro/content/cgi-bin/mmfinderassistant-bin/post/post_list
```

## 数据库

- `accounts`: 平台 × 账号（is_active 控制是否采集，UNIQUE(platform, account_name)）
- `videos`: 视频静态信息（aweme_id 去重，含 cover_url 封面图）
- `snapshots`: 时间序列数据（每次采集追加，UNIQUE(video_id, collected_at) 按分钟去重）

关键设计：
- **每次采集都更新 cover_url** — 刷新 CDN 签名，解决旧封面 403
- **昵称变化时更新** — 采集到不同昵称自动同步，而非仅在首次填写
- **昨日播放量** — 昨天最后一次快照 - 前天最后一次快照

## 常见陷阱

1. **快手 DOM 行数不稳定** — "流量助推"视频多一行，用倒序查找 stats row，不要用固定 index
2. **视频号 cookie 过期频繁** — 几天到一周就会过期，需重新扫码。页面跳转到 login.html 时 API 返回空数据
3. **视频号 cookie 只在 Windows 侧** — tencent_uploader 目录在 WSL 侧始终为空，不要依赖 WSL→Windows 的 cookie 同步
4. **WSL Playwright EPIPE** — WSL 下 Playwright 约 3 分钟 crash，所有采集用 Windows 原生 Playwright
5. **GBK 编码崩溃** — Windows Python 3.14 的 print 遇到中文字符可能崩溃。所有采集脚本先把 JSON 写入文件，再做调试输出
6. **CDN 签名过期** — 快手封面 URL 带时间戳签名，旧数据会 403。每次采集更新 cover_url 解决
7. **小红书 API 406** — 有 X-s 签名保护，不要死磕，用 DOM 提取

## 移植到纯 Linux/macOS

把所有采集脚本从 Windows 移到本机 Playwright 即可。具体参考 skill `social-monitor-collection` 的移植说明。
