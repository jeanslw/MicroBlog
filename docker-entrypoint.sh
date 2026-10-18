#!/bin/sh
# 容器入口：修正 bind 挂载目录权限 → 准备会话密钥 → 以非 root 用户启动主进程。
set -e

RUNTIME_DIRS="/app/data /app/backups /app/logs /app/uploads/banner /app/uploads/image"
for d in $RUNTIME_DIRS; do
    mkdir -p "$d"
    chown appuser:root "$d" 2>/dev/null || true
done

PUBLIC_DEFAULT_KEY="insecure-compose-default-key-CHANGE-ME-0123456789abcdef"

if [ -z "${BLOG_SECRET_KEY:-}" ] || [ "${BLOG_SECRET_KEY:-}" = "$PUBLIC_DEFAULT_KEY" ]; then
    if [ "${BLOG_SECRET_KEY:-}" = "$PUBLIC_DEFAULT_KEY" ]; then
        echo "[entrypoint] 检测到公开默认的 BLOG_SECRET_KEY，已忽略并改用自动生成的随机密钥"
        echo "[entrypoint] public default BLOG_SECRET_KEY detected - ignored; using an auto-generated random key"
    fi
    SECRET_FILE="${BLOG_SECRET_KEY_FILE:-/app/data/.secret_key}"
    if [ ! -s "$SECRET_FILE" ]; then
        mkdir -p "$(dirname "$SECRET_FILE")"
        # 仅生成密钥时收紧 umask，随后还原
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
    # 置空并导出：使 config.py 落到 BLOG_SECRET_KEY_FILE 分支，密钥本体不进入环境变量
    BLOG_SECRET_KEY=""
    export BLOG_SECRET_KEY
fi

exec gosu appuser "$@"
