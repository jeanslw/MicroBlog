"""数据库初始化工具。

原 db.py 提供裸 SQL 连接管理 + 自建表 + DictCursor 适配层,
重构后由 Flask-SQLAlchemy 统一负责连接池、ORM、schema 同步。
本模块仅保留：
- init_db(): 创建所有表 + 轻量幂等迁移
- ensure_admin_exists(): 初始化管理员
- ensure_default_settings(): 初始化三张单行配置表（site_setting/mail_setting/about_profile）
- get_site_setting / get_mail_setting / get_about_profile: 统一读取三张单行配置表
- get_or_create_*: 读取,缺失时创建默认行（后台各设置页使用）

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
    _migrate_site_config_split()
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


def _migrate_site_config_split():
    """v1.3.6：site_config 单表拆分为 site_setting / mail_setting / about_profile（幂等）。

    触发场景（检测到 site_config 表存在即执行）：
    - 旧库升级：v1.3.5 及以前的单表 site_config 拆到三张新表；
    - 恢复旧备份：SQLite 文件替换 / MySQL dump 导入把库变回旧 schema 后，
      gunicorn SIGHUP 重启时 create_all 重建新表，本函数再拆一次。
      此时旧行是用户明确要恢复的权威状态，故**覆盖**新表可能残留的数据。

    顺序保证：init_db 先 create_all（新表此时已存在）再跑本迁移；随后
    ensure_default_settings 只在对应表为空时补默认行。

    安全设计（用户决策：迁移后立即 DROP 旧表）：
    1. 复制（INSERT）与行数校验在同一个 DML 事务里完成；
    2. 校验通过（三表各恰好一行）后才执行 DROP —— MySQL 的 DDL 会隐式提交、
       无法与 DML 同事务，因此「先校验后删」是该引擎下最接近原子性的做法；
       校验失败则抛异常回滚，旧表原样保留，下次启动重试；
    3. 旧库可能缺列（v1.1.x 及以前没有 bg/about/mail 列）：缺列取默认值，
       不再像旧迁移那样逐列 ALTER 后复制。
    """
    try:
        inspector = db.inspect(db.engine)
        if "site_config" not in inspector.get_table_names():
            return  # 新库或已完成迁移
        old_cols = {c["name"] for c in inspector.get_columns("site_config")}
        row = db.session.execute(db.text("SELECT * FROM site_config ORDER BY id LIMIT 1")).mappings().first()

        with db.engine.begin() as conn:
            if row is not None:
                # 缺列取默认值：老库可能没有 v1.2+ 新增的列
                def val(col, default):
                    v = row[col] if col in old_cols else default
                    return default if v is None else v

                conn.execute(db.text("DELETE FROM site_setting"))
                conn.execute(db.text("DELETE FROM mail_setting"))
                conn.execute(db.text("DELETE FROM about_profile"))
                conn.execute(
                    db.text(
                        "INSERT INTO site_setting "
                        "(id, site_name, favicon_path, logo_path, bg_style, bg_custom, comments_enabled, sidebar_style) "
                        "VALUES (1, :site_name, :favicon_path, :logo_path, :bg_style, :bg_custom, "
                        ":comments_enabled, :sidebar_style)"
                    ),
                    {
                        "site_name": val("site_name", "My Blog"),
                        "favicon_path": val("favicon_path", "static/favicon.ico"),
                        "logo_path": val("logo_path", ""),
                        "bg_style": val("bg_style", "bg1"),
                        "bg_custom": val("bg_custom", ""),
                        "comments_enabled": 1 if val("comments_enabled", True) else 0,
                        "sidebar_style": val("sidebar_style", "book"),
                    },
                )
                conn.execute(
                    db.text(
                        "INSERT INTO mail_setting "
                        "(id, mail_host, mail_port, mail_user, mail_password, mail_from, mail_use_ssl, mail_use_tls) "
                        "VALUES (1, :mail_host, :mail_port, :mail_user, :mail_password, :mail_from, "
                        ":mail_use_ssl, :mail_use_tls)"
                    ),
                    {
                        "mail_host": val("mail_host", ""),
                        "mail_port": int(val("mail_port", 587)),
                        "mail_user": val("mail_user", ""),
                        "mail_password": val("mail_password", ""),
                        "mail_from": val("mail_from", ""),
                        "mail_use_ssl": 1 if val("mail_use_ssl", False) else 0,
                        "mail_use_tls": 1 if val("mail_use_tls", True) else 0,
                    },
                )
                conn.execute(
                    db.text(
                        "INSERT INTO about_profile "
                        "(id, about_avatar, about_bio, about_email, about_github, about_homepage, about_nickname) "
                        "VALUES (1, :about_avatar, :about_bio, :about_email, :about_github, "
                        ":about_homepage, :about_nickname)"
                    ),
                    {
                        "about_avatar": val("about_avatar", ""),
                        "about_bio": val("about_bio", ""),
                        "about_email": val("about_email", ""),
                        "about_github": val("about_github", ""),
                        "about_homepage": val("about_homepage", ""),
                        "about_nickname": val("about_nickname", ""),
                    },
                )
                # 校验：三张新表各恰好一行，任何异常整体回滚（旧表保留,下次启动重试）
                for table in ("site_setting", "mail_setting", "about_profile"):
                    cnt = conn.execute(db.text(f"SELECT COUNT(*) FROM {table}")).scalar()
                    if cnt != 1:
                        raise RuntimeError(f"{table} 迁移校验失败: 期望 1 行,实际 {cnt} 行")
            # 旧行为空也直接删空表；校验通过后 DROP 旧表
            conn.execute(db.text("DROP TABLE site_config"))
        log.info("site_config 已拆分迁移至 site_setting / mail_setting / about_profile,旧表已删除")
    except Exception as e:
        log.warning("site_config 拆分迁移失败,旧表保留待下次重试: %s", e)


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


def ensure_default_settings():
    """确保三张单行配置表（site_setting / mail_setting / about_profile）各有一行默认配置。

    迁移（_migrate_site_config_split）已填充的表不会被覆盖；新装环境
    （SQLite create_all / MySQL init.sql）在此补齐缺失的默认行。
    """
    from app.models import AboutProfile, MailSetting, SiteSetting

    for model, defaults in (
        (SiteSetting, {"site_name": "My Blog", "favicon_path": "static/favicon.ico"}),
        (MailSetting, {}),
        (AboutProfile, {}),
    ):
        try:
            cnt = db.session.scalar(db.select(db.func.count(model.id)))
        except Exception as e:
            log.warning("ensure_default_settings: 查询失败: %s", e)
            return
        if cnt == 0:
            db.session.add(model(id=1, **defaults))
            try:
                db.session.commit()
            except IntegrityError:
                # 多 worker 并发时其他进程可能已插入；复查确认后静默跳过
                db.session.rollback()
                if not db.session.scalar(db.select(db.func.count(model.id))):
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


def _get_single_row(model):
    """读取单行配置表：优先 id=1，兼容「只有一行但主键不是 1」的历史库。

    单行配置表全站只有一行。此前（site_config 时代）前台各模块用「取第一行」
    （SELECT ... LIMIT 1）读取、后台用 get(model, 1) 读取，两者在「唯一一行
    id≠1」的库上读到的不是同一行，表现为「后台改了站点名/背景，前台不生效」
    （v1.3.5 修复的坑）。拆表后三张表沿用同一读取策略，读写永远指向同一行。

    无行时返回 None；数据库异常向上抛出，由调用方决定兜底策略。
    """
    row = db.session.get(model, 1)
    if row is None:
        row = db.session.scalars(db.select(model).order_by(model.id).limit(1)).first()
    return row


def get_site_setting():
    """读取站点设置行（site_setting 表）。"""
    from app.models import SiteSetting

    return _get_single_row(SiteSetting)


def get_mail_setting():
    """读取 SMTP 邮件设置行（mail_setting 表）。"""
    from app.models import MailSetting

    return _get_single_row(MailSetting)


def get_about_profile():
    """读取「关于我」资料行（about_profile 表）。"""
    from app.models import AboutProfile

    return _get_single_row(AboutProfile)


def _get_or_create_single_row(model, **defaults):
    """读取单行配置表，缺失时创建默认行（id=1）并提交，返回该行。

    后台各设置页统一用它取行，避免每处各写一份「get(id=1) → 没有就新建」，
    也避免在「唯一行 id≠1」的库上又插入第二行配置。
    """
    row = _get_single_row(model)
    if row is not None:
        return row
    row = model(id=1, **defaults)
    db.session.add(row)
    db.session.commit()
    return row


def get_or_create_site_setting():
    """读取站点设置行，缺失时创建默认行。"""
    from app.models import SiteSetting

    return _get_or_create_single_row(SiteSetting, site_name="My Blog", favicon_path="static/favicon.ico")


def get_or_create_mail_setting():
    """读取 SMTP 邮件设置行，缺失时创建默认行。"""
    from app.models import MailSetting

    return _get_or_create_single_row(MailSetting)


def get_or_create_about_profile():
    """读取「关于我」资料行，缺失时创建默认行。"""
    from app.models import AboutProfile

    return _get_or_create_single_row(AboutProfile)
