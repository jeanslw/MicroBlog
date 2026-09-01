"""Banner 查询层 —— 基于 SQLAlchemy"""

from app.extensions import db
from app.models import Banner


def get_all_banner():
    """获取所有轮播图（按排序字段降序）"""
    try:
        return db.session.scalars(db.select(Banner).order_by(Banner.sort.desc())).all()
    except Exception:
        from app.extensions import log

        log.error("获取轮播图失败", exc_info=True)
        return []
