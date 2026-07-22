import traceback
from functools import wraps
from flask import session, flash, redirect, url_for
from app.db import get_db, DictCursor


def admin_required(f):
    """装饰器：要求管理员登录"""
    @wraps(f)
    def decorated(*args, **kwargs):
        if not session.get("is_admin"):
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
        print("=====获取分类失败=====")
        traceback.print_exc()
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
