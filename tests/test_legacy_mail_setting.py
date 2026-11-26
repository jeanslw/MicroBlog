"""遗留 mail_setting 表删除守卫回归.

读取、复制、回读校验任一步失败都必须保留旧表,避免 SMTP 历史配置不可逆丢失.
"""

from types import SimpleNamespace

from sqlalchemy import text

from app.database import _drop_legacy_mail_setting
from app.extensions import db

_LEGACY_COLUMNS = (
    "id INTEGER PRIMARY KEY, "
    "mail_host VARCHAR(200), mail_port INTEGER, mail_user VARCHAR(200), "
    "mail_password VARCHAR(200), mail_from VARCHAR(200), "
    "mail_use_ssl INTEGER, mail_use_tls INTEGER"
)


def _create_legacy_table(db):
    with db.engine.begin() as conn:
        conn.execute(text(f"CREATE TABLE mail_setting ({_LEGACY_COLUMNS})"))


def _insert_legacy_row(db, mail_host="smtp.old.com"):
    with db.engine.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO mail_setting "
                "(mail_host, mail_port, mail_user, mail_password, mail_from, mail_use_ssl, mail_use_tls) "
                "VALUES (:h, 465, 'old-user', 'old-pass', 'old@from.com', 1, 0)"
            ),
            {"h": mail_host},
        )


def _legacy_table_exists() -> bool:
    return db.inspect(db.engine).has_table("mail_setting")


def test_unreadable_legacy_table_is_kept(app, db):
    with db.engine.begin() as conn:
        conn.execute(text("CREATE TABLE mail_setting (foo VARCHAR(10))"))

    _drop_legacy_mail_setting()

    assert _legacy_table_exists(), "旧表结构不可读时必须保留旧表"


def test_copy_failure_keeps_legacy_table(app, db, monkeypatch):
    _create_legacy_table(db)
    _insert_legacy_row(db)
    from app import database

    def boom():
        raise RuntimeError("copy failed")

    monkeypatch.setattr(database, "get_or_create_system_setting", boom)

    _drop_legacy_mail_setting()

    assert _legacy_table_exists(), "复制失败必须保留旧表"
    with db.engine.connect() as conn:
        row = conn.execute(text("SELECT mail_host FROM mail_setting")).scalar()
        assert row == "smtp.old.com", "旧表数据必须原样保留"
    assert not db.session.execute(text("SELECT mail_host FROM system_settings")).scalar(), "目标配置不得被半写"


def test_verify_mismatch_keeps_legacy_table(app, db, monkeypatch):
    _create_legacy_table(db)
    _insert_legacy_row(db)
    from app import database

    fake = SimpleNamespace(
        mail_host="unexpected.host",
        mail_port=587,
        mail_user="",
        mail_password="",
        mail_from="",
        mail_use_ssl=False,
        mail_use_tls=True,
    )
    monkeypatch.setattr(database, "get_system_setting", lambda: fake)

    _drop_legacy_mail_setting()

    assert _legacy_table_exists(), "回读校验不一致必须保留旧表"


def test_empty_legacy_table_is_dropped(app, db):
    _create_legacy_table(db)

    _drop_legacy_mail_setting()

    assert not _legacy_table_exists(), "空旧表无数据可丢,应正常清理"
