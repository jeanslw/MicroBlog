"""数据库初始化工具。

原 db.py 提供裸 SQL 连接管理 + 自建表 + DictCursor 适配层,
重构后由 Flask-SQLAlchemy 统一负责连接池、ORM、schema 同步。
本模块仅保留：
- init_db(): 创建所有表
- ensure_admin_exists(): 初始化管理员
- ensure_site_config(): 初始化站点配置

注：文件名从 db.py 改为 database.py，避免与 app.extensions.db 实例
在 app 包命名空间中产生属性遮蔽（module shadowing）。
"""

import os
import warnings

from flask import current_app

from app.extensions import db, log


def init_db():
    """创建所有表（已存在则跳过,幂等）。

    仅对开发/SQLite 首次启动有意义；MySQL 生产环境推荐用 init.sql + Flask-Migrate。
    """
    # 触发所有模型注册
    from app import models  # noqa: F401

    db.create_all()
    _migrate_site_config()
    _migrate_banner()


def _migrate_banner():
    """轻量迁移：为旧版 banner 表补齐 is_active（撤回/下架）列（幂等）。

    新装环境表结构已包含该列,直接跳过；旧库通过 ALTER TABLE 追加,
    避免老数据迁移 SQLite/MySQL 报错。
    """
    try:
        inspector = db.inspect(db.engine)
        if "banner" not in inspector.get_table_names():
            return
        cols = {c["name"] for c in inspector.get_columns("banner")}
        if "is_active" not in cols:
            with db.engine.begin() as conn:
                conn.execute(db.text("ALTER TABLE banner ADD COLUMN is_active BOOLEAN NOT NULL DEFAULT 1"))
    except Exception as e:
        log.warning("banner is_active 列迁移失败,可手动执行 ALTER TABLE: %s", e)


def _migrate_site_config():
    """轻量迁移：为旧版 site_config 表补齐背景相关列（幂等）。

    新装环境表结构已包含新列,直接跳过；旧库（v1.1.0 及以前）通过
    ALTER TABLE 追加 bg_style / bg_custom,避免老数据迁移 SQLite/MySQL 报错。
    """
    try:
        inspector = db.inspect(db.engine)
        if "site_config" not in inspector.get_table_names():
            return
        cols = {c["name"] for c in inspector.get_columns("site_config")}
        with db.engine.begin() as conn:
            if "bg_style" not in cols:
                conn.execute(db.text("ALTER TABLE site_config ADD COLUMN bg_style VARCHAR(50) NOT NULL DEFAULT 'bg1'"))
            if "bg_custom" not in cols:
                conn.execute(db.text("ALTER TABLE site_config ADD COLUMN bg_custom VARCHAR(500) NOT NULL DEFAULT ''"))
            if "logo_path" not in cols:
                conn.execute(db.text("ALTER TABLE site_config ADD COLUMN logo_path VARCHAR(200) NOT NULL DEFAULT ''"))
    except Exception as e:
        log.warning("site_config 背景列迁移失败,可手动执行 ALTER TABLE: %s", e)


def ensure_admin_exists():
    """如果 admin 表为空且 BLOG_INIT_ADMIN_PWD 已设置,自动创建管理员。

    覆盖三种场景：
    - SQLite 首次部署（表已建但 admin 未创建）
    - MySQL 首次部署（init.sql 建表后无管理员）
    - 补建场景（之前未设密码,现在补设）
    """
    from werkzeug.security import generate_password_hash

    from app.models import Admin

    admin_user = os.environ.get("BLOG_INIT_ADMIN_USER") or current_app.config.get("INIT_ADMIN_USERNAME", "admin")
    admin_pwd = os.environ.get("BLOG_INIT_ADMIN_PWD") or current_app.config.get("INIT_ADMIN_PASSWORD", "")

    try:
        count = db.session.scalar(db.select(db.func.count(Admin.id)))
    except Exception as e:
        log.warning("ensure_admin_exists: 查询失败,可能表未建立: %s", e)
        return

    if count and count > 0:
        return  # 已有管理员

    if not admin_pwd:
        warnings.warn(
            "admin 表为空,但未设置 BLOG_INIT_ADMIN_PWD 环境变量,初始管理员未创建。请设置后重启。",
            stacklevel=2,
        )
        return

    hashed = generate_password_hash(admin_pwd)
    db.session.add(Admin(username=admin_user, password=hashed))
    db.session.commit()
    log.info("初始管理员账号已创建: %s", admin_user)


def ensure_site_config():
    """确保 site_config 表存在一行默认配置"""
    from app.models import SiteConfig

    try:
        cnt = db.session.scalar(db.select(db.func.count(SiteConfig.id)))
    except Exception as e:
        log.warning("ensure_site_config: 查询失败: %s", e)
        return
    if cnt == 0:
        db.session.add(SiteConfig(site_name="我的博客", favicon_path="static/favicon.ico"))
        db.session.commit()
