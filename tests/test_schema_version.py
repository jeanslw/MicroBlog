"""schema_version 版本化迁移框架（v1.3.6）。

触发方向:程序 SCHEMA_VERSION **大于** 数据库版本 → 存在待迁移,执行;
数据库版本高于程序（代码被降级）→ 告警并跳过,绝不用旧代码碰新库。
启动初始化与后台「迁移数据库」共用 run_schema_migrations 同一入口。
"""

from app.database import (
    SCHEMA_VERSION,
    get_schema_version,
    pending_schema_migrations,
    run_schema_migrations,
    sync_schema_version,
)
from app.extensions import db
from app.models import SchemaVersion


def _table_exists(name):
    return name in set(db.inspect(db.engine).get_table_names())


def _create_legacy_site_config():
    """造出 v1 旧库形态:site_config 表存在即可（缺列由迁移按默认值兼容）。"""
    with db.engine.begin() as conn:
        conn.execute(db.text("DROP TABLE IF EXISTS site_config"))
        conn.execute(db.text("CREATE TABLE site_config (id INTEGER PRIMARY KEY, site_name VARCHAR(100))"))
        conn.execute(db.text("INSERT INTO site_config (id, site_name) VALUES (1, '旧库站点')"))


def _reset_to_legacy(db):
    """把测试库伪装成 v1 旧库:清掉版本行 + 造出 site_config 旧表。"""
    db.session.query(SchemaVersion).delete()
    db.session.commit()
    _create_legacy_site_config()


def test_fresh_db_is_stamped_current_and_has_no_pending(app, db):
    """全新库（conftest 已跑过迁移）:直接戳当前版本,无待迁移,重复执行幂等。"""
    assert get_schema_version() == SCHEMA_VERSION
    assert pending_schema_migrations() == []
    assert run_schema_migrations() == []


def test_legacy_db_detected_and_migrated_step_by_step(app, db):
    """旧库（site_config 存在、无版本行）→ 推断 v1 → 迁移 v2 应用并逐级戳记。"""
    _reset_to_legacy(db)

    assert sync_schema_version() == 1
    assert [v for v, _ in pending_schema_migrations()] == [2]

    applied = run_schema_migrations()
    assert [v for v, _ in applied] == [2]
    assert not _table_exists("site_config")
    assert get_schema_version() == SCHEMA_VERSION


def test_db_ahead_of_code_is_never_migrated(app, db):
    """数据库版本高于程序（代码被降级）:待迁移恒为空,不执行任何迁移。"""
    row = db.session.get(SchemaVersion, 1)
    row.version = SCHEMA_VERSION + 5
    db.session.commit()

    assert pending_schema_migrations() == []
    assert run_schema_migrations() == []
    assert get_schema_version() == SCHEMA_VERSION + 5


def test_admin_migrate_page_shows_status_and_manual_trigger_runs_migrations(login_admin, db):
    """后台页面:GET 显示状态;POST 与启动共用同一迁移入口,完成后回显最新。"""
    # 已是最新:GET 显示最新提示,POST 提示无需迁移
    html = login_admin.get("/admin/migrate").get_data(as_text=True)
    assert "已是最新" in html
    rv = login_admin.post("/admin/migrate", follow_redirects=False)
    assert rv.status_code == 302

    # 伪装旧库:GET 显示待迁移列表,POST 手动触发后版本推进、旧表消失
    _reset_to_legacy(db)
    html = login_admin.get("/admin/migrate").get_data(as_text=True)
    assert "site_setting" in html  # 待迁移说明文字
    rv = login_admin.post("/admin/migrate", follow_redirects=False)
    assert rv.status_code == 302
    assert get_schema_version() == SCHEMA_VERSION
    assert not _table_exists("site_config")
    html = login_admin.get("/admin/migrate").get_data(as_text=True)
    assert "已是最新" in html
