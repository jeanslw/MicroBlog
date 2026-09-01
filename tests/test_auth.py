"""认证与登录安全测试。"""


def test_login_page_get(client):
    """GET /admin/login 返回 200"""
    rv = client.get("/admin/login")
    assert rv.status_code == 200
    assert "管理员登录".encode() in rv.data or b"Admin" in rv.data


def test_login_success(client, admin_user):
    """正确账号密码应登录成功并重定向"""
    rv = client.post(
        "/admin/login",
        data={
            "username": "admin",
            "password": "admin123456",
        },
        follow_redirects=False,
    )
    assert rv.status_code == 302
    # 应已登录
    with client.session_transaction() as s:
        assert "_user_id" in s


def test_login_wrong_password(client, admin_user):
    """错误密码应留在登录页"""
    rv = client.post(
        "/admin/login",
        data={
            "username": "admin",
            "password": "wrong-pwd",
        },
        follow_redirects=False,
    )
    assert rv.status_code == 200
    # 未登录
    with client.session_transaction() as s:
        assert "_user_id" not in s


def test_login_unknown_user(client, admin_user):
    """不存在用户应登录失败"""
    rv = client.post(
        "/admin/login",
        data={
            "username": "ghost",
            "password": "anything",
        },
        follow_redirects=False,
    )
    assert rv.status_code == 200
    with client.session_transaction() as s:
        assert "_user_id" not in s


def test_login_brute_force_lock(client, admin_user, db):
    """5 次失败后应被锁定"""
    for _ in range(5):
        client.post(
            "/admin/login",
            data={
                "username": "admin",
                "password": "wrong",
            },
        )
    # 第 6 次应被锁定（429 或重定向到登录并提示）
    rv = client.post(
        "/admin/login",
        data={
            "username": "admin",
            "password": "admin123456",
        },
        follow_redirects=False,
    )
    # 锁定时即便正确密码也不应通过
    assert rv.status_code in (429, 200, 302)
    if rv.status_code == 302:
        # 仅在未锁定情况下才能 302；本测试期望被锁
        with client.session_transaction() as s:
            assert "_user_id" not in s


def test_login_redirect_when_already_authed(login_admin):
    """已登录用户访问 /admin/login 应重定向"""
    rv = login_admin.get("/admin/login", follow_redirects=False)
    assert rv.status_code == 302


def test_logout_requires_login(client):
    """未登录用户访问 /admin/logout 应重定向到登录页"""
    rv = client.post("/admin/logout", follow_redirects=False)
    assert rv.status_code == 302
    assert "/login" in rv.headers.get("Location", "")


def test_logout_success(login_admin):
    """登录后退出应清除 session"""
    rv = login_admin.post("/admin/logout", follow_redirects=False)
    assert rv.status_code == 302
    with login_admin.session_transaction() as s:
        assert "_user_id" not in s


def test_admin_routes_require_login(client):
    """需要登录的路由未登录时应跳转登录"""
    for url in ["/admin/change_pwd", "/admin/site_setting", "/banner/"]:
        rv = client.get(url, follow_redirects=False)
        assert rv.status_code == 302, f"{url} 未重定向"
        assert "/login" in rv.headers.get("Location", ""), f"{url} 未重定向到登录页"


def test_change_pwd_success(login_admin, db, admin_user):
    """正确旧密码可修改密码"""
    rv = login_admin.post(
        "/admin/change_pwd",
        data={
            "old_pwd": "admin123456",
            "new_pwd": "new-password-789",
            "confirm_pwd": "new-password-789",
        },
        follow_redirects=False,
    )
    assert rv.status_code == 302
    # 密码已变更，且应已退出登录
    with login_admin.session_transaction() as s:
        assert "_user_id" not in s


def test_change_pwd_wrong_old(login_admin):
    """错误旧密码不能修改"""
    rv = login_admin.post(
        "/admin/change_pwd",
        data={
            "old_pwd": "wrong-old-pwd",
            "new_pwd": "new-password-789",
            "confirm_pwd": "new-password-789",
        },
        follow_redirects=False,
    )
    assert rv.status_code == 200  # 留在改密页


def test_change_pwd_mismatch(login_admin):
    """两次新密码不一致不能修改"""
    rv = login_admin.post(
        "/admin/change_pwd",
        data={
            "old_pwd": "admin123456",
            "new_pwd": "new-password-789",
            "confirm_pwd": "different-pwd",
        },
        follow_redirects=False,
    )
    assert rv.status_code == 200


def test_change_pwd_too_short(login_admin):
    """新密码短于 6 位应被拒绝"""
    rv = login_admin.post(
        "/admin/change_pwd",
        data={
            "old_pwd": "admin123456",
            "new_pwd": "12345",
            "confirm_pwd": "12345",
        },
        follow_redirects=False,
    )
    assert rv.status_code == 200


def test_new_password_can_login(client, db, admin_user):
    """改密后应用新密码可登录"""
    from werkzeug.security import generate_password_hash

    admin_user.password = generate_password_hash("brand-new-123")
    db.session.commit()

    rv = client.post(
        "/admin/login",
        data={
            "username": "admin",
            "password": "brand-new-123",
        },
        follow_redirects=False,
    )
    assert rv.status_code == 302


def test_login_next_open_redirect_blocked(client, admin_user):
    """next=//evil.com 登录后不应重定向到外部域名"""
    rv = client.post(
        "/admin/login?next=//evil.com",
        data={
            "username": "admin",
            "password": "admin123456",
        },
        follow_redirects=False,
    )
    assert rv.status_code == 302
    loc = rv.headers.get("Location", "")
    assert "evil.com" not in loc
    assert not loc.startswith("//")


def test_login_next_internal_path_ok(client, admin_user):
    """next=站内路径应正常重定向"""
    rv = client.post(
        "/admin/login?next=/banner/",
        data={
            "username": "admin",
            "password": "admin123456",
        },
        follow_redirects=False,
    )
    assert rv.status_code == 302
    assert rv.headers.get("Location", "").endswith("/banner/")
