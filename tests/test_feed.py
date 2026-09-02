"""RSS/Atom 订阅源功能测试。"""


def test_rss_feed(client, article, draft):
    """RSS 2.0 应包含已发布文章、排除草稿"""
    rv = client.get("/rss")
    assert rv.status_code == 200
    assert "application/rss+xml" in rv.content_type
    assert article.title.encode("utf-8") in rv.data
    assert draft.title.encode("utf-8") not in rv.data


def test_atom_feed(client, article, draft):
    """Atom 订阅源应包含已发布文章、排除草稿"""
    rv = client.get("/feed")
    assert rv.status_code == 200
    assert "application/atom+xml" in rv.content_type
    assert article.title.encode("utf-8") in rv.data
    assert draft.title.encode("utf-8") not in rv.data


def test_rss_contains_article_link(client, article):
    """RSS 中应包含文章绝对链接"""
    rv = client.get("/rss")
    assert f"/article/{article.id}".encode() in rv.data
    # 链接应为绝对地址（host 前缀）
    assert b"http://localhost/article/" in rv.data


def test_atom_contains_article_link(client, article):
    """Atom 中应包含文章绝对链接"""
    rv = client.get("/feed")
    assert b"http://localhost/article/" in rv.data


def test_feed_empty_site(client):
    """无文章时订阅源应返回 200 空 feed"""
    rv = client.get("/rss")
    assert rv.status_code == 200
    assert b"<rss" in rv.data
