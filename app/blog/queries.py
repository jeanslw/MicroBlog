import re
import traceback
from math import ceil
from config import PAGE_SIZE
from app.db import get_db, DictCursor


def strip_html(raw_html):
    """去除 HTML 标签，提取纯文本摘要"""
    rule = re.compile('<.*?>')
    text = re.sub(rule, '', raw_html)
    if len(text) > 220:
        return text[:220] + "..."
    return text


def get_article_list(offset, limit, cid=None):
    """获取文章列表（分页 + 可选栏目筛选）"""
    db = get_db()
    if not db:
        return [], 1
    cur = db.cursor(DictCursor)
    try:
        if cid:
            cur.execute("""
                SELECT a.*, COUNT(c.id) comment_num
                FROM article a
                LEFT JOIN comment c ON a.id = c.article_id
                WHERE a.status='publish' AND a.category_id=%s
                GROUP BY a.id ORDER BY a.create_time DESC LIMIT %s,%s
            """, (cid, offset, limit))
            article_data = cur.fetchall()
            cur.execute("SELECT COUNT(id) total FROM article WHERE status='publish' AND category_id=%s", (cid,))
        else:
            cur.execute("""
                SELECT a.*, COUNT(c.id) comment_num
                FROM article a
                LEFT JOIN comment c ON a.id = c.article_id
                WHERE a.status='publish'
                GROUP BY a.id ORDER BY a.create_time DESC LIMIT %s,%s
            """, (offset, limit))
            article_data = cur.fetchall()
            cur.execute("SELECT COUNT(id) total FROM article WHERE status='publish'")
        total = cur.fetchone()["total"]
        total_page = ceil(total / PAGE_SIZE)
        for art in article_data:
            art["brief"] = strip_html(art["content"])
            sub_cur = db.cursor(DictCursor)
            sub_cur.execute("SELECT * FROM comment WHERE article_id=%s ORDER BY create_time", (art["id"],))
            art["comment_list"] = sub_cur.fetchall()
            for com in art["comment_list"]:
                sub_cur2 = db.cursor(DictCursor)
                sub_cur2.execute("SELECT * FROM reply WHERE comment_id=%s ORDER BY create_time", (com["id"],))
                com["reply_list"] = sub_cur2.fetchall()
                sub_cur2.close()
            sub_cur.close()
        return article_data, total_page
    except Exception:
        print("=====获取文章列表失败=====")
        traceback.print_exc()
        return [], 1
    finally:
        cur.close()
        db.close()


def get_article_detail(aid):
    """获取文章详情 + 评论 + 回复"""
    db = get_db()
    if not db:
        return None, []
    cur = db.cursor(DictCursor)
    cur.execute("SELECT * FROM article WHERE id=%s", (aid,))
    article = cur.fetchone()
    if not article:
        cur.close()
        db.close()
        return None, []
    cur.execute("SELECT * FROM comment WHERE article_id=%s ORDER BY create_time", (aid,))
    comments = cur.fetchall()
    for com in comments:
        sub_cur = db.cursor(DictCursor)
        sub_cur.execute("SELECT * FROM reply WHERE comment_id=%s ORDER BY create_time", (com["id"],))
        com["reply_list"] = sub_cur.fetchall()
        sub_cur.close()
    cur.close()
    db.close()
    return article, comments
