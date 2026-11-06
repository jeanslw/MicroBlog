"""RSS/Atom 订阅源功能测试."""

from app.database import get_or_create_site_setting
from app.extensions import db


def _set_switches(rss=True, atom=True):
    site = get_or_create_site_setting()
    site.rss_enabled = rss
    site.atom_enabled = atom
    db.session.commit()


def test_rss_feed(client, article, draft):
    """RSS 2.0 应包含已发布文章,排除草稿"""
    rv = client.get("/rss")
    assert rv.status_code == 200
    assert "application/rss+xml" in rv.content_type
    assert article.title.encode("utf-8") in rv.data
    assert draft.title.encode("utf-8") not in rv.data


def test_atom_feed(client, article, draft):
    """Atom 订阅源应包含已发布文章,排除草稿"""
    rv = client.get("/feed")
    assert rv.status_code == 200
    assert "application/atom+xml" in rv.content_type
    assert article.title.encode("utf-8") in rv.data
    assert draft.title.encode("utf-8") not in rv.data


def test_rss_contains_article_link(client, article):
    """RSS 中应包含文章绝对链接"""
    rv = client.get("/rss")
    assert f"/article/{article.id}".encode() in rv.data
    # 链接应为绝对地址(host 前缀)
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


def test_rss_switch_off(client, db):
    """关闭 RSS 后 /rss 返回 404,前台不再输出 RSS 链接."""
    _set_switches(rss=False)
    assert client.get("/rss").status_code == 404
    assert client.get("/feed").status_code == 200
    html = client.get("/").get_data(as_text=True)
    assert 'type="application/rss+xml"' not in html
    assert 'href="/rss"' not in html


def test_atom_switch_off(client, db):
    """关闭 Atom 后 /feed 返回 404,前台不再输出 Atom 链接."""
    _set_switches(atom=False)
    assert client.get("/feed").status_code == 404
    assert client.get("/rss").status_code == 200
    html = client.get("/").get_data(as_text=True)
    assert 'type="application/atom+xml"' not in html
    assert 'href="/feed"' not in html
