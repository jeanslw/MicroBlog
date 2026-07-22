import traceback
from app.db import get_db, DictCursor


def get_all_banner():
    """获取所有轮播图（按排序字段降序）"""
    try:
        db = get_db()
        cur = db.cursor(DictCursor)
        cur.execute("SELECT * FROM banner ORDER BY sort DESC")
        res = cur.fetchall()
        cur.close()
        return res
    except Exception:
        print("=====获取轮播图失败=====")
        traceback.print_exc()
        return []
