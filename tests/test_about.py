"""「关于我」前台页面与后台独立设置页测试。"""

from app.models import SiteConfig

ABOUT_FIELD_NAMES = (
    "avatar_upload",
    "avatar_url",
    "avatar_clear",
    "about_email",
    "about_github",
    "about_homepage",
    "about_bio",
)


def _update_site(db, **kwargs):
    s = db.session.get(SiteConfig, 1)
    for k, v in kwargs.items():
        setattr(s, k, v)
    db.session.commit()
    return s


# ── 前台 /about ──────────────────────────────────────────

def test_about_page_empty(client):
    """未填写内容时 /about 应 200 且无崩溃"""
    rv = client.get("/about")
    assert rv.status_code == 200
    assert "关于我".encode() in rv.data
    assert "暂无内容".encode() in rv.data
    body = rv.data.decode("utf-8")
    assert 'href="/about"' in body  # 导航含「关于我」入口
    # 「关于我」排在「全部栏目」之后
    assert body.index("全部栏目") < body.index('href="/about"')


def test_about_page_shows_configured(client, db):
    """后台填写的头像/简介/邮箱/GitHub 应展示在 /about"""
    _update_site(
        db,
        about_avatar="https://example.com/me.png",
        about_bio="我是一名开发者\n爱好开源与写作",
        about_email="me@example.com",
        about_github="github.com/jeanslw",
        about_homepage="example.com/home",
    )
    rv = client.get("/about")
    assert rv.status_code == 200
    body = rv.data.decode("utf-8")
    assert "https://example.com/me.png" in body
    assert "mailto:me@example.com" in body
    assert "https://github.com/jeanslw" in body
    assert "github.com/jeanslw" in body
    assert "https://example.com/home" in body  # 无协议时自动补 https://
    assert "example.com/home" in body  # 展示文本去掉协议
    assert "我是一名开发者" in body
    assert "暂无内容" not in body


# ── 后台独立「关于我」设置页 ──────────────────────────────

def test_about_setting_page_has_fields_and_menu(login_admin):
    """关于我设置页包含输入项,侧栏含菜单入口;站点设置页不再含这些字段"""
    rv = login_admin.get("/admin/about_setting")
    assert rv.status_code == 200
    body = rv.data.decode("utf-8")
    for name in ABOUT_FIELD_NAMES:
        assert f'name="{name}"' in body
    assert 'href="/admin/about_setting"' in body  # 侧栏菜单入口


def test_site_setting_page_without_about_fields(login_admin):
    """拆分后原「站点设置」页不应再出现关于字段"""
    rv = login_admin.get("/admin/site_setting")
    assert rv.status_code == 200
    body = rv.data.decode("utf-8")
    for name in ABOUT_FIELD_NAMES:
        assert f'name="{name}"' not in body


def test_about_setting_save(login_admin, db):
    """保存关于字段应持久化到 site_config"""
    rv = login_admin.post(
        "/admin/about_setting",
        data={
            "avatar_url": "https://example.com/me.png",
            "about_email": "ME@Example.COM",
            "about_github": "github.com/jeanslw",
            "about_homepage": "https://example.com/home",
            "about_bio": "第一行\n第二行",
        },
        follow_redirects=False,
    )
    assert rv.status_code == 302
    s = db.session.get(SiteConfig, 1)
    assert s.about_avatar == "https://example.com/me.png"
    assert s.about_email == "me@example.com"  # 邮箱统一转小写
    assert s.about_github == "github.com/jeanslw"
    assert s.about_homepage == "https://example.com/home"
    assert s.about_bio == "第一行\n第二行"


def test_about_setting_clear_avatar(login_admin, db):
    """勾选清除头像应清空 about_avatar"""
    _update_site(db, about_avatar="/static/uploads/avatar/old.png")
    rv = login_admin.post(
        "/admin/about_setting",
        data={"avatar_clear": "y"},
        follow_redirects=False,
    )
    assert rv.status_code == 302
    assert db.session.get(SiteConfig, 1).about_avatar == ""


def test_about_setting_invalid_email_rejected(login_admin, db):
    """非法邮箱应留在表单页且不保存"""
    _update_site(db, about_email="old@example.com")
    rv = login_admin.post(
        "/admin/about_setting",
        data={"about_email": "not-an-email"},
        follow_redirects=False,
    )
    assert rv.status_code == 200
    assert db.session.get(SiteConfig, 1).about_email == "old@example.com"
