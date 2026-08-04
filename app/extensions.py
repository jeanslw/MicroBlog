import logging
import time
from functools import wraps

from flask import session, flash, redirect, url_for, request

from app.db import get_db, DictCursor

log = logging.getLogger(__name__)


def get_client_ip():
    """获取真实客户端 IP（兼容反代）"""
    # 若部署在 Nginx 后并配置了 X-Forwarded-For，可信任首段
    xff = request.headers.get("X-Forwarded-For")
    if xff:
        return xff.split(",")[0].strip()
    return request.remote_addr or "unknown"


def admin_required(f):
    """装饰器：要求管理员登录（基于 admin_id 而非布尔标志）"""
    @wraps(f)
    def decorated(*args, **kwargs):
        if not session.get("admin_id"):
            flash("请先登录管理员账号")
            return redirect(url_for("admin.login"))
        return f(*args, **kwargs)
    return decorated


def get_categories():
    """获取所有栏目 + 已发布文章总数"""
    try:
        db = get_db()
        cur = db.cursor(DictCursor)
        cur.execute("""
            SELECT c.id, c.cat_name, c.tag_text, c.create_time, COUNT(a.id) AS art_count
            FROM category c
            LEFT JOIN article a ON c.id = a.category_id AND a.status='publish'
            GROUP BY c.id ORDER BY c.id DESC
        """)
        category_data = cur.fetchall()
        cur.execute("SELECT COUNT(id) total FROM article WHERE status='publish'")
        all_total = cur.fetchone()["total"]
        cur.close()
        return category_data, all_total
    except Exception:
        log.error("获取分类失败", exc_info=True)
        return [], 0


def get_site_name():
    """获取站点名称"""
    try:
        db = get_db()
        cur = db.cursor(DictCursor)
        cur.execute("SELECT site_name FROM site_config LIMIT 1")
        res = cur.fetchone()
        cur.close()
        return res["site_name"] if res else "我的博客"
    except Exception:
        return "我的博客"


# ── 登录防爆破（基于 IP + 用户名，跨 session 不可绕过） ────────
_login_fail_cache = {}  # key: (ip, username) -> [fail_count, lock_until_ts]


def check_login_lock(ip, username):
    """检查登录是否被锁定，返回 (locked, remain_seconds)"""
    key = (ip, username)
    rec = _login_fail_cache.get(key)
    if not rec:
        return False, 0
    fail_count, lock_until = rec
    if fail_count >= 5 and time.time() < lock_until:
        return True, int(lock_until - time.time())
    # 锁定期过，自动重置
    if fail_count >= 5 and time.time() >= lock_until:
        _login_fail_cache.pop(key, None)
    return False, 0


def record_login_fail(ip, username, lock_seconds=300):
    """记录一次登录失败，达阈值则锁定"""
    key = (ip, username)
    rec = _login_fail_cache.get(key, [0, 0])
    rec[0] += 1
    if rec[0] >= 5:
        rec[1] = time.time() + lock_seconds
    _login_fail_cache[key] = rec
    return rec[0]


def clear_login_fail(ip, username):
    """登录成功后清除失败记录"""
    _login_fail_cache.pop((ip, username), None)
