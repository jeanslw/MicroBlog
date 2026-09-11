# ============================================================
# Flask 博客系统 Docker 镜像
# 基础镜像：python:3.11-slim（兼顾体积与兼容性）
# 运行方式：gunicorn 4 worker
# ============================================================
FROM python:3.11-slim

# Python 运行时优化 + 时区（避免时间差 8 小时）
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    TZ=Asia/Shanghai

WORKDIR /app

# 安装系统依赖（gcc 给 pymysql 编译用；curl 用于健康检查；
# gosu 用于入口脚本从 root 降权到 appuser）
RUN apt-get update && apt-get install -y --no-install-recommends \
        gcc \
        curl \
        gosu \
        tzdata \
    && rm -rf /var/lib/apt/lists/*

# 先装依赖（利用 Docker 层缓存）
COPY requirements.txt .
RUN pip install -r requirements.txt

# 复制项目代码
COPY . .

# 创建运行时目录（数据 + 上传图：文章图/轮播图/自定义背景）
RUN mkdir -p data static/banner static/uploads/backgrounds

# 容器内非 root 运行（入口脚本以 root 修正挂载目录属主后再 gosu 降权）
RUN useradd -r -u 1000 -g root appuser \
    && chown -R appuser:root /app

# 入口脚本：修正 bind 挂载目录权限 → 降权为 appuser → 执行 CMD
# sed 去 \r 兼容 Windows 检出时可能带的 CRLF 行尾
COPY docker-entrypoint.sh /usr/local/bin/docker-entrypoint.sh
RUN sed -i 's/\r$//' /usr/local/bin/docker-entrypoint.sh \
    && chmod +x /usr/local/bin/docker-entrypoint.sh
ENTRYPOINT ["/usr/local/bin/docker-entrypoint.sh"]

EXPOSE 5000

# 健康检查：/healthz 同时校验进程与数据库连通性，且豁免 Host 白名单。
# start-period 给到 40s，兼容 MySQL 容器首次初始化较慢的场景。
HEALTHCHECK --interval=15s --timeout=5s --start-period=40s --retries=5 \
    CMD curl -fsS http://127.0.0.1:5000/healthz || exit 1

# 启动命令
CMD ["gunicorn", \
     "-w", "4", \
     "-b", "0.0.0.0:5000", \
     "--timeout", "60", \
     "--access-logfile", "-", \
     "--error-logfile", "-", \
     "wsgi:application"]
