"""schema_version 版本化迁移框架（v1.3.6）。

schema 版本一律用真实发布号（如 1.3.6）,不用 1、2 这类内部序号——日志和
后台页面所见即发布版本。触发方向:程序 SCHEMA_VERSION **大于** 数据库
版本 → 存在待迁移,执行;数据库版本高于程序（代码被降级）→ 告警并跳过,
绝不用旧代码碰新库。启动初始化与后台「迁移数据库」共用
run_schema_migrations 同一入口。

版本戳记为履历表:每应用一级迁移追一行（version 主键 + applied_time +
note）,「数据库当前版本」= 履历里语义化最高的一行。
"""

import re

from app import run_startup_schema_migrations
from app.database import (
    SCHEMA_VERSION,
    SCHEMA_VERSION_BASELINE,
    _migrate_schema_version,
    get_schema_version,
    pending_schema_migrations,
    run_schema_migrations,
    schema_version_cmp,
    sync_schema_version,
)
from app.extensions import db
from app.models import SchemaVersion

TS_RE = re.compile(r"^\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}$")


def _table_exists(name):
    return name in set(db.inspect(db.engine).get_table_names())


def _create_legacy_site_config():
    """造出 v1 旧库形态:site_config 表存在即可（缺列由迁移按默认值兼容）。"""
    with db.engine.begin() as conn:
        conn.execute(db.text("DROP TABLE IF EXISTS site_config"))
        conn.execute(db.text("CREATE TABLE site_config (id INTEGER PRIMARY KEY, site_name VARCHAR(100))"))
        conn.execute(db.text("INSERT INTO site_config (id, site_name) VALUES (1, '旧库站点')"))


def _reset_to_legacy():
    """把测试库伪装成 v1 旧库:清掉版本履历 + 造出 site_config 旧表。"""
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
    _reset_to_legacy()

    assert sync_schema_version() == SCHEMA_VERSION_BASELINE
    assert [v for v, _ in pending_schema_migrations()] == ["1.3.6"]

    applied = run_schema_migrations()
    assert [v for v, _ in applied] == ["1.3.6"]
    assert not _table_exists("site_config")
    assert get_schema_version() == SCHEMA_VERSION


def test_history_table_records_one_row_per_version(app, db):
    """履历表:基线推断 + 迁移各追一行,含应用时间与迁移说明;同版本不重复追行。"""
    _reset_to_legacy()
    sync_schema_version()  # 推断基线 → 追一行 1.3.5
    run_schema_migrations()  # 应用 1.3.6 → 再追一行

    rows = db.session.scalars(db.select(SchemaVersion).order_by(SchemaVersion.version)).all()
    assert [r.version for r in rows] == [SCHEMA_VERSION_BASELINE, SCHEMA_VERSION]
    baseline, applied = rows
    assert TS_RE.match(baseline.applied_time)
    assert "推断" in baseline.note
    assert TS_RE.match(applied.applied_time)
    assert "site_config" in applied.note  # 说明来自迁移登记表

    # 幂等:同一版本再戳一次只刷新那一行,不新增
    run_schema_migrations()
    versions = db.session.scalars(db.select(SchemaVersion.version)).all()
    assert sorted(versions) == [SCHEMA_VERSION_BASELINE, SCHEMA_VERSION]


def test_db_ahead_of_code_is_never_migrated(app, db, caplog):
    """数据库版本高于程序（代码被降级）:待迁移恒为空,不执行任何迁移。"""
    db.session.add(SchemaVersion(version="99.0.0", applied_time="2026-01-01 00:00:00"))
    db.session.commit()

    assert pending_schema_migrations() == []
    assert run_schema_migrations() == []
    assert get_schema_version() == "99.0.0"

    # quiet=True 抑制「请先升级程序」告警（维护闸门每请求重查,避免刷屏）
    with caplog.at_level("WARNING", logger="blog"):
        caplog.clear()
        pending_schema_migrations(quiet=False)
        assert any("高于程序版本" in r.message for r in caplog.records)
        caplog.clear()
        pending_schema_migrations(quiet=True)
        assert caplog.records == []


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
    db.session.add(SchemaVersion(version="2", applied_time="2026-01-01 00:00:00"))
    db.session.commit()

    assert get_schema_version() == "1.3.6"
    assert pending_schema_migrations() == []  # 已等价于当前版本,无待迁移


def test_v1_single_row_table_is_rebuilt_into_history(app, db):
    """开发期单行结构（id 主键）→ 履历表（version 主键）重建,保留最新戳记。"""
    db.session.query(SchemaVersion).delete()
    db.session.commit()
    with db.engine.begin() as conn:
        conn.execute(db.text("DROP TABLE schema_version"))
        conn.execute(
            db.text(
                "CREATE TABLE schema_version (id INTEGER PRIMARY KEY, version VARCHAR(20), applied_time VARCHAR(50))"
            )
        )
        conn.execute(db.text("INSERT INTO schema_version (id, version, applied_time) VALUES (1, '1.3.5', '')"))
        conn.execute(db.text("INSERT INTO schema_version (id, version, applied_time) VALUES (2, '2', '')"))

    _migrate_schema_version()

    cols = {c["name"] for c in db.inspect(db.engine).get_columns("schema_version")}
    assert cols == {"version", "applied_time", "note"}
    assert not _table_exists("schema_version_v1_legacy")
    assert get_schema_version() == "1.3.6"  # 整数 2 → 发布号 1.3.6


def test_startup_auto_mode_applies_migrations(app, db):
    """默认（BLOG_AUTO_MIGRATE=true）:启动步骤直接执行迁移,不置维护标志。"""
    _reset_to_legacy()

    run_startup_schema_migrations(app)

    assert app.config.get("SCHEMA_UPGRADE_PENDING") is None
    assert get_schema_version() == SCHEMA_VERSION
    assert not _table_exists("site_config")


def test_startup_manual_mode_leaves_db_untouched_and_flags_maintenance(app, db):
    """手动模式:启动只读不动库,置维护标志（等管理员在后台手动执行）。"""
    _reset_to_legacy()
    app.config["AUTO_SCHEMA_MIGRATE"] = False

    run_startup_schema_migrations(app)

    assert app.config["SCHEMA_UPGRADE_PENDING"] is True
    assert _table_exists("site_config")  # 库未被改动
    assert sync_schema_version() == SCHEMA_VERSION_BASELINE


def test_startup_step_never_blocks_startup_on_error(app, db, monkeypatch):
    """启动步骤遇异常只告警:数据库暂时不可用不应让整个应用起不来。"""
    import app.database as database_module

    def boom(*args, **kwargs):
        raise RuntimeError("db 不可用")

    monkeypatch.setattr(database_module, "run_schema_migrations", boom)
    run_startup_schema_migrations(app)  # 不抛异常
    assert app.config.get("SCHEMA_UPGRADE_PENDING") is None


def test_gate_blocks_site_and_allows_login_paths(client, app, db):
    """维护闸门:普通页面 503 且渲染独立升级页;登录/静态资源照常放行。"""
    _reset_to_legacy()
    app.config["SCHEMA_UPGRADE_PENDING"] = True

    rv = client.get("/")
    assert rv.status_code == 503
    html = rv.get_data(as_text=True)
    assert "站点维护中" in html
    assert "1.3.6" in html  # 目标版本
    assert _table_exists("site_config")  # 被拦下来的请求没动库

    assert client.get("/admin/login").status_code == 200
    assert client.get("/static/css/themes.css").status_code == 200


def test_gate_self_clears_when_migration_completed_elsewhere(login_admin, app, db):
    """自恢复:另一 worker/CLI 完成迁移后,闸门下次请求自动解除（无需重启）。"""
    _reset_to_legacy()
    app.config["SCHEMA_UPGRADE_PENDING"] = True
    assert login_admin.get("/").status_code == 503

    run_schema_migrations()  # 模拟另一进程完成迁移
    rv = login_admin.get("/")
    assert rv.status_code == 200
    assert app.config["SCHEMA_UPGRADE_PENDING"] is False


def test_manual_migration_from_admin_page_clears_gate(login_admin, app, db):
    """手动模式全流程:登录（放行）→ 迁移页放行 → 执行迁移 → 站点恢复。"""
    _reset_to_legacy()
    app.config["SCHEMA_UPGRADE_PENDING"] = True

    assert login_admin.get("/admin/migrate").status_code == 200
    rv = login_admin.post("/admin/migrate", follow_redirects=False)
    assert rv.status_code == 302
    assert get_schema_version() == SCHEMA_VERSION
    assert not _table_exists("site_config")
    assert login_admin.get("/").status_code == 200


def test_admin_migrate_page_shows_status_history_and_manual_mode(login_admin, app, db):
    """后台页面:状态卡片、迁移履历、手动模式标识与待迁移列表。"""
    # 已是最新:显示最新提示 + 履历（至少一行当前版本）
    html = login_admin.get("/admin/migrate").get_data(as_text=True)
    assert "已是最新" in html
    assert "迁移履历" in html
    assert SCHEMA_VERSION in html
    rv = login_admin.post("/admin/migrate", follow_redirects=False)
    assert rv.status_code == 302

    # 手动模式标识
    app.config["AUTO_SCHEMA_MIGRATE"] = False
    html = login_admin.get("/admin/migrate").get_data(as_text=True)
    assert "手动模式" in html

    # 伪装旧库:显示待迁移列表,POST 手动触发后版本推进、旧表消失
    app.config["AUTO_SCHEMA_MIGRATE"] = True
    _reset_to_legacy()
    html = login_admin.get("/admin/migrate").get_data(as_text=True)
    assert "site_setting" in html  # 待迁移说明文字
    rv = login_admin.post("/admin/migrate", follow_redirects=False)
    assert rv.status_code == 302
    assert get_schema_version() == SCHEMA_VERSION
    assert not _table_exists("site_config")
    html = login_admin.get("/admin/migrate").get_data(as_text=True)
    assert "已是最新" in html


def test_admin_backup_page_renders_with_history_table(login_admin):
    """回归:履历表结构下备份页的 mysqldump/mysql 分支仍可渲染。"""
    rv = login_admin.get("/admin/backup")
    assert rv.status_code == 200


def test_banner_withdraw_and_activate_stamp_update_time(login_admin, db):
    """banner.update_time:撤回/重新启用各自刷新（撤回后它就是「撤回时间」）。"""
    from app.models import Banner

    banner = Banner(img_path="/uploads/banner/x.jpg", title="轮播A", create_time="2026-01-01 00:00:00")
    db.session.add(banner)
    db.session.commit()

    rv = login_admin.post(f"/banner/withdraw/{banner.id}", follow_redirects=False)
    assert rv.status_code == 302
    db.session.refresh(banner)
    assert banner.is_active is False
    assert TS_RE.match(banner.update_time or "")

    rv = login_admin.post(f"/banner/activate/{banner.id}", follow_redirects=False)
    assert rv.status_code == 302
    db.session.refresh(banner)
    assert banner.is_active is True
    assert TS_RE.match(banner.update_time or "")

    html = login_admin.get("/banner/").get_data(as_text=True)
    assert "最近变更" in html


def test_login_attempt_stamps_update_time(client, db):
    """login_attempt.update_time:登录失败时刷新（v1.3.6 起该列随失败写入）。"""
    from app.models import LoginAttempt

    rv = client.post("/admin/login", data={"username": "admin", "password": "wrong-password"}, follow_redirects=False)
    assert rv.status_code == 200  # 验证失败,原地重渲染登录页
    rec = db.session.scalar(db.select(LoginAttempt).filter_by(username="admin"))
    assert rec is not None and rec.fail_count >= 1
    assert TS_RE.match(rec.update_time or "")


def test_account_page_shows_login_failures(login_admin, db):
    """账户安全页展示登录失败记录（IP / 账号 / 次数 / 最近失败时间 / 锁定状态）。"""
    from app.extensions import record_login_fail

    record_login_fail("10.0.0.9", "admin")
    html = login_admin.get("/admin/account").get_data(as_text=True)
    assert "登录失败记录" in html
    assert "10.0.0.9" in html
    assert "最近失败时间" in html
