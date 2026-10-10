"""schema_version 版本化迁移框架（v1.3.6）。

schema 版本一律用真实发布号（如 1.3.6）,不用 1、2 这类内部序号——日志和
后台页面所见即发布版本。触发方向:程序 SCHEMA_VERSION **大于** 数据库
版本 → 存在待迁移,执行;数据库版本高于程序（代码被降级）→ 告警并跳过,
绝不用旧代码碰新库。启动初始化与后台「迁移数据库」共用
run_schema_migrations 同一入口。
"""

from app.database import (
    SCHEMA_VERSION,
    SCHEMA_VERSION_BASELINE,
    get_schema_version,
    pending_schema_migrations,
    run_schema_migrations,
    schema_version_cmp,
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
    """旧库（site_config 存在、无版本行）→ 推断为单表时代基线 → 迁移应用并戳记。"""
    _reset_to_legacy(db)

    assert sync_schema_version() == SCHEMA_VERSION_BASELINE
    assert [v for v, _ in pending_schema_migrations()] == ["1.3.6"]

    applied = run_schema_migrations()
    assert [v for v, _ in applied] == ["1.3.6"]
    assert not _table_exists("site_config")
    assert get_schema_version() == SCHEMA_VERSION


def test_db_ahead_of_code_is_never_migrated(app, db):
    """数据库版本高于程序（代码被降级）:待迁移恒为空,不执行任何迁移。"""
    row = db.session.get(SchemaVersion, 1)
    row.version = "99.0.0"  # 远高于任何当前发布号
    db.session.commit()

    assert pending_schema_migrations() == []
    assert run_schema_migrations() == []
    assert get_schema_version() == "99.0.0"


def test_release_version_comparison():
    """发布号比较:语义化比较而非字典序（"1.3.10" > "1.3.6" 是关键分歧点）。"""
    assert schema_version_cmp("1.3.10", "1.3.6") > 0  # 字典序会给出错误结论
    assert schema_version_cmp("1.3.6", SCHEMA_VERSION) == 0
    assert schema_version_cmp("1.3.5", "1.3.6") < 0
    assert schema_version_cmp("v1.3.6", "1.3.6") == 0  # 容忍 v 前缀
    assert schema_version_cmp("1.3", "1.3.0") == 0  # 段数不足按 0 补齐
    assert schema_version_cmp("2.0.0", "1.3.6") > 0


def test_legacy_int_stamp_is_normalized_to_release_version(app, db):
    """本框架开发期曾短暂用过整数序号（未发布）:老开发库的整数行映射为发布号。

    正式环境遇不到;这层兼容只为开发机上的旧库不报错、可继续迁移。
    """
    row = db.session.get(SchemaVersion, 1)
    row.version = 2  # SQLite  VARCHAR 列可存整数,读回 int 2
    db.session.commit()
    db.session.expire_all()

    assert get_schema_version() == "1.3.6"
    assert pending_schema_migrations() == []  # 已等价于当前版本,无待迁移


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
