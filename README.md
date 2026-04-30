# Social Monitor

社交媒体账号监控系统。基于 social-auto-upload 的 cookie 机制采集各平台创作者后台数据。

## 项目结构

```
social-monitor/
├── collector.py              ← 主采集脚本
├── server.py                 ← 轻量 API 服务（前端 + 后端）
├── schema.sql                ← 数据库建表 SQL
├── monitor.db                ← SQLite 数据库
├── cookies/                  ← cookie 文件（同步自 social-auto-upload）
├── frontend/
│   └── index.html            ← 前端页面（Airbnb 风格）
├── social-auto-upload/       ← 上游项目依赖
│   ├── uploader/             ← 各平台上传达器
│   ├── cookies/              ← 原始 cookie 文件
│   └── utils/                ← 工具（base_social_media, login_qrcode 等）
└── .venv/                    ← Python 虚拟环境
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

## 采集机制

抖音采集走混合方案：
1. WSL 侧的 collector.py 同步 cookie 到 Windows 桌面
2. 调用 cmd.exe 启动 Windows 侧的 win_collector.py
3. Windows 侧用 Playwright + cookie 直接调创作者后台 API（支持游标翻页）
4. 结果写入临时 JSON 文件，WSL 读取后入库

## 数据库

- accounts: 平台 × 账号（支持 is_active 控制）
- videos: 视频静态信息（一条视频一条记录）
- snapshots: 时间序列数据（每次采集追加，按 minute 去重）
