"""评论、点赞、回复功能测试。"""

from app.models import Comment, Reply, VoteLog


def test_vote_success(client, article, db):
    """点赞应成功并计数"""
    rv = client.post(f"/vote/{article.id}", follow_redirects=False)
    assert rv.status_code == 302
    db.session.refresh(article)
    assert article.vote_num == 1
    assert db.session.scalar(db.select(db.func.count(VoteLog.id)).where(VoteLog.article_id == article.id)) == 1


def test_vote_duplicate_same_ip(client, article, db):
    """同一 IP 重复点赞应被拒绝"""
    client.post(f"/vote/{article.id}")
    db.session.refresh(article)
    first_count = article.vote_num

    rv = client.post(f"/vote/{article.id}", follow_redirects=False)
    assert rv.status_code == 302
    db.session.refresh(article)
    # 计数不应变化
    assert article.vote_num == first_count


def test_vote_unpublished_article(client, draft, db):
    """草稿不能被点赞"""
    rv = client.post(f"/vote/{draft.id}", follow_redirects=False)
    assert rv.status_code == 302
    db.session.refresh(draft)
    assert draft.vote_num == 0


def test_vote_nonexistent_article(client):
    """不存在的文章不能点赞"""
    rv = client.post("/vote/99999", follow_redirects=False)
    assert rv.status_code == 302


def test_vote_from_article_list_returns_to_source(client, article, db):
    """列表页点赞后应回到来源页（而非跳文章详情）"""
    rv = client.post(
        f"/vote/{article.id}",
        data={"next": "/?page=2"},
        follow_redirects=False,
    )
    assert rv.status_code == 302
    location = rv.headers["Location"]
    assert "?page=2" in location
    assert f"/article/{article.id}" not in location
    db.session.refresh(article)
    assert article.vote_num == 1


def test_vote_ignores_external_next(client, article):
    """next 指向站外时忽略并回详情页（防开放重定向）"""
    rv = client.post(
        f"/vote/{article.id}",
        data={"next": "https://evil.example.com/steal"},
        follow_redirects=False,
    )
    assert rv.status_code == 302
    assert f"/article/{article.id}" in rv.headers["Location"]


def test_article_list_has_clickable_like_button(client, article):
    """首页文章列表的点赞应是可以提交的表单按钮"""
    rv = client.get("/")
    assert rv.status_code == 200
    body = rv.data.decode("utf-8")
    assert f'action="/vote/{article.id}"' in body
    assert 'name="next"' in body
    assert "csrf_token" in body


def test_add_comment_success(client, article, db):
    """发表评论应成功"""
    rv = client.post(
        f"/comment/add/{article.id}",
        data={
            "username": "测试用户",
            "content": "这是一条评论",
        },
        follow_redirects=False,
    )
    assert rv.status_code == 302
    cnt = db.session.scalar(db.select(db.func.count(Comment.id)).where(Comment.article_id == article.id))
    assert cnt == 1


def test_add_comment_empty_content(client, article, db):
    """空内容评论应被拒绝"""
    rv = client.post(
        f"/comment/add/{article.id}",
        data={
            "username": "x",
            "content": "",
        },
        follow_redirects=False,
    )
    assert rv.status_code == 302
    cnt = db.session.scalar(db.select(db.func.count(Comment.id)).where(Comment.article_id == article.id))
    assert cnt == 0


def test_add_comment_default_username(client, article, db):
    """未填用户名时默认游客"""
    client.post(
        f"/comment/add/{article.id}",
        data={
            "username": "",
            "content": "评论",
        },
    )
    c = db.session.scalar(db.select(Comment).filter_by(article_id=article.id))
    assert c is not None
    assert c.username == "游客"


def test_add_comment_to_unpublished(client, draft):
    """草稿文章不能评论"""
    rv = client.post(
        f"/comment/add/{draft.id}",
        data={
            "username": "x",
            "content": "评论",
        },
        follow_redirects=False,
    )
    assert rv.status_code == 302


def test_add_comment_to_nonexistent(client):
    """不存在文章不能评论"""
    rv = client.post(
        "/comment/add/99999",
        data={
            "username": "x",
            "content": "评论",
        },
        follow_redirects=False,
    )
    assert rv.status_code == 302


def test_add_reply_success(client, article, db):
    """回复评论应成功"""
    c = Comment(article_id=article.id, username="u", content="c", create_time="2026-01-01 00:00:00")
    db.session.add(c)
    db.session.commit()

    rv = client.post(
        f"/reply/add/{article.id}/{c.id}",
        data={
            "username": "回复者",
            "content": "回复内容",
        },
        follow_redirects=False,
    )
    assert rv.status_code == 302
    cnt = db.session.scalar(db.select(db.func.count(Reply.id)).where(Reply.comment_id == c.id))
    assert cnt == 1


def test_add_reply_empty_content(client, article, db):
    """空内容回复应被拒绝"""
    c = Comment(article_id=article.id, username="u", content="c", create_time="2026-01-01 00:00:00")
    db.session.add(c)
    db.session.commit()

    rv = client.post(
        f"/reply/add/{article.id}/{c.id}",
        data={
            "username": "x",
            "content": "",
        },
        follow_redirects=False,
    )
    assert rv.status_code == 302
    cnt = db.session.scalar(db.select(db.func.count(Reply.id)).where(Reply.comment_id == c.id))
    assert cnt == 0


def test_add_reply_to_nonexistent_comment(client, article):
    """回复不存在的评论应失败"""
    rv = client.post(
        f"/reply/add/{article.id}/99999",
        data={
            "username": "x",
            "content": "reply",
        },
        follow_redirects=False,
    )
    assert rv.status_code == 302


def test_add_reply_to_wrong_article(client, article, db):
    """评论与文章不匹配应失败"""
    c = Comment(article_id=article.id, username="u", content="c", create_time="2026-01-01 00:00:00")
    db.session.add(c)
    db.session.commit()

    # 用错误的 aid
    rv = client.post(
        f"/reply/add/99999/{c.id}",
        data={
            "username": "x",
            "content": "reply",
        },
        follow_redirects=False,
    )
    assert rv.status_code == 302


def test_comments_displayed_on_detail(client, article, db):
    """评论应展示在文章详情页"""
    c = Comment(article_id=article.id, username="访客甲", content="看完了", create_time="2026-01-01 00:00:00")
    db.session.add(c)
    db.session.commit()

    rv = client.get(f"/article/{article.id}")
    assert rv.status_code == 200
    assert "访客甲".encode() in rv.data
    assert "看完了".encode() in rv.data
