"""数据库初始化工具。

原 db.py 提供裸 SQL 连接管理 + 自建表 + DictCursor 适配层,
重构后由 Flask-SQLAlchemy 统一负责连接池、ORM、schema 同步。
本模块仅保留：
- init_db(): 创建所有表 + 轻量幂等迁移
- ensure_admin_exists(): 初始化管理员
- ensure_site_config(): 初始化站点配置
- get_site_config() / get_or_create_site_config(): 统一读取/创建站点配置行

注：文件名从 db.py 改为 database.py，避免与 app.extensions.db 实例
在 app 包命名空间中产生属性遮蔽（module shadowing）。
"""

import os

from flask import current_app
from sqlalchemy.exc import IntegrityError, OperationalError

from app.extensions import db, log


def wait_for_database(max_wait: int = 90, interval: float = 3.0) -> None:
    """启动前等待数据库可连通（仅 MySQL 需要等待,SQLite 首次探测即成功）。

    MySQL 容器首次启动要执行初始化（30s 以上），若应用先于数据库就绪启动,
    建表/初始数据写入会一次性失败且启动期内不再重试。此处有限重试兜底，
    同时覆盖非容器直跑（waitress/gunicorn 连接本机或远程 MySQL）的场景。
    超时后抛出最后一次异常,由进程管理器（gunicorn worker 重启 / 容器重启策略）
    继续重试。
    """
    import time

    if db.engine.dialect.name != "mysql":
        return

    deadline = time.monotonic() + max_wait
    attempt = 0
    while True:
        attempt += 1
        try:
            db.session.execute(db.text("SELECT 1"))
            db.session.commit()
            if attempt > 1:
                log.info("MySQL 连接已就绪（第 %d 次探测成功）", attempt)
            return
        except Exception as e:
            db.session.rollback()
            if time.monotonic() >= deadline:
                log.error("等待 MySQL 就绪超时（%ss）: %s", max_wait, e)
                raise
            log.warning("MySQL 尚未就绪,%.0fs 后重试（第 %d 次探测）: %s", interval, attempt, e)
            time.sleep(interval)


def init_db():
    """创建所有表（已存在则跳过,幂等）。

    仅对开发/SQLite 首次启动有意义；MySQL 生产环境推荐用 init.sql + Flask-Migrate。
    多 worker（如 gunicorn -w 4）并发启动时可能抢建同一张表,
    对 "table already exists" 做一次重试（此时表已被其他 worker 建好,
    create_all 的 checkfirst 会跳过已存在的表）。
    """
    # 触发所有模型注册
    from app import models  # noqa: F401

    try:
        db.create_all()
    except OperationalError as e:
        if "already exists" not in str(e).lower():
            raise
        db.create_all()
    _migrate_admin()
    _migrate_article()
    _migrate_site_config()
    _migrate_banner()
    _migrate_rate_limit()


def _migrate_admin():
    """轻量迁移：为旧版 admin 表补齐 email 列（幂等）。"""
    try:
        inspector = db.inspect(db.engine)
        if "admin" not in inspector.get_table_names():
            return
        cols = {c["name"] for c in inspector.get_columns("admin")}
        if "email" not in cols:
            with db.engine.begin() as conn:
                conn.execute(db.text("ALTER TABLE admin ADD COLUMN email VARCHAR(200) NOT NULL DEFAULT ''"))
    except Exception as e:
        log.warning("admin email 列迁移失败,可手动执行 ALTER TABLE: %s", e)


def _migrate_article():
    """兼容旧表：为 article 补齐 is_pinned / SEO 描述 / 关键词列，避免老库首页 500。"""
    try:
        inspector = db.inspect(db.engine)
        if "article" not in inspector.get_table_names():
            return
        cols = {c["name"] for c in inspector.get_columns("article")}
        with db.engine.begin() as conn:
            if "is_pinned" not in cols:
                conn.execute(db.text("ALTER TABLE article ADD COLUMN is_pinned BOOLEAN NOT NULL DEFAULT 0"))
            if "seo_description" not in cols:
                conn.execute(db.text("ALTER TABLE article ADD COLUMN seo_description VARCHAR(300) NOT NULL DEFAULT ''"))
            if "seo_keywords" not in cols:
                conn.execute(db.text("ALTER TABLE article ADD COLUMN seo_keywords VARCHAR(300) NOT NULL DEFAULT ''"))
    except Exception as e:
        log.warning("article 列迁移失败,可手动执行 ALTER TABLE: %s", e)


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
            # 「关于我」字段（v1.4.0 新增）
            if "about_avatar" not in cols:
                conn.execute(db.text("ALTER TABLE site_config ADD COLUMN about_avatar VARCHAR(500) DEFAULT ''"))
            if "about_bio" not in cols:
                conn.execute(db.text("ALTER TABLE site_config ADD COLUMN about_bio TEXT"))
            if "about_email" not in cols:
                conn.execute(db.text("ALTER TABLE site_config ADD COLUMN about_email VARCHAR(200) DEFAULT ''"))
            if "about_github" not in cols:
                conn.execute(db.text("ALTER TABLE site_config ADD COLUMN about_github VARCHAR(200) DEFAULT ''"))
            if "about_homepage" not in cols:
                conn.execute(db.text("ALTER TABLE site_config ADD COLUMN about_homepage VARCHAR(200) DEFAULT ''"))
            if "about_nickname" not in cols:
                conn.execute(db.text("ALTER TABLE site_config ADD COLUMN about_nickname VARCHAR(100) DEFAULT ''"))
            # SMTP 邮件设置（后台配置优先于 app.env）
            if "mail_host" not in cols:
                conn.execute(db.text("ALTER TABLE site_config ADD COLUMN mail_host VARCHAR(200) DEFAULT ''"))
            if "mail_port" not in cols:
                conn.execute(db.text("ALTER TABLE site_config ADD COLUMN mail_port INTEGER DEFAULT 587"))
            if "mail_user" not in cols:
                conn.execute(db.text("ALTER TABLE site_config ADD COLUMN mail_user VARCHAR(200) DEFAULT ''"))
            if "mail_password" not in cols:
                conn.execute(db.text("ALTER TABLE site_config ADD COLUMN mail_password VARCHAR(200) DEFAULT ''"))
            if "mail_from" not in cols:
                conn.execute(db.text("ALTER TABLE site_config ADD COLUMN mail_from VARCHAR(200) DEFAULT ''"))
            if "mail_use_ssl" not in cols:
                conn.execute(db.text("ALTER TABLE site_config ADD COLUMN mail_use_ssl BOOLEAN NOT NULL DEFAULT 0"))
            if "mail_use_tls" not in cols:
                conn.execute(db.text("ALTER TABLE site_config ADD COLUMN mail_use_tls BOOLEAN NOT NULL DEFAULT 1"))
            # 评论总开关（关闭后全站禁止新评论/回复）
            if "comments_enabled" not in cols:
                conn.execute(db.text("ALTER TABLE site_config ADD COLUMN comments_enabled BOOLEAN NOT NULL DEFAULT 1"))
            # 栏目分类样式（book=书本树形 / classic=经典箭头）
            if "sidebar_style" not in cols:
                conn.execute(
                    db.text("ALTER TABLE site_config ADD COLUMN sidebar_style VARCHAR(20) NOT NULL DEFAULT 'book'")
                )
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
        # 不设置密码是完全正常的路径：首次安装通过 /admin/setup 引导页
        # 在浏览器中创建管理员（无管理员时访问任意后台路由会自动跳转）。
        # 此处仅记录说明性日志；设置密码则为无头部署（Docker/CI）自动建号。
        log.info(
            "admin 表为空且未设置 BLOG_INIT_ADMIN_PWD,跳过自动建号;"
            "请访问 /admin/setup 引导页创建管理员(或设置该环境变量后重启自动创建)。"
        )
        return

    hashed = generate_password_hash(admin_pwd)
    db.session.add(Admin(username=admin_user, password=hashed))
    try:
        db.session.commit()
    except IntegrityError:
        # gunicorn 多 worker 并发启动时,其他 worker 可能已用同名账号先一步提交
        # （username 唯一约束）。回滚后复查：确认管理员已存在即视为初始化完成,
        # 这是预期的竞争结果,不是错误；复查仍为空才说明是其它异常。
        db.session.rollback()
        existing = db.session.scalar(db.select(db.func.count(Admin.id)))
        if existing and existing > 0:
            log.info("初始管理员已由其他进程创建,跳过: %s", admin_user)
            return
        raise
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
        db.session.add(SiteConfig(site_name="My Blog", favicon_path="static/favicon.ico"))
        try:
            db.session.commit()
        except IntegrityError:
            # 多 worker 并发时其他进程可能已插入；复查确认后静默跳过
            db.session.rollback()
            if not db.session.scalar(db.select(db.func.count(SiteConfig.id))):
                raise


def _migrate_rate_limit():
    """为 rate_limit 补 (action, create_time) 复合索引（幂等）。

    限流每次请求都会按 action + 时间窗口做一次 DELETE 清理，旧库若只有
    (ip, action) 索引，清理条件里的 create_time 用不上索引，会退化为全表
    扫描；表越大每次请求越慢。新库由模型 RateLimit.__table_args__ 直接建好，
    这里兜住已有的旧库。失败只告警：缺索引不影响功能正确性。
    """
    try:
        inspector = db.inspect(db.engine)
        if "rate_limit" not in inspector.get_table_names():
            return
        names = {idx["name"] for idx in inspector.get_indexes("rate_limit")}
        if "idx_action_time" in names:
            return
        with db.engine.begin() as conn:
            conn.execute(db.text("CREATE INDEX idx_action_time ON rate_limit (action, create_time)"))
        log.info("已为 rate_limit 创建复合索引 idx_action_time(action, create_time)")
    except Exception as e:
        log.warning("rate_limit 索引迁移失败（仅影响清理性能，不影响功能）: %s", e)


def get_site_config():
    """读取站点配置行：优先 id=1，兼容「只有一行但主键不是 1」的历史库。

    站点配置全站只有一行。此前前台各模块用「取第一行」（SELECT ... LIMIT 1）
    读取、后台用 db.session.get(SiteConfig, 1) 读取，两者在「唯一一行 id≠1」
    的库上读到的不是同一行，表现为「后台改了站点名/背景，前台不生效」。
    统一走本函数后，读与写（get_or_create_site_config）永远指向同一行。

    无配置行时返回 None；数据库异常向上抛出，由调用方决定兜底策略。
    """
    from app.models import SiteConfig

    site = db.session.get(SiteConfig, 1)
    if site is None:
        site = db.session.scalars(db.select(SiteConfig).order_by(SiteConfig.id).limit(1)).first()
    return site


def get_or_create_site_config():
    """读取站点配置行，缺失时创建默认行（id=1）并提交，返回该行。

    后台各设置页统一用它取行，避免每处各写一份「get(id=1) → 没有就新建」，
    也避免在「唯一行 id≠1」的库上又插入第二行配置。
    """
    from app.models import SiteConfig

    site = get_site_config()
    if site is not None:
        return site
    site = SiteConfig(id=1, site_name="My Blog", favicon_path="static/favicon.ico")
    db.session.add(site)
    db.session.commit()
    return site
