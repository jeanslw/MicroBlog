"""数据库恢复的互斥与安全性回归。

- **跨进程锁**：模块级 ``threading.Lock`` 只在单个 worker 内有效，gunicorn -w 4
  时两个恢复请求会真正并行执行（MySQL 的 DDL 交错、SQLite 同时改写同一个文件），
  直接损坏库表，因此必须再加跨进程锁文件；
- **残留锁**（持锁进程被 kill -9）：超过 1 小时视为过期，可被接管，避免恢复功能
  被永久锁死；
- **SQLite 恢复**：先写临时文件 → 校验（integrity_check + admin 表有数据）→
  ``os.replace`` 原子替换。校验不通过的备份绝不能覆盖线上库。
"""

import os
import sqlite3
import time

import pytest

from app.admin import routes as admin_routes


@pytest.fixture(autouse=True)
def _release_locks():
    """恢复锁状态是模块级变量：用例前后都要清干净，避免相互影响。"""
    admin_routes._release_restore_file_lock()
    yield
    admin_routes._release_restore_file_lock()


def _lock_path():
    return os.path.join(admin_routes._backup_dir(), ".restore.lock")


def _call(app, func, *args, **kwargs):
    """恢复相关函数用 flask_babel 的 _() 生成错误消息，需要请求上下文。

    生产路径（HTTP 请求内）天然具备；测试里显式构造，避免断言到
    「Working outside of request context」这种与被测逻辑无关的异常。
    """
    with app.test_request_context():
        return func(*args, **kwargs)


def _make_sqlite_dump(path, rows=1):
    """生成一个结构合法、admin 表有数据的 SQLite 库文件，返回其内容 bytes。"""
    conn = sqlite3.connect(path)
    conn.execute("CREATE TABLE admin (id INTEGER PRIMARY KEY, username TEXT, password TEXT)")
    for i in range(rows):
        conn.execute("INSERT INTO admin (username, password) VALUES (?, ?)", (f"admin{i}", "x"))
    conn.commit()
    conn.close()
    data = path.read_bytes()
    os.remove(path)
    return data


def test_file_lock_blocks_concurrent_restore(app):
    """已有恢复进行中时，第二个请求必须被拒绝（跨进程生效）。"""
    assert admin_routes._acquire_restore_file_lock() is True
    assert os.path.isfile(_lock_path())
    # 同一进程重复获取等价于「另一个 worker 正在恢复」：必须失败
    assert admin_routes._acquire_restore_file_lock() is False
    admin_routes._release_restore_file_lock()
    assert not os.path.exists(_lock_path())


def test_fresh_foreign_lock_is_respected(app):
    with open(_lock_path(), "w", encoding="utf-8") as f:
        f.write("999999")  # 另一个进程刚留下的锁
    assert admin_routes._acquire_restore_file_lock() is False


def test_stale_lock_is_taken_over(app):
    """被 kill -9 的进程留下的锁不能永远锁死恢复功能。"""
    with open(_lock_path(), "w", encoding="utf-8") as f:
        f.write("999999")
    old = time.time() - admin_routes._RESTORE_LOCK_STALE_SECONDS - 60
    os.utime(_lock_path(), (old, old))
    assert admin_routes._acquire_restore_file_lock() is True


def test_non_file_sqlite_database_is_rejected(app):
    """内存库没有可替换的文件：必须给出可读错误，而不是写到其它路径。"""
    assert admin_routes._sqlite_db_path() is None
    with pytest.raises(RuntimeError, match="SQLite"):
        _call(app, admin_routes._restore_sqlite_database, b"SQLite format 3\x00")


def test_corrupt_backup_never_touches_live_database(app, tmp_path, monkeypatch):
    """损坏的备份必须在替换前被拦下（回归：曾经会直接覆盖线上库）。"""
    live = tmp_path / "blog.db"
    live.write_bytes(_make_sqlite_dump(tmp_path / "old.db"))
    before = live.read_bytes()
    monkeypatch.setattr(admin_routes, "_sqlite_db_path", lambda: str(live))

    with pytest.raises(RuntimeError, match="有效的 SQLite"):
        _call(app, admin_routes._restore_sqlite_database, b"this is not a sqlite database")

    assert live.read_bytes() == before, "校验失败时线上库必须保持原样"
    assert not list(tmp_path.glob("*.restore-*.tmp")), "临时文件必须清理干净"


def test_backup_without_admin_table_is_rejected(app, tmp_path, monkeypatch):
    """缺 admin 表的库不是本站备份：拒绝，避免恢复后无法登录后台。"""
    empty = tmp_path / "other.db"
    conn = sqlite3.connect(empty)
    conn.execute("CREATE TABLE article (id INTEGER PRIMARY KEY)")
    conn.commit()
    conn.close()
    payload = empty.read_bytes()

    live = tmp_path / "blog.db"
    live.write_bytes(_make_sqlite_dump(tmp_path / "old.db"))
    before = live.read_bytes()
    monkeypatch.setattr(admin_routes, "_sqlite_db_path", lambda: str(live))

    with pytest.raises(RuntimeError, match="admin"):
        _call(app, admin_routes._restore_sqlite_database, payload)
    assert live.read_bytes() == before


def test_valid_backup_replaces_live_database_atomically(app, tmp_path, monkeypatch):
    live = tmp_path / "blog.db"
    live.write_bytes(_make_sqlite_dump(tmp_path / "old.db", rows=1))
    payload = _make_sqlite_dump(tmp_path / "new.db", rows=3)
    monkeypatch.setattr(admin_routes, "_sqlite_db_path", lambda: str(live))
    # 单进程环境无需重启（POSIX 下 gunicorn 才会收到 SIGHUP）
    monkeypatch.setattr(admin_routes, "_request_worker_recycle", lambda: True)

    restart_needed = _call(app, admin_routes._restore_sqlite_database, payload)

    assert live.read_bytes() == payload
    assert restart_needed is False
    assert not list(tmp_path.glob("*.restore-*.tmp"))


def test_verify_accepts_valid_file_and_rejects_empty_admin_table(app, tmp_path):
    good = tmp_path / "good.db"
    good.write_bytes(_make_sqlite_dump(tmp_path / "src.db", rows=1))
    _call(app, admin_routes._verify_sqlite_backup_file, str(good))  # 不抛异常即通过

    empty_admin = tmp_path / "empty_admin.db"
    conn = sqlite3.connect(empty_admin)
    conn.execute("CREATE TABLE admin (id INTEGER PRIMARY KEY, username TEXT, password TEXT)")
    conn.commit()
    conn.close()
    with pytest.raises(RuntimeError, match="admin"):
        _call(app, admin_routes._verify_sqlite_backup_file, str(empty_admin))
