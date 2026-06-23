# 贡献指南

感谢你对 Social Monitor 的关注！

## 如何贡献

### 提 Issue

- **Bug 报告** — 描述问题、复现步骤、环境信息（OS、Python 版本）
- **功能建议** — 说明场景和期望行为
- **问题求助** — 部署/使用中遇到的问题

### 提 Pull Request

1. Fork 本仓库
2. 创建功能分支：`git checkout -b feature/xxx`
3. 提交更改：`git commit -m 'feat: 添加 xxx'`
4. 推送到分支：`git push origin feature/xxx`
5. 提交 Pull Request

### Commit 规范

- `feat:` 新功能
- `fix:` 修复 bug
- `docs:` 文档更新
- `refactor:` 重构
- `chore:` 杂项（CI、依赖更新等）

### 代码风格

- Python 代码保持与现有风格一致（4 空格缩进、snake_case）
- 前端保持 Vue 3 Options API + 原生 CSS 风格
- CI 会自动运行 lint 检查

## 开发环境

```bash
# 安装依赖
python3 install.py --quick

# 启动开发服务器
python3 server.py
# → http://localhost:5408

# 运行采集测试
python3 collector.py --platform douyin --account benxian1
```

## 项目结构说明

- `server.py` — API 服务 + 静态文件托管，项目入口
- `collector.py` — 采集调度，协调各平台采集脚本
- `config.json` + `config.py` — 所有可配置项
- `frontend/` — Vue 3 纯静态前端（无需构建）
- `social-auto-upload/` — 采集引擎（子模块，Playwright 自动化）
