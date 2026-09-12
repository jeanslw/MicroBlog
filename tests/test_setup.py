"""首次安装引导页（/admin/setup）测试。

无管理员时：所有后台路由跳转引导页；引导页创建账号并自动登录；
已有管理员时：引导页失效跳登录页；多 worker 并发建号竞争不死。
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
    """清空 admin 表，模拟全新部署（conftest 默认已建 admin）。"""
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
        """已有管理员（conftest 默认建号）→ 引导页永久失效。"""
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
        # 密码哈希存储，不落明文
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
        """并发安装：commit 前他人抢先建号 → 引导页优雅退出到登录页，而非 500。"""
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
