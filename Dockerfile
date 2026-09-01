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

# 安装系统依赖（gcc 给 pymysql 编译用，可移除则更小）
RUN apt-get update && apt-get install -y --no-install-recommends \
        gcc \
        curl \
        tzdata \
    && rm -rf /var/lib/apt/lists/*

# 先装依赖（利用 Docker 层缓存）
COPY requirements.txt .
RUN pip install -r requirements.txt

# 复制项目代码
COPY . .

# 创建运行时目录（数据 + 上传图：文章图/轮播图/自定义背景）
RUN mkdir -p data static/banner static/uploads/backgrounds

# 容器内非 root 运行
RUN useradd -r -u 1000 -g root appuser \
    && chown -R appuser:root /app
USER appuser

EXPOSE 5000

# 健康检查（gunicorn 监听端口）
HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
    CMD curl -fsS http://127.0.0.1:5000/ || exit 1

# 启动命令
CMD ["gunicorn", \
     "-w", "4", \
     "-b", "0.0.0.0:5000", \
     "--timeout", "60", \
     "--access-logfile", "-", \
     "--error-logfile", "-", \
     "wsgi:application"]
