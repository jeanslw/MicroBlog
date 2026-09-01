"""UI 主题与背景设置单元测试（内置图库 / 自定义 URL / 上传背景）。"""

import io
import os

from PIL import Image

from app.models import SiteConfig


def _make_image_bytes(fmt="JPEG", size=(320, 200)):
    buf = io.BytesIO()
    Image.new("RGB", size, "white").save(buf, format=fmt)
    buf.seek(0)
    return buf


def test_homepage_bg_style_default(client):
    """默认风格 bg1 应输出到 body data-bg"""
    html = client.get("/").get_data(as_text=True)
    assert 'data-bg="bg1"' in html


def test_site_setting_page_shows_bg_gallery(login_admin):
    """后台设置页应包含内置背景图库选项"""
    html = login_admin.get("/admin/site_setting").get_data(as_text=True)
    assert 'name="bg_style"' in html
    assert "bg1" in html
    assert 'value="custom"' in html


def test_site_bg_style_save(login_admin, db):
    """保存内置风格 bg3 应生效，且 bg_custom 被清空"""
    rv = login_admin.post(
        "/admin/site_setting",
        data={
            "site_name": "我的博客",
            "bg_style": "bg3",
        },
        follow_redirects=False,
    )
    assert rv.status_code == 302
    s = db.session.get(SiteConfig, 1)
    assert s.bg_style == "bg3"
    assert s.bg_custom == ""


def test_site_bg_custom_url_save(login_admin, db):
    """自定义 URL 背景保存应生效"""
    url = "https://example.com/custom-bg.jpg"
    rv = login_admin.post(
        "/admin/site_setting",
        data={
            "site_name": "我的博客",
            "bg_style": "custom",
            "bg_custom": url,
        },
        follow_redirects=False,
    )
    assert rv.status_code == 302
    s = db.session.get(SiteConfig, 1)
    assert s.bg_style == "custom"
    assert s.bg_custom == url


def test_site_bg_upload_save(login_admin, db, monkeypatch, tmp_path):
    """上传背景图应保存到 uploads/backgrounds 且 URL 可访问"""
    from app.admin import routes as admin_routes

    def fake_upload_dir(subdir="uploads"):
        d = tmp_path / "bg" / subdir
        d.mkdir(parents=True, exist_ok=True)
        return str(d)

    # 重定向上传目录，避免污染真实 static/ 目录
    monkeypatch.setattr(admin_routes, "upload_dir", fake_upload_dir)

    img = _make_image_bytes("JPEG")
    rv = login_admin.post(
        "/admin/site_setting",
        data={
            "site_name": "我的博客",
            "bg_style": "custom",
            "bg_upload": (img, "my-bg.jpg"),
        },
        content_type="multipart/form-data",
        follow_redirects=False,
    )
    assert rv.status_code == 302
    s = db.session.get(SiteConfig, 1)
    assert s.bg_style == "custom"
    assert s.bg_custom.startswith("/static/uploads/backgrounds/")
    fname = os.path.basename(s.bg_custom)
    saved = os.path.join(str(tmp_path / "bg" / "uploads" / "backgrounds"), fname)
    assert os.path.exists(saved), "上传文件应已写入磁盘"


def test_site_bg_upload_invalid_rejected(login_admin, db):
    """非法扩展名背景应被拒绝，站点背景保持不变"""
    old = db.session.get(SiteConfig, 1)
    old_bg_style, old_bg_custom = old.bg_style, old.bg_custom
    rv = login_admin.post(
        "/admin/site_setting",
        data={
            "site_name": "我的博客",
            "bg_style": "custom",
            "bg_upload": (io.BytesIO(b"not an image"), "evil.txt"),
        },
        content_type="multipart/form-data",
        follow_redirects=False,
    )
    assert rv.status_code == 200  # 校验失败留在表单页
    s = db.session.get(SiteConfig, 1)
    assert s.bg_style == old_bg_style
    assert s.bg_custom == old_bg_custom


def test_site_logo_upload_save(login_admin, db, monkeypatch, tmp_path):
    """上传 Logo 应保存到 uploads/logo 且 URL 可访问"""
    from app.admin import routes as admin_routes

    def fake_upload_dir(subdir="uploads"):
        d = tmp_path / "logo" / subdir
        d.mkdir(parents=True, exist_ok=True)
        return str(d)

    monkeypatch.setattr(admin_routes, "upload_dir", fake_upload_dir)

    img = _make_image_bytes("PNG")
    rv = login_admin.post(
        "/admin/site_setting",
        data={
            "site_name": "我的博客",
            "bg_style": "bg1",
            "logo_upload": (img, "my-logo.png"),
        },
        content_type="multipart/form-data",
        follow_redirects=False,
    )
    assert rv.status_code == 302
    s = db.session.get(SiteConfig, 1)
    assert s.logo_path.startswith("/static/uploads/logo/")
    fname = os.path.basename(s.logo_path)
    saved = os.path.join(str(tmp_path / "logo" / "uploads" / "logo"), fname)
    assert os.path.exists(saved), "Logo 文件应已写入磁盘"


def test_site_logo_oversized_auto_scaled(login_admin, db, monkeypatch, tmp_path):
    """超大 Logo（1200x600）上传后应自动缩放到长边不超过 400"""
    from app.admin import routes as admin_routes

    def fake_upload_dir(subdir="uploads"):
        d = tmp_path / "logo2" / subdir
        d.mkdir(parents=True, exist_ok=True)
        return str(d)

    monkeypatch.setattr(admin_routes, "upload_dir", fake_upload_dir)

    img = _make_image_bytes("JPEG", size=(1200, 600))
    rv = login_admin.post(
        "/admin/site_setting",
        data={
            "site_name": "我的博客",
            "bg_style": "bg1",
            "logo_upload": (img, "big-logo.jpg"),
        },
        content_type="multipart/form-data",
        follow_redirects=False,
    )
    assert rv.status_code == 302
    s = db.session.get(SiteConfig, 1)
    fname = os.path.basename(s.logo_path)
    saved = os.path.join(str(tmp_path / "logo2" / "uploads" / "logo"), fname)
    with Image.open(saved) as out:
        assert max(out.width, out.height) <= 400, "Logo 过长边应被缩放到 400 内"


def test_site_logo_invalid_rejected(login_admin, db):
    """非法 Logo 文件应被拒绝，站点 Logo 保持不变"""
    old = db.session.get(SiteConfig, 1)
    old_logo = old.logo_path
    rv = login_admin.post(
        "/admin/site_setting",
        data={
            "site_name": "我的博客",
            "bg_style": "bg1",
            "logo_upload": (io.BytesIO(b"not an image"), "evil.txt"),
        },
        content_type="multipart/form-data",
        follow_redirects=False,
    )
    assert rv.status_code == 200  # 校验失败留在表单页
    s = db.session.get(SiteConfig, 1)
    assert s.logo_path == old_logo


def test_homepage_renders_navbar_logo(login_admin, db):
    """设置 Logo 后首页导航栏应输出 <img class="navbar-logo">"""
    s = db.session.get(SiteConfig, 1)
    s.logo_path = "/static/uploads/logo/test-logo.png"
    db.session.commit()
    html = login_admin.get("/").get_data(as_text=True)
    assert 'class="navbar-logo"' in html
    assert "/static/uploads/logo/test-logo.png" in html


def test_background_assets_complete():
    """内置背景图库文件齐全（供 themes.css 引用）"""
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    bg_dir = os.path.join(root, "static", "backgrounds")
    assert os.path.isdir(bg_dir), "static/backgrounds 目录应存在"
    files = [f for f in os.listdir(bg_dir) if f.lower().endswith((".jpg", ".jpeg", ".png", ".webp"))]
    assert len(files) >= 12, "内置背景图应不少于 12 张"


def test_homepage_custom_bg_style_renders(login_admin, db):
    """保存 bg5 后首页 data-bg 应输出 bg5"""
    s = db.session.get(SiteConfig, 1)
    s.bg_style = "bg5"
    db.session.commit()
    html = login_admin.get("/").get_data(as_text=True)
    assert 'data-bg="bg5"' in html
