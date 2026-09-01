"""冒烟测试：核心链路健康检查。

覆盖：公开页面可达性、静态资源加载、后台登录保护、
404 处理、flash 消息以 Toast（牛皮癣式）形式输出且不占用页面布局。
"""

import json
import os
import re

from app.models import Article


def _flash_payload(html):
    """从页面 HTML 提取 id="flashData" 的 JSON 并解析。"""
    m = re.search(r'<script type="application/json" id="flashData">(.*?)</script>', html, re.S)
    assert m, "页面应注入 id=flashData 的 JSON（Toast 数据源）"
    return json.loads(m.group(1))


def test_homepage_smoke(client, article):
    """首页可达，UI 骨架完整：背景层 + Toast 容器 + 主题切换器"""
    rv = client.get("/")
    assert rv.status_code == 200
    html = rv.get_data(as_text=True)
    assert 'id="bgLayer"' in html
    assert 'id="flashToastContainer"' in html
    assert 'id="themeSwitcher"' in html
    assert "测试文章标题" in html


def test_static_assets_smoke(client):
    """核心静态资源可加载"""
    for path in (
        "/static/css/themes.css",
        "/static/lib/bootstrap.min.css",
        "/static/js/theme-switcher.js",
        "/static/js/flash-toast.js",
    ):
        assert client.get(path).status_code == 200, path


def test_background_image_smoke(client):
    """内置背景图可被静态服务访问"""
    bg_dir = os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
        "static",
        "backgrounds",
    )
    name = next(f for f in sorted(os.listdir(bg_dir)) if f.lower().endswith((".jpg", ".png", ".webp")))
    rv = client.get("/static/backgrounds/" + name)
    assert rv.status_code == 200
    assert rv.mimetype.startswith("image/")


def test_public_pages_smoke(client, article, category):
    """公开页面：首页 / 栏目页 / 文章详情"""
    for url in (
        "/",
        f"/category/{category.id}",
        f"/article/{article.id}",
    ):
        rv = client.get(url)
        assert rv.status_code == 200, url


def test_login_page_smoke(client):
    rv = client.get("/admin/login")
    assert rv.status_code == 200
    assert "管理员登录".encode() in rv.data


def test_404_smoke(client):
    assert client.get("/no-such-page").status_code == 404


def test_admin_requires_login(client):
    """未登录访问后台应重定向到登录页"""
    rv = client.get("/admin/site_setting", follow_redirects=False)
    assert rv.status_code == 302
    assert "/login" in rv.headers.get("Location", "")


def test_login_failure_flash_as_toast(client):
    """登录失败消息以 Toast JSON 注入，而非页面内 alert 占位"""
    rv = client.post(
        "/admin/login",
        data={
            "username": "admin",
            "password": "wrong-password-1",
        },
    )
    html = rv.get_data(as_text=True)
    payload = _flash_payload(html)
    assert payload[0][0] == "danger"
    assert "账号或密码错误" in payload[0][1]
    assert 'class="alert alert-danger"' not in html


def test_login_success_flash_as_toast(client):
    """登录成功后 redirect 的首页应带成功 Toast"""
    rv = client.post(
        "/admin/login",
        data={
            "username": "admin",
            "password": "admin123456",
        },
        follow_redirects=True,
    )
    html = rv.get_data(as_text=True)
    payload = _flash_payload(html)
    assert payload[0][0] == "success"
    assert payload[0][1] == "登录成功"


def test_article_list_home_smoke(client, category):
    """发布文章应出现在首页列表"""
    client.post(
        "/admin/login",
        data={
            "username": "admin",
            "password": "admin123456",
        },
    )
    rv = client.post(
        "/article/new",
        data={
            "title": "冒烟文章A",
            "content": "<p>冒烟正文</p>",
            "status": "publish",
            "category_id": str(category.id),
        },
        follow_redirects=False,
    )
    assert rv.status_code in (302, 200)
    home = client.get("/").get_data(as_text=True)
    assert "冒烟文章A" in home
    db_arts = Article.query.count()
    assert db_arts >= 1
