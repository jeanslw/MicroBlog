"""首次安装引导页(/admin/setup)测试.

无管理员时:所有后台路由跳转引导页;引导页创建账号并自动登录;
已有管理员时:引导页失效跳登录页;多 worker 并发建号竞争不死.
"""

import pytest

SETUP_DATA = {
    "username": "installer",
    "email": "installer@example.com",
    "password": "strong-pass-123",
    "confirm_password": "strong-pass-123",
}


@pytest.fixture()
def no_admin(app):
    """清空 admin 表,模拟全新部署(conftest 默认已建 admin)."""
    from app.extensions import db
    from app.models import Admin

    db.session.query(Admin).delete()
    db.session.commit()
    return app


@pytest.fixture()
def fresh_client(no_admin):
    return no_admin.test_client()


class TestSetupRedirects:
    def test_login_redirects_to_setup_when_no_admin(self, fresh_client):
        rv = fresh_client.get("/admin/login")
        assert rv.status_code == 302
        assert "/admin/setup" in rv.headers["Location"]

    def test_panel_redirects_to_setup_when_no_admin(self, fresh_client):
        rv = fresh_client.get("/admin/panel")
        assert rv.status_code == 302
        assert "/admin/setup" in rv.headers["Location"]

    def test_setup_page_renders_when_no_admin(self, fresh_client):
        rv = fresh_client.get("/admin/setup")
        assert rv.status_code == 200
        html = rv.get_data(as_text=True)
        assert 'name="username"' in html
        assert 'name="password"' in html

    def test_setup_redirects_to_login_when_admin_exists(self, client):
        """已有管理员(conftest 默认建号)-> 引导页永久失效."""
        rv = client.get("/admin/setup")
        assert rv.status_code == 302
        assert "/admin/login" in rv.headers["Location"]


class TestSetupCreateAdmin:
    def test_create_admin_and_auto_login(self, fresh_client, no_admin):
        rv = fresh_client.post("/admin/setup", data=SETUP_DATA, follow_redirects=True)
        assert rv.status_code == 200
        assert rv.request.path == "/admin/panel"

        from app.extensions import db
        from app.models import Admin

        admin = db.session.scalar(db.select(Admin).filter_by(username="installer"))
        assert admin is not None
        assert admin.email == "installer@example.com"
        # 密码哈希存储,不落明文
        assert admin.password != SETUP_DATA["password"]

    def test_password_mismatch_rejected(self, fresh_client, no_admin):
        data = dict(SETUP_DATA, confirm_password="different")
        rv = fresh_client.post("/admin/setup", data=data)
        assert rv.status_code == 200  # 表单页回显错误

        from app.extensions import db
        from app.models import Admin

        assert not db.session.scalar(db.select(db.func.count(Admin.id)))

    def test_short_password_rejected(self, fresh_client, no_admin):
        data = dict(SETUP_DATA, password="123", confirm_password="123")
        rv = fresh_client.post("/admin/setup", data=data)
        assert rv.status_code == 200

        from app.extensions import db
        from app.models import Admin

        assert not db.session.scalar(db.select(db.func.count(Admin.id)))


class TestSetupRace:
    def test_admin_created_by_other_process(self, fresh_client, no_admin, monkeypatch):
        """并发安装:commit 前他人抢先建号 -> 引导页优雅退出到登录页,而非 500."""
        from sqlalchemy.exc import IntegrityError

        from app.extensions import db
        from app.models import Admin

        real_commit = db.session.commit
        raced = {"done": False}

        def racing_commit():
            if not raced["done"]:
                raced["done"] = True
                # 模拟另一进程先一步提交
                db.session.add(Admin(username="winner", password="x"))
                real_commit()
                raise IntegrityError("INSERT INTO admin", {}, Exception("UNIQUE constraint failed"))
            return real_commit()

        monkeypatch.setattr(db.session, "commit", racing_commit)

        rv = fresh_client.post("/admin/setup", data=SETUP_DATA, follow_redirects=False)
        assert rv.status_code == 302
        assert "/admin/login" in rv.headers["Location"]

    def test_lock_recheck_rejects_concurrent_creation(self, fresh_client, no_admin, monkeypatch):
        """锁内复查:入口检查通过后另一进程用不同用户名建号 -> 只保留一个管理员"""
        from sqlalchemy.orm import Session

        from app.extensions import db
        from app.models import Admin

        real_scalar = Session.scalar
        calls = {"n": 0}

        def racing_scalar(self, statement, *args, **kwargs):
            calls["n"] += 1
            if calls["n"] == 1:
                return 0
            return real_scalar(self, statement, *args, **kwargs)

        monkeypatch.setattr(Session, "scalar", racing_scalar)
        db.session.add(Admin(username="winner", password="x"))
        db.session.commit()

        rv = fresh_client.post("/admin/setup", data=SETUP_DATA, follow_redirects=False)
        assert rv.status_code == 302
        assert "/admin/login" in rv.headers["Location"]
        assert db.session.scalar(db.select(db.func.count(Admin.id))) == 1


class TestSetupTokenGate:
    def test_production_without_token_disables_setup(self, fresh_client, no_admin):
        """生产环境未配置初始化令牌时,网页安装被禁用,返回 403 信息页而非重定向(避免死循环)"""
        no_admin.config["IS_PRODUCTION"] = True
        no_admin.config["SETUP_TOKEN"] = ""
        try:
            for method, url in (
                (fresh_client.get, "/admin/setup"),
                (fresh_client.post, "/admin/setup"),
            ):
                rv = method(url, follow_redirects=False)
                assert rv.status_code == 403
                assert b"create-admin" in rv.data

            from app.extensions import db
            from app.models import Admin

            assert db.session.scalar(db.select(db.func.count(Admin.id))) == 0
        finally:
            no_admin.config["IS_PRODUCTION"] = False

    def test_production_with_wrong_token_rejected(self, fresh_client, no_admin):
        """生产环境令牌不匹配时拒绝访问,且不得重定向(与 _require_setup 成环)"""
        no_admin.config["IS_PRODUCTION"] = True
        no_admin.config["SETUP_TOKEN"] = "real-token"
        try:
            for url in ("/admin/setup", "/admin/setup?setup_token=wrong-token"):
                rv = fresh_client.get(url, follow_redirects=False)
                assert rv.status_code == 403
                assert b"BLOG_SETUP_TOKEN" in rv.data

            from app.extensions import db
            from app.models import Admin

            assert db.session.scalar(db.select(db.func.count(Admin.id))) == 0
        finally:
            no_admin.config["IS_PRODUCTION"] = False

    def test_non_ascii_token_does_not_crash(self, fresh_client, no_admin):
        """令牌含非 ASCII 字符时不得因 compare_digest 抛 TypeError"""
        no_admin.config["IS_PRODUCTION"] = True
        no_admin.config["SETUP_TOKEN"] = "令牌-token"
        try:
            rv = fresh_client.get("/admin/setup?setup_token=令牌-token", follow_redirects=False)
            assert rv.status_code == 200, "非 ASCII 令牌匹配时应正常渲染安装页"

            rv = fresh_client.get("/admin/setup?setup_token=另一个", follow_redirects=False)
            assert rv.status_code == 403, "不匹配时返回 403"
        finally:
            no_admin.config["IS_PRODUCTION"] = False

    def test_production_with_valid_token_allows_setup(self, fresh_client, no_admin):
        """生产环境携带正确令牌可完成安装"""
        no_admin.config["IS_PRODUCTION"] = True
        no_admin.config["SETUP_TOKEN"] = "real-token"
        try:
            rv = fresh_client.get("/admin/setup?setup_token=real-token", follow_redirects=False)
            assert rv.status_code == 200

            rv = fresh_client.post(
                "/admin/setup", data=dict(SETUP_DATA, setup_token="real-token"), follow_redirects=False
            )
            assert rv.status_code == 302

            from app.extensions import db
            from app.models import Admin

            assert db.session.scalar(db.select(Admin).filter_by(username="installer")) is not None
        finally:
            no_admin.config["IS_PRODUCTION"] = False

    def test_development_without_token_still_works(self, fresh_client, no_admin):
        """开发/测试环境不要求令牌"""
        assert no_admin.config["IS_PRODUCTION"] is False
        rv = fresh_client.get("/admin/setup", follow_redirects=False)
        assert rv.status_code == 200
