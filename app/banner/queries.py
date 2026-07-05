import pymysql
import traceback
from app.extensions import get_db


def get_all_banner():
    """获取所有轮播图（按排序字段降序）"""
    try:
        db = get_db()
        cur = db.cursor(pymysql.cursors.DictCursor)
        cur.execute("SELECT * FROM banner ORDER BY sort DESC")
        res = cur.fetchall()
        cur.close()
        db.close()
        return res
    except Exception:
        return []
