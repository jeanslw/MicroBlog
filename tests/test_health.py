"""/healthz 健康探针测试。"""

from unittest.mock import patch

from sqlalchemy.exc import OperationalError


def test_healthz_ok(client):
    """数据库正常时返回 200 + status=ok"""
    rv = client.get("/healthz")
    assert rv.status_code == 200
    assert rv.get_json() == {"status": "ok"}


def test_healthz_exempt_from_trusted_hosts(app, client):
    """配置 Host 白名单后：普通路径非白名单 Host 返回 400，/healthz 仍放行。

    容器内探针 Host 为 127.0.0.1:5000，无法预知，必须豁免白名单校验。
    """
    app.config["HOST_WHITELIST"] = ["example.com"]
    try:
        # test_client 默认 Host 为 localhost，不在白名单
        blocked = client.get("/robots.txt")
        assert blocked.status_code == 400
        # 健康探针不受白名单影响
        probe = client.get("/healthz")
        assert probe.status_code == 200
    finally:
        app.config["HOST_WHITELIST"] = []


def test_healthz_503_when_db_unavailable(client):
    """数据库查询失败时返回 503，便于编排识别异常实例"""
    err = OperationalError("SELECT 1", {}, Exception("connection refused"))
    with patch("sqlalchemy.orm.Session.execute", side_effect=err):
        rv = client.get("/healthz")
    assert rv.status_code == 503
    assert rv.get_json() == {"status": "db unavailable"}


def test_wait_for_database_retries_until_ready(app, monkeypatch):
    """MySQL 启动就绪前应有限重试，探测成功后正常返回（SQLite 不等待）。"""
    import time

    from app.database import wait_for_database
    from app.extensions import db

    # 伪装为 mysql 引擎（SQLite 分支会直接返回，无需等待）
    monkeypatch.setattr(db.engine.dialect, "name", "mysql")
    monkeypatch.setattr(time, "sleep", lambda *_: None)

    attempts = {"n": 0}

    def flaky_execute(self, statement, *args, **kwargs):
        attempts["n"] += 1
        if attempts["n"] < 3:
            raise OperationalError("SELECT 1", {}, Exception("not ready yet"))
        # 走底层连接真正执行，绕过被替换的 Session.execute，避免代理递归
        from sqlalchemy import text as _text

        return self.connection().execute(_text("SELECT 1"))

    with patch("sqlalchemy.orm.Session.execute", flaky_execute):
        wait_for_database(max_wait=90, interval=0.01)
    assert attempts["n"] == 3


def test_wait_for_database_skips_sqlite(app):
    """SQLite 引擎不进入等待循环，立即返回。"""
    from app.database import wait_for_database
    from app.extensions import db

    assert db.engine.dialect.name == "sqlite"
    wait_for_database(max_wait=1)  # 不应阻塞或报错
