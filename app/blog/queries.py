"""博客查询层 —— 基于 SQLAlchemy ORM。

提供文章列表、文章详情、评论聚合等查询。
所有返回值为 ORM 对象或字典,供模板直接使用。
"""
import math

from sqlalchemy import func, select

from app.extensions import db
from app.models import Article, Category, Comment, Reply
from app.utils import sanitize_html, strip_html


def get_categories_with_count():
    """获取所有栏目 + 已发布文章数（用于侧边栏/导航）"""
    rows = db.session.execute(
        select(
            Category.id, Category.cat_name, Category.tag_text, Category.create_time,
            func.count(Article.id).label("art_count"),
        )
        .outerjoin(Article, (Category.id == Article.category_id) & (Article.status == "publish"))
        .group_by(Category.id)
        .order_by(Category.id.desc())
    ).all()
    return rows


def get_article_list(offset: int, limit: int, cid: int | None = None):
    """获取已发布文章列表（分页 + 可选栏目筛选）。

    返回 (article_list, total_page)
    """
    base_filter = (Article.status == "publish")
    if cid:
        base_filter = db.and_(base_filter, Article.category_id == cid)

    total = db.session.scalar(
        select(func.count(Article.id)).where(base_filter)
    ) or 0
    total_page = max(math.ceil(total / limit) if limit > 0 else 1, 1)

    # 评论计数子查询
    comment_count = (
        select(func.count(Comment.id))
        .where(Comment.article_id == Article.id)
        .correlate(Article)
        .scalar_subquery()
        .label("comment_num")
    )

    rows = db.session.execute(
        select(Article, comment_count)
        .where(base_filter)
        .order_by(Article.create_time.desc())
        .offset(offset)
        .limit(limit)
    ).all()

    articles = []
    for art, comment_num in rows:
        art.comment_num = comment_num or 0
        art.brief = strip_html(art.content)
        articles.append(art)

    return articles, total_page


def get_article_detail(aid: int):
    """获取文章详情 + 评论 + 回复（批量查询避免 N+1）

    返回 (article, comments_with_replies)
    article.content 会被净化以防止 XSS。
    """
    article = db.session.get(Article, aid)
    if not article:
        return None, []

    # 净化 HTML 输出,防止存储型 XSS
    article.content = sanitize_html(article.content)

    # 一次性查出所有评论
    comments = db.session.scalars(
        select(Comment)
        .where(Comment.article_id == aid)
        .order_by(Comment.create_time)
    ).all()

    if not comments:
        return article, []

    # 一次性查出所有回复
    comment_ids = [c.id for c in comments]
    replies = db.session.scalars(
        select(Reply)
        .where(Reply.comment_id.in_(comment_ids))
        .order_by(Reply.create_time)
    ).all()

    # 按 comment_id 分组
    reply_map = {}
    for r in replies:
        reply_map.setdefault(r.comment_id, []).append(r)
    for c in comments:
        c.reply_list = reply_map.get(c.id, [])

    return article, comments
