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
import re
from collections.abc import Callable

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
    _migrate_schema_version()
    _migrate_admin()
    _migrate_article()
    _migrate_banner()
    _migrate_rate_limit()
    _migrate_login_attempt()
    # 注意:site_config → 三表拆分这类「带数据搬迁」的迁移不在这里直调,
    # 由版本化迁移框架（run_schema_migrations / SCHEMA_VERSION）驱动,
    # 保证启动自动执行与后台「迁移数据库」手动触发走同一条路径。


def _migrate_schema_version():
    """schema_version v1（开发期单行 id 主键）→ v2 履历表（version 主键、含 note）。

    v1 结构只存在于 v1.3.6 开发期,从未随正式版交付;此迁移仅为开发机老库
    平滑过渡:读出最新戳记 → 整表重建 → 回写。整数戳记经 _LEGACY_INT_VERSIONS
    归一化为真实发布号。
    """
    try:
        inspector = db.inspect(db.engine)
        if "schema_version" not in inspector.get_table_names():
            return
        cols = {c["name"] for c in inspector.get_columns("schema_version")}
        if "id" not in cols and "note" in cols:
            return  # 已是 v2 履历结构
        # 注:create_all 先于本函数执行,但旧表已存在时 create_all 会跳过,
        # 所以走到这里时拿的一定是 v1 旧结构,可安全重建。
        # 表改名语法分引擎:MySQL 用 RENAME TABLE,SQLite 用 ALTER TABLE ... RENAME TO。
        with db.engine.begin() as conn:
            old_rows = conn.execute(db.text("SELECT version, applied_time FROM schema_version ORDER BY id ASC")).all()
            if db.engine.dialect.name == "mysql":
                conn.execute(db.text("RENAME TABLE schema_version TO schema_version_v1_legacy"))
            else:
                conn.execute(db.text("ALTER TABLE schema_version RENAME TO schema_version_v1_legacy"))
        db.metadata.tables["schema_version"].create(db.engine)
        ver = None
        with db.engine.begin() as conn:
            if old_rows:
                ver = str(old_rows[-1][0])
                if ver.isdigit():
                    ver = _LEGACY_INT_VERSIONS.get(int(ver), ver)
                conn.execute(
                    db.text("INSERT INTO schema_version (version, applied_time, note) VALUES (:v, :t, :n)"),
                    {"v": ver, "t": old_rows[-1][1] or "", "n": "自开发期单行结构重建"},
                )
            conn.execute(db.text("DROP TABLE schema_version_v1_legacy"))
        log.info("schema_version 已由开发期单行结构重建为履历表(%s)", f"v{ver}" if ver else "无戳记")
    except Exception as e:
        log.warning("schema_version 结构迁移失败,可手动重建: %s", e)


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
    """轻量迁移：为旧版 banner 表补齐 is_active（撤回/下架）/ update_time 列（幂等）。

    新装环境表结构已包含该列,直接跳过；旧库通过 ALTER TABLE 追加,
    避免老数据迁移 SQLite/MySQL 报错。
    """
    try:
        inspector = db.inspect(db.engine)
        if "banner" not in inspector.get_table_names():
            return
        cols = {c["name"] for c in inspector.get_columns("banner")}
        with db.engine.begin() as conn:
            if "is_active" not in cols:
                conn.execute(db.text("ALTER TABLE banner ADD COLUMN is_active BOOLEAN NOT NULL DEFAULT 1"))
            if "update_time" not in cols:
                conn.execute(db.text("ALTER TABLE banner ADD COLUMN update_time VARCHAR(50) NULL"))
    except Exception as e:
        log.warning("banner 列迁移失败,可手动执行 ALTER TABLE: %s", e)


def _migrate_login_attempt():
    """轻量迁移：为旧版 login_attempt 表补齐 update_time 列（幂等）。

    update_time = 最近一次登录失败时间,供账户安全页可视化排查爆破尝试。
    """
    try:
        inspector = db.inspect(db.engine)
        if "login_attempt" not in inspector.get_table_names():
            return
        cols = {c["name"] for c in inspector.get_columns("login_attempt")}
        if "update_time" not in cols:
            with db.engine.begin() as conn:
                conn.execute(db.text("ALTER TABLE login_attempt ADD COLUMN update_time VARCHAR(50) NULL"))
    except Exception as e:
        log.warning("login_attempt update_time 列迁移失败,可手动执行 ALTER TABLE: %s", e)


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
    1. 读旧行（SELECT）、复制（INSERT）、行数校验与 DROP 旧表全部在**同一条
       连接/事务**里顺序完成——绝不跨连接读写。若用 db.session 读旧行、engine
       另一连接 DROP，MySQL 下会话未提交事务会持有 site_config 的共享 MDL，
       DROP 需要排他 MDL，会阻塞到 lock_wait_timeout 才失败；
    2. 校验通过（三表各恰好一行）后才执行 DROP —— MySQL 的 DDL 会隐式提交、
       无法与 DML 同事务，因此「先校验后删」是该引擎下最接近原子性的做法；
    3. 任何失败都**向上抛出**（不吞异常）：由版本化迁移框架负责「不戳记、
       下次启动/手动触发重试」。若在这里吞掉异常，run_schema_migrations 仍会
       把该版本戳成「已应用」，失败就再也不会重试，用户配置静默丢失；
    4. 旧库可能缺列（v1.1.x 及以前没有 bg/about/mail 列）：缺列取默认值，
       不再像旧迁移那样逐列 ALTER 后复制。
    """
    inspector = db.inspect(db.engine)
    if "site_config" not in inspector.get_table_names():
        return  # 新库或已完成迁移
    old_cols = {c["name"] for c in inspector.get_columns("site_config")}

    def _int_or(raw, default):
        """旧库 mail_port 可能是空串/非数字（极老 VARCHAR schema）：转 int 失败回退默认。"""
        try:
            return int(raw)
        except (TypeError, ValueError):
            return default

    with db.engine.begin() as conn:
        row = conn.execute(db.text("SELECT * FROM site_config ORDER BY id LIMIT 1")).mappings().first()
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
                    "mail_port": _int_or(val("mail_port", 587), 587),
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


# ── Schema 版本化迁移框架（v1.3.6 引入） ────────────────────
# schema 版本一律使用真实发布号（如 "1.3.6"）,不用 1、2 这类内部序号——
# 日志和后台「迁移数据库」页所见即发布版本,排查时无需再查对照表。
# 仅当某次发布包含「需迁移」的 schema 变更时才操作:
# 1. 把迁移函数登记进 _SCHEMA_MIGRATIONS,键为该发布的版本号;
# 2. SCHEMA_VERSION 升为本发布号;
# 3. 同步 MySQL/init.sql（新装环境直接建最新 schema）。
# 不含 schema 变更的发布（如纯补丁 1.3.7）不动 SCHEMA_VERSION——版本戳记
# 停在最近一次 schema 发布号即可。
# 列级兼容（老库补列/补索引,无数据搬迁）仍走 init_db 里的幂等 _migrate_*。
SCHEMA_VERSION = "1.3.6"

# 版本管理首次上线时,无版本行的老库所处的基线:site_config 单表时代
# 的最后一个发布号（该时代的库都能在 _SCHEMA_MIGRATIONS 里找到出路）。
SCHEMA_VERSION_BASELINE = "1.3.5"

# 发布号 -> (说明, 迁移函数)。迁移函数必须幂等、失败抛异常,由框架负责戳记。
_SCHEMA_MIGRATIONS: dict[str, tuple[str, Callable[[], None]]] = {
    "1.3.6": ("站点配置表拆分:site_config → site_setting / mail_setting / about_profile", _migrate_site_config_split),
}

# 开发期本框架曾短暂使用内部整数序号（未随任何发布交付）;老开发库里的
# 整数行读取时映射为真实发布号,正式环境不会遇到这些值。
_LEGACY_INT_VERSIONS = {1: SCHEMA_VERSION_BASELINE, 2: "1.3.6"}


def _version_key(version: str) -> tuple[int, ...]:
    """ "1.3.6" → (1, 3, 6):把发布号转为可比较的元组。

    容忍 "v" 前缀;段内取前导数字（如 "6rc1" → 6）,无数字按 0。
    """
    parts = []
    for seg in str(version).strip().lstrip("vV").split("."):
        m = re.match(r"\d+", seg)
        parts.append(int(m.group()) if m else 0)
    return tuple(parts)


def schema_version_cmp(a: str, b: str) -> int:
    """比较两个发布号:a 较新 → 1,相等 → 0,a 较旧 → -1。段数不足按 0 补齐。"""
    ka, kb = list(_version_key(a)), list(_version_key(b))
    n = max(len(ka), len(kb))
    ka.extend([0] * (n - len(ka)))
    kb.extend([0] * (n - len(kb)))
    return (ka > kb) - (ka < kb)


def get_schema_version() -> str | None:
    """读取数据库当前 schema 版本 = 履历表中语义化最高的一行;无行返回 None。

    「最高」按语义化比较（_version_key）而非字典序——"1.3.10" > "1.3.6"。
    """
    from app.models import SchemaVersion

    inspector = db.inspect(db.engine)
    if "schema_version" not in inspector.get_table_names():
        return None
    versions = [str(r[0]) for r in db.session.execute(db.select(SchemaVersion.version)).all()]
    if not versions:
        return None
    max_ver = max(versions, key=_version_key)
    # 兼容本框架开发期写入的内部整数序号（仅老开发库可能出现,
    # 含 SQLite TEXT 亲和列把 int 读成 "2" 的情况）
    return _LEGACY_INT_VERSIONS.get(int(max_ver), max_ver) if max_ver.isdigit() else max_ver


def _stamp_schema_version(version: str, note: str = "") -> None:
    """向履历表幂等戳记一行（主键 version;同版本重复戳记只刷新时间/说明）。

    多 worker 并发戳同一行时以内置 IntegrityError 兜底:后提交者回滚,
    以库里的为准——两份戳记语义等价,无所谓谁赢。
    """
    from datetime import datetime

    from app.models import SchemaVersion

    try:
        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        inspector = db.inspect(db.engine)
        if "schema_version" not in inspector.get_table_names():
            from app import models  # noqa: F401

            SchemaVersion.__table__.create(db.engine)
        row = db.session.get(SchemaVersion, version)
        if row is None:
            db.session.add(SchemaVersion(version=version, applied_time=now, note=note))
        else:
            row.applied_time = now  # type: ignore[assignment]
            row.note = note  # type: ignore[assignment]
        db.session.commit()
    except IntegrityError:
        db.session.rollback()


def sync_schema_version() -> str | None:
    """确保版本行存在并返回数据库当前 schema 版本（发布号;无版本行时推断初始值）。

    版本管理首次上线（库里没有 schema_version 行）时的推断：
    - 存在旧 site_config 表 → 单表时代基线（SCHEMA_VERSION_BASELINE,有待拆分迁移）;
    - 不存在 → 全新库（create_all / init.sql 已直接建出当前 schema）→ SCHEMA_VERSION。
    查询异常时返回 None,由调用方决定兜底（启动流程按「跳过本步」处理）。
    """

    try:
        current = get_schema_version()
    except Exception as e:
        log.warning("sync_schema_version: 读取失败: %s", e)
        return None
    if current is not None:
        return current
    inspector = db.inspect(db.engine)
    initial = SCHEMA_VERSION_BASELINE if "site_config" in inspector.get_table_names() else SCHEMA_VERSION
    _stamp_schema_version(initial, "版本管理上线时推断的初始版本")
    log.info("schema 版本管理初始化: 数据库版本 v%s,程序版本 v%s", initial, SCHEMA_VERSION)
    return initial


def pending_schema_migrations(current: str | None = None, quiet: bool = False) -> list[tuple[str, str]]:
    """待应用的迁移列表 [(发布号, 说明), ...],按发布号升序。

    程序版本 **大于** 数据库版本（数据库比代码旧）才有待应用迁移;
    数据库版本高于程序（代码被降级）时返回空并告警——迁移永远只把旧库
    往前带,不用旧代码的迁移逻辑去碰比它新的库。
    quiet=True 抑制告警日志（维护闸门每次请求都重查,避免刷屏）。
    """
    if current is None:
        current = sync_schema_version()
    if current is None:
        return []
    if schema_version_cmp(current, SCHEMA_VERSION) > 0:
        if not quiet:
            log.warning("数据库 schema 版本 (v%s) 高于程序版本 (v%s),请先升级程序,跳过迁移", current, SCHEMA_VERSION)
        return []
    cur, target = _version_key(current), _version_key(SCHEMA_VERSION)
    return [
        (v, desc)
        for v, (desc, _) in sorted(_SCHEMA_MIGRATIONS.items(), key=lambda item: _version_key(item[0]))
        if cur < _version_key(v) <= target
    ]


_MIGRATION_LOCK_NAME = "microblog_schema_migration"


def _acquire_migration_lock(timeout: int = 60):
    """MySQL 命名锁,防止多 worker 并发启动 / 手动与自动迁移同时执行。

    GET_LOCK 是连接级锁:持锁期间该连接不归还连接池,RELEASE_LOCK 或连接
    断开（进程崩溃）自动释放。返回持有锁的连接,调用方须在 finally 中传给
    _release_migration_lock。非 MySQL（测试 SQLite,单进程）无此原语,返回 None。
    取锁超时抛 RuntimeError,由调用方决定跳过或向用户报错。
    """
    if db.engine.dialect.name != "mysql":
        return None
    conn = db.engine.connect()
    acquired = conn.execute(
        db.text("SELECT GET_LOCK(:name, :timeout)"),
        {"name": _MIGRATION_LOCK_NAME, "timeout": timeout},
    ).scalar()
    if acquired != 1:
        conn.close()
        raise RuntimeError(f"schema 迁移锁 {timeout}s 内未获取,可能有另一迁移正在进行")
    return conn


def _release_migration_lock(conn) -> None:
    try:
        conn.execute(db.text("SELECT RELEASE_LOCK(:name)"), {"name": _MIGRATION_LOCK_NAME})
    except Exception:
        log.warning("schema 迁移锁释放失败(连接回收时也会自动释放)", exc_info=True)
    finally:
        conn.close()


def run_schema_migrations() -> list[tuple[str, str]]:
    """执行所有待应用的迁移并逐级戳记;启动初始化与后台「迁移数据库」共用此入口。

    触发条件（启动自动 / 后台手动同一函数）:程序 SCHEMA_VERSION **大于** 数据库
    schema 版本。每个迁移执行成功后立刻把版本戳到该迁移的发布号（履历表追一行,
    说明随戳记入档）——中途失败时已完成的迁移不会重复执行,失败的迁移下次
    启动/手动触发时重试。返回本次实际应用了的迁移列表。

    MySQL 下全程持有命名锁（_acquire_migration_lock）:多 worker 并发启动时
    只有抢到锁的 worker 真正执行,其余超时后由启动链 catch 记 warning 跳过。
    """
    lock_conn = _acquire_migration_lock()
    try:
        applied: list[tuple[str, str]] = []
        for version, desc in pending_schema_migrations():
            log.info("应用 schema 迁移 v%s: %s", version, desc)
            _SCHEMA_MIGRATIONS[version][1]()
            _stamp_schema_version(version, desc)
            applied.append((version, desc))
        return applied
    finally:
        if lock_conn is not None:
            _release_migration_lock(lock_conn)


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
