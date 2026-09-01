"""站点设置与图片上传功能测试。"""
import io

from PIL import Image

from app.models import SiteConfig


def _make_image_bytes(fmt="PNG", size=(50, 50)):
    buf = io.BytesIO()
    Image.new("RGB", size, "white").save(buf, format=fmt)
    buf.seek(0)  # 重置流位置，避免 PIL 读取到空数据
    return buf


def test_site_setting_form(login_admin):
    """站点设置表单可访问"""
    rv = login_admin.get("/admin/site_setting")
    assert rv.status_code == 200
    assert "站点全局设置".encode() in rv.data


def test_site_setting_update_name(login_admin, db):
    """修改站点名应生效"""
    rv = login_admin.post("/admin/site_setting", data={
        "site_name": "我的新博客",
    }, follow_redirects=False)
    assert rv.status_code == 302
    s = db.session.get(SiteConfig, 1)
    assert s.site_name == "我的新博客"


def test_site_setting_empty_name_rejected(login_admin, db):
    """空站点名应被拒绝"""
    old = db.session.get(SiteConfig, 1).site_name
    rv = login_admin.post("/admin/site_setting", data={
        "site_name": "",
    }, follow_redirects=False)
    # 校验失败留在表单页
    assert rv.status_code == 200
    # 名称不应变化
    assert db.session.get(SiteConfig, 1).site_name == old


def test_site_name_appears_in_navbar(login_admin, db):
    """修改的站点名应出现在导航栏"""
    s = db.session.get(SiteConfig, 1)
    s.site_name = "测试站点XYZ"
    db.session.commit()
    rv = login_admin.get("/")
    assert "测试站点XYZ".encode() in rv.data


def test_upload_image_requires_login(client):
    """未登录不能上传图片"""
    img = _make_image_bytes()
    rv = client.post("/admin/upload", data={
        "image": (img, "x.png"),
    }, content_type="multipart/form-data", follow_redirects=False)
    assert rv.status_code == 302
    assert "/login" in rv.headers.get("Location", "")


def test_upload_image_success(login_admin):
    """成功上传图片应返回 JSON url"""
    img = _make_image_bytes("PNG")
    rv = login_admin.post("/admin/upload", data={
        "image": (img, "photo.png"),
    })
    assert rv.status_code == 200
    import json
    data = json.loads(rv.data)
    assert "url" in data
    assert data["url"].startswith("/static/uploads/")
    assert data["url"].endswith(".png") or data["url"].endswith(".jpg")


def test_upload_image_no_file(login_admin):
    """未传文件应返回错误"""
    rv = login_admin.post("/admin/upload", data={
        "image": (io.BytesIO(b""), ""),
    }, content_type="multipart/form-data")
    assert rv.status_code == 400


def test_upload_image_invalid_ext(login_admin):
    """非法扩展名应被拒绝"""
    rv = login_admin.post("/admin/upload", data={
        "image": (io.BytesIO(b"not image"), "evil.txt"),
    }, content_type="multipart/form-data")
    assert rv.status_code == 400


def test_upload_image_jpeg(login_admin):
    """JPEG 格式应可上传并返回 .jpg 扩展名"""
    img = _make_image_bytes("JPEG")
    rv = login_admin.post("/admin/upload", data={
        "image": (img, "photo.jpg"),
    }, content_type="multipart/form-data")
    assert rv.status_code == 200
    import json
    data = json.loads(rv.data)
    assert data["url"].endswith(".jpg")


def test_upload_image_gif(login_admin):
    """GIF 格式应可上传"""
    img = _make_image_bytes("GIF")
    rv = login_admin.post("/admin/upload", data={
        "image": (img, "photo.gif"),
    }, content_type="multipart/form-data")
    assert rv.status_code == 200
    import json
    data = json.loads(rv.data)
    assert data["url"].endswith(".gif")


def test_ensure_admin_exists_creates_admin(app, db):
    """空 admin 表 + 设置密码时应创建管理员"""
    from app.database import ensure_admin_exists
    from app.models import Admin
    # 清空 admin 表
    db.session.query(Admin).delete()
    db.session.commit()
    ensure_admin_exists()
    cnt = db.session.scalar(db.select(db.func.count(Admin.id)))
    assert cnt == 1


def test_ensure_site_config_creates_default(app, db):
    """空 site_config 表应创建默认配置"""
    from app.database import ensure_site_config
    from app.models import SiteConfig
    db.session.query(SiteConfig).delete()
    db.session.commit()
    ensure_site_config()
    s = db.session.get(SiteConfig, 1)
    assert s is not None
    assert s.site_name == "我的博客"


def test_cli_init_db(runner):
    """flask init-db 命令应可执行"""
    rv = runner.invoke(args=["init-db"])
    assert rv.exit_code == 0
