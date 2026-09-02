"""Banner 轮播图功能测试。"""

import io

from PIL import Image

from app.models import Banner


def _make_image_bytes(fmt="PNG", size=(50, 50)):
    """生成测试用图片字节流"""
    buf = io.BytesIO()
    Image.new("RGB", size, "white").save(buf, format=fmt)
    buf.seek(0)
    return buf


def test_banner_list_requires_login(client):
    """轮播图列表需登录"""
    rv = client.get("/banner/", follow_redirects=False)
    assert rv.status_code == 302


def test_banner_list_empty(login_admin):
    """无 banner 时展示空状态"""
    rv = login_admin.get("/banner/")
    assert rv.status_code == 200
    assert "暂无轮播广告".encode() in rv.data


def test_banner_list_shows_items(login_admin, db):
    """已有 banner 时展示"""
    db.session.add(
        Banner(
            img_path="/static/banner/x.jpg",
            title="T1",
            link_url="https://example.com",
            sort=1,
            create_time="2026-01-01 00:00:00",
        )
    )
    db.session.commit()
    rv = login_admin.get("/banner/")
    assert rv.status_code == 200
    assert b"T1" in rv.data


def test_banner_add_success(login_admin, db, app):
    """成功新增 banner"""
    img_buf = _make_image_bytes("PNG")
    rv = login_admin.post(
        "/banner/add",
        data={
            "banner_img": (img_buf, "test.png"),
            "link_url": "https://example.com",
            "title": "新Banner",
            "desc_text": "描述",
            "sort_num": 5,
        },
        content_type="multipart/form-data",
        follow_redirects=False,
    )
    assert rv.status_code == 302
    b = db.session.scalar(db.select(Banner).filter_by(title="新Banner"))
    assert b is not None
    assert b.sort == 5
    assert b.img_path.startswith("/static/banner/")


def test_banner_add_no_file(login_admin, db):
    """未传文件应失败"""
    rv = login_admin.post(
        "/banner/add",
        data={
            "banner_img": (io.BytesIO(b""), ""),
            "title": "无图",
            "link_url": "",
            "desc_text": "",
            "sort_num": 0,
        },
        content_type="multipart/form-data",
        follow_redirects=False,
    )
    assert rv.status_code == 302
    cnt = db.session.scalar(db.select(db.func.count(Banner.id)))
    assert cnt == 0


def test_banner_add_invalid_format(login_admin, db):
    """非法扩展名应被表单校验拒绝"""
    rv = login_admin.post(
        "/banner/add",
        data={
            "banner_img": (io.BytesIO(b"not an image"), "evil.txt"),
            "title": "x",
            "link_url": "",
            "desc_text": "",
            "sort_num": 0,
        },
        content_type="multipart/form-data",
        follow_redirects=False,
    )
    # FileAllowed 应阻止 txt
    assert rv.status_code == 302
    cnt = db.session.scalar(db.select(db.func.count(Banner.id)))
    assert cnt == 0


def test_banner_edit_metadata(login_admin, db):
    """仅编辑文字字段（不换图）应成功"""
    b = Banner(img_path="/static/banner/old.jpg", title="旧", create_time="2026-01-01 00:00:00")
    db.session.add(b)
    db.session.commit()

    rv = login_admin.post(
        f"/banner/edit/{b.id}",
        data={
            "banner_img": (io.BytesIO(b""), ""),
            "title": "新标题",
            "link_url": "https://new.example.com",
            "desc_text": "新描述",
            "sort_num": 9,
        },
        content_type="multipart/form-data",
        follow_redirects=False,
    )
    assert rv.status_code == 302
    db.session.refresh(b)
    assert b.title == "新标题"
    assert b.sort == 9


def test_banner_edit_replace_image(login_admin, db):
    """更换图片应更新 img_path"""
    b = Banner(img_path="/static/banner/old.jpg", title="x", create_time="2026-01-01 00:00:00")
    db.session.add(b)
    db.session.commit()
    old_path = b.img_path

    img_buf = _make_image_bytes("PNG")
    rv = login_admin.post(
        f"/banner/edit/{b.id}",
        data={
            "banner_img": (img_buf, "new.png"),
            "title": "x",
            "link_url": "",
            "desc_text": "",
            "sort_num": 0,
        },
        content_type="multipart/form-data",
        follow_redirects=False,
    )
    assert rv.status_code == 302
    db.session.refresh(b)
    assert b.img_path != old_path
    assert b.img_path.startswith("/static/banner/")


def test_banner_edit_not_found(login_admin):
    """编辑不存在的 banner 应重定向"""
    rv = login_admin.post(
        "/banner/edit/99999",
        data={
            "title": "x",
            "link_url": "",
            "desc_text": "",
            "sort_num": 0,
        },
        content_type="multipart/form-data",
        follow_redirects=False,
    )
    assert rv.status_code == 302


def test_banner_del_success(login_admin, db):
    """删除 banner 应从数据库移除"""
    b = Banner(img_path="/static/banner/del.jpg", title="待删", create_time="2026-01-01 00:00:00")
    db.session.add(b)
    db.session.commit()
    bid = b.id

    rv = login_admin.post(f"/banner/del/{bid}", follow_redirects=False)
    assert rv.status_code == 302
    assert db.session.get(Banner, bid) is None


def test_banner_del_not_found(login_admin):
    """删除不存在的 banner 应重定向"""
    rv = login_admin.post("/banner/del/99999", follow_redirects=False)
    assert rv.status_code == 302


def test_banner_add_requires_login(client):
    """未登录不能新增 banner"""
    rv = client.post("/banner/add", follow_redirects=False)
    assert rv.status_code == 302
    assert "/login" in rv.headers.get("Location", "")


def test_banner_withdraw_success(login_admin, db):
    """撤回（下架）后记录保留,is_active=False"""
    b = Banner(
        img_path="/static/banner/a.jpg",
        title="a",
        create_time="2026-01-01 00:00:00",
        is_active=True,
    )
    db.session.add(b)
    db.session.commit()
    bid = b.id

    rv = login_admin.post(f"/banner/withdraw/{bid}", follow_redirects=False)
    assert rv.status_code == 302
    db.session.refresh(b)
    assert b.is_active is False
    # 记录与图片保留,未删除
    assert db.session.get(Banner, bid) is not None


def test_banner_withdraw_twice(login_admin, db):
    """已撤回的 banner 再次撤回应保持 False"""
    b = Banner(
        img_path="/static/banner/a.jpg",
        title="a",
        create_time="2026-01-01 00:00:00",
        is_active=False,
    )
    db.session.add(b)
    db.session.commit()

    rv = login_admin.post(f"/banner/withdraw/{b.id}", follow_redirects=False)
    assert rv.status_code == 302
    db.session.refresh(b)
    assert b.is_active is False


def test_banner_withdraw_not_found(login_admin):
    """撤回不存在的 banner 应重定向"""
    rv = login_admin.post("/banner/withdraw/99999", follow_redirects=False)
    assert rv.status_code == 302


def test_banner_withdraw_requires_login(client):
    """未登录不能撤回 banner"""
    rv = client.post("/banner/withdraw/1", follow_redirects=False)
    assert rv.status_code == 302
    assert "/login" in rv.headers.get("Location", "")


def test_banner_activate_success(login_admin, db):
    """启用（上架）后 is_active=True"""
    b = Banner(
        img_path="/static/banner/b.jpg",
        title="b",
        create_time="2026-01-01 00:00:00",
        is_active=False,
    )
    db.session.add(b)
    db.session.commit()

    rv = login_admin.post(f"/banner/activate/{b.id}", follow_redirects=False)
    assert rv.status_code == 302
    db.session.refresh(b)
    assert b.is_active is True


def test_banner_activate_requires_login(client):
    """未登录不能启用 banner"""
    rv = client.post("/banner/activate/1", follow_redirects=False)
    assert rv.status_code == 302
    assert "/login" in rv.headers.get("Location", "")


def test_homepage_hides_withdrawn_banner(client, db):
    """首页轮播只展示启用中的 banner,已撤回的不出现"""
    on = Banner(
        img_path="/static/banner/on.jpg",
        title="ONBANNER",
        create_time="2026-01-01 00:00:00",
        is_active=True,
    )
    off = Banner(
        img_path="/static/banner/off.jpg",
        title="OFFBANNER",
        create_time="2026-01-02 00:00:00",
        is_active=False,
    )
    db.session.add_all([on, off])
    db.session.commit()

    rv = client.get("/")
    assert rv.status_code == 200
    assert b"ONBANNER" in rv.data
    assert b"OFFBANNER" not in rv.data

