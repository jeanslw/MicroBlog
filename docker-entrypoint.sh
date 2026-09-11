#!/bin/sh
# ============================================================
# 容器入口：修正 bind 挂载目录权限后，以非 root 用户启动主进程。
#
# 背景：compose 把 data/backups/static 等目录以 bind mount 挂入容器，
# 宿主机侧新建目录默认属 root:root，而应用以 uid=1000 的 appuser 运行，
# 会导致 SQLite 建库、图片上传、备份写入因权限失败。
# 容器以 root 启动（默认），在此修正属主后通过 gosu 降权。
# 仅修正顶层目录（非递归），避免静态文件较多时拖慢启动。
# ============================================================
set -e

RUNTIME_DIRS="/app/data /app/backups /app/static/banner /app/static/uploads /app/static/uploads/backgrounds"
for d in $RUNTIME_DIRS; do
    mkdir -p "$d"
    chown appuser:root "$d" 2>/dev/null || true
done

exec gosu appuser "$@"
