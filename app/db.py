"""
统一数据库层 —— 根据 config.DB_TYPE 自动切换 MySQL / SQLite。
所有模块通过此层访问数据库，无需关心底层实现。

用法：
    from app.db import get_db, DictCursor, IntegrityError

    db = get_db()
    cur = db.cursor(DictCursor)   # 返回 dict 行
    cur = db.cursor()              # 返回 tuple 行
"""
import os
from config import DB_TYPE

# ── 根据配置导出对应后端的符号 ──────────────────────────────

if DB_TYPE == "mysql":
    import pymysql
    import pymysql.err

    DictCursor = pymysql.cursors.DictCursor
    IntegrityError = pymysql.err.IntegrityError

elif DB_TYPE == "sqlite":
    import sqlite3

    IntegrityError = sqlite3.IntegrityError

    class DictCursor:
        """标记类 —— 传入 db.cursor() 即返回 dict 行"""
        pass

else:
    raise ValueError(f"不支持的 DB_TYPE: {DB_TYPE!r}，可选 'mysql' 或 'sqlite'")


# ── MySQL 后端 ─────────────────────────────────────────────

def _get_mysql_db():
    from config import MYSQL_HOST, MYSQL_USER, MYSQL_PWD, MYSQL_DB
    return pymysql.connect(
        host=MYSQL_HOST,
        user=MYSQL_USER,
        password=MYSQL_PWD,
        database=MYSQL_DB,
        charset="utf8mb4",
    )


# ── SQLite 后端 ────────────────────────────────────────────

def _get_sqlite_db():
    from config import SQLITE_PATH

    db_path = os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
        SQLITE_PATH,
    )
    # 确保 data 目录存在
    os.makedirs(os.path.dirname(db_path), exist_ok=True)

    raw = sqlite3.connect(db_path)
    raw.execute("PRAGMA journal_mode=WAL")
    raw.execute("PRAGMA foreign_keys=ON")
    return _SqliteConnection(raw)


class _SqliteConnection:
    """包装 sqlite3.Connection，提供与 pymysql 一致的接口"""

    def __init__(self, raw_conn):
        self._conn = raw_conn

    def cursor(self, dict_cls=None):
        cur = self._conn.cursor()
        if dict_cls is not None:
            return _SqliteDictCursor(cur)
        return _SqlitePlainCursor(cur)

    def commit(self):
        self._conn.commit()

    def close(self):
        self._conn.close()


class _SqlitePlainCursor:
    """普通游标（tuple 行），自动转换 %s → ?"""

    def __init__(self, raw_cursor):
        self._cur = raw_cursor

    def execute(self, sql, params=None):
        sql = sql.replace("%s", "?")
        if params is None:
            return self._cur.execute(sql)
        return self._cur.execute(sql, params)

    def fetchone(self):
        return self._cur.fetchone()

    def fetchall(self):
        return self._cur.fetchall()

    def close(self):
        self._cur.close()


class _SqliteDictCursor:
    """字典游标（dict 行），自动转换 %s → ?"""

    def __init__(self, raw_cursor):
        self._cur = raw_cursor
        self._cur.row_factory = sqlite3.Row

    def execute(self, sql, params=None):
        sql = sql.replace("%s", "?")
        if params is None:
            return self._cur.execute(sql)
        return self._cur.execute(sql, params)

    def fetchone(self):
        row = self._cur.fetchone()
        return dict(row) if row else None

    def fetchall(self):
        return [dict(row) for row in self._cur.fetchall()]

    def close(self):
        self._cur.close()


# ── SQLite 自动建表 ────────────────────────────────────────

_sqlite_inited = False


def _init_sqlite():
    """首次连接时自动建表并写入初始数据"""
    global _sqlite_inited
    if _sqlite_inited:
        return
    _sqlite_inited = True

    from config import SQLITE_PATH

    db_path = os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
        SQLITE_PATH,
    )
    os.makedirs(os.path.dirname(db_path), exist_ok=True)

    conn = sqlite3.connect(db_path)

    conn.executescript("""
        CREATE TABLE IF NOT EXISTS admin (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username VARCHAR(50) NOT NULL UNIQUE,
            password VARCHAR(100) NOT NULL
        );

        CREATE TABLE IF NOT EXISTS article (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            title VARCHAR(500) NOT NULL,
            content TEXT NOT NULL,
            status VARCHAR(20) DEFAULT 'draft',
            create_time VARCHAR(50),
            update_time VARCHAR(50),
            vote_num INTEGER DEFAULT 0,
            category_id INTEGER
        );

        CREATE TABLE IF NOT EXISTS category (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            cat_name VARCHAR(60) NOT NULL UNIQUE,
            tag_text VARCHAR(60) DEFAULT '',
            create_time VARCHAR(50)
        );

        CREATE TABLE IF NOT EXISTS comment (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            article_id INTEGER,
            username VARCHAR(100) DEFAULT '游客',
            content TEXT NOT NULL,
            create_time VARCHAR(50)
        );

        CREATE TABLE IF NOT EXISTS reply (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            comment_id INTEGER,
            username VARCHAR(100) DEFAULT '游客',
            content TEXT NOT NULL,
            create_time VARCHAR(50)
        );

        CREATE TABLE IF NOT EXISTS banner (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            img_path VARCHAR(200) NOT NULL,
            link_url VARCHAR(500) DEFAULT '',
            title VARCHAR(100) DEFAULT '',
            desc_text VARCHAR(200) DEFAULT '',
            sort INTEGER DEFAULT 0,
            create_time VARCHAR(50)
        );

        CREATE TABLE IF NOT EXISTS site_config (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            site_name VARCHAR(100) NOT NULL DEFAULT '我的博客',
            favicon_path VARCHAR(200) DEFAULT 'static/favicon.ico'
        );

        CREATE TABLE IF NOT EXISTS vote_log (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            article_id INTEGER,
            ip VARCHAR(100)
        );
    """)

    cur = conn.execute("SELECT COUNT(*) FROM site_config")
    if cur.fetchone()[0] == 0:
        conn.execute("INSERT INTO site_config (site_name) VALUES ('我的博客')")

    cur = conn.execute("SELECT COUNT(*) FROM admin")
    if cur.fetchone()[0] == 0:
        from werkzeug.security import generate_password_hash
        hashed = generate_password_hash("123456")
        conn.execute("INSERT INTO admin (username, password) VALUES ('admin', ?)", (hashed,))

    conn.commit()
    conn.close()


# ── 对外接口 ───────────────────────────────────────────────

def get_db():
    """获取数据库连接（根据 DB_TYPE 自动选择后端）"""
    if DB_TYPE == "mysql":
        return _get_mysql_db()
    elif DB_TYPE == "sqlite":
        _init_sqlite()
        return _get_sqlite_db()
    else:
        raise ValueError(f"不支持的 DB_TYPE: {DB_TYPE!r}")
