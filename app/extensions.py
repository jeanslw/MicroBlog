import traceback
from app.db import get_db, DictCursor


def get_categories():
    """获取所有栏目 + 已发布文章总数"""
    db = get_db()
    if not db:
        return [], 0
    cur = db.cursor(DictCursor)
    try:
        cur.execute("""
            SELECT c.id, c.cat_name, c.tag_text, c.create_time, COUNT(a.id) AS art_count
            FROM category c
            LEFT JOIN article a ON c.id = a.category_id AND a.status='publish'
            GROUP BY c.id ORDER BY c.id DESC
        """)
        category_data = cur.fetchall()
        cur.execute("SELECT COUNT(id) total FROM article WHERE status='publish'")
        all_total = cur.fetchone()["total"]
        return category_data, all_total
    except Exception:
        print("=====获取分类失败=====")
        traceback.print_exc()
        return [], 0
    finally:
        cur.close()
        db.close()


def get_site_name():
    """获取站点名称"""
    db = get_db()
    if not db:
        return "我的博客"
    try:
        cur = db.cursor(DictCursor)
        cur.execute("SELECT site_name FROM site_config LIMIT 1")
        res = cur.fetchone()
        return res["site_name"] if res else "我的博客"
    except Exception:
        return "我的博客"
    finally:
        try:
            db.close()
        except Exception:
            pass
