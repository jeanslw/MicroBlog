"""博客查询层 —— 基于 SQLAlchemy ORM。

提供文章列表、文章详情、评论聚合等查询。
所有返回值为 ORM 对象或字典,供模板直接使用。
"""

import math

from sqlalchemy import func, or_, select

from app.extensions import db
from app.models import Article, Category, Comment, Reply
from app.utils import sanitize_html, strip_html


def get_categories_with_count():
    """获取所有栏目 + 已发布文章数（用于侧边栏/导航）"""
    rows = db.session.execute(
        select(
            Category.id,
            Category.cat_name,
            Category.tag_text,
            Category.create_time,
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
    base_filter = Article.status == "publish"
    if cid:
        base_filter = db.and_(base_filter, Article.category_id == cid)

    total = db.session.scalar(select(func.count(Article.id)).where(base_filter)) or 0
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
        .order_by(Article.is_pinned.desc(), Article.create_time.desc())
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
    article.safe_content 为净化后的 HTML（非映射属性,不会触发脏 UPDATE）。
    切勿把净化结果赋回 article.content（mapped 列会变 dirty,触发无谓 UPDATE）。
    """
    article = db.session.get(Article, aid)
    if not article:
        return None, []

    # 净化 HTML 输出,防止存储型 XSS。结果存到非映射属性 safe_content,
    # 不修改 mapped 的 content 列，避免每次详情页访问都触发一条 UPDATE。
    article.safe_content = sanitize_html(article.content)

    # 一次性查出所有评论
    comments = db.session.scalars(select(Comment).where(Comment.article_id == aid).order_by(Comment.create_time)).all()

    if not comments:
        return article, []

    # 一次性查出所有回复
    comment_ids = [c.id for c in comments]
    replies = db.session.scalars(
        select(Reply).where(Reply.comment_id.in_(comment_ids)).order_by(Reply.create_time)
    ).all()

    # 按 comment_id 分组
    reply_map = {}
    for r in replies:
        reply_map.setdefault(r.comment_id, []).append(r)
    for c in comments:
        c.reply_list = reply_map.get(c.id, [])

    return article, comments


def search_articles(keyword: str, offset: int, limit: int):
    """按关键词搜索已发布文章（标题/正文模糊匹配）。

    返回 (article_list, total_page, total)
    """
    like = f"%{keyword}%"
    base_filter = db.and_(
        Article.status == "publish",
        or_(Article.title.like(like), Article.content.like(like)),
    )
    total = db.session.scalar(select(func.count(Article.id)).where(base_filter)) or 0
    total_page = max(math.ceil(total / limit) if limit > 0 else 1, 1)
    articles = db.session.scalars(
        select(Article)
        .where(base_filter)
        .order_by(Article.create_time.desc())
        .offset(offset)
        .limit(limit)
    ).all()
    for art in articles:
        art.brief = strip_html(art.content)
    return articles, total_page, total


def get_recent_articles(limit: int = 20):
    """获取最近发布的文章（用于 RSS/Atom 订阅源）"""
    return db.session.scalars(
        select(Article)
        .where(Article.status == "publish")
        .order_by(Article.create_time.desc())
        .limit(limit)
    ).all()


def _split_year_month(value):
    """从 "YYYY-MM-DD HH:MM:SS" 解析 (year, month)，异常返回 (None, None)。"""
    try:
        return int(value[:4]), int(value[5:7])
    except (TypeError, ValueError, IndexError):
        return None, None


def get_sidebar_tree():
    """构建侧边栏「栏目树 + 文章档案」数据。

    一次查询全部已发布文章的 (id, title, category_id, create_time)，内存聚合避免 N+1。

    返回 (category_map, archive)：
      category_map: {category_id: [(article_id, title), ...]}
      archive: [{"year": int, "count": int,
                 "months": [{"month": int, "count": int, "articles": [(id, title), ...]}, ...]}, ...]
    """
    rows = db.session.execute(
        select(Article.id, Article.title, Article.category_id, Article.create_time)
        .where(Article.status == "publish")
        .order_by(Article.create_time.desc())
    ).all()

    category_map = {}
    archive_map = {}
    for aid, title, cid, ctime in rows:
        if cid is not None:
            category_map.setdefault(cid, []).append((aid, title))
        year, month = _split_year_month(ctime)
        if year is None:
            continue
        archive_map.setdefault(year, {}).setdefault(month, []).append((aid, title))

    archive = []
    for year in sorted(archive_map, reverse=True):
        months_map = archive_map[year]
        months = [
            {"month": m, "count": len(items), "articles": items}
            for m, items in sorted(months_map.items(), reverse=True)
        ]
        archive.append({"year": year, "count": sum(x["count"] for x in months), "months": months})

    return category_map, archive
