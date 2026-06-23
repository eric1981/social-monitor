# Social Monitor — Docker 部署
# 一键运行：docker compose up -d
FROM python:3.13-slim

LABEL org.opencontainers.image.title="Social Monitor"
LABEL org.opencontainers.image.description="跨平台社交媒体监控面板"
LABEL org.opencontainers.image.source="https://github.com/eric1981/social-monitor"

# ── 系统依赖（Playwright Chromium 所需） ──
RUN apt-get update && apt-get install -y --no-install-recommends \
    libnss3 libnspr4 libatk-bridge2.0-0 libatk1.0-0 libcups2 \
    libdrm2 libdbus-1-3 libxkbcommon0 libxcomposite1 libxdamage1 \
    libxfixes3 libxrandr2 libgbm1 libpango-1.0-0 libcairo2 \
    libasound2t64 curl ca-certificates \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# ── Python 依赖 ──
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt playwright

# ── Playwright Chromium（内嵌二维码截图用） ──
RUN playwright install chromium
RUN playwright install-deps chromium

# ── 项目文件 ──
COPY . .

# ── Entrypoint ──
RUN chmod +x /app/docker-entrypoint.sh

# ── 持久化数据卷 ──
VOLUME ["/app/data"]

# ── 环境变量默认值 ──
ENV PYTHONUNBUFFERED=1
ENV SM_DATA_DIR=/app/data
ENV SM_PORT=5408

# ── 健康检查 ──
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD curl -sf http://localhost:${SM_PORT}/api/health || exit 1

EXPOSE 5408

ENTRYPOINT ["/app/docker-entrypoint.sh"]
