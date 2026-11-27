# ============================================================
# Flask 博客系统 Docker 镜像
# 基础镜像:python:3.11-slim(兼顾体积与兼容性)
# 运行方式:gunicorn 4 worker
# ============================================================
FROM python:3.11-slim

# Python 运行时优化；容器保持默认 UTC 时区
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app

# 安装系统依赖(gcc 给 pymysql 编译用;curl 用于健康检查;
# gosu 用于入口脚本从 root 降权到 appuser;
# default-mysql-client 提供 mysqldump/mysql,供管理后台数据库备份与恢复调用,
# 无需依赖宿主机安装客户端)
RUN apt-get update && apt-get install -y --no-install-recommends \
        gcc \
        curl \
        gosu \
        tzdata \
        default-mysql-client \
    && rm -rf /var/lib/apt/lists/*

# 先装依赖(利用 Docker 层缓存)
COPY requirements.txt .
RUN pip install -r requirements.txt

# 复制项目代码
COPY . .

# 创建运行时目录(数据 + 上传图:轮播图/文章图/Logo/头像/背景 + 日志)
RUN mkdir -p data logs uploads/banner uploads/image

# 容器内非 root 运行(入口脚本以 root 修正挂载目录属主后再 gosu 降权)
RUN useradd -r -u 1000 -g root appuser \
    && chown -R appuser:root /app

# 入口脚本:修正 bind 挂载目录权限 -> 降权为 appuser -> 执行 CMD
# sed 去 \r 兼容 Windows 检出时可能带的 CRLF 行尾
COPY docker-entrypoint.sh /usr/local/bin/docker-entrypoint.sh
RUN sed -i 's/\r$//' /usr/local/bin/docker-entrypoint.sh \
    && chmod +x /usr/local/bin/docker-entrypoint.sh
ENTRYPOINT ["/usr/local/bin/docker-entrypoint.sh"]

EXPOSE 5000

# 健康检查:/healthz 同时校验进程与数据库连通性,且豁免 Host 白名单.
# start-period 给到 40s,兼容 MySQL 容器首次初始化较慢的场景.
# 双端口兜底:gunicorn 与 uwsgi HTTP 模式监听 5000;切换 uwsgi 协议模式后
# 5000 变为 uwsgi 二进制协议,curl 改探 uwsgi.ini 恒开的 HTTP 探针口 5001.
HEALTHCHECK --interval=15s --timeout=5s --start-period=40s --retries=5 \
    CMD curl -fsS http://127.0.0.1:5000/healthz || curl -fsS http://127.0.0.1:5001/healthz || exit 1

# 启动命令(切换 uWSGI:安装 uwsgi 后改为 ["uwsgi", "--ini", "uwsgi.ini"],
# 切换步骤见 docs/部署文档.md uWSGI 章节)
CMD ["gunicorn", \
     "-w", "4", \
     "-b", "0.0.0.0:5000", \
     "--timeout", "60", \
     "--access-logfile", "-", \
     "--error-logfile", "-", \
     "wsgi:application"]
