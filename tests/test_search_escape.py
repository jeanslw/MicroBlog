"""站内搜索的 LIKE 通配符转义（P1）。

旧实现把用户输入直接拼进 ``%{keyword}%``：搜索「%」会命中全部文章、搜索「a_」
会命中「ab」等 —— 结果与关键词无关，同时让查询退化为全表模糊匹配。
现在改用 ``contains(..., autoescape=True)``：通配符按字面匹配。
"""

from app.models import Article


def _add_article(db, title, content="<p>正文</p>", ctime="2026-02-01 00:00:00"):
    art = Article(
        title=title,
        content=content,
        status="publish",
        create_time=ctime,
        update_time=ctime,
        vote_num=0,
    )
    db.session.add(art)
    db.session.commit()
    return art


def test_percent_is_matched_literally(app, db, article):
    from app.blog.queries import search_articles

    _, _, total = search_articles("%", 0, 10)
    assert total == 0, "旧实现下搜索 % 会命中全部文章"

    matched = _add_article(db, "进度 100% 完成")
    arts, _, total = search_articles("%", 0, 10)
    assert total == 1
    assert arts[0].id == matched.id


def test_underscore_is_matched_literally(app, db, article):
    from app.blog.queries import search_articles

    _, _, total = search_articles("_", 0, 10)
    assert total == 0, "旧实现下 _ 会匹配任意单个字符"

    matched = _add_article(db, "snake_case 命名")
    arts, _, total = search_articles("_", 0, 10)
    assert total == 1
    assert arts[0].id == matched.id


def test_normal_keyword_still_matches_title_and_content(app, db, article):
    from app.blog.queries import search_articles

    arts, _, total = search_articles("测试", 0, 10)
    assert total == 1
    assert arts[0].id == article.id

    _add_article(db, "无关标题", content="<p>正文里提到 SQLAlchemy 查询</p>")
    arts, _, total = search_articles("SQLAlchemy", 0, 10)
    assert total == 1
