#!/bin/bash
# 启动 Social Monitor — 前端 + 后端
# 用法: ./start.sh

echo "=============================="
echo "  Social Monitor 启动"
echo "=============================="

# 1. 启动后端 API 服务（前台，按 Ctrl+C 停止）
echo "[1/1] 启动 API 服务 → http://localhost:5408"
echo "      前端页面: http://localhost:5408"
echo "      按 Ctrl+C 停止"
echo ""

cd "$(dirname "$0")"
.venv/bin/python3 server.py
