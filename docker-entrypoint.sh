#!/bin/sh
# ============================================================
# 容器入口：修正 bind 挂载目录权限 → 准备会话密钥 → 以非 root 用户启动主进程。
#
# 背景：compose 把 data/backups/static 等目录以 bind mount 挂入容器，
# 宿主机侧新建目录默认属 root:root，而应用以 uid=1000 的 appuser 运行，
# 会导致 SQLite 建库、图片上传、备份写入因权限失败。
# 容器以 root 启动（默认），在此修正属主后通过 gosu 降权。
# 仅修正顶层目录（非递归），避免静态文件较多时拖慢启动。
# ============================================================
set -e

RUNTIME_DIRS="/app/data /app/backups /app/logs /app/uploads/banner /app/uploads/image"
for d in $RUNTIME_DIRS; do
    mkdir -p "$d"
    chown appuser:root "$d" 2>/dev/null || true
done

# ── 会话密钥（SECRET_KEY）：未显式提供时自动生成并持久化 ──────────
# compose 的 BLOG_SECRET_KEY 默认值是写在仓库里的公开口令，任何拿到仓库的人
# 都能用它签名出合法 Cookie 冒充管理员（=后台接管）。因此这里把「未设置」和
# 「仍等于公开默认值」两种情况都当作未配置：生成 64 位十六进制随机密钥写入
# BLOG_SECRET_KEY_FILE，并让应用从文件读取（比环境变量更隐蔽：docker inspect、
# /proc/<pid>/environ、进程环境快照里都看不到密钥本身）。
# 文件放在 /app/data 下，随 ./data 卷持久化：容器重建后登录态不失效；
# gunicorn 多 worker 共享同一进程环境，密钥天然一致。
PUBLIC_DEFAULT_KEY="insecure-compose-default-key-CHANGE-ME-0123456789abcdef"

if [ -z "${BLOG_SECRET_KEY:-}" ] || [ "${BLOG_SECRET_KEY:-}" = "$PUBLIC_DEFAULT_KEY" ]; then
    if [ "${BLOG_SECRET_KEY:-}" = "$PUBLIC_DEFAULT_KEY" ]; then
        echo "[entrypoint] 检测到公开默认的 BLOG_SECRET_KEY，已忽略并改用自动生成的随机密钥"
        echo "[entrypoint] public default BLOG_SECRET_KEY detected - ignored; using an auto-generated random key"
    fi
    SECRET_FILE="${BLOG_SECRET_KEY_FILE:-/app/data/.secret_key}"
    if [ ! -s "$SECRET_FILE" ]; then
        mkdir -p "$(dirname "$SECRET_FILE")"
        # 仅在生成密钥时收紧 umask，随后还原：否则应用之后创建的
        # 上传图片/日志/库文件都会继承 077，宿主机侧不便查看
        OLD_UMASK=$(umask)
        umask 077
        python -c "import secrets; print(secrets.token_hex(32))" > "$SECRET_FILE"
        umask "$OLD_UMASK"
        echo "[entrypoint] 已生成随机会话密钥并持久化到 $SECRET_FILE（请勿删除，删除后所有登录态与加密字段失效）"
        echo "[entrypoint] generated a random session key at $SECRET_FILE (do not delete: sessions and encrypted columns depend on it)"
    fi
    chown appuser:root "$SECRET_FILE" 2>/dev/null || true
    chmod 600 "$SECRET_FILE" 2>/dev/null || true
    BLOG_SECRET_KEY_FILE="$SECRET_FILE"
    export BLOG_SECRET_KEY_FILE
    # 置空（而非 unset）并导出：python-dotenv 在 override=False 时会跳过「已存在于
    # 环境」的键，因此即便镜像/挂载里意外混入了含旧密钥的 app.env，也无法覆盖这里
    # 生成的密钥；空值同时让 config.py 落到 BLOG_SECRET_KEY_FILE 分支，密钥本体
    # 始终不出现在环境变量里。
    BLOG_SECRET_KEY=""
    export BLOG_SECRET_KEY
fi

exec gosu appuser "$@"
