"""site_config 拆分迁移与三张单行配置表的读写一致性（v1.3.6）。

v1.3.5 及以前全站配置挤在单行表 site_config（20 列）。v1.3.6 按语义拆为
site_setting / mail_setting / about_profile 三张单行表：

- 拆分迁移（database._migrate_site_config_split）：旧库升级、恢复旧备份
  （SQLite 文件替换 / MySQL dump 导入把库变回旧 schema）时启动自动执行；
  复制并校验行数通过后才 DROP 旧表，失败则旧表原样保留、下次启动重试；
- 三张表读写统一走 database.get_site_setting / get_mail_setting /
  get_about_profile（+ get_or_create_*），「唯一一行 id≠1」的历史库兼容
  （v1.3.5 修复的坑）在拆表后继续成立。
"""

from app.database import (
    _migrate_site_config_split,
    get_about_profile,
    get_mail_setting,
    get_or_create_about_profile,
    get_or_create_mail_setting,
    get_or_create_site_setting,
    get_site_setting,
)
from app.extensions import db, fetch_global_context
from app.models import AboutProfile, MailSetting, SiteSetting

# v1.3.5 时代的完整 site_config 建表 DDL（迁移测试用它模拟旧库）
_LEGACY_DDL = """
CREATE TABLE site_config (
    id INTEGER NOT NULL PRIMARY KEY,
    site_name VARCHAR(100) DEFAULT 'My Blog',
    favicon_path VARCHAR(200) DEFAULT 'static/favicon.ico',
    logo_path VARCHAR(200) DEFAULT '',
    bg_style VARCHAR(50) DEFAULT 'bg1',
    bg_custom VARCHAR(500) DEFAULT '',
    about_avatar VARCHAR(500) DEFAULT '',
    about_bio TEXT,
    about_email VARCHAR(200) DEFAULT '',
    about_github VARCHAR(200) DEFAULT '',
    about_homepage VARCHAR(200) DEFAULT '',
    about_nickname VARCHAR(100) DEFAULT '',
    mail_host VARCHAR(200) DEFAULT '',
    mail_port INTEGER DEFAULT 587,
    mail_user VARCHAR(200) DEFAULT '',
    mail_password VARCHAR(200) DEFAULT '',
    mail_from VARCHAR(200) DEFAULT '',
    mail_use_ssl BOOLEAN DEFAULT 0,
    mail_use_tls BOOLEAN DEFAULT 1,
    comments_enabled BOOLEAN DEFAULT 1,
    sidebar_style VARCHAR(20) DEFAULT 'book'
)
"""

_LEGACY_INSERT = """
INSERT INTO site_config
    (id, site_name, favicon_path, logo_path, bg_style, bg_custom, about_nickname,
     about_bio, about_email, mail_host, mail_port, mail_user, mail_password,
     mail_from, mail_use_ssl, mail_use_tls, comments_enabled, sidebar_style)
VALUES
    (42, '迁移前站点', 'static/favicon.ico', '', 'bg7', '', '迁移前昵称',
     '迁移前简介', 'old@x.com', 'smtp.old.com', 465, 'olduser', 'oldpass',
     'from@old.com', 1, 0, 0, 'classic')
"""


def _table_exists(name):
    return name in set(db.inspect(db.engine).get_table_names())


def _create_legacy_site_config():
    """手工建出旧版 site_config 表（ORM 已无该模型,直接 DDL）并插入一行数据。"""
    with db.engine.begin() as conn:
        conn.execute(db.text("DROP TABLE IF EXISTS site_config"))
        conn.execute(db.text(_LEGACY_DDL))
        conn.execute(db.text(_LEGACY_INSERT))


# ── 拆分迁移 ──────────────────────────────────────────────
def test_split_migration_copies_data_and_drops_legacy_table(app, db):
    _create_legacy_site_config()

    _migrate_site_config_split()

    # 旧表已删除
    assert not _table_exists("site_config")
    # 站点设置：值来自旧行
    site = get_site_setting()
    assert site.id == 1
    assert site.site_name == "迁移前站点"
    assert site.bg_style == "bg7"
    assert site.comments_enabled is False
    assert site.sidebar_style == "classic"
    # 邮件设置：值来自旧行
    mail = get_mail_setting()
    assert mail.mail_host == "smtp.old.com"
    assert mail.mail_port == 465
    assert mail.mail_use_ssl is True
    assert mail.mail_use_tls is False
    # 关于我：值来自旧行
    about = get_about_profile()
    assert about.about_nickname == "迁移前昵称"
    assert about.about_bio == "迁移前简介"
    # 三张新表各恰好一行
    for model in (SiteSetting, MailSetting, AboutProfile):
        assert db.session.scalar(db.select(db.func.count(model.id))) == 1


def test_split_migration_is_idempotent(app, db):
    _create_legacy_site_config()
    _migrate_site_config_split()
    # 第二次运行（旧表已不存在）应静默跳过,不报错不改动
    _migrate_site_config_split()
    assert get_site_setting().site_name == "迁移前站点"


def test_split_migration_overwrites_stale_rows_on_old_backup_restore(app, db):
    """恢复旧备份场景：旧表出现时它就是权威状态,新表残留的旧数据必须被覆盖。"""
    # 新表先被应用改成与旧行不同的值（模拟恢复前的现网状态）
    site = get_site_setting()
    site.site_name = "恢复后的现网值"
    db.session.commit()

    _create_legacy_site_config()
    _migrate_site_config_split()

    assert get_site_setting().site_name == "迁移前站点"


def test_split_migration_tolerates_very_old_schema(app, db):
    """v1.0 老库只有 site_name/favicon 两列：缺列取默认值,迁移不报错。"""
    with db.engine.begin() as conn:
        conn.execute(db.text("DROP TABLE IF EXISTS site_config"))
        conn.execute(db.text("CREATE TABLE site_config (id INTEGER PRIMARY KEY, site_name VARCHAR(100))"))
        conn.execute(db.text("INSERT INTO site_config (id, site_name) VALUES (5, '远古站点')"))

    _migrate_site_config_split()

    assert not _table_exists("site_config")
    site = get_site_setting()
    assert site.site_name == "远古站点"
    assert site.bg_style == "bg1"  # 缺列默认值
    assert site.comments_enabled is True
    mail = get_mail_setting()
    assert mail.mail_port == 587
    assert mail.mail_use_tls is True


def test_split_migration_keeps_legacy_table_on_copy_failure(app, db):
    """复制失败（如新表意外缺失）时旧表必须原样保留,下次启动可重试。"""
    _create_legacy_site_config()
    with db.engine.begin() as conn:
        conn.execute(db.text("DROP TABLE site_setting"))

    _migrate_site_config_split()

    assert _table_exists("site_config")


# ── 单行访问器：id≠1 历史库兼容（v1.3.5 修复的坑在拆表后继续成立） ──
def _replace_with_single_row(model, **fields):
    db.session.execute(db.delete(model))
    row = model(**fields)
    db.session.add(row)
    db.session.commit()
    return row


def test_single_row_accessors_read_the_row_with_non_default_id(app, db):
    _replace_with_single_row(SiteSetting, id=42, site_name="唯一站点行", bg_style="bg7")
    _replace_with_single_row(AboutProfile, id=7, about_nickname="昵称X")
    _replace_with_single_row(MailSetting, id=9, mail_host="smtp.x.com")

    assert get_site_setting().id == 42
    assert get_about_profile().id == 7
    assert get_mail_setting().id == 9

    ctx = fetch_global_context()
    assert ctx["site_name"] == "唯一站点行"
    assert ctx["site_bg_style"] == "bg7"
    assert ctx["about_nickname"] == "昵称X"


def test_get_or_create_never_creates_a_second_row(app, db):
    _replace_with_single_row(SiteSetting, id=13, site_name="既有行")

    assert get_or_create_site_setting().id == 13
    assert get_or_create_mail_setting() is not None
    assert get_or_create_about_profile() is not None
    for model in (SiteSetting, MailSetting, AboutProfile):
        assert db.session.scalar(db.select(db.func.count(model.id))) == 1


def test_get_or_create_creates_default_rows_when_missing(app, db):
    for model in (SiteSetting, MailSetting, AboutProfile):
        db.session.execute(db.delete(model))
    db.session.commit()

    assert get_or_create_site_setting().id == 1
    assert get_or_create_site_setting().site_name == "My Blog"
    assert get_or_create_mail_setting().id == 1
    assert get_or_create_about_profile().id == 1
