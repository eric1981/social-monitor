#!/bin/bash
# Social Monitor — 启动脚本
# 用法: ./start.sh

cd "$(dirname "$0")"

# Python 检测
PYTHON=""
for p in python3 .venv/bin/python3 python; do
    if command -v $p &>/dev/null; then PYTHON=$p; break; fi
done
if [ -z "$PYTHON" ]; then echo "ERROR: Python3 not found"; exit 1; fi

echo "=============================="
echo "  Social Monitor 启动"
echo "  $PYTHON server.py → :5408"
echo "=============================="
echo ""

exec $PYTHON server.py
